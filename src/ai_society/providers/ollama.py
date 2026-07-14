from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_society.cognition.embeddings import validate_embeddings
from ai_society.providers.contracts import (
    ModelDescriptor,
    ModelRequest,
    ModelResponse,
    ProviderError,
)


class OllamaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    base_url: str = Field(default="http://127.0.0.1:11434", min_length=1, max_length=512)
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
    api_key: str | None = Field(default=None, min_length=1, max_length=4_096, repr=False)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    decision_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    max_json_response_bytes: int = Field(
        default=1_048_576, ge=65_536, le=8_388_608
    )
    max_model_output_bytes: int = Field(default=65_536, ge=1_024, le=262_144)
    structured_outputs: bool = True
    max_in_flight: int = Field(default=3, ge=1, le=16)

    @model_validator(mode="after")
    def validate_endpoint(self) -> OllamaConfig:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Ollama base URL must use HTTP(S) with a host")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Ollama base URL cannot contain credentials or query data")
        if parsed.hostname not in self.allowed_hosts:
            raise ValueError("Ollama host is not in the server allowlist")
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if not loopback and parsed.scheme != "https":
            raise ValueError("non-loopback Ollama endpoints require HTTPS")
        return self


class _OllamaHttpClient:
    def __init__(self, config: OllamaConfig, client: httpx.AsyncClient | None) -> None:
        self.config = config
        self._owns_client = client is None
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        timeout = httpx.Timeout(
            timeout=config.decision_timeout_seconds,
            connect=config.connect_timeout_seconds,
        )
        self.client = client or httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )
        self._semaphore = asyncio.Semaphore(config.max_in_flight)

    async def request_json(
        self, method: str, path: str, *, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        chunks: list[bytes] = []
        try:
            async with asyncio.timeout(self.config.decision_timeout_seconds):
                async with self._semaphore:
                    async with self.client.stream(method, url, json=payload) as response:
                        if response.status_code < 200 or response.status_code >= 300:
                            raise ProviderError(
                                "ollama_http_error",
                                f"Ollama returned HTTP {response.status_code}",
                            )
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.config.max_json_response_bytes:
                                raise ProviderError(
                                    "ollama_response_too_large",
                                    "Ollama response exceeded the configured limit",
                                )
                            chunks.append(chunk)
        except ProviderError:
            raise
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderError("ollama_timeout", "Ollama request timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("ollama_transport_error", "Ollama request failed") from exc
        try:
            decoded = b"".join(chunks).decode("utf-8")
            value = json.loads(
                decoded,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    ValueError("non-finite JSON value")
                ),
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            RecursionError,
        ) as exc:
            raise ProviderError(
                "ollama_protocol_error", "Ollama returned invalid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise ProviderError(
                "ollama_protocol_error", "Ollama response must be a JSON object"
            )
        return value

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


class OllamaModelProvider:
    provider_id = "ollama"

    def __init__(
        self,
        config: OllamaConfig | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or OllamaConfig()
        self._http = _OllamaHttpClient(self.config, client)

    async def list_models(self) -> list[ModelDescriptor]:
        payload = await self._http.request_json("GET", "/api/tags")
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise ProviderError(
                "ollama_protocol_error", "Ollama model inventory is malformed"
            )
        descriptors: list[ModelDescriptor] = []
        for raw in raw_models:
            if not isinstance(raw, dict):
                raise ProviderError(
                    "ollama_protocol_error", "Ollama model entry is malformed"
                )
            name = raw.get("name") or raw.get("model")
            if not isinstance(name, str) or not 1 <= len(name) <= 128:
                raise ProviderError(
                    "ollama_protocol_error", "Ollama model name is invalid"
                )
            digest = raw.get("digest")
            size = raw.get("size")
            try:
                descriptor = ModelDescriptor(
                    provider=self.provider_id,
                    model=name,
                    display_name=name,
                    digest=digest if isinstance(digest, str) and len(digest) <= 256 else None,
                    size_bytes=(
                        size
                        if isinstance(size, int)
                        and not isinstance(size, bool)
                        and size >= 0
                        else None
                    ),
                )
            except ValidationError as exc:
                raise ProviderError(
                    "ollama_protocol_error", "Ollama model inventory is malformed"
                ) from exc
            descriptors.append(descriptor)
        descriptors.sort(key=lambda item: item.model)
        return descriptors

    async def generate(self, request: ModelRequest) -> ModelResponse:
        body: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.context_json},
            ],
            "stream": False,
            "think": False,
            "options": {
                "temperature": request.temperature_milli / 1_000,
                "num_predict": request.max_output_tokens,
            },
        }
        if self.config.structured_outputs:
            body["format"] = request.intent_schema
        payload = await self._http.request_json("POST", "/api/chat", payload=body)
        message = payload.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise ProviderError(
                "ollama_protocol_error", "Ollama chat response has no message content"
            )
        content = message["content"]
        if not 1 <= len(content.encode("utf-8")) <= self.config.max_model_output_bytes:
            raise ProviderError(
                "ollama_output_too_large", "Ollama model output exceeded the safe limit"
            )
        resolved_model = payload.get("model")
        if not isinstance(resolved_model, str) or not resolved_model:
            resolved_model = request.model
        try:
            return ModelResponse(
                content=content,
                model=resolved_model[:128],
                input_tokens=self._optional_count(
                    payload.get("prompt_eval_count"), maximum=10_000_000
                ),
                output_tokens=self._optional_count(
                    payload.get("eval_count"), maximum=10_000_000
                ),
                total_duration_ns=self._optional_count(
                    payload.get("total_duration"), maximum=10_000_000_000_000
                ),
                finish_reason=(
                    str(payload["done_reason"])[:96]
                    if payload.get("done_reason") is not None
                    else None
                ),
            )
        except ValidationError as exc:
            raise ProviderError(
                "ollama_protocol_error", "Ollama response metadata is invalid"
            ) from exc

    async def close(self) -> None:
        await self._http.close()

    @staticmethod
    def _optional_count(value: object, *, maximum: int) -> int | None:
        if value is None:
            return None
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            or value > maximum
        ):
            raise ProviderError(
                "ollama_protocol_error", "Ollama response metadata is invalid"
            )
        return value


class OllamaEmbeddingProvider:
    provider_id = "ollama"

    def __init__(
        self,
        model_id: str,
        config: OllamaConfig | None = None,
        *,
        expected_dimension: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not 1 <= len(model_id) <= 128:
            raise ValueError("embedding model id is invalid")
        self.model_id = model_id
        self.dimension = expected_dimension or 0
        self.config = config or OllamaConfig()
        self._http = _OllamaHttpClient(self.config, client)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not 1 <= len(texts) <= 64:
            raise ValueError("embedding batch size must be between 1 and 64")
        if any(not text or len(text) > 4_000 for text in texts):
            raise ValueError("embedding input is outside the safe size range")
        payload = await self._http.request_json(
            "POST", "/api/embed", payload={"model": self.model_id, "input": texts}
        )
        raw = payload.get("embeddings")
        if not isinstance(raw, list) or any(not isinstance(item, list) for item in raw):
            raise ProviderError(
                "ollama_protocol_error", "Ollama embedding response is malformed"
            )
        try:
            vectors = validate_embeddings(
                raw,
                expected_count=len(texts),
                expected_dimension=self.dimension or None,
            )
        except (TypeError, ValueError) as exc:
            raise ProviderError(
                "ollama_embedding_invalid", "Ollama embedding response is invalid"
            ) from exc
        if self.dimension == 0:
            self.dimension = len(vectors[0])
        return vectors

    async def close(self) -> None:
        await self._http.close()

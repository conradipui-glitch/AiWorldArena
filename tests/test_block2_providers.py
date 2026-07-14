import asyncio
import json
import socket

import httpx
import pytest

from ai_society.providers.contracts import ModelRequest, ProviderError
from ai_society.providers.fake import FakeModelProvider
from ai_society.providers.ollama import (
    OllamaConfig,
    OllamaEmbeddingProvider,
    OllamaModelProvider,
)


def model_request() -> ModelRequest:
    return ModelRequest(
        request_id="decision-0123456789abcdef-1",
        model="qwen-test",
        system_prompt="Return one JSON object.",
        context_json="{}",
        intent_schema={"type": "object"},
        temperature_milli=0,
        max_output_tokens=128,
    )


def test_fake_provider_is_deterministic_and_never_opens_network(monkeypatch) -> None:
    def fail_network(*_args, **_kwargs):
        raise AssertionError("network access is forbidden in fake-provider tests")

    monkeypatch.setattr(socket, "create_connection", fail_network)

    async def scenario() -> None:
        provider = FakeModelProvider()
        first = await provider.generate(model_request())
        second = await provider.generate(model_request())
        assert first == second
        assert len(provider.requests) == 2
        assert [item.model for item in await provider.list_models()] == [
            "fake-json-v1"
        ]

    asyncio.run(scenario())


def test_ollama_tags_chat_and_embed_contracts_use_bounded_nonstreaming_requests() -> None:
    seen: list[tuple[str, dict[str, object] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        seen.append((request.url.path, payload))
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "qwen-test", "digest": "sha256:abc", "size": 42}
                    ]
                },
            )
        if request.url.path == "/api/chat":
            assert payload["stream"] is False
            assert payload["think"] is False
            assert payload["format"] == {"type": "object"}
            return httpx.Response(
                200,
                json={
                    "model": "qwen-test",
                    "message": {
                        "role": "assistant",
                        "content": '{"action":"wait","reason":"safe"}',
                    },
                    "prompt_eval_count": 11,
                    "eval_count": 7,
                    "total_duration": 1234,
                    "done_reason": "stop",
                },
            )
        if request.url.path == "/api/embed":
            assert payload == {"model": "embed-test", "input": ["one", "two"]}
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0], [0.0, 1.0]]})
        return httpx.Response(404)

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        config = OllamaConfig()
        model_provider = OllamaModelProvider(config, client=client)
        embedding_provider = OllamaEmbeddingProvider(
            "embed-test", config, expected_dimension=2, client=client
        )
        try:
            models = await model_provider.list_models()
            response = await model_provider.generate(model_request())
            embeddings = await embedding_provider.embed(["one", "two"])
        finally:
            await client.aclose()
        assert models[0].model == "qwen-test"
        assert response.input_tokens == 11
        assert response.output_tokens == 7
        assert embeddings == [[1.0, 0.0], [0.0, 1.0]]
        assert [item[0] for item in seen] == ["/api/tags", "/api/chat", "/api/embed"]

    asyncio.run(scenario())


def test_ollama_errors_are_typed_and_do_not_echo_response_body() -> None:
    secret = "SECRET_PROVIDER_BODY"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=secret)

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaModelProvider(client=client)
        try:
            with pytest.raises(ProviderError) as captured:
                await provider.list_models()
        finally:
            await client.aclose()
        assert captured.value.code == "ollama_http_error"
        assert secret not in str(captured.value)

    asyncio.run(scenario())


def test_ollama_response_size_limit_is_enforced_while_streaming() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{" + b"x" * 70_000 + b"}")

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaModelProvider(
            OllamaConfig(max_json_response_bytes=65_536), client=client
        )
        try:
            with pytest.raises(ProviderError, match="configured limit") as captured:
                await provider.list_models()
        finally:
            await client.aclose()
        assert captured.value.code == "ollama_response_too_large"

    asyncio.run(scenario())


def test_ollama_total_deadline_stops_a_slow_drip_response() -> None:
    class SlowDripStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in (b'{"models":', b"[", b"]", b"}"):
                await asyncio.sleep(0.03)
                yield chunk

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=SlowDripStream())

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaModelProvider(
            OllamaConfig(decision_timeout_seconds=0.05), client=client
        )
        try:
            with pytest.raises(ProviderError) as captured:
                await provider.list_models()
        finally:
            await client.aclose()
        assert captured.value.code == "ollama_timeout"

    asyncio.run(scenario())


def test_ollama_total_deadline_includes_waiting_for_request_capacity() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("request must time out before transport dispatch")

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaModelProvider(
            OllamaConfig(decision_timeout_seconds=0.02, max_in_flight=1),
            client=client,
        )
        await provider._http._semaphore.acquire()
        try:
            with pytest.raises(ProviderError) as captured:
                await provider.list_models()
        finally:
            provider._http._semaphore.release()
            await client.aclose()
        assert captured.value.code == "ollama_timeout"

    asyncio.run(scenario())


def test_ollama_excessively_nested_json_is_a_typed_protocol_error() -> None:
    nested_json = b"[" * 10_000 + b"0" + b"]" * 10_000

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=nested_json)

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaModelProvider(client=client)
        try:
            with pytest.raises(ProviderError) as captured:
                await provider.list_models()
        finally:
            await client.aclose()
        assert captured.value.code == "ollama_protocol_error"

    asyncio.run(scenario())


def test_ollama_boolean_model_size_is_not_treated_as_an_integer() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"models": [{"name": "qwen-test", "size": True}]},
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaModelProvider(client=client)
        try:
            models = await provider.list_models()
        finally:
            await client.aclose()
        assert models[0].size_bytes is None

    asyncio.run(scenario())


def test_ollama_malformed_usage_metadata_is_a_typed_protocol_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen-test",
                "message": {
                    "role": "assistant",
                    "content": '{"action":"wait","reason":"safe"}',
                },
                "prompt_eval_count": 10_000_001,
                "eval_count": 7,
                "total_duration": 1234,
                "done_reason": "stop",
            },
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaModelProvider(client=client)
        try:
            with pytest.raises(ProviderError) as captured:
                await provider.generate(model_request())
        finally:
            await client.aclose()
        assert captured.value.code == "ollama_protocol_error"
        assert "10_000_001" not in str(captured.value)

    asyncio.run(scenario())


def test_ollama_embedding_overflow_is_a_typed_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[10**1_000]]})

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OllamaEmbeddingProvider("embed-test", client=client)
        try:
            with pytest.raises(ProviderError) as raised:
                await provider.embed(["bounded input"])
            assert raised.value.code == "ollama_embedding_invalid"
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_ollama_endpoint_is_server_allowlisted() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        OllamaConfig(base_url="http://169.254.169.254:11434")

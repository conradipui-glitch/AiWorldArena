from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from ai_society.providers.contracts import (
    ModelDescriptor,
    ModelRequest,
    ModelResponse,
    ProviderError,
)


class FakeModelProvider:
    provider_id = "fake"

    def __init__(
        self,
        outputs: Iterable[str | Exception] | None = None,
        *,
        model: str = "fake-json-v1",
    ) -> None:
        self.model = model
        self._outputs = deque(outputs or [])
        self.requests: list[ModelRequest] = []

    async def list_models(self) -> list[ModelDescriptor]:
        return [
            ModelDescriptor(
                provider=self.provider_id,
                model=self.model,
                display_name="Deterministic Fake JSON",
                digest="fake-provider-v1",
                size_bytes=0,
            )
        ]

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        output: str | Exception
        if self._outputs:
            output = self._outputs.popleft()
        else:
            output = '{"action":"wait","reason":"deterministic fake wait"}'
        if isinstance(output, ProviderError):
            raise output
        if isinstance(output, Exception):
            raise ProviderError("fake_provider_error", "fake provider failed") from output
        input_tokens = max(1, (len(request.system_prompt) + len(request.context_json)) // 4)
        output_tokens = max(1, len(output) // 4)
        return ModelResponse(
            content=output,
            model=request.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_duration_ns=1_000_000,
            finish_reason="stop",
        )

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelDescriptor(ProviderModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=160)
    digest: str | None = Field(default=None, max_length=256)
    size_bytes: int | None = Field(default=None, ge=0)


class ModelRequest(ProviderModel):
    request_id: str = Field(pattern=r"^decision-[0-9a-f]{16}-[12]$")
    model: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(min_length=1, max_length=16_000)
    context_json: str = Field(min_length=2, max_length=65_536)
    intent_schema: dict[str, object]
    temperature_milli: int = Field(ge=0, le=2_000)
    max_output_tokens: int = Field(ge=32, le=2_048)
    repair: bool = False


class ModelResponse(ProviderModel):
    content: str = Field(min_length=1, max_length=65_536)
    model: str = Field(min_length=1, max_length=128)
    input_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=10_000_000)
    total_duration_ns: int | None = Field(default=None, ge=0)
    finish_reason: str | None = Field(default=None, max_length=96)


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code[:96]
        super().__init__(message[:240])


class ModelProvider(Protocol):
    provider_id: str

    async def list_models(self) -> list[ModelDescriptor]: ...

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

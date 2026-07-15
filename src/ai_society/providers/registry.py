from __future__ import annotations

from ai_society.providers.contracts import ModelDescriptor, ModelProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider) -> None:
        provider_id = provider.provider_id
        if not provider_id or len(provider_id) > 64:
            raise ValueError("provider id is invalid")
        if provider_id in self._providers:
            raise ValueError(f"provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> ModelProvider:
        try:
            return self._providers[provider_id]
        except KeyError as exc:
            raise LookupError("provider is not registered") from exc

    async def list_models(self, provider_id: str) -> list[ModelDescriptor]:
        return await self.get(provider_id).list_models()

    async def available_bindings(self) -> set[tuple[str, str]]:
        result: set[tuple[str, str]] = set()
        for provider_id in sorted(self._providers):
            for descriptor in await self._providers[provider_id].list_models():
                result.add((provider_id, descriptor.model))
        return result

    async def validate_binding(self, provider_id: str, model: str) -> None:
        descriptors = await self.list_models(provider_id)
        if model not in {descriptor.model for descriptor in descriptors}:
            raise ValueError("model is not present in the provider inventory")

    async def check_binding(self, provider_id: str, model: str) -> None:
        await self.validate_binding(provider_id, model)
        check_access = getattr(self.get(provider_id), "check_access", None)
        if check_access is not None:
            await check_access(model)

    async def close(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "close", None)
            if close is not None:
                await close()

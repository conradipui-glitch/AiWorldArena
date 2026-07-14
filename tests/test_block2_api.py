import asyncio

from httpx import ASGITransport, AsyncClient

from ai_society.api.app import create_app
from ai_society.providers.fake import FakeModelProvider
from ai_society.providers.registry import ProviderRegistry


def test_api_lists_dynamic_provider_inventory_without_accepting_endpoint() -> None:
    async def scenario() -> None:
        providers = ProviderRegistry()
        providers.register(FakeModelProvider())
        app = create_app(provider_registry=providers)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get("/v1/providers/fake/models")
            assert response.status_code == 200
            assert response.json()["models"][0]["model"] == "fake-json-v1"
            rejected = await client.post(
                "/v1/runs",
                json={
                    "seed": 1,
                    "agents": ["A"],
                    "provider_endpoint": "http://169.254.169.254",
                },
            )
            assert rejected.status_code == 422

    asyncio.run(scenario())

def test_api_reports_unconfigured_provider_surface_without_proxying() -> None:
    async def scenario() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://testserver"
        ) as client:
            response = await client.get("/v1/providers/ollama/models")
            assert response.status_code == 503

    asyncio.run(scenario())

import asyncio

from httpx import ASGITransport, AsyncClient

from ai_society.api.app import create_app


def test_api_create_advance_and_read() -> None:
    async def scenario() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://testserver"
        ) as client:
            health = await client.get("/health")
            assert health.status_code == 200
            assert health.json()["status"] == "ok"

            created = await client.post(
                "/v1/runs",
                json={
                    "seed": 77,
                    "width": 24,
                    "height": 24,
                    "agents": ["A", "B", "C"],
                },
            )
            assert created.status_code == 201
            run_id = created.json()["run_id"]

            advanced = await client.post(
                f"/v1/runs/{run_id}/advance", json={"events": 100}
            )
            assert advanced.status_code == 200
            assert advanced.json()["processed_events"] == 100

            read = await client.get(f"/v1/runs/{run_id}")
            assert read.status_code == 200
            assert read.json()["event_digest"] == advanced.json()["event_digest"]

    asyncio.run(scenario())


def test_api_rejects_unknown_fields() -> None:
    async def scenario() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=create_app()), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/v1/runs",
                json={
                    "seed": 77,
                    "agents": ["A"],
                    "provider_endpoint": "http://169.254.169.254",
                },
            )
            assert response.status_code == 422

    asyncio.run(scenario())

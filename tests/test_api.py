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


def test_api_reopens_a_deterministic_run_without_resetting_its_history() -> None:
    async def scenario() -> None:
        app = create_app(observer_tick_seconds=0.01)
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                request = {
                    "seed": 99,
                    "width": 24,
                    "height": 24,
                    "agents": ["A", "B", "C"],
                }
                first = await client.post("/v1/runs", json=request)
                assert first.status_code == 201
                assert first.json()["reused"] is False
                run_id = first.json()["run_id"]

                listed = await client.get("/v1/runs")
                assert listed.status_code == 200
                assert listed.json()["runs"] == [
                    {
                        "run_id": run_id,
                        "seed": 99,
                        "scenario": "Свободный мир",
                        "status": "created",
                        "paused": True,
                        "speed": 1,
                        "game_minute": 0,
                        "processed_events": 0,
                    }
                ]

                advanced = await client.post(
                    f"/v1/runs/{run_id}/advance", json={"events": 3}
                )
                assert advanced.status_code == 200

                reopened = await client.post("/v1/runs", json=request)
                assert reopened.status_code == 200
                assert reopened.json()["run_id"] == run_id
                assert reopened.json()["reused"] is True
                assert reopened.json()["processed_events"] == 3

                started = await client.post(
                    f"/v1/runs/{run_id}/controls", json={"paused": False}
                )
                assert started.status_code == 200
                await asyncio.sleep(0.04)
                state = await client.get(f"/v1/runs/{run_id}/state")
                assert state.json()["state"]["processed_events"] > 3
        finally:
            await app.state.registry.shutdown()

    asyncio.run(scenario())

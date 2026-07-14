import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from ai_society.api.app import create_app


def test_observer_projection_controls_inspector_and_snapshot() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create_app(
                snapshot_root=root / "snapshots",
                cognition_root=root / "cognition",
                observer_tick_seconds=0.01,
            )
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://testserver"
                ) as client:
                    created = await client.post(
                        "/v1/runs",
                        json={"seed": 123, "agents": ["Ада", "Борин", "Сайра"]},
                    )
                    assert created.status_code == 201
                    run_id = created.json()["run_id"]

                    observer = await client.get(f"/v1/runs/{run_id}/observer")
                    assert observer.status_code == 200
                    payload = observer.json()
                    assert payload["map"]["width"] == 32
                    assert len(payload["map"]["tiles"]) == 32 * 32
                    assert payload["environment"]["weather_visual_only"] is True
                    assert payload["agents"][0]["current_action"] == "Ожидает первого решения"

                    advanced = await client.post(
                        f"/v1/runs/{run_id}/advance", json={"events": 6}
                    )
                    assert advanced.status_code == 200
                    inspector = await client.get(
                        f"/v1/runs/{run_id}/agents/agent-001/inspector"
                    )
                    assert inspector.status_code == 200
                    assert inspector.json()["memory"]
                    assert "known_map" in inspector.json()

                    rejected = await client.post(
                        f"/v1/runs/{run_id}/controls",
                        json={"paused": True, "state": {"agents": []}},
                    )
                    assert rejected.status_code == 422

                    saved = await client.post(
                        f"/v1/runs/{run_id}/snapshots", json={"name": "observer-check"}
                    )
                    assert saved.status_code == 200
                    assert saved.json()["name"] == "observer-check"
                    listed = await client.get("/v1/snapshots")
                    assert listed.json()["snapshots"] == ["observer-check"]
                    loaded = await client.post(
                        "/v1/runs/load", json={"name": "observer-check"}
                    )
                    assert loaded.status_code == 200
            finally:
                await app.state.registry.shutdown()

    asyncio.run(scenario())


def test_headless_run_continues_after_control_without_browser() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create_app(
                snapshot_root=root / "snapshots",
                cognition_root=root / "cognition",
                observer_tick_seconds=0.01,
            )
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://testserver"
                ) as client:
                    created = await client.post("/v1/runs", json={"seed": 321})
                    run_id = created.json()["run_id"]
                    started = await client.post(
                        f"/v1/runs/{run_id}/controls", json={"paused": False, "speed": 1}
                    )
                    assert started.status_code == 200
                    await asyncio.sleep(0.06)
                    state = await client.get(f"/v1/runs/{run_id}/state")
                    assert state.json()["state"]["processed_events"] > 0
            finally:
                await app.state.registry.shutdown()

    asyncio.run(scenario())


def test_read_only_websocket_reconnects_with_fresh_snapshot() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        app = create_app(
            snapshot_root=root / "snapshots",
            cognition_root=root / "cognition",
            observer_tick_seconds=0.01,
        )
        with TestClient(app) as client:
            created = client.post("/v1/runs", json={"seed": 456})
            run_id = created.json()["run_id"]
            with client.websocket_connect(f"/v1/runs/{run_id}/stream") as stream:
                initial = stream.receive_json()
                assert initial["type"] == "world_snapshot"
                stream.send_text('{"attempt":"mutate"}')
                rejected = stream.receive_json()
                assert rejected["code"] == "read_only_stream"
            with client.websocket_connect(f"/v1/runs/{run_id}/stream") as reconnected:
                repeated = reconnected.receive_json()
                assert repeated["type"] == "world_snapshot"
                assert repeated["data"]["run"]["id"] == run_id

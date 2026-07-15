import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from ai_society.api.app import create_app
from ai_society.api.observer import ObserverRunConfig, RunRegistry


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
                    saved_event_count = advanced.json()["processed_events"]
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
                    advanced_after_save = await client.post(
                        f"/v1/runs/{run_id}/advance", json={"events": 4}
                    )
                    assert advanced_after_save.status_code == 200
                    assert advanced_after_save.json()["processed_events"] > saved_event_count
                    listed = await client.get("/v1/snapshots")
                    assert listed.json()["snapshots"] == ["observer-check"]
                    loaded = await client.post(
                        "/v1/runs/load", json={"name": "observer-check"}
                    )
                    assert loaded.status_code == 200
                    restored = await client.get(f"/v1/runs/{run_id}/observer")
                    assert restored.status_code == 200
                    assert restored.json()["run"]["processed_events"] == saved_event_count
                    assert restored.json()["run"]["paused"] is True
            finally:
                await app.state.registry.shutdown()

    asyncio.run(scenario())


def test_researcher_can_spawn_visible_creature_and_trigger_logged_event() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create_app(
                snapshot_root=root / "snapshots",
                cognition_root=root / "cognition",
                experiment_root=root / "experiments",
                observer_tick_seconds=0.01,
            )
            async with app.router.lifespan_context(app):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    created = await client.post(
                        "/v1/runs",
                        json={
                            "seed": 9123,
                            "width": 16,
                            "height": 16,
                            "agents": ["Ада"],
                        },
                    )
                    run_id = created.json()["run_id"]
                    state = (await client.get(f"/v1/runs/{run_id}/state")).json()[
                        "state"
                    ]
                    occupied = {
                        (item["position"]["x"], item["position"]["y"])
                        for item in state["agents"].values()
                    }
                    tile = next(
                        item
                        for item in state["tiles"]
                        if item["terrain"] not in {"water", "rock"}
                        and (item["position"]["x"], item["position"]["y"])
                        not in occupied
                    )
                    position = tile["position"]
                    spawned = await client.post(
                        f"/v1/runs/{run_id}/agents",
                        json={
                            "name": "Серый",
                            "species": "wolf",
                            "provider": "deterministic",
                            "model": "scripted-v1",
                            "personality": "Осторожный",
                            "behavior_description": "Защищает территорию",
                            "vision_radius": 3,
                            "x": position["x"],
                            "y": position["y"],
                        },
                    )
                    assert spawned.status_code == 201
                    agent_id = spawned.json()["agent_id"]
                    inspector = (
                        await client.get(
                            f"/v1/runs/{run_id}/agents/{agent_id}/inspector"
                        )
                    ).json()
                    assert inspector["species"] == "wolf"
                    assert inspector["vision_radius"] == 3
                    assert inspector["personality"] == "Осторожный"

                    event = await client.post(
                        f"/v1/runs/{run_id}/events",
                        json={
                            "event_type": "rain",
                            "intensity": 40,
                            "duration_minutes": 90,
                        },
                    )
                    assert event.status_code == 201
                    observer = (
                        await client.get(f"/v1/runs/{run_id}/observer")
                    ).json()
                    assert observer["run"]["modified"] is True
                    assert observer["environment"]["weather"] == "Дождь"
                    assert any(
                        item["kind"] == "researcher_event_triggered"
                        for item in observer["events"]
                    )

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
                    paused = await client.post(
                        f"/v1/runs/{run_id}/controls", json={"paused": True}
                    )
                    assert paused.status_code == 200
                    count_at_pause = paused.json()["run"]["processed_events"]
                    await asyncio.sleep(0.06)
                    stopped = await client.get(f"/v1/runs/{run_id}/state")
                    assert stopped.json()["state"]["processed_events"] == count_at_pause
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


def test_observer_speed_applies_the_multiplier_only_once_per_tick() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = RunRegistry(
                snapshot_root=root / "snapshots",
                cognition_root=root / "cognition",
                tick_seconds=0.25,
            )
            acquired = await registry.acquire(
                ObserverRunConfig(
                    seed=991,
                    width=24,
                    height=24,
                    agents=["Ада", "Борин", "Сайра"],
                )
            )
            run_id = acquired.engine.state.run.run_id
            session = registry.get(run_id)
            session.paused = False
            session.speed = 3
            batches: list[int] = []
            delays: list[float] = []

            async def record_advance(_run_id: str, events: int) -> int:
                batches.append(events)
                return events

            async def stop_after_delay(delay: float) -> None:
                delays.append(delay)
                registry._closed = True

            registry.advance = record_advance  # type: ignore[method-assign]
            try:
                with patch(
                    "ai_society.api.observer.asyncio.sleep", new=stop_after_delay
                ):
                    await registry._run_loop(run_id)
                assert batches == [3]
                assert delays == [0.25]
            finally:
                await registry.shutdown()

    asyncio.run(scenario())


def test_loading_waits_for_an_in_flight_world_advance() -> None:
    async def scenario() -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = RunRegistry(
                snapshot_root=root / "snapshots",
                cognition_root=root / "cognition",
                tick_seconds=0.01,
            )
            acquired = await registry.acquire(
                ObserverRunConfig(
                    seed=992,
                    width=24,
                    height=24,
                    agents=["Ада", "Борин", "Сайра"],
                )
            )
            run_id = acquired.engine.state.run.run_id
            prior = registry.get(run_id)
            registry.save_snapshot(run_id, "before-advance")
            entered_refresh = asyncio.Event()
            allow_refresh = asyncio.Event()
            original_refresh = registry._refresh_cognition

            async def delayed_refresh(session) -> None:
                if session is prior:
                    entered_refresh.set()
                    await allow_refresh.wait()
                await original_refresh(session)

            registry._refresh_cognition = delayed_refresh  # type: ignore[method-assign]
            advance_task: asyncio.Task[int] | None = None
            load_task: asyncio.Task | None = None
            try:
                advance_task = asyncio.create_task(registry.advance(run_id, 1))
                await entered_refresh.wait()
                load_task = asyncio.create_task(registry.load_snapshot("before-advance"))
                await asyncio.sleep(0)
                assert not load_task.done()

                allow_refresh.set()
                assert await advance_task == 1
                loaded = await load_task
                assert loaded.state.processed_events == 0
                assert registry.get(run_id).engine is loaded
            finally:
                allow_refresh.set()
                pending = [
                    task
                    for task in (advance_task, load_task)
                    if task is not None and not task.done()
                ]
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                await registry.shutdown()

    asyncio.run(scenario())

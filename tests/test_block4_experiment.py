import asyncio
from collections import Counter

import pytest
from httpx import ASGITransport, AsyncClient

from ai_society.cognition.embeddings import DeterministicEmbeddingProvider
from ai_society.cognition.repository import SQLiteCognitionRepository
from ai_society.domain.enums import (
    ExperimentMode,
    ScheduledEventKind,
    WorldEventKind,
)
from ai_society.executive.layer import ExecutiveLayer
from ai_society.experiment.models import ExperimentConfig, ModelAssignment
from ai_society.experiment.persistence import (
    ExperimentBundleError,
    ExperimentBundleRepository,
    bundle_digest,
)
from ai_society.experiment.runner import ExperimentRunner, replay_bundle
from ai_society.experiment.scenario import (
    ExperimentalScriptedPolicy,
    STARTING_INVENTORY,
    create_experiment_world,
)
from ai_society.providers.fake import FakeModelProvider
from ai_society.providers.registry import ProviderRegistry
from ai_society.simulation.engine import SimulationEngine
from ai_society.api.app import create_app


def test_experiment_modes_enforce_comparable_model_assignments() -> None:
    shared = tuple(
        ModelAssignment(
            agent_id=f"agent-{index:03d}", provider="ollama", model="qwen3:8b"
        )
        for index in range(1, 4)
    )
    controlled = ExperimentConfig(
        mode=ExperimentMode.CONTROLLED, model_assignments=shared
    )
    assert controlled.mode is ExperimentMode.CONTROLLED

    with pytest.raises(ValueError, match="distinct"):
        ExperimentConfig(mode=ExperimentMode.NATURAL, model_assignments=shared)
    with pytest.raises(ValueError, match="does not accept"):
        ExperimentConfig(model_assignments=shared)


def test_controlled_mode_survives_invalid_model_output(tmp_path) -> None:
    async def scenario() -> None:
        assignments = tuple(
            ModelAssignment(
                agent_id=f"agent-{index:03d}",
                provider="fake",
                model="fake-json-v1",
            )
            for index in range(1, 4)
        )
        config = ExperimentConfig(
            seed=71,
            mode=ExperimentMode.CONTROLLED,
            model_assignments=assignments,
        )
        initial = create_experiment_world(config)
        engine = SimulationEngine(
            state=initial.model_copy(deep=True),
            policy=ExperimentalScriptedPolicy(),
        )
        providers = ProviderRegistry()
        providers.register(FakeModelProvider(["not-json", "still-not-json"]))
        with SQLiteCognitionRepository(tmp_path) as cognition:
            executive = ExecutiveLayer(
                providers=providers,
                cognition=cognition,
                embedding_provider=DeterministicEmbeddingProvider(),
            )
            runner = ExperimentRunner(
                config=config,
                initial_state=initial,
                engine=engine,
                cognition=cognition,
                executive=executive,
            )
            result = await runner.step()
            assert result is not None and result.success
            assert runner.decisions[0].fallback_code == "invalid_after_repair"
            kinds = [event.kind for event in engine.event_log.events]
            assert WorldEventKind.MODEL_OUTPUT_REJECTED in kinds
            assert WorldEventKind.MODEL_FALLBACK_USED in kinds

    asyncio.run(scenario())


def test_seven_day_experiment_exports_metrics_and_replays_exactly(tmp_path) -> None:
    async def scenario() -> None:
        config = ExperimentConfig(seed=20260715)
        initial = create_experiment_world(config)
        inventories = [agent.inventory for agent in initial.agents.values()]
        assert all(inventory == STARTING_INVENTORY for inventory in inventories)
        assert initial.processed_events == 0
        assert initial.event_queue == []

        engine = SimulationEngine(
            state=initial.model_copy(deep=True),
            policy=ExperimentalScriptedPolicy(),
        )
        assert engine.next_scheduled_kind() is ScheduledEventKind.DECISION_DUE
        runner = ExperimentRunner(
            config=config,
            initial_state=initial,
            engine=engine,
        )
        processed = await runner.run_to_completion()
        assert processed > 1_000
        bundle = runner.export_bundle()

        assert bundle.final_state.game_minute == 10_080
        assert all(agent.body.health > 0 for agent in bundle.final_state.agents.values())
        assert all(agent.knowledge.explored for agent in bundle.final_state.agents.values())
        kinds = Counter(event.kind for event in bundle.events)
        for required in (
            WorldEventKind.PROJECT_COMPLETED,
            WorldEventKind.PROJECT_REFUSED,
            WorldEventKind.RESOURCE_STORED,
            WorldEventKind.RESOURCE_TAKEN,
            WorldEventKind.OFFER_ACCEPTED,
            WorldEventKind.RESOURCE_TRANSFERRED,
            WorldEventKind.COMMITMENT_FULFILLED,
            WorldEventKind.COMMITMENT_BROKEN,
            WorldEventKind.WEATHER_CHANGED,
            WorldEventKind.WEATHER_CRISIS_STARTED,
            WorldEventKind.WEATHER_CRISIS_ENDED,
            WorldEventKind.EXPERIMENT_COMPLETED,
        ):
            assert kinds[required] >= 1
        assert bundle.metrics.duration_minutes == 10_080
        assert bundle.metrics.projects_completed == 1
        assert bundle.metrics.interventions == 0
        assert sum(item.decisions for item in bundle.metrics.agents) == len(
            bundle.decisions
        )

        repository = ExperimentBundleRepository(tmp_path / "experiments")
        saved = repository.save("acceptance", bundle)
        assert saved.is_file()
        loaded = repository.load("acceptance")
        replayed = replay_bundle(loaded)
        assert replayed.state_hash == loaded.final_state_hash
        assert replayed.event_log.digest == loaded.final_event_digest
        with pytest.raises(ExperimentBundleError, match="safe slug"):
            repository.save("../escape", bundle)
        wrong_metrics = bundle.metrics.model_copy(update={"duration_minutes": 1})
        tampered = bundle.model_copy(
            update={"metrics": wrong_metrics, "bundle_digest": "0" * 64}
        )
        tampered = tampered.model_copy(update={"bundle_digest": bundle_digest(tampered)})
        with pytest.raises(ExperimentBundleError, match="completion metrics"):
            repository.save("semantic-tamper", tampered)

    asyncio.run(scenario())


def test_observer_exposes_authoritative_block4_experiment_in_russian(tmp_path) -> None:
    async def scenario() -> None:
        app = create_app(
            snapshot_root=tmp_path / "snapshots",
            cognition_root=tmp_path / "cognition",
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                created = await client.post(
                    "/v1/runs",
                    json={
                        "seed": 20260715,
                        "width": 48,
                        "height": 48,
                        "agents": ["Ада", "Борин", "Сайра"],
                        "provider": "deterministic",
                        "model": "scripted-experiment-v1",
                    },
                )
                assert created.status_code == 201
                run_id = created.json()["run_id"]
                await client.post(f"/v1/runs/{run_id}/advance", json={"events": 12})
                observer = (await client.get(f"/v1/runs/{run_id}/observer")).json()
                assert observer["environment"]["weather_visual_only"] is False
                assert observer["environment"]["weather"] == "Ясно"
                assert observer["map"]["width"] == 48
                chronicle = " ".join(event["text"] for event in observer["events"])
                assert "совместн" in chronicle.casefold()
        finally:
            await app.state.registry.shutdown()

    asyncio.run(scenario())

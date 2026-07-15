import asyncio
import json
import shutil
from pathlib import Path
from tempfile import mkdtemp

import pytest
from httpx import ASGITransport, AsyncClient

from ai_society.api.app import create_app
from ai_society.cli import main
from ai_society.domain.intents import WaitIntent
from ai_society.experiment.models import InterventionRecord
from ai_society.experiment.persistence import bundle_digest
from ai_society.experiment.runner import ExperimentRunner
from ai_society.experiment.scenario import (
    ExperimentalScriptedPolicy,
    create_experiment_world,
)
from ai_society.experiment.models import ExperimentConfig
from ai_society.research.comparison import compare_bundles
from ai_society.research.models import ResearchArtifactKind, RunMark
from ai_society.research.persistence import ResearchArtifactError, world_contract_digest
from ai_society.research.service import ResearchService
from ai_society.simulation.engine import SimulationEngine


async def _complete_bundle(config: ExperimentConfig, initial_state=None):
    initial = (
        create_experiment_world(config)
        if initial_state is None
        else initial_state.model_copy(deep=True)
    )
    runner = ExperimentRunner(
        config=config,
        initial_state=initial,
        engine=SimulationEngine(
            state=initial.model_copy(deep=True), policy=ExperimentalScriptedPolicy()
        ),
    )
    await runner.run_to_completion()
    return runner.export_bundle()


@pytest.fixture(scope="module")
def research_source():
    root = Path(mkdtemp(prefix="ai-society-research-"))
    try:
        config = ExperimentConfig(seed=20260715, run_nonce="source")
        bundle = asyncio.run(_complete_bundle(config))
        service = ResearchService(root)
        manifest, report = service.register_bundle(
            artifact_name="source", bundle=bundle
        )
        yield root, service, bundle, manifest, report
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_catalog_manifest_report_and_clean_mark_are_verified(research_source) -> None:
    root, service, bundle, manifest, report = research_source

    assert manifest.marks == (RunMark.CLEAN,)
    assert manifest.bundle_digest == bundle.bundle_digest
    assert manifest.world_contract_digest == world_contract_digest(bundle.initial_state)
    assert manifest.engine_version == "0.5.0"
    assert manifest.rules_version == "block4-v1"
    assert service.load_bundle("source").bundle_digest == bundle.bundle_digest
    assert [entry.artifact_name for entry in service.list_catalog()] == ["source"]
    assert report.charts[0].title == "Успешные действия по агентам"
    report_root = root / "research" / "reports"
    assert (report_root / "source.md").is_file()
    assert (report_root / "source-charts.svg").is_file()
    assert "Ключевые метрики" in (report_root / "source-charts.svg").read_text(
        encoding="utf-8"
    )
    with pytest.raises(ResearchArtifactError, match="safe slug"):
        service.load_manifest("../escape")


def test_explicit_annotation_is_journaled_and_marks_run_modified(research_source) -> None:
    _root, service, source, _manifest, _report = research_source
    annotation = InterventionRecord(
        intervention_id="intervention-000001",
        game_minute=0,
        kind="researcher_annotation",
        actor="operator",
        reason="Контекст запуска зафиксирован до начала эксперимента.",
    )
    metrics = source.metrics.model_copy(update={"interventions": 1})
    draft = source.model_copy(
        update={
            "interventions": [annotation],
            "metrics": metrics,
            "bundle_digest": "0" * 64,
        }
    )
    annotated = draft.model_copy(update={"bundle_digest": bundle_digest(draft)})
    manifest, _report = service.register_bundle(
        artifact_name="annotated", bundle=annotated
    )

    assert manifest.marks == (RunMark.MODIFIED,)
    assert manifest.intervention_count == 1
    assert manifest.intervention_digest != "0" * 64


def test_duplicate_artifact_name_is_rejected_before_any_registered_data_changes(
    research_source,
) -> None:
    root, service, source, manifest, _report = research_source
    paths = (
        root / "source.json",
        root / "research" / "manifests" / "source.json",
        root / "research" / "catalog.json",
    )
    before = {path: path.read_bytes() for path in paths}

    with pytest.raises(ResearchArtifactError, match="already registered"):
        service.register_bundle(artifact_name="source", bundle=source)

    assert {path: path.read_bytes() for path in paths} == before
    assert service.load_manifest("source").manifest_digest == manifest.manifest_digest


def test_initial_snapshot_branch_preserves_parent_contract_and_namespace(research_source) -> None:
    _root, service, source, source_manifest, _report = research_source
    config, initial = service.create_initial_snapshot_branch("source", "branch")

    assert initial.game_minute == 0
    assert initial.processed_events == 0
    assert initial.event_queue == []
    assert initial.run.run_id != source.initial_state.run.run_id
    assert initial.run.modified is True
    assert world_contract_digest(initial) == source_manifest.world_contract_digest

    branch_bundle = asyncio.run(_complete_bundle(config, initial))
    manifest, _report = service.register_bundle(
        artifact_name="branch",
        bundle=branch_bundle,
        artifact_kind=ResearchArtifactKind.INITIAL_SNAPSHOT_BRANCH,
        parent_artifact_name="source",
    )

    assert manifest.marks == (RunMark.MODIFIED,)
    assert manifest.parent is not None
    assert manifest.parent.artifact_name == "source"
    assert manifest.parent.bundle_digest == source.bundle_digest
    assert source.bundle_digest == service.load_bundle("source").bundle_digest
    assert service.load_bundle("branch").final_state_hash == branch_bundle.final_state_hash


def test_experimental_rerun_has_a_new_namespace_and_explicit_mark(research_source) -> None:
    _root, service, source, source_manifest, _report = research_source
    config = service.rerun_config("source", "rerun")
    rerun_initial = create_experiment_world(config)
    assert rerun_initial.run.run_id != source.initial_state.run.run_id
    assert world_contract_digest(rerun_initial) == source_manifest.world_contract_digest

    rerun_bundle = asyncio.run(_complete_bundle(config))
    manifest, _report = service.register_bundle(
        artifact_name="rerun",
        bundle=rerun_bundle,
        artifact_kind=ResearchArtifactKind.EXPERIMENTAL_RERUN,
        parent_artifact_name="source",
    )
    assert manifest.marks == (RunMark.EXPERIMENTAL,)
    assert manifest.exact_decision_replay_verified is True


def test_comparison_finds_first_semantic_behavior_divergence(research_source) -> None:
    _root, service, source, _manifest, _report = research_source
    identical = compare_bundles(
        source, source, left_artifact_name="source", right_artifact_name="source"
    )
    assert identical.comparable is True
    assert identical.first_divergence is None

    changed_first = source.decisions[0].model_copy(
        update={"intent": WaitIntent(reason="контрольная ветка")}
    )
    divergent = source.model_copy(
        update={"decisions": [changed_first, *source.decisions[1:]]}
    )
    comparison = compare_bundles(
        source,
        divergent,
        left_artifact_name="source",
        right_artifact_name="synthetic",
    )
    assert comparison.first_divergence is not None
    assert comparison.first_divergence.stream == "decision"
    assert comparison.first_divergence.ordinal == 1
    assert comparison.first_divergence.field == "intent"
    saved = service.compare("source", "source")
    assert saved.first_divergence is None


def test_incomparable_runs_do_not_claim_a_first_behavioral_divergence(
    research_source,
) -> None:
    _root, _service, source, _manifest, _report = research_source
    changed_initial = source.initial_state.model_copy(deep=True)
    changed_initial.agents["agent-001"].identity.name = "Другой исследователь"
    changed_first = source.decisions[0].model_copy(
        update={"intent": WaitIntent(reason="несопоставимая ветка")}
    )
    incompatible = source.model_copy(
        update={
            "initial_state": changed_initial,
            "decisions": [changed_first, *source.decisions[1:]],
        }
    )

    comparison = compare_bundles(
        source,
        incompatible,
        left_artifact_name="source",
        right_artifact_name="incompatible",
    )

    assert comparison.comparable is False
    assert "different_world_or_personality_contract" in comparison.comparability_reasons
    assert comparison.first_divergence is None


def test_research_api_exposes_metadata_not_cognition(research_source) -> None:
    root, _service, _source, _manifest, _report = research_source

    async def scenario() -> None:
        app = create_app(
            snapshot_root=root / "snapshots",
            cognition_root=root / "cognition",
            experiment_root=root,
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                catalog = await client.get("/v1/experiments")
                assert catalog.status_code == 200
                assert {item["artifact_name"] for item in catalog.json()["runs"]} >= {"source"}
                manifest = await client.get("/v1/experiments/source")
                assert manifest.status_code == 200
                assert "cognition" not in json.dumps(manifest.json())
                report = await client.get("/v1/experiments/source/report")
                assert report.status_code == 200
                assert report.json()["charts"]
                comparisons_before = {
                    item.name
                    for item in (root / "research" / "comparisons").glob("*")
                }
                comparison = await client.get(
                    "/v1/experiments/compare", params={"left": "source", "right": "source"}
                )
                assert comparison.status_code == 200
                assert {
                    item.name
                    for item in (root / "research" / "comparisons").glob("*")
                } == comparisons_before
                rejected = await client.get("/v1/experiments/%2E%2E%2Fescape")
                assert rejected.status_code in {404, 422}
        finally:
            await app.state.registry.shutdown()

    asyncio.run(scenario())


def test_research_api_rejects_metadata_for_a_missing_catalogued_bundle() -> None:
    root = Path(mkdtemp(prefix="ai-society-research-api-"))
    try:
        config = ExperimentConfig(seed=20260716, run_nonce="missing")
        bundle = asyncio.run(_complete_bundle(config))
        service = ResearchService(root)
        service.register_bundle(artifact_name="missing", bundle=bundle)
        (root / "missing.json").unlink()

        async def scenario() -> None:
            app = create_app(
                snapshot_root=root / "snapshots",
                cognition_root=root / "cognition",
                experiment_root=root,
            )
            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://testserver"
                ) as client:
                    for path in (
                        "/v1/experiments",
                        "/v1/experiments/missing",
                        "/v1/experiments/missing/report",
                    ):
                        response = await client.get(path)
                        assert response.status_code in {404, 409}
            finally:
                await app.state.registry.shutdown()

        asyncio.run(scenario())
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_research_cli_reads_artifacts_and_rejects_nonminimal_replication(
    research_source, capsys
) -> None:
    root, _service, _source, _manifest, _report = research_source
    assert main(["catalog-experiments", "--output-root", str(root)]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert any(item["artifact_name"] == "source" for item in catalog["runs"])
    assert main(["report-experiment", "source", "--output-root", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["artifact_name"] == "source"
    with pytest.raises(ValueError, match="at least two"):
        main(
            [
                "replicate-experiment",
                "source",
                "--prefix",
                "invalid",
                "--count",
                "1",
                "--output-root",
                str(root),
            ]
        )


def test_root_windows_launcher_uses_existing_loopback_observer() -> None:
    launcher = Path(__file__).resolve().parents[1] / "START_AIWORLD_ARENA.bat"
    content = launcher.read_text(encoding="utf-8")
    assert "scripts\\observer.ps1" in content
    assert "-OpenBrowser" in content
    assert "AIWORLD_NO_PAUSE" in content
    assert all(ord(character) < 128 for character in content)
    observer = Path(__file__).resolve().parents[1] / "scripts" / "observer.ps1"
    assert observer.read_bytes().startswith(b"\xef\xbb\xbf")
    smoke = Path(__file__).resolve().parents[1] / "scripts" / "test-launcher.ps1"
    assert smoke.is_file()
    assert "AIWORLD_NO_BROWSER" in smoke.read_text(encoding="utf-8-sig")

import argparse
import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_society.cognition.embeddings import DeterministicEmbeddingProvider
from ai_society.cognition.repository import SQLiteCognitionRepository
from ai_society.executive.layer import ExecutiveLayer
from ai_society.executive.runner import ExecutiveRunner
from ai_society.experiment.models import ExperimentConfig, ModelAssignment
from ai_society.experiment.persistence import ExperimentBundleRepository
from ai_society.experiment.runner import ExperimentRunner, replay_bundle
from ai_society.experiment.scenario import (
    ExperimentalScriptedPolicy,
    create_experiment_world,
)
from ai_society.domain.enums import ExperimentMode
from ai_society.persistence.repository import SnapshotRepository
from ai_society.providers.ollama import (
    OllamaConfig,
    OllamaEmbeddingProvider,
    OllamaModelProvider,
)
from ai_society.providers.registry import ProviderRegistry
from ai_society.research.models import ResearchArtifactKind
from ai_society.research.service import ResearchService
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"
DEFAULT_COGNITION_ROOT = PROJECT_ROOT / "data" / "cognition"
DEFAULT_EXPERIMENT_ROOT = PROJECT_ROOT / "outputs" / "experiments"


def _agent_names(count: int) -> list[str]:
    return [f"Agent-{index:02d}" for index in range(1, count + 1)]


def _print_summary(engine: SimulationEngine) -> None:
    print(json.dumps(engine.summary(), ensure_ascii=False, indent=2, sort_keys=True))


@contextmanager
def _isolated_cognition_repository(
    root: Path,
) -> Iterator[SQLiteCognitionRepository]:
    """Create an empty, disposable cognition store for a single smoke run."""
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="ollama-smoke-", dir=root) as temporary_root:
        with SQLiteCognitionRepository(Path(temporary_root), "cognition") as repository:
            yield repository


def _run(args: argparse.Namespace) -> int:
    world = generate_world(
        seed=args.seed,
        width=args.width,
        height=args.height,
        agent_names=_agent_names(args.agents),
    )
    engine = SimulationEngine(state=world, policy=ScriptedPolicy())
    completed = engine.run(args.events)
    if completed != args.events:
        raise RuntimeError(f"simulation stopped after {completed} events")
    if args.save:
        repository = SnapshotRepository(Path(args.snapshot_root))
        repository.save(
            args.save,
            state=engine.state,
            events=engine.event_log.events,
        )
    _print_summary(engine)
    return 0


def _resume(args: argparse.Namespace) -> int:
    repository = SnapshotRepository(Path(args.snapshot_root))
    envelope = repository.load(args.snapshot)
    engine = SimulationEngine.restore(
        state=envelope.state,
        events=envelope.events,
        policy=ScriptedPolicy(),
    )
    engine.mark_snapshot_imported(
        source_state_hash=envelope.state_hash,
        source_event_digest=envelope.event_digest,
    )
    completed = engine.run(args.events)
    if completed != args.events:
        raise RuntimeError(f"simulation stopped after {completed} events")
    if args.save:
        repository.save(
            args.save,
            state=engine.state,
            events=engine.event_log.events,
        )
    _print_summary(engine)
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "ai_society.api.app:app",
        host="127.0.0.1",
        port=args.port,
        reload=False,
    )
    return 0


def _ollama_models(_args: argparse.Namespace) -> int:
    async def operation() -> list[dict[str, object]]:
        provider = OllamaModelProvider()
        try:
            return [
                item.model_dump(mode="json") for item in await provider.list_models()
            ]
        finally:
            await provider.close()

    print(json.dumps(asyncio.run(operation()), ensure_ascii=False, indent=2))
    return 0


def _ollama_smoke(args: argparse.Namespace) -> int:
    async def operation() -> dict[str, object]:
        config = OllamaConfig(structured_outputs=not args.no_structured_output)
        provider = OllamaModelProvider(config)
        embedding_provider = None
        registry = ProviderRegistry()
        registry.register(provider)
        try:
            models = await provider.list_models()
            available = {(item.provider, item.model) for item in models}
            if (provider.provider_id, args.model) not in available:
                raise RuntimeError(
                    "selected model is not present in the dynamic Ollama inventory"
                )
            if args.embedding_model:
                embedding_provider = OllamaEmbeddingProvider(
                    args.embedding_model, config
                )
                embedder = embedding_provider
            else:
                embedder = DeterministicEmbeddingProvider()
            world = generate_world(seed=args.seed, agent_names=["Ollama-Smoke"])
            engine = SimulationEngine(state=world, policy=ScriptedPolicy())
            engine.hot_swap_model(
                "agent-001",
                provider=provider.provider_id,
                model=args.model,
                available_bindings=available,
                temperature_milli=args.temperature_milli,
            )
            with _isolated_cognition_repository(Path(args.cognition_root)) as cognition:
                executive = ExecutiveLayer(
                    providers=registry,
                    cognition=cognition,
                    embedding_provider=embedder,
                )
                result = await ExecutiveRunner(engine, executive).step()
                usage = cognition.usage_summary(
                    run_id=world.run.run_id, agent_id="agent-001"
                )
                return {
                    "model": args.model,
                    "embedding_model": args.embedding_model,
                    "action_result": result.model_dump(mode="json") if result else None,
                    "usage": usage.model_dump(mode="json"),
                    "event_digest": engine.event_log.digest,
                    "state_hash": engine.state_hash,
                }
        finally:
            if embedding_provider is not None:
                await embedding_provider.close()
            await registry.close()

    print(
        json.dumps(
            asyncio.run(operation()), ensure_ascii=False, indent=2, sort_keys=True
        )
    )
    return 0


def _assignments_for(
    mode: ExperimentMode, models: list[str], temperature_milli: int
) -> tuple[ModelAssignment, ...]:
    if mode is ExperimentMode.CONTROLLED:
        if len(models) != 1:
            raise ValueError("controlled mode requires exactly one --models value")
        return tuple(
            ModelAssignment(
                agent_id=f"agent-{index:03d}",
                provider="ollama",
                model=models[0],
                temperature_milli=temperature_milli,
            )
            for index in range(1, 4)
        )
    if mode is ExperimentMode.NATURAL:
        if len(models) != 3:
            raise ValueError("natural mode requires exactly three --models values")
        return tuple(
            ModelAssignment(
                agent_id=f"agent-{index:03d}",
                provider="ollama",
                model=model,
                temperature_milli=temperature_milli,
            )
            for index, model in enumerate(models, start=1)
        )
    if models:
        raise ValueError("scripted mode does not accept --models")
    return ()


async def _execute_experiment(
    *,
    config: ExperimentConfig,
    cognition_root: Path,
    max_events: int,
    initial_state=None,
    annotations: list[str] | None = None,
) -> tuple[object, int]:
    """Run a fresh experiment. This path is intentionally distinct from replay."""

    initial = (
        create_experiment_world(config)
        if initial_state is None
        else initial_state.model_copy(deep=True)
    )
    engine = SimulationEngine(
        state=initial.model_copy(deep=True), policy=ExperimentalScriptedPolicy()
    )
    providers = ProviderRegistry()
    try:
        with _isolated_cognition_repository(cognition_root) as cognition:
            executive = None
            if config.mode is not ExperimentMode.SCRIPTED:
                provider = OllamaModelProvider()
                providers.register(provider)
                available = await providers.available_bindings()
                missing = {
                    (assignment.provider, assignment.model)
                    for assignment in config.model_assignments
                    if (assignment.provider, assignment.model) not in available
                }
                if missing:
                    raise RuntimeError(
                        "selected model is absent from Ollama inventory: "
                        + ", ".join(sorted(model for _, model in missing))
                    )
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
            for annotation in annotations or []:
                runner.record_annotation(actor="operator", reason=annotation)
            processed = await runner.run_to_completion(max_events=max_events)
            return runner.export_bundle(), processed
    finally:
        await providers.close()


def _experiment_summary(
    *,
    bundle,
    processed: int,
    manifest,
    output_root: Path,
) -> dict[str, object]:
    return {
        "bundle": str(output_root / f"{manifest.artifact_name}.json"),
        "manifest": str(
            output_root / "research" / "manifests" / f"{manifest.artifact_name}.json"
        ),
        "report": str(
            output_root / "research" / "reports" / f"{manifest.artifact_name}.md"
        ),
        "mode": bundle.config.mode.value,
        "marks": [mark.value for mark in manifest.marks],
        "processed_events": processed,
        "decisions": len(bundle.decisions),
        "duration_minutes": bundle.metrics.duration_minutes,
        "state_hash": bundle.final_state_hash,
        "event_digest": bundle.final_event_digest,
        "exact_replay_verified": manifest.exact_decision_replay_verified,
        "metrics": bundle.metrics.model_dump(mode="json"),
    }


def _experiment(args: argparse.Namespace) -> int:
    async def operation() -> dict[str, object]:
        mode = ExperimentMode(args.mode)
        config = ExperimentConfig(
            seed=args.seed,
            width=args.size,
            height=args.size,
            mode=mode,
            model_assignments=_assignments_for(
                mode, list(args.models or []), args.temperature_milli
            ),
            run_nonce=args.name,
        )
        root = Path(args.output_root)
        bundle, processed = await _execute_experiment(
            config=config,
            cognition_root=Path(args.cognition_root),
            max_events=args.max_events,
            annotations=list(args.annotation or []),
        )
        service = ResearchService(root)
        manifest, _report = service.register_bundle(
            artifact_name=args.name,
            bundle=bundle,
        )
        return _experiment_summary(
            bundle=bundle,
            processed=processed,
            manifest=manifest,
            output_root=root,
        )

    print(json.dumps(asyncio.run(operation()), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _rerun_experiment(args: argparse.Namespace) -> int:
    async def operation() -> dict[str, object]:
        root = Path(args.output_root)
        service = ResearchService(root)
        config = service.rerun_config(args.source, args.name)
        bundle, processed = await _execute_experiment(
            config=config,
            cognition_root=Path(args.cognition_root),
            max_events=args.max_events,
        )
        manifest, _report = service.register_bundle(
            artifact_name=args.name,
            bundle=bundle,
            artifact_kind=ResearchArtifactKind.EXPERIMENTAL_RERUN,
            parent_artifact_name=args.source,
        )
        return _experiment_summary(
            bundle=bundle,
            processed=processed,
            manifest=manifest,
            output_root=root,
        )

    print(json.dumps(asyncio.run(operation()), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _replicate_experiment(args: argparse.Namespace) -> int:
    async def operation() -> dict[str, object]:
        if args.count < 2:
            raise ValueError("minimal replication requires at least two replicas")
        root = Path(args.output_root)
        service = ResearchService(root)
        results: list[dict[str, object]] = []
        for index in range(1, args.count + 1):
            name = f"{args.prefix}-{index:02d}"
            config = service.rerun_config(args.source, name)
            bundle, processed = await _execute_experiment(
                config=config,
                cognition_root=Path(args.cognition_root),
                max_events=args.max_events,
            )
            manifest, _report = service.register_bundle(
                artifact_name=name,
                bundle=bundle,
                artifact_kind=ResearchArtifactKind.REPLICA,
                parent_artifact_name=args.source,
            )
            results.append(
                _experiment_summary(
                    bundle=bundle,
                    processed=processed,
                    manifest=manifest,
                    output_root=root,
                )
            )
        return {"source": args.source, "replicas": results}

    print(json.dumps(asyncio.run(operation()), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _branch_experiment(args: argparse.Namespace) -> int:
    async def operation() -> dict[str, object]:
        root = Path(args.output_root)
        service = ResearchService(root)
        config, initial_state = service.create_initial_snapshot_branch(
            args.source, args.name
        )
        bundle, processed = await _execute_experiment(
            config=config,
            cognition_root=Path(args.cognition_root),
            max_events=args.max_events,
            initial_state=initial_state,
            annotations=[
                f"Ветка создана из начального снимка запуска {args.source}."
            ],
        )
        manifest, _report = service.register_bundle(
            artifact_name=args.name,
            bundle=bundle,
            artifact_kind=ResearchArtifactKind.INITIAL_SNAPSHOT_BRANCH,
            parent_artifact_name=args.source,
        )
        return _experiment_summary(
            bundle=bundle,
            processed=processed,
            manifest=manifest,
            output_root=root,
        )

    print(json.dumps(asyncio.run(operation()), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _catalog_experiments(args: argparse.Namespace) -> int:
    service = ResearchService(Path(args.output_root))
    print(
        json.dumps(
            {"runs": [entry.model_dump(mode="json") for entry in service.list_catalog()]},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _compare_experiments(args: argparse.Namespace) -> int:
    comparison = ResearchService(Path(args.output_root)).compare(args.left, args.right)
    print(
        json.dumps(
            comparison.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _report_experiment(args: argparse.Namespace) -> int:
    report = ResearchService(Path(args.output_root)).regenerate_report(args.name)
    print(
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _replay_experiment(args: argparse.Namespace) -> int:
    repository = ExperimentBundleRepository(Path(args.output_root))
    bundle = repository.load(args.name)
    engine = replay_bundle(bundle)
    print(
        json.dumps(
            {
                "run_id": engine.state.run.run_id,
                "duration_minutes": engine.state.game_minute,
                "decisions": len(bundle.decisions),
                "state_hash": engine.state_hash,
                "event_digest": engine.event_log.digest,
                "network_calls": 0,
                "exact_replay_verified": True,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-society")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run a new deterministic world")
    run_parser.add_argument("--seed", type=int, default=42)
    run_parser.add_argument("--width", type=int, default=32)
    run_parser.add_argument("--height", type=int, default=32)
    run_parser.add_argument("--agents", type=int, default=3, choices=range(1, 101))
    run_parser.add_argument("--events", type=int, default=1_000)
    run_parser.add_argument("--save")
    run_parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT))
    run_parser.set_defaults(handler=_run)

    resume_parser = subparsers.add_parser(
        "resume",
        help="resume an integrity-checked snapshot as an unverified import",
    )
    resume_parser.add_argument("snapshot")
    resume_parser.add_argument("--events", type=int, default=1_000)
    resume_parser.add_argument("--save")
    resume_parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT))
    resume_parser.set_defaults(handler=_resume)

    serve_parser = subparsers.add_parser("serve", help="serve the loopback-only API")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.set_defaults(handler=_serve)

    models_parser = subparsers.add_parser(
        "ollama-models", help="list models from the server-configured Ollama runtime"
    )
    models_parser.set_defaults(handler=_ollama_models)

    smoke_parser = subparsers.add_parser(
        "ollama-smoke", help="run one isolated real Executive Layer decision"
    )
    smoke_parser.add_argument("--model", required=True)
    smoke_parser.add_argument("--embedding-model")
    smoke_parser.add_argument("--seed", type=int, default=2026)
    smoke_parser.add_argument("--temperature-milli", type=int, default=0)
    smoke_parser.add_argument("--no-structured-output", action="store_true")
    smoke_parser.add_argument(
        "--cognition-root", default=str(DEFAULT_COGNITION_ROOT)
    )
    smoke_parser.set_defaults(handler=_ollama_smoke)

    experiment_parser = subparsers.add_parser(
        "experiment", help="run and export the seven-day Experimental MVP"
    )
    experiment_parser.add_argument(
        "--mode",
        choices=["scripted", "natural", "controlled"],
        default="scripted",
    )
    experiment_parser.add_argument("--models", nargs="*")
    experiment_parser.add_argument("--seed", type=int, default=20260715)
    experiment_parser.add_argument("--size", type=int, choices=[48, 64], default=48)
    experiment_parser.add_argument("--temperature-milli", type=int, default=0)
    experiment_parser.add_argument("--max-events", type=int, default=100_000)
    experiment_parser.add_argument("--name", default="three-agents-seven-days")
    experiment_parser.add_argument(
        "--annotation",
        action="append",
        default=[],
        help="explicit researcher annotation recorded in the intervention journal",
    )
    experiment_parser.add_argument(
        "--output-root", default=str(DEFAULT_EXPERIMENT_ROOT)
    )
    experiment_parser.add_argument(
        "--cognition-root", default=str(DEFAULT_COGNITION_ROOT)
    )
    experiment_parser.set_defaults(handler=_experiment)

    replay_parser = subparsers.add_parser(
        "replay-experiment", help="verify an exported experiment without network calls"
    )
    replay_parser.add_argument("name")
    replay_parser.add_argument(
        "--output-root", default=str(DEFAULT_EXPERIMENT_ROOT)
    )
    replay_parser.set_defaults(handler=_replay_experiment)

    rerun_parser = subparsers.add_parser(
        "rerun-experiment",
        help="run the same world and bindings again; this is never an exact replay",
    )
    rerun_parser.add_argument("source")
    rerun_parser.add_argument("--name", required=True)
    rerun_parser.add_argument("--max-events", type=int, default=100_000)
    rerun_parser.add_argument("--output-root", default=str(DEFAULT_EXPERIMENT_ROOT))
    rerun_parser.add_argument("--cognition-root", default=str(DEFAULT_COGNITION_ROOT))
    rerun_parser.set_defaults(handler=_rerun_experiment)

    replication_parser = subparsers.add_parser(
        "replicate-experiment",
        help="perform the mandatory minimum of two fresh replicas from one source",
    )
    replication_parser.add_argument("source")
    replication_parser.add_argument("--prefix", required=True)
    replication_parser.add_argument("--count", type=int, default=2)
    replication_parser.add_argument("--max-events", type=int, default=100_000)
    replication_parser.add_argument(
        "--output-root", default=str(DEFAULT_EXPERIMENT_ROOT)
    )
    replication_parser.add_argument(
        "--cognition-root", default=str(DEFAULT_COGNITION_ROOT)
    )
    replication_parser.set_defaults(handler=_replicate_experiment)

    branch_parser = subparsers.add_parser(
        "branch-experiment",
        help="create a full child run from a verified time-zero bundle snapshot",
    )
    branch_parser.add_argument("source")
    branch_parser.add_argument("--name", required=True)
    branch_parser.add_argument("--max-events", type=int, default=100_000)
    branch_parser.add_argument("--output-root", default=str(DEFAULT_EXPERIMENT_ROOT))
    branch_parser.add_argument("--cognition-root", default=str(DEFAULT_COGNITION_ROOT))
    branch_parser.set_defaults(handler=_branch_experiment)

    catalog_parser = subparsers.add_parser(
        "catalog-experiments", help="list verified research artifacts"
    )
    catalog_parser.add_argument("--output-root", default=str(DEFAULT_EXPERIMENT_ROOT))
    catalog_parser.set_defaults(handler=_catalog_experiments)

    compare_parser = subparsers.add_parser(
        "compare-experiments", help="compare two catalogued experiment artifacts"
    )
    compare_parser.add_argument("left")
    compare_parser.add_argument("right")
    compare_parser.add_argument("--output-root", default=str(DEFAULT_EXPERIMENT_ROOT))
    compare_parser.set_defaults(handler=_compare_experiments)

    report_parser = subparsers.add_parser(
        "report-experiment", help="regenerate a readable JSON, Markdown and SVG report"
    )
    report_parser.add_argument("name")
    report_parser.add_argument("--output-root", default=str(DEFAULT_EXPERIMENT_ROOT))
    report_parser.set_defaults(handler=_report_experiment)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

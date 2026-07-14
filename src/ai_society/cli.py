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
from ai_society.persistence.repository import SnapshotRepository
from ai_society.providers.ollama import (
    OllamaConfig,
    OllamaEmbeddingProvider,
    OllamaModelProvider,
)
from ai_society.providers.registry import ProviderRegistry
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"
DEFAULT_COGNITION_ROOT = PROJECT_ROOT / "data" / "cognition"


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

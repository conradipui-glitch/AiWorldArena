import argparse
import json
from pathlib import Path

from ai_society.persistence.repository import SnapshotRepository
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "snapshots"


def _agent_names(count: int) -> list[str]:
    return [f"Agent-{index:02d}" for index in range(1, count + 1)]


def _print_summary(engine: SimulationEngine) -> None:
    print(json.dumps(engine.summary(), ensure_ascii=False, indent=2, sort_keys=True))


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

    resume_parser = subparsers.add_parser("resume", help="resume a verified snapshot")
    resume_parser.add_argument("snapshot")
    resume_parser.add_argument("--events", type=int, default=1_000)
    resume_parser.add_argument("--save")
    resume_parser.add_argument("--snapshot-root", default=str(DEFAULT_SNAPSHOT_ROOT))
    resume_parser.set_defaults(handler=_resume)

    serve_parser = subparsers.add_parser("serve", help="serve the loopback-only API")
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.set_defaults(handler=_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

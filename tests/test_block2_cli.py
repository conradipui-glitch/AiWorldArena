from pathlib import Path
import json

from ai_society.cli import _isolated_cognition_repository, main
from ai_society.domain.enums import MemoryLayer, WorldEventKind
from ai_society.persistence.repository import SnapshotRepository
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


def test_ollama_smoke_uses_a_fresh_disposable_cognition_store(
    tmp_path: Path,
) -> None:
    run_id = "run-123456789abc"
    with _isolated_cognition_repository(tmp_path) as first:
        first_path = first.path
        first.add_memory(
            run_id=run_id,
            agent_id="agent-001",
            layer=MemoryLayer.WORKING,
            content="must not survive the isolated smoke run",
            game_minute=0,
            source_kind="test",
        )
        assert first.list_memories(
            run_id=run_id, agent_id="agent-001"
        )

    assert not first_path.exists()

    with _isolated_cognition_repository(tmp_path) as second:
        assert second.path != first_path
        assert second.list_memories(
            run_id=run_id, agent_id="agent-001"
        ) == []


def test_cli_resume_marks_snapshot_as_unverified_import(
    tmp_path: Path, capsys
) -> None:
    repository = SnapshotRepository(tmp_path)
    engine = SimulationEngine(
        state=generate_world(seed=808, agent_names=["A", "B"]),
        policy=ScriptedPolicy(),
    )
    engine.run(5)
    repository.save(
        "source",
        state=engine.state,
        events=engine.event_log.events,
    )

    result = main(
        [
            "resume",
            "source",
            "--events",
            "1",
            "--save",
            "imported",
            "--snapshot-root",
            str(tmp_path),
        ]
    )

    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["modified"] is True
    imported = repository.load("imported")
    assert imported.state.run.modified is True
    assert any(
        event.kind is WorldEventKind.SNAPSHOT_IMPORTED
        for event in imported.events
    )

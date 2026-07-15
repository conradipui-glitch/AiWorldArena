import json

import pytest

from ai_society.persistence.event_log import EventIntegrityError, EventLog
from ai_society.persistence.canonical import canonical_digest
from ai_society.persistence.repository import SnapshotError, SnapshotRepository
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


def new_engine() -> SimulationEngine:
    return SimulationEngine(
        state=generate_world(seed=404, agent_names=["A", "B", "C"]),
        policy=ScriptedPolicy(),
    )


def test_save_load_continue_is_exact(tmp_path) -> None:
    uninterrupted = new_engine()
    interrupted = new_engine()
    uninterrupted.run(1_000)

    interrupted.run(400)
    repository = SnapshotRepository(tmp_path)
    repository.save(
        "checkpoint",
        state=interrupted.state,
        events=interrupted.event_log.events,
    )
    envelope = repository.load("checkpoint")
    restored = SimulationEngine.restore(
        state=envelope.state,
        events=envelope.events,
        policy=ScriptedPolicy(),
    )
    restored.run(600)

    assert restored.state_hash == uninterrupted.state_hash
    assert restored.event_log.digest == uninterrupted.event_log.digest


def test_event_log_detects_tampering() -> None:
    engine = new_engine()
    engine.run(10)
    tampered = [event.model_copy(deep=True) for event in engine.event_log.events]
    tampered[-1].payload["forged"] = True
    with pytest.raises(EventIntegrityError):
        EventLog(tampered)


def test_snapshot_name_rejects_path_traversal(tmp_path) -> None:
    engine = new_engine()
    repository = SnapshotRepository(tmp_path)
    with pytest.raises(SnapshotError):
        repository.save(
            "../escape",
            state=engine.state,
            events=engine.event_log.events,
        )


def test_snapshot_save_never_silently_overwrites_a_checkpoint(tmp_path) -> None:
    engine = new_engine()
    repository = SnapshotRepository(tmp_path)
    repository.save(
        "checkpoint",
        state=engine.state,
        events=engine.event_log.events,
    )

    with pytest.raises(SnapshotError, match="already exists"):
        repository.save(
            "checkpoint",
            state=engine.state,
            events=engine.event_log.events,
        )


def test_snapshot_detects_state_tampering(tmp_path) -> None:
    engine = new_engine()
    engine.run(20)
    repository = SnapshotRepository(tmp_path)
    path = repository.save(
        "tamper-check",
        state=engine.state,
        events=engine.event_log.events,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["game_minute"] += 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SnapshotError, match="state hash mismatch"):
        repository.load("tamper-check")


def test_snapshot_rejects_unknown_schema_version(tmp_path) -> None:
    engine = new_engine()
    repository = SnapshotRepository(tmp_path)
    path = repository.save(
        "unknown-schema",
        state=engine.state,
        events=engine.event_log.events,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = "snapshot-v999"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotError, match="schema validation failed"):
        repository.load("unknown-schema")


def test_snapshot_rejects_self_consistent_but_dangling_world_references(
    tmp_path,
) -> None:
    engine = new_engine()
    repository = SnapshotRepository(tmp_path)
    path = repository.save(
        "dangling-reference",
        state=engine.state,
        events=engine.event_log.events,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"]["event_queue"][0]["actor_id"] = "ghost-agent"
    payload["state_hash"] = canonical_digest(payload["state"])
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SnapshotError, match="schema validation failed"):
        repository.load("dangling-reference")

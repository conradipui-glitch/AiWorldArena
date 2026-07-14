from ai_society.domain.enums import CommitmentStatus, MessageStatus
from ai_society.domain.intents import CreatePromiseIntent, SpeakIntent
from ai_society.persistence.repository import SnapshotRepository
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


def test_pending_message_survives_snapshot_and_delivers_exactly_once(tmp_path) -> None:
    engine = SimulationEngine(
        state=generate_world(seed=33, agent_names=["A", "B"]),
        policy=ScriptedPolicy(),
    )
    engine.state.event_queue.clear()
    engine.state.agents["agent-002"].position = engine.state.agents["agent-001"].position
    engine.execute(
        "agent-001",
        SpeakIntent(
            target_agent_id="agent-002",
            message="persist me",
            reason="verify pending delivery persistence",
        ),
    )
    repository = SnapshotRepository(tmp_path)
    repository.save(
        "pending-message", state=engine.state, events=engine.event_log.events
    )
    envelope = repository.load("pending-message")
    restored = SimulationEngine.restore(
        state=envelope.state,
        events=envelope.events,
        policy=ScriptedPolicy(),
    )
    restored.process_next_system_event()
    assert restored.state.messages["message-000001"].status is MessageStatus.DELIVERED
    restored.process_next_system_event()
    assert restored.state.messages["message-000001"].status is MessageStatus.DELIVERED


def test_pending_commitment_deadline_survives_snapshot(tmp_path) -> None:
    engine = SimulationEngine(
        state=generate_world(seed=34, agent_names=["A", "B"]),
        policy=ScriptedPolicy(),
    )
    engine.state.event_queue.clear()
    engine.state.agents["agent-002"].position = engine.state.agents["agent-001"].position
    engine.execute(
        "agent-001",
        CreatePromiseIntent(
            beneficiary_agent_id="agent-002",
            agreement_terms="return before dusk",
            due_in_minutes=45,
            reason="verify deadline persistence",
        ),
    )
    repository = SnapshotRepository(tmp_path)
    repository.save(
        "pending-commitment", state=engine.state, events=engine.event_log.events
    )
    envelope = repository.load("pending-commitment")
    restored = SimulationEngine.restore(
        state=envelope.state,
        events=envelope.events,
        policy=ScriptedPolicy(),
    )
    restored.process_next_system_event()
    commitment = restored.state.commitments["commitment-000001"]
    assert commitment.status is CommitmentStatus.EXPIRED
    assert restored.state.game_minute == 45

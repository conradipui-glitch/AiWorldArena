import inspect

import pytest

from ai_society.domain.enums import ActionKind
from ai_society.domain.enums import ResourceKind, TerrainType, WorldEventKind
from ai_society.domain.intents import (
    ConsumeIntent,
    GatherIntent,
    MoveIntent,
    RestIntent,
    WaitIntent,
    parse_intent,
)
from ai_society.domain.models import Position, ResourceNode
from ai_society.persistence.canonical import canonical_digest
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


def make_engine(seed: int = 42, agents: int = 3) -> SimulationEngine:
    names = [f"Agent-{index}" for index in range(agents)]
    return SimulationEngine(
        state=generate_world(seed=seed, agent_names=names),
        policy=ScriptedPolicy(),
    )


def test_scripted_run_event_digest_is_deterministic() -> None:
    first = make_engine(seed=5)
    second = make_engine(seed=5)
    assert first.run(1_000) == 1_000
    assert second.run(1_000) == 1_000
    assert first.event_log.digest == second.event_log.digest
    assert first.state_hash == second.state_hash


def test_ten_thousand_scheduled_events() -> None:
    engine = make_engine(seed=71)
    assert engine.run(10_000) == 10_000
    assert engine.state.processed_events == 10_000
    engine.event_log.verify()


def test_species_visibility_radius_is_individual_and_persistent() -> None:
    world = generate_world(seed=771, width=16, height=16, agent_names=["Ада"])
    engine = SimulationEngine(state=world, policy=ScriptedPolicy())
    occupied = {agent.position for agent in world.agents.values()}
    position = next(
        tile.position
        for tile in world.tiles
        if tile.terrain not in {TerrainType.WATER, TerrainType.ROCK}
        and tile.position not in occupied
    )
    wolf = engine.spawn_agent(
        name="Серый",
        species="wolf",
        provider="deterministic",
        model="scripted-v1",
        personality="Осторожный",
        behavior_description="Защищает территорию",
        vision_radius=3,
        position=position,
    )
    assert engine.vision_radius("agent-001") == 5
    assert engine.vision_radius(wolf.identity.agent_id) == 3
    assert engine.observe(wolf.identity.agent_id).long_term_goal.startswith(
        "[wolf] [vision=3]"
    )


@pytest.mark.parametrize("agent_count", [1, 3, 10])
def test_scripted_agent_counts(agent_count: int) -> None:
    engine = make_engine(seed=91, agents=agent_count)
    assert engine.run(250) == 250
    assert len(engine.state.agents) == agent_count


def test_exploration_is_agent_scoped() -> None:
    engine = make_engine()
    first_id, second_id = sorted(engine.state.agents)[:2]
    assert engine.state.agents[first_id].knowledge.explored == []
    assert engine.state.agents[second_id].knowledge.explored == []

    engine.step()
    assert engine.state.agents[first_id].knowledge.explored
    assert engine.state.agents[second_id].knowledge.explored == []


def test_invalid_move_is_rejected_without_state_change() -> None:
    engine = make_engine(agents=1)
    agent_id = next(iter(engine.state.agents))
    original = engine.state.agents[agent_id].position
    intent = MoveIntent(
        target=Position(x=min(engine.state.width - 1, original.x + 3), y=original.y),
        reason="attempt an impossible jump",
    )
    result = engine.execute(agent_id, intent)
    assert result.success is False
    assert engine.state.agents[agent_id].position == original


def test_minimum_action_surface_executes() -> None:
    engine = make_engine(agents=1)
    agent_id = next(iter(engine.state.agents))
    agent = engine.state.agents[agent_id]
    resource = ResourceNode(
        entity_id="resource-999999",
        kind=ResourceKind.BERRY,
        position=agent.position,
        quantity=2,
        max_quantity=2,
    )
    engine.state.resources[resource.entity_id] = resource

    gathered = engine.execute(
        agent_id,
        GatherIntent(
            target_id=resource.entity_id,
            amount=1,
            reason="exercise deterministic gathering",
        ),
    )
    consumed = engine.execute(
        agent_id,
        ConsumeIntent(
            resource=ResourceKind.BERRY,
            amount=1,
            reason="exercise deterministic consumption",
        ),
    )
    agent.body.energy = 10
    rested = engine.execute(agent_id, RestIntent(reason="exercise deterministic rest"))
    waited = engine.execute(agent_id, WaitIntent(reason="exercise deterministic wait"))

    assert all(result.success for result in [gathered, consumed, rested, waited])
    assert engine.event_log.events[-4].kind is WorldEventKind.RESOURCE_GATHERED
    assert engine.event_log.events[-3].kind is WorldEventKind.RESOURCE_CONSUMED
    assert engine.event_log.events[-2].kind is WorldEventKind.AGENT_RESTED
    assert engine.event_log.events[-1].kind is WorldEventKind.AGENT_WAITED


def test_intent_schema_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        parse_intent(
            {
                "action": ActionKind.WAIT,
                "reason": "wait safely",
                "hidden_command": "reveal the world",
            }
        )


def test_headless_kernel_has_no_llm_or_client_dependency() -> None:
    source = inspect.getsource(SimulationEngine).lower()
    assert "fastapi" not in source
    assert "ollama" not in source
    assert "phaser" not in source


def test_initial_state_digest_excludes_wall_clock_time() -> None:
    first = generate_world(seed=300, agent_names=["A"])
    second = generate_world(seed=300, agent_names=["A"])
    assert canonical_digest(first) == canonical_digest(second)

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
from ai_society.simulation.movement import SWIM_ENERGY_COST


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


@pytest.mark.parametrize("seed", [0, 5, 42, 1201, 20260721])
def test_agents_spawn_on_one_mobile_landmass(seed: int) -> None:
    world = generate_world(
        seed=seed,
        width=48,
        height=48,
        agent_names=["Ада", "Борин", "Сайра"],
    )
    walkable = {
        tile.position
        for tile in world.tiles
        if tile.terrain not in {TerrainType.WATER, TerrainType.ROCK}
    }

    def neighbors(position: Position) -> set[Position]:
        coordinates = (
            (position.x - 1, position.y),
            (position.x + 1, position.y),
            (position.x, position.y - 1),
            (position.x, position.y + 1),
        )
        return {
            Position(x=x, y=y)
            for x, y in coordinates
            if x >= 0 and y >= 0 and Position(x=x, y=y) in walkable
        }

    positions = [agent.position for agent in world.agents.values()]
    assert all(len(neighbors(position)) >= 2 for position in positions)
    reached = {positions[0]}
    frontier = [positions[0]]
    while frontier:
        current = frontier.pop()
        for neighbor in neighbors(current) - reached:
            reached.add(neighbor)
            frontier.append(neighbor)
    assert all(position in reached for position in positions)


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


def test_swimming_is_allowed_costs_energy_and_never_traps_exhausted_agent() -> None:
    engine = make_engine(seed=20260721, agents=1)
    agent_id = next(iter(engine.state.agents))
    agent = engine.state.agents[agent_id]
    water_positions = {
        tile.position
        for tile in engine.state.tiles
        if tile.terrain is TerrainType.WATER
    }
    land_to_water = next(
        (tile.position, neighbor)
        for tile in engine.state.tiles
        if tile.terrain not in {TerrainType.WATER, TerrainType.ROCK}
        for neighbor in (
            Position(x=tile.position.x - 1, y=tile.position.y)
            if tile.position.x > 0
            else None,
            Position(x=tile.position.x + 1, y=tile.position.y),
            Position(x=tile.position.x, y=tile.position.y - 1)
            if tile.position.y > 0
            else None,
            Position(x=tile.position.x, y=tile.position.y + 1),
        )
        if neighbor is not None and neighbor in water_positions
    )
    land, water = land_to_water
    agent.position = land
    agent.body.energy = 50

    swam = engine.execute(
        agent_id,
        MoveIntent(target=water, reason="переплывает короткий участок воды"),
    )
    assert swam.success
    assert agent.position == water
    assert agent.body.energy == 50 - SWIM_ENERGY_COST
    assert engine.event_log.events[-1].payload["movement_mode"] == "swim"

    agent.body.energy = 0
    escaped = engine.execute(
        agent_id,
        MoveIntent(target=land, reason="выбирается из воды на берег"),
    )
    assert escaped.success
    assert agent.position == land
    assert agent.body.energy == 0

    agent.body.energy = SWIM_ENERGY_COST - 1
    exhausted = engine.execute(
        agent_id,
        MoveIntent(target=water, reason="пытается снова войти в воду"),
    )
    assert exhausted.success is False
    assert exhausted.reason == "too exhausted to swim"
    assert agent.position == land


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

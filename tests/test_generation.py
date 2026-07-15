from ai_society.domain.models import Tile
from ai_society.persistence.canonical import canonical_digest
from ai_society.simulation.generation import generate_world


def test_same_seed_same_initial_world() -> None:
    first = generate_world(seed=144, agent_names=["A", "B", "C"])
    second = generate_world(seed=144, agent_names=["A", "B", "C"])
    assert canonical_digest(first) == canonical_digest(second)


def test_different_seed_changes_world() -> None:
    first = generate_world(seed=144, agent_names=["A", "B", "C"])
    second = generate_world(seed=145, agent_names=["A", "B", "C"])
    assert canonical_digest(first) != canonical_digest(second)


def test_tile_has_no_global_exploration_field() -> None:
    assert "explored" not in Tile.model_fields


def test_free_world_agents_start_far_apart() -> None:
    world = generate_world(
        seed=20260715,
        width=48,
        height=48,
        agent_names=["Ада", "Борин", "Сайра"],
    )
    positions = [agent.position for agent in world.agents.values()]

    assert min(
        left.manhattan_distance(right)
        for index, left in enumerate(positions)
        for right in positions[index + 1 :]
    ) >= 12

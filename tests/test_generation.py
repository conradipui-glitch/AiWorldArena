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

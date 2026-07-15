from ai_society.domain.enums import TerrainType


SWIM_ENERGY_COST = 8


def movement_mode(terrain: TerrainType) -> str:
    if terrain is TerrainType.ROCK:
        return "blocked"
    if terrain is TerrainType.WATER:
        return "swim"
    return "walk"


def movement_energy_cost(terrain: TerrainType) -> int:
    return SWIM_ENERGY_COST if terrain is TerrainType.WATER else 0


def terrain_is_traversable(terrain: TerrainType, *, energy: int) -> bool:
    if terrain is TerrainType.ROCK:
        return False
    if terrain is TerrainType.WATER:
        return energy >= SWIM_ENERGY_COST
    return True

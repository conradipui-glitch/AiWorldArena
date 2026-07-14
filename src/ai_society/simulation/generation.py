from collections.abc import Sequence

from ai_society.domain.enums import (
    ExperimentMode,
    IntelligenceTier,
    ResourceKind,
    TerrainType,
)
from ai_society.domain.models import (
    Agent,
    AgentBodyState,
    AgentIdentity,
    AgentKnowledgeMap,
    ExperimentRun,
    MindBinding,
    Position,
    ResourceNode,
    Tile,
    WorldState,
)
from ai_society.persistence.canonical import canonical_digest
from ai_society.simulation.rng import DeterministicRng


def _terrain_for(
    *, x: int, y: int, width: int, height: int, rng: DeterministicRng
) -> tuple[TerrainType, int, int, int]:
    center_x = (width - 1) / 2
    center_y = (height - 1) / 2
    normalized_x = (x - center_x) / max(center_x, 1)
    normalized_y = (y - center_y) / max(center_y, 1)
    distance_sq = normalized_x * normalized_x + normalized_y * normalized_y
    shoreline_noise = rng.randbelow(21) - 10
    moisture = rng.randbelow(101)
    elevation = max(0, min(100, int((1.15 - distance_sq) * 70) + rng.randbelow(21)))

    if distance_sq * 100 + shoreline_noise > 92:
        return TerrainType.WATER, 0, 100, 0
    if distance_sq * 100 + shoreline_noise > 72:
        return TerrainType.SAND, elevation, max(25, moisture), 15
    if elevation > 76 and moisture < 60:
        return TerrainType.ROCK, elevation, moisture, 10
    if moisture > 55 or rng.chance(1, 5):
        return TerrainType.FOREST, elevation, moisture, 65
    return TerrainType.GRASS, elevation, moisture, 80


def _resource_for_tile(
    tile: Tile, rng: DeterministicRng
) -> tuple[ResourceKind, int] | None:
    if tile.terrain is TerrainType.FOREST and rng.chance(2, 5):
        return ResourceKind.WOOD, 8
    if tile.terrain is TerrainType.ROCK and rng.chance(1, 2):
        return ResourceKind.STONE, 6
    if tile.terrain is TerrainType.GRASS and rng.chance(1, 7):
        return ResourceKind.BERRY, 8
    if tile.terrain is TerrainType.WATER and rng.chance(1, 5):
        return ResourceKind.WATER, 40
    return None


def _spawn_positions(tiles: list[Tile], agent_count: int) -> list[Position]:
    walkable = [
        tile.position
        for tile in tiles
        if tile.terrain not in {TerrainType.WATER, TerrainType.ROCK}
    ]
    if len(walkable) < agent_count:
        raise ValueError("generated world does not have enough walkable spawn tiles")
    walkable.sort(key=lambda position: (position.y, position.x))
    return [
        walkable[min(len(walkable) - 1, ((2 * index + 1) * len(walkable)) // (2 * agent_count))]
        for index in range(agent_count)
    ]


def generate_world(
    *,
    seed: int,
    width: int = 32,
    height: int = 32,
    agent_names: Sequence[str] = ("Ada", "Borin", "Cyra"),
) -> WorldState:
    if seed < 0 or seed > 2**63 - 1:
        raise ValueError("seed must fit an unsigned signed-64 range")
    if not 8 <= width <= 512 or not 8 <= height <= 512:
        raise ValueError("world dimensions must be between 8 and 512")
    if not 1 <= len(agent_names) <= 100:
        raise ValueError("agent count must be between 1 and 100")
    if len(set(agent_names)) != len(agent_names):
        raise ValueError("agent names must be unique")

    rng = DeterministicRng(seed)
    tiles: list[Tile] = []
    resources: dict[str, ResourceNode] = {}
    resource_ordinal = 0

    for y in range(height):
        for x in range(width):
            terrain, elevation, moisture, fertility = _terrain_for(
                x=x, y=y, width=width, height=height, rng=rng
            )
            tile = Tile(
                position=Position(x=x, y=y),
                terrain=terrain,
                elevation=elevation,
                moisture=moisture,
                fertility=fertility,
                has_water=terrain is TerrainType.WATER,
            )
            tiles.append(tile)
            generated_resource = _resource_for_tile(tile, rng)
            if generated_resource is not None:
                kind, quantity = generated_resource
                resource_ordinal += 1
                entity_id = f"resource-{resource_ordinal:06d}"
                resources[entity_id] = ResourceNode(
                    entity_id=entity_id,
                    kind=kind,
                    position=tile.position,
                    quantity=quantity,
                    max_quantity=quantity,
                )

    positions = _spawn_positions(tiles, len(agent_names))
    agents: dict[str, Agent] = {}
    for index, (name, position) in enumerate(zip(agent_names, positions, strict=True), start=1):
        agent_id = f"agent-{index:03d}"
        agents[agent_id] = Agent(
            identity=AgentIdentity(agent_id=agent_id, name=name),
            body=AgentBodyState(),
            mind=MindBinding(intelligence_tier=IntelligenceTier.SCRIPTED),
            position=position,
            inventory={ResourceKind.BERRY: 2, ResourceKind.WATER: 1},
            knowledge=AgentKnowledgeMap(),
        )

    identity_material = {
        "seed": seed,
        "width": width,
        "height": height,
        "agents": list(agent_names),
        "rules_version": "block1-v1",
    }
    identity_digest = canonical_digest(identity_material)
    world_id = f"world-{identity_digest[:12]}"
    run_id = f"run-{canonical_digest({'world_id': world_id, 'mode': 'scripted'})[:12]}"
    run = ExperimentRun(
        run_id=run_id,
        world_id=world_id,
        mode=ExperimentMode.SCRIPTED,
    )
    return WorldState(
        run=run,
        seed=seed,
        width=width,
        height=height,
        tiles=tiles,
        resources=resources,
        agents=agents,
        rng_state=rng.state,
    )

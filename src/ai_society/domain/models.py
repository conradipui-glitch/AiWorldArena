from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_society.domain.enums import (
    ExperimentMode,
    IntelligenceTier,
    ResourceKind,
    RunStatus,
    TerrainType,
)
from ai_society.domain.events import ScheduledEvent


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Position(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: int = Field(ge=0)
    y: int = Field(ge=0)

    def manhattan_distance(self, other: "Position") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)


class Tile(StrictModel):
    position: Position
    terrain: TerrainType
    elevation: int = Field(ge=0, le=100)
    moisture: int = Field(ge=0, le=100)
    fertility: int = Field(ge=0, le=100)
    has_water: bool = False
    light: int = Field(default=100, ge=0, le=100)


class ResourceNode(StrictModel):
    entity_id: str = Field(pattern=r"^resource-[0-9]{6}$")
    kind: ResourceKind
    position: Position
    quantity: int = Field(ge=0)
    max_quantity: int = Field(gt=0)

    @field_validator("quantity")
    @classmethod
    def quantity_cannot_exceed_reasonable_limit(cls, value: int) -> int:
        if value > 1_000_000:
            raise ValueError("resource quantity exceeds safety limit")
        return value


class AgentIdentity(StrictModel):
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    name: str = Field(min_length=1, max_length=64)
    long_term_goal: str = Field(default="survive and understand the world", max_length=240)


class AgentBodyState(StrictModel):
    health: int = Field(default=100, ge=0, le=100)
    hunger: int = Field(default=0, ge=0, le=100)
    energy: int = Field(default=100, ge=0, le=100)
    body_temperature_milli_c: int = Field(default=37_000, ge=30_000, le=45_000)
    last_updated_minute: int = Field(default=0, ge=0)
    hunger_remainder_minutes: int = Field(default=0, ge=0, lt=30)
    energy_remainder_minutes: int = Field(default=0, ge=0, lt=20)
    health_remainder_minutes: int = Field(default=0, ge=0, lt=60)


class MindBinding(StrictModel):
    intelligence_tier: IntelligenceTier = IntelligenceTier.SCRIPTED
    provider: str = Field(default="deterministic", min_length=1, max_length=64)
    model: str = Field(default="scripted-v1", min_length=1, max_length=128)


class AgentKnowledgeMap(StrictModel):
    explored: list[Position] = Field(default_factory=list, max_length=100_000)


class Agent(StrictModel):
    identity: AgentIdentity
    body: AgentBodyState
    mind: MindBinding
    position: Position
    inventory: dict[ResourceKind, int] = Field(default_factory=dict)
    knowledge: AgentKnowledgeMap = Field(default_factory=AgentKnowledgeMap)

    @field_validator("inventory")
    @classmethod
    def inventory_values_are_non_negative(
        cls, value: dict[ResourceKind, int]
    ) -> dict[ResourceKind, int]:
        if any(amount < 0 or amount > 1_000_000 for amount in value.values()):
            raise ValueError("inventory values must be within safe bounds")
        return value


class ExperimentRun(StrictModel):
    run_id: str = Field(pattern=r"^run-[0-9a-f]{12}$")
    world_id: str = Field(pattern=r"^world-[0-9a-f]{12}$")
    mode: ExperimentMode = ExperimentMode.SCRIPTED
    status: RunStatus = RunStatus.CREATED
    modified: bool = False
    engine_version: str = "0.1.0"
    rules_version: str = "block1-v1"
    schema_version: str = "world-state-v1"


class WorldState(StrictModel):
    schema_version: str = "world-state-v1"
    run: ExperimentRun
    seed: int = Field(ge=0, le=2**63 - 1)
    width: int = Field(ge=8, le=512)
    height: int = Field(ge=8, le=512)
    game_minute: int = Field(default=0, ge=0)
    tiles: list[Tile]
    resources: dict[str, ResourceNode]
    agents: dict[str, Agent]
    event_queue: list[ScheduledEvent] = Field(default_factory=list, max_length=1_000_000)
    next_schedule_sequence: int = Field(default=0, ge=0)
    processed_events: int = Field(default=0, ge=0)
    rng_state: int = Field(ge=0, le=2**64 - 1)

    def tile_at(self, position: Position) -> Tile | None:
        if position.x >= self.width or position.y >= self.height:
            return None
        return self.tiles[position.y * self.width + position.x]


class AgentObservation(StrictModel):
    agent_id: str
    name: str
    game_minute: int = Field(ge=0)
    position: Position
    body: AgentBodyState
    inventory: dict[ResourceKind, int]
    visible_tiles: list[Tile]
    visible_resources: list[ResourceNode]
    known_positions: list[Position]


class ActionResult(StrictModel):
    success: bool
    reason: str = Field(max_length=240)
    duration_minutes: int = Field(ge=1, le=24 * 60)
    event_id: str

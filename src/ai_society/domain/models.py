from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_society.domain.enums import (
    CommitmentStatus,
    ExperimentMode,
    IntelligenceTier,
    MessageStatus,
    OfferStatus,
    ResourceKind,
    RunStatus,
    ScheduledEventKind,
    StructureKind,
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
    temperature_milli: int = Field(default=0, ge=0, le=2_000)
    max_output_tokens: int = Field(default=512, ge=32, le=2_048)
    request_budget: int = Field(default=10_000, ge=0, le=1_000_000)
    token_budget: int = Field(default=1_000_000, ge=0, le=100_000_000)
    revision: int = Field(default=0, ge=0)


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


class Structure(StrictModel):
    structure_id: str = Field(pattern=r"^structure-[0-9]{6}$")
    kind: StructureKind
    position: Position
    builder_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    created_minute: int = Field(ge=0)


class Message(StrictModel):
    message_id: str = Field(pattern=r"^message-[0-9]{6}$")
    sender_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    recipient_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    content: str = Field(min_length=1, max_length=2_000)
    sent_minute: int = Field(ge=0)
    deliver_minute: int = Field(ge=0)
    expires_minute: int = Field(ge=0)
    status: MessageStatus = MessageStatus.PENDING
    delivered_minute: int | None = Field(default=None, ge=0)
    reply_to_id: str | None = Field(
        default=None, pattern=r"^message-[0-9]{6}$"
    )
    provenance: str = Field(default="agent_message", min_length=1, max_length=64)


class TradeOffer(StrictModel):
    offer_id: str = Field(pattern=r"^offer-[0-9]{6}$")
    sender_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    recipient_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    offer_resource: ResourceKind
    offer_amount: int = Field(ge=1, le=1_000)
    request_resource: ResourceKind
    request_amount: int = Field(ge=1, le=1_000)
    terms: str = Field(default="", max_length=2_000)
    created_minute: int = Field(ge=0)
    deliver_minute: int = Field(ge=0)
    expires_minute: int = Field(ge=0)
    status: OfferStatus = OfferStatus.PENDING
    responded_minute: int | None = Field(default=None, ge=0)
    version: int = Field(default=1, ge=1)


class Commitment(StrictModel):
    commitment_id: str = Field(pattern=r"^commitment-[0-9]{6}$")
    creator_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    beneficiary_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    terms: str = Field(min_length=1, max_length=4_000)
    provenance: str = Field(min_length=1, max_length=128)
    status: CommitmentStatus = CommitmentStatus.ACTIVE
    created_minute: int = Field(ge=0)
    deadline_minute: int = Field(ge=0)
    resolved_minute: int | None = Field(default=None, ge=0)
    version: int = Field(default=1, ge=1)


class ExperimentRun(StrictModel):
    run_id: str = Field(pattern=r"^run-[0-9a-f]{12}$")
    world_id: str = Field(pattern=r"^world-[0-9a-f]{12}$")
    mode: ExperimentMode = ExperimentMode.SCRIPTED
    status: RunStatus = RunStatus.CREATED
    modified: bool = False
    engine_version: str = "0.2.0"
    rules_version: str = "block2-v1"
    schema_version: Literal["world-state-v2"] = "world-state-v2"


class WorldState(StrictModel):
    # Full cross-reference validation is intentionally construction/import-time only.
    # The authoritative engine mutates top-level clock/counter fields frequently; running
    # an O(world-size) validator on every trusted assignment would make long simulations
    # quadratic in practice.
    model_config = ConfigDict(extra="forbid", validate_assignment=False)

    schema_version: Literal["world-state-v2"] = "world-state-v2"
    run: ExperimentRun
    seed: int = Field(ge=0, le=2**63 - 1)
    width: int = Field(ge=8, le=512)
    height: int = Field(ge=8, le=512)
    game_minute: int = Field(default=0, ge=0)
    tiles: list[Tile]
    resources: dict[str, ResourceNode]
    agents: dict[str, Agent]
    structures: dict[str, Structure] = Field(default_factory=dict)
    messages: dict[str, Message] = Field(default_factory=dict)
    offers: dict[str, TradeOffer] = Field(default_factory=dict)
    commitments: dict[str, Commitment] = Field(default_factory=dict)
    event_queue: list[ScheduledEvent] = Field(default_factory=list, max_length=1_000_000)
    next_schedule_sequence: int = Field(default=0, ge=0)
    next_structure_sequence: int = Field(default=1, ge=1)
    next_message_sequence: int = Field(default=1, ge=1)
    next_offer_sequence: int = Field(default=1, ge=1)
    next_commitment_sequence: int = Field(default=1, ge=1)
    processed_events: int = Field(default=0, ge=0)
    rng_state: int = Field(ge=0, le=2**64 - 1)

    @model_validator(mode="after")
    def validate_world_invariants(self) -> "WorldState":
        """Reject structurally valid snapshots that cannot represent a coherent world."""

        def in_bounds(position: Position) -> bool:
            return position.x < self.width and position.y < self.height

        if len(self.tiles) != self.width * self.height:
            raise ValueError("tile count does not match world dimensions")
        for index, tile in enumerate(self.tiles):
            expected = Position(x=index % self.width, y=index // self.width)
            if tile.position != expected:
                raise ValueError("tiles must cover the world in row-major order")

        for key, resource in self.resources.items():
            if key != resource.entity_id or not in_bounds(resource.position):
                raise ValueError("resource identity or position is inconsistent")
            if resource.quantity > resource.max_quantity:
                raise ValueError("resource quantity exceeds its maximum")

        for key, agent in self.agents.items():
            if key != agent.identity.agent_id or not in_bounds(agent.position):
                raise ValueError("agent identity or position is inconsistent")
            if any(not in_bounds(position) for position in agent.knowledge.explored):
                raise ValueError("agent knowledge contains an out-of-bounds position")

        for key, structure in self.structures.items():
            if (
                key != structure.structure_id
                or structure.builder_id not in self.agents
                or not in_bounds(structure.position)
            ):
                raise ValueError("structure references are inconsistent")

        for key, message in self.messages.items():
            if (
                key != message.message_id
                or message.sender_id not in self.agents
                or message.recipient_id not in self.agents
                or not message.sent_minute <= message.deliver_minute <= message.expires_minute
                or (
                    message.reply_to_id is not None
                    and message.reply_to_id not in self.messages
                )
            ):
                raise ValueError("message references or timing are inconsistent")

        for key, offer in self.offers.items():
            if (
                key != offer.offer_id
                or offer.sender_id not in self.agents
                or offer.recipient_id not in self.agents
                or not offer.created_minute <= offer.deliver_minute <= offer.expires_minute
            ):
                raise ValueError("offer references or timing are inconsistent")

        for key, commitment in self.commitments.items():
            if (
                key != commitment.commitment_id
                or commitment.creator_id not in self.agents
                or commitment.beneficiary_id not in self.agents
                or commitment.deadline_minute < commitment.created_minute
            ):
                raise ValueError("commitment references or timing are inconsistent")

        seen_sequences: set[int] = set()
        subject_maps = {
            ScheduledEventKind.MESSAGE_DELIVERY_DUE: self.messages,
            ScheduledEventKind.MESSAGE_EXPIRY_DUE: self.messages,
            ScheduledEventKind.OFFER_DELIVERY_DUE: self.offers,
            ScheduledEventKind.OFFER_EXPIRY_DUE: self.offers,
            ScheduledEventKind.COMMITMENT_DEADLINE_DUE: self.commitments,
        }
        for scheduled in self.event_queue:
            if scheduled.sequence in seen_sequences:
                raise ValueError("scheduled event sequence is duplicated")
            seen_sequences.add(scheduled.sequence)
            if (
                scheduled.sequence >= self.next_schedule_sequence
                or scheduled.due_minute < self.game_minute
                or scheduled.actor_id not in self.agents
            ):
                raise ValueError("scheduled event metadata is inconsistent")
            if scheduled.kind is ScheduledEventKind.DECISION_DUE:
                if scheduled.subject_id is not None:
                    raise ValueError("agent decisions cannot carry a subject")
            else:
                subjects = subject_maps[scheduled.kind]
                if scheduled.subject_id not in subjects:
                    raise ValueError("scheduled event references a missing subject")

        sequence_contracts = (
            (self.structures, "structure_id", self.next_structure_sequence),
            (self.messages, "message_id", self.next_message_sequence),
            (self.offers, "offer_id", self.next_offer_sequence),
            (self.commitments, "commitment_id", self.next_commitment_sequence),
        )
        for values, attribute, next_sequence in sequence_contracts:
            used = [int(getattr(value, attribute).rsplit("-", 1)[1]) for value in values.values()]
            if next_sequence <= max(used, default=0):
                raise ValueError("entity sequence counter can reuse an existing identifier")
        return self

    def tile_at(self, position: Position) -> Tile | None:
        if position.x >= self.width or position.y >= self.height:
            return None
        return self.tiles[position.y * self.width + position.x]


class VisibleAgent(StrictModel):
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    name: str = Field(min_length=1, max_length=64)
    position: Position


class AgentObservation(StrictModel):
    run_id: str = Field(pattern=r"^run-[0-9a-f]{12}$")
    agent_id: str
    name: str
    long_term_goal: str = Field(max_length=240)
    mind: MindBinding
    game_minute: int = Field(ge=0)
    position: Position
    body: AgentBodyState
    inventory: dict[ResourceKind, int]
    visible_tiles: list[Tile]
    visible_resources: list[ResourceNode]
    visible_agents: list[VisibleAgent] = Field(default_factory=list, max_length=100)
    known_positions: list[Position]
    delivered_messages: list[Message] = Field(default_factory=list, max_length=100)
    accessible_offers: list[TradeOffer] = Field(default_factory=list, max_length=100)
    accessible_commitments: list[Commitment] = Field(
        default_factory=list, max_length=100
    )


class ActionResult(StrictModel):
    success: bool
    reason: str = Field(max_length=240)
    duration_minutes: int = Field(ge=1, le=24 * 60)
    event_id: str

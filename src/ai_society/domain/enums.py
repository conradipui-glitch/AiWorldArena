from enum import StrEnum


class TerrainType(StrEnum):
    WATER = "water"
    SAND = "sand"
    GRASS = "grass"
    FOREST = "forest"
    ROCK = "rock"


class ResourceKind(StrEnum):
    WOOD = "wood"
    STONE = "stone"
    BERRY = "berry"
    WATER = "water"


class ActionKind(StrEnum):
    OBSERVE = "observe"
    MOVE = "move"
    GATHER = "gather"
    CONSUME = "consume"
    REST = "rest"
    WAIT = "wait"
    BUILD_FIRE = "build_fire"
    BUILD_SHELTER = "build_shelter"
    SPEAK = "speak"
    TRANSFER = "transfer"
    CREATE_OFFER = "create_offer"
    RESPOND_TO_OFFER = "respond_to_offer"
    CREATE_PROMISE = "create_promise"
    RESOLVE_PROMISE = "resolve_promise"


class IntelligenceTier(StrEnum):
    REACTIVE = "reactive"
    SCRIPTED = "scripted"
    HYBRID = "hybrid"
    FULL_LLM = "full_llm"


class ExperimentMode(StrEnum):
    SCRIPTED = "scripted"
    NATURAL = "natural"
    CONTROLLED = "controlled"
    REPLICATION = "replication"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class ScheduledEventKind(StrEnum):
    DECISION_DUE = "decision_due"
    MESSAGE_DELIVERY_DUE = "message_delivery_due"
    MESSAGE_EXPIRY_DUE = "message_expiry_due"
    OFFER_DELIVERY_DUE = "offer_delivery_due"
    OFFER_EXPIRY_DUE = "offer_expiry_due"
    COMMITMENT_DEADLINE_DUE = "commitment_deadline_due"


class StructureKind(StrEnum):
    FIRE = "fire"
    SHELTER = "shelter"


class MessageStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    EXPIRED = "expired"


class OfferStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OfferResponse(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class CommitmentStatus(StrEnum):
    ACTIVE = "active"
    FULFILLED = "fulfilled"
    BROKEN = "broken"
    EXPIRED = "expired"


class CommitmentResolution(StrEnum):
    FULFILLED = "fulfilled"
    BROKEN = "broken"


class MemoryLayer(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    SOCIAL = "social"


class WorldEventKind(StrEnum):
    WORLD_CREATED = "world_created"
    AGENT_OBSERVED = "agent_observed"
    AGENT_MOVED = "agent_moved"
    RESOURCE_GATHERED = "resource_gathered"
    RESOURCE_CONSUMED = "resource_consumed"
    AGENT_RESTED = "agent_rested"
    AGENT_WAITED = "agent_waited"
    ACTION_REJECTED = "action_rejected"
    STRUCTURE_BUILT = "structure_built"
    MESSAGE_SENT = "message_sent"
    MESSAGE_DELIVERED = "message_delivered"
    MESSAGE_EXPIRED = "message_expired"
    RESOURCE_TRANSFERRED = "resource_transferred"
    OFFER_CREATED = "offer_created"
    OFFER_DELIVERED = "offer_delivered"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_REJECTED = "offer_rejected"
    OFFER_EXPIRED = "offer_expired"
    COMMITMENT_CREATED = "commitment_created"
    COMMITMENT_FULFILLED = "commitment_fulfilled"
    COMMITMENT_BROKEN = "commitment_broken"
    COMMITMENT_EXPIRED = "commitment_expired"
    MODEL_OUTPUT_REJECTED = "model_output_rejected"
    MODEL_FALLBACK_USED = "model_fallback_used"
    MODEL_REBOUND = "model_rebound"
    SNAPSHOT_IMPORTED = "snapshot_imported"
    SCHEDULED_EVENT_SKIPPED = "scheduled_event_skipped"

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


class WorldEventKind(StrEnum):
    WORLD_CREATED = "world_created"
    AGENT_OBSERVED = "agent_observed"
    AGENT_MOVED = "agent_moved"
    RESOURCE_GATHERED = "resource_gathered"
    RESOURCE_CONSUMED = "resource_consumed"
    AGENT_RESTED = "agent_rested"
    AGENT_WAITED = "agent_waited"
    ACTION_REJECTED = "action_rejected"

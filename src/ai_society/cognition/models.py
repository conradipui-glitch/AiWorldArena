from pydantic import BaseModel, ConfigDict, Field

from ai_society.domain.enums import MemoryLayer


class CognitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MemoryRecord(CognitionModel):
    memory_id: str = Field(pattern=r"^memory-[0-9]{12}$")
    run_id: str = Field(pattern=r"^run-[0-9a-f]{12}$")
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    layer: MemoryLayer
    content: str = Field(min_length=1, max_length=4_000)
    created_minute: int = Field(ge=0)
    last_accessed_minute: int = Field(ge=0)
    last_decay_minute: int = Field(ge=0)
    importance_milli: int = Field(ge=0, le=1_000)
    confidence_milli: int = Field(ge=0, le=1_000)
    access_count: int = Field(ge=0)
    source_kind: str = Field(min_length=1, max_length=64)
    source_actor_id: str | None = Field(default=None, max_length=96)
    source_event_id: str | None = Field(default=None, max_length=96)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    related_agent_id: str | None = Field(default=None, max_length=96)
    parent_memory_ids: tuple[str, ...] = Field(default=(), max_length=30)
    embedding_model: str | None = Field(default=None, max_length=128)
    embedding: tuple[float, ...] | None = Field(default=None, max_length=4_096)
    archived: bool = False


class BeliefRecord(CognitionModel):
    belief_id: str = Field(pattern=r"^belief-[0-9]{12}$")
    run_id: str = Field(pattern=r"^run-[0-9a-f]{12}$")
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    subject: str = Field(min_length=1, max_length=240)
    predicate: str = Field(min_length=1, max_length=120)
    object: str = Field(min_length=1, max_length=1_000)
    confidence_milli: int = Field(ge=0, le=1_000)
    updated_minute: int = Field(ge=0)
    last_decay_minute: int = Field(ge=0)
    source_kind: str = Field(min_length=1, max_length=64)
    source_event_id: str | None = Field(default=None, max_length=96)
    provenance: str = Field(min_length=1, max_length=240)


class ModelUsageSummary(CognitionModel):
    requests: int = Field(ge=0)
    successful_requests: int = Field(ge=0)
    failed_requests: int = Field(ge=0)
    charged_tokens: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_latency_ms: int = Field(ge=0)

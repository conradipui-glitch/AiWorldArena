from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_society.domain.enums import ExperimentMode, ResourceKind
from ai_society.domain.events import WorldEvent
from ai_society.domain.intents import AnyIntent
from ai_society.domain.models import ActionResult, WorldState


class ExperimentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelAssignment(ExperimentModel):
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    temperature_milli: int = Field(default=0, ge=0, le=2_000)


class ExperimentConfig(ExperimentModel):
    seed: int = Field(default=20260715, ge=0, le=2**63 - 1)
    width: Literal[48, 64] = 48
    height: Literal[48, 64] = 48
    agent_names: tuple[str, str, str] = ("Ада", "Борин", "Сайра")
    mode: ExperimentMode = ExperimentMode.SCRIPTED
    model_assignments: tuple[ModelAssignment, ...] = ()
    duration_minutes: Literal[10080] = 10_080

    @model_validator(mode="after")
    def mode_matches_assignments(self) -> "ExperimentConfig":
        expected_ids = {"agent-001", "agent-002", "agent-003"}
        actual_ids = {item.agent_id for item in self.model_assignments}
        if self.mode is ExperimentMode.SCRIPTED:
            if self.model_assignments:
                raise ValueError("scripted mode does not accept model assignments")
            return self
        if self.mode not in {ExperimentMode.NATURAL, ExperimentMode.CONTROLLED}:
            raise ValueError("replication mode is reserved for Block 5")
        if actual_ids != expected_ids or len(self.model_assignments) != 3:
            raise ValueError("natural and controlled modes require one binding per agent")
        bindings = {(item.provider, item.model) for item in self.model_assignments}
        if self.mode is ExperimentMode.CONTROLLED and len(bindings) != 1:
            raise ValueError("controlled mode requires one shared model binding")
        if self.mode is ExperimentMode.NATURAL and len(bindings) < 2:
            raise ValueError("natural mode requires at least two distinct model bindings")
        return self


class RecordedDecision(ExperimentModel):
    ordinal: int = Field(ge=1)
    schedule_sequence: int = Field(ge=0)
    due_minute: int = Field(ge=0)
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    binding_revision: int = Field(ge=0)
    intent: AnyIntent
    context_digest: str = ""
    rejected_outputs: tuple[str, ...] = ()
    fallback_code: str | None = None
    attempt_count: int = Field(default=0, ge=0, le=2)
    provider: str | None = None
    model: str | None = None
    result: ActionResult


class AgentExperimentMetrics(ExperimentModel):
    agent_id: str
    lifespan_minutes: int = Field(ge=0)
    decisions: int = Field(ge=0)
    successful_actions: int = Field(ge=0)
    rejected_actions: int = Field(ge=0)
    resources_gathered: dict[ResourceKind, int]
    resources_spent: dict[ResourceKind, int]
    buildings: int = Field(ge=0)
    interactions: int = Field(ge=0)
    offers: int = Field(ge=0)
    promises_created: int = Field(ge=0)
    promises_fulfilled: int = Field(ge=0)
    promises_broken_or_expired: int = Field(ge=0)
    memory_retrievals: int = Field(ge=0)
    model_requests: int = Field(ge=0)
    charged_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


class ExperimentMetrics(ExperimentModel):
    schema_version: Literal["experiment-metrics-v1"] = "experiment-metrics-v1"
    run_id: str
    duration_minutes: int = Field(ge=0)
    decisions: int = Field(ge=0)
    successful_actions: int = Field(ge=0)
    rejected_actions: int = Field(ge=0)
    structures: int = Field(ge=0)
    projects_completed: int = Field(ge=0)
    interventions: int = Field(ge=0)
    agents: list[AgentExperimentMetrics]


class InterventionRecord(ExperimentModel):
    intervention_id: str = Field(pattern=r"^intervention-[0-9]{6}$")
    game_minute: int = Field(ge=0)
    kind: str = Field(min_length=1, max_length=64)
    actor: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)


class ExperimentBundle(ExperimentModel):
    schema_version: Literal["experiment-bundle-v1"] = "experiment-bundle-v1"
    config: ExperimentConfig
    initial_state: WorldState
    final_state: WorldState
    events: list[WorldEvent]
    decisions: list[RecordedDecision]
    cognition: dict[str, object]
    cognition_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: ExperimentMetrics
    interventions: list[InterventionRecord]
    final_state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    final_event_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

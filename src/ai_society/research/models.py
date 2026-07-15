from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_society.domain.enums import ExperimentMode
from ai_society.experiment.models import ModelAssignment


SAFE_ARTIFACT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunMark(StrEnum):
    CLEAN = "clean"
    MODIFIED = "modified"
    EXPERIMENTAL = "experimental"


class ResearchArtifactKind(StrEnum):
    BASELINE = "baseline"
    EXPERIMENTAL_RERUN = "experimental_rerun"
    REPLICA = "replica"
    INITIAL_SNAPSHOT_BRANCH = "initial_snapshot_branch"


class ParentReference(ResearchModel):
    artifact_name: str = Field(pattern=SAFE_ARTIFACT_PATTERN)
    bundle_digest: str = Field(pattern=SHA256_PATTERN)
    source_snapshot: Literal["bundle.initial_state"] = "bundle.initial_state"


class ReproducibilityManifest(ResearchModel):
    """A deterministic provenance record for one research artifact.

    This is intentionally an integrity record, not a signature or assertion of
    the external origin of a file.
    """

    schema_version: Literal["reproducibility-manifest-v1"] = (
        "reproducibility-manifest-v1"
    )
    artifact_name: str = Field(pattern=SAFE_ARTIFACT_PATTERN)
    artifact_kind: ResearchArtifactKind
    marks: tuple[RunMark, ...] = Field(min_length=1, max_length=2)
    run_id: str = Field(pattern=r"^run-[0-9a-f]{12}$")
    world_id: str = Field(pattern=r"^world-[0-9a-f]{12}$")
    mode: ExperimentMode
    seed: int = Field(ge=0, le=2**63 - 1)
    width: int = Field(ge=1, le=256)
    height: int = Field(ge=1, le=256)
    engine_version: str = Field(min_length=1, max_length=64)
    rules_version: str = Field(min_length=1, max_length=64)
    world_schema_version: str = Field(min_length=1, max_length=64)
    world_contract_digest: str = Field(pattern=SHA256_PATTERN)
    config_digest: str = Field(pattern=SHA256_PATTERN)
    bundle_digest: str = Field(pattern=SHA256_PATTERN)
    initial_state_hash: str = Field(pattern=SHA256_PATTERN)
    final_state_hash: str = Field(pattern=SHA256_PATTERN)
    final_event_digest: str = Field(pattern=SHA256_PATTERN)
    decision_count: int = Field(ge=0)
    model_assignments: tuple[ModelAssignment, ...] = ()
    intervention_count: int = Field(ge=0)
    intervention_digest: str = Field(pattern=SHA256_PATTERN)
    exact_decision_replay_verified: bool
    parent: ParentReference | None = None
    manifest_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_lineage_and_marks(self) -> "ReproducibilityManifest":
        if len(set(self.marks)) != len(self.marks):
            raise ValueError("research marks must not repeat")
        if self.artifact_kind is ResearchArtifactKind.BASELINE:
            if self.parent is not None:
                raise ValueError("baseline artifacts cannot have a parent")
        elif self.parent is None:
            raise ValueError("derived research artifacts require parent provenance")
        if (
            self.artifact_kind is ResearchArtifactKind.INITIAL_SNAPSHOT_BRANCH
            and RunMark.MODIFIED not in self.marks
        ):
            raise ValueError("initial snapshot branches must be marked modified")
        if self.artifact_kind in {
            ResearchArtifactKind.EXPERIMENTAL_RERUN,
            ResearchArtifactKind.REPLICA,
        } and RunMark.EXPERIMENTAL not in self.marks:
            raise ValueError("reruns and replicas must be marked experimental")
        return self


class CatalogEntry(ResearchModel):
    artifact_name: str = Field(pattern=SAFE_ARTIFACT_PATTERN)
    artifact_kind: ResearchArtifactKind
    marks: tuple[RunMark, ...] = Field(min_length=1, max_length=2)
    run_id: str = Field(pattern=r"^run-[0-9a-f]{12}$")
    world_id: str = Field(pattern=r"^world-[0-9a-f]{12}$")
    mode: ExperimentMode
    engine_version: str = Field(min_length=1, max_length=64)
    rules_version: str = Field(min_length=1, max_length=64)
    final_state_hash: str = Field(pattern=SHA256_PATTERN)
    final_event_digest: str = Field(pattern=SHA256_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    parent_artifact_name: str | None = Field(
        default=None, pattern=SAFE_ARTIFACT_PATTERN
    )


class ResearchCatalog(ResearchModel):
    schema_version: Literal["research-catalog-v1"] = "research-catalog-v1"
    entries: list[CatalogEntry] = Field(default_factory=list)
    catalog_digest: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_entries(self) -> "ResearchCatalog":
        names = [entry.artifact_name for entry in self.entries]
        if names != sorted(names) or len(set(names)) != len(names):
            raise ValueError("catalog entries must be unique and sorted by artifact name")
        return self


class ChartPoint(ResearchModel):
    label: str = Field(min_length=1, max_length=128)
    value: int = Field(ge=0)


class Chart(ResearchModel):
    chart_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=160)
    unit: str = Field(min_length=1, max_length=64)
    points: list[ChartPoint] = Field(min_length=1, max_length=32)


class ModelReportRow(ResearchModel):
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    decisions: int = Field(ge=0)
    successful_actions: int = Field(ge=0)
    rejected_actions: int = Field(ge=0)
    model_requests: int = Field(ge=0)
    charged_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


class ResearchReport(ResearchModel):
    schema_version: Literal["research-report-v1"] = "research-report-v1"
    artifact_name: str = Field(pattern=SAFE_ARTIFACT_PATTERN)
    manifest_digest: str = Field(pattern=SHA256_PATTERN)
    summary: dict[str, int | str | bool]
    charts: list[Chart] = Field(min_length=2, max_length=8)
    model_table: list[ModelReportRow] = Field(min_length=1, max_length=32)
    report_digest: str = Field(pattern=SHA256_PATTERN)


class DivergencePoint(ResearchModel):
    stream: Literal["decision", "event"]
    ordinal: int = Field(ge=1)
    game_minute: int = Field(ge=0)
    field: str = Field(min_length=1, max_length=96)
    left_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    right_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)


class ModelComparisonRow(ResearchModel):
    agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    left_provider: str = Field(min_length=1, max_length=64)
    left_model: str = Field(min_length=1, max_length=128)
    right_provider: str = Field(min_length=1, max_length=64)
    right_model: str = Field(min_length=1, max_length=128)
    decision_delta: int
    successful_action_delta: int
    rejected_action_delta: int
    model_request_delta: int
    charged_token_delta: int
    latency_ms_delta: int


class RunComparison(ResearchModel):
    schema_version: Literal["run-comparison-v1"] = "run-comparison-v1"
    left_artifact_name: str = Field(pattern=SAFE_ARTIFACT_PATTERN)
    right_artifact_name: str = Field(pattern=SAFE_ARTIFACT_PATTERN)
    comparable: bool
    comparability_reasons: tuple[str, ...]
    first_divergence: DivergencePoint | None = None
    model_table: list[ModelComparisonRow] = Field(min_length=1, max_length=32)
    comparison_digest: str = Field(pattern=SHA256_PATTERN)

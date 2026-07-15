from __future__ import annotations

from typing import Any

from ai_society.experiment.models import ExperimentBundle, RecordedDecision
from ai_society.persistence.canonical import canonical_digest
from ai_society.research.models import (
    DivergencePoint,
    ModelComparisonRow,
    RunComparison,
)
from ai_society.research.persistence import comparison_digest, world_contract_digest


def _decision_semantics(decision: RecordedDecision) -> dict[str, object]:
    """Keep behavior, omit provider diagnostics that are not behavior itself."""

    result = decision.result.model_dump(mode="json")
    result.pop("event_id", None)
    return {
        "schedule_sequence": decision.schedule_sequence,
        "due_minute": decision.due_minute,
        "agent_id": decision.agent_id,
        "intent": decision.intent.model_dump(mode="json"),
        "result": result,
    }


def _event_semantics(event: Any) -> dict[str, object]:
    return {
        "kind": event.kind.value,
        "game_minute": event.game_minute,
        "actor_id": event.actor_id,
        "payload": event.payload,
    }


def _first_difference(
    left: dict[str, object] | None, right: dict[str, object] | None
) -> str:
    if left is None or right is None:
        return "stream_length"
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            return key
    return "unknown"


def _first_divergence(
    left: ExperimentBundle, right: ExperimentBundle
) -> DivergencePoint | None:
    for ordinal in range(1, max(len(left.decisions), len(right.decisions)) + 1):
        left_item = left.decisions[ordinal - 1] if ordinal <= len(left.decisions) else None
        right_item = (
            right.decisions[ordinal - 1] if ordinal <= len(right.decisions) else None
        )
        left_semantic = (
            None if left_item is None else _decision_semantics(left_item)
        )
        right_semantic = (
            None if right_item is None else _decision_semantics(right_item)
        )
        if left_semantic != right_semantic:
            minute = (
                left_item.due_minute
                if left_item is not None
                else right_item.due_minute
                if right_item is not None
                else 0
            )
            return DivergencePoint(
                stream="decision",
                ordinal=ordinal,
                game_minute=minute,
                field=_first_difference(left_semantic, right_semantic),
                left_digest=(
                    None
                    if left_semantic is None
                    else canonical_digest(left_semantic)
                ),
                right_digest=(
                    None
                    if right_semantic is None
                    else canonical_digest(right_semantic)
                ),
            )

    for ordinal in range(1, max(len(left.events), len(right.events)) + 1):
        left_item = left.events[ordinal - 1] if ordinal <= len(left.events) else None
        right_item = right.events[ordinal - 1] if ordinal <= len(right.events) else None
        left_semantic = None if left_item is None else _event_semantics(left_item)
        right_semantic = None if right_item is None else _event_semantics(right_item)
        if left_semantic != right_semantic:
            minute = (
                left_item.game_minute
                if left_item is not None
                else right_item.game_minute
                if right_item is not None
                else 0
            )
            return DivergencePoint(
                stream="event",
                ordinal=ordinal,
                game_minute=minute,
                field=_first_difference(left_semantic, right_semantic),
                left_digest=(
                    None
                    if left_semantic is None
                    else canonical_digest(left_semantic)
                ),
                right_digest=(
                    None
                    if right_semantic is None
                    else canonical_digest(right_semantic)
                ),
            )
    return None


def _model_rows(left: ExperimentBundle, right: ExperimentBundle) -> list[ModelComparisonRow]:
    left_metrics = {item.agent_id: item for item in left.metrics.agents}
    right_metrics = {item.agent_id: item for item in right.metrics.agents}
    result: list[ModelComparisonRow] = []
    for agent_id in sorted(set(left.initial_state.agents) | set(right.initial_state.agents)):
        left_agent = left.initial_state.agents.get(agent_id)
        right_agent = right.initial_state.agents.get(agent_id)
        if left_agent is None or right_agent is None:
            # Experiment configs validate the fixed three-agent MVP contract.  This
            # guard keeps a malformed imported bundle from making a comparison
            # report look complete.
            continue
        left_metric = left_metrics.get(agent_id)
        right_metric = right_metrics.get(agent_id)
        if left_metric is None or right_metric is None:
            continue
        result.append(
            ModelComparisonRow(
                agent_id=agent_id,
                left_provider=left_agent.mind.provider,
                left_model=left_agent.mind.model,
                right_provider=right_agent.mind.provider,
                right_model=right_agent.mind.model,
                decision_delta=right_metric.decisions - left_metric.decisions,
                successful_action_delta=(
                    right_metric.successful_actions - left_metric.successful_actions
                ),
                rejected_action_delta=(
                    right_metric.rejected_actions - left_metric.rejected_actions
                ),
                model_request_delta=(
                    right_metric.model_requests - left_metric.model_requests
                ),
                charged_token_delta=(
                    right_metric.charged_tokens - left_metric.charged_tokens
                ),
                latency_ms_delta=right_metric.latency_ms - left_metric.latency_ms,
            )
        )
    return result


def compare_bundles(
    left: ExperimentBundle,
    right: ExperimentBundle,
    *,
    left_artifact_name: str,
    right_artifact_name: str,
) -> RunComparison:
    """Compare two verified runs without claiming a causal explanation."""

    reasons: list[str] = []
    if world_contract_digest(left.initial_state) != world_contract_digest(
        right.initial_state
    ):
        reasons.append("different_world_or_personality_contract")
    if left.final_state.run.engine_version != right.final_state.run.engine_version:
        reasons.append("different_engine_version")
    if left.final_state.run.rules_version != right.final_state.run.rules_version:
        reasons.append("different_rules_version")
    if left.config.duration_minutes != right.config.duration_minutes:
        reasons.append("different_duration")
    draft = RunComparison(
        left_artifact_name=left_artifact_name,
        right_artifact_name=right_artifact_name,
        comparable=not reasons,
        comparability_reasons=tuple(reasons),
        first_divergence=None if reasons else _first_divergence(left, right),
        model_table=_model_rows(left, right),
        comparison_digest="0" * 64,
    )
    return draft.model_copy(update={"comparison_digest": comparison_digest(draft)})

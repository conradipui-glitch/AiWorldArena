from __future__ import annotations

from ai_society.cognition.repository import SQLiteCognitionRepository
from ai_society.domain.enums import ExperimentMode, ScheduledEventKind
from ai_society.executive.layer import ExecutiveLayer
from ai_society.experiment.metrics import build_metrics
from ai_society.experiment.models import (
    ExperimentBundle,
    ExperimentConfig,
    InterventionRecord,
    RecordedDecision,
)
from ai_society.experiment.persistence import bundle_digest
from ai_society.persistence.canonical import canonical_digest
from ai_society.simulation.decisions import DecisionResolution
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.policies import PolicyDecision, ScriptedPolicy
from ai_society.simulation.rng import DeterministicRng


class ReplayMismatchError(ValueError):
    pass


class ExperimentRunner:
    def __init__(
        self,
        *,
        config: ExperimentConfig,
        initial_state,
        engine: SimulationEngine,
        cognition: SQLiteCognitionRepository | None = None,
        executive: ExecutiveLayer | None = None,
    ) -> None:
        if config.mode is not ExperimentMode.SCRIPTED and executive is None:
            raise ValueError("natural and controlled modes require an Executive Layer")
        self.config = config
        self.initial_state = initial_state.model_copy(deep=True)
        self.engine = engine
        self.cognition = cognition
        self.executive = executive
        self.decisions: list[RecordedDecision] = []
        self.interventions: list[InterventionRecord] = []

    def record_annotation(
        self,
        *,
        actor: str,
        reason: str,
        kind: str = "researcher_annotation",
    ) -> InterventionRecord:
        """Record explicit researcher context without mutating the authoritative world.

        The MVP deliberately has no free-form world-editing control path.  A
        researcher can still declare an annotation before export, and that
        declaration is carried by the immutable experiment bundle and its
        reproducibility manifest.  State-changing controls must be modelled as
        authoritative world actions in a later, separately reviewed contract.
        """

        record = InterventionRecord(
            intervention_id=f"intervention-{len(self.interventions) + 1:06d}",
            game_minute=self.engine.state.game_minute,
            kind=kind,
            actor=actor,
            reason=reason,
        )
        self.interventions.append(record)
        return record

    async def step(self):
        kind = self.engine.next_scheduled_kind()
        if kind is None:
            return None
        if kind is not ScheduledEventKind.DECISION_DUE:
            return self.engine.process_next_system_event()
        ticket = self.engine.prepare_next_decision()
        if self.executive is not None:
            resolution = await self.executive.resolve(ticket)
        else:
            rng = DeterministicRng(self.engine.state.rng_state)
            raw = self.engine.policy.decide(ticket.observation, rng)
            self.engine.state.rng_state = rng.state
            if isinstance(raw, PolicyDecision):
                resolution = DecisionResolution(
                    intent=raw.intent,
                    rejected_outputs=raw.rejected_outputs,
                    fallback_code="policy_fallback" if raw.fallback_used else None,
                    attempt_count=max(1, len(raw.rejected_outputs)),
                    provider=raw.provider,
                    model=raw.model,
                    binding_revision=ticket.binding_revision,
                )
            else:
                resolution = DecisionResolution(
                    intent=raw,
                    binding_revision=ticket.binding_revision,
                )
        result = self.engine.commit_decision(ticket, resolution)
        if self.executive is not None:
            await self.executive.record_outcome(ticket, resolution, result)
        self.decisions.append(
            RecordedDecision(
                ordinal=len(self.decisions) + 1,
                schedule_sequence=ticket.schedule_sequence,
                due_minute=ticket.due_minute,
                agent_id=ticket.agent_id,
                binding_revision=ticket.binding_revision,
                intent=resolution.intent,
                context_digest=resolution.context_digest,
                rejected_outputs=resolution.rejected_outputs,
                fallback_code=resolution.fallback_code,
                attempt_count=resolution.attempt_count,
                provider=resolution.provider,
                model=resolution.model,
                result=result,
            )
        )
        return result

    async def run_to_completion(self, *, max_events: int = 100_000) -> int:
        completed = 0
        while completed < max_events:
            result = await self.step()
            if result is None:
                break
            completed += 1
        if self.engine.state.run.status.value != "completed":
            raise RuntimeError("experiment did not reach its authoritative end event")
        if self.engine.state.game_minute != self.config.duration_minutes:
            raise RuntimeError("experiment did not end at seven game days")
        return completed

    def export_bundle(self) -> ExperimentBundle:
        if self.engine.state.run.status.value != "completed":
            raise RuntimeError("only a completed experiment can be exported")
        cognition = (
            self.cognition.export_run(self.engine.state.run.run_id)
            if self.cognition is not None
            else {
                "schema_version": 1,
                "run_id": self.engine.state.run.run_id,
                "memories": [],
                "beliefs": [],
                "model_calls": [],
            }
        )
        metrics = build_metrics(
            state=self.engine.state,
            events=self.engine.event_log.events,
            decisions=self.decisions,
            cognition=cognition,
            interventions=self.interventions,
        )
        draft = ExperimentBundle(
            config=self.config,
            initial_state=self.initial_state,
            final_state=self.engine.state.model_copy(deep=True),
            events=list(self.engine.event_log.events),
            decisions=list(self.decisions),
            cognition=cognition,
            cognition_digest=canonical_digest(cognition),
            metrics=metrics,
            interventions=list(self.interventions),
            final_state_hash=self.engine.state_hash,
            final_event_digest=self.engine.event_log.digest,
            bundle_digest="0" * 64,
        )
        return draft.model_copy(update={"bundle_digest": bundle_digest(draft)})


def replay_bundle(bundle: ExperimentBundle) -> SimulationEngine:
    engine = SimulationEngine(
        state=bundle.initial_state.model_copy(deep=True),
        policy=ScriptedPolicy(),
    )
    decision_index = 0
    while True:
        kind = engine.next_scheduled_kind()
        if kind is None:
            break
        if kind is not ScheduledEventKind.DECISION_DUE:
            engine.process_next_system_event()
            continue
        if decision_index >= len(bundle.decisions):
            raise ReplayMismatchError("replay decision stream ended early")
        recorded = bundle.decisions[decision_index]
        ticket = engine.prepare_next_decision()
        if (
            recorded.ordinal != decision_index + 1
            or recorded.schedule_sequence != ticket.schedule_sequence
            or recorded.due_minute != ticket.due_minute
            or recorded.agent_id != ticket.agent_id
            or recorded.binding_revision != ticket.binding_revision
        ):
            raise ReplayMismatchError("recorded decision does not match the replay ticket")
        resolution = DecisionResolution(
            intent=recorded.intent,
            context_digest=recorded.context_digest,
            rejected_outputs=recorded.rejected_outputs,
            fallback_code=recorded.fallback_code,
            attempt_count=recorded.attempt_count,
            provider=recorded.provider,
            model=recorded.model,
            binding_revision=recorded.binding_revision,
        )
        result = engine.commit_decision(ticket, resolution)
        if result != recorded.result:
            raise ReplayMismatchError("replayed action result differs from the recording")
        decision_index += 1
    if decision_index != len(bundle.decisions):
        raise ReplayMismatchError("replay left unused decisions")
    if engine.state_hash != bundle.final_state_hash:
        raise ReplayMismatchError("replayed state hash differs from the recording")
    if engine.event_log.digest != bundle.final_event_digest:
        raise ReplayMismatchError("replayed event digest differs from the recording")
    return engine

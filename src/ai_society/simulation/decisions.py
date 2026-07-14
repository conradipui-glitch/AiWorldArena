from dataclasses import dataclass

from ai_society.domain.intents import AnyIntent
from ai_society.domain.models import AgentObservation


@dataclass(frozen=True, slots=True)
class DecisionTicket:
    schedule_sequence: int
    due_minute: int
    agent_id: str
    binding_revision: int
    observation: AgentObservation


@dataclass(frozen=True, slots=True)
class DecisionResolution:
    intent: AnyIntent
    context_digest: str = ""
    rejected_outputs: tuple[str, ...] = ()
    fallback_code: str | None = None
    attempt_count: int = 0
    provider: str | None = None
    model: str | None = None
    binding_revision: int | None = None


class StaleDecisionError(RuntimeError):
    """Raised when a decision no longer matches the authoritative queue/binding."""

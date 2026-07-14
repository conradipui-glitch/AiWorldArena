from __future__ import annotations

from ai_society.domain.enums import ScheduledEventKind
from ai_society.domain.models import ActionResult
from ai_society.executive.layer import ExecutiveLayer
from ai_society.simulation.decisions import StaleDecisionError
from ai_society.simulation.engine import SimulationEngine


class ExecutiveRunner:
    """Orchestrates provider I/O outside the authoritative simulation kernel."""

    def __init__(self, engine: SimulationEngine, executive: ExecutiveLayer) -> None:
        self.engine = engine
        self.executive = executive
        self._step_lock = executive.run_step_lock(engine.state.run.run_id)

    async def step(self) -> ActionResult | None:
        async with self._step_lock:
            return await self._step_serialized()

    async def _step_serialized(self) -> ActionResult | None:
        for _ in range(3):
            kind = self.engine.next_scheduled_kind()
            if kind is None:
                return None
            if kind is not ScheduledEventKind.DECISION_DUE:
                return self.engine.process_next_system_event()
            ticket = self.engine.prepare_next_decision()
            resolution = await self.executive.resolve(ticket)
            try:
                result = self.engine.commit_decision(ticket, resolution)
            except StaleDecisionError:
                self.engine.record_stale_decision(ticket)
                continue
            await self.executive.record_outcome(ticket, resolution, result)
            return result
        raise StaleDecisionError("decision could not commit after repeated binding changes")

    async def run(self, max_events: int) -> int:
        if max_events < 0:
            raise ValueError("max_events must be non-negative")
        completed = 0
        while completed < max_events:
            result = await self.step()
            if result is None:
                break
            completed += 1
        return completed

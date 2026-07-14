from collections.abc import Iterable

from ai_society.domain.enums import (
    ActionKind,
    ResourceKind,
    RunStatus,
    ScheduledEventKind,
    TerrainType,
    WorldEventKind,
)
from ai_society.domain.events import ScheduledEvent, WorldEvent
from ai_society.domain.intents import (
    AnyIntent,
    ConsumeIntent,
    GatherIntent,
    MoveIntent,
    ObserveIntent,
    RestIntent,
    WaitIntent,
)
from ai_society.domain.models import (
    ActionResult,
    Agent,
    AgentObservation,
    Position,
    WorldState,
)
from ai_society.persistence.canonical import canonical_digest
from ai_society.persistence.event_log import EventLog
from ai_society.simulation.policies import AgentPolicy
from ai_society.simulation.rng import DeterministicRng


ACTION_DURATIONS: dict[ActionKind, int] = {
    ActionKind.OBSERVE: 1,
    ActionKind.MOVE: 6,
    ActionKind.GATHER: 12,
    ActionKind.CONSUME: 2,
    ActionKind.REST: 60,
    ActionKind.WAIT: 5,
}


class SimulationEngine:
    def __init__(
        self,
        *,
        state: WorldState,
        policy: AgentPolicy,
        events: Iterable[WorldEvent] | None = None,
        initialize: bool = True,
    ) -> None:
        self.state = state
        self.policy = policy
        self.event_log = EventLog(events)
        if initialize and not self.state.event_queue and self.state.processed_events == 0:
            self.event_log.append(
                kind=WorldEventKind.WORLD_CREATED,
                game_minute=0,
                payload={
                    "world_id": self.state.run.world_id,
                    "seed": self.state.seed,
                    "width": self.state.width,
                    "height": self.state.height,
                    "agents": len(self.state.agents),
                },
            )
            for agent_id in sorted(self.state.agents):
                self._schedule_decision(agent_id, due_minute=0)

    @classmethod
    def restore(
        cls,
        *,
        state: WorldState,
        events: Iterable[WorldEvent],
        policy: AgentPolicy,
    ) -> "SimulationEngine":
        return cls(state=state, events=events, policy=policy, initialize=False)

    @property
    def state_hash(self) -> str:
        return canonical_digest(self.state)

    def run(self, max_events: int) -> int:
        if max_events < 0:
            raise ValueError("max_events must be non-negative")
        completed = 0
        while completed < max_events and self.step() is not None:
            completed += 1
        return completed

    def step(self) -> ActionResult | None:
        if not self.state.event_queue:
            self.state.run.status = RunStatus.COMPLETED
            return None

        self.state.event_queue.sort(key=lambda item: (item.due_minute, item.sequence))
        scheduled = self.state.event_queue.pop(0)
        self.state.game_minute = scheduled.due_minute
        self.state.run.status = RunStatus.RUNNING
        self.state.processed_events += 1

        agent = self.state.agents.get(scheduled.actor_id)
        if agent is None:
            return self._record_rejection(
                actor_id=scheduled.actor_id,
                action="decision_due",
                reason="scheduled agent does not exist",
                duration=1,
                reschedule=False,
            )
        self._advance_needs(agent)
        if agent.body.health == 0:
            return self._record_rejection(
                actor_id=agent.identity.agent_id,
                action="decision_due",
                reason="agent cannot act at zero health",
                duration=1,
                reschedule=False,
            )

        rng = DeterministicRng(self.state.rng_state)
        observation = self.observe(agent.identity.agent_id)
        intent = self.policy.decide(observation, rng)
        self.state.rng_state = rng.state
        result = self.execute(agent.identity.agent_id, intent)
        self._schedule_decision(
            agent.identity.agent_id,
            due_minute=self.state.game_minute + result.duration_minutes,
        )
        return result

    def observe(self, agent_id: str, radius: int = 2) -> AgentObservation:
        agent = self.state.agents[agent_id]
        visible_tiles = [
            tile
            for tile in self.state.tiles
            if agent.position.manhattan_distance(tile.position) <= radius
        ]
        visible_tiles.sort(key=lambda tile: (tile.position.y, tile.position.x))
        visible_resources = [
            resource
            for resource in self.state.resources.values()
            if resource.quantity > 0
            and agent.position.manhattan_distance(resource.position) <= radius
        ]
        visible_resources.sort(key=lambda resource: resource.entity_id)
        return AgentObservation(
            agent_id=agent_id,
            name=agent.identity.name,
            game_minute=self.state.game_minute,
            position=agent.position,
            body=agent.body.model_copy(deep=True),
            inventory=dict(agent.inventory),
            visible_tiles=[tile.model_copy(deep=True) for tile in visible_tiles],
            visible_resources=[node.model_copy(deep=True) for node in visible_resources],
            known_positions=list(agent.knowledge.explored),
        )

    def execute(self, agent_id: str, intent: AnyIntent) -> ActionResult:
        agent = self.state.agents[agent_id]
        if isinstance(intent, ObserveIntent):
            visible = self.observe(agent_id).visible_tiles
            known = {(position.x, position.y) for position in agent.knowledge.explored}
            for tile in visible:
                known.add((tile.position.x, tile.position.y))
            agent.knowledge.explored = [
                Position(x=x, y=y) for x, y in sorted(known, key=lambda item: (item[1], item[0]))
            ]
            return self._record_success(
                agent_id,
                WorldEventKind.AGENT_OBSERVED,
                intent.action,
                {"tiles_seen": len(visible), "known_tiles": len(known)},
            )

        if isinstance(intent, MoveIntent):
            if agent.position.manhattan_distance(intent.target) != 1:
                return self._reject_intent(agent_id, intent, "target is not adjacent")
            tile = self.state.tile_at(intent.target)
            if tile is None:
                return self._reject_intent(agent_id, intent, "target is outside the world")
            if tile.terrain in {TerrainType.WATER, TerrainType.ROCK}:
                return self._reject_intent(agent_id, intent, "target terrain is not walkable")
            previous = agent.position
            agent.position = intent.target
            return self._record_success(
                agent_id,
                WorldEventKind.AGENT_MOVED,
                intent.action,
                {
                    "from": f"{previous.x},{previous.y}",
                    "to": f"{intent.target.x},{intent.target.y}",
                },
            )

        if isinstance(intent, GatherIntent):
            resource = self.state.resources.get(intent.target_id)
            if resource is None:
                return self._reject_intent(agent_id, intent, "resource does not exist")
            if agent.position.manhattan_distance(resource.position) > 1:
                return self._reject_intent(agent_id, intent, "resource is too far away")
            if resource.quantity < intent.amount:
                return self._reject_intent(agent_id, intent, "resource is depleted")
            resource.quantity -= intent.amount
            agent.inventory[resource.kind] = agent.inventory.get(resource.kind, 0) + intent.amount
            return self._record_success(
                agent_id,
                WorldEventKind.RESOURCE_GATHERED,
                intent.action,
                {
                    "resource_id": resource.entity_id,
                    "resource": resource.kind.value,
                    "amount": intent.amount,
                    "remaining": resource.quantity,
                },
            )

        if isinstance(intent, ConsumeIntent):
            carried = agent.inventory.get(intent.resource, 0)
            if carried < intent.amount:
                return self._reject_intent(agent_id, intent, "resource is not in inventory")
            if intent.resource not in {ResourceKind.BERRY, ResourceKind.WATER}:
                return self._reject_intent(agent_id, intent, "resource is not consumable")
            agent.inventory[intent.resource] = carried - intent.amount
            if intent.resource is ResourceKind.BERRY:
                agent.body.hunger = max(0, agent.body.hunger - 25 * intent.amount)
            else:
                agent.body.energy = min(100, agent.body.energy + 3 * intent.amount)
            return self._record_success(
                agent_id,
                WorldEventKind.RESOURCE_CONSUMED,
                intent.action,
                {
                    "resource": intent.resource.value,
                    "amount": intent.amount,
                    "hunger": agent.body.hunger,
                    "energy": agent.body.energy,
                },
            )

        if isinstance(intent, RestIntent):
            agent.body.energy = min(100, agent.body.energy + 45)
            return self._record_success(
                agent_id,
                WorldEventKind.AGENT_RESTED,
                intent.action,
                {"energy": agent.body.energy},
            )

        if isinstance(intent, WaitIntent):
            return self._record_success(
                agent_id,
                WorldEventKind.AGENT_WAITED,
                intent.action,
                {"reason": intent.reason},
            )
        raise TypeError(f"unsupported intent type: {type(intent).__name__}")

    def summary(self) -> dict[str, str | int]:
        return {
            "run_id": self.state.run.run_id,
            "world_id": self.state.run.world_id,
            "status": self.state.run.status.value,
            "game_minute": self.state.game_minute,
            "processed_events": self.state.processed_events,
            "agents": len(self.state.agents),
            "remaining_resources": sum(node.quantity for node in self.state.resources.values()),
            "state_hash": self.state_hash,
            "event_digest": self.event_log.digest,
        }

    def _schedule_decision(self, agent_id: str, *, due_minute: int) -> None:
        sequence = self.state.next_schedule_sequence
        self.state.next_schedule_sequence += 1
        self.state.event_queue.append(
            ScheduledEvent(
                due_minute=due_minute,
                sequence=sequence,
                kind=ScheduledEventKind.DECISION_DUE,
                actor_id=agent_id,
            )
        )

    def _advance_needs(self, agent: Agent) -> None:
        elapsed = self.state.game_minute - agent.body.last_updated_minute
        if elapsed <= 0:
            return
        hunger_total = agent.body.hunger_remainder_minutes + elapsed
        hunger_change, agent.body.hunger_remainder_minutes = divmod(hunger_total, 30)
        agent.body.hunger = min(100, agent.body.hunger + hunger_change)

        energy_total = agent.body.energy_remainder_minutes + elapsed
        energy_change, agent.body.energy_remainder_minutes = divmod(energy_total, 20)
        agent.body.energy = max(0, agent.body.energy - energy_change)

        if agent.body.hunger == 100 or agent.body.energy == 0:
            health_total = agent.body.health_remainder_minutes + elapsed
            health_change, agent.body.health_remainder_minutes = divmod(health_total, 60)
            agent.body.health = max(0, agent.body.health - health_change)
        agent.body.last_updated_minute = self.state.game_minute

    def _record_success(
        self,
        actor_id: str,
        kind: WorldEventKind,
        action: ActionKind,
        payload: dict[str, str | int | float | bool | None],
    ) -> ActionResult:
        event = self.event_log.append(
            kind=kind,
            game_minute=self.state.game_minute,
            actor_id=actor_id,
            payload={"action": action.value, **payload},
        )
        return ActionResult(
            success=True,
            reason="action completed",
            duration_minutes=ACTION_DURATIONS[action],
            event_id=event.event_id,
        )

    def _reject_intent(self, actor_id: str, intent: AnyIntent, reason: str) -> ActionResult:
        return self._record_rejection(
            actor_id=actor_id,
            action=intent.action.value,
            reason=reason,
            duration=1,
            reschedule=True,
        )

    def _record_rejection(
        self,
        *,
        actor_id: str,
        action: str,
        reason: str,
        duration: int,
        reschedule: bool,
    ) -> ActionResult:
        del reschedule  # scheduling is owned by step(); kept explicit for auditability.
        event = self.event_log.append(
            kind=WorldEventKind.ACTION_REJECTED,
            game_minute=self.state.game_minute,
            actor_id=actor_id,
            payload={"action": action, "reason": reason},
        )
        return ActionResult(
            success=False,
            reason=reason,
            duration_minutes=duration,
            event_id=event.event_id,
        )

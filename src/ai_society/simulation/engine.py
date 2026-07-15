from __future__ import annotations

from collections.abc import Iterable
from threading import RLock

from ai_society.domain.enums import (
    ActionKind,
    CommitmentResolution,
    CommitmentStatus,
    IntelligenceTier,
    MessageStatus,
    OfferResponse,
    OfferStatus,
    ProjectMemberStatus,
    ProjectResponse,
    ProjectStatus,
    ResourceKind,
    RunStatus,
    ScheduledEventKind,
    StructureKind,
    TerrainType,
    WeatherKind,
    WorldEventKind,
)
from ai_society.domain.events import ScheduledEvent, WorldEvent
from ai_society.domain.intents import (
    AttackIntent,
    AnyIntent,
    BuildFireIntent,
    BuildShelterIntent,
    BuildStorageIntent,
    ContributeToProjectIntent,
    ConsumeIntent,
    CreateOfferIntent,
    CreatePromiseIntent,
    CreateProjectIntent,
    GatherIntent,
    MoveIntent,
    ObserveIntent,
    ResolvePromiseIntent,
    RespondToProjectIntent,
    RespondToOfferIntent,
    RestIntent,
    StoreResourceIntent,
    SpeakIntent,
    TransferIntent,
    TakeResourceIntent,
    WaitIntent,
    LeaveProjectIntent,
)
from ai_society.domain.models import (
    ActionResult,
    Agent,
    AgentObservation,
    AgentBodyState,
    AgentIdentity,
    AgentKnowledgeMap,
    Commitment,
    JointProject,
    Message,
    MindBinding,
    Position,
    Structure,
    TradeOffer,
    VisibleAgent,
    WorldState,
    ResourceNode,
    WeatherTransition,
)
from ai_society.persistence.canonical import canonical_digest
from ai_society.persistence.event_log import EventLog
from ai_society.simulation.decisions import (
    DecisionResolution,
    DecisionTicket,
    StaleDecisionError,
)
from ai_society.simulation.policies import AgentPolicy, PolicyDecision
from ai_society.simulation.rng import DeterministicRng


ACTION_DURATIONS: dict[ActionKind, int] = {
    ActionKind.OBSERVE: 1,
    ActionKind.MOVE: 6,
    ActionKind.GATHER: 12,
    ActionKind.CONSUME: 2,
    ActionKind.REST: 60,
    ActionKind.WAIT: 5,
    ActionKind.BUILD_FIRE: 20,
    ActionKind.BUILD_SHELTER: 120,
    ActionKind.BUILD_STORAGE: 90,
    ActionKind.STORE_RESOURCE: 5,
    ActionKind.TAKE_RESOURCE: 5,
    ActionKind.SPEAK: 5,
    ActionKind.TRANSFER: 5,
    ActionKind.CREATE_OFFER: 5,
    ActionKind.RESPOND_TO_OFFER: 5,
    ActionKind.CREATE_PROMISE: 5,
    ActionKind.RESOLVE_PROMISE: 2,
    ActionKind.CREATE_PROJECT: 5,
    ActionKind.RESPOND_TO_PROJECT: 3,
    ActionKind.CONTRIBUTE_TO_PROJECT: 8,
    ActionKind.LEAVE_PROJECT: 3,
    ActionKind.ATTACK: 8,
}

BUILD_COSTS: dict[StructureKind, dict[ResourceKind, int]] = {
    StructureKind.FIRE: {ResourceKind.WOOD: 2},
    StructureKind.SHELTER: {ResourceKind.WOOD: 4, ResourceKind.STONE: 2},
    StructureKind.STORAGE: {ResourceKind.WOOD: 4, ResourceKind.STONE: 2},
}

STORAGE_CAPACITY = 100

VISIBILITY_RADIUS = 2
COMMUNICATION_RADIUS = 4
TRANSFER_RADIUS = 1
MESSAGE_DELIVERY_DELAY = 1
MESSAGE_TTL = 15
OFFER_DELIVERY_DELAY = 1
ACCEPTED_OFFER_DEADLINE = 24 * 60


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
        self._lock = RLock()
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
                self._schedule(
                    kind=ScheduledEventKind.DECISION_DUE,
                    actor_id=agent_id,
                    due_minute=0,
                )
            for transition in self.state.environment.transitions:
                self._schedule(
                    kind=ScheduledEventKind.WEATHER_CHANGE_DUE,
                    actor_id="world",
                    subject_id=transition.transition_id,
                    due_minute=transition.minute,
                )
            if self.state.run.ends_minute is not None:
                self._schedule(
                    kind=ScheduledEventKind.EXPERIMENT_END_DUE,
                    actor_id="world",
                    due_minute=self.state.run.ends_minute,
                )

    @classmethod
    def restore(
        cls,
        *,
        state: WorldState,
        events: Iterable[WorldEvent],
        policy: AgentPolicy,
    ) -> SimulationEngine:
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
        """Compatibility runner for deterministic local policies.

        LLM-backed decisions use ExecutiveRunner so provider I/O remains outside
        the authoritative kernel.
        """
        with self._lock:
            head = self._peek_scheduled()
            if head is None:
                self.state.run.status = RunStatus.COMPLETED
                return None
            if head.kind is not ScheduledEventKind.DECISION_DUE:
                return self._process_next_system_event()
            ticket = self.prepare_next_decision()

        rng = DeterministicRng(self.state.rng_state)
        raw_decision = self.policy.decide(ticket.observation, rng)
        resolution = self._normalize_policy_decision(raw_decision, ticket)
        with self._lock:
            self.state.rng_state = rng.state
            return self.commit_decision(ticket, resolution)

    def prepare_next_decision(self) -> DecisionTicket:
        """Build an agent-scoped, defensive observation without consuming the event."""
        with self._lock:
            scheduled = self._peek_scheduled()
            if scheduled is None or scheduled.kind is not ScheduledEventKind.DECISION_DUE:
                raise RuntimeError("the next scheduled event is not an agent decision")
            agent = self.state.agents.get(scheduled.actor_id)
            if agent is None:
                raise RuntimeError("scheduled decision references a missing agent")
            projected = agent.model_copy(deep=True)
            self._advance_needs_to(projected, scheduled.due_minute)
            observation = self._build_observation(
                projected,
                game_minute=scheduled.due_minute,
                radius=self._vision_radius(projected),
            )
            return DecisionTicket(
                schedule_sequence=scheduled.sequence,
                due_minute=scheduled.due_minute,
                agent_id=scheduled.actor_id,
                binding_revision=agent.mind.revision,
                observation=observation,
            )

    def commit_decision(
        self, ticket: DecisionTicket, resolution: DecisionResolution
    ) -> ActionResult:
        """Atomically accept a still-current decision and mutate the world."""
        with self._lock:
            scheduled = self._peek_scheduled()
            if (
                scheduled is None
                or scheduled.kind is not ScheduledEventKind.DECISION_DUE
                or scheduled.sequence != ticket.schedule_sequence
                or scheduled.actor_id != ticket.agent_id
                or scheduled.due_minute != ticket.due_minute
            ):
                raise StaleDecisionError("scheduled decision changed before commit")
            agent = self.state.agents.get(ticket.agent_id)
            if agent is None or agent.mind.revision != ticket.binding_revision:
                raise StaleDecisionError("model binding changed before decision commit")
            if (
                resolution.binding_revision is not None
                and resolution.binding_revision != ticket.binding_revision
            ):
                raise StaleDecisionError("decision was produced by a stale model binding")

            self.state.event_queue.pop(0)
            self.state.game_minute = scheduled.due_minute
            self.state.run.status = RunStatus.RUNNING
            self.state.processed_events += 1
            self._advance_needs_to(agent, self.state.game_minute)

            if agent.body.health == 0:
                return self._record_rejection(
                    actor_id=agent.identity.agent_id,
                    action="decision_due",
                    reason="agent cannot act at zero health",
                    duration=1,
                    schedule_next=False,
                )

            self._record_decision_diagnostics(ticket, resolution)
            result = self.execute(ticket.agent_id, resolution.intent)
            self._schedule(
                kind=ScheduledEventKind.DECISION_DUE,
                actor_id=ticket.agent_id,
                due_minute=self.state.game_minute + result.duration_minutes,
            )
            return result

    def process_next_system_event(self) -> ActionResult | None:
        with self._lock:
            return self._process_next_system_event()

    def next_scheduled_kind(self) -> ScheduledEventKind | None:
        with self._lock:
            scheduled = self._peek_scheduled()
            return None if scheduled is None else scheduled.kind

    def observe_agent(self, agent_id: str) -> AgentObservation:
        """Return the current world view available to one agent.

        This is deliberately scoped to the selected agent.  Observer clients may
        request it for inspection, but the method never exposes this projection
        to another agent or mutates the authoritative world.
        """
        with self._lock:
            agent = self.state.agents.get(agent_id)
            if agent is None:
                raise LookupError(agent_id)
            projected = agent.model_copy(deep=True)
            self._advance_needs_to(projected, self.state.game_minute)
            return self._build_observation(
                projected,
                game_minute=self.state.game_minute,
                radius=VISIBILITY_RADIUS,
            )

    def record_stale_decision(self, ticket: DecisionTicket) -> WorldEvent:
        with self._lock:
            return self.event_log.append(
                kind=WorldEventKind.MODEL_OUTPUT_REJECTED,
                game_minute=self.state.game_minute,
                actor_id=ticket.agent_id,
                payload={
                    "attempt": 0,
                    "reason_code": "stale_binding_revision",
                    "binding_revision": ticket.binding_revision,
                    "schedule_sequence": ticket.schedule_sequence,
                },
            )

    def observe(self, agent_id: str, radius: int | None = None) -> AgentObservation:
        with self._lock:
            agent = self.state.agents[agent_id].model_copy(deep=True)
            return self._build_observation(
                agent,
                game_minute=self.state.game_minute,
                radius=self._vision_radius(agent) if radius is None else radius,
            )

    def vision_radius(self, agent_id: str) -> int:
        with self._lock:
            return self._vision_radius(self.state.agents[agent_id])

    def execute(self, agent_id: str, intent: AnyIntent) -> ActionResult:
        agent = self.state.agents[agent_id]
        if isinstance(intent, ObserveIntent):
            visible = self.observe(agent_id).visible_tiles
            known = {(position.x, position.y) for position in agent.knowledge.explored}
            for tile in visible:
                known.add((tile.position.x, tile.position.y))
            agent.knowledge.explored = [
                Position(x=x, y=y)
                for x, y in sorted(known, key=lambda item: (item[1], item[0]))
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
                return self._reject_intent(agent_id, intent, "resource is unavailable")
            if agent.position.manhattan_distance(resource.position) > 1:
                return self._reject_intent(agent_id, intent, "resource is unavailable")
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

        if isinstance(intent, AttackIntent):
            target = self._available_agent(
                actor=agent, target_id=intent.target_agent_id, radius=1
            )
            if target is None:
                return self._reject_intent(agent_id, intent, "target is unavailable")
            damage = 14 if agent.identity.long_term_goal.casefold().startswith("[bear]") else 9
            target.body.health = max(0, target.body.health - damage)
            agent.body.energy = max(0, agent.body.energy - 5)
            return self._record_success(
                agent_id,
                WorldEventKind.AGENT_ATTACKED,
                intent.action,
                {
                    "target_agent_id": target.identity.agent_id,
                    "damage": damage,
                    "target_health": target.body.health,
                },
            )

        if isinstance(intent, BuildFireIntent):
            return self._build_structure(
                agent_id, StructureKind.FIRE, intent.location, intent.action, intent
            )

        if isinstance(intent, BuildShelterIntent):
            return self._build_structure(
                agent_id, StructureKind.SHELTER, intent.location, intent.action, intent
            )

        if isinstance(intent, BuildStorageIntent):
            return self._build_structure(
                agent_id, StructureKind.STORAGE, intent.location, intent.action, intent
            )

        if isinstance(intent, StoreResourceIntent):
            storage = self._available_storage(agent, intent.structure_id)
            if storage is None:
                return self._reject_intent(agent_id, intent, "storage is unavailable")
            carried = agent.inventory.get(intent.resource, 0)
            if carried < intent.amount:
                return self._reject_intent(agent_id, intent, "insufficient inventory")
            if sum(storage.inventory.values()) + intent.amount > storage.capacity:
                return self._reject_intent(agent_id, intent, "storage capacity is exceeded")
            agent.inventory[intent.resource] = carried - intent.amount
            storage.inventory[intent.resource] = (
                storage.inventory.get(intent.resource, 0) + intent.amount
            )
            return self._record_success(
                agent_id,
                WorldEventKind.RESOURCE_STORED,
                intent.action,
                {
                    "structure_id": storage.structure_id,
                    "resource": intent.resource.value,
                    "amount": intent.amount,
                },
            )

        if isinstance(intent, TakeResourceIntent):
            storage = self._available_storage(agent, intent.structure_id)
            if storage is None:
                return self._reject_intent(agent_id, intent, "storage is unavailable")
            stored = storage.inventory.get(intent.resource, 0)
            if stored < intent.amount:
                return self._reject_intent(agent_id, intent, "stored resource is unavailable")
            storage.inventory[intent.resource] = stored - intent.amount
            agent.inventory[intent.resource] = (
                agent.inventory.get(intent.resource, 0) + intent.amount
            )
            return self._record_success(
                agent_id,
                WorldEventKind.RESOURCE_TAKEN,
                intent.action,
                {
                    "structure_id": storage.structure_id,
                    "resource": intent.resource.value,
                    "amount": intent.amount,
                },
            )

        if isinstance(intent, SpeakIntent):
            target = self._available_agent(
                actor=agent, target_id=intent.target_agent_id, radius=COMMUNICATION_RADIUS
            )
            if target is None:
                return self._reject_intent(agent_id, intent, "target is unavailable")
            if intent.reply_to_id is not None:
                replied = self.state.messages.get(intent.reply_to_id)
                if (
                    replied is None
                    or replied.status is not MessageStatus.DELIVERED
                    or replied.recipient_id != agent_id
                    or replied.sender_id != target.identity.agent_id
                ):
                    return self._reject_intent(agent_id, intent, "reply context is unavailable")
            message_id = f"message-{self.state.next_message_sequence:06d}"
            self.state.next_message_sequence += 1
            deliver_minute = self.state.game_minute + MESSAGE_DELIVERY_DELAY
            expires_minute = self.state.game_minute + MESSAGE_TTL
            self.state.messages[message_id] = Message(
                message_id=message_id,
                sender_id=agent_id,
                recipient_id=target.identity.agent_id,
                content=intent.message,
                sent_minute=self.state.game_minute,
                deliver_minute=deliver_minute,
                expires_minute=expires_minute,
                reply_to_id=intent.reply_to_id,
            )
            self._schedule(
                kind=ScheduledEventKind.MESSAGE_DELIVERY_DUE,
                actor_id=agent_id,
                subject_id=message_id,
                due_minute=deliver_minute,
            )
            self._schedule(
                kind=ScheduledEventKind.MESSAGE_EXPIRY_DUE,
                actor_id=agent_id,
                subject_id=message_id,
                due_minute=expires_minute,
            )
            return self._record_success(
                agent_id,
                WorldEventKind.MESSAGE_SENT,
                intent.action,
                {
                    "message_id": message_id,
                    "recipient_id": target.identity.agent_id,
                    "deliver_minute": deliver_minute,
                    "expires_minute": expires_minute,
                    "reply_to_id": intent.reply_to_id,
                },
            )

        if isinstance(intent, TransferIntent):
            target = self._available_agent(
                actor=agent, target_id=intent.target_agent_id, radius=TRANSFER_RADIUS
            )
            if target is None:
                return self._reject_intent(agent_id, intent, "target is unavailable")
            carried = agent.inventory.get(intent.resource, 0)
            if carried < intent.amount:
                return self._reject_intent(agent_id, intent, "insufficient inventory")
            agent.inventory[intent.resource] = carried - intent.amount
            target.inventory[intent.resource] = (
                target.inventory.get(intent.resource, 0) + intent.amount
            )
            return self._record_success(
                agent_id,
                WorldEventKind.RESOURCE_TRANSFERRED,
                intent.action,
                {
                    "recipient_id": target.identity.agent_id,
                    "resource": intent.resource.value,
                    "amount": intent.amount,
                },
            )

        if isinstance(intent, CreateOfferIntent):
            target = self._available_agent(
                actor=agent, target_id=intent.target_agent_id, radius=COMMUNICATION_RADIUS
            )
            if target is None:
                return self._reject_intent(agent_id, intent, "target is unavailable")
            if agent.inventory.get(intent.offer_resource, 0) < intent.offer_amount:
                return self._reject_intent(agent_id, intent, "offered resource is unavailable")
            offer_id = f"offer-{self.state.next_offer_sequence:06d}"
            self.state.next_offer_sequence += 1
            deliver_minute = self.state.game_minute + OFFER_DELIVERY_DELAY
            expires_minute = self.state.game_minute + intent.expires_in_minutes
            self.state.offers[offer_id] = TradeOffer(
                offer_id=offer_id,
                sender_id=agent_id,
                recipient_id=target.identity.agent_id,
                offer_resource=intent.offer_resource,
                offer_amount=intent.offer_amount,
                request_resource=intent.request_resource,
                request_amount=intent.request_amount,
                terms=intent.agreement_terms,
                created_minute=self.state.game_minute,
                deliver_minute=deliver_minute,
                expires_minute=expires_minute,
            )
            self._schedule(
                kind=ScheduledEventKind.OFFER_DELIVERY_DUE,
                actor_id=agent_id,
                subject_id=offer_id,
                due_minute=deliver_minute,
            )
            self._schedule(
                kind=ScheduledEventKind.OFFER_EXPIRY_DUE,
                actor_id=agent_id,
                subject_id=offer_id,
                due_minute=expires_minute,
            )
            return self._record_success(
                agent_id,
                WorldEventKind.OFFER_CREATED,
                intent.action,
                {
                    "offer_id": offer_id,
                    "recipient_id": target.identity.agent_id,
                    "deliver_minute": deliver_minute,
                    "expires_minute": expires_minute,
                },
            )

        if isinstance(intent, RespondToOfferIntent):
            offer = self.state.offers.get(intent.offer_id)
            if (
                offer is None
                or offer.recipient_id != agent_id
                or offer.status is not OfferStatus.OPEN
            ):
                return self._reject_intent(agent_id, intent, "offer is unavailable")
            if intent.response is OfferResponse.REJECT:
                offer.responded_minute = self.state.game_minute
                offer.version += 1
                offer.status = OfferStatus.REJECTED
                return self._record_success(
                    agent_id,
                    WorldEventKind.OFFER_REJECTED,
                    intent.action,
                    {"offer_id": offer.offer_id, "sender_id": offer.sender_id},
                )

            sender = self.state.agents.get(offer.sender_id)
            if (
                sender is None
                or sender.inventory.get(offer.offer_resource, 0) < offer.offer_amount
            ):
                return self._reject_intent(
                    agent_id, intent, "offered resource is unavailable"
                )
            try:
                validated_offer = TradeOffer.model_validate(
                    offer.model_dump(mode="python")
                )
                terms = validated_offer.terms if validated_offer.terms.strip() else (
                    f"{offer.sender_id} offers {offer.offer_amount} "
                    f"{offer.offer_resource.value} for {offer.request_amount} "
                    f"{offer.request_resource.value}"
                )
                commitment = self._build_commitment(
                    creator_id=offer.sender_id,
                    beneficiary_id=offer.recipient_id,
                    terms=terms,
                    provenance=f"offer:{offer.offer_id}",
                    deadline_minute=self.state.game_minute + ACCEPTED_OFFER_DEADLINE,
                )
            except ValueError:
                return self._reject_intent(agent_id, intent, "offer terms are invalid")

            offer.responded_minute = self.state.game_minute
            offer.version += 1
            offer.status = OfferStatus.ACCEPTED
            self._store_commitment(commitment)
            self.event_log.append(
                kind=WorldEventKind.COMMITMENT_CREATED,
                game_minute=self.state.game_minute,
                actor_id=offer.sender_id,
                payload={
                    "commitment_id": commitment.commitment_id,
                    "beneficiary_id": commitment.beneficiary_id,
                    "provenance": commitment.provenance,
                    "deadline_minute": commitment.deadline_minute,
                },
            )
            return self._record_success(
                agent_id,
                WorldEventKind.OFFER_ACCEPTED,
                intent.action,
                {
                    "offer_id": offer.offer_id,
                    "commitment_id": commitment.commitment_id,
                    "sender_id": offer.sender_id,
                },
            )

        if isinstance(intent, CreatePromiseIntent):
            target = self._available_agent(
                actor=agent,
                target_id=intent.beneficiary_agent_id,
                radius=COMMUNICATION_RADIUS,
            )
            if target is None:
                return self._reject_intent(agent_id, intent, "target is unavailable")
            commitment = self._create_commitment(
                creator_id=agent_id,
                beneficiary_id=target.identity.agent_id,
                terms=intent.agreement_terms,
                provenance="direct_promise",
                deadline_minute=self.state.game_minute + intent.due_in_minutes,
            )
            return self._record_success(
                agent_id,
                WorldEventKind.COMMITMENT_CREATED,
                intent.action,
                {
                    "commitment_id": commitment.commitment_id,
                    "beneficiary_id": commitment.beneficiary_id,
                    "deadline_minute": commitment.deadline_minute,
                },
            )

        if isinstance(intent, ResolvePromiseIntent):
            commitment = self.state.commitments.get(intent.commitment_id)
            if (
                commitment is None
                or commitment.creator_id != agent_id
                or commitment.status is not CommitmentStatus.ACTIVE
            ):
                return self._reject_intent(agent_id, intent, "commitment is unavailable")
            commitment.status = (
                CommitmentStatus.FULFILLED
                if intent.resolution is CommitmentResolution.FULFILLED
                else CommitmentStatus.BROKEN
            )
            commitment.resolved_minute = self.state.game_minute
            commitment.version += 1
            kind = (
                WorldEventKind.COMMITMENT_FULFILLED
                if commitment.status is CommitmentStatus.FULFILLED
                else WorldEventKind.COMMITMENT_BROKEN
            )
            return self._record_success(
                agent_id,
                kind,
                intent.action,
                {
                    "commitment_id": commitment.commitment_id,
                    "beneficiary_id": commitment.beneficiary_id,
                },
            )

        if isinstance(intent, CreateProjectIntent):
            if intent.structure_kind is not StructureKind.STORAGE:
                return self._reject_intent(
                    agent_id, intent, "only shared storage is available in the MVP"
                )
            if intent.location != agent.position:
                return self._reject_intent(agent_id, intent, "project must start here")
            invited = sorted(set(intent.invited_agent_ids))
            if agent_id in invited or any(item not in self.state.agents for item in invited):
                return self._reject_intent(agent_id, intent, "project invitations are invalid")
            if any(
                self.state.agents[item].position.manhattan_distance(agent.position)
                > COMMUNICATION_RADIUS
                for item in invited
            ):
                return self._reject_intent(agent_id, intent, "invited agent is unavailable")
            project_id = f"project-{self.state.next_project_sequence:06d}"
            self.state.next_project_sequence += 1
            member_status = {agent_id: ProjectMemberStatus.JOINED}
            member_status.update(
                {item: ProjectMemberStatus.INVITED for item in invited}
            )
            self.state.projects[project_id] = JointProject(
                project_id=project_id,
                creator_id=agent_id,
                structure_kind=intent.structure_kind,
                location=intent.location,
                member_status=member_status,
                required_resources=dict(BUILD_COSTS[intent.structure_kind]),
                contributions={agent_id: {}},
                created_minute=self.state.game_minute,
            )
            return self._record_success(
                agent_id,
                WorldEventKind.PROJECT_CREATED,
                intent.action,
                {
                    "project_id": project_id,
                    "structure": intent.structure_kind.value,
                    "invited": ",".join(invited),
                    "position": f"{intent.location.x},{intent.location.y}",
                },
            )

        if isinstance(intent, RespondToProjectIntent):
            project = self.state.projects.get(intent.project_id)
            if (
                project is None
                or project.status is not ProjectStatus.OPEN
                or project.member_status.get(agent_id) is not ProjectMemberStatus.INVITED
            ):
                return self._reject_intent(agent_id, intent, "project invitation is unavailable")
            status = (
                ProjectMemberStatus.JOINED
                if intent.response is ProjectResponse.JOIN
                else ProjectMemberStatus.REFUSED
            )
            project.member_status[agent_id] = status
            project.version += 1
            if status is ProjectMemberStatus.JOINED:
                project.contributions.setdefault(agent_id, {})
            return self._record_success(
                agent_id,
                (
                    WorldEventKind.PROJECT_JOINED
                    if status is ProjectMemberStatus.JOINED
                    else WorldEventKind.PROJECT_REFUSED
                ),
                intent.action,
                {"project_id": project.project_id, "creator_id": project.creator_id},
            )

        if isinstance(intent, ContributeToProjectIntent):
            project = self.state.projects.get(intent.project_id)
            if (
                project is None
                or project.status is not ProjectStatus.OPEN
                or project.member_status.get(agent_id) is not ProjectMemberStatus.JOINED
                or agent.position.manhattan_distance(project.location) > 1
            ):
                return self._reject_intent(agent_id, intent, "project is unavailable")
            required = project.required_resources.get(intent.resource, 0)
            contributed = sum(
                resources.get(intent.resource, 0)
                for resources in project.contributions.values()
            )
            remaining = max(0, required - contributed)
            if remaining == 0:
                return self._reject_intent(agent_id, intent, "resource is not required")
            amount = min(intent.amount, remaining)
            if agent.inventory.get(intent.resource, 0) < amount:
                return self._reject_intent(agent_id, intent, "insufficient inventory")
            agent.inventory[intent.resource] = agent.inventory.get(intent.resource, 0) - amount
            contribution = project.contributions.setdefault(agent_id, {})
            contribution[intent.resource] = contribution.get(intent.resource, 0) + amount
            project.version += 1
            result = self._record_success(
                agent_id,
                WorldEventKind.PROJECT_CONTRIBUTION_ADDED,
                intent.action,
                {
                    "project_id": project.project_id,
                    "resource": intent.resource.value,
                    "amount": amount,
                },
            )
            if self._project_is_funded(project):
                self._complete_project(project)
            return result

        if isinstance(intent, LeaveProjectIntent):
            project = self.state.projects.get(intent.project_id)
            if (
                project is None
                or project.status is not ProjectStatus.OPEN
                or project.creator_id == agent_id
                or project.member_status.get(agent_id) is not ProjectMemberStatus.JOINED
            ):
                return self._reject_intent(agent_id, intent, "project cannot be left")
            project.member_status[agent_id] = ProjectMemberStatus.LEFT
            project.version += 1
            return self._record_success(
                agent_id,
                WorldEventKind.PROJECT_LEFT,
                intent.action,
                {"project_id": project.project_id, "creator_id": project.creator_id},
            )

        raise TypeError(f"unsupported intent type: {type(intent).__name__}")

    def hot_swap_model(
        self,
        agent_id: str,
        *,
        provider: str,
        model: str,
        available_bindings: set[tuple[str, str]],
        temperature_milli: int | None = None,
        max_output_tokens: int | None = None,
    ) -> WorldEvent:
        """Operator-only kernel operation; API/provider registry performs authorization."""
        with self._lock:
            if not available_bindings or (provider, model) not in available_bindings:
                raise ValueError("provider/model binding is not registered")
            agent = self.state.agents.get(agent_id)
            if agent is None:
                raise LookupError(agent_id)
            old = agent.mind.model_copy(deep=True)
            updated = MindBinding(
                intelligence_tier=IntelligenceTier.FULL_LLM,
                provider=provider,
                model=model,
                temperature_milli=(
                    old.temperature_milli
                    if temperature_milli is None
                    else temperature_milli
                ),
                max_output_tokens=(
                    old.max_output_tokens
                    if max_output_tokens is None
                    else max_output_tokens
                ),
                request_budget=old.request_budget,
                token_budget=old.token_budget,
                revision=old.revision + 1,
            )
            agent.mind = updated
            self.state.run.modified = True
            parameter_hash = canonical_digest(
                {
                    "temperature_milli": updated.temperature_milli,
                    "max_output_tokens": updated.max_output_tokens,
                }
            )
            return self.event_log.append(
                kind=WorldEventKind.MODEL_REBOUND,
                game_minute=self.state.game_minute,
                actor_id=agent_id,
                payload={
                    "old_provider": old.provider,
                    "old_model": old.model,
                    "old_revision": old.revision,
                    "new_provider": updated.provider,
                    "new_model": updated.model,
                    "new_revision": updated.revision,
                    "parameter_hash": parameter_hash,
                },
            )

    def spawn_agent(
        self,
        *,
        name: str,
        species: str,
        provider: str,
        model: str,
        personality: str,
        behavior_description: str,
        vision_radius: int,
        position: Position,
        health: int = 100,
        hunger: int = 0,
        energy: int = 100,
    ) -> Agent:
        """Add a researcher-configured actor at an explicit world position."""

        with self._lock:
            if self.state.run.status is RunStatus.COMPLETED:
                raise ValueError("completed experiments cannot be modified")
            tile = self.state.tile_at(position)
            if tile is None or tile.terrain in {TerrainType.WATER, TerrainType.ROCK}:
                raise ValueError("spawn position must be a walkable tile")
            if any(agent.position == position for agent in self.state.agents.values()):
                raise ValueError("spawn position is already occupied")
            used = [int(agent_id.rsplit("-", 1)[1]) for agent_id in self.state.agents]
            ordinal = max(used, default=0) + 1
            if ordinal > 999:
                raise ValueError("the world reached its supported actor limit")
            agent_id = f"agent-{ordinal:03d}"
            profile = (
                f"[{species}] [vision={vision_radius}] {personality.strip()} — "
                f"{behavior_description.strip()}"
            )[:240]
            agent = Agent(
                identity=AgentIdentity(
                    agent_id=agent_id,
                    name=name.strip(),
                    long_term_goal=profile,
                ),
                body=AgentBodyState(
                    health=health,
                    hunger=hunger,
                    energy=energy,
                    last_updated_minute=self.state.game_minute,
                ),
                mind=MindBinding(
                    intelligence_tier=(
                        IntelligenceTier.SCRIPTED
                        if provider == "deterministic"
                        else IntelligenceTier.FULL_LLM
                    ),
                    provider=provider,
                    model=model,
                    temperature_milli=650 if provider != "deterministic" else 0,
                ),
                position=position,
                inventory=(
                    {ResourceKind.BERRY: 1, ResourceKind.WATER: 1}
                    if species == "human"
                    else {}
                ),
                knowledge=AgentKnowledgeMap(),
            )
            self.state.agents[agent_id] = agent
            self.state.run.modified = True
            self.event_log.append(
                kind=WorldEventKind.AGENT_SPAWNED,
                game_minute=self.state.game_minute,
                actor_id=agent_id,
                payload={
                    "species": species,
                    "provider": provider,
                    "model": model,
                    "position": f"{position.x},{position.y}",
                    "provenance": "researcher_intervention",
                },
            )
            self._schedule(
                kind=ScheduledEventKind.DECISION_DUE,
                actor_id=agent_id,
                due_minute=self.state.game_minute + 1,
            )
            return agent.model_copy(deep=True)

    def trigger_research_event(
        self,
        *,
        event_type: str,
        intensity: int,
        duration_minutes: int,
        position: Position | None = None,
        resource_kind: ResourceKind = ResourceKind.BERRY,
    ) -> WorldEvent:
        """Apply a bounded intervention and preserve it in the authoritative log."""

        with self._lock:
            if self.state.run.status is RunStatus.COMPLETED:
                raise ValueError("completed experiments cannot be modified")
            payload: dict[str, str | int | float | bool | None] = {
                "event_type": event_type,
                "intensity": intensity,
                "duration_minutes": duration_minutes,
                "provenance": "researcher_intervention",
            }
            if event_type in {
                "rain",
                "cold_snap",
                "heat_wave",
                "fog",
                "storm",
                "drought",
                "clear",
            }:
                weather = WeatherKind(event_type)
                temperature = {
                    "rain": 9_000,
                    "cold_snap": -8_000,
                    "heat_wave": 38_000,
                    "fog": 12_000,
                    "storm": 4_000,
                    "drought": 33_000,
                    "clear": 18_000,
                }[event_type]
                crisis = event_type in {"cold_snap", "heat_wave", "storm", "drought"}
                self.state.environment.weather = weather
                self.state.environment.ambient_temperature_milli_c = temperature
                self.state.environment.crisis = crisis
                self.state.environment.last_changed_minute = self.state.game_minute
                if event_type == "drought":
                    reduction = max(1, intensity // 5)
                    for resource in self.state.resources.values():
                        if resource.kind in {ResourceKind.WATER, ResourceKind.BERRY}:
                            resource.quantity = max(0, resource.quantity - reduction)
                if event_type != "clear" and duration_minutes > 0:
                    used = [
                        int(item.transition_id.rsplit("-", 1)[1])
                        for item in self.state.environment.transitions
                    ]
                    transition_id = f"weather-{max(used, default=0) + 1:04d}"
                    transition = WeatherTransition(
                        transition_id=transition_id,
                        minute=self.state.game_minute + duration_minutes,
                        weather=WeatherKind.CLEAR,
                        ambient_temperature_milli_c=18_000,
                        crisis=False,
                    )
                    self.state.environment.transitions.append(transition)
                    self.state.environment.transitions.sort(
                        key=lambda item: (item.minute, item.transition_id)
                    )
                    self._schedule(
                        kind=ScheduledEventKind.WEATHER_CHANGE_DUE,
                        actor_id="world",
                        subject_id=transition_id,
                        due_minute=transition.minute,
                    )
            elif event_type == "resource_cache":
                if position is None:
                    raise ValueError("resource event requires a map position")
                tile = self.state.tile_at(position)
                if tile is None or tile.terrain is TerrainType.WATER:
                    raise ValueError("resource cache must be placed on land")
                used = [
                    int(resource_id.rsplit("-", 1)[1])
                    for resource_id in self.state.resources
                ]
                entity_id = f"resource-{max(used, default=0) + 1:06d}"
                quantity = max(1, intensity)
                self.state.resources[entity_id] = ResourceNode(
                    entity_id=entity_id,
                    kind=resource_kind,
                    position=position,
                    quantity=quantity,
                    max_quantity=quantity,
                )
                payload.update(
                    {
                        "resource": resource_kind.value,
                        "quantity": quantity,
                        "position": f"{position.x},{position.y}",
                    }
                )
            elif event_type == "berry_bloom":
                added = 0
                for resource in self.state.resources.values():
                    if resource.kind is ResourceKind.BERRY:
                        increase = max(1, intensity // 4)
                        resource.max_quantity = min(1_000_000, resource.max_quantity + increase)
                        resource.quantity = min(resource.max_quantity, resource.quantity + increase)
                        added += increase
                payload["quantity"] = added
            elif event_type == "epidemic":
                damage = max(1, intensity // 4)
                affected = 0
                for agent in self.state.agents.values():
                    if agent.body.health > 0:
                        agent.body.health = max(0, agent.body.health - damage)
                        affected += 1
                payload.update({"damage": damage, "affected": affected})
            elif event_type == "meteor":
                if position is None:
                    raise ValueError("meteor event requires a map position")
                damage = max(5, intensity // 2)
                affected = 0
                for agent in self.state.agents.values():
                    if agent.position.manhattan_distance(position) <= 2:
                        agent.body.health = max(0, agent.body.health - damage)
                        affected += 1
                depleted = 0
                for resource in self.state.resources.values():
                    if resource.position.manhattan_distance(position) <= 2:
                        depleted += resource.quantity
                        resource.quantity = 0
                payload.update(
                    {
                        "position": f"{position.x},{position.y}",
                        "damage": damage,
                        "affected": affected,
                        "depleted_resources": depleted,
                    }
                )
            else:
                raise ValueError("unknown researcher event")
            self.state.run.modified = True
            return self.event_log.append(
                kind=WorldEventKind.RESEARCHER_EVENT_TRIGGERED,
                game_minute=self.state.game_minute,
                actor_id="researcher",
                payload=payload,
            )

    def mark_snapshot_imported(
        self, *, source_state_hash: str, source_event_digest: str
    ) -> WorldEvent:
        """Record that an integrity-checked snapshot has no authenticated provenance."""

        with self._lock:
            self.state.run.modified = True
            return self.event_log.append(
                kind=WorldEventKind.SNAPSHOT_IMPORTED,
                game_minute=self.state.game_minute,
                payload={
                    "source_state_hash": source_state_hash,
                    "source_event_digest": source_event_digest,
                    "provenance": "unverified_import",
                },
            )

    def summary(self) -> dict[str, str | int]:
        return {
            "run_id": self.state.run.run_id,
            "world_id": self.state.run.world_id,
            "status": self.state.run.status.value,
            "modified": self.state.run.modified,
            "game_minute": self.state.game_minute,
            "processed_events": self.state.processed_events,
            "agents": len(self.state.agents),
            "structures": len(self.state.structures),
            "messages": len(self.state.messages),
            "commitments": len(self.state.commitments),
            "projects": len(self.state.projects),
            "weather": self.state.environment.weather.value,
            "remaining_resources": sum(
                node.quantity for node in self.state.resources.values()
            ),
            "state_hash": self.state_hash,
            "event_digest": self.event_log.digest,
        }

    def _peek_scheduled(self) -> ScheduledEvent | None:
        if not self.state.event_queue:
            return None
        self.state.event_queue.sort(key=lambda item: (item.due_minute, item.sequence))
        return self.state.event_queue[0]

    def _process_next_system_event(self) -> ActionResult | None:
        scheduled = self._peek_scheduled()
        if scheduled is None:
            self.state.run.status = RunStatus.COMPLETED
            return None
        if scheduled.kind is ScheduledEventKind.DECISION_DUE:
            raise RuntimeError("the next event is an agent decision")
        self.state.event_queue.pop(0)
        self.state.game_minute = scheduled.due_minute
        self.state.run.status = RunStatus.RUNNING
        self.state.processed_events += 1
        subject_id = scheduled.subject_id

        if scheduled.kind in {
            ScheduledEventKind.MESSAGE_DELIVERY_DUE,
            ScheduledEventKind.MESSAGE_EXPIRY_DUE,
        }:
            message = self.state.messages.get(subject_id or "")
            if message is None or message.status is not MessageStatus.PENDING:
                return self._record_skipped(scheduled, "message transition is no longer applicable")
            if scheduled.kind is ScheduledEventKind.MESSAGE_EXPIRY_DUE:
                message.status = MessageStatus.EXPIRED
                return self._record_scheduled_result(
                    WorldEventKind.MESSAGE_EXPIRED,
                    scheduled.actor_id,
                    {"message_id": message.message_id, "recipient_id": message.recipient_id},
                    "message expired",
                )
            sender = self.state.agents.get(message.sender_id)
            recipient = self.state.agents.get(message.recipient_id)
            if (
                sender is None
                or recipient is None
                or sender.body.health == 0
                or recipient.body.health == 0
                or sender.position.manhattan_distance(recipient.position)
                > COMMUNICATION_RADIUS
            ):
                message.status = MessageStatus.EXPIRED
                return self._record_scheduled_result(
                    WorldEventKind.MESSAGE_EXPIRED,
                    message.sender_id,
                    {"message_id": message.message_id, "recipient_id": message.recipient_id},
                    "message could not be delivered",
                )
            message.status = MessageStatus.DELIVERED
            message.delivered_minute = self.state.game_minute
            return self._record_scheduled_result(
                WorldEventKind.MESSAGE_DELIVERED,
                message.sender_id,
                {"message_id": message.message_id, "recipient_id": message.recipient_id},
                "message delivered",
            )

        if scheduled.kind is ScheduledEventKind.WEATHER_CHANGE_DUE:
            transition = next(
                (
                    item
                    for item in self.state.environment.transitions
                    if item.transition_id == subject_id
                ),
                None,
            )
            if transition is None:
                return self._record_skipped(scheduled, "weather transition is unavailable")
            for agent in self.state.agents.values():
                self._advance_needs_to(agent, self.state.game_minute)
            was_crisis = self.state.environment.crisis
            self.state.environment.weather = transition.weather
            self.state.environment.ambient_temperature_milli_c = (
                transition.ambient_temperature_milli_c
            )
            self.state.environment.crisis = transition.crisis
            self.state.environment.last_changed_minute = self.state.game_minute
            if transition.crisis and not was_crisis:
                kind = WorldEventKind.WEATHER_CRISIS_STARTED
            elif was_crisis and not transition.crisis:
                kind = WorldEventKind.WEATHER_CRISIS_ENDED
            else:
                kind = WorldEventKind.WEATHER_CHANGED
            return self._record_scheduled_result(
                kind,
                "world",
                {
                    "transition_id": transition.transition_id,
                    "weather": transition.weather.value,
                    "ambient_temperature_milli_c": transition.ambient_temperature_milli_c,
                    "crisis": transition.crisis,
                },
                "weather changed",
            )

        if scheduled.kind is ScheduledEventKind.EXPERIMENT_END_DUE:
            for agent in self.state.agents.values():
                self._advance_needs_to(agent, self.state.game_minute)
            self.state.event_queue.clear()
            self.state.run.status = RunStatus.COMPLETED
            return self._record_scheduled_result(
                WorldEventKind.EXPERIMENT_COMPLETED,
                "world",
                {"duration_minutes": self.state.game_minute},
                "experiment completed",
            )

        if scheduled.kind in {
            ScheduledEventKind.OFFER_DELIVERY_DUE,
            ScheduledEventKind.OFFER_EXPIRY_DUE,
        }:
            offer = self.state.offers.get(subject_id or "")
            if offer is None or offer.status not in {OfferStatus.PENDING, OfferStatus.OPEN}:
                return self._record_skipped(scheduled, "offer transition is no longer applicable")
            if scheduled.kind is ScheduledEventKind.OFFER_EXPIRY_DUE:
                offer.status = OfferStatus.EXPIRED
                offer.version += 1
                return self._record_scheduled_result(
                    WorldEventKind.OFFER_EXPIRED,
                    offer.sender_id,
                    {"offer_id": offer.offer_id, "recipient_id": offer.recipient_id},
                    "offer expired",
                )
            if offer.status is not OfferStatus.PENDING:
                return self._record_skipped(scheduled, "offer is already delivered")
            sender = self.state.agents.get(offer.sender_id)
            recipient = self.state.agents.get(offer.recipient_id)
            if (
                sender is None
                or recipient is None
                or sender.body.health == 0
                or recipient.body.health == 0
                or sender.position.manhattan_distance(recipient.position)
                > COMMUNICATION_RADIUS
            ):
                offer.status = OfferStatus.EXPIRED
                offer.version += 1
                return self._record_scheduled_result(
                    WorldEventKind.OFFER_EXPIRED,
                    offer.sender_id,
                    {"offer_id": offer.offer_id, "recipient_id": offer.recipient_id},
                    "offer could not be delivered",
                )
            offer.status = OfferStatus.OPEN
            offer.version += 1
            return self._record_scheduled_result(
                WorldEventKind.OFFER_DELIVERED,
                offer.sender_id,
                {"offer_id": offer.offer_id, "recipient_id": offer.recipient_id},
                "offer delivered",
            )

        if scheduled.kind is ScheduledEventKind.COMMITMENT_DEADLINE_DUE:
            commitment = self.state.commitments.get(subject_id or "")
            if commitment is None or commitment.status is not CommitmentStatus.ACTIVE:
                return self._record_skipped(
                    scheduled, "commitment transition is no longer applicable"
                )
            commitment.status = CommitmentStatus.EXPIRED
            commitment.resolved_minute = self.state.game_minute
            commitment.version += 1
            return self._record_scheduled_result(
                WorldEventKind.COMMITMENT_EXPIRED,
                commitment.creator_id,
                {
                    "commitment_id": commitment.commitment_id,
                    "beneficiary_id": commitment.beneficiary_id,
                },
                "commitment expired",
            )
        return self._record_skipped(scheduled, "unknown scheduled event kind")

    def _build_observation(
        self, agent: Agent, *, game_minute: int, radius: int
    ) -> AgentObservation:
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
        visible_structures = [
            structure
            for structure in self.state.structures.values()
            if agent.position.manhattan_distance(structure.position) <= radius
        ]
        visible_structures.sort(key=lambda structure: structure.structure_id)
        visible_agents = [
            VisibleAgent(
                agent_id=other.identity.agent_id,
                name=other.identity.name,
                position=other.position,
                species=self._species_for(other),
            )
            for other in self.state.agents.values()
            if other.identity.agent_id != agent.identity.agent_id
            and agent.position.manhattan_distance(other.position) <= radius
        ]
        visible_agents.sort(key=lambda item: item.agent_id)
        messages = [
            message
            for message in self.state.messages.values()
            if message.status is MessageStatus.DELIVERED
            and agent.identity.agent_id in {message.sender_id, message.recipient_id}
        ]
        messages.sort(key=lambda item: (item.delivered_minute or 0, item.message_id))
        offers = [
            offer
            for offer in self.state.offers.values()
            if offer.sender_id == agent.identity.agent_id
            or (
                offer.recipient_id == agent.identity.agent_id
                and offer.status is not OfferStatus.PENDING
            )
        ]
        offers.sort(key=lambda item: item.offer_id)
        commitments = [
            commitment
            for commitment in self.state.commitments.values()
            if agent.identity.agent_id
            in {commitment.creator_id, commitment.beneficiary_id}
        ]
        commitments.sort(key=lambda item: item.commitment_id)
        projects = [
            project
            for project in self.state.projects.values()
            if agent.identity.agent_id in project.member_status
        ]
        projects.sort(key=lambda item: item.project_id)
        return AgentObservation(
            run_id=self.state.run.run_id,
            agent_id=agent.identity.agent_id,
            name=agent.identity.name,
            long_term_goal=agent.identity.long_term_goal,
            mind=agent.mind.model_copy(deep=True),
            game_minute=game_minute,
            position=agent.position,
            body=agent.body.model_copy(deep=True),
            environment=self.state.environment.model_copy(deep=True),
            inventory=dict(agent.inventory),
            visible_tiles=[tile.model_copy(deep=True) for tile in visible_tiles],
            visible_resources=[node.model_copy(deep=True) for node in visible_resources],
            visible_structures=[
                structure.model_copy(deep=True) for structure in visible_structures
            ],
            visible_agents=[item.model_copy(deep=True) for item in visible_agents],
            known_positions=list(agent.knowledge.explored),
            delivered_messages=[item.model_copy(deep=True) for item in messages[-100:]],
            accessible_offers=[item.model_copy(deep=True) for item in offers[-100:]],
            accessible_commitments=[
                item.model_copy(deep=True) for item in commitments[-100:]
            ],
            accessible_projects=[item.model_copy(deep=True) for item in projects[-100:]],
        )

    @staticmethod
    def _species_for(agent: Agent) -> str:
        goal = agent.identity.long_term_goal
        if goal.startswith("[") and "]" in goal:
            return goal[1:].split("]", 1)[0]
        return "human"

    def _vision_radius(self, agent: Agent) -> int:
        if self.state.run.rules_version == "block4-v1":
            return VISIBILITY_RADIUS
        goal = agent.identity.long_term_goal
        marker = "[vision="
        if marker in goal:
            raw = goal.split(marker, 1)[1].split("]", 1)[0]
            try:
                radius = max(1, min(8, int(raw)))
            except ValueError:
                radius = 3
        else:
            radius = {"human": 5, "wolf": 3, "bear": 2, "boar": 2}.get(
                self._species_for(agent), 3
            )
        if self.state.environment.weather is WeatherKind.FOG:
            return max(1, radius - 2)
        if self.state.environment.weather is WeatherKind.STORM:
            return max(1, radius - 1)
        return radius

    def _build_structure(
        self,
        agent_id: str,
        kind: StructureKind,
        location: Position,
        action: ActionKind,
        intent: AnyIntent,
    ) -> ActionResult:
        agent = self.state.agents[agent_id]
        if location != agent.position:
            return self._reject_intent(agent_id, intent, "structure must be built here")
        if any(
            structure.kind is kind and structure.position == location
            for structure in self.state.structures.values()
        ):
            return self._reject_intent(agent_id, intent, "structure already exists here")
        costs = BUILD_COSTS[kind]
        if any(agent.inventory.get(resource, 0) < amount for resource, amount in costs.items()):
            return self._reject_intent(agent_id, intent, "insufficient building resources")
        for resource, amount in costs.items():
            agent.inventory[resource] = agent.inventory.get(resource, 0) - amount
        structure_id = f"structure-{self.state.next_structure_sequence:06d}"
        self.state.next_structure_sequence += 1
        self.state.structures[structure_id] = Structure(
            structure_id=structure_id,
            kind=kind,
            position=location,
            builder_id=agent_id,
            created_minute=self.state.game_minute,
            contributor_ids=[agent_id],
            capacity=STORAGE_CAPACITY if kind is StructureKind.STORAGE else 0,
        )
        return self._record_success(
            agent_id,
            WorldEventKind.STRUCTURE_BUILT,
            action,
            {
                "structure_id": structure_id,
                "structure": kind.value,
                "position": f"{location.x},{location.y}",
            },
        )

    def _create_commitment(
        self,
        *,
        creator_id: str,
        beneficiary_id: str,
        terms: str,
        provenance: str,
        deadline_minute: int,
    ) -> Commitment:
        commitment = self._build_commitment(
            creator_id=creator_id,
            beneficiary_id=beneficiary_id,
            terms=terms,
            provenance=provenance,
            deadline_minute=deadline_minute,
        )
        self._store_commitment(commitment)
        return commitment

    def _build_commitment(
        self,
        *,
        creator_id: str,
        beneficiary_id: str,
        terms: str,
        provenance: str,
        deadline_minute: int,
    ) -> Commitment:
        commitment_id = f"commitment-{self.state.next_commitment_sequence:06d}"
        return Commitment(
            commitment_id=commitment_id,
            creator_id=creator_id,
            beneficiary_id=beneficiary_id,
            terms=terms,
            provenance=provenance,
            created_minute=self.state.game_minute,
            deadline_minute=deadline_minute,
        )

    def _store_commitment(self, commitment: Commitment) -> None:
        expected_id = f"commitment-{self.state.next_commitment_sequence:06d}"
        if commitment.commitment_id != expected_id:
            raise ValueError("commitment sequence changed before persistence")
        self.state.next_commitment_sequence += 1
        self.state.commitments[commitment.commitment_id] = commitment
        self._schedule(
            kind=ScheduledEventKind.COMMITMENT_DEADLINE_DUE,
            actor_id=commitment.creator_id,
            subject_id=commitment.commitment_id,
            due_minute=commitment.deadline_minute,
        )

    def _available_agent(
        self, *, actor: Agent, target_id: str, radius: int
    ) -> Agent | None:
        target = self.state.agents.get(target_id)
        if (
            target is None
            or target.identity.agent_id == actor.identity.agent_id
            or target.body.health == 0
            or actor.position.manhattan_distance(target.position) > radius
        ):
            return None
        return target

    def _available_storage(self, agent: Agent, structure_id: str) -> Structure | None:
        structure = self.state.structures.get(structure_id)
        if (
            structure is None
            or structure.kind is not StructureKind.STORAGE
            or agent.position.manhattan_distance(structure.position) > 1
        ):
            return None
        return structure

    @staticmethod
    def _project_is_funded(project: JointProject) -> bool:
        return all(
            sum(resources.get(resource, 0) for resources in project.contributions.values())
            >= required
            for resource, required in project.required_resources.items()
        )

    def _complete_project(self, project: JointProject) -> None:
        completed_project = JointProject.model_validate(
            {
                **project.model_dump(mode="python"),
                "status": ProjectStatus.COMPLETED,
                "completed_minute": self.state.game_minute,
                "version": project.version + 1,
            }
        )
        self.state.projects[project.project_id] = completed_project
        project = completed_project
        structure_id = f"structure-{self.state.next_structure_sequence:06d}"
        self.state.next_structure_sequence += 1
        contributors = sorted(
            agent_id
            for agent_id, resources in project.contributions.items()
            if sum(resources.values()) > 0
        )
        self.state.structures[structure_id] = Structure(
            structure_id=structure_id,
            kind=project.structure_kind,
            position=project.location,
            builder_id=project.creator_id,
            created_minute=self.state.game_minute,
            contributor_ids=contributors,
            capacity=STORAGE_CAPACITY,
        )
        self.event_log.append(
            kind=WorldEventKind.PROJECT_COMPLETED,
            game_minute=self.state.game_minute,
            actor_id=project.creator_id,
            payload={
                "project_id": project.project_id,
                "structure_id": structure_id,
                "contributors": ",".join(contributors),
            },
        )

    def _schedule(
        self,
        *,
        kind: ScheduledEventKind,
        actor_id: str,
        due_minute: int,
        subject_id: str | None = None,
    ) -> None:
        sequence = self.state.next_schedule_sequence
        self.state.next_schedule_sequence += 1
        self.state.event_queue.append(
            ScheduledEvent(
                due_minute=due_minute,
                sequence=sequence,
                kind=kind,
                actor_id=actor_id,
                subject_id=subject_id,
            )
        )

    def _advance_needs_to(self, agent: Agent, game_minute: int) -> None:
        elapsed = game_minute - agent.body.last_updated_minute
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
        protected = any(
            structure.position == agent.position
            and structure.kind in {StructureKind.FIRE, StructureKind.SHELTER}
            for structure in self.state.structures.values()
        )
        cold_rate = 0
        if not protected:
            if self.state.environment.weather is WeatherKind.COLD_SNAP:
                cold_rate = 250
            elif self.state.environment.weather is WeatherKind.STORM:
                cold_rate = 180
            elif self.state.environment.weather is WeatherKind.RAIN:
                cold_rate = 80
        if cold_rate:
            cold_steps = elapsed // 30
            agent.body.body_temperature_milli_c = max(
                30_000,
                agent.body.body_temperature_milli_c - cold_rate * cold_steps,
            )
        elif agent.body.body_temperature_milli_c < 37_000:
            recovery_steps = elapsed // 30
            agent.body.body_temperature_milli_c = min(
                37_000,
                agent.body.body_temperature_milli_c + 120 * recovery_steps,
            )
        if agent.body.body_temperature_milli_c <= 35_000:
            agent.body.health = max(0, agent.body.health - elapsed // 60)
        if self.state.environment.weather in {WeatherKind.HEAT_WAVE, WeatherKind.DROUGHT}:
            agent.body.energy = max(0, agent.body.energy - elapsed // 30)
        agent.body.last_updated_minute = game_minute

    def _record_decision_diagnostics(
        self, ticket: DecisionTicket, resolution: DecisionResolution
    ) -> None:
        for attempt, rejection_code in enumerate(resolution.rejected_outputs, start=1):
            self.event_log.append(
                kind=WorldEventKind.MODEL_OUTPUT_REJECTED,
                game_minute=self.state.game_minute,
                actor_id=ticket.agent_id,
                payload={
                    "attempt": attempt,
                    "reason_code": rejection_code,
                    "provider": resolution.provider,
                    "model": resolution.model,
                    "binding_revision": ticket.binding_revision,
                    "context_digest": resolution.context_digest or None,
                },
            )
        if resolution.fallback_code is not None:
            self.event_log.append(
                kind=WorldEventKind.MODEL_FALLBACK_USED,
                game_minute=self.state.game_minute,
                actor_id=ticket.agent_id,
                payload={
                    "fallback_code": resolution.fallback_code,
                    "attempt_count": resolution.attempt_count,
                    "provider": resolution.provider,
                    "model": resolution.model,
                    "binding_revision": ticket.binding_revision,
                },
            )

    @staticmethod
    def _normalize_policy_decision(
        raw: AnyIntent | PolicyDecision, ticket: DecisionTicket
    ) -> DecisionResolution:
        if isinstance(raw, PolicyDecision):
            return DecisionResolution(
                intent=raw.intent,
                rejected_outputs=raw.rejected_outputs,
                fallback_code="policy_fallback" if raw.fallback_used else None,
                attempt_count=max(1, len(raw.rejected_outputs)),
                provider=raw.provider,
                model=raw.model,
                binding_revision=(
                    ticket.binding_revision
                    if raw.binding_revision is None
                    else raw.binding_revision
                ),
            )
        return DecisionResolution(
            intent=raw,
            attempt_count=0,
            binding_revision=ticket.binding_revision,
        )

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

    def _reject_intent(
        self, actor_id: str, intent: AnyIntent, reason: str
    ) -> ActionResult:
        return self._record_rejection(
            actor_id=actor_id,
            action=intent.action.value,
            reason=reason,
            duration=1,
            schedule_next=True,
        )

    def _record_rejection(
        self,
        *,
        actor_id: str,
        action: str,
        reason: str,
        duration: int,
        schedule_next: bool,
    ) -> ActionResult:
        del schedule_next  # commit_decision owns decision rescheduling.
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

    def _record_scheduled_result(
        self,
        kind: WorldEventKind,
        actor_id: str,
        payload: dict[str, str | int | float | bool | None],
        reason: str,
    ) -> ActionResult:
        event = self.event_log.append(
            kind=kind,
            game_minute=self.state.game_minute,
            actor_id=actor_id,
            payload=payload,
        )
        return ActionResult(
            success=True,
            reason=reason,
            duration_minutes=1,
            event_id=event.event_id,
        )

    def _record_skipped(
        self, scheduled: ScheduledEvent, reason: str
    ) -> ActionResult:
        return self._record_scheduled_result(
            WorldEventKind.SCHEDULED_EVENT_SKIPPED,
            scheduled.actor_id,
            {
                "scheduled_kind": scheduled.kind.value,
                "subject_id": scheduled.subject_id,
                "reason": reason,
            },
            reason,
        )

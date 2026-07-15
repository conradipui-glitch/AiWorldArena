"""Read models and headless run control for the Block 3 observer.

The browser is a replaceable observer.  This module owns the small amount of
runtime orchestration needed to keep a scripted simulation moving while no
browser is connected, and projects authoritative state into Russian observer
views.  It never accepts a client-supplied world state or client-generated
events.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_society.cognition.embeddings import DeterministicEmbeddingProvider
from ai_society.cognition.repository import SQLiteCognitionRepository
from ai_society.domain.enums import (
    IntelligenceTier,
    MemoryLayer,
    ResourceKind,
    RunStatus,
    ScheduledEventKind,
    WorldEventKind,
)
from ai_society.domain.events import WorldEvent
from ai_society.domain.models import ActionResult, Position
from ai_society.executive.layer import ExecutiveLayer
from ai_society.executive.projector import CognitionProjector
from ai_society.experiment.models import ExperimentConfig
from ai_society.experiment.scenario import (
    ExperimentalScriptedPolicy,
    create_experiment_world,
)
from ai_society.persistence.repository import SnapshotRepository
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy
from ai_society.providers.registry import ProviderRegistry


ACTION_LABELS = {
    "observe": "Осмотр",
    "move": "Перемещение",
    "gather": "Сбор ресурсов",
    "consume": "Приём пищи",
    "rest": "Отдых",
    "wait": "Ожидание",
    "build_fire": "Строительство костра",
    "build_shelter": "Строительство укрытия",
    "build_storage": "Строительство хранилища",
    "store_resource": "Размещение в хранилище",
    "take_resource": "Получение из хранилища",
    "speak": "Разговор",
    "transfer": "Передача ресурса",
    "create_offer": "Предложение обмена",
    "respond_to_offer": "Ответ на обмен",
    "create_promise": "Создание обещания",
    "resolve_promise": "Завершение обещания",
    "create_project": "Создание совместного проекта",
    "respond_to_project": "Ответ на совместный проект",
    "contribute_to_project": "Вклад в совместный проект",
    "leave_project": "Выход из совместного проекта",
    "attack": "Атака",
}

EVENT_LABELS = {
    WorldEventKind.WORLD_CREATED: "Мир создан",
    WorldEventKind.AGENT_OBSERVED: "осматривает окрестности",
    WorldEventKind.AGENT_MOVED: "перемещается",
    WorldEventKind.RESOURCE_GATHERED: "собирает ресурс",
    WorldEventKind.RESOURCE_CONSUMED: "использует запас",
    WorldEventKind.AGENT_RESTED: "отдыхает",
    WorldEventKind.AGENT_WAITED: "ожидает",
    WorldEventKind.ACTION_REJECTED: "получает отклонение действия",
    WorldEventKind.STRUCTURE_BUILT: "завершает постройку",
    WorldEventKind.RESOURCE_STORED: "помещает ресурс в хранилище",
    WorldEventKind.RESOURCE_TAKEN: "берёт ресурс из хранилища",
    WorldEventKind.MESSAGE_SENT: "отправляет сообщение",
    WorldEventKind.MESSAGE_DELIVERED: "получает сообщение",
    WorldEventKind.MESSAGE_EXPIRED: "теряет сообщение по сроку",
    WorldEventKind.RESOURCE_TRANSFERRED: "передаёт ресурс",
    WorldEventKind.OFFER_CREATED: "создаёт предложение обмена",
    WorldEventKind.OFFER_DELIVERED: "получает предложение обмена",
    WorldEventKind.OFFER_ACCEPTED: "принимает обмен",
    WorldEventKind.OFFER_REJECTED: "отклоняет обмен",
    WorldEventKind.OFFER_EXPIRED: "теряет предложение по сроку",
    WorldEventKind.COMMITMENT_CREATED: "создаёт обещание",
    WorldEventKind.COMMITMENT_FULFILLED: "выполняет обещание",
    WorldEventKind.COMMITMENT_BROKEN: "нарушает обещание",
    WorldEventKind.COMMITMENT_EXPIRED: "не успевает выполнить обещание",
    WorldEventKind.PROJECT_CREATED: "создаёт совместный проект",
    WorldEventKind.PROJECT_JOINED: "присоединяется к совместному проекту",
    WorldEventKind.PROJECT_REFUSED: "отказывается от совместного проекта",
    WorldEventKind.PROJECT_LEFT: "выходит из совместного проекта",
    WorldEventKind.PROJECT_CONTRIBUTION_ADDED: "вносит вклад в совместный проект",
    WorldEventKind.PROJECT_COMPLETED: "завершает совместный проект",
    WorldEventKind.WEATHER_CHANGED: "наблюдает смену погоды",
    WorldEventKind.WEATHER_CRISIS_STARTED: "сталкивается с погодным кризисом",
    WorldEventKind.WEATHER_CRISIS_ENDED: "переживает окончание погодного кризиса",
    WorldEventKind.EXPERIMENT_COMPLETED: "завершает семидневный эксперимент",
    WorldEventKind.MODEL_OUTPUT_REJECTED: "получает отклонённый ответ модели",
    WorldEventKind.MODEL_FALLBACK_USED: "переходит к безопасному действию",
    WorldEventKind.MODEL_REBOUND: "получает новую модель решений",
    WorldEventKind.SNAPSHOT_IMPORTED: "загружен из сохранения",
    WorldEventKind.SCHEDULED_EVENT_SKIPPED: "пропускает событие",
    WorldEventKind.AGENT_SPAWNED: "добавлен исследователем",
    WorldEventKind.AGENT_ATTACKED: "атакует другое существо",
    WorldEventKind.RESEARCHER_EVENT_TRIGGERED: "запускает событие",
}

RESOURCE_LABELS = {
    "wood": "древесина",
    "stone": "камень",
    "berry": "ягоды",
    "water": "вода",
}


@dataclass(frozen=True, slots=True)
class ObserverRunConfig:
    seed: int
    width: int
    height: int
    agents: list[str]
    provider: str = "deterministic"
    model: str = "scripted-v1"
    agent_provider: str = "deterministic"
    agent_model: str = "scripted-v1"


@dataclass(frozen=True, slots=True)
class RunAcquisition:
    """The result of opening a deterministic observer run.

    A deterministic configuration names one logical world.  Reopening that
    configuration must therefore return the existing live world rather than
    failing with a duplicate-creation error.
    """

    engine: SimulationEngine
    reused: bool


@dataclass(slots=True)
class ObserverSession:
    engine: SimulationEngine
    cognition: SQLiteCognitionRepository
    projector: CognitionProjector
    executive: ExecutiveLayer | None = None
    paused: bool = True
    speed: int = 1
    advance_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    last_actions: dict[str, dict[str, str | int]] = field(default_factory=dict)
    last_reasons: dict[str, str] = field(default_factory=dict)
    task: asyncio.Task[None] | None = None


class RunRegistry:
    """Owns live engines and their read-only observer subscriptions."""

    def __init__(
        self,
        *,
        snapshot_root: Path,
        cognition_root: Path,
        providers: ProviderRegistry | None = None,
        tick_seconds: float = 0.35,
    ) -> None:
        self._runs: dict[str, ObserverSession] = {}
        self._snapshot_repository = SnapshotRepository(snapshot_root)
        self._cognition_root = cognition_root
        self._cognition_root.mkdir(parents=True, exist_ok=True)
        self._providers = providers
        self._tick_seconds = tick_seconds
        self._serial = 0
        self._closed = False
        # A world can be replaced when a checkpoint is loaded.  This lock
        # serializes that replacement with advancing and control operations,
        # so a request cannot keep using a cognition repository after it has
        # been retired.
        self._lifecycle_lock = asyncio.Lock()

    async def acquire(self, config: ObserverRunConfig) -> RunAcquisition:
        """Create a live world once, then reopen it by deterministic identity."""
        if config.provider != "deterministic" or config.model not in {
            "scripted-v1",
            "scripted-experiment-v1",
        }:
            raise ValueError(
                "в текущем наблюдателе доступен только локальный сценарный режим"
            )
        random_models = []
        if config.agent_provider == "random":
            if self._providers is None:
                raise ValueError("провайдеры моделей не настроены")
            random_models = await self._providers.list_models("ollama")
            if not random_models:
                raise ValueError("Ollama не сообщил доступных моделей")
        elif config.agent_provider != "deterministic":
            if self._providers is None:
                raise ValueError("провайдеры моделей не настроены")
            await self._providers.validate_binding(
                config.agent_provider, config.agent_model
            )
        elif config.agent_model != "scripted-v1":
            raise ValueError("неизвестная сценарная модель поведения")
        if config.model == "scripted-experiment-v1":
            world = create_experiment_world(
                ExperimentConfig(
                    seed=config.seed,
                    width=config.width,
                    height=config.height,
                    agent_names=tuple(config.agents),
                )
            )
            policy = ExperimentalScriptedPolicy()
        else:
            world = generate_world(
                seed=config.seed,
                width=config.width,
                height=config.height,
                agent_names=config.agents,
            )
            for agent in world.agents.values():
                agent.identity.long_term_goal = (
                    "Выжить, исследовать неизвестный мир, понять своё положение "
                    "и самостоятельно выбрать долгосрочные цели."
                )
            policy = ScriptedPolicy()
        if config.agent_provider != "deterministic":
            for index, agent in enumerate(world.agents.values()):
                if config.agent_provider == "random":
                    binding = random_models[(config.seed + index) % len(random_models)]
                    agent_provider = binding.provider
                    agent_model = binding.model
                else:
                    agent_provider = config.agent_provider
                    agent_model = config.agent_model
                agent.mind.intelligence_tier = IntelligenceTier.FULL_LLM
                agent.mind.provider = agent_provider
                agent.mind.model = agent_model
                agent.mind.temperature_milli = 650
        async with self._lifecycle_lock:
            existing = self._runs.get(world.run.run_id)
            if existing is not None:
                return RunAcquisition(engine=existing.engine, reused=True)
            engine = SimulationEngine(state=world, policy=policy)
            session = self._new_session(engine)
            self._runs[world.run.run_id] = session
            await self._refresh_cognition(session)
            return RunAcquisition(engine=engine, reused=False)

    async def create(self, config: ObserverRunConfig) -> SimulationEngine:
        """Compatibility helper for callers that only need the live engine."""
        return (await self.acquire(config)).engine

    def get(self, run_id: str) -> ObserverSession:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise LookupError(run_id) from exc

    def list_runs(self) -> list[dict[str, str | int | bool]]:
        """Return the live worlds that the local laboratory can reopen.

        This is deliberately a compact projection: it identifies an existing
        world and its time state, but it never exposes client-side mutation of
        authoritative state.
        """
        return [
            {
                "run_id": run_id,
                "seed": session.engine.state.seed,
                "paused": session.paused,
                "speed": session.speed,
                "game_minute": session.engine.state.game_minute,
                "processed_events": session.engine.state.processed_events,
                "status": session.engine.state.run.status.value,
                "scenario": self._scenario_label(session.engine),
            }
            for run_id, session in self._runs.items()
        ]

    async def advance(self, run_id: str, events: int) -> int:
        # This endpoint is the explicit deterministic single-step mechanism
        # used by tests and later researcher tooling.  Browser pause controls
        # never call it, so a paused observer remains visually and autonomously
        # still until the researcher resumes it.
        async with self._lifecycle_lock:
            session = self.get(run_id)
            async with session.advance_lock:
                completed = 0
                for _ in range(events):
                    result = await self._step_session(session)
                    if result is None:
                        session.paused = True
                        break
                    completed += 1
                    self._record_action(session, result)
                await self._refresh_cognition(session)
        await self.publish(run_id)
        return completed

    async def spawn_agent(
        self,
        run_id: str,
        *,
        name: str,
        species: str,
        provider: str,
        model: str,
        personality: str,
        behavior_description: str,
        vision_radius: int,
        position: Position,
        health: int,
        hunger: int,
        energy: int,
    ) -> str:
        random_models = []
        if provider == "random":
            if self._providers is None:
                raise ValueError("провайдеры моделей не настроены")
            random_models = await self._providers.list_models("ollama")
            if not random_models:
                raise ValueError("Ollama не сообщил доступных моделей")
        elif provider != "deterministic":
            if self._providers is None:
                raise ValueError("провайдеры моделей не настроены")
            await self._providers.validate_binding(provider, model)
        elif model != "scripted-v1":
            raise ValueError("неизвестная сценарная модель поведения")
        async with self._lifecycle_lock:
            session = self.get(run_id)
            async with session.advance_lock:
                if random_models:
                    binding = random_models[
                        (session.engine.state.seed + len(session.engine.state.agents))
                        % len(random_models)
                    ]
                    provider, model = binding.provider, binding.model
                agent = session.engine.spawn_agent(
                    name=name,
                    species=species,
                    provider=provider,
                    model=model,
                    personality=personality,
                    behavior_description=behavior_description,
                    vision_radius=vision_radius,
                    position=position,
                    health=health,
                    hunger=hunger,
                    energy=energy,
                )
                await self._refresh_cognition(session)
        await self.publish(run_id)
        return agent.identity.agent_id

    async def trigger_event(
        self,
        run_id: str,
        *,
        event_type: str,
        intensity: int,
        duration_minutes: int,
        position: Position | None,
        resource_kind: ResourceKind,
    ) -> str:
        async with self._lifecycle_lock:
            session = self.get(run_id)
            async with session.advance_lock:
                event = session.engine.trigger_research_event(
                    event_type=event_type,
                    intensity=intensity,
                    duration_minutes=duration_minutes,
                    position=position,
                    resource_kind=resource_kind,
                )
                await self._refresh_cognition(session)
        await self.publish(run_id)
        return event.event_id

    async def rebind_agent_model(
        self, run_id: str, agent_id: str, *, provider: str, model: str
    ) -> None:
        if provider == "deterministic":
            raise ValueError("возврат к сценарному режиму пока недоступен")
        if self._providers is None:
            raise ValueError("провайдеры моделей не настроены")
        if provider == "random":
            descriptors = await self._providers.list_models("ollama")
            if not descriptors:
                raise ValueError("Ollama не сообщил доступных моделей")
            session = self.get(run_id)
            ordinal = int(agent_id.rsplit("-", 1)[1])
            descriptor = descriptors[
                (session.engine.state.seed + session.engine.state.game_minute + ordinal)
                % len(descriptors)
            ]
            provider, model = descriptor.provider, descriptor.model
        else:
            await self._providers.validate_binding(provider, model)
        bindings = await self._providers.available_bindings()
        async with self._lifecycle_lock:
            session = self.get(run_id)
            async with session.advance_lock:
                session.engine.hot_swap_model(
                    agent_id,
                    provider=provider,
                    model=model,
                    available_bindings=bindings,
                )
        await self.publish(run_id)

    async def set_controls(
        self, run_id: str, *, paused: bool | None, speed: int | None
    ) -> ObserverSession:
        # A control takes effect between complete world events.  In particular,
        # a pause cannot race a speed batch and leave a seemingly paused world
        # progressing in the background.
        async with self._lifecycle_lock:
            session = self.get(run_id)
            async with session.advance_lock:
                if speed is not None:
                    if speed not in {1, 3, 10}:
                        raise ValueError("скорость должна быть 1, 3 или 10")
                    session.speed = speed
                if paused is not None:
                    if session.engine.state.run.status is RunStatus.COMPLETED:
                        session.paused = True
                        if not paused:
                            raise ValueError("этот эксперимент уже завершён")
                    else:
                        session.paused = paused
                        session.engine.state.run.status = (
                            RunStatus.PAUSED if paused else RunStatus.RUNNING
                        )
                        if not paused:
                            self._ensure_loop(run_id, session)
        await self.publish(run_id)
        return session

    def save_snapshot(self, run_id: str, name: str) -> str:
        session = self.get(run_id)
        saved = self._snapshot_repository.save(
            name,
            state=session.engine.state,
            events=session.engine.event_log.events,
        )
        return saved.stem

    async def load_snapshot(self, name: str) -> SimulationEngine:
        envelope = self._snapshot_repository.load(name)
        policy = (
            ExperimentalScriptedPolicy()
            if envelope.state.run.rules_version == "block4-v1"
            else ScriptedPolicy()
        )
        engine = SimulationEngine.restore(
            state=envelope.state,
            events=envelope.events,
            policy=policy,
        )
        run_id = engine.state.run.run_id
        async with self._lifecycle_lock:
            # Loading a normal local checkpoint opens it at a stable boundary.
            # The researcher explicitly resumes time from the observer controls.
            # A completed checkpoint retains that terminal status instead.
            if engine.state.run.status is not RunStatus.COMPLETED:
                engine.state.run.status = RunStatus.PAUSED
            prior = self._runs.get(run_id)
            subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
            if prior is not None:
                subscribers = prior.subscribers
                prior.subscribers = set()
                await self._retire(prior)
            session = self._new_session(engine)
            session.subscribers = subscribers
            session.paused = True
            self._runs[run_id] = session
            await self._refresh_cognition(session)
        await self.publish(run_id)
        return engine

    def list_snapshots(self) -> list[str]:
        result = []
        for path in self._snapshot_repository.root.glob("*.json"):
            if path.is_file() and not path.is_symlink():
                result.append(path.stem)
        return sorted(result)

    def snapshot(self, run_id: str) -> dict[str, Any]:
        session = self.get(run_id)
        return self._world_projection(session)

    def inspector(self, run_id: str, agent_id: str) -> dict[str, Any]:
        session = self.get(run_id)
        engine = session.engine
        try:
            observation = engine.observe_agent(agent_id)
            agent = engine.state.agents[agent_id]
        except KeyError as exc:
            raise LookupError(agent_id) from exc

        memories = session.cognition.list_memories(
            run_id=run_id,
            agent_id=agent_id,
            layers=[MemoryLayer.WORKING, MemoryLayer.EPISODIC, MemoryLayer.SOCIAL],
        )[-8:]
        beliefs = session.cognition.list_beliefs(run_id=run_id, agent_id=agent_id)[-8:]
        commitments = [
            commitment
            for commitment in engine.state.commitments.values()
            if agent_id in {commitment.creator_id, commitment.beneficiary_id}
        ]
        profile = {
            **self._profile_for(agent.identity.long_term_goal),
            "vision_radius": engine.vision_radius(agent_id),
        }
        return {
            "agent_id": agent_id,
            "name": agent.identity.name,
            "model": {
                "provider": agent.mind.provider,
                "name": agent.mind.model,
                "tier": agent.mind.intelligence_tier.value,
            },
            "goal": agent.identity.long_term_goal,
            **profile,
            "body": agent.body.model_dump(mode="json"),
            "position": agent.position.model_dump(mode="json"),
            "inventory": {
                RESOURCE_LABELS.get(kind.value, kind.value): quantity
                for kind, quantity in agent.inventory.items()
            },
            "current_action": self._action_for(session, agent_id),
            "last_decision": self._decision_explanation(session, agent_id),
            "observation": {
                "game_minute": observation.game_minute,
                "visible_tiles": [tile.model_dump(mode="json") for tile in observation.visible_tiles],
                "visible_resources": [
                    resource.model_dump(mode="json")
                    for resource in observation.visible_resources
                ],
                "visible_agents": [
                    visible.model_dump(mode="json")
                    for visible in observation.visible_agents
                ],
                "delivered_messages": len(observation.delivered_messages),
            },
            "known_map": [position.model_dump(mode="json") for position in agent.knowledge.explored],
            "memory": [self._memory_projection(memory) for memory in memories],
            "beliefs": [self._belief_projection(belief) for belief in beliefs],
            "relations": self._relations_projection(engine, agent_id),
            "active_promises": [
                {
                    "id": commitment.commitment_id,
                    "with": self._agent_name(engine, self._counterpart(commitment, agent_id)),
                    "status": commitment.status.value,
                    "terms": commitment.terms,
                    "deadline_minute": commitment.deadline_minute,
                }
                for commitment in commitments
                if commitment.status.value == "active"
            ],
        }

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        session = self.get(run_id)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2)
        session.subscribers.add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self.get(run_id).subscribers.discard(queue)
        except LookupError:
            pass

    async def publish(self, run_id: str) -> None:
        session = self.get(run_id)
        message = {"type": "world_snapshot", "data": self._world_projection(session)}
        for queue in tuple(session.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                continue

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            self._closed = True
            sessions = list(self._runs.values())
            self._runs.clear()
            for session in sessions:
                await self._retire(session)

    def _new_session(self, engine: SimulationEngine) -> ObserverSession:
        self._serial += 1
        database_name = (
            f"observer-{engine.state.run.run_id.removeprefix('run-')}-{self._serial}"
        )
        cognition = SQLiteCognitionRepository(self._cognition_root, database_name)
        executive = (
            ExecutiveLayer(
                providers=self._providers,
                cognition=cognition,
                embedding_provider=DeterministicEmbeddingProvider(),
            )
            if self._providers is not None
            else None
        )
        return ObserverSession(
            engine=engine,
            cognition=cognition,
            projector=CognitionProjector(cognition, DeterministicEmbeddingProvider()),
            executive=executive,
        )

    async def _step_session(self, session: ObserverSession) -> ActionResult | None:
        engine = session.engine
        if engine.next_scheduled_kind() is not ScheduledEventKind.DECISION_DUE:
            return engine.step()
        ticket = engine.prepare_next_decision()
        if ticket.observation.mind.intelligence_tier not in {
            IntelligenceTier.HYBRID,
            IntelligenceTier.FULL_LLM,
        }:
            return engine.step()
        if session.executive is None:
            return engine.step()
        resolution = await session.executive.resolve(ticket)
        result = engine.commit_decision(ticket, resolution)
        session.last_reasons[ticket.agent_id] = resolution.intent.reason
        await session.executive.record_outcome(ticket, resolution, result)
        return result

    @staticmethod
    def _scenario_label(engine: SimulationEngine) -> str:
        if engine.state.run.rules_version == "block4-v1":
            return "Остров: три агента, семь дней"
        return "Свободный мир"

    async def _retire(self, session: ObserverSession) -> None:
        if session.task is not None and not session.task.done():
            session.task.cancel()
            try:
                await session.task
            except asyncio.CancelledError:
                pass
        session.cognition.close()

    def _ensure_loop(self, run_id: str, session: ObserverSession) -> None:
        if self._closed or (session.task is not None and not session.task.done()):
            return
        session.task = asyncio.create_task(
            self._run_loop(run_id), name=f"observer-run-{run_id}"
        )

    async def _run_loop(self, run_id: str) -> None:
        try:
            while not self._closed:
                session = self._runs.get(run_id)
                if session is None:
                    return
                if not session.paused:
                    await self.advance(run_id, session.speed)
                # Speed changes the amount of game time processed per real-time
                # tick.  Dividing the delay as well would make ×3 and ×10 run
                # at 9× and 100× respectively.
                await asyncio.sleep(self._tick_seconds)
        except asyncio.CancelledError:
            raise

    async def _refresh_cognition(self, session: ObserverSession) -> None:
        engine = session.engine
        for agent_id in sorted(engine.state.agents):
            observation = engine.observe_agent(agent_id)
            await session.projector.project_observation(observation)
            session.cognition.apply_forgetting(
                run_id=engine.state.run.run_id,
                agent_id=agent_id,
                game_minute=engine.state.game_minute,
            )
            session.cognition.apply_belief_forgetting(
                run_id=engine.state.run.run_id,
                agent_id=agent_id,
                game_minute=engine.state.game_minute,
            )

    def _record_action(self, session: ObserverSession, result: ActionResult) -> None:
        if result.event_id is None:
            return
        event = next(
            (
                candidate
                for candidate in reversed(session.engine.event_log.events)
                if candidate.event_id == result.event_id
            ),
            None,
        )
        if event is None or event.actor_id is None:
            return
        action = str(event.payload.get("action", ""))
        label = ACTION_LABELS.get(action, EVENT_LABELS.get(event.kind, "Действие"))
        session.last_actions[event.actor_id] = {
            "label": label,
            "minute": event.game_minute,
            "event_id": event.event_id,
        }
        session.cognition.add_memory(
            run_id=session.engine.state.run.run_id,
            agent_id=event.actor_id,
            layer=MemoryLayer.WORKING,
            content=f"{label}: {self._event_text(session.engine, event)}",
            game_minute=event.game_minute,
            importance_milli=700 if result.success else 780,
            confidence_milli=1_000,
            source_kind="authoritative_action_outcome",
            source_actor_id=event.actor_id,
            source_event_id=event.event_id,
            dedupe_key=f"observer-event:{event.event_id}",
        )
        session.cognition.compact_working_memory(
            run_id=session.engine.state.run.run_id,
            agent_id=event.actor_id,
            game_minute=event.game_minute,
        )

    def _world_projection(self, session: ObserverSession) -> dict[str, Any]:
        engine = session.engine
        state = engine.state
        day = state.game_minute // 1_440 + 1
        minute_of_day = state.game_minute % 1_440
        hour, minute = divmod(minute_of_day, 60)
        weather_labels = {
            "clear": "Ясно",
            "rain": "Дождь",
            "cold_snap": "Резкое похолодание",
            "heat_wave": "Жара",
            "fog": "Туман",
            "storm": "Шторм",
            "drought": "Засуха",
        }
        if 6 <= hour < 19:
            night_overlay = 0.0
        elif 5 <= hour < 21:
            night_overlay = 0.26
        else:
            night_overlay = 0.58
        agents = []
        for agent_id, agent in sorted(state.agents.items()):
            profile = {
                **self._profile_for(agent.identity.long_term_goal),
                "vision_radius": engine.vision_radius(agent_id),
            }
            agents.append(
                {
                    "id": agent_id,
                    "name": agent.identity.name,
                    "position": agent.position.model_dump(mode="json"),
                    "health": agent.body.health,
                    "hunger": agent.body.hunger,
                    "energy": agent.body.energy,
                    "model": f"{agent.mind.provider}/{agent.mind.model}",
                    "goal": agent.identity.long_term_goal,
                    **profile,
                    "current_action": self._action_for(session, agent_id),
                }
            )
        return {
            "run": {
                "id": state.run.run_id,
                "seed": state.seed,
                "scenario": self._scenario_label(engine),
                "status": state.run.status.value,
                "paused": session.paused,
                "speed": session.speed,
                "processed_events": state.processed_events,
                "modified": state.run.modified,
            },
            "environment": {
                "day": day,
                "clock": f"{hour:02d}:{minute:02d}",
                "weather": weather_labels[state.environment.weather.value],
                "weather_visual_only": not bool(state.environment.transitions),
                "night_overlay": night_overlay,
                "temperature_c": state.environment.ambient_temperature_milli_c / 1_000,
                "crisis": state.environment.crisis,
            },
            "map": {
                "width": state.width,
                "height": state.height,
                "tiles": [
                    {
                        "x": tile.position.x,
                        "y": tile.position.y,
                        "terrain": tile.terrain.value,
                    }
                    for tile in state.tiles
                ],
                "resources": [
                    {
                        "id": resource.entity_id,
                        "kind": resource.kind.value,
                        "x": resource.position.x,
                        "y": resource.position.y,
                        "quantity": resource.quantity,
                    }
                    for resource in state.resources.values()
                    if resource.quantity > 0
                ],
                "structures": [
                    {
                        "id": structure.structure_id,
                        "kind": structure.kind.value,
                        "x": structure.position.x,
                        "y": structure.position.y,
                    }
                    for structure in state.structures.values()
                ],
            },
            "agents": agents,
            "dialogues": [
                {
                    "id": message.message_id,
                    "agent_id": message.sender_id,
                    "recipient_id": message.recipient_id,
                    "text": message.content,
                    "minute": message.sent_minute,
                }
                for message in sorted(
                    state.messages.values(),
                    key=lambda item: (item.sent_minute, item.message_id),
                )[-6:]
                if message.sent_minute >= state.game_minute - 120
            ],
            "events": [
                self._event_projection(engine, event)
                for event in engine.event_log.events[-24:]
            ],
            "instruments": {
                "population": len(state.agents),
                "resources": sum(
                    resource.quantity for resource in state.resources.values()
                ),
                "structures": len(state.structures),
                "active_promises": sum(
                    1
                    for commitment in state.commitments.values()
                    if commitment.status.value == "active"
                ),
            },
        }

    def _event_projection(
        self, engine: SimulationEngine, event: WorldEvent
    ) -> dict[str, str | int | None]:
        return {
            "id": event.event_id,
            "minute": event.game_minute,
            "actor_id": event.actor_id,
            "kind": event.kind.value,
            "text": self._event_text(engine, event),
        }

    def _event_text(self, engine: SimulationEngine, event: WorldEvent) -> str:
        if event.kind is WorldEventKind.WORLD_CREATED:
            return "Создан новый детерминированный мир"
        actor = self._agent_name(engine, event.actor_id)
        label = EVENT_LABELS.get(event.kind, "изменяет мир")
        if event.kind is WorldEventKind.RESOURCE_GATHERED:
            resource = RESOURCE_LABELS.get(str(event.payload.get("resource", "")), "ресурс")
            amount = event.payload.get("amount", 1)
            return f"{actor} собирает {resource}: {amount}"
        if event.kind is WorldEventKind.AGENT_MOVED:
            return f"{actor} перемещается по карте"
        if event.kind is WorldEventKind.ACTION_REJECTED:
            return f"{actor}: действие отклонено правилами мира"
        if event.kind is WorldEventKind.MESSAGE_SENT:
            message = engine.state.messages.get(str(event.payload.get("message_id", "")))
            return f"{actor}: «{message.content}»" if message is not None else f"{actor} говорит"
        if event.kind is WorldEventKind.AGENT_SPAWNED:
            species = self._species_label(str(event.payload.get("species", "human")))
            return f"Исследователь добавил: {actor} ({species})"
        if event.kind is WorldEventKind.AGENT_ATTACKED:
            target = self._agent_name(engine, str(event.payload.get("target_agent_id", "")))
            return f"{actor} атакует {target}: −{event.payload.get('damage', 0)} здоровья"
        if event.kind is WorldEventKind.RESEARCHER_EVENT_TRIGGERED:
            labels = {
                "rain": "дождь",
                "cold_snap": "резкое похолодание",
                "heat_wave": "жару",
                "fog": "туман",
                "storm": "шторм",
                "drought": "засуху",
                "clear": "ясную погоду",
                "resource_cache": "новый запас ресурсов",
                "berry_bloom": "цветение ягод",
                "epidemic": "эпидемию",
                "meteor": "падение метеорита",
            }
            event_type = str(event.payload.get("event_type", ""))
            return f"Исследователь запустил {labels.get(event_type, 'событие мира')}"
        return f"{actor} {label}"

    @staticmethod
    def _profile_for(goal: str) -> dict[str, str]:
        if goal.startswith("[") and "]" in goal:
            marker, remainder = goal[1:].split("]", 1)
            remainder = remainder.strip()
            if remainder.startswith("[vision=") and "]" in remainder:
                remainder = remainder.split("]", 1)[1].strip()
            personality, separator, behavior = remainder.partition(" — ")
            return {
                "species": marker,
                "personality": personality or "Не задан",
                "behavior_description": behavior if separator else remainder.strip(),
            }
        return {
            "species": "human",
            "personality": "Самостоятельный исследователь",
            "behavior_description": (
                "Выжить, исследовать неизвестный мир, понять своё положение "
                "и самостоятельно выбрать долгосрочные цели."
                if goal == "survive and understand the world"
                else goal
            ),
        }

    @staticmethod
    def _species_label(species: str) -> str:
        return {
            "human": "человек",
            "wolf": "волк",
            "bear": "медведь",
            "boar": "кабан",
        }.get(species, species)

    def _action_for(self, session: ObserverSession, agent_id: str) -> str:
        action = session.last_actions.get(agent_id)
        return "Ожидает первого решения" if action is None else str(action["label"])

    def _decision_explanation(self, session: ObserverSession, agent_id: str) -> str:
        if agent_id in session.last_reasons:
            return session.last_reasons[agent_id]
        action = self._action_for(session, agent_id)
        explanations = {
            "Осмотр": "Осматривает доступную область, чтобы пополнить известную карту.",
            "Перемещение": "Выбирает соседнюю доступную клетку для исследования или пути к ресурсу.",
            "Сбор ресурсов": "Забирает доступный ресурс рядом с собой для поддержания запасов.",
            "Приём пищи": "Восстанавливает состояние до того, как голод станет опасным.",
            "Отдых": "Восстанавливает энергию перед следующим действием.",
        }
        return explanations.get(
            action,
            "Последнее решение зафиксировано авторитетным журналом мира.",
        )

    def _relations_projection(
        self, engine: SimulationEngine, agent_id: str
    ) -> list[dict[str, str | int]]:
        result = []
        for counterpart_id, counterpart in sorted(engine.state.agents.items()):
            if counterpart_id == agent_id:
                continue
            commitments = [
                commitment
                for commitment in engine.state.commitments.values()
                if {commitment.creator_id, commitment.beneficiary_id}
                == {agent_id, counterpart_id}
                and commitment.status.value == "active"
            ]
            result.append(
                {
                    "agent_id": counterpart_id,
                    "name": counterpart.identity.name,
                    "score": 50 + min(30, len(commitments) * 15),
                    "basis": (
                        "активное обязательство"
                        if commitments
                        else "нет зафиксированной связи"
                    ),
                }
            )
        return result

    def _memory_projection(self, memory: Any) -> dict[str, str | int]:
        content = str(memory.content)
        if content.startswith("Resource "):
            content = "Зафиксирован ресурс в зоне видимости."
        elif content.startswith("Message "):
            content = "Зафиксировано сообщение в доступной переписке."
        elif content.startswith("Commitment "):
            content = "Зафиксировано обязательство с другим агентом."
        return {
            "id": memory.memory_id,
            "layer": memory.layer.value,
            "content": content,
            "minute": memory.created_minute,
            "confidence": memory.confidence_milli,
        }

    @staticmethod
    def _belief_projection(belief: Any) -> dict[str, str | int]:
        return {
            "subject": belief.subject,
            "statement": "Последнее наблюдение остаётся актуальным.",
            "confidence": belief.confidence_milli,
            "minute": belief.updated_minute,
        }

    @staticmethod
    def _counterpart(commitment: Any, agent_id: str) -> str:
        return (
            commitment.beneficiary_id
            if commitment.creator_id == agent_id
            else commitment.creator_id
        )

    @staticmethod
    def _agent_name(engine: SimulationEngine, agent_id: str | None) -> str:
        if agent_id is None:
            return "Мир"
        agent = engine.state.agents.get(agent_id)
        return agent.identity.name if agent is not None else agent_id

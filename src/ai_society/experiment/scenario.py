from __future__ import annotations

from ai_society.domain.enums import (
    CommitmentResolution,
    CommitmentStatus,
    ExperimentMode,
    IntelligenceTier,
    OfferResponse,
    OfferStatus,
    ProjectMemberStatus,
    ProjectResponse,
    ProjectStatus,
    ResourceKind,
    StructureKind,
    TerrainType,
    WeatherKind,
    RunStatus,
)
from ai_society.domain.intents import (
    ContributeToProjectIntent,
    ConsumeIntent,
    CreateOfferIntent,
    CreateProjectIntent,
    CreatePromiseIntent,
    ResolvePromiseIntent,
    RespondToOfferIntent,
    RespondToProjectIntent,
    SpeakIntent,
    StoreResourceIntent,
    TransferIntent,
    TakeResourceIntent,
)
from ai_society.domain.models import (
    EnvironmentState,
    MindBinding,
    Position,
    WeatherTransition,
    WorldState,
)
from ai_society.experiment.models import ExperimentConfig
from ai_society.persistence.canonical import canonical_digest
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import AgentPolicy, ScriptedPolicy
from ai_society.simulation.rng import DeterministicRng


STARTING_INVENTORY = {
    ResourceKind.WOOD: 6,
    ResourceKind.STONE: 4,
    ResourceKind.BERRY: 14,
    ResourceKind.WATER: 8,
}


def create_experiment_world(config: ExperimentConfig) -> WorldState:
    world = generate_world(
        seed=config.seed,
        width=config.width,
        height=config.height,
        agent_names=config.agent_names,
    )
    world.run.mode = config.mode
    world.run.status = RunStatus.CREATED
    world.run.ends_minute = config.duration_minutes
    world.run.engine_version = "0.4.0"
    world.run.rules_version = "block4-v1"
    run_material = {
        "world_id": world.run.world_id,
        "mode": config.mode.value,
        "models": [item.model_dump(mode="json") for item in config.model_assignments],
        "duration_minutes": config.duration_minutes,
    }
    world.run.run_id = f"run-{canonical_digest(run_material)[:12]}"

    walkable = [
        tile.position
        for tile in world.tiles
        if tile.terrain not in {TerrainType.WATER, TerrainType.ROCK}
    ]
    center = Position(x=world.width // 2, y=world.height // 2)
    walkable.sort(
        key=lambda item: (item.manhattan_distance(center), item.y, item.x)
    )
    camp: list[Position] = []
    for anchor in walkable:
        nearby = [
            item
            for item in walkable
            if item.manhattan_distance(anchor) <= 2
        ]
        for second in nearby:
            if second == anchor:
                continue
            candidates = [
                item
                for item in nearby
                if item not in {anchor, second}
                and item.manhattan_distance(second) <= 2
            ]
            if candidates:
                camp = [anchor, second, candidates[0]]
                break
        if camp:
            break
    if len(set(camp)) != 3:
        raise ValueError("generated island does not contain a valid shared landing area")

    assignments = {item.agent_id: item for item in config.model_assignments}
    for index, agent_id in enumerate(sorted(world.agents)):
        agent = world.agents[agent_id]
        agent.position = camp[index]
        agent.inventory = dict(STARTING_INVENTORY)
        if config.mode is ExperimentMode.SCRIPTED:
            agent.mind = MindBinding(
                intelligence_tier=IntelligenceTier.SCRIPTED,
                provider="deterministic",
                model="scripted-experiment-v1",
            )
        else:
            assignment = assignments[agent_id]
            agent.mind = MindBinding(
                intelligence_tier=IntelligenceTier.FULL_LLM,
                provider=assignment.provider,
                model=assignment.model,
                temperature_milli=assignment.temperature_milli,
            )

    world.environment = EnvironmentState(
        weather=WeatherKind.CLEAR,
        ambient_temperature_milli_c=18_000,
        transitions=[
            WeatherTransition(
                transition_id="weather-0001",
                minute=2_160,
                weather=WeatherKind.RAIN,
                ambient_temperature_milli_c=9_000,
            ),
            WeatherTransition(
                transition_id="weather-0002",
                minute=2_880,
                weather=WeatherKind.CLEAR,
                ambient_temperature_milli_c=17_000,
            ),
            WeatherTransition(
                transition_id="weather-0003",
                minute=6_480,
                weather=WeatherKind.COLD_SNAP,
                ambient_temperature_milli_c=-4_000,
                crisis=True,
            ),
            WeatherTransition(
                transition_id="weather-0004",
                minute=7_920,
                weather=WeatherKind.CLEAR,
                ambient_temperature_milli_c=14_000,
            ),
        ],
    )
    return WorldState.model_validate(world.model_dump(mode="python"))


class ExperimentalScriptedPolicy(AgentPolicy):
    """Deterministic acceptance choreography plus the ordinary survival policy."""

    def __init__(self) -> None:
        self._survival = ScriptedPolicy()
        self._stage = {"agent-001": 0, "agent-002": 0, "agent-003": 0}

    def decide(self, observation, rng: DeterministicRng):
        if observation.body.hunger >= 45 and observation.inventory.get(ResourceKind.BERRY, 0):
            return ConsumeIntent(
                resource=ResourceKind.BERRY,
                reason="поддержать силы в семидневном эксперименте",
            )

        agent_id = observation.agent_id
        if agent_id == "agent-001":
            decision = self._leader_decision(observation)
        elif agent_id == "agent-002":
            decision = self._partner_decision(observation)
        else:
            decision = self._observer_decision(observation)
        if decision is not None:
            return decision
        return self._survival.decide(observation, rng)

    def _leader_decision(self, observation):
        stage = self._stage["agent-001"]
        projects = observation.accessible_projects
        if stage == 0 and not projects:
            self._stage["agent-001"] = 1
            return CreateProjectIntent(
                structure_kind=StructureKind.STORAGE,
                location=observation.position,
                invited_agent_ids=["agent-002", "agent-003"],
                reason="предложить общее хранилище соседям",
            )
        if not projects:
            return None
        project = projects[0]
        own = project.contributions.get("agent-001", {})
        if stage == 1 and project.status is ProjectStatus.OPEN and own.get(ResourceKind.WOOD, 0) < 2:
            self._stage["agent-001"] = 2
            return ContributeToProjectIntent(
                project_id=project.project_id,
                resource=ResourceKind.WOOD,
                amount=2,
                reason="внести первую долю в общее хранилище",
            )

        offers = observation.accessible_offers
        leader_offer = next((item for item in offers if item.sender_id == "agent-001"), None)
        if stage == 2 and project.status is ProjectStatus.COMPLETED:
            self._stage["agent-001"] = 3
            return CreateOfferIntent(
                target_agent_id="agent-002",
                offer_resource=ResourceKind.BERRY,
                offer_amount=1,
                request_resource=ResourceKind.WOOD,
                request_amount=1,
                agreement_terms="Одна ягода за одну единицу древесины",
                expires_in_minutes=180,
                reason="проверить добровольный обмен",
            )
        if stage == 3 and leader_offer is not None and leader_offer.status is OfferStatus.ACCEPTED:
            offer_commitment = next(
                (
                    item
                    for item in observation.accessible_commitments
                    if item.provenance == f"offer:{leader_offer.offer_id}"
                    and item.status is CommitmentStatus.ACTIVE
                ),
                None,
            )
            if offer_commitment is not None:
                self._stage["agent-001"] = 4
                return ResolvePromiseIntent(
                    commitment_id=offer_commitment.commitment_id,
                    resolution=CommitmentResolution.FULFILLED,
                    reason="зафиксировать выполненный обмен",
                )

        fulfilled_terms = "Передать воду Борину"
        fulfilled = next(
            (item for item in observation.accessible_commitments if item.terms == fulfilled_terms),
            None,
        )
        if stage == 4:
            self._stage["agent-001"] = 5
            return CreatePromiseIntent(
                beneficiary_agent_id="agent-002",
                agreement_terms=fulfilled_terms,
                due_in_minutes=240,
                reason="дать проверяемое обещание о помощи",
            )
        if stage == 5 and fulfilled is not None and fulfilled.status is CommitmentStatus.ACTIVE:
            self._stage["agent-001"] = 6
            return TransferIntent(
                target_agent_id="agent-002",
                resource=ResourceKind.WATER,
                amount=1,
                reason="выполнить обещанную передачу воды",
            )
        if stage == 6 and fulfilled is not None and fulfilled.status is CommitmentStatus.ACTIVE:
            self._stage["agent-001"] = 7
            return SpeakIntent(
                target_agent_id="agent-002",
                message="Вода передана по обещанию",
                reason="сообщить о выполнении обещания",
            )
        if stage == 7 and fulfilled is not None and fulfilled.status is CommitmentStatus.ACTIVE:
            self._stage["agent-001"] = 8
            return ResolvePromiseIntent(
                commitment_id=fulfilled.commitment_id,
                resolution=CommitmentResolution.FULFILLED,
                reason="отметить обещание выполненным",
            )
        broken_terms = "Передать камень Сайре"
        broken = next(
            (item for item in observation.accessible_commitments if item.terms == broken_terms),
            None,
        )
        if stage == 8 and fulfilled is not None and fulfilled.status is CommitmentStatus.FULFILLED:
            self._stage["agent-001"] = 9
            return CreatePromiseIntent(
                beneficiary_agent_id="agent-003",
                agreement_terms=broken_terms,
                due_in_minutes=240,
                reason="создать обещание с возможностью отказа",
            )
        if stage == 9 and broken is not None and broken.status is CommitmentStatus.ACTIVE:
            self._stage["agent-001"] = 10
            return ResolvePromiseIntent(
                commitment_id=broken.commitment_id,
                resolution=CommitmentResolution.BROKEN,
                reason="честно зафиксировать отказ от обещания",
            )
        storage = next(
            (
                item
                for item in observation.visible_structures
                if item.kind is StructureKind.STORAGE
            ),
            None,
        )
        if stage == 10 and storage is not None:
            self._stage["agent-001"] = 11
            return StoreResourceIntent(
                structure_id=storage.structure_id,
                resource=ResourceKind.BERRY,
                amount=1,
                reason="поместить общий запас в хранилище",
            )
        if (
            stage == 11
            and storage is not None
            and storage.inventory.get(ResourceKind.BERRY, 0) > 0
        ):
            self._stage["agent-001"] = 12
            return TakeResourceIntent(
                structure_id=storage.structure_id,
                resource=ResourceKind.BERRY,
                amount=1,
                reason="проверить извлечение запаса из хранилища",
            )

        return None

    def _partner_decision(self, observation):
        stage = self._stage["agent-002"]
        if observation.accessible_projects:
            project = observation.accessible_projects[0]
            status = project.member_status.get("agent-002")
            if stage == 0 and status is ProjectMemberStatus.INVITED:
                self._stage["agent-002"] = 1
                return RespondToProjectIntent(
                    project_id=project.project_id,
                    response=ProjectResponse.JOIN,
                    reason="добровольно присоединиться к общему хранилищу",
                )
            own = project.contributions.get("agent-002", {})
            if stage == 1 and project.status is ProjectStatus.OPEN and own.get(ResourceKind.WOOD, 0) < 2:
                self._stage["agent-002"] = 2
                return ContributeToProjectIntent(
                    project_id=project.project_id,
                    resource=ResourceKind.WOOD,
                    amount=2,
                    reason="добавить древесину к совместному проекту",
                )
            if stage == 2 and project.status is ProjectStatus.OPEN and own.get(ResourceKind.STONE, 0) < 2:
                self._stage["agent-002"] = 3
                return ContributeToProjectIntent(
                    project_id=project.project_id,
                    resource=ResourceKind.STONE,
                    amount=2,
                    reason="завершить совместный проект камнем",
                )
        offer = next(
            (
                item
                for item in observation.accessible_offers
                if item.recipient_id == "agent-002" and item.status is OfferStatus.OPEN
            ),
            None,
        )
        if stage == 3 and offer is not None:
            self._stage["agent-002"] = 4
            return RespondToOfferIntent(
                offer_id=offer.offer_id,
                response=OfferResponse.ACCEPT,
                message="Согласен",
                reason="принять понятное предложение обмена",
            )
        return None

    def _observer_decision(self, observation):
        if observation.accessible_projects:
            project = observation.accessible_projects[0]
            if (
                self._stage["agent-003"] == 0
                and project.member_status.get("agent-003") is ProjectMemberStatus.INVITED
            ):
                self._stage["agent-003"] = 1
                return RespondToProjectIntent(
                    project_id=project.project_id,
                    response=ProjectResponse.REFUSE,
                    reason="отказаться от проекта без принуждения",
                )
        return None

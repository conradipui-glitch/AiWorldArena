from dataclasses import dataclass
from typing import Protocol

from ai_society.domain.enums import ResourceKind
from ai_society.domain.intents import (
    AttackIntent,
    AnyIntent,
    ConsumeIntent,
    GatherIntent,
    MoveIntent,
    ObserveIntent,
    RestIntent,
    WaitIntent,
    SpeakIntent,
)
from ai_society.domain.models import AgentObservation, Position, ResourceNode, Tile
from ai_society.simulation.rng import DeterministicRng
from ai_society.simulation.movement import terrain_is_traversable


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    intent: AnyIntent
    rejected_outputs: tuple[str, ...] = ()
    fallback_used: bool = False
    provider: str | None = None
    model: str | None = None
    binding_revision: int | None = None


class AgentPolicy(Protocol):
    def decide(
        self, observation: AgentObservation, rng: DeterministicRng
    ) -> AnyIntent | PolicyDecision: ...


class ScriptedPolicy:
    """Deterministic acceptance driver, not a prescribed LLM strategy."""

    def __init__(self, *, enable_social: bool = True) -> None:
        self.enable_social = enable_social

    def decide(self, observation: AgentObservation, rng: DeterministicRng) -> AnyIntent:
        if (
            observation.body.hunger >= 50
            and observation.inventory.get(ResourceKind.BERRY, 0) > 0
        ):
            return ConsumeIntent(
                resource=ResourceKind.BERRY,
                reason="consume carried food before hunger becomes dangerous",
            )
        if observation.body.energy <= 35:
            return RestIntent(reason="restore energy before continuing")

        profile = observation.long_term_goal.casefold()
        is_mob = profile.startswith(("[wolf]", "[bear]", "[boar]"))
        is_peaceful = any(marker in profile for marker in ("мирн", "peaceful", "избег"))
        threats = [
            item
            for item in observation.visible_agents
            if item.species in {"wolf", "bear", "boar"}
        ]
        if self.enable_social and not is_mob and threats:
            threat = min(
                threats,
                key=lambda item: observation.position.manhattan_distance(item.position),
            )
            candidates = self._walkable_neighbors(
                observation.visible_tiles,
                observation.position,
                observation.body.energy,
            )
            if candidates:
                destination = max(
                    candidates,
                    key=lambda position: (
                        position.manhattan_distance(threat.position),
                        -position.y,
                        -position.x,
                    ),
                )
                return MoveIntent(
                    target=destination,
                    reason=f"увидел угрозу ({threat.species}) и увеличивает дистанцию",
                )
        if is_mob and not is_peaceful and observation.visible_agents:
            target = min(
                observation.visible_agents,
                key=lambda item: (
                    observation.position.manhattan_distance(item.position),
                    item.agent_id,
                ),
            )
            if observation.position.manhattan_distance(target.position) <= 1:
                return AttackIntent(
                    target_agent_id=target.agent_id,
                    reason="защищает территорию согласно заданному поведению",
                )
            step = self._step_toward(observation, target.position)
            if step is not None:
                return MoveIntent(target=step, reason="приближается к замеченной цели")

        if self.enable_social and observation.visible_agents:
            target = min(
                observation.visible_agents,
                key=lambda item: (
                    observation.position.manhattan_distance(item.position),
                    item.agent_id,
                ),
            )
            distance = observation.position.manhattan_distance(target.position)
            social_turn = (
                observation.game_minute
                + int(observation.agent_id.rsplit("-", 1)[1])
            ) % 4 == 0
            if distance <= 4 and social_turn:
                return SpeakIntent(
                    target_agent_id=target.agent_id,
                    message="Я продолжаю исследовать мир. Что ты заметил рядом?",
                    reason="обменивается наблюдениями с ближайшим существом",
                )
            step = self._step_toward(observation, target.position)
            if step is not None:
                return MoveIntent(
                    target=step,
                    reason="проявляет социальное любопытство и идёт к замеченному существу",
                )

        known = {(position.x, position.y) for position in observation.known_positions}
        current_key = (observation.position.x, observation.position.y)
        if current_key not in known:
            return ObserveIntent(reason="record the newly reached surroundings")

        target = self._select_resource(observation)
        if target is not None:
            distance = observation.position.manhattan_distance(target.position)
            if distance <= 1:
                return GatherIntent(
                    target_id=target.entity_id,
                    amount=1,
                    reason=f"gather visible {target.kind.value}",
                )
            step = self._step_toward(observation, target.position)
            if step is not None:
                return MoveIntent(
                    target=step,
                    reason=f"move toward visible {target.kind.value}",
                )

        candidates = self._walkable_neighbors(
            observation.visible_tiles,
            observation.position,
            observation.body.energy,
        )
        if candidates:
            return MoveIntent(
                target=candidates[rng.randbelow(len(candidates))],
                reason="explore a deterministic neighboring tile",
            )
        return WaitIntent(reason="no safe adjacent movement is available")

    @staticmethod
    def _select_resource(observation: AgentObservation) -> ResourceNode | None:
        priority = {
            ResourceKind.BERRY: 0,
            ResourceKind.WATER: 1,
            ResourceKind.WOOD: 2,
            ResourceKind.STONE: 3,
        }
        available = [node for node in observation.visible_resources if node.quantity > 0]
        if not available:
            return None
        return min(
            available,
            key=lambda node: (
                priority[node.kind],
                observation.position.manhattan_distance(node.position),
                node.entity_id,
            ),
        )

    def _step_toward(
        self, observation: AgentObservation, target: Position
    ) -> Position | None:
        candidates = self._walkable_neighbors(
            observation.visible_tiles,
            observation.position,
            observation.body.energy,
        )
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda position: (
                position.manhattan_distance(target),
                position.y,
                position.x,
            ),
        )

    @staticmethod
    def _walkable_neighbors(
        tiles: list[Tile], current: Position, energy: int
    ) -> list[Position]:
        result = [
            tile.position
            for tile in tiles
            if current.manhattan_distance(tile.position) == 1
            and terrain_is_traversable(tile.terrain, energy=energy)
        ]
        result.sort(key=lambda position: (position.y, position.x))
        return result

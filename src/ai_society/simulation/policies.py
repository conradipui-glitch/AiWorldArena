from dataclasses import dataclass
from typing import Protocol

from ai_society.domain.enums import ResourceKind, TerrainType
from ai_society.domain.intents import (
    AnyIntent,
    ConsumeIntent,
    GatherIntent,
    MoveIntent,
    ObserveIntent,
    RestIntent,
    WaitIntent,
)
from ai_society.domain.models import AgentObservation, Position, ResourceNode, Tile
from ai_society.simulation.rng import DeterministicRng


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

        candidates = self._walkable_neighbors(observation.visible_tiles, observation.position)
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
        candidates = self._walkable_neighbors(observation.visible_tiles, observation.position)
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
    def _walkable_neighbors(tiles: list[Tile], current: Position) -> list[Position]:
        result = [
            tile.position
            for tile in tiles
            if current.manhattan_distance(tile.position) == 1
            and tile.terrain not in {TerrainType.WATER, TerrainType.ROCK}
        ]
        result.sort(key=lambda position: (position.y, position.x))
        return result

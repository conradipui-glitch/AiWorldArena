from __future__ import annotations

from ai_society.cognition.embeddings import EmbeddingProvider
from ai_society.cognition.repository import SQLiteCognitionRepository
from ai_society.domain.enums import MemoryLayer
from ai_society.domain.intents import AnyIntent
from ai_society.domain.models import ActionResult, AgentObservation
from ai_society.providers.contracts import ProviderError


class CognitionProjector:
    def __init__(
        self,
        repository: SQLiteCognitionRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    async def project_observation(self, observation: AgentObservation) -> None:
        for resource in observation.visible_resources:
            self.repository.upsert_belief(
                run_id=observation.run_id,
                agent_id=observation.agent_id,
                subject=resource.entity_id,
                predicate="last_observed_state",
                object=(
                    f"kind={resource.kind.value};position={resource.position.x},"
                    f"{resource.position.y};quantity={resource.quantity}"
                ),
                confidence_milli=1_000,
                game_minute=observation.game_minute,
                source_kind="direct_observation",
                provenance="agent-visible resource projection",
                supersede_subject_predicate=True,
            )
            await self._upsert_semantic_memory(
                run_id=observation.run_id,
                agent_id=observation.agent_id,
                content=(
                    f"Resource {resource.entity_id} is {resource.kind.value} at "
                    f"{resource.position.x},{resource.position.y}."
                ),
                game_minute=observation.game_minute,
                importance_milli=700,
                confidence_milli=1_000,
                source_kind="direct_observation",
                source_actor_id=observation.agent_id,
                source_event_id=None,
                dedupe_key=f"semantic:resource:{resource.entity_id}",
            )

        for message in observation.delivered_messages:
            if observation.agent_id == message.recipient_id:
                direction = "received"
                counterpart = message.sender_id
                content = f"Message received from {message.sender_id}: {message.content}"
            else:
                direction = "sent"
                counterpart = message.recipient_id
                content = f"Message sent to {message.recipient_id}: {message.content}"
            await self._add_memory(
                run_id=observation.run_id,
                agent_id=observation.agent_id,
                layer=MemoryLayer.WORKING,
                content=content,
                game_minute=message.delivered_minute or observation.game_minute,
                importance_milli=650,
                confidence_milli=1_000,
                source_kind="delivered_message",
                source_actor_id=message.sender_id,
                source_event_id=message.message_id,
                related_agent_id=counterpart,
                dedupe_key=f"message:{message.message_id}:{direction}",
            )

        for commitment in observation.accessible_commitments:
            counterpart = (
                commitment.beneficiary_id
                if commitment.creator_id == observation.agent_id
                else commitment.creator_id
            )
            await self._add_memory(
                run_id=observation.run_id,
                agent_id=observation.agent_id,
                layer=MemoryLayer.SOCIAL,
                content=(
                    f"Commitment {commitment.commitment_id} with {counterpart}: "
                    f"status={commitment.status.value}; terms={commitment.terms}"
                )[:4_000],
                game_minute=observation.game_minute,
                importance_milli=800,
                confidence_milli=1_000,
                source_kind="commitment_projection",
                source_actor_id=commitment.creator_id,
                source_event_id=commitment.commitment_id,
                related_agent_id=counterpart,
                dedupe_key=(
                    f"commitment:{commitment.commitment_id}:v{commitment.version}"
                ),
            )

    async def record_outcome(
        self,
        observation: AgentObservation,
        intent: AnyIntent,
        result: ActionResult,
    ) -> None:
        await self._add_memory(
            run_id=observation.run_id,
            agent_id=observation.agent_id,
            layer=MemoryLayer.WORKING,
            content=(
                f"Action {intent.action.value}: success={result.success}; "
                f"result={result.reason}"
            ),
            game_minute=observation.game_minute,
            importance_milli=600 if result.success else 750,
            confidence_milli=1_000,
            source_kind="action_outcome",
            source_actor_id=observation.agent_id,
            source_event_id=result.event_id,
            dedupe_key=f"action_outcome:{result.event_id}",
        )
        self.repository.compact_working_memory(
            run_id=observation.run_id,
            agent_id=observation.agent_id,
            game_minute=observation.game_minute,
        )

    async def _add_memory(
        self,
        *,
        run_id: str,
        agent_id: str,
        layer: MemoryLayer,
        content: str,
        game_minute: int,
        importance_milli: int,
        confidence_milli: int,
        source_kind: str,
        source_actor_id: str | None,
        source_event_id: str | None,
        related_agent_id: str | None = None,
        dedupe_key: str,
    ) -> None:
        embedding = None
        embedding_model = None
        try:
            embedding = (await self.embedding_provider.embed([content]))[0]
            embedding_model = self.embedding_provider.model_id
        except (ProviderError, ValueError):
            # Retrieval falls back to bounded lexical matching.
            pass
        self.repository.add_memory(
            run_id=run_id,
            agent_id=agent_id,
            layer=layer,
            content=content,
            game_minute=game_minute,
            importance_milli=importance_milli,
            confidence_milli=confidence_milli,
            source_kind=source_kind,
            source_actor_id=source_actor_id,
            source_event_id=source_event_id,
            related_agent_id=related_agent_id,
            embedding_model=embedding_model,
            embedding=embedding,
            dedupe_key=dedupe_key,
        )

    async def _upsert_semantic_memory(
        self,
        *,
        run_id: str,
        agent_id: str,
        content: str,
        game_minute: int,
        importance_milli: int,
        confidence_milli: int,
        source_kind: str,
        source_actor_id: str | None,
        source_event_id: str | None,
        dedupe_key: str,
    ) -> None:
        embedding = None
        embedding_model = None
        try:
            embedding = (await self.embedding_provider.embed([content]))[0]
            embedding_model = self.embedding_provider.model_id
        except (ProviderError, ValueError):
            # The semantic fact remains usable through bounded lexical retrieval.
            pass
        self.repository.upsert_semantic_memory(
            run_id=run_id,
            agent_id=agent_id,
            content=content,
            game_minute=game_minute,
            importance_milli=importance_milli,
            confidence_milli=confidence_milli,
            source_kind=source_kind,
            source_actor_id=source_actor_id,
            source_event_id=source_event_id,
            embedding_model=embedding_model,
            embedding=embedding,
            dedupe_key=dedupe_key,
        )

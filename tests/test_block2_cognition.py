import asyncio
import math

import pytest

from ai_society.cognition.embeddings import (
    DeterministicEmbeddingProvider,
    validate_embeddings,
)
from ai_society.cognition.repository import (
    CognitiveBudgetExceeded,
    CognitionRepositoryError,
    SQLiteCognitionRepository,
)
from ai_society.domain.enums import MemoryLayer, ResourceKind
from ai_society.domain.models import (
    AgentBodyState,
    AgentObservation,
    MindBinding,
    Position,
    ResourceNode,
)
from ai_society.executive.projector import CognitionProjector


RUN_ID = "run-123456789abc"
AGENT_A = "agent-001"
AGENT_B = "agent-002"


def resource_observation(
    *, agent_id: str = AGENT_A, game_minute: int, quantity: int
) -> AgentObservation:
    return AgentObservation(
        run_id=RUN_ID,
        agent_id=agent_id,
        name=f"Agent {agent_id}",
        long_term_goal="remember where wood can be found",
        mind=MindBinding(),
        game_minute=game_minute,
        position=Position(x=2, y=3),
        body=AgentBodyState(last_updated_minute=game_minute),
        inventory={},
        visible_tiles=[],
        visible_resources=[
            ResourceNode(
                entity_id="resource-000001",
                kind=ResourceKind.WOOD,
                position=Position(x=2, y=3),
                quantity=quantity,
                max_quantity=10,
            )
        ],
        known_positions=[Position(x=2, y=3)],
    )


def test_four_memory_layers_round_trip_and_are_agent_scoped(tmp_path) -> None:
    with SQLiteCognitionRepository(tmp_path) as repository:
        for index, layer in enumerate(MemoryLayer):
            repository.add_memory(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                layer=layer,
                content=f"{layer.value} memory",
                game_minute=index,
                source_kind="test",
                dedupe_key=f"layer:{layer.value}",
            )
        repository.add_memory(
            run_id=RUN_ID,
            agent_id=AGENT_B,
            layer=MemoryLayer.WORKING,
            content="foreign secret",
            game_minute=0,
            source_kind="test",
        )
        memories = repository.list_memories(run_id=RUN_ID, agent_id=AGENT_A)
        assert {memory.layer for memory in memories} == set(MemoryLayer)
        assert "foreign secret" not in {memory.content for memory in memories}

    with SQLiteCognitionRepository(tmp_path) as reopened:
        assert len(reopened.list_memories(run_id=RUN_ID, agent_id=AGENT_A)) == 4
        assert reopened.schema_version == 1


def test_retrieval_is_relevant_bounded_and_updates_access(tmp_path) -> None:
    async def scenario() -> None:
        embedder = DeterministicEmbeddingProvider()
        query_vector, relevant_vector, other_vector = await embedder.embed(
            ["berries by the river", "berries by the river", "cold stone mountain"]
        )
        with SQLiteCognitionRepository(tmp_path) as repository:
            relevant = repository.add_memory(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                layer=MemoryLayer.EPISODIC,
                content="berries by the river",
                game_minute=10,
                importance_milli=900,
                confidence_milli=900,
                source_kind="test",
                embedding_model=embedder.model_id,
                embedding=relevant_vector,
            )
            repository.add_memory(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                layer=MemoryLayer.EPISODIC,
                content="cold stone mountain",
                game_minute=100,
                importance_milli=100,
                confidence_milli=200,
                source_kind="test",
                embedding_model=embedder.model_id,
                embedding=other_vector,
            )
            selected = repository.retrieve(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                query="berries by the river",
                query_embedding=query_vector,
                game_minute=120,
                limit=1,
                max_characters=100,
            )
            assert [item.memory_id for item in selected] == [relevant.memory_id]
            assert selected[0].access_count == 1
            assert selected[0].last_accessed_minute == 120

    asyncio.run(scenario())


def test_forgetting_is_monotonic_and_idempotent_for_same_minute(tmp_path) -> None:
    with SQLiteCognitionRepository(tmp_path) as repository:
        original = repository.add_memory(
            run_id=RUN_ID,
            agent_id=AGENT_A,
            layer=MemoryLayer.WORKING,
            content="unconfirmed location",
            game_minute=0,
            confidence_milli=900,
            source_kind="test",
        )
        assert repository.apply_forgetting(
            run_id=RUN_ID, agent_id=AGENT_A, game_minute=10 * 1_440
        ) == 1
        decayed = repository.list_memories(run_id=RUN_ID, agent_id=AGENT_A)[0]
        assert decayed.confidence_milli < original.confidence_milli
        repository.apply_forgetting(
            run_id=RUN_ID, agent_id=AGENT_A, game_minute=10 * 1_440
        )
        unchanged = repository.list_memories(run_id=RUN_ID, agent_id=AGENT_A)[0]
        assert unchanged.confidence_milli == decayed.confidence_milli


def test_working_memory_compacts_deterministically_with_provenance(tmp_path) -> None:
    with SQLiteCognitionRepository(tmp_path) as repository:
        for index in range(31):
            repository.add_memory(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                layer=MemoryLayer.WORKING,
                content=f"event {index:02d}",
                game_minute=index,
                source_kind="test",
                source_event_id=f"event-{index:02d}",
            )
        compacted = repository.compact_working_memory(
            run_id=RUN_ID,
            agent_id=AGENT_A,
            game_minute=31,
            max_items=30,
            keep_recent=20,
        )
        assert compacted is not None
        assert compacted.layer is MemoryLayer.EPISODIC
        assert len(compacted.parent_memory_ids) == 11
        active_working = repository.list_memories(
            run_id=RUN_ID, agent_id=AGENT_A, layers=[MemoryLayer.WORKING]
        )
        archived = repository.list_memories(
            run_id=RUN_ID,
            agent_id=AGENT_A,
            layers=[MemoryLayer.WORKING],
            include_archived=True,
        )
        assert len(active_working) == 20
        assert sum(item.archived for item in archived) == 11
        assert (
            repository.compact_working_memory(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                game_minute=31,
                max_items=30,
                keep_recent=20,
            )
            is None
        )


def test_beliefs_are_subjective_and_do_not_become_global_reputation(tmp_path) -> None:
    with SQLiteCognitionRepository(tmp_path) as repository:
        repository.upsert_belief(
            run_id=RUN_ID,
            agent_id=AGENT_A,
            subject=AGENT_B,
            predicate="keeps_promises",
            object="usually",
            confidence_milli=800,
            game_minute=10,
            source_kind="experience",
            provenance="promise-1",
        )
        assert len(repository.list_beliefs(run_id=RUN_ID, agent_id=AGENT_A)) == 1
        assert repository.list_beliefs(run_id=RUN_ID, agent_id=AGENT_B) == []


def test_cognitive_budget_reservation_is_atomic_and_failed_calls_are_charged(tmp_path) -> None:
    with SQLiteCognitionRepository(tmp_path) as repository:
        call_id = repository.reserve_model_call(
            run_id=RUN_ID,
            agent_id=AGENT_A,
            provider="fake",
            model="fake-json-v1",
            binding_revision=1,
            attempt=1,
            request_budget=1,
            token_budget=100,
            estimated_input_tokens=20,
            max_output_tokens=30,
        )
        with pytest.raises(CognitiveBudgetExceeded):
            repository.reserve_model_call(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                provider="fake",
                model="fake-json-v1",
                binding_revision=1,
                attempt=2,
                request_budget=1,
                token_budget=100,
                estimated_input_tokens=20,
                max_output_tokens=30,
            )
        repository.finish_model_call(
            call_id,
            success=False,
            latency_ms=5,
            input_tokens=None,
            output_tokens=None,
            error_code="invalid_json",
            response_digest=None,
        )
        summary = repository.usage_summary(run_id=RUN_ID, agent_id=AGENT_A)
        assert summary.requests == 1
        assert summary.failed_requests == 1
        assert summary.charged_tokens == 50


def test_embedding_validation_rejects_nonfinite_and_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        validate_embeddings([[0.0, math.nan]], expected_count=1)
    with pytest.raises(ValueError):
        validate_embeddings([[0.0], [0.0, 1.0]], expected_count=2)


def test_database_name_rejects_traversal(tmp_path) -> None:
    with pytest.raises(CognitionRepositoryError):
        SQLiteCognitionRepository(tmp_path, "../escape")


def test_subthreshold_memory_forgetting_calls_accumulate_elapsed_time(
    tmp_path,
) -> None:
    with SQLiteCognitionRepository(tmp_path) as repository:
        repository.add_memory(
            run_id=RUN_ID,
            agent_id=AGENT_A,
            layer=MemoryLayer.WORKING,
            content="a slowly fading observation",
            game_minute=0,
            confidence_milli=900,
            source_kind="test",
        )
        for minute in (10, 20, 30, 40, 50):
            assert repository.apply_forgetting(
                run_id=RUN_ID, agent_id=AGENT_A, game_minute=minute
            ) == 0
            current = repository.list_memories(
                run_id=RUN_ID, agent_id=AGENT_A
            )[0]
            assert current.confidence_milli == 900
            assert current.last_decay_minute == 0

        assert repository.apply_forgetting(
            run_id=RUN_ID, agent_id=AGENT_A, game_minute=60
        ) == 1
        decayed = repository.list_memories(run_id=RUN_ID, agent_id=AGENT_A)[0]
        assert decayed.confidence_milli == 899
        assert decayed.last_decay_minute == 58


def test_subthreshold_belief_forgetting_calls_accumulate_elapsed_time(
    tmp_path,
) -> None:
    with SQLiteCognitionRepository(tmp_path) as repository:
        repository.upsert_belief(
            run_id=RUN_ID,
            agent_id=AGENT_A,
            subject="north-forest",
            predicate="contains",
            object="iron",
            confidence_milli=800,
            game_minute=0,
            source_kind="test",
            provenance="test observation",
        )
        for minute in (60, 120, 180, 240):
            assert repository.apply_belief_forgetting(
                run_id=RUN_ID, agent_id=AGENT_A, game_minute=minute
            ) == 0
            current = repository.list_beliefs(
                run_id=RUN_ID, agent_id=AGENT_A
            )[0]
            assert current.confidence_milli == 800
            assert current.last_decay_minute == 0

        assert repository.apply_belief_forgetting(
            run_id=RUN_ID, agent_id=AGENT_A, game_minute=300
        ) == 1
        decayed = repository.list_beliefs(run_id=RUN_ID, agent_id=AGENT_A)[0]
        assert decayed.confidence_milli == 799
        assert decayed.last_decay_minute == 288


def test_projector_creates_retrievable_semantic_memory_end_to_end(
    tmp_path,
) -> None:
    async def scenario() -> None:
        embedder = DeterministicEmbeddingProvider()
        with SQLiteCognitionRepository(tmp_path) as repository:
            projector = CognitionProjector(repository, embedder)
            observation = resource_observation(game_minute=10, quantity=8)
            await projector.project_observation(observation)

            semantic = repository.list_memories(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                layers=[MemoryLayer.SEMANTIC],
            )
            assert len(semantic) == 1
            assert semantic[0].source_kind == "direct_observation"
            assert semantic[0].source_actor_id == AGENT_A
            assert semantic[0].embedding_model == embedder.model_id
            assert semantic[0].embedding is not None
            assert len(semantic[0].embedding) == embedder.dimension
            assert repository.list_memories(
                run_id=RUN_ID,
                agent_id=AGENT_B,
                layers=[MemoryLayer.SEMANTIC],
            ) == []

            query_embedding = (await embedder.embed(["where is the wood resource"]))[0]
            selected = repository.retrieve(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                query="where is the wood resource",
                query_embedding=query_embedding,
                layers=[MemoryLayer.SEMANTIC],
                game_minute=20,
                limit=1,
            )
            assert [item.memory_id for item in selected] == [semantic[0].memory_id]

            repository.apply_forgetting(
                run_id=RUN_ID, agent_id=AGENT_A, game_minute=490
            )
            await projector.project_observation(
                resource_observation(game_minute=500, quantity=3)
            )
            reconfirmed = repository.list_memories(
                run_id=RUN_ID,
                agent_id=AGENT_A,
                layers=[MemoryLayer.SEMANTIC],
            )
            assert len(reconfirmed) == 1
            assert reconfirmed[0].memory_id == semantic[0].memory_id
            assert reconfirmed[0].confidence_milli == 1_000
            assert reconfirmed[0].last_decay_minute == 500

    asyncio.run(scenario())


def test_direct_observation_supersedes_contradictory_current_beliefs(
    tmp_path,
) -> None:
    async def scenario() -> None:
        embedder = DeterministicEmbeddingProvider()
        with SQLiteCognitionRepository(tmp_path) as repository:
            for minute, value in ((1, "quantity=9"), (2, "quantity=7")):
                repository.upsert_belief(
                    run_id=RUN_ID,
                    agent_id=AGENT_A,
                    subject="resource-000001",
                    predicate="last_observed_state",
                    object=value,
                    confidence_milli=1_000,
                    game_minute=minute,
                    source_kind="direct_observation",
                    provenance="legacy direct observation",
                )
            repository.upsert_belief(
                run_id=RUN_ID,
                agent_id=AGENT_B,
                subject="resource-000001",
                predicate="last_observed_state",
                object="quantity=6",
                confidence_milli=1_000,
                game_minute=2,
                source_kind="direct_observation",
                provenance="other agent observation",
            )

            projector = CognitionProjector(repository, embedder)
            await projector.project_observation(
                resource_observation(game_minute=10, quantity=3)
            )
            beliefs = repository.list_beliefs(run_id=RUN_ID, agent_id=AGENT_A)
            current = [
                belief
                for belief in beliefs
                if belief.subject == "resource-000001"
                and belief.predicate == "last_observed_state"
            ]
            assert len(current) == 1
            assert "quantity=3" in current[0].object
            assert "quantity=9" not in current[0].object
            assert "quantity=7" not in current[0].object
            assert current[0].confidence_milli == 1_000
            assert current[0].updated_minute == 10

            foreign = repository.list_beliefs(run_id=RUN_ID, agent_id=AGENT_B)
            assert len(foreign) == 1
            assert foreign[0].object == "quantity=6"

            belief_id = current[0].belief_id
            await projector.project_observation(
                resource_observation(game_minute=20, quantity=2)
            )
            revised = repository.list_beliefs(run_id=RUN_ID, agent_id=AGENT_A)
            revised_current = [
                belief
                for belief in revised
                if belief.subject == "resource-000001"
                and belief.predicate == "last_observed_state"
            ]
            assert len(revised_current) == 1
            assert revised_current[0].belief_id == belief_id
            assert "quantity=2" in revised_current[0].object
            assert revised_current[0].updated_minute == 20

    asyncio.run(scenario())

from ai_society.domain.enums import (
    CommitmentResolution,
    CommitmentStatus,
    MessageStatus,
    OfferResponse,
    OfferStatus,
    ResourceKind,
    StructureKind,
    TerrainType,
    WorldEventKind,
)
from ai_society.domain.intents import (
    BuildFireIntent,
    BuildShelterIntent,
    CreateOfferIntent,
    CreatePromiseIntent,
    ResolvePromiseIntent,
    RespondToOfferIntent,
    SpeakIntent,
    TransferIntent,
)
from ai_society.simulation.engine import SimulationEngine
from ai_society.simulation.generation import generate_world
from ai_society.simulation.policies import ScriptedPolicy


def social_engine(agent_count: int = 3) -> SimulationEngine:
    engine = SimulationEngine(
        state=generate_world(
            seed=909,
            agent_names=[f"Agent-{index}" for index in range(1, agent_count + 1)],
        ),
        policy=ScriptedPolicy(),
    )
    engine.state.event_queue.clear()
    anchor = engine.state.agents["agent-001"].position
    for agent in engine.state.agents.values():
        agent.position = anchor
    return engine


def test_message_is_sent_then_delivered_asynchronously_and_expiry_is_idempotent() -> None:
    engine = social_engine(2)
    sent = engine.execute(
        "agent-001",
        SpeakIntent(
            target_agent_id="agent-002",
            message="Meet by the river",
            reason="coordinate without blocking the world",
        ),
    )
    assert sent.success
    message = engine.state.messages["message-000001"]
    assert message.status is MessageStatus.PENDING
    assert engine.observe("agent-002").delivered_messages == []

    delivered = engine.process_next_system_event()
    assert delivered is not None and delivered.success
    assert message.status is MessageStatus.DELIVERED
    assert engine.observe("agent-002").delivered_messages[0].content == "Meet by the river"

    skipped_expiry = engine.process_next_system_event()
    assert skipped_expiry is not None
    assert message.status is MessageStatus.DELIVERED
    assert engine.event_log.events[-1].kind is WorldEventKind.SCHEDULED_EVENT_SKIPPED


def test_message_expires_when_recipient_moves_before_delivery() -> None:
    engine = social_engine(2)
    engine.execute(
        "agent-001",
        SpeakIntent(
            target_agent_id="agent-002",
            message="This reply will arrive too late",
            reason="test asynchronous reachability",
        ),
    )
    origin = engine.state.agents["agent-001"].position
    distant = next(
        tile.position
        for tile in engine.state.tiles
        if tile.terrain not in {TerrainType.WATER, TerrainType.ROCK}
        and origin.manhattan_distance(tile.position) > 4
    )
    engine.state.agents["agent-002"].position = distant
    engine.process_next_system_event()
    assert engine.state.messages["message-000001"].status is MessageStatus.EXPIRED
    assert engine.observe("agent-002").delivered_messages == []


def test_transfer_is_atomic_and_requires_inventory_and_proximity() -> None:
    engine = social_engine(2)
    sender = engine.state.agents["agent-001"]
    recipient = engine.state.agents["agent-002"]
    sender.inventory[ResourceKind.WOOD] = 3
    transferred = engine.execute(
        "agent-001",
        TransferIntent(
            target_agent_id="agent-002",
            resource=ResourceKind.WOOD,
            amount=2,
            reason="share building material",
        ),
    )
    assert transferred.success
    assert sender.inventory[ResourceKind.WOOD] == 1
    assert recipient.inventory[ResourceKind.WOOD] == 2

    rejected = engine.execute(
        "agent-001",
        TransferIntent(
            target_agent_id="agent-002",
            resource=ResourceKind.WOOD,
            amount=2,
            reason="attempt an overdraw",
        ),
    )
    assert rejected.success is False
    assert sender.inventory[ResourceKind.WOOD] == 1
    assert recipient.inventory[ResourceKind.WOOD] == 2


def test_offer_acceptance_creates_private_versioned_commitment() -> None:
    engine = social_engine(3)
    engine.state.agents["agent-001"].inventory[ResourceKind.WOOD] = 5
    created = engine.execute(
        "agent-001",
        CreateOfferIntent(
            target_agent_id="agent-002",
            offer_resource=ResourceKind.WOOD,
            offer_amount=2,
            request_resource=ResourceKind.BERRY,
            request_amount=1,
            agreement_terms="Two wood for one berry tomorrow",
            expires_in_minutes=60,
            reason="propose a voluntary exchange",
        ),
    )
    assert created.success
    offer = engine.state.offers["offer-000001"]
    assert offer.status is OfferStatus.PENDING
    engine.process_next_system_event()
    assert offer.status is OfferStatus.OPEN

    accepted = engine.execute(
        "agent-002",
        RespondToOfferIntent(
            offer_id=offer.offer_id,
            response=OfferResponse.ACCEPT,
            message="Agreed",
            reason="accept the proposed terms",
        ),
    )
    assert accepted.success
    assert offer.status is OfferStatus.ACCEPTED
    commitment = engine.state.commitments["commitment-000001"]
    assert commitment.status is CommitmentStatus.ACTIVE
    assert commitment.provenance == "offer:offer-000001"
    assert "Two wood" in commitment.terms
    assert engine.observe("agent-003").accessible_commitments == []

    resolved = engine.execute(
        "agent-001",
        ResolvePromiseIntent(
            commitment_id=commitment.commitment_id,
            resolution=CommitmentResolution.FULFILLED,
            reason="record that the promise was fulfilled",
        ),
    )
    assert resolved.success
    assert commitment.status is CommitmentStatus.FULFILLED
    duplicate = engine.execute(
        "agent-001",
        ResolvePromiseIntent(
            commitment_id=commitment.commitment_id,
            resolution=CommitmentResolution.BROKEN,
            reason="attempt an invalid terminal transition",
        ),
    )
    assert duplicate.success is False
    assert commitment.status is CommitmentStatus.FULFILLED


def test_offer_acceptance_revalidates_inventory_without_partial_mutation() -> None:
    engine = social_engine(2)
    sender = engine.state.agents["agent-001"]
    sender.inventory[ResourceKind.WOOD] = 2
    engine.execute(
        "agent-001",
        CreateOfferIntent(
            target_agent_id="agent-002",
            offer_resource=ResourceKind.WOOD,
            offer_amount=2,
            request_resource=ResourceKind.BERRY,
            request_amount=1,
            agreement_terms="Two wood for one berry",
            expires_in_minutes=60,
            reason="create an offer whose inventory can become stale",
        ),
    )
    engine.process_next_system_event()
    offer = engine.state.offers["offer-000001"]
    sender.inventory[ResourceKind.WOOD] = 0
    state_hash_before = engine.state_hash
    version_before = offer.version

    rejected = engine.execute(
        "agent-002",
        RespondToOfferIntent(
            offer_id=offer.offer_id,
            response=OfferResponse.ACCEPT,
            message="Agreed",
            reason="attempt to accept a stale offer",
        ),
    )

    assert rejected.success is False
    assert rejected.reason == "offered resource is unavailable"
    assert engine.state_hash == state_hash_before
    assert offer.status is OfferStatus.OPEN
    assert offer.version == version_before
    assert offer.responded_minute is None
    assert engine.state.commitments == {}
    assert engine.state.next_commitment_sequence == 1
    assert engine.event_log.events[-1].kind is WorldEventKind.ACTION_REJECTED
    assert (
        engine.event_log.events[-1].payload["reason"]
        == "offered resource is unavailable"
    )


def test_offer_acceptance_revalidates_terms_without_partial_mutation() -> None:
    engine = social_engine(2)
    engine.state.agents["agent-001"].inventory[ResourceKind.WOOD] = 2
    engine.execute(
        "agent-001",
        CreateOfferIntent(
            target_agent_id="agent-002",
            offer_resource=ResourceKind.WOOD,
            offer_amount=2,
            request_resource=ResourceKind.BERRY,
            request_amount=1,
            agreement_terms="Initially valid terms",
            expires_in_minutes=60,
            reason="create an offer for validation at acceptance",
        ),
    )
    engine.process_next_system_event()
    offer = engine.state.offers["offer-000001"]
    object.__setattr__(offer, "terms", "x" * 2_001)
    state_hash_before = engine.state_hash
    version_before = offer.version

    rejected = engine.execute(
        "agent-002",
        RespondToOfferIntent(
            offer_id=offer.offer_id,
            response=OfferResponse.ACCEPT,
            message="Agreed",
            reason="attempt to accept corrupted terms",
        ),
    )

    assert rejected.success is False
    assert rejected.reason == "offer terms are invalid"
    assert engine.state_hash == state_hash_before
    assert offer.status is OfferStatus.OPEN
    assert offer.version == version_before
    assert offer.responded_minute is None
    assert engine.state.commitments == {}
    assert engine.state.next_commitment_sequence == 1
    assert engine.event_log.events[-1].kind is WorldEventKind.ACTION_REJECTED
    assert engine.event_log.events[-1].payload["reason"] == "offer terms are invalid"


def test_direct_promise_expires_once_at_authoritative_deadline() -> None:
    engine = social_engine(2)
    created = engine.execute(
        "agent-001",
        CreatePromiseIntent(
            beneficiary_agent_id="agent-002",
            agreement_terms="I will bring water",
            due_in_minutes=30,
            reason="make a unilateral promise",
        ),
    )
    assert created.success
    commitment = engine.state.commitments["commitment-000001"]
    engine.process_next_system_event()
    assert engine.state.game_minute == 30
    assert commitment.status is CommitmentStatus.EXPIRED
    assert engine.event_log.events[-1].kind is WorldEventKind.COMMITMENT_EXPIRED


def test_fire_building_uses_world_validation_and_resources() -> None:
    engine = social_engine(1)
    agent = engine.state.agents["agent-001"]
    agent.inventory[ResourceKind.WOOD] = 2
    result = engine.execute(
        "agent-001",
        BuildFireIntent(
            location=agent.position,
            reason="need warmth at the current location",
        ),
    )
    assert result.success
    assert agent.inventory[ResourceKind.WOOD] == 0
    assert engine.state.structures["structure-000001"].kind is StructureKind.FIRE


def test_shelter_building_uses_world_validation_and_resources() -> None:
    engine = social_engine(1)
    agent = engine.state.agents["agent-001"]
    agent.inventory[ResourceKind.WOOD] = 4
    agent.inventory[ResourceKind.STONE] = 2

    result = engine.execute(
        "agent-001",
        BuildShelterIntent(
            location=agent.position,
            reason="need protection from the weather",
        ),
    )

    assert result.success
    assert agent.inventory[ResourceKind.WOOD] == 0
    assert agent.inventory[ResourceKind.STONE] == 0
    assert (
        engine.state.structures["structure-000001"].kind
        is StructureKind.SHELTER
    )

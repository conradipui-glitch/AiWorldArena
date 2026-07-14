from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ai_society.domain.enums import (
    ActionKind,
    CommitmentResolution,
    OfferResponse,
    ResourceKind,
)
from ai_society.domain.models import Position


class IntentBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    reason: str = Field(min_length=1, max_length=240)


class ObserveIntent(IntentBase):
    action: Literal[ActionKind.OBSERVE] = ActionKind.OBSERVE


class MoveIntent(IntentBase):
    action: Literal[ActionKind.MOVE] = ActionKind.MOVE
    target: Position


class GatherIntent(IntentBase):
    action: Literal[ActionKind.GATHER] = ActionKind.GATHER
    target_id: str = Field(pattern=r"^resource-[0-9]{6}$")
    amount: int = Field(default=1, ge=1, le=10)


class ConsumeIntent(IntentBase):
    action: Literal[ActionKind.CONSUME] = ActionKind.CONSUME
    resource: ResourceKind
    amount: int = Field(default=1, ge=1, le=10)


class RestIntent(IntentBase):
    action: Literal[ActionKind.REST] = ActionKind.REST


class WaitIntent(IntentBase):
    action: Literal[ActionKind.WAIT] = ActionKind.WAIT


class BuildFireIntent(IntentBase):
    action: Literal[ActionKind.BUILD_FIRE] = ActionKind.BUILD_FIRE
    location: Position


class BuildShelterIntent(IntentBase):
    action: Literal[ActionKind.BUILD_SHELTER] = ActionKind.BUILD_SHELTER
    location: Position


class SpeakIntent(IntentBase):
    action: Literal[ActionKind.SPEAK] = ActionKind.SPEAK
    target_agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    message: str = Field(min_length=1, max_length=2_000)
    reply_to_id: str | None = Field(
        default=None, pattern=r"^message-[0-9]{6}$"
    )


class TransferIntent(IntentBase):
    action: Literal[ActionKind.TRANSFER] = ActionKind.TRANSFER
    target_agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    resource: ResourceKind
    amount: int = Field(ge=1, le=1_000)


class CreateOfferIntent(IntentBase):
    action: Literal[ActionKind.CREATE_OFFER] = ActionKind.CREATE_OFFER
    target_agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    offer_resource: ResourceKind
    offer_amount: int = Field(ge=1, le=1_000)
    request_resource: ResourceKind
    request_amount: int = Field(ge=1, le=1_000)
    agreement_terms: str = Field(default="", max_length=2_000)
    expires_in_minutes: int = Field(default=60, ge=2, le=7 * 24 * 60)


class RespondToOfferIntent(IntentBase):
    action: Literal[ActionKind.RESPOND_TO_OFFER] = ActionKind.RESPOND_TO_OFFER
    offer_id: str = Field(pattern=r"^offer-[0-9]{6}$")
    response: OfferResponse
    message: str = Field(default="", max_length=2_000)


class CreatePromiseIntent(IntentBase):
    action: Literal[ActionKind.CREATE_PROMISE] = ActionKind.CREATE_PROMISE
    beneficiary_agent_id: str = Field(pattern=r"^agent-[0-9]{3}$")
    agreement_terms: str = Field(min_length=1, max_length=4_000)
    due_in_minutes: int = Field(ge=1, le=30 * 24 * 60)


class ResolvePromiseIntent(IntentBase):
    action: Literal[ActionKind.RESOLVE_PROMISE] = ActionKind.RESOLVE_PROMISE
    commitment_id: str = Field(pattern=r"^commitment-[0-9]{6}$")
    resolution: CommitmentResolution


AnyIntent: TypeAlias = Annotated[
    ObserveIntent
    | MoveIntent
    | GatherIntent
    | ConsumeIntent
    | RestIntent
    | WaitIntent
    | BuildFireIntent
    | BuildShelterIntent
    | SpeakIntent
    | TransferIntent
    | CreateOfferIntent
    | RespondToOfferIntent
    | CreatePromiseIntent
    | ResolvePromiseIntent,
    Field(discriminator="action"),
]

INTENT_ADAPTER = TypeAdapter(AnyIntent)


def parse_intent(value: object) -> AnyIntent:
    return INTENT_ADAPTER.validate_python(value)

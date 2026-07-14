from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ai_society.domain.enums import ActionKind, ResourceKind
from ai_society.domain.models import Position


class IntentBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


AnyIntent: TypeAlias = Annotated[
    ObserveIntent | MoveIntent | GatherIntent | ConsumeIntent | RestIntent | WaitIntent,
    Field(discriminator="action"),
]

INTENT_ADAPTER = TypeAdapter(AnyIntent)


def parse_intent(value: object) -> AnyIntent:
    return INTENT_ADAPTER.validate_python(value)

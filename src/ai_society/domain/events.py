from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from ai_society.domain.enums import ScheduledEventKind, WorldEventKind


JsonScalar: TypeAlias = str | int | float | bool | None


class ScheduledEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    due_minute: int = Field(ge=0)
    sequence: int = Field(ge=0)
    kind: ScheduledEventKind
    actor_id: str = Field(min_length=1, max_length=96)


class WorldEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    event_id: str = Field(pattern=r"^evt-[0-9]{12}$")
    kind: WorldEventKind
    game_minute: int = Field(ge=0)
    actor_id: str | None = Field(default=None, max_length=96)
    payload: dict[str, JsonScalar] = Field(default_factory=dict)
    previous_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

from collections.abc import Iterable

from ai_society.domain.enums import WorldEventKind
from ai_society.domain.events import JsonScalar, WorldEvent
from ai_society.persistence.canonical import canonical_digest


GENESIS_HASH = "0" * 64


class EventIntegrityError(ValueError):
    pass


class EventLog:
    def __init__(self, events: Iterable[WorldEvent] | None = None) -> None:
        self.events = list(events or [])
        self.verify()

    @property
    def digest(self) -> str:
        return self.events[-1].event_hash if self.events else GENESIS_HASH

    def append(
        self,
        *,
        kind: WorldEventKind,
        game_minute: int,
        actor_id: str | None = None,
        payload: dict[str, JsonScalar] | None = None,
    ) -> WorldEvent:
        event_id = f"evt-{len(self.events) + 1:012d}"
        material = {
            "event_id": event_id,
            "kind": kind,
            "game_minute": game_minute,
            "actor_id": actor_id,
            "payload": payload or {},
            "previous_hash": self.digest,
        }
        event = WorldEvent(
            **material,
            event_hash=canonical_digest(material),
        )
        self.events.append(event)
        return event

    def verify(self) -> None:
        previous_hash = GENESIS_HASH
        for index, event in enumerate(self.events, start=1):
            expected_id = f"evt-{index:012d}"
            if event.event_id != expected_id:
                raise EventIntegrityError(
                    f"event id mismatch: expected {expected_id}, got {event.event_id}"
                )
            if event.previous_hash != previous_hash:
                raise EventIntegrityError(f"event chain broken at {event.event_id}")
            material = event.model_dump(mode="json", exclude={"event_hash"})
            expected_hash = canonical_digest(material)
            if event.event_hash != expected_hash:
                raise EventIntegrityError(f"event hash mismatch at {event.event_id}")
            previous_hash = event.event_hash

import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_society.domain.events import WorldEvent
from ai_society.domain.models import WorldState
from ai_society.persistence.canonical import canonical_digest, canonical_json
from ai_society.persistence.event_log import EventIntegrityError, EventLog


_SAFE_SNAPSHOT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024


class SnapshotError(ValueError):
    pass


class SnapshotEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["snapshot-v1"] = "snapshot-v1"
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    event_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: WorldState
    events: list[WorldEvent]


class SnapshotRepository:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise SnapshotError("snapshot root must be a directory")

    def save(
        self,
        name: str,
        *,
        state: WorldState,
        events: list[WorldEvent],
    ) -> Path:
        path = self._path_for(name)
        if path.is_symlink():
            raise SnapshotError("snapshot target cannot be a symbolic link")
        event_log = EventLog(events)
        envelope = SnapshotEnvelope(
            state_hash=canonical_digest(state),
            event_digest=event_log.digest,
            state=state,
            events=events,
        )
        encoded = canonical_json(envelope)
        if len(encoded.encode("utf-8")) > _MAX_SNAPSHOT_BYTES:
            raise SnapshotError("snapshot exceeds size limit")
        temporary = path.with_suffix(".json.tmp")
        if temporary.is_symlink():
            raise SnapshotError("temporary snapshot target cannot be a symbolic link")
        temporary.write_text(encoded, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
        return path

    def load(self, name: str) -> SnapshotEnvelope:
        path = self._path_for(name)
        if not path.exists() or not path.is_file() or path.is_symlink():
            raise SnapshotError("snapshot does not exist as a regular file")
        if path.stat().st_size > _MAX_SNAPSHOT_BYTES:
            raise SnapshotError("snapshot exceeds size limit")
        try:
            envelope = SnapshotEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise SnapshotError("snapshot schema validation failed") from exc
        if canonical_digest(envelope.state) != envelope.state_hash:
            raise SnapshotError("snapshot state hash mismatch")
        try:
            event_log = EventLog(envelope.events)
        except EventIntegrityError as exc:
            raise SnapshotError("snapshot event chain is invalid") from exc
        if event_log.digest != envelope.event_digest:
            raise SnapshotError("snapshot event digest mismatch")
        return envelope

    def _path_for(self, name: str) -> Path:
        if not _SAFE_SNAPSHOT_NAME.fullmatch(name):
            raise SnapshotError("snapshot name must be a safe slug")
        candidate = (self.root / f"{name}.json").resolve(strict=False)
        if candidate.parent != self.root:
            raise SnapshotError("snapshot path escapes configured root")
        return candidate

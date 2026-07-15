from __future__ import annotations

import os
import re
from pathlib import Path

from ai_society.experiment.models import ExperimentBundle
from ai_society.persistence.canonical import canonical_digest, canonical_json
from ai_society.persistence.event_log import EventIntegrityError, EventLog


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MAX_BUNDLE_BYTES = 128 * 1024 * 1024


class ExperimentBundleError(ValueError):
    pass


def bundle_digest(bundle: ExperimentBundle) -> str:
    return canonical_digest(bundle.model_dump(mode="json", exclude={"bundle_digest"}))


class ExperimentBundleRepository:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ExperimentBundleError("experiment root must be a directory")

    def save(self, name: str, bundle: ExperimentBundle) -> Path:
        self._verify(bundle)
        path = self._path_for(name)
        if path.is_symlink():
            raise ExperimentBundleError("bundle target cannot be a symbolic link")
        encoded = canonical_json(bundle)
        if len(encoded.encode("utf-8")) > _MAX_BUNDLE_BYTES:
            raise ExperimentBundleError("experiment bundle exceeds size limit")
        temporary = path.with_suffix(".json.tmp")
        if temporary.is_symlink():
            raise ExperimentBundleError("temporary bundle cannot be a symbolic link")
        temporary.write_text(encoded, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
        return path

    def load(self, name: str) -> ExperimentBundle:
        path = self._path_for(name)
        if not path.is_file() or path.is_symlink():
            raise ExperimentBundleError("experiment bundle is unavailable")
        if path.stat().st_size > _MAX_BUNDLE_BYTES:
            raise ExperimentBundleError("experiment bundle exceeds size limit")
        try:
            bundle = ExperimentBundle.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ExperimentBundleError("experiment bundle schema validation failed") from exc
        self._verify(bundle)
        return bundle

    @staticmethod
    def _verify(bundle: ExperimentBundle) -> None:
        if bundle_digest(bundle) != bundle.bundle_digest:
            raise ExperimentBundleError("experiment bundle digest mismatch")
        if canonical_digest(bundle.final_state) != bundle.final_state_hash:
            raise ExperimentBundleError("final state hash mismatch")
        if canonical_digest(bundle.cognition) != bundle.cognition_digest:
            raise ExperimentBundleError("cognition digest mismatch")
        try:
            events = EventLog(bundle.events)
        except EventIntegrityError as exc:
            raise ExperimentBundleError("event chain is invalid") from exc
        if events.digest != bundle.final_event_digest:
            raise ExperimentBundleError("final event digest mismatch")
        if bundle.initial_state.processed_events != 0 or bundle.initial_state.event_queue:
            raise ExperimentBundleError("initial state must precede engine initialization")
        initial = bundle.initial_state
        final = bundle.final_state
        config = bundle.config
        if (
            initial.run.run_id != final.run.run_id
            or initial.run.world_id != final.run.world_id
            or initial.seed != config.seed
            or initial.width != config.width
            or initial.height != config.height
            or initial.run.mode is not config.mode
            or initial.run.ends_minute != config.duration_minutes
        ):
            raise ExperimentBundleError("bundle config and world identity are inconsistent")
        if (
            final.game_minute != config.duration_minutes
            or final.run.status.value != "completed"
            or bundle.metrics.run_id != final.run.run_id
            or bundle.metrics.duration_minutes != final.game_minute
            or bundle.metrics.decisions != len(bundle.decisions)
            or bundle.metrics.interventions != len(bundle.interventions)
        ):
            raise ExperimentBundleError("bundle completion metrics are inconsistent")
        if [item.ordinal for item in bundle.decisions] != list(
            range(1, len(bundle.decisions) + 1)
        ):
            raise ExperimentBundleError("decision ordinals are not contiguous")
        if any(
            item.agent_id not in final.agents
            or item.due_minute > final.game_minute
            for item in bundle.decisions
        ):
            raise ExperimentBundleError("decision stream references invalid world scope")
        if bundle.cognition.get("run_id") != final.run.run_id:
            raise ExperimentBundleError("cognition run identity is inconsistent")
        if len({item.intervention_id for item in bundle.interventions}) != len(
            bundle.interventions
        ) or any(item.game_minute > final.game_minute for item in bundle.interventions):
            raise ExperimentBundleError("intervention journal is inconsistent")

    def _path_for(self, name: str) -> Path:
        if not _SAFE_NAME.fullmatch(name):
            raise ExperimentBundleError("experiment name must be a safe slug")
        path = (self.root / f"{name}.json").resolve(strict=False)
        if path.parent != self.root:
            raise ExperimentBundleError("experiment path escapes configured root")
        return path

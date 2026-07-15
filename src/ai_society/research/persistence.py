from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ai_society.domain.models import WorldState
from ai_society.experiment.models import InterventionRecord
from ai_society.experiment.persistence import ExperimentBundleRepository
from ai_society.persistence.canonical import canonical_digest, canonical_json
from ai_society.persistence.repository import SnapshotRepository
from ai_society.research.models import (
    CatalogEntry,
    ResearchCatalog,
    ResearchReport,
    ReproducibilityManifest,
    RunComparison,
)


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
ModelT = TypeVar("ModelT", bound=BaseModel)


class ResearchArtifactError(ValueError):
    pass


def manifest_digest(manifest: ReproducibilityManifest) -> str:
    return canonical_digest(manifest.model_dump(mode="json", exclude={"manifest_digest"}))


def catalog_digest(catalog: ResearchCatalog) -> str:
    return canonical_digest(catalog.model_dump(mode="json", exclude={"catalog_digest"}))


def report_digest(report: ResearchReport) -> str:
    return canonical_digest(report.model_dump(mode="json", exclude={"report_digest"}))


def comparison_digest(comparison: RunComparison) -> str:
    return canonical_digest(
        comparison.model_dump(mode="json", exclude={"comparison_digest"})
    )


def intervention_digest(entries: list[InterventionRecord]) -> str:
    return canonical_digest([entry.model_dump(mode="json") for entry in entries])


def world_contract_digest(state: WorldState) -> str:
    """Digest the reproducible world/personality contract, not run namespace or model.

    A model binding is intentionally excluded: the project treats personality as
    separate from its current decision mechanism.  The full model assignments
    remain explicit in the manifest and comparison table.
    """

    material = state.model_dump(mode="json")
    material.pop("run", None)
    for agent in material.get("agents", {}).values():
        agent.pop("mind", None)
    return canonical_digest(material)


class ResearchArtifactRepository:
    """Safe, deterministic persistence for catalogued research outputs.

    Experiment bundles remain in their Block 4 root.  Research metadata lives
    below a separate directory so a bundle name can never overwrite catalog or
    report files.
    """

    def __init__(self, experiment_root: Path) -> None:
        self.bundle_repository = ExperimentBundleRepository(experiment_root)
        self.experiment_root = self.bundle_repository.root
        self.research_root = self._ensure_child_directory(
            self.experiment_root, "research"
        )
        self.manifest_root = self._ensure_child_directory(self.research_root, "manifests")
        self.report_root = self._ensure_child_directory(self.research_root, "reports")
        self.comparison_root = self._ensure_child_directory(
            self.research_root, "comparisons"
        )
        self.branch_root = self._ensure_child_directory(self.research_root, "branches")
        self.branch_snapshots = SnapshotRepository(self.branch_root)
        self._catalog_path = self.research_root / "catalog.json"

    @staticmethod
    def _ensure_child_directory(parent: Path, name: str) -> Path:
        candidate = parent / name
        if candidate.exists() and candidate.is_symlink():
            raise ResearchArtifactError("research directory cannot be a symbolic link")
        candidate.mkdir(parents=True, exist_ok=True)
        resolved = candidate.resolve(strict=True)
        if resolved.parent != parent or not resolved.is_dir():
            raise ResearchArtifactError("research directory escapes configured root")
        return resolved

    @staticmethod
    def _assert_safe_name(name: str) -> None:
        if not _SAFE_NAME.fullmatch(name):
            raise ResearchArtifactError("research artifact name must be a safe slug")

    def _path_for(self, root: Path, name: str, suffix: str) -> Path:
        self._assert_safe_name(name)
        path = (root / f"{name}{suffix}").resolve(strict=False)
        if path.parent != root:
            raise ResearchArtifactError("research artifact path escapes configured root")
        return path

    @staticmethod
    def _write_text(path: Path, content: str) -> Path:
        encoded = content.encode("utf-8")
        if len(encoded) > _MAX_ARTIFACT_BYTES:
            raise ResearchArtifactError("research artifact exceeds size limit")
        if path.exists() and path.is_symlink():
            raise ResearchArtifactError("research artifact target cannot be a symbolic link")
        temporary = path.with_suffix(path.suffix + ".tmp")
        if temporary.exists() and temporary.is_symlink():
            raise ResearchArtifactError("research temporary target cannot be a symbolic link")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
        return path

    @staticmethod
    def _read_text(path: Path) -> str:
        if not path.is_file() or path.is_symlink():
            raise ResearchArtifactError("research artifact is unavailable")
        if path.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise ResearchArtifactError("research artifact exceeds size limit")
        return path.read_text(encoding="utf-8")

    def _write_model(self, path: Path, model: BaseModel) -> Path:
        return self._write_text(path, canonical_json(model))

    def _read_model(self, path: Path, model_type: type[ModelT]) -> ModelT:
        try:
            return model_type.model_validate_json(self._read_text(path))
        except ResearchArtifactError:
            raise
        except Exception as exc:
            raise ResearchArtifactError("research artifact schema validation failed") from exc

    @staticmethod
    def _empty_catalog() -> ResearchCatalog:
        draft = ResearchCatalog(catalog_digest="0" * 64)
        return draft.model_copy(update={"catalog_digest": catalog_digest(draft)})

    def load_catalog(self) -> ResearchCatalog:
        if not self._catalog_path.exists():
            return self._empty_catalog()
        catalog = self._read_model(self._catalog_path, ResearchCatalog)
        if catalog_digest(catalog) != catalog.catalog_digest:
            raise ResearchArtifactError("research catalog digest mismatch")
        return catalog

    def ensure_artifact_name_available(self, name: str) -> None:
        """Reject a duplicate name before any bundle or metadata write occurs."""

        self._assert_safe_name(name)
        if any(entry.artifact_name == name for entry in self.load_catalog().entries):
            raise ResearchArtifactError("research artifact name is already registered")

        paths = (
            self.experiment_root / f"{name}.json",
            self.manifest_root / f"{name}.json",
            self.report_root / f"{name}.json",
            self.report_root / f"{name}.md",
            self.report_root / f"{name}-charts.svg",
        )
        if any(path.exists() or path.is_symlink() for path in paths):
            raise ResearchArtifactError(
                "research artifact name is occupied by an unregistered file"
            )

    def save_manifest(self, manifest: ReproducibilityManifest) -> Path:
        if manifest_digest(manifest) != manifest.manifest_digest:
            raise ResearchArtifactError("reproducibility manifest digest mismatch")
        return self._write_model(
            self._path_for(self.manifest_root, manifest.artifact_name, ".json"), manifest
        )

    def load_manifest(self, name: str) -> ReproducibilityManifest:
        manifest = self._read_model(
            self._path_for(self.manifest_root, name, ".json"), ReproducibilityManifest
        )
        if manifest_digest(manifest) != manifest.manifest_digest:
            raise ResearchArtifactError("reproducibility manifest digest mismatch")
        return manifest

    def register_manifest(self, manifest: ReproducibilityManifest) -> CatalogEntry:
        entry = CatalogEntry(
            artifact_name=manifest.artifact_name,
            artifact_kind=manifest.artifact_kind,
            marks=manifest.marks,
            run_id=manifest.run_id,
            world_id=manifest.world_id,
            mode=manifest.mode,
            engine_version=manifest.engine_version,
            rules_version=manifest.rules_version,
            final_state_hash=manifest.final_state_hash,
            final_event_digest=manifest.final_event_digest,
            manifest_digest=manifest.manifest_digest,
            parent_artifact_name=(
                None if manifest.parent is None else manifest.parent.artifact_name
            ),
        )
        current = self.load_catalog()
        entries = {
            existing.artifact_name: existing for existing in current.entries
        }
        existing = entries.get(entry.artifact_name)
        if existing is not None:
            raise ResearchArtifactError("research artifact name is already registered")
        self.save_manifest(manifest)
        entries[entry.artifact_name] = entry
        draft = ResearchCatalog(
            entries=[entries[name] for name in sorted(entries)], catalog_digest="0" * 64
        )
        verified = draft.model_copy(update={"catalog_digest": catalog_digest(draft)})
        self._write_model(self._catalog_path, verified)
        return entry

    def save_report(self, report: ResearchReport, markdown: str, svg: str) -> tuple[Path, Path, Path]:
        if report_digest(report) != report.report_digest:
            raise ResearchArtifactError("research report digest mismatch")
        json_path = self._write_model(
            self._path_for(self.report_root, report.artifact_name, ".json"), report
        )
        markdown_path = self._write_text(
            self._path_for(self.report_root, report.artifact_name, ".md"), markdown
        )
        svg_path = self._write_text(
            self._path_for(self.report_root, report.artifact_name, "-charts.svg"), svg
        )
        return json_path, markdown_path, svg_path

    def load_report(self, name: str) -> ResearchReport:
        report = self._read_model(
            self._path_for(self.report_root, name, ".json"), ResearchReport
        )
        if report_digest(report) != report.report_digest:
            raise ResearchArtifactError("research report digest mismatch")
        return report

    def save_comparison(self, comparison: RunComparison, markdown: str) -> tuple[Path, Path]:
        if comparison_digest(comparison) != comparison.comparison_digest:
            raise ResearchArtifactError("comparison digest mismatch")
        key = "compare-" + comparison.comparison_digest[:16]
        json_path = self._write_model(
            self._path_for(self.comparison_root, key, ".json"), comparison
        )
        markdown_path = self._write_text(
            self._path_for(self.comparison_root, key, ".md"), markdown
        )
        return json_path, markdown_path

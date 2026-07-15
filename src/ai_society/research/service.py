from __future__ import annotations

from pathlib import Path

from ai_society.domain.models import WorldState
from ai_society.experiment.models import ExperimentBundle, ExperimentConfig
from ai_society.experiment.persistence import ExperimentBundleError
from ai_society.experiment.runner import ReplayMismatchError, replay_bundle
from ai_society.experiment.scenario import create_experiment_world
from ai_society.persistence.canonical import canonical_digest
from ai_society.research.comparison import compare_bundles
from ai_society.research.models import (
    ParentReference,
    ResearchArtifactKind,
    ResearchReport,
    ReproducibilityManifest,
    RunComparison,
    RunMark,
)
from ai_society.research.persistence import (
    ResearchArtifactError,
    ResearchArtifactRepository,
    intervention_digest,
    manifest_digest,
    world_contract_digest,
)
from ai_society.research.reporting import (
    build_research_report,
    render_comparison_markdown,
    render_report_markdown,
    render_report_svg,
)


class ResearchService:
    """Coordinates verified, optional research artifacts around experiment bundles."""

    def __init__(self, experiment_root: Path) -> None:
        self.repository = ResearchArtifactRepository(experiment_root)

    def list_catalog(self):
        entries = self.repository.load_catalog().entries
        for entry in entries:
            manifest, bundle = self._load_verified_artifact(entry.artifact_name)
            if (
                entry.manifest_digest != manifest.manifest_digest
                or entry.run_id != bundle.final_state.run.run_id
                or entry.world_id != bundle.final_state.run.world_id
                or entry.final_state_hash != bundle.final_state_hash
                or entry.final_event_digest != bundle.final_event_digest
            ):
                raise ResearchArtifactError("research catalog entry does not match bundle")
        return entries

    def load_bundle(self, artifact_name: str) -> ExperimentBundle:
        return self._load_verified_artifact(artifact_name)[1]

    def load_manifest(self, artifact_name: str) -> ReproducibilityManifest:
        return self._load_verified_artifact(artifact_name)[0]

    def load_report(self, artifact_name: str) -> ResearchReport:
        manifest, _bundle = self._load_verified_artifact(artifact_name)
        report = self.repository.load_report(artifact_name)
        if report.manifest_digest != manifest.manifest_digest:
            raise ResearchArtifactError("research report does not match manifest")
        return report

    def _load_verified_artifact(
        self, artifact_name: str
    ) -> tuple[ReproducibilityManifest, ExperimentBundle]:
        """Load a catalogued artifact only when manifest and bundle agree."""

        try:
            manifest = self.repository.load_manifest(artifact_name)
            bundle = self.repository.bundle_repository.load(artifact_name)
        except ExperimentBundleError as exc:
            raise ResearchArtifactError(
                "catalogued experiment bundle is unavailable or invalid"
            ) from exc
        if bundle.bundle_digest != manifest.bundle_digest:
            raise ResearchArtifactError("catalogued bundle digest does not match manifest")
        return manifest, bundle

    def register_bundle(
        self,
        *,
        artifact_name: str,
        bundle: ExperimentBundle,
        artifact_kind: ResearchArtifactKind = ResearchArtifactKind.BASELINE,
        parent_artifact_name: str | None = None,
    ) -> tuple[ReproducibilityManifest, ResearchReport]:
        """Persist a verified bundle, its provenance, catalogue entry and reports."""

        self.repository.ensure_artifact_name_available(artifact_name)
        parent = self._parent_reference(parent_artifact_name)
        if artifact_kind is ResearchArtifactKind.BASELINE and parent is not None:
            raise ResearchArtifactError("baseline artifact cannot be derived from a parent")
        if artifact_kind is not ResearchArtifactKind.BASELINE and parent is None:
            raise ResearchArtifactError("derived artifact requires a catalogued parent")
        if parent is not None:
            source_manifest = self.load_manifest(parent.artifact_name)
            if source_manifest.world_contract_digest != world_contract_digest(
                bundle.initial_state
            ):
                raise ResearchArtifactError("derived artifact changed world/personality contract")
            if (
                source_manifest.engine_version != bundle.final_state.run.engine_version
                or source_manifest.rules_version != bundle.final_state.run.rules_version
            ):
                raise ResearchArtifactError("derived artifact changed world or rules version")

        try:
            replayed = replay_bundle(bundle)
        except ReplayMismatchError as exc:
            raise ResearchArtifactError("bundle does not pass exact decision replay") from exc
        if (
            replayed.state_hash != bundle.final_state_hash
            or replayed.event_log.digest != bundle.final_event_digest
        ):
            raise ResearchArtifactError("bundle replay verification is incomplete")

        self.repository.bundle_repository.save(artifact_name, bundle)

        marks = self._marks_for(bundle, artifact_kind)
        manifest = self._build_manifest(
            artifact_name=artifact_name,
            bundle=bundle,
            artifact_kind=artifact_kind,
            marks=marks,
            parent=parent,
        )
        report = build_research_report(bundle, manifest)
        self.repository.save_report(
            report,
            render_report_markdown(report, manifest),
            render_report_svg(report),
        )
        self.repository.register_manifest(manifest)
        return manifest, report

    def rerun_config(self, source_artifact_name: str, destination_name: str) -> ExperimentConfig:
        source = self.load_bundle(source_artifact_name)
        return source.config.model_copy(update={"run_nonce": destination_name})

    def create_initial_snapshot_branch(
        self, source_artifact_name: str, destination_name: str
    ) -> tuple[ExperimentConfig, WorldState]:
        """Create an independent, verified child world from the parent time-zero snapshot.

        Bundle v1 stores only an uninitialized initial state.  This method is
        deliberately limited to that snapshot: it does not pretend that a
        cognition-consistent arbitrary mid-run fork exists yet.
        """

        source = self.load_bundle(source_artifact_name)
        source_manifest = self.load_manifest(source_artifact_name)
        snapshot_name = "branch-" + canonical_digest(
            {"destination": destination_name}
        )[:12]
        self.repository.branch_snapshots.save(
            snapshot_name, state=source.initial_state, events=[]
        )
        snapshot = self.repository.branch_snapshots.load(snapshot_name)
        config = source.config.model_copy(update={"run_nonce": destination_name})
        generated = create_experiment_world(config)
        if world_contract_digest(snapshot.state) != world_contract_digest(generated):
            raise ResearchArtifactError("branch snapshot is incompatible with source config")
        state = snapshot.state.model_copy(deep=True)
        state.run = generated.run.model_copy(deep=True)
        state.run.modified = True
        for agent_id, agent in state.agents.items():
            agent.mind = generated.agents[agent_id].mind.model_copy(deep=True)
        if world_contract_digest(state) != source_manifest.world_contract_digest:
            raise ResearchArtifactError("branch preparation changed world/personality contract")
        return config, state

    def compare(
        self, left_artifact_name: str, right_artifact_name: str, *, persist: bool = True
    ) -> RunComparison:
        comparison = compare_bundles(
            self.load_bundle(left_artifact_name),
            self.load_bundle(right_artifact_name),
            left_artifact_name=left_artifact_name,
            right_artifact_name=right_artifact_name,
        )
        if persist:
            self.repository.save_comparison(
                comparison, render_comparison_markdown(comparison)
            )
        return comparison

    def regenerate_report(self, artifact_name: str) -> ResearchReport:
        bundle = self.load_bundle(artifact_name)
        manifest = self.load_manifest(artifact_name)
        report = build_research_report(bundle, manifest)
        self.repository.save_report(
            report,
            render_report_markdown(report, manifest),
            render_report_svg(report),
        )
        return report

    def _parent_reference(self, artifact_name: str | None) -> ParentReference | None:
        if artifact_name is None:
            return None
        manifest = self.load_manifest(artifact_name)
        return ParentReference(
            artifact_name=artifact_name,
            bundle_digest=manifest.bundle_digest,
        )

    @staticmethod
    def _marks_for(
        bundle: ExperimentBundle, artifact_kind: ResearchArtifactKind
    ) -> tuple[RunMark, ...]:
        marks: list[RunMark] = []
        if artifact_kind in {
            ResearchArtifactKind.EXPERIMENTAL_RERUN,
            ResearchArtifactKind.REPLICA,
        }:
            marks.append(RunMark.EXPERIMENTAL)
        if (
            artifact_kind is ResearchArtifactKind.INITIAL_SNAPSHOT_BRANCH
            or bundle.final_state.run.modified
            or bundle.interventions
        ):
            marks.append(RunMark.MODIFIED)
        if not marks:
            marks.append(RunMark.CLEAN)
        return tuple(marks)

    @staticmethod
    def _build_manifest(
        *,
        artifact_name: str,
        bundle: ExperimentBundle,
        artifact_kind: ResearchArtifactKind,
        marks: tuple[RunMark, ...],
        parent: ParentReference | None,
    ) -> ReproducibilityManifest:
        initial = bundle.initial_state
        final = bundle.final_state
        draft = ReproducibilityManifest(
            artifact_name=artifact_name,
            artifact_kind=artifact_kind,
            marks=marks,
            run_id=final.run.run_id,
            world_id=final.run.world_id,
            mode=bundle.config.mode,
            seed=bundle.config.seed,
            width=bundle.config.width,
            height=bundle.config.height,
            engine_version=final.run.engine_version,
            rules_version=final.run.rules_version,
            world_schema_version=final.run.schema_version,
            world_contract_digest=world_contract_digest(initial),
            config_digest=canonical_digest(bundle.config),
            bundle_digest=bundle.bundle_digest,
            initial_state_hash=canonical_digest(initial),
            final_state_hash=bundle.final_state_hash,
            final_event_digest=bundle.final_event_digest,
            decision_count=len(bundle.decisions),
            model_assignments=bundle.config.model_assignments,
            intervention_count=len(bundle.interventions),
            intervention_digest=intervention_digest(bundle.interventions),
            exact_decision_replay_verified=True,
            parent=parent,
            manifest_digest="0" * 64,
        )
        return draft.model_copy(update={"manifest_digest": manifest_digest(draft)})

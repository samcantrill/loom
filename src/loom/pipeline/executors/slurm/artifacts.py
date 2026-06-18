"""Artifact writing for SLURM dry-run plans."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import cast

from loom.pipeline.stores.atomic import atomic_write_json, atomic_write_text
from loom.pipeline.stores.run_store import LocalRunStorePaths
from loom.serialization import PlainData

from .errors import SlurmPlanningError
from .manifest import SlurmPlannedJob, SlurmPlannedSubmission
from .paths import (
    SlurmGeneratedArtifactPath,
    resolve_slurm_generated_artifact_path,
)


@dataclass(frozen=True, slots=True)
class SlurmDryRunPlanningResult:
    """Written SLURM dry-run artifacts and parsed manifest data."""

    submission: SlurmPlannedSubmission
    manifest_artifact: SlurmGeneratedArtifactPath
    plan_artifact: SlurmGeneratedArtifactPath
    script_artifacts: Mapping[str, SlurmGeneratedArtifactPath]

    def __post_init__(self) -> None:
        if not isinstance(self.submission, SlurmPlannedSubmission):
            raise SlurmPlanningError("submission must be a SlurmPlannedSubmission")
        if not isinstance(self.manifest_artifact, SlurmGeneratedArtifactPath):
            raise SlurmPlanningError(
                "manifest_artifact must be a SlurmGeneratedArtifactPath"
            )
        if not isinstance(self.plan_artifact, SlurmGeneratedArtifactPath):
            raise SlurmPlanningError("plan_artifact must be a SlurmGeneratedArtifactPath")
        normalized: dict[str, SlurmGeneratedArtifactPath] = {}
        for key, artifact in self.script_artifacts.items():
            if not isinstance(key, str) or not key:
                raise SlurmPlanningError("script artifact keys must be non-empty strings")
            if not isinstance(artifact, SlurmGeneratedArtifactPath):
                raise SlurmPlanningError(
                    "script artifact values must be SlurmGeneratedArtifactPath records"
                )
            normalized[key] = artifact
        object.__setattr__(
            self,
            "script_artifacts",
            MappingProxyType(dict(sorted(normalized.items()))),
        )

    @property
    def generated_artifacts(self) -> tuple[SlurmGeneratedArtifactPath, ...]:
        return (
            self.plan_artifact,
            self.manifest_artifact,
            *self.script_artifacts.values(),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "submission": self.submission.to_dict(),
            "manifest_artifact": self.manifest_artifact.to_dict(),
            "plan_artifact": self.plan_artifact.to_dict(),
            "script_artifacts": {
                key: artifact.to_dict()
                for key, artifact in self.script_artifacts.items()
            },
        }


def write_slurm_dry_run_artifacts(
    *,
    store_paths: LocalRunStorePaths,
    run_uri: str,
    submission: SlurmPlannedSubmission,
    scripts: Mapping[str, str],
    plan_metadata: Mapping[str, PlainData],
) -> SlurmDryRunPlanningResult:
    """Write scripts, planning metadata, and manifest through store path helpers."""

    script_artifacts: dict[str, SlurmGeneratedArtifactPath] = {}
    jobs = cast(tuple[SlurmPlannedJob, ...], submission.jobs)
    jobs_by_key = {job.logical_key: job for job in jobs}
    if set(scripts) != set(jobs_by_key):
        raise SlurmPlanningError("scripts must match planned job logical keys")

    for logical_key, script_text in sorted(scripts.items()):
        if not isinstance(script_text, str):
            raise SlurmPlanningError("script text must be a string")
        script_relative_path = jobs_by_key[logical_key].script_relative_path
        if script_relative_path is None:
            raise SlurmPlanningError("planned jobs must include script paths")
        artifact = resolve_slurm_generated_artifact_path(
            store_paths,
            run_uri,
            script_relative_path,
        )
        atomic_write_text(artifact.local_path, script_text)
        _make_executable(artifact.local_path)
        script_artifacts[logical_key] = artifact

    plan_artifact = resolve_slurm_generated_artifact_path(
        store_paths,
        run_uri,
        submission.plan_relative_path,
    )
    atomic_write_json(plan_artifact.local_path, dict(plan_metadata))

    manifest_artifact = resolve_slurm_generated_artifact_path(
        store_paths,
        run_uri,
        cast(str, submission.manifest_relative_path),
    )
    atomic_write_json(manifest_artifact.local_path, submission.to_dict())

    return SlurmDryRunPlanningResult(
        submission=submission,
        manifest_artifact=manifest_artifact,
        plan_artifact=plan_artifact,
        script_artifacts=script_artifacts,
    )


def _make_executable(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | 0o111)
    except OSError as exc:
        raise SlurmPlanningError(f"failed to mark script executable: {path}") from exc


__all__ = [
    "SlurmDryRunPlanningResult",
    "write_slurm_dry_run_artifacts",
]

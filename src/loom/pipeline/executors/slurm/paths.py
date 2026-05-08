"""SLURM generated-artifact path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loom.pipeline.stores.run_store import LocalRunStorePaths
from loom.serialization import PlainData

from .errors import SlurmPathError

SLURM_SUBMISSION_ROOT = "slurm/submissions"


@dataclass(frozen=True, slots=True)
class SlurmGeneratedArtifactPath:
    """Relative manifest value plus store-resolved local path."""

    relative_path: str
    local_path: Path

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relative_path",
            _relative_path(
                self.relative_path, path="SlurmGeneratedArtifactPath.relative_path"
            ),
        )
        if not isinstance(self.local_path, Path):
            raise SlurmPathError("SlurmGeneratedArtifactPath.local_path must be a Path")

    def to_dict(self) -> dict[str, PlainData]:
        return {"relative_path": self.relative_path, "local_path": str(self.local_path)}


def slurm_submission_relative_path(planning_id: str, *parts: str) -> str:
    """Build a relative path under ``slurm/submissions/<planning_id>/...``."""

    planning_component = _path_component(planning_id, path="planning_id")
    if not parts:
        raise SlurmPathError(
            "slurm submission path requires at least one artifact name"
        )
    artifact_parts = tuple(
        _path_component(part, path=f"parts[{index}]")
        for index, part in enumerate(parts)
    )
    return "/".join((SLURM_SUBMISSION_ROOT, planning_component, *artifact_parts))


def slurm_manifest_relative_path(planning_id: str) -> str:
    return slurm_submission_relative_path(planning_id, "manifest.json")


def slurm_plan_relative_path(planning_id: str) -> str:
    return slurm_submission_relative_path(planning_id, "plan.json")


def slurm_job_script_relative_path(planning_id: str, logical_job_key: str) -> str:
    return slurm_submission_relative_path(
        planning_id,
        "scripts",
        f"{_job_file_stem(logical_job_key)}.sh",
    )


def slurm_job_log_relative_path(
    planning_id: str,
    logical_job_key: str,
    stream: str,
) -> str:
    stream_text = _path_component(stream, path="stream")
    if stream_text not in {"stdout", "stderr"}:
        raise SlurmPathError("stream must be one of: stdout, stderr")
    return slurm_submission_relative_path(
        planning_id,
        "logs",
        f"{_job_file_stem(logical_job_key)}.{stream_text}.log",
    )


def resolve_slurm_generated_artifact_path(
    store_paths: LocalRunStorePaths,
    run_uri: str,
    relative_path: str,
) -> SlurmGeneratedArtifactPath:
    """Resolve a generated artifact path through the store-owned path helper."""

    relative = _relative_path(relative_path, path="relative_path")
    return SlurmGeneratedArtifactPath(
        relative_path=relative,
        local_path=store_paths.local_generated_artifact_path(run_uri, relative),
    )


def resolve_slurm_manifest_path(
    store_paths: LocalRunStorePaths,
    run_uri: str,
    planning_id: str,
) -> SlurmGeneratedArtifactPath:
    return resolve_slurm_generated_artifact_path(
        store_paths,
        run_uri,
        slurm_manifest_relative_path(planning_id),
    )


def _job_file_stem(logical_job_key: str) -> str:
    if logical_job_key == "pipeline":
        return "pipeline"
    if logical_job_key.startswith("stage:"):
        stage_name = logical_job_key.removeprefix("stage:")
        return f"stage-{_path_component(stage_name, path='stage_name')}"
    raise SlurmPathError("logical_job_key must be 'pipeline' or 'stage:<stage_name>'")


def _relative_path(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmPathError(f"{path} must be a non-empty relative path")
    if value.startswith("/") or "\\" in value:
        raise SlurmPathError(f"{path} must be a safe relative path")
    if value.strip() != value:
        raise SlurmPathError(f"{path} must not contain leading or trailing whitespace")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SlurmPathError(f"{path} must not contain empty, '.', or '..' components")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise SlurmPathError(
            f"{path} must not contain whitespace or control characters"
        )
    return value


def _path_component(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise SlurmPathError(f"{path} must be a non-empty path component")
    if value.strip() != value:
        raise SlurmPathError(f"{path} must not contain leading or trailing whitespace")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise SlurmPathError(f"{path} must be a safe single path component")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise SlurmPathError(
            f"{path} must not contain whitespace or control characters"
        )
    return value


__all__ = [
    "SLURM_SUBMISSION_ROOT",
    "SlurmGeneratedArtifactPath",
    "resolve_slurm_generated_artifact_path",
    "resolve_slurm_manifest_path",
    "slurm_job_log_relative_path",
    "slurm_job_script_relative_path",
    "slurm_manifest_relative_path",
    "slurm_plan_relative_path",
    "slurm_submission_relative_path",
]

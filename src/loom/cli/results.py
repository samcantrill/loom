"""CLI-facing result and warning payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable

type PlainCliData = object


@runtime_checkable
class SupportsToDict(Protocol):
    """Object that exposes a plain-data conversion helper."""

    def to_dict(self) -> object:
        """Return a mapping or value suitable for CLI normalization."""


def to_plain_cli_data(value: object) -> PlainCliData:
    """Convert simple CLI values into JSON-compatible plain data."""

    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): to_plain_cli_data(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [to_plain_cli_data(item) for item in value]
    if isinstance(value, frozenset | set):
        return [to_plain_cli_data(item) for item in sorted(value, key=str)]
    if isinstance(value, SupportsToDict):
        return to_plain_cli_data(value.to_dict())
    return str(value)


@dataclass(frozen=True, slots=True)
class CliWarning:
    """Machine-readable warning emitted by CLI commands."""

    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, PlainCliData]:
        """Return the warning as plain data."""

        details = to_plain_cli_data(dict(self.details))
        if not isinstance(details, dict):
            details = {}
        return {
            "code": self.code,
            "message": self.message,
            "details": details,
        }


@dataclass(frozen=True, slots=True)
class ValidationCliResult:
    """CLI-facing validation result placeholder."""

    config_path: Path
    pipeline_name: str | None = None
    stage_count: int | None = None
    check_targets: bool = False
    target_count: int | None = None

    def to_dict(self) -> dict[str, PlainCliData]:
        """Return the result as plain data."""

        return {
            "config_path": str(self.config_path),
            "pipeline_name": self.pipeline_name,
            "stage_count": self.stage_count,
            "check_targets": self.check_targets,
            "target_count": self.target_count,
        }


@dataclass(frozen=True, slots=True)
class PlanCliResult:
    """CLI-facing plan result placeholder."""

    config_path: Path
    pipeline_name: str | None = None
    run_uri: str | None = None
    resume: bool = False
    selectors: Mapping[str, object] = field(default_factory=dict)
    summary: Mapping[str, object] = field(default_factory=dict)
    stage_actions: tuple[Mapping[str, object], ...] = ()
    explanation: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, PlainCliData]:
        """Return the result as plain data."""

        return {
            "config_path": str(self.config_path),
            "pipeline_name": self.pipeline_name,
            "run_uri": self.run_uri,
            "resume": self.resume,
            "selectors": to_plain_cli_data(dict(self.selectors)),
            "summary": to_plain_cli_data(dict(self.summary)),
            "stage_actions": to_plain_cli_data(self.stage_actions),
            "explanation": to_plain_cli_data(self.explanation),
        }


@dataclass(frozen=True, slots=True)
class RunCliResult:
    """CLI-facing run result placeholder."""

    run_uri: str
    status: str
    stage_summaries: tuple[Mapping[str, object], ...] = ()
    failure_summary: Mapping[str, object] | None = None
    plan_summary: Mapping[str, object] = field(default_factory=dict)
    artifact_count: int | None = None

    def to_dict(self) -> dict[str, PlainCliData]:
        """Return the result as plain data."""

        return {
            "run_uri": self.run_uri,
            "status": self.status,
            "stage_summaries": to_plain_cli_data(self.stage_summaries),
            "failure_summary": to_plain_cli_data(self.failure_summary),
            "plan_summary": to_plain_cli_data(dict(self.plan_summary)),
            "artifact_count": self.artifact_count,
        }


@dataclass(frozen=True, slots=True)
class SlurmDryRunCliResult:
    """CLI-facing SLURM dry-run artifact summary."""

    run_uri: str
    mode: str
    planning_id: str
    manifest_path: str
    manifest_relative_path: str
    plan_path: str
    plan_relative_path: str
    script_directory: str | None
    script_count: int
    script_paths: tuple[Mapping[str, object], ...] = ()
    log_paths: tuple[Mapping[str, object], ...] = ()
    job_count: int = 0
    dependency_count: int = 0
    generated_commands: tuple[Mapping[str, object], ...] = ()
    resource_summary: Mapping[str, object] = field(default_factory=dict)
    generated_artifact_count: int = 0
    preflight_warnings: tuple[Mapping[str, object], ...] = ()
    dry_run: bool = True

    def to_dict(self) -> dict[str, PlainCliData]:
        """Return the result as plain data."""

        return {
            "run_uri": self.run_uri,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "planning_id": self.planning_id,
            "manifest_path": self.manifest_path,
            "manifest_relative_path": self.manifest_relative_path,
            "plan_path": self.plan_path,
            "plan_relative_path": self.plan_relative_path,
            "script_directory": self.script_directory,
            "script_count": self.script_count,
            "script_paths": to_plain_cli_data(self.script_paths),
            "log_paths": to_plain_cli_data(self.log_paths),
            "job_count": self.job_count,
            "dependency_count": self.dependency_count,
            "generated_commands": to_plain_cli_data(self.generated_commands),
            "resource_summary": to_plain_cli_data(dict(self.resource_summary)),
            "generated_artifact_count": self.generated_artifact_count,
            "preflight_warnings": to_plain_cli_data(self.preflight_warnings),
        }


__all__ = [
    "CliWarning",
    "PlainCliData",
    "PlanCliResult",
    "RunCliResult",
    "SlurmDryRunCliResult",
    "ValidationCliResult",
    "to_plain_cli_data",
]

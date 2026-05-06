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
    run_uri: str | None = None
    resume: bool = False
    stage_actions: tuple[Mapping[str, object], ...] = ()

    def to_dict(self) -> dict[str, PlainCliData]:
        """Return the result as plain data."""

        return {
            "config_path": str(self.config_path),
            "run_uri": self.run_uri,
            "resume": self.resume,
            "stage_actions": to_plain_cli_data(self.stage_actions),
        }


@dataclass(frozen=True, slots=True)
class RunCliResult:
    """CLI-facing run result placeholder."""

    run_uri: str
    status: str
    stage_summaries: tuple[Mapping[str, object], ...] = ()
    failure_summary: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, PlainCliData]:
        """Return the result as plain data."""

        return {
            "run_uri": self.run_uri,
            "status": self.status,
            "stage_summaries": to_plain_cli_data(self.stage_summaries),
            "failure_summary": to_plain_cli_data(self.failure_summary),
        }


__all__ = [
    "CliWarning",
    "PlainCliData",
    "PlanCliResult",
    "RunCliResult",
    "ValidationCliResult",
    "to_plain_cli_data",
]

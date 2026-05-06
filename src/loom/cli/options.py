"""Typed CLI option adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class OutputFormat(StrEnum):
    """Supported command output formats."""

    TEXT = "text"
    JSON = "json"

    @classmethod
    def parse(cls, value: "str | OutputFormat") -> "OutputFormat":
        """Parse an output format value."""

        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError as exc:
            choices = ", ".join(format.value for format in cls)
            raise ValueError(f"Unknown output format {value!r}; expected one of: {choices}") from exc


@dataclass(frozen=True, slots=True)
class ConfigCliOptions:
    """Config source options shared by v2 commands."""

    config_path: Path
    overlays: tuple[Path, ...] = ()
    overrides: tuple[str, ...] = ()

    @classmethod
    def from_namespace(cls, namespace: Any) -> "ConfigCliOptions":
        """Build config options from an argparse namespace."""

        return cls(
            config_path=Path(namespace.config),
            overlays=tuple(Path(path) for path in getattr(namespace, "overlay", ()) or ()),
            overrides=tuple(getattr(namespace, "override", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class SelectorCliOptions:
    """Planner selector options shared by plan and run commands."""

    from_stage: str | None = None
    only_stages: frozenset[str] = frozenset()
    force_stages: frozenset[str] = frozenset()
    skip_stages: frozenset[str] = frozenset()

    @classmethod
    def from_namespace(cls, namespace: Any) -> "SelectorCliOptions":
        """Build selector options from an argparse namespace."""

        return cls(
            from_stage=getattr(namespace, "from_stage", None),
            only_stages=frozenset(getattr(namespace, "only_stage", ()) or ()),
            force_stages=frozenset(getattr(namespace, "force_stage", ()) or ()),
            skip_stages=frozenset(getattr(namespace, "skip_stage", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class ValidateCliOptions:
    """Validate-command options."""

    check_targets: bool = False

    @classmethod
    def from_namespace(cls, namespace: Any) -> "ValidateCliOptions":
        """Build validate options from an argparse namespace."""

        return cls(check_targets=bool(getattr(namespace, "check_targets", False)))


@dataclass(frozen=True, slots=True)
class PlanCliOptions:
    """Plan-command options."""

    run_uri: str | None = None
    resume: bool = False
    explain_stage: str | None = None

    @classmethod
    def from_namespace(cls, namespace: Any) -> "PlanCliOptions":
        """Build plan options from an argparse namespace."""

        return cls(
            run_uri=getattr(namespace, "run_uri", None),
            resume=bool(getattr(namespace, "resume", False)),
            explain_stage=getattr(namespace, "explain_stage", None),
        )


@dataclass(frozen=True, slots=True)
class RunCliOptions:
    """Run-command options."""

    run_uri: str | None = None
    executor: str = "local"
    resume: bool = False
    dry_run: bool = False

    @classmethod
    def from_namespace(cls, namespace: Any) -> "RunCliOptions":
        """Build run options from an argparse namespace."""

        return cls(
            run_uri=getattr(namespace, "run_uri", None),
            executor=getattr(namespace, "executor", "local"),
            resume=bool(getattr(namespace, "resume", False)),
            dry_run=bool(getattr(namespace, "dry_run", False)),
        )


def output_format_from_namespace(namespace: Any) -> OutputFormat:
    """Return the parsed output format from an argparse namespace."""

    return OutputFormat.parse(getattr(namespace, "output_format", OutputFormat.TEXT))


__all__ = [
    "ConfigCliOptions",
    "OutputFormat",
    "PlanCliOptions",
    "RunCliOptions",
    "SelectorCliOptions",
    "ValidateCliOptions",
    "output_format_from_namespace",
]

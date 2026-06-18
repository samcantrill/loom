"""Typed CLI option adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    def to_runtime_source(self) -> dict[str, object]:
        """Return a sparse ``RunOptions.selectors`` source."""

        source: dict[str, object] = {}
        if self.force_stages:
            source["force_stages"] = sorted(self.force_stages)
        if self.from_stage is not None:
            source["from_stage"] = self.from_stage
        if self.only_stages:
            source["only_stages"] = sorted(self.only_stages)
        if self.skip_stages:
            source["skip_stages"] = sorted(self.skip_stages)
        return source


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
    profile: str | None = None
    executor: str | None = None
    tags: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()
    explain_stage: str | None = None

    @classmethod
    def from_namespace(cls, namespace: Any) -> "PlanCliOptions":
        """Build plan options from an argparse namespace."""

        return cls(
            run_uri=getattr(namespace, "run_uri", None),
            resume=bool(getattr(namespace, "resume", False)),
            profile=getattr(namespace, "runtime_profile", None),
            executor=getattr(namespace, "runtime_executor", None),
            tags=_tag_pairs(getattr(namespace, "tag", ()) or ()),
            notes=_notes(getattr(namespace, "note", ()) or ()),
            explain_stage=getattr(namespace, "explain_stage", None),
        )

    def to_runtime_source(
        self,
        *,
        selectors: SelectorCliOptions | None = None,
    ) -> dict[str, object]:
        """Return a sparse explicit runtime source for plan-like commands."""

        return _runtime_source(
            run_uri=self.run_uri,
            executor=self.executor,
            profile=self.profile,
            resume=self.resume,
            tags=self.tags,
            notes=self.notes,
            selectors=selectors,
        )


@dataclass(frozen=True, slots=True)
class PreflightCliOptions:
    """Preflight-command options."""

    run_uri: str | None = None
    executor: str | None = None
    profile: str | None = None
    dry_run: bool = False
    resume: bool = False
    tags: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()
    check_groups: tuple[str, ...] = ()
    plugin_groups: tuple[str, ...] = ()
    plugin_names: tuple[str, ...] = ()
    plugin_packages: tuple[str, ...] = ()
    strict: bool = False

    @classmethod
    def from_namespace(cls, namespace: Any) -> "PreflightCliOptions":
        """Build preflight options from an argparse namespace."""

        return cls(
            run_uri=getattr(namespace, "run_uri", None),
            executor=getattr(namespace, "runtime_executor", None),
            profile=getattr(namespace, "runtime_profile", None),
            dry_run=bool(getattr(namespace, "dry_run", False)),
            resume=bool(getattr(namespace, "resume", False)),
            tags=_tag_pairs(getattr(namespace, "tag", ()) or ()),
            notes=_notes(getattr(namespace, "note", ()) or ()),
            check_groups=tuple(getattr(namespace, "check_group", ()) or ()),
            plugin_groups=tuple(getattr(namespace, "plugin_group", ()) or ()),
            plugin_names=tuple(getattr(namespace, "plugin_name", ()) or ()),
            plugin_packages=tuple(getattr(namespace, "plugin_package", ()) or ()),
            strict=bool(getattr(namespace, "strict", False)),
        )

    def to_runtime_source(
        self,
        *,
        selectors: SelectorCliOptions | None = None,
    ) -> dict[str, object]:
        """Return a sparse explicit runtime source for preflight."""

        return _runtime_source(
            run_uri=self.run_uri,
            executor=self.executor,
            profile=self.profile,
            dry_run=self.dry_run,
            resume=self.resume,
            tags=self.tags,
            notes=self.notes,
            selectors=selectors,
        )


@dataclass(frozen=True, slots=True)
class RunCliOptions:
    """Run-command options."""

    run_uri: str | None = None
    executor: str = "local"
    executor_explicit: bool = field(default=False, compare=False)
    profile: str | None = None
    resume: bool = False
    dry_run: bool = False
    max_parallel_stages: int | None = None
    failure_policy: str | None = None
    tags: tuple[tuple[str, str], ...] = ()
    notes: tuple[str, ...] = ()

    @classmethod
    def from_namespace(cls, namespace: Any) -> "RunCliOptions":
        """Build run options from an argparse namespace."""

        executor = getattr(namespace, "executor", None)
        return cls(
            run_uri=getattr(namespace, "run_uri", None),
            executor="local" if executor is None else executor,
            executor_explicit=executor is not None,
            profile=getattr(namespace, "profile", None),
            resume=bool(getattr(namespace, "resume", False)),
            dry_run=bool(getattr(namespace, "dry_run", False)),
            max_parallel_stages=getattr(namespace, "max_parallel_stages", None),
            failure_policy=_runtime_failure_policy(
                getattr(namespace, "failure_policy", None)
            ),
            tags=_tag_pairs(getattr(namespace, "tag", ()) or ()),
            notes=_notes(getattr(namespace, "note", ()) or ()),
        )

    def to_runtime_source(
        self,
        *,
        selectors: SelectorCliOptions | None = None,
        include_executor_default: bool = False,
    ) -> dict[str, object]:
        """Return a sparse explicit runtime source for run commands."""

        executor = self.executor if self.executor_explicit or include_executor_default else None
        return _runtime_source(
            run_uri=self.run_uri,
            executor=executor,
            profile=self.profile,
            dry_run=self.dry_run,
            resume=self.resume,
            max_parallel_stages=self.max_parallel_stages,
            failure_policy=self.failure_policy,
            tags=self.tags,
            notes=self.notes,
            selectors=selectors,
        )


def output_format_from_namespace(namespace: Any) -> OutputFormat:
    """Return the parsed output format from an argparse namespace."""

    return OutputFormat.parse(getattr(namespace, "output_format", OutputFormat.TEXT))


def _runtime_source(
    *,
    run_uri: str | None = None,
    executor: str | None = None,
    profile: str | None = None,
    dry_run: bool = False,
    resume: bool = False,
    max_parallel_stages: int | None = None,
    failure_policy: str | None = None,
    tags: tuple[tuple[str, str], ...] = (),
    notes: tuple[str, ...] = (),
    selectors: SelectorCliOptions | None = None,
) -> dict[str, object]:
    source: dict[str, object] = {}
    if run_uri is not None:
        source["run_uri"] = run_uri
    if executor is not None:
        source["executor"] = executor
    if profile is not None:
        source["profile"] = profile
    if dry_run:
        source["dry_run"] = True
    if resume:
        source["resume"] = {"enabled": True}
    execution_settings: dict[str, object] = {}
    if max_parallel_stages is not None:
        execution_settings["max_parallel_stages"] = max_parallel_stages
    if failure_policy is not None:
        execution_settings["failure_policy"] = failure_policy
    if execution_settings:
        source["execution"] = {"settings": execution_settings}
    if tags:
        source["tags"] = dict(tags)
    if notes:
        source["notes"] = list(notes)
    if selectors is not None:
        selector_source = selectors.to_runtime_source()
        if selector_source:
            source["selectors"] = selector_source
    return source


def _tag_pairs(values: tuple[str, ...] | list[str]) -> tuple[tuple[str, str], ...]:
    pairs: list[tuple[str, str]] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or "=" not in value:
            raise ValueError(f"tag[{index}] must use KEY=VALUE syntax")
        key, item = value.split("=", 1)
        if not key:
            raise ValueError(f"tag[{index}] key must be non-empty")
        pairs.append((key, item))
    return tuple(pairs)


def _notes(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    notes: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value:
            raise ValueError(f"note[{index}] must be a non-empty string")
        notes.append(value)
    return tuple(notes)


def _runtime_failure_policy(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("-", "_")


__all__ = [
    "ConfigCliOptions",
    "OutputFormat",
    "PlanCliOptions",
    "PreflightCliOptions",
    "RunCliOptions",
    "SelectorCliOptions",
    "ValidateCliOptions",
    "output_format_from_namespace",
]

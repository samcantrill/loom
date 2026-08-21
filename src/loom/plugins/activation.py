"""Explicit plugin activation identity and reconstruction helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from loom.serialization import PlainData

from .entrypoints import PluginInvalidEntryPointError, PluginRecord, find_plugin_duplicates

PLUGIN_ACTIVATIONS_METADATA_KEY = "plugin_activations"
PLUGIN_ACTIVATION_MANIFEST_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PluginActivationManifest:
    """The minimal durable evidence for explicitly selected entry points."""

    plugins: tuple[PluginRecord, ...] = ()
    schema_version: int = PLUGIN_ACTIVATION_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PLUGIN_ACTIVATION_MANIFEST_SCHEMA_VERSION:
            raise PluginInvalidEntryPointError("PluginActivationManifest schema_version must be 1")
        plugins = tuple(self.plugins)
        if any(not isinstance(record, PluginRecord) for record in plugins):
            raise PluginInvalidEntryPointError("PluginActivationManifest plugins must be PluginRecord values")
        if find_plugin_duplicates(plugins):
            raise PluginInvalidEntryPointError("PluginActivationManifest plugins must have unique group/name records")
        object.__setattr__(self, "plugins", tuple(sorted(plugins, key=lambda item: (item.group, item.name, item.value))))

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "plugins": [record.to_summary() for record in self.plugins],
        }

    @classmethod
    def from_dict(cls, data: object) -> "PluginActivationManifest":
        if not isinstance(data, Mapping):
            raise PluginInvalidEntryPointError("PluginActivationManifest must be a mapping")
        unknown = set(data) - {"schema_version", "plugins"}
        missing = {"schema_version", "plugins"} - set(data)
        if unknown or missing:
            raise PluginInvalidEntryPointError("PluginActivationManifest must contain exactly schema_version and plugins")
        version = data["schema_version"]
        records = data["plugins"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise PluginInvalidEntryPointError("PluginActivationManifest schema_version must be an integer")
        if not isinstance(records, list):
            raise PluginInvalidEntryPointError("PluginActivationManifest plugins must be a list")
        return cls(schema_version=version, plugins=tuple(PluginRecord.from_summary(item) for item in records))


def parse_plugin_selector(value: object) -> tuple[str, str]:
    """Parse exactly one ``GROUP:NAME`` selection without importing its target."""
    if not isinstance(value, str) or value.count(":") != 1:
        raise PluginInvalidEntryPointError("plugin selector must use exact GROUP:NAME syntax")
    group, name = value.split(":", 1)
    if not group or not name or group.strip() != group or name.strip() != name:
        raise PluginInvalidEntryPointError("plugin selector must use exact GROUP:NAME syntax")
    return group, name


def resolve_plugin_selections(
    selectors: Iterable[str], records: Iterable[PluginRecord], *, allowed_groups: Iterable[str],
) -> tuple[PluginRecord, ...]:
    """Resolve strict applicable metadata records before any target import."""
    allowed = frozenset(allowed_groups)
    by_key: dict[tuple[str, str], list[PluginRecord]] = {}
    for record in records:
        by_key.setdefault((record.group, record.name), []).append(record)
    selected: list[PluginRecord] = []
    for selector in selectors:
        group, name = parse_plugin_selector(selector)
        if group not in allowed:
            raise PluginInvalidEntryPointError(f"plugin group {group!r} is not applicable to this command")
        matches = by_key.get((group, name), [])
        if len(matches) != 1:
            reason = "missing" if not matches else "duplicate"
            raise PluginInvalidEntryPointError(f"plugin selector {group}:{name} resolved {reason} metadata")
        selected.append(matches[0])
    if find_plugin_duplicates(selected):
        raise PluginInvalidEntryPointError("plugin selectors must not repeat a group/name")
    return tuple(sorted(selected, key=lambda item: (item.group, item.name, item.value)))


def compare_plugin_activation_records(
    recorded: Iterable[PluginRecord], current: Iterable[PluginRecord],
) -> tuple[str, ...]:
    """Return bounded identity diagnostics before an applicable target is used."""
    expected = {(item.group, item.name): item for item in recorded}
    actual = {(item.group, item.name): item for item in current}
    findings: list[str] = []
    for key in sorted(set(expected) | set(actual)):
        left, right = expected.get(key), actual.get(key)
        label = f"{key[0]}:{key[1]}"
        if left is None:
            findings.append(f"unexpected plugin activation {label}")
        elif right is None:
            findings.append(f"missing plugin activation {label}")
        elif left.value != right.value:
            findings.append(f"plugin target changed for {label}")
        elif left.package is not None and right.package is not None and left.package != right.package:
            findings.append(f"plugin package changed for {label}")
        elif left.package_version is not None and right.package_version is not None and left.package_version != right.package_version:
            findings.append(f"plugin package version changed for {label}")
        elif left.package is None or right.package is None or left.package_version is None or right.package_version is None:
            findings.append(f"plugin distribution evidence unavailable for {label}")
    return tuple(findings)


__all__ = [
    "PLUGIN_ACTIVATION_MANIFEST_SCHEMA_VERSION", "PLUGIN_ACTIVATIONS_METADATA_KEY",
    "PluginActivationManifest", "compare_plugin_activation_records", "parse_plugin_selector",
    "resolve_plugin_selections",
]

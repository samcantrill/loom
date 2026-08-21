"""CLI composition for explicitly selected runtime extension records."""

from __future__ import annotations

import argparse
from collections.abc import Iterable

from loom.io.codecs import CodecRegistry, create_default_codec_registry
from loom.pipeline.executors import ExecutorRegistry, create_default_executor_registry
from loom.pipeline.resources import (
    DEFAULT_RESOURCE_VALIDATOR_REGISTRY,
    ResourceValidatorRegistry,
)
from loom.plugins import (
    LOOM_CODECS_GROUP,
    LOOM_RESOURCE_VALIDATORS_GROUP,
    PluginRecord,
    list_entry_points,
    load_codec_entry_points,
    load_executor_entry_points,
    load_resource_validator_entry_points,
)
from loom.plugins.activation import PluginActivationManifest, resolve_plugin_selections


def add_plugin_option(parser: argparse.ArgumentParser) -> None:
    """Attach the shared explicit repeatable selector option to a CLI parser."""
    parser.add_argument(
        "--plugin",
        action="append",
        default=None,
        metavar="GROUP:NAME",
        help="explicit runtime plugin; may be repeated",
    )


def selected_runtime_plugins(
    selectors: Iterable[str] | None,
    *,
    allowed_groups: Iterable[str],
) -> tuple[PluginRecord, ...]:
    values = tuple(selectors or ())
    if not values:
        return ()
    return resolve_plugin_selections(
        values,
        list_entry_points(groups=tuple(allowed_groups)),
        allowed_groups=allowed_groups,
    )


def build_selected_registries(
    records: Iterable[PluginRecord],
    *,
    base_codecs: CodecRegistry | None = None,
    base_validators: ResourceValidatorRegistry = DEFAULT_RESOURCE_VALIDATOR_REGISTRY,
    executor_registry: ExecutorRegistry | None = None,
) -> tuple[
    CodecRegistry, ResourceValidatorRegistry, ExecutorRegistry, PluginActivationManifest
]:
    """Load only already-selected records into caller-owned dependencies."""
    selected = tuple(records)
    codecs = create_default_codec_registry() if base_codecs is None else base_codecs
    executors = (
        create_default_executor_registry(
            worker_plugin_selectors=plugin_selectors_for_groups(
                selected,
                groups=(LOOM_CODECS_GROUP, LOOM_RESOURCE_VALIDATORS_GROUP),
            )
        )
        if executor_registry is None
        else executor_registry
    )
    load_codec_entry_points(selected, codecs, selected=selected, strict=True)
    validators, _ = load_resource_validator_entry_points(
        selected, base_validators, selected=selected, strict=True
    )
    load_executor_entry_points(selected, executors, selected=selected, strict=True)
    return codecs, validators, executors, PluginActivationManifest(plugins=selected)


def plugin_selectors_for_groups(
    records: Iterable[PluginRecord],
    *,
    groups: Iterable[str],
) -> tuple[str, ...]:
    """Project selected identities into one process's closed allowlist."""

    applicable = frozenset(groups)
    return tuple(
        f"{record.group}:{record.name}"
        for record in records
        if record.group in applicable
    )


__all__ = [
    "add_plugin_option",
    "build_selected_registries",
    "plugin_selectors_for_groups",
    "selected_runtime_plugins",
]

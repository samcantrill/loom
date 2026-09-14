"""Shared semantic and saved-selection boundary for direct container builders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import DEFAULT_RESOURCE_VALIDATOR_REGISTRY, ResourceEntry
from loom.pipeline.runtime.resource_policy import (
    ResourcePolicy,
    coerce_resource_policy,
    validate_resource_selection,
)

from .containers import ContainerResourceIntent


def container_resource_selection(
    intent: ContainerResourceIntent | None,
    policy: ResourcePolicy | Mapping[str, object] | None,
    selection: Mapping[str, Sequence[str]] | None,
    *,
    path: str,
) -> tuple[ResourcePolicy, Mapping[str, ResourceEntry], Mapping[str, tuple[str, ...]]]:
    """Validate canonical demand before adapter-specific control representation.

    Unknown kinds keep their existing upstream semantic owner. Selecting an
    unsupported control is the concrete adapter's responsibility, not a reason
    to discard an unselected declaration. The legacy public zero-GPU intent
    retains its existing GPU-helper semantics.
    """

    entries = (
        {} if intent is None else cast(Mapping[str, ResourceEntry], intent.entries)
    )
    for kind, entry in entries.items():
        if kind == "gpu" and entry.amount == 0:
            from .gpu_visibility import requested_gpu_count

            requested_gpu_count({kind: entry})
        elif kind in DEFAULT_RESOURCE_VALIDATOR_REGISTRY.validators:
            DEFAULT_RESOURCE_VALIDATOR_REGISTRY.validate(entry, path=f"{path}.{kind}")
    authored = (
        ResourcePolicy()
        if policy is None
        else coerce_resource_policy(policy, path=path)
    )
    if selection is not None and (
        authored.account_for is None or authored.enforce is None
    ):
        raise RuntimeResourceError(
            f"{path}: saved selection requires both saved policy axes"
        )
    effective = authored.resolved()
    resolved = (
        effective.select(entries)
        if selection is None
        else validate_resource_selection(selection, entries, effective, path=path)
    )
    return effective, entries, resolved

"""Plain-data evidence shared by existing resource-control owners."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Literal, cast

from loom.pipeline.resources import ResourceEntry
from loom.serialization import PlainData

from .resource_policy import ResourcePolicy

ControlDisposition = Literal[
    "not_requested",
    "not_applicable",
    "requested",
    "applied",
    "delegated",
    "unavailable",
    "failed",
]


def _validated_resource_controls(
    value: object,
) -> tuple[Mapping[str, PlainData], ...] | None:
    """Validate the shared closed record shape at report/launch boundaries."""

    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("resource controls must be a sequence or null")
    dispositions = {
        "not_requested",
        "not_applicable",
        "requested",
        "applied",
        "delegated",
        "unavailable",
        "failed",
    }
    records: list[Mapping[str, PlainData]] = []
    previous: tuple[str, str, str] | None = None
    for record in value:
        if not isinstance(record, Mapping) or set(record) != {
            "resource",
            "owner",
            "mechanism",
            "disposition",
        }:
            raise ValueError("resource control record has invalid fields")
        resource, owner = record["resource"], record["owner"]
        mechanism, disposition = record["mechanism"], record["disposition"]
        if (
            not isinstance(resource, str)
            or not resource
            or not isinstance(owner, str)
            or not owner
            or (
                mechanism is not None
                and (not isinstance(mechanism, str) or not mechanism)
            )
            or not isinstance(disposition, str)
            or disposition not in dispositions
        ):
            raise ValueError("resource control record is invalid")
        key = (resource, owner, mechanism or "")
        if previous is not None and key <= previous:
            raise ValueError("resource control records must be unique and sorted")
        previous = key
        records.append(MappingProxyType(dict(record)))
    return tuple(records)


def resource_control_records(
    *,
    entries: Mapping[str, ResourceEntry],
    policy: ResourcePolicy,
    selection: Mapping[str, Sequence[str]],
    owner: str,
    mechanisms: Mapping[str, str],
    selected_disposition: ControlDisposition = "requested",
) -> list[PlainData]:
    """Describe controls without copying amounts, binding values or lease tokens."""

    authored = policy.enforce if isinstance(policy.enforce, tuple) else ()
    names = sorted(set(entries) | set(authored))
    selected = set(selection["enforce"])
    records: list[PlainData] = []
    for name in names:
        entry = entries.get(name)
        disposition: ControlDisposition
        if entry is None or entry.amount == 0:
            disposition = "not_applicable"
        elif name in selected:
            disposition = selected_disposition
        else:
            disposition = "not_requested"
        records.append(
            {
                "resource": name,
                "owner": owner,
                "mechanism": mechanisms.get(name) if name in selected else None,
                "disposition": disposition,
            }
        )
    return records


def with_resource_control_disposition(
    metadata: Mapping[str, PlainData], disposition: ControlDisposition
) -> dict[str, PlainData]:
    """Update requested controls only when their existing launch owner has evidence.

    A validated worker result establishes that the inner job launched, even when
    that application failed. Merely receiving an outer runtime process result
    does not establish that fact. Missing legacy evidence stays missing.
    """

    result = dict(metadata)
    controls = metadata.get("resource_controls")
    if controls is not None:
        result["resource_controls"] = [
            {
                **record,
                "disposition": disposition
                if record["disposition"] in {"requested", "failed"}
                else record["disposition"],
            }
            for record in cast(Sequence[Mapping[str, PlainData]], controls)
        ]
    return result

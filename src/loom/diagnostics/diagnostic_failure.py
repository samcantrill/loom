"""Detached diagnostics for inspection and portable execution failures."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from loom.serialization._diagnostic_capture import (
    _MAX_NODES,
    _SCHEMA,
    _capture_exception_details as _capture_exception_details,
    project_diagnostic_failure as project_diagnostic_failure,
)


_RELATIONS = frozenset({"cause", "context", "group_child"})
_TRUNCATIONS = frozenset({"cycle", "limit"})


class DiagnosticFailureError(ValueError):
    """Raised when untrusted diagnostic data is not canonical Loom data."""


@dataclass(frozen=True, slots=True)
class _DiagnosticLink:
    relation: str
    record: "_DiagnosticNode | None" = None
    truncation: str | None = None


@dataclass(frozen=True, slots=True)
class _DiagnosticNode:
    type: str
    message: str
    links: tuple[_DiagnosticLink, ...]


def render_diagnostic_failure(value: object) -> str:
    """Strictly validate and render a private ``loom.diagnostic.v1`` mapping."""

    root = _decode_root(value)
    lines: list[str] = []

    def render_node(node: _DiagnosticNode, indent: int) -> None:
        prefix = " " * indent
        lines.append(f"{prefix}{node.type}: {node.message}")
        for link in node.links:
            if link.record is not None:
                lines.append(f"{prefix}  {link.relation}:")
                render_node(link.record, indent + 4)
            else:
                assert link.truncation is not None
                lines.append(f"{prefix}  {link.relation}: <{link.truncation}>")

    render_node(root, 0)
    return "\n".join(lines)


def _decode_root(value: object) -> _DiagnosticNode:
    root = _mapping(value, "diagnostic failure")
    _exact_fields(root, {"schema", "type", "message", "links"}, "diagnostic failure")
    if root["schema"] != _SCHEMA:
        raise DiagnosticFailureError("diagnostic failure schema is unsupported")
    return _decode_node(
        root,
        "diagnostic failure",
        nodes=[0],
        active=set(),
        root=True,
    )


def _decode_node(
    value: Mapping[str, object],
    name: str,
    *,
    nodes: list[int],
    active: set[int],
    root: bool = False,
) -> _DiagnosticNode:
    _exact_fields(value, {"type", "message", "links"}, name, allow_schema=root)
    type_label = value["type"]
    message = value["message"]
    links_value = _sequence(value["links"], f"{name} links")
    if not isinstance(type_label, str) or not isinstance(message, str):
        raise DiagnosticFailureError(f"{name} type and message must be strings")
    identity = id(value)
    if identity in active:
        raise DiagnosticFailureError("diagnostic failure records must not cycle")
    nodes[0] += 1
    if nodes[0] > _MAX_NODES:
        raise DiagnosticFailureError("diagnostic failure exceeds 128 records")
    active.add(identity)
    try:
        links = tuple(
            _decode_link(item, nodes=nodes, active=active) for item in links_value
        )
    finally:
        active.remove(identity)
    return _DiagnosticNode(type_label, message, links)


def _decode_link(
    value: object, *, nodes: list[int], active: set[int]
) -> _DiagnosticLink:
    link = _mapping(value, "diagnostic link")
    _exact_fields(
        link,
        {"relation", "record", "truncation"},
        "diagnostic link",
        optional=True,
    )
    relation = link.get("relation")
    if not isinstance(relation, str) or relation not in _RELATIONS:
        raise DiagnosticFailureError("diagnostic link relation is unsupported")
    has_record = "record" in link
    has_truncation = "truncation" in link
    if has_record == has_truncation:
        raise DiagnosticFailureError(
            "diagnostic link must contain exactly one record or truncation"
        )
    if has_record:
        record = _mapping(link["record"], "diagnostic link record")
        return _DiagnosticLink(
            relation,
            record=_decode_node(
                record, "diagnostic record", nodes=nodes, active=active
            ),
        )
    truncation = link["truncation"]
    if not isinstance(truncation, str) or truncation not in _TRUNCATIONS:
        raise DiagnosticFailureError("diagnostic link truncation is unsupported")
    return _DiagnosticLink(relation, truncation=truncation)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise DiagnosticFailureError(f"{name} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise DiagnosticFailureError(f"{name} keys must be strings")
    return value


def _exact_fields(
    value: Mapping[str, object],
    fields: set[str],
    name: str,
    *,
    optional: bool = False,
    allow_schema: bool = False,
) -> None:
    expected = fields if not allow_schema else fields | {"schema"}
    if optional:
        if "relation" not in value or set(value) - expected:
            raise DiagnosticFailureError(f"{name} fields are invalid")
    elif set(value) != expected:
        raise DiagnosticFailureError(f"{name} fields are invalid")


def _sequence(value: object, name: str) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    raise DiagnosticFailureError(f"{name} must be a sequence")

"""Dependency-neutral projection of native exceptions to portable plain data."""

from __future__ import annotations

from collections.abc import Mapping
import re
import traceback

from loom.serialization import PlainData

_SCHEMA = "loom.diagnostic.v1"
_MAX_NODES = 128
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(\b[\w-]*(?:api[_-]?key|auth|credential|password|secret|token)[\w-]*"
    r"\s*=\s*)(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s\"'&,;)]+)"
)


def _capture_exception_details(
    error: BaseException,
    *,
    details: Mapping[str, PlainData] | None = None,
    traceback_text: str | None = None,
) -> dict[str, PlainData]:
    """Capture native causality beside existing owner-supplied failure details.

    The formatted traceback includes notes and source locations, but not locals
    or arbitrary exception attributes. Credential assignments are masked in both
    messages and traceback source lines; arbitrary prose is not a secret-safe
    channel. The detached record does not need the original traceback file.
    """

    return {
        **dict(details or {}),
        "diagnostic_failure": _redact_captured_diagnostic(
            project_diagnostic_failure(error)
        ),
        "traceback": _redact_captured_diagnostic(
            traceback_text
            if traceback_text is not None
            else "".join(traceback.format_exception(error))
        ),
    }


def _redact_captured_diagnostic(value: PlainData) -> PlainData:
    if isinstance(value, str):
        return _CREDENTIAL_ASSIGNMENT.sub(r"\1[redacted]", value)
    if isinstance(value, dict):
        return {key: _redact_captured_diagnostic(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_captured_diagnostic(item) for item in value]
    return value


def project_diagnostic_failure(error: BaseException) -> dict[str, PlainData]:
    """Detach native exception causality into the Loom diagnostic-v1 shape.

    The projection contains only type labels, guarded messages, and causal links.
    It deliberately does not retain tracebacks, notes, locals, or exception
    attributes.
    """

    active: set[int] = set()
    budget = [0]

    def project_node(item: BaseException) -> dict[str, PlainData]:
        budget[0] += 1
        active.add(id(item))
        links: list[PlainData] = []
        try:
            cause = item.__cause__
            if cause is not None:
                links.append(project_link("cause", cause))
            elif not item.__suppress_context__ and item.__context__ is not None:
                links.append(project_link("context", item.__context__))
            if isinstance(item, BaseExceptionGroup):
                for child in item.exceptions:
                    links.append(project_link("group_child", child))
            error_type = type(item)
            return {
                "type": f"{error_type.__module__}.{error_type.__qualname__}",
                "message": _message(item),
                "links": links,
            }
        finally:
            active.remove(id(item))

    def project_link(relation: str, item: BaseException) -> dict[str, PlainData]:
        if id(item) in active:
            return {"relation": relation, "truncation": "cycle"}
        if budget[0] >= _MAX_NODES:
            return {"relation": relation, "truncation": "limit"}
        return {"relation": relation, "record": project_node(item)}

    root = project_node(error)
    return {"schema": _SCHEMA, **root}


def _message(error: BaseException) -> str:
    try:
        return str(error)
    except Exception:  # noqa: BLE001 - formatting must not replace the failure
        return "<exception message unavailable>"

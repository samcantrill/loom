"""Tests for detached inspection-failure diagnostics."""

from __future__ import annotations

import json

import pytest

from loom.diagnostics import DiagnosticFailureError, render_diagnostic_failure
from loom.diagnostics.diagnostic_failure import project_diagnostic_failure
from loom.serialization import freeze_plain_data, thaw_plain_data


pytestmark = pytest.mark.unit


def test_projection_preserves_native_causality_groups_and_shared_occurrences() -> None:
    shared = ValueError("shared child")
    grouped = ExceptionGroup("multiple failures", [shared, shared])
    cause = OSError("missing /private/run/config.json")
    grouped.__cause__ = cause
    grouped.__context__ = RuntimeError("suppressed context")

    projected = project_diagnostic_failure(grouped)

    assert projected == {
        "schema": "loom.diagnostic.v1",
        "type": "builtins.ExceptionGroup",
        "message": "multiple failures (2 sub-exceptions)",
        "links": [
            {
                "relation": "cause",
                "record": {
                    "type": "builtins.OSError",
                    "message": "missing /private/run/config.json",
                    "links": [],
                },
            },
            {
                "relation": "group_child",
                "record": {
                    "type": "builtins.ValueError",
                    "message": "shared child",
                    "links": [],
                },
            },
            {
                "relation": "group_child",
                "record": {
                    "type": "builtins.ValueError",
                    "message": "shared child",
                    "links": [],
                },
            },
        ],
    }
    rendered = render_diagnostic_failure(projected)
    assert "builtins.ExceptionGroup: multiple failures (2 sub-exceptions)" in rendered
    assert "cause:" in rendered
    assert rendered.count("group_child:") == 2
    assert "suppressed context" not in rendered


def test_projection_marks_cycles_and_limits_and_guards_messages() -> None:
    cycle = ValueError("cycle")
    cycle.__cause__ = cycle
    cycle_projection = project_diagnostic_failure(cycle)
    assert cycle_projection["links"] == [{"relation": "cause", "truncation": "cycle"}]

    root = RuntimeError("node-0")
    current = root
    for index in range(1, 129):
        child = RuntimeError(f"node-{index}")
        current.__cause__ = child
        current = child
    limit_projection = project_diagnostic_failure(root)
    node: object = limit_projection
    for _ in range(127):
        assert isinstance(node, dict)
        links = node["links"]
        assert isinstance(links, list)
        link = links[0]
        assert isinstance(link, dict)
        node = link["record"]
    assert isinstance(node, dict)
    assert node["links"] == [{"relation": "cause", "truncation": "limit"}]
    limit_wire = json.loads(
        json.dumps(thaw_plain_data(freeze_plain_data(limit_projection)))
    )
    assert render_diagnostic_failure(limit_wire).count("builtins.RuntimeError") == 128

    class Hostile(Exception):
        def __str__(self) -> str:
            raise RuntimeError("do not disclose formatter failure")

    hostile = project_diagnostic_failure(Hostile())
    assert hostile["message"] == "<exception message unavailable>"
    assert "formatter failure" not in render_diagnostic_failure(hostile)


@pytest.mark.parametrize(
    "value",
    [
        object(),
        {"schema": "loom.diagnostic.v1", "type": "x", "message": "x"},
        {
            "schema": "loom.diagnostic.v1",
            "type": "x",
            "message": "x",
            "links": [{"relation": "unknown", "truncation": "cycle"}],
        },
        {
            "schema": "loom.diagnostic.v1",
            "type": "x",
            "message": "x",
            "links": [{"relation": "cause", "record": {}, "truncation": "cycle"}],
        },
    ],
)
def test_renderer_rejects_noncanonical_external_data(value: object) -> None:
    with pytest.raises(DiagnosticFailureError):
        render_diagnostic_failure(value)

"""Terminal views of run context, notes and query vocabulary."""

from __future__ import annotations

import io
import json

import pytest

from loom.cli.main import main
from loom.cli.queue import LOCAL_DAEMON_SCHEMA_VERSION
from loom.coordinator import CoordinatorClient
from loom.runs import QueryPage, RunAnnotations, RunContext, RunNote, RunNotePage
from loom.runs.query import query_fields

pytestmark = pytest.mark.unit

RUN = "file:///runs/observed"
WHEN = "2026-11-02T09:20:31.390207+00:00"


def _views(monkeypatch, argv, operation, request, result):
    def native(client, op, payload, expected_id):
        assert op == operation and payload == request
        return result

    monkeypatch.setattr(CoordinatorClient, "_native_call", native)
    outputs = []
    for fmt in ("text", "json"):
        out, err = io.StringIO(), io.StringIO()
        code = main(
            ["runs", *argv, "--endpoint", "/unused/socket", "--format", fmt],
            stdout=out,
            stderr=err,
        )
        assert (code, err.getvalue()) == (0, "")
        outputs.append(out.getvalue())
    assert json.loads(outputs[1]) == {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "ok": True,
        "warnings": [],
        "result": result.to_dict() if hasattr(result, "to_dict") else result,
    }
    return outputs[0]


def test_notes_wrap_full_text_in_returned_order_and_show_cursor(monkeypatch):
    monkeypatch.setenv("COLUMNS", "64")
    text = "Inspect the first measurement again after reviewing its original reference."
    page = RunNotePage(
        (
            RunNote(RUN, "a", text, "zoe", WHEN),
            RunNote(RUN, "b", "Reviewed.", "ada", WHEN),
        ),
        next_cursor="next-note",
    )
    output = _views(
        monkeypatch,
        ["notes", RUN, "--limit", "2"],
        "list_run_notes",
        {"run_uri": RUN, "cursor": None, "limit": 2},
        page,
    )
    lines = output.splitlines()
    assert lines[0].split() == ["TIME", "(UTC)", "AUTHOR", "NOTE"]
    assert lines[1].split() == [WHEN, "zoe", "↓"]
    assert lines[-2].split() == [WHEN, "ada", "Reviewed."]
    assert " ".join(" ".join(lines[2:-2]).split()) == f"Note: {text}"
    assert max(map(len, lines)) <= 64
    assert lines[-1] == "Continue with --cursor next-note"


def test_note_append_confirms_committed_id(monkeypatch):
    note = RunNote(RUN, "recorded-id", "Reviewed.", "zoe", WHEN)
    output = _views(
        monkeypatch,
        ["notes", RUN, "--text", note.text, "--mutation-id", "request-id"],
        "append_run_note",
        {"run_uri": RUN, "mutation_id": "request-id", "text": note.text},
        note,
    )
    assert output.splitlines() == ["Note recorded: recorded-id"]


def test_context_distinguishes_original_annotations_and_partial_submission_links(
    monkeypatch,
):
    links = tuple(
        {"operation_id": f"op-{i:02d}", "accepted_at": WHEN, "state": "applied"}
        for i in range(20)
    )
    context = RunContext(
        RUN,
        RunAnnotations(
            RUN,
            2,
            "Follow-up",
            {"study_name": "later"},
            {"capture": {"sample_rate": 30}},
            "op-00",
            "coordinator",
        ),
        {
            **links[0],
            "principal_id": "submitter",
            "context": {"description": "Initial study", "tags": {}, "metadata": {}},
        },
        links,
        37,
        None,
        ("inspection_unavailable",),
    )
    monkeypatch.setenv("COLUMNS", "80")
    output = _views(
        monkeypatch,
        ["context", RUN],
        "get_run_context",
        {"run_uri": RUN},
        context.to_dict(),
    )
    original, current = output.split("Current annotations")
    assert original.startswith(f"{RUN}\n\nOriginal submission\n")
    assert "submitter" in original and "Initial study" in original
    annotations, submissions = current.split(
        "Linked submissions (20 of 37 submissions)"
    )
    assert "revision: 2" in annotations and "Follow-up" in annotations
    assert "tags:\n    study_name: later" in annotations
    assert "metadata:\n    capture:\n      sample_rate: 30" in annotations
    links_text, missing = submissions.split("Unavailable evidence")
    assert [
        line.split()[0] for line in links_text.splitlines() if line.startswith("op-")
    ] == [link["operation_id"] for link in links]
    assert missing.strip() == "inspection_unavailable"


def test_context_surfaces_missing_original_and_annotations(monkeypatch):
    context = RunContext(
        RUN,
        None,
        None,
        (),
        0,
        None,
        (
            "authority_unavailable",
            "original_submission_unknown",
            "inspection_unavailable",
        ),
    )
    output = _views(
        monkeypatch,
        ["context", RUN],
        "get_run_context",
        {"run_uri": RUN},
        context.to_dict(),
    )
    assert "Original submission\n  Unavailable" in output
    assert "Current annotations\n  Unavailable" in output
    assert "No linked submissions." in output
    assert output.split("Unavailable evidence")[1].split() == list(context.unavailable)


def test_fields_marks_only_sortable_entity_fields(monkeypatch):
    result = query_fields("runs")
    output = _views(
        monkeypatch,
        ["fields", "--entity", "runs"],
        "query_fields",
        {"entity": "runs"},
        result,
    )
    native, remainder = output.split("Stage fields")
    stage, operators = remainder.split("Supported operators")
    assert [row.strip() for row in native.splitlines()[1:] if row.strip()] == [
        name + (" (sortable)" if name in result["sort_fields"] else "")
        for name in result["native_fields"]
    ]
    # The stage field created_at shares its name with an entity sort key.
    assert stage.split() == result["stage_fields"]
    assert operators.split() == result["operators"]


@pytest.mark.parametrize(
    ("argv", "items", "lines"),
    [
        ([], ({"key": "model.name"}, {"key": "study"}), ["model.name", "study"]),
        (
            ["--key", "study"],
            ({"value": ""}, {"value": "phase one"}),
            ['""', "phase one"],
        ),
        (["--key", "missing"], (), ["No tags returned on this page."]),
    ],
)
def test_tags_show_each_observed_string_and_retain_page_evidence(
    monkeypatch, argv, items, lines
):
    request = {"scope": {"kind": "managed"}, "cursor": None, "limit": 50}
    operation = "tag_keys"
    if argv:
        operation = "tag_values"
        request["key"] = argv[1]
    page = QueryPage(
        items,
        "next-tags",
        {"kind": "managed"},
        "coordinator",
        WHEN,
        ({"code": "annotations_unavailable", "run_uri": RUN},),
        False,
        500,
    )
    output = _views(monkeypatch, ["tags", *argv], operation, request, page)
    assert output.splitlines() == [
        *lines,
        "Coverage incomplete (500 candidates examined).",
        f"Warning: annotations_unavailable (run_uri={RUN})",
        "Continue with --cursor next-tags",
    ]

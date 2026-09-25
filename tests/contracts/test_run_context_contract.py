"""Caller data boundaries, digest compatibility and authority initialization."""

from dataclasses import replace
import json
import sqlite3
from typing import Any, cast

import pytest

from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.queue.errors import QueueServiceError
from loom.runs import SubmissionContext
from loom.serialization import stable_json_bytes

pytestmark = pytest.mark.contract


def test_annotation_patch_preserves_unrelated_keys_and_distinguishes_null_removal():
    from loom.runs import AnnotationConflictError, AnnotationPatch, RunAnnotations

    original = RunAnnotations(
        "file:///run",
        3,
        "reason",
        {"keep": "yes", "drop": "no"},
        {"keep": [1], "drop": 2, "nullable": 3},
        "submission",
        "coordinator",
    )
    patch = AnnotationPatch.from_dict(
        {
            "expected_revision": 3,
            "set_tags": {"new": "label"},
            "remove_tags": ["drop"],
            "set_metadata": {"nullable": None},
            "remove_metadata": ["drop"],
        }
    )
    result = patch.apply(original)
    assert result.revision == 4
    assert result.description == "reason"
    assert result.tags == {"keep": "yes", "new": "label"}
    assert result.metadata == {"keep": (1,), "nullable": None}
    assert result.initializer_operation_id == "submission"
    assert AnnotationPatch.from_dict(patch.to_dict()) == patch
    assert (
        AnnotationPatch.from_dict({"expected_revision": 4, "description": None})
        .apply(result)
        .description
        is None
    )
    with pytest.raises(AnnotationConflictError) as error:
        patch.apply(result)
    assert error.value.current_revision == 4


@pytest.mark.parametrize(
    "fields",
    [
        {"set_tags": {"x": "v"}, "remove_tags": ["x"]},
        {"set_metadata": {"x": None}, "remove_metadata": ["x"]},
        {"remove_tags": ["x", "x"]},
        {"remove_metadata": "key"},
        {"expected_revision": True},
        {"expected_revision": -1},
        {"description": "é" * 8193},
        {"set_metadata": {"n": float("nan")}},
        {"author": "spoofed"},
    ],
)
def test_annotation_patch_rejects_ambiguous_or_unbounded_changes(fields):
    from loom.runs import AnnotationPatch

    with pytest.raises(ValueError):
        AnnotationPatch.from_dict({"expected_revision": 0, **fields})


def test_annotation_patch_checks_result_size_not_only_patch_size():
    from loom.runs import AnnotationPatch, RunAnnotations

    original = RunAnnotations(
        "file:///run", 1, None, {str(i): "v" for i in range(128)}, {}
    )
    with pytest.raises(ValueError, match="128"):
        AnnotationPatch(1, set_tags={"extra": "v"}).apply(original)


def test_note_and_encoded_transport_limits_are_checked_before_dispatch():
    from loom.queue._coordinator_control import validate_request

    request = {"run_uri": "file:///run", "mutation_id": "note", "text": "é" * 8192}
    assert validate_request("append_run_note", request)["text"] == request["text"]
    with pytest.raises(ValueError, match="note text"):
        validate_request("append_run_note", {**request, "text": request["text"] + "é"})
    with pytest.raises(ValueError, match="transport budget"):
        validate_request("patch_run_annotations", {"run_uri": "file:///run", "mutation_id": "patch",
            "patch": {"expected_revision": 1, "set_metadata": {"escaped": "漢" * 15000}}})
    for fields in ({"author": "spoof"}, {"created_at": "2000-01-01"}):
        with pytest.raises(ValueError, match="fields"):
            validate_request("append_run_note", {**request, **fields})
    for options in ({"limit": 51, "cursor": None}, {"limit": 1, "cursor": '["file:///other","",""]'}):
        with pytest.raises(ValueError):
            validate_request("list_run_notes", {"run_uri": "file:///run", **options})


def test_note_pages_bound_encoded_bytes_and_continue_without_loss():
    from loom.runs import RunNote
    from loom.runs.annotations import page_notes
    from loom.queue._coordinator_control import encode_wire, MAX_RESPONSE_BYTES

    notes = tuple(RunNote("file:///run", f"note-{i:03d}", "é" * 8192, "caller", "2026-09-25T01:00:00+00:00") for i in range(50))
    page = page_notes("file:///run", notes, 50, None)
    assert 0 < len(page.notes) < 50
    seen = list(page.notes)
    while True:
        assert len(encode_wire({"ok": True, "result": page.to_dict()})) < MAX_RESPONSE_BYTES
        if page.next_cursor is None:
            break
        page = page_notes("file:///run", notes, 50, page.next_cursor)
        seen.extend(page.notes)
    assert tuple(seen) == notes


def request(context=None):
    return PrepareRunRequest(
        "intent",
        "target",
        PreparationSource("shared", "projects", ".", ("pipeline.yaml",)),
        "pipeline.yaml",
        "profile",
        context=context,
    )


def test_empty_context_preserves_historical_bytes_and_digest():
    original = request()
    expected = {
        "operation_id": "intent",
        "run_name": "target",
        "source": {
            "mode": "shared",
            "root": "projects",
            "path": ".",
            "include": ["pipeline.yaml"],
        },
        "config_path": "pipeline.yaml",
        "preparation_profile": "profile",
        "overlays": [],
        "overrides": [],
        "run_options": {},
    }
    assert stable_json_bytes(original.to_dict()) == stable_json_bytes(expected)
    assert request(SubmissionContext()).to_dict() == expected
    assert request(SubmissionContext()).intent_digest(
        "principal"
    ) == original.intent_digest("principal")
    assert request(SubmissionContext(description="reason")).intent_digest(
        "principal"
    ) != original.intent_digest("principal")


def test_context_is_inert_detached_typed_and_deeply_immutable():
    supplied = {
        "revision": 3,
        "text": "3",
        "null": None,
        "status": "not-native",
        "submitted_by": "not-native",
        "commit": "not-native",
        "nested": [{"_target_": "nonexistent.module.function"}],
    }
    context = SubmissionContext("reason", {"application-key": "value"}, supplied)
    supplied["nested"][0]["_target_"] = "changed"
    frozen = cast(Any, context.metadata)
    assert frozen["nested"][0]["_target_"] == "nonexistent.module.function"
    detached = cast(Any, context.to_dict())
    detached["metadata"]["revision"] = 99
    assert context.metadata["revision"] == 3
    assert type(context.metadata["revision"]) is int
    assert type(context.metadata["text"]) is str
    with pytest.raises(TypeError):
        frozen["nested"][0]["_target_"] = "changed"
    assert PrepareRunRequest.from_dict(request(context).to_dict()).context == context


@pytest.mark.parametrize(
    "fields",
    [
        {"metadata": {"x": float("nan")}},
        {"metadata": {"x": float("inf")}},
        {"metadata": {"x": object()}},
        {"metadata": {"x": b"bytes"}},
        {"tags": {"x": 3}},
        {"tags": {str(i): "v" for i in range(129)}},
        {"tags": {"x" * 129: "v"}},
        {"tags": {"x": "é" * 513}},
        {"description": "é" * 8193},
        {"metadata": {"x": "a" * (48 * 1024)}},
    ],
)
def test_context_rejects_non_json_or_oversize_payload(fields):
    with pytest.raises(ValueError):
        SubmissionContext(**fields)


def test_explicit_conflicts_rejected_before_submission():
    original = request(SubmissionContext(tags={"model": "first"}))
    with pytest.raises(QueueServiceError, match="conflict"):
        replace(original, run_options={"tags": {"model": "second"}})
    assert (
        replace(original, run_options={"tags": {"model": "first"}}).context
        == original.context
    )


def test_context_accepts_exact_utf8_and_payload_boundaries():
    tags = {str(i): "v" for i in range(127)}
    tags["é" * 64] = "é" * 512
    assert len(SubmissionContext("é" * 8192, tags).tags) == 128
    overhead = len(stable_json_bytes(SubmissionContext(metadata={"x": ""}).to_dict()))
    context = SubmissionContext(metadata={"x": "a" * (48 * 1024 - overhead)})
    assert len(stable_json_bytes(context.to_dict())) == 48 * 1024
    with pytest.raises(ValueError, match="48 KiB"):
        SubmissionContext(metadata={"x": "a" * (48 * 1024 - overhead + 1)})


@pytest.mark.parametrize("backend", ["embedded", "repository", "service"])
def test_authority_initialization_is_atomic_once_and_separate_from_lifecycle(
    tmp_path, backend
):
    from contextlib import ExitStack
    from loom.authority._repository import initialize_authority_repository
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.pipeline.stores.service_authority import (
        LocalAuthorityService,
        create_service_authority_store,
    )

    uri = (tmp_path / "run").as_uri()
    with ExitStack() as stack:
        if backend == "embedded":
            store = SQLitePerRunAuthorityStore(uri)
            store.create_run(uri)
        elif backend == "repository":
            store = initialize_authority_repository(
                tmp_path / "authority", service_generation="generation"
            )
            store.admit_run(uri)
        else:
            service = stack.enter_context(LocalAuthorityService.start())
            store = create_service_authority_store(service.config())
            store.create_run(uri)
        before = store.open_run(uri).to_dict()
        assert store.read_run_annotations(uri) is None
        first = store.initialize_run_annotations(
            uri,
            SubmissionContext("first", {"project": "one"}, {"n": 3}),
            "op-one",
            "coordinator",
        )
        assert first.revision == 1
        assert (
            store.initialize_run_annotations(
                uri, SubmissionContext("second"), "op-two", "coordinator"
            )
            == first
        )
        assert (
            store.initialize_run_annotations(
                uri,
                SubmissionContext("first", {"project": "one"}, {"n": 3}),
                "op-one",
                "coordinator",
            )
            == first
        )
        assert store.read_run_annotations(uri) == first
        assert store.open_run(uri).to_dict() == before


@pytest.mark.parametrize("backend", ["embedded", "repository"])
def test_additive_migration_preserves_legacy_metadata_without_inventing_context(
    tmp_path, backend
):
    from loom.authority._repository import initialize_authority_repository
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

    uri = (tmp_path / "run").as_uri()
    legacy = {
        "tags": {"legacy": "value"},
        "notes": ["old observation"],
        "commit": "caller value",
    }
    if backend == "embedded":
        store = SQLitePerRunAuthorityStore(uri)
        store.create_run(uri, metadata=legacy)
        database = tmp_path / "run" / ".loom" / "authority.sqlite3"
        table, version = "metadata", 7
    else:
        store = initialize_authority_repository(
            tmp_path / "authority", service_generation="generation"
        )
        store.admit_run(uri, metadata=legacy)
        database = tmp_path / "authority" / "authority.sqlite3"
        table, version = "repository_metadata", 8
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE run_annotations")
        conn.execute(
            f"UPDATE {table} SET value = ? WHERE key = 'schema_version'",
            (str(version),),
        )
    if backend == "repository":
        cast(Any, store).initialize(service_generation="generation")
    assert store.read_run_annotations(uri) is None
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM run_annotations").fetchone()[0] == 0
        run_table = "run_state" if backend == "embedded" else "authority_runs"
        assert (
            json.loads(
                conn.execute(f"SELECT metadata_json FROM {run_table}").fetchone()[0]
            )
            == legacy
        )

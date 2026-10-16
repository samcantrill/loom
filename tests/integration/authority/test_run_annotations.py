"""Run-scoped receipts, atomic CAS, durable notes and authority adapter parity."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from typing import Any

import pytest

from loom.runs import AnnotationConflictError, SubmissionContext

pytestmark = pytest.mark.integration


@pytest.fixture(params=["embedded", "repository", "service"])
def authority(tmp_path, request):
    from loom.authority._repository import initialize_authority_repository
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
    from loom.pipeline.stores.service_authority import (
        LocalAuthorityService,
        create_service_authority_store,
    )

    with ExitStack() as stack:
        service_store = None
        if request.param == "service":
            service = stack.enter_context(LocalAuthorityService.start())
            service_store = create_service_authority_store(service.config())

        def factory(uri) -> Any:
            if service_store is not None:
                return service_store
            if request.param == "repository":
                return initialize_authority_repository(
                    tmp_path / "authority", service_generation="generation"
                )
            return SQLitePerRunAuthorityStore(uri)

        uris = [(tmp_path / name).as_uri() for name in ("one", "two")]
        for uri in uris:
            store: Any = factory(uri)
            if request.param == "repository":
                store.admit_run(uri)
            else:
                store.create_run(uri)
        yield factory, uris, request.param


def test_atomic_receipts_cas_restart_cross_run_scope_and_independent_notes(authority):
    factory, (uri, other), backend = authority
    store = factory(uri)
    initial = store.initialize_run_annotations(
        uri,
        SubmissionContext("original", {"keep": "yes"}, {"n": 3}),
        "initial",
        "coordinator",
    )
    before = store.open_run(uri).to_dict()

    def patch(key):
        try:
            return store.mutate_run_annotations(
                uri,
                "alice",
                key,
                "patch_run_annotations",
                {"expected_revision": 1, "set_tags": {key: "v"}},
            )
        except AnnotationConflictError as exc:
            return exc

    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(patch, ["first", "second"]))
    winner = next(
        value for value in results if not isinstance(value, AnnotationConflictError)
    )
    conflict = next(
        value for value in results if isinstance(value, AnnotationConflictError)
    )
    assert conflict.current_revision == 2
    winning_key = next(key for key in winner.tags if key != "keep")
    losing_key = "second" if winning_key == "first" else "first"
    rebased = store.mutate_run_annotations(
        uri,
        "alice",
        "rebase",
        "patch_run_annotations",
        {"expected_revision": 2, "set_tags": {losing_key: "v"}},
    )
    assert rebased.tags == {"keep": "yes", "first": "v", "second": "v"}
    store = factory(uri)  # Reopen durable owners before replaying an old revision.
    assert (
        store.mutate_run_annotations(
            uri,
            "alice",
            winning_key,
            "patch_run_annotations",
            {"expected_revision": 1, "set_tags": {winning_key: "v"}},
        )
        == winner
    )
    assert (
        store.initialize_run_annotations(
            uri,
            SubmissionContext("original", {"keep": "yes"}, {"n": 3}),
            "initial",
            "coordinator",
        )
        == initial
    )
    for operation, change in [
        ("append_run_note", {"text": "changed operation"}),
        ("patch_run_annotations", {"expected_revision": 3, "description": "changed"}),
    ]:
        with pytest.raises(AnnotationConflictError):
            store.mutate_run_annotations(
                uri, "alice", winning_key, operation, change
            )
    # Another run and another principal have independent ID scopes.
    other_store = factory(other)
    assert (
        other_store.mutate_run_annotations(
            other,
            "alice",
            winning_key,
            "append_run_note",
            {"text": "other"},
        ).text
        == "other"
    )
    with ThreadPoolExecutor(2) as executor:
        notes = list(
            executor.map(
                lambda name: store.mutate_run_annotations(
                    uri,
                    name,
                    winning_key if name == "bob" else "note",
                    "append_run_note",
                    {"text": name},
                ),
                ["alice", "bob"],
            )
        )
    assert {note.author for note in notes} == {"alice", "bob"}
    assert all(
        note.created_at.endswith("+00:00") and note.source == "native" for note in notes
    )
    assert (
        factory(uri).mutate_run_annotations(
            uri,
            "alice",
            "note",
            "append_run_note",
            {"text": "alice"},
        )
        == notes[0]
    )
    first = store.list_run_notes(uri, 1)
    second = store.list_run_notes(uri, 1, first.next_cursor)
    assert len(first.notes) == len(second.notes) == 1
    assert first.notes[0].note_id != second.notes[0].note_id
    assert second.next_cursor is None
    assert store.read_run_annotations(uri).revision == 3
    assert store.open_run(uri).to_dict() == before


def test_first_write_starts_empty_and_conflict_rolls_back(authority):
    factory, (uri, _), _ = authority
    store = factory(uri)
    before = store.open_run(uri).to_dict()
    assert store.read_run_annotations(uri) is None
    assert store.list_run_notes(uri).notes == ()
    assert store.read_run_annotations(uri) is None
    with pytest.raises(AnnotationConflictError) as error:
        store.mutate_run_annotations(
            uri, "alice", "first", "patch_run_annotations", {"expected_revision": 1},
        )
    assert error.value.current_revision == 0
    assert store.read_run_annotations(uri) is None
    value = store.mutate_run_annotations(
        uri, "alice", "first", "patch_run_annotations",
        {"expected_revision": 0, "set_tags": {"new": "yes"}},
    )
    assert value.revision == 1 and value.tags == {"new": "yes"}
    assert value.description is None and value.metadata == {}
    assert value.initializer_operation_id is value.initializer_coordinator_id is None
    assert factory(uri).read_run_annotations(uri) == value
    assert factory(uri).list_run_notes(uri).notes == ()
    assert store.open_run(uri).to_dict() == before


def test_native_note_limits_preserve_receipts_and_lifecycle(authority):
    from loom.runs.context import RUN_CONTEXT_LIMITS

    factory, (uri, _), _ = authority
    store = factory(uri)
    before = store.open_run(uri).to_dict()
    with pytest.raises(ValueError, match="note text"):
        store.mutate_run_annotations(
            uri, "alice", "note", "append_run_note",
            {"text": "x" * (RUN_CONTEXT_LIMITS["text_bytes"] + 1)},
        )
    assert store.read_run_annotations(uri) is None
    assert store.list_run_notes(uri).notes == ()
    text = "é" * (RUN_CONTEXT_LIMITS["text_bytes"] // 2)
    note = store.mutate_run_annotations(
        uri, "alice", "note", "append_run_note", {"text": text},
    )
    reopened = factory(uri)
    assert reopened.list_run_notes(uri).notes == (note,)
    assert note.text == text and note.author == "alice" and note.source == "native"
    assert note.created_at.endswith("+00:00")
    assert reopened.mutate_run_annotations(
        uri, "alice", "note", "append_run_note", {"text": text},
    ) == note
    annotations = reopened.read_run_annotations(uri)
    assert annotations.revision == 0 and annotations.tags == {}
    assert annotations.initializer_operation_id is None
    assert reopened.open_run(uri).to_dict() == before

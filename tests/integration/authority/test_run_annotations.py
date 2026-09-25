"""Run-scoped receipts, atomic CAS, durable notes and authority adapter parity."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import sqlite3
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
                SubmissionContext(),
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
        SubmissionContext(),
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
            SubmissionContext(),
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
                uri, "alice", winning_key, operation, change, SubmissionContext()
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
            SubmissionContext(),
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
                    SubmissionContext(),
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
            SubmissionContext(),
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


def test_legacy_first_write_and_rollback_preserve_runtime_evidence(authority):
    factory, (uri, _), backend = authority
    store = factory(uri)
    legacy = SubmissionContext(tags={"legacy": "yes"})
    assert store.read_run_annotations(uri) is None
    page = store.list_run_notes(uri, legacy_notes=("old note",))
    assert page.notes[0].author is page.notes[0].created_at is None
    assert page.notes[0].source == "legacy_runtime"
    assert store.read_run_annotations(uri) is None
    with pytest.raises(AnnotationConflictError):
        store.mutate_run_annotations(
            uri,
            "alice",
            "first",
            "patch_run_annotations",
            {"expected_revision": 1},
            legacy,
            ("old note",),
        )
    assert store.read_run_annotations(uri) is None
    value = store.mutate_run_annotations(
        uri,
        "alice",
        "first",
        "patch_run_annotations",
        {"expected_revision": 0, "set_tags": {"new": "yes"}},
        legacy,
        ("old note",),
    )
    assert value.revision == 1 and value.tags == {"legacy": "yes", "new": "yes"}
    assert value.initializer_operation_id is None
    assert factory(uri).list_run_notes(uri).notes == page.notes


def test_legacy_note_sizes_preserve_mutations_and_bound_listing(authority):
    from loom.pipeline.runtime.options import RunOptions
    from loom.runs.context import RUN_CONTEXT_LIMITS

    factory, (uri, _), backend = authority
    store = factory(uri)
    # RunOptions is the supported producer, with no native append text limit.
    texts = tuple(RunOptions(notes=("x" * 16385, "\x00" * 131072)).notes)
    first = store.list_run_notes(uri, 1, legacy_notes=texts)
    assert first.notes[0].text == texts[0]
    assert first.notes[0].author is first.notes[0].created_at is None
    assert first.notes[0].source == "legacy_runtime"
    assert first.next_cursor is not None
    with pytest.raises(ValueError, match="legacy-000000000001.*unrepresentable"):
        store.list_run_notes(uri, cursor=first.next_cursor, legacy_notes=texts)
    patch = store.mutate_run_annotations(
        uri, "alice", "patch", "patch_run_annotations",
        {"expected_revision": 0, "set_tags": {"review": "yes"}},
        SubmissionContext(), texts,
    )
    assert patch.tags == {"review": "yes"}
    note = store.mutate_run_annotations(
        uri, "alice", "note", "append_run_note", {"text": "native"},
        SubmissionContext(), texts,
    )
    reopened = factory(uri)
    assert reopened.list_run_notes(uri, 1).notes == first.notes
    with pytest.raises(ValueError, match="legacy-000000000001.*unrepresentable"):
        reopened.list_run_notes(uri, cursor=first.next_cursor)
    # Durable owners retain the complete unrepresentable record, not a truncation.
    if backend != "service":
        import json
        from loom.io.uris import uri_to_path

        database = (
            reopened.database_path if backend == "repository"
            else uri_to_path(uri) / ".loom/authority.sqlite3"
        )
        with sqlite3.connect(database) as conn:
            value = json.loads(conn.execute(
                "SELECT note_json FROM run_annotation_notes WHERE run_uri=? AND note_id=?",
                (uri, "legacy-000000000001"),
            ).fetchone()[0])
        assert value["text"] == texts[1]
        assert value["author"] is value["created_at"] is None
    assert reopened.mutate_run_annotations(
        uri, "alice", "note", "append_run_note", {"text": "native"},
        SubmissionContext(), texts,
    ) == note
    with pytest.raises(ValueError, match="note text"):
        store.mutate_run_annotations(
            uri, "alice", "too-long", "append_run_note",
            {"text": "x" * (RUN_CONTEXT_LIMITS["text_bytes"] + 1)},
            SubmissionContext(), texts,
        )


@pytest.mark.parametrize("backend", ["embedded", "repository"])
def test_annotation_mutation_schema_migration_preserves_initial_context(
    tmp_path, backend
):
    from loom.authority._repository import initialize_authority_repository
    from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore

    uri = (tmp_path / "run").as_uri()
    if backend == "embedded":
        store = SQLitePerRunAuthorityStore(uri)
        store.create_run(uri)
        database, table, version = (
            tmp_path / "run/.loom/authority.sqlite3",
            "metadata",
            8,
        )
    else:
        store = initialize_authority_repository(
            tmp_path / "authority", service_generation="generation"
        )
        store.admit_run(uri)
        database, table, version = (
            tmp_path / "authority/authority.sqlite3",
            "repository_metadata",
            9,
        )
    original = store.initialize_run_annotations(
        uri, SubmissionContext("original"), "op", "coord"
    )
    before = store.open_run(uri).to_dict()
    with sqlite3.connect(database) as conn:
        conn.execute("DROP TABLE run_annotation_mutations")
        conn.execute("DROP TABLE run_annotation_notes")
        conn.execute(
            f"UPDATE {table} SET value=? WHERE key='schema_version'", (str(version),)
        )
    if backend == "repository":
        store = initialize_authority_repository(
            tmp_path / "authority", service_generation="generation"
        )
    assert store.read_run_annotations(uri) == original
    assert store.open_run(uri).to_dict() == before
    assert store.list_run_notes(uri).notes == ()

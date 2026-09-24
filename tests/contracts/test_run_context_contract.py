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

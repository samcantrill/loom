"""Exact output metadata remains authority-owned through retry and reuse."""

from dataclasses import replace
import json
from types import SimpleNamespace
from typing import Any

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue._output_selection import output_operation, validate_output_request
from loom.runs import CollectionScope, OutputLocator, OutputSelection, SelectedOutput
from loom.runs.query import InvalidCursorError

pytestmark = pytest.mark.contract


def commit(store, uri, version, *, stage="produce", outputs=2):
    previous = store.list_output_commits(uri, stage_name=stage)
    if version > 1:
        store.transition_stage(
            uri,
            stage,
            from_status=StageStatus.SUCCEEDED,
            to_status=StageStatus.STALE,
            intent=TransitionIntent.RESUME,
        )
    attempt = store.allocate_stage_attempt(
        uri, stage, owner_id="worker", lease_ttl_seconds=300
    )
    return store.record_output_commit(
        uri,
        stage,
        attempt_id=attempt.attempt.attempt_id,
        **(
            {"owner_id": "worker"}
            if not isinstance(store, SQLitePerRunAuthorityStore)
            else {}
        ),
        fencing_token=attempt.lease.fencing_token,
        supersedes_commit_id=previous[-1].commit.commit_id if previous else None,
        outputs={
            f"out{n}": ArtifactRef(
                artifact_id=f"{stage}/{version}/{n}",
                uri=f"s3://uninstalled/{version}/{n}",
                artifact_type="invoice" if n else "summary",
                metadata={"literal.key": version, "_target_": "must.never.import"},
            )
            for n in range(outputs)
        },
    )


def fixture(tmp_path, backend="embedded") -> tuple[Any, Any, str]:
    factory: Any
    root = tmp_path / "runs"
    root.mkdir()
    uri = (root / "producer").as_uri()
    if backend == "embedded":
        authority = SQLitePerRunAuthorityStore(uri)
        authority.create_run(uri)

        def embedded_factory(address):
            return authority if address == uri else SQLitePerRunAuthorityStore(address)

        factory = embedded_factory
    else:
        from tests.integration.authority.test_coordinator_authority_api import (
            _authority_factory,
        )

        repository, factory = _authority_factory(tmp_path)
        repository.admit_run(uri)
        from loom.pipeline.stores.authority import CoordinatorAdmissionRequest

        factory(uri).bind_coordinator_admission(
            uri,
            CoordinatorAdmissionRequest(
                operation_id="original-op",
                coordinator_id="coordinator",
                run_uri=uri,
                intent_digest="intent",
            ),
        )
        authority = repository
    daemon = SimpleNamespace(
        config=SimpleNamespace(
            run_store_root=root, coordinator_authority_factory=factory
        ),
        _require_started=lambda: "coordinator",
    )
    return daemon, authority, uri


def select(daemon, request, operation="select_outputs"):
    return output_operation(
        daemon,
        operation,
        validate_output_request(operation, {"selection": request.to_dict()}),
    )


def pages(daemon, request):
    result = []
    while True:
        page = select(daemon, request)
        result.extend(page.items)
        if page.next_cursor is None:
            return result
        request = replace(request, cursor=page.next_cursor)


@pytest.mark.parametrize("backend", ["embedded", "authenticated"])
def test_exact_current_history_failed_run_and_no_payload_reads(tmp_path, backend):
    daemon, authority, uri = fixture(tmp_path, backend)
    old = commit(authority, uri, 1)
    request = OutputSelection(run_uris=(uri,), stage_names=("produce",), scope=CollectionScope(), limit=1)
    first = select(daemon, request)
    chosen = SelectedOutput.from_dict(first.items[0])
    newer = commit(authority, uri, 2)
    authority.allocate_stage_attempt(uri, "downstream", owner_id="worker")
    authority.transition_stage(uri, "downstream", from_status=StageStatus.RUNNING, to_status=StageStatus.FAILED)
    authority.transition_run(
        uri, from_status=authority.open_run(uri).status, to_status=RunStatus.FAILED
    )
    current = pages(daemon, request)
    assert {r["locator"]["commit_id"] for r in current} == {newer.commit.commit_id}
    assert all(r["observation"]["run_status"] == "FAILED" for r in current)
    assert select(daemon, replace(request, stage_names=("downstream",))).items[0]["outcome"] == "no_matching_output"
    exact = select(
        daemon, OutputSelection(locator=chosen.locator, scope=CollectionScope())
    )
    assert exact.items[0]["artifact"] == chosen.artifact.to_dict()
    assert exact.items[0]["locator"]["commit_id"] == old.commit.commit_id
    assert exact.items[0]["availability"] == "not_checked"
    history = pages(daemon, replace(request, history="all"))
    assert len(history) == 4
    assert {r["locator"]["commit_id"] for r in history} == {
        old.commit.commit_id,
        newer.commit.commit_id,
    }
    assert (
        len(select(daemon, replace(request, limit=200), "list_output_commits").items)
        == 2
    )
    assert (
        len(
            pages(
                daemon,
                replace(
                    request,
                    artifact_type="invoice",
                    metadata={"literal.key": 1},
                    history="all",
                ),
            )
        )
        == 1
    )
    assert (
        len(
            pages(
                daemon,
                replace(
                    request,
                    artifact_type="invoice",
                    metadata={"literal.key": 1.0},
                    history="all",
                ),
            )
        )
        == 1
    )
    assert (
        select(daemon, replace(request, metadata={"literal.key": True})).items[0][
            "outcome"
        ]
        == "no_matching_output"
    )
    no_match = select(daemon, replace(request, stage_names=("absent",)))
    assert no_match.items[0]["outcome"] == "no_matching_output" and no_match.complete
    no_output = select(daemon, replace(request, output_name="absent"))
    assert no_output.items[0]["outcome"] == "no_matching_output"
    forbidden = select(
        daemon, replace(request, run_uris=((tmp_path / "outside").as_uri(),))
    )
    assert forbidden.items[0]["outcome"] == "run_not_found"
    with pytest.raises(InvalidCursorError):
        select(daemon, replace(request, cursor=first.next_cursor, history="all"))
    assert (
        json.loads(json.dumps(chosen.to_dict()))["artifact"]["metadata"]["_target_"]
        == "must.never.import"
    )


def test_reuse_checks_original_scope_and_authority_and_retains_match(tmp_path):
    from loom.pipeline.stores.read_models import ActionResultBinding
    from loom.pipeline.stores.authority import CoordinatorAdmissionRequest

    daemon, authority, uri = fixture(tmp_path)
    published = commit(authority, uri, 1)
    consumer_uri = (daemon.config.run_store_root / "consumer").as_uri()
    consumer = SQLitePerRunAuthorityStore(consumer_uri)
    consumer.create_run(consumer_uri)
    consumer.bind_coordinator_admission(
        consumer_uri,
        CoordinatorAdmissionRequest(
            operation_id="consumer-op",
            coordinator_id="coordinator",
            run_uri=consumer_uri,
            intent_digest="intent",
        ),
    )
    consumer.bind_action_result(
        consumer_uri,
        "adopted",
        ActionResultBinding(
            claim_id="claim",
            execution_key="sha256:" + "a" * 64,
            commit=published.commit,
            artifact_facts=published.artifact_facts,
            verification={
                "schema_version": 1,
                "candidate_digest": "sha256:" + "b" * 64,
                "verdict": "verified",
            },
        ),
        expected_revision=consumer.open_run(consumer_uri).revision,
    )
    original_factory = daemon.config.coordinator_authority_factory
    daemon.config.coordinator_authority_factory = lambda u: (
        consumer if u == consumer_uri else original_factory(u)
    )
    request = OutputSelection(run_uris=(consumer_uri,), scope=CollectionScope())
    current = select(daemon, request)
    assert len(current.items) == 2
    assert all(
        r["locator"]["run_uri"] == uri and r["matched_run_uri"] == consumer_uri
        for r in current.items
    )
    assert consumer.list_output_commits(consumer_uri) == ()
    commit(authority, uri, 2)
    assert (
        select(daemon, request).items[0]["locator"]["commit_id"]
        == published.commit.commit_id
    )
    assert len(pages(daemon, replace(request, history="all"))) == 2

    def unavailable(u):
        if u == uri:
            raise OSError("original offline")
        return consumer

    daemon.config.coordinator_authority_factory = unavailable
    missing = select(daemon, request)
    assert not missing.complete
    assert missing.items == (
        {
            "outcome": "producer_unavailable",
            "matched_run_uri": consumer_uri,
            "matched_stage_name": "adopted",
        },
    )
    assert uri not in json.dumps(missing.to_dict())


def test_restricted_original_and_multirun_pages_keep_every_association(
    tmp_path, monkeypatch
):
    from loom.queue import _output_selection
    from loom.pipeline.stores.read_models import ActionResultBinding
    from loom.pipeline.stores.authority import CoordinatorAdmissionRequest

    daemon, authority, uri = fixture(tmp_path)
    published = commit(authority, uri, 1)
    consumer_uri = (daemon.config.run_store_root / "consumer").as_uri()
    consumer = SQLitePerRunAuthorityStore(consumer_uri)
    consumer.create_run(consumer_uri)
    consumer.bind_coordinator_admission(
        consumer_uri,
        CoordinatorAdmissionRequest(
            "consumer-op", "coordinator", consumer_uri, "intent"
        ),
    )
    consumer.bind_action_result(
        consumer_uri,
        "adopted",
        ActionResultBinding(
            "claim",
            "sha256:" + "a" * 64,
            published.commit,
            published.artifact_facts,
            {
                "schema_version": 1,
                "candidate_digest": "sha256:" + "b" * 64,
                "verdict": "verified",
            },
        ),
    )
    daemon.config.coordinator_authority_factory = lambda u: (
        consumer if u == consumer_uri else authority
    )
    request = OutputSelection(
        run_uris=(uri, consumer_uri), scope=CollectionScope(), limit=1
    )
    rows = pages(daemon, request)
    assert len(rows) == 4
    assert len({json.dumps(r["locator"], sort_keys=True) for r in rows}) == 2
    assert {r["matched_run_uri"] for r in rows} == {uri, consumer_uri}
    # The actual managed scope owner only recognizes the adopted run. The same
    # valid binding must not reveal a producer outside that owner's journal.
    from loom.queue import _run_queries

    monkeypatch.setattr(
        _run_queries, "_journal", lambda _: ([], [{"run_uri": consumer_uri}])
    )
    denied = select(daemon, OutputSelection(run_uris=(consumer_uri,)))
    assert not denied.complete and denied.items[0]["outcome"] == "producer_restricted"
    assert uri not in json.dumps(denied.to_dict())
    assert _output_selection.authorized_run(daemon, consumer_uri, {"kind": "managed"})


def test_oversize_metadata_advances_and_retains_explicit_stage_failures(tmp_path):
    daemon, authority, uri = fixture(tmp_path)
    attempt = authority.allocate_stage_attempt(
        uri, "large", owner_id="worker", lease_ttl_seconds=300
    )
    authority.record_output_commit(
        uri,
        "large",
        attempt_id=attempt.attempt.attempt_id,
        fencing_token=attempt.lease.fencing_token,
        outputs={
            "huge": ArtifactRef(
                "huge", "unread://payload", "text", metadata={"value": "x" * 600_000}
            ),
            "small": ArtifactRef("small", "unread://payload", "text"),
        },
    )
    request = OutputSelection(run_uris=(uri,), scope=CollectionScope(), limit=1)
    first = select(daemon, request)
    assert first.items[0]["outcome"] == "metadata_too_large" and not first.complete
    assert len(json.dumps(first.to_dict())) < 8000
    second = select(daemon, replace(request, cursor=first.next_cursor))
    assert (
        second.items[0]["locator"]["output_name"] == "small"
        and second.next_cursor is None
    )

    def unavailable(_):
        raise OSError("disconnected")

    daemon.config.coordinator_authority_factory = unavailable
    failures = select(daemon, replace(request, stage_names=("one", "two"), limit=200))
    assert {r["matched_stage_name"] for r in failures.items} == {"one", "two"}
    assert {r["outcome"] for r in failures.items} == {"authority_unavailable"}


@pytest.mark.parametrize(
    "change",
    [
        {"run_uris": []},
        {"history": "latest"},
        {"locator": {"uri": "/etc/passwd"}},
        {"limit": 201},
        {"metadata": []},
    ],
)
def test_invalid_native_selectors(change):
    with pytest.raises((ValueError, TypeError)):
        OutputSelection.from_dict({"run_uris": ["file:///run"], **change})


def test_locator_rejects_client_artifact_override():
    locator = OutputLocator("file:///run", "stage", "commit", "out")
    with pytest.raises(ValueError):
        OutputLocator.from_dict(
            {**locator.to_dict(), "artifact": {"uri": "/etc/passwd"}}
        )


@pytest.mark.parametrize("value", [None, 17, [1]])
def test_nonobject_output_cursor_is_invalid_cursor(tmp_path, value):
    import base64
    daemon, _, uri = fixture(tmp_path)
    cursor = base64.urlsafe_b64encode(json.dumps(value).encode()).decode()
    with pytest.raises(InvalidCursorError):
        select(daemon, OutputSelection(run_uris=(uri,), scope=CollectionScope(), cursor=cursor))


def test_selection_never_opens_payload_or_changes_authority(tmp_path, monkeypatch):
    from pathlib import Path
    daemon, authority, uri = fixture(tmp_path)
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"opaque")
    attempt = authority.allocate_stage_attempt(uri, "publish", owner_id="worker", lease_ttl_seconds=300)
    authority.record_output_commit(uri, "publish", attempt_id=attempt.attempt.attempt_id,
        fencing_token=attempt.lease.fencing_token,
        outputs={"out": ArtifactRef("opaque", payload.as_uri(), "custom", codec_key="never.execute", metadata={"nested": {"ratio": 0.5}})})
    before = authority.open_run(uri)
    original_open = Path.open
    def guarded_open(self, *args, **kwargs):
        assert self != payload, "metadata selection opened artifact bytes"
        return original_open(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", guarded_open)
    request = OutputSelection(run_uris=(uri,), scope=CollectionScope(), metadata={"nested": {"ratio": 0.5}})
    chosen = select(daemon, request).items[0]
    assert chosen["artifact"]["uri"] == payload.as_uri()
    payload.unlink()
    assert select(daemon, request).items[0]["artifact"] == chosen["artifact"]
    assert authority.open_run(uri) == before

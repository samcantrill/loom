"""Native action ownership survives races, cancellation and coordinator reopen."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from loom.queue._action_results import ActionResults, initialize_action_results
from loom.queue.errors import QueueConflictError


def _store(tmp_path: Path) -> ActionResults:
    path = tmp_path / "actions.sqlite"
    if not path.exists():
        with sqlite3.connect(path) as conn:
            initialize_action_results(conn)

    @contextmanager
    def connection():
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    return ActionResults(connection)


def _select(store, run="run-a", node="generate", *, principal="one", key="a"):
    return store.select(
        run_uri=run,
        node=node,
        scope={"principal": principal},
        identity={"digest": key * 64},
    )


def _publish(store, claim):
    store.attach_fence(
        claim,
        run_uri="run-a",
        node="generate",
        attempt_id="attempt-a",
        assignment_id="assignment-a",
        fencing_token="fence-a",
    )
    result = {"commit": "original-commit", "artifact": "original-artifact"}
    store.publish(
        claim,
        result=result,
        attempt_id="attempt-a",
        assignment_id="assignment-a",
        fencing_token="fence-a",
    )
    return result


def test_racing_demands_have_one_producer_and_reopen_retains_it(tmp_path):
    store = _store(tmp_path)
    barrier = Barrier(2)

    def select(run):
        barrier.wait()
        return _select(store, run)

    with ThreadPoolExecutor(max_workers=2) as pool:
        selections = tuple(pool.map(select, ("run-a", "run-b")))
    assert {selection["decision"] for selection in selections} == {"owner", "wait"}
    assert len({selection["claim"]["claim_id"] for selection in selections}) == 1
    reopened = _store(tmp_path)
    for run, original in zip(("run-a", "run-b"), selections, strict=True):
        assert _select(reopened, run) == original
    assert _select(reopened, "run-c", principal="two")["decision"] == "owner"
    assert _select(reopened, "run-d", key="b")["decision"] == "owner"


def test_cancel_creator_retains_shared_producer_until_final_demand(tmp_path):
    store = _store(tmp_path)
    claim = _select(store)["claim"]["claim_id"]
    assert _select(store, "run-b")["decision"] == "wait"
    assert store.detach_graph("run-a", "cancel-a") == ()
    assert _store(tmp_path).producer_needed("run-a", "generate")
    (settling,) = store.detach_graph("run-b", "cancel-b")
    assert settling["claim_id"] == claim
    assert settling["state"] == "settling"
    assert not store.producer_needed("run-a", "generate")
    assert store.detach_graph("run-b", "cancel-b") == (settling,)
    with pytest.raises(QueueConflictError, match="cancelled graph"):
        _select(store, "run-b")
    assert _select(store, "run-c")["decision"] == "failed"


def test_binding_keeps_original_result_and_rejects_cancel_during_verification(tmp_path):
    store = _store(tmp_path)
    claim = _select(store)["claim"]["claim_id"]
    result = _publish(store, claim)
    candidate = _select(store, "run-b")["claim"]
    binding = store.bind(
        run_uri="run-b",
        node="generate",
        claim_id=claim,
        expected_revision=candidate["revision"],
        result=result,
        verification={"verdict": "verified"},
    )
    assert binding["origin_run_uri"] == "run-a"
    assert binding["result"] == result
    assert _select(_store(tmp_path), "run-b")["binding"] == binding
    _select(store, "run-c")
    store.detach_graph("run-c", "cancel-c")
    with pytest.raises(QueueConflictError, match="no longer live"):
        store.bind(
            run_uri="run-c",
            node="generate",
            claim_id=claim,
            expected_revision=candidate["revision"],
            result=result,
            verification={"verdict": "verified"},
        )
    assert store.claim(claim)["state"] == "succeeded"


def test_stale_fence_cannot_publish_and_failed_producer_is_not_a_miss(tmp_path):
    store = _store(tmp_path)
    claim = _select(store)["claim"]["claim_id"]
    _publish(store, claim)
    with pytest.raises(QueueConflictError, match="fence conflicts"):
        store.publish(
            claim,
            result={"commit": "stale"},
            attempt_id="attempt-a",
            assignment_id="assignment-a",
            fencing_token="stale",
        )
    other = _select(store, "run-failed", key="b")["claim"]["claim_id"]
    store.fail(other, {"code": "producer_failed"})
    selected = _select(_store(tmp_path), "run-waiter", key="b")
    assert selected["decision"] == "failed"
    assert selected["claim"]["owner_run_uri"] == "run-failed"


def test_only_authorized_owner_retry_reopens_failure_and_stale_observer_cannot_fail_it(
    tmp_path,
):
    store = _store(tmp_path)
    selected = store.select(
        run_uri="owner",
        node="fit",
        scope={},
        identity={"digest": "same"},
        attempt_id="fit-1",
    )
    claim = selected["claim"]
    store.fail(
        claim["claim_id"],
        {"code": "producer_failed"},
        expected_revision=claim["revision"],
    )
    assert (
        store.select(
            run_uri="owner",
            node="fit",
            scope={},
            identity={"digest": "same"},
            attempt_id="fit-2",
        )["decision"]
        == "failed"
    )
    retry = store.select(
        run_uri="owner",
        node="fit",
        scope={},
        identity={"digest": "same"},
        attempt_id="fit-2",
        retry_authorized=True,
    )
    assert retry["decision"] == "owner"
    assert retry["claim"]["claim_id"] == claim["claim_id"]
    store.fail(
        claim["claim_id"],
        {"code": "old_attempt_failure"},
        expected_revision=claim["revision"],
    )
    assert store.claim(claim["claim_id"])["state"] == "owned"
    store.attach_fence(
        claim["claim_id"],
        run_uri="owner",
        node="fit",
        attempt_id="fit-2",
        assignment_id="assignment-2",
        fencing_token="fence-2",
    )
    with pytest.raises(QueueConflictError, match="fence conflicts"):
        store.publish(
            claim["claim_id"],
            result={"commit": "old"},
            attempt_id="fit-1",
            assignment_id="assignment-1",
            fencing_token="fence-1",
        )

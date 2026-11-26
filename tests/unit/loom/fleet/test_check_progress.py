"""Check wait reasons use existing native facts, not admission state guesses."""

from dataclasses import replace
from types import SimpleNamespace

from typing import Any

import pytest

from loom.coordinator import CoordinatorConnectionDescription, RunObservation
from loom.diagnostics.run_inspection import RunInspectionAxis, RunInspectionAxisName as Axis, RunInspectionResult, RunInspectionTruncation
from loom.fleet import self_tests
from loom.queue.local_daemon import LocalDaemonOperation, LocalDaemonAdmission, LocalDaemonAdmissionState
from tests.contracts.test_run_inspection_contract import _all_axes


def observation(fact=None, *, preparing=False):
    admission = LocalDaemonAdmission(
        "admission", "queue", "coordinator", "file:///runs/check", "digest", "managed-stage",
        LocalDaemonAdmissionState.ACTIVE, "2026-10-19T00:00:00Z", "binding",
    )
    inspection = None if fact is None else RunInspectionResult(
        admission.run_uri, "2026-10-19T00:00:01Z", "RUNNING", _all_axes(fact), (), (),
        (RunInspectionTruncation("stages", 0, 0), RunInspectionTruncation("locations", 0, 0)),
    )
    return RunObservation(
        "check-id", LocalDaemonOperation("check-id", "run", "applying" if preparing else "applied", None, {}),
        None if preparing else admission, inspection,
        CoordinatorConnectionDescription("13", "unix", "owner", "epoch", (), (), (), ()),
    )


@pytest.mark.parametrize(("axis", "state", "freshness", "availability", "expected"), [
    (Axis.SCHEDULING, "ready", "current", "available", "waiting_for_capacity"),
    (Axis.ASSIGNMENT, "running", "current", "available", "check_running"),
    (Axis.TRANSFER_RESULT, "result_durable", "current", "available", "publication_pending"),
    (Axis.ASSIGNMENT, "terminal", "current", "available", "settlement_pending"),
    (Axis.SCHEDULING, "ready", "stale", "available", "check_pending_unknown"),
    (Axis.ASSIGNMENT, "running", "unavailable", "unavailable", "check_pending_unknown"),
    (Axis.LIFECYCLE, "RUNNING", "current", "available", "check_pending_unknown"),
])
def test_pending_reason_preserves_owner_evidence(axis, state, freshness, availability, expected):
    fact = RunInspectionAxis(axis, "native-owner", availability, state, 7, "2026-10-19T00:00:00Z", freshness, None)
    code, explanation = self_tests._pending_observation(observation(fact))
    assert code == expected
    assert fact.to_dict() in explanation["facts"]


def test_pending_preparation_and_absent_execution_are_distinct():
    assert self_tests._pending_observation(observation(preparing=True))[0] == "preparation_pending"
    assert self_tests._pending_observation(observation())[0] == "check_pending_unknown"


def test_blocked_native_admission_is_not_reported_as_capacity_wait(tmp_path, monkeypatch):
    observed = observation()
    assert observed.admission is not None
    observed = replace(observed, admission=replace(observed.admission, state=LocalDaemonAdmissionState.BLOCKED, blocked_reason="stage_failed"))
    monkeypatch.setattr(self_tests.RunRequest, "from_dict", lambda _: SimpleNamespace(preparation=SimpleNamespace(operation_id="check-id")))
    operator: Any = None  # These observation-only cases cannot call an operator.
    client: Any = SimpleNamespace(observe_run=lambda *a, **k: observed)
    result = self_tests._observe_check(client, operator, tmp_path, {"requests": {"cpu": {}}}, "cpu", self_tests.time.monotonic() + 10)
    assert result["outcome"] == "failed" and result["code"] == "native_check_failed"
    assert result["native"]["admission"]["blocked_reason"] == "stage_failed"


@pytest.mark.parametrize("wait", [False, True])
def test_upgrade_observation_is_bounded_while_standalone_waits(tmp_path, monkeypatch, wait):
    monkeypatch.setattr(self_tests.RunRequest, "from_dict", lambda _: SimpleNamespace(
        preparation=SimpleNamespace(operation_id="check-id")))
    calls = []
    def observe(identity, **kwargs):
        calls.append((identity, kwargs))
        return observation(preparing=True)
    operator: Any = None  # These observation-only cases cannot call an operator.
    client: Any = SimpleNamespace(observe_run=observe)
    for _ in range(2):
        result = self_tests._observe_check(
            client, operator, tmp_path, {"requests": {"cpu": {}}}, "cpu",
            self_tests.time.monotonic() + 120, wait=wait,
        )
        assert result["outcome"] == "waiting"
    assert [identity for identity, _ in calls] == ["check-id", "check-id"]
    assert all(options["wait"] is wait for _, options in calls)
    assert all(100 < options["timeout_seconds"] <= 120 if wait
               else 0 < options["timeout_seconds"] <= 10 for _, options in calls)


@pytest.mark.parametrize(("operation", "ids", "replay"), [
    ("operation", {"operation_id": "check-id"}, True),
    ("admission", {"admission_id": "admission"}, False),
    ("operation", {"operation_id": "other-check"}, False),
])
def test_check_replays_only_its_missing_start_operation(tmp_path, monkeypatch, operation, ids, replay):
    request = SimpleNamespace(preparation=SimpleNamespace(operation_id="check-id"))
    monkeypatch.setattr(self_tests.RunRequest, "from_dict", lambda _: request)
    missing = self_tests.CoordinatorClientError("not_found", boundary="coordinator",
                                                operation=operation, ids=ids)
    sent = []

    def observe(*args, **kwargs):
        raise missing

    client: Any = SimpleNamespace(observe_run=observe, start_run=lambda request, **options: sent.append(request))
    operator: Any = None
    intent = {"requests": {"cpu": {}}}
    if replay:
        result = self_tests._observe_check(client, operator, tmp_path, intent, "cpu",
                                           self_tests.time.monotonic() + 10)
        assert result["code"] == "exact_request_replayed"
        assert sent == [request]
    else:
        with pytest.raises(self_tests.CoordinatorClientError) as caught:
            self_tests._observe_check(client, operator, tmp_path, intent, "cpu",
                                      self_tests.time.monotonic() + 10)
        assert caught.value is missing
        assert sent == []


@pytest.mark.parametrize("changed", ["credential", "locator"])
def test_changed_binding_discards_partial_ranges_and_old_verification(tmp_path, monkeypatch, changed):
    from hashlib import sha256
    import base64
    from loom import _artifact_ranges
    from loom.fleet import _check_artifacts

    directory = tmp_path / "receipts"
    directory.mkdir()
    credential = tmp_path / "client.crt"
    credential.write_bytes(b"first certificate")
    monkeypatch.setattr(_check_artifacts, "load_coordinator_connection_file",
                        lambda path: SimpleNamespace(certificate_path=credential))
    monkeypatch.setattr(_check_artifacts, "gettempdir", lambda: str(tmp_path))
    intent = {"requests": {"cpu": {"preparation": {"operation_id": "exact-check"}}},
              "coordinator_id": "owner", "connection": "selected-client"}
    selected = {"locator": {"run_uri": "test:run", "stage_name": "probe", "output_name": "report",
                            "commit_id": "old"}, "artifact": {"metadata": {"loom.shared_publication": {}}}}
    payload = b'{"test":true}' + b" " * _artifact_ranges.CHUNK_BYTES
    declaration = "f" * 64
    offsets = []
    corrupt = False
    def describe(*args, **kwargs):
        return {"outcome": "available", "primary": "report.json", "verification": "verified_at_read",
                "declaration": declaration, "next_cursor": None, "members": [{
                    "path": "report.json", "size_bytes": len(payload), "digest": sha256(payload).hexdigest(),
                }]}
    def read(locator, *, offset, length, member, **kwargs):
        data = payload[offset:offset + length]
        if corrupt and offset + length == len(payload):
            data = data[:-1] + b"!"
        offsets.append(offset)
        return {"outcome": "available", "data": base64.b64encode(data).decode(), "member": member,
                "offset": offset, "declaration": declaration, "locator": locator.to_dict()}
    client = SimpleNamespace(describe_artifact=describe, read_artifact_chunk=read)
    def fetch(*, collect=True):
        return _check_artifacts.verify_publication(client, directory, "cpu", intent, selected, None, collect=collect)

    assert fetch(collect=False)["code"] == "publication_available"
    assert not offsets
    save = _artifact_ranges._save
    def detach(path, data):
        save(path, data)
        raise TimeoutError("detach after a durable range")
    with monkeypatch.context() as patch:
        patch.setattr(_artifact_ranges, "_save", detach)
        assert fetch()["outcome"] == "waiting"
    def change(generation):
        if changed == "credential":
            credential.write_bytes(generation.encode())
        else:
            selected["locator"]["commit_id"] = generation
    change("second")
    offsets.clear()
    assert fetch()["report"] == {"test": True}
    assert sorted(offsets) == [0, _artifact_ranges.CHUNK_BYTES]
    assert fetch(collect=False)["report"] == {"test": True}
    change("third")
    assert fetch(collect=False)["code"] == "publication_available"
    offsets.clear()
    corrupt = True
    result = fetch()
    assert sorted(offsets) == [0, _artifact_ranges.CHUNK_BYTES]
    assert result["outcome"] == "failed" and result["code"] == "publication_integrity_failed"
    assert fetch(collect=False)["code"] == "publication_available"

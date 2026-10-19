"""Check wait reasons use existing native facts, not admission state guesses."""

from dataclasses import replace
from types import SimpleNamespace

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
    observed = replace(observed, admission=replace(observed.admission, state=LocalDaemonAdmissionState.BLOCKED, blocked_reason="stage_failed"))
    monkeypatch.setattr(self_tests.RunRequest, "from_dict", lambda _: SimpleNamespace(preparation=SimpleNamespace(operation_id="check-id")))
    client = SimpleNamespace(observe_run=lambda *a, **k: observed)
    result = self_tests._observe_check(client, None, tmp_path, {"requests": {"cpu": {}}}, "cpu", self_tests.time.monotonic() + 10)
    assert result["outcome"] == "failed" and result["code"] == "native_check_failed"
    assert result["native"]["admission"]["blocked_reason"] == "stage_failed"

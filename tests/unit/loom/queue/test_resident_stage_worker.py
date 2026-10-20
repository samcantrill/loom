"""Unit tests for the resident stage-worker process entry point."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import loom.queue._resident_stage_worker as resident_stage_worker
import loom.queue._phase_timing as phase_timing
from loom.pipeline import ProcessContainmentOwner
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.status import StageStatus
import pytest


def test_resident_main_passes_outer_boundary_containment_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "agent" / "assignments" / "assignment-1"
    workspace_root.mkdir(parents=True)
    (workspace_root / "run.grant").write_text("granted", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeWorkspace:
        def request(self):
            return SimpleNamespace(fingerprint={"payload": {"factory_target": "pkg.Stage", "fingerprint_fields": {}}}, preparation_input=None)

        def worker_request(self, *, resolve_shared: bool = False) -> object:
            assert resolve_shared
            return object()

        def preparation_context(self) -> None:
            return None

    result = StageWorkerResult(
        schema_version=1, run_uri="file:///runs/example", stage_name="probe", attempt=1,
        status=StageStatus.SUCCEEDED, started_at="2026-10-19T00:00:00Z",
        finished_at="2026-10-19T00:00:01Z", executor_name="local",
        executor_metadata={"existing": "kept"},
    )
    ticks = iter((1, 3, 5, 8, 10, 17))
    monkeypatch.setattr(phase_timing, "monotonic", lambda: next(ticks))

    monkeypatch.setattr(
        resident_stage_worker,
        "_ResidentAssignmentWorkspace",
        lambda _agent_root, _assignment_id: FakeWorkspace(),
    )
    monkeypatch.setattr(
        resident_stage_worker,
        "execute_resident_stage_worker_request",
        lambda **kwargs: captured.update(kwargs) or result,
    )
    saved = []
    monkeypatch.setattr(resident_stage_worker, "atomic_write_json", lambda path, value: saved.append(value))

    assert resident_stage_worker.main(["--workspace", str(workspace_root)]) == 0
    assert (
        captured["process_containment_owner"] is ProcessContainmentOwner.OUTER_BOUNDARY
    )
    decoded = StageWorkerResult.from_dict(saved[0])
    assert decoded.executor_metadata["existing"] == "kept"
    spans = decoded.executor_metadata["native_timings"]["spans"]
    assert [(span["action"], span["elapsed_nanoseconds"]) for span in spans] == [
        ("input_materialization", 2_000_000_000), ("preparation_materialization", 3_000_000_000), ("worker_execution", 7_000_000_000),
    ]
    assert all(span["outcome"] == "complete" for span in spans)
    assert "native_timings" not in result.executor_metadata


def test_timing_preserves_failure_and_bounds_repeated_materialization():
    timings = phase_timing.PhaseTimings()
    failure = RuntimeError("materialization failed")
    with pytest.raises(RuntimeError) as observed, timings.measure("materialization"):
        raise failure
    assert observed.value is failure
    assert timings.spans[0]["outcome"] == "error"
    for _ in range(70):
        with timings.measure("materialization"):
            pass
    assert len(timings.spans) == 64 and timings.dropped == 7


def test_native_timing_crosses_actual_event_codec():
    import json
    from loom.queue._agent_session_codec import _decode
    from loom.queue._remote_stage_execution import _reject_path_bearing_data

    timings = phase_timing.PhaseTimings()
    with timings.measure("output_retention"):
        pass
    payload = {"kind": "native_timing", **timings.payload()}
    _reject_path_bearing_data(payload, "remote event")
    assert _decode(json.dumps({"payload": payload}).encode())["payload"] == payload

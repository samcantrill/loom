"""Unit tests for the resident stage-worker process entry point."""

from __future__ import annotations

from pathlib import Path

import loom.queue._resident_stage_worker as resident_stage_worker
from loom.pipeline import ProcessContainmentOwner
import pytest


def test_resident_main_passes_outer_boundary_containment_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_root = tmp_path / "agent" / "assignments" / "assignment-1"
    workspace_root.mkdir(parents=True)
    (workspace_root / "run.grant").write_text("granted", encoding="utf-8")
    captured: dict[str, object] = {}

    class FakeWorkspace:
        def worker_request(self) -> object:
            return object()

    class FakeResult:
        def to_dict(self) -> dict[str, str]:
            return {"status": "succeeded"}

    monkeypatch.setattr(
        resident_stage_worker,
        "_ResidentAssignmentWorkspace",
        lambda _agent_root, _assignment_id: FakeWorkspace(),
    )
    monkeypatch.setattr(
        resident_stage_worker,
        "execute_resident_stage_worker_request",
        lambda **kwargs: captured.update(kwargs) or FakeResult(),
    )
    monkeypatch.setattr(resident_stage_worker, "atomic_write_json", lambda *_args: None)

    assert resident_stage_worker.main(["--workspace", str(workspace_root)]) == 0
    assert (
        captured["process_containment_owner"] is ProcessContainmentOwner.OUTER_BOUNDARY
    )

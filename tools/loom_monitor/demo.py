"""In-memory native admission observations for the monitor's visual playground.

This generates presentation fixtures only. It starts no service, schedules no
stage, writes no queue database and sends no network request.
"""

from dataclasses import dataclass, replace
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from loom.serialization import PlainData
from typing import cast

from loom.queue import (
    AdmissionPage,
    LocalDaemonAdmission,
    LocalDaemonAdmissionDetail,
    LocalDaemonAdmissionState,
)
from .collector import MonitorCollector
from .models import MonitorView

DEMO_SCENARIOS = ("mixed", "failures", "scheduler")


class DemoCoordinator:
    """Synthetic read-only native client responses for isolated presentation."""

    def __init__(self, *, monotonic=time.monotonic, speed=1.0, items=None):
        self._clock, self._speed, self._started = monotonic, speed, monotonic()
        self._items = items or tuple(
            self.item(name, state)
            for name, state in (
                ("demo-live-analysis", "ACTIVE"),
                ("demo-waiting-large", "WAITING"),
                ("demo-feature-failed", "FAILED"),
                ("demo-cancelled", "CANCELLED"),
                ("demo-recovery-unknown", "BLOCKED"),
                ("demo-slurm-train", "ACTIVE"),
            )
        )

    @staticmethod
    def item(name, state):
        return LocalDaemonAdmission(
            admission_id=name,
            queue_item_id=name,
            coordinator_id="demo-coordinator",
            run_uri=f"file:///demo/{name}",
            intent_digest=f"intent-{name}",
            execution_owner="managed-stage",
            state=LocalDaemonAdmissionState(state),
            accepted_at="2026-08-19T00:00:00Z",
            authority_operation_id=f"admit-{name}",
        )

    def status(self):
        return SimpleNamespace(
            coordinator_id="demo-coordinator",
            service_health="healthy",
            service_diagnostic=None,
        )

    def admissions(self, limit=100, cursor=None):
        start = int(cursor or 0)
        elapsed = (self._clock() - self._started) * self._speed
        items = tuple(
            replace(item, state=LocalDaemonAdmissionState.SUCCEEDED)
            if elapsed >= 20 and item.state is LocalDaemonAdmissionState.ACTIVE
            else item
            for item in self._items
        )
        return AdmissionPage(
            items[start : start + limit],
            str(start + limit) if start + limit < len(items) else None,
        )

    def admission_for_queue_item(self, queue_item_id):
        return next(
            item
            for item in self.admissions().admissions
            if item.queue_item_id == queue_item_id
        )

    def admission(self, admission_id):
        item = self.admission_for_queue_item(admission_id)
        state = (
            "RUNNING"
            if item.state is LocalDaemonAdmissionState.ACTIVE
            else item.state.value
        )
        authority = {
            "availability": "available",
            "state": state,
            "artifacts": {},
            "stages": {"build": state},
            "attempts": [{"stage_name": "build", "attempt": 1}],
        }
        assignments = []
        if "slurm" in item.queue_item_id:
            assignments = [
                {
                    "assignment_id": "demo-assignment",
                    "stage_name": "build",
                    "job_id": "1234",
                    "state": "running",
                    "submission": {"scheduler_state": "RUNNING"},
                }
            ]
        owners: dict[str, PlainData] = {
            "slurm": {
                "availability": "available",
                "assignments": cast(list[PlainData], assignments),
            }
        }
        return LocalDaemonAdmissionDetail(
            item,
            authority,
            owners,
        )

    def close(self):
        pass


@dataclass
class DemoSession:
    collector: MonitorCollector
    workspace_path: Path
    config_path: Path
    preserved: bool
    _temporary: tempfile.TemporaryDirectory[str] | None
    initial_view: MonitorView = MonitorView.ALL
    initial_pool_filter: str | None = None

    def close(self):
        self.collector.service.close()
        if self._temporary is not None:
            self._temporary.cleanup()


def create_demo_session(
    *, scenario="mixed", speed=1.0, seed=42, output_root=None, monotonic=time.monotonic
):
    """Build synthetic observations without an execution engine or credentials."""
    del seed
    if scenario not in DEMO_SCENARIOS or speed <= 0:
        raise ValueError("invalid demo scenario or speed")
    temporary = (
        tempfile.TemporaryDirectory(prefix="loom-monitor-demo-")
        if output_root is None
        else None
    )
    root = Path(temporary.name) if temporary is not None else Path(output_root or ".")
    root.mkdir(parents=True, exist_ok=True)
    client = DemoCoordinator(monotonic=monotonic, speed=speed)
    collector = MonitorCollector(
        config_path=root / "synthetic-observations",
        service=client,
        workspace_name=f"Native demo ({scenario})",
    )
    return DemoSession(
        collector, root, collector.config_path, temporary is None, temporary
    )


__all__ = ["DEMO_SCENARIOS", "DemoSession", "create_demo_session"]

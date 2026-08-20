"""Unit coverage for the repository-local Loom monitor."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from textual.containers import Horizontal
from textual.widgets import DataTable, Static, TabbedContent

from loom.diagnostics.inspection import (
    LogStreamSummary,
    RunStatusSummary,
    StageLogsSummary,
    StageStatusSummary,
)
from loom.pipeline.executors.slurm.status import (
    SlurmJobStatusSummary,
    SlurmJobsStatusReport,
)
from loom.queue import QueueEnqueueRequest, QueueService, normalize_queue_spec
from loom.state_sources import (
    authoritative_service_source,
    local_materialization_source,
)
from tools.loom_monitor.app import HelpScreen, LoomMonitorApp
from tools.loom_monitor.collector import MonitorCollector
from tools.loom_monitor.demo import create_demo_session
from tools.loom_monitor.__main__ import main as monitor_main
from tools.loom_monitor.models import (
    ActiveAttempt,
    AuthorityData,
    MonitorSnapshot,
    MonitorView,
    Observation,
    QueueData,
    QueueRecord,
    RunRecord,
)
from tools.loom_monitor.presenter import (
    all_attention,
    build_work_records,
    fifo_positions,
    filter_work,
    sanitize_terminal_text,
    states_divergent,
)


pytestmark = pytest.mark.unit
NOW = datetime(2026, 8, 19, 1, 2, 3, tzinfo=timezone.utc)


def test_observation_failure_retains_last_successful_value() -> None:
    observation = Observation[int](source="queue").succeeded(7, at=NOW)

    stale = observation.failed(ConnectionError("connection refused"), at=NOW)

    assert stale.value == 7
    assert stale.last_success_at == NOW
    assert stale.error == "connection refused"
    assert stale.stale is True


def test_presenter_keeps_identity_fifo_and_lifecycle_owners_stable() -> None:
    first = _queue_record("item-b", enqueued_at="2026-08-19T00:00:00Z")
    second = _queue_record("item-a", enqueued_at="2026-08-19T00:00:00Z")
    second = replace(second, tags={"team": "alpha"})
    dispatched = _queue_record(
        "item-active",
        status="DISPATCHED",
        pool_mode="managed",
        active_attempt=ActiveAttempt(
            queue_item_id="item-active",
            owner_id="controller",
            session_id="session",
            evidence_source="persisted",
            live_observation="unavailable",
        ),
    )
    queue = QueueData(
        workspace_name="workspace", pools=(), items=(first, second, dispatched)
    )
    run = RunRecord(
        run_uri=dispatched.run_uri,
        status="SUCCEEDED",
        message=None,
        artifact_count=0,
        state_source=authoritative_service_source(),
        stages=(),
        submitted_operations=(),
    )
    snapshot = MonitorSnapshot(
        queue=Observation(source="queue").succeeded(queue, at=NOW),
        authority=Observation(source="authority"),
        runs={
            dispatched.run_uri: Observation(source="authority/run").succeeded(
                run, at=NOW
            )
        },
    )

    positions = fifo_positions(queue.items)
    work = build_work_records(snapshot)

    assert positions == {"item-a": (1, 2), "item-b": (2, 2)}
    assert states_divergent("DISPATCHED", "SUCCEEDED") is True
    active = filter_work(work, view=MonitorView.ACTIVE, pool_name=None, query="")
    assert [record.item.queue_item_id for record in active] == ["item-active"]
    tagged = filter_work(work, view=MonitorView.ALL, pool_name=None, query="alpha")
    assert [record.item.queue_item_id for record in tagged] == ["item-a"]
    assert active[0].divergent is True
    assert {record.kind.value for record in active[0].attention} == {"UNCERTAIN"}
    attention = all_attention(work)
    assert attention[-1].kind.value == "WAITING"
    assert "not a stuck alert" in attention[-1].message


def test_log_sanitizer_removes_terminal_controls_but_preserves_text_layout() -> None:
    unsafe = "plain\x1b[31m red\x1b[0m\nnext\x07\tcolumn\x1b]0;title\x07"

    assert sanitize_terminal_text(unsafe) == "plain red\nnext\tcolumn"


def test_blue_is_the_monitor_accent_with_a_subdued_footer() -> None:
    css = LoomMonitorApp.CSS + HelpScreen.CSS

    assert "#008080" not in css
    assert "#3BB9FF" in css
    assert "background: #3A3A3A" in LoomMonitorApp.CSS


def test_collectors_fail_independently_and_keep_stale_queue_data(
    tmp_path: Path,
) -> None:
    service = _queue_service(tmp_path)
    probes: list[object] = [AuthorityData(state="READY"), OSError("offline")]

    def probe() -> AuthorityData:
        value = probes.pop(0)
        if isinstance(value, BaseException):
            raise value
        assert isinstance(value, AuthorityData)
        return value

    collector = MonitorCollector(
        config_path=tmp_path / "queue.yaml",
        service=service,
        workspace_name="workspace",
        clock=lambda: NOW,
        authority_probe=probe,
        run_store=_RunStore(),
    )

    first = collector.refresh_queue()
    collector.refresh_authority()
    second_authority = collector.refresh_authority()
    original_status = service.status

    def failed_status() -> Any:
        raise OSError("database busy")

    service.status = failed_status  # type: ignore[method-assign]
    stale = collector.refresh_queue()
    service.status = original_status  # type: ignore[method-assign]

    assert first.queue.value is not None
    assert stale.queue.value == first.queue.value
    assert stale.queue.error == "database busy"
    assert second_authority.authority.value == AuthorityData(state="READY")
    assert second_authority.authority.error == "offline"


def test_logs_use_paths_only_fallback_when_no_content_is_materialized(
    tmp_path: Path,
) -> None:
    service = _queue_service(tmp_path)

    def inspect_logs(
        run_uri: str,
        stage_name: str,
        *,
        paths_only: bool = False,
        **_: Any,
    ) -> StageLogsSummary:
        if not paths_only:
            raise ValueError("no log content found")
        return StageLogsSummary(
            run_uri=run_uri,
            stage_name=stage_name,
            paths_only=True,
            streams=(
                LogStreamSummary(
                    stream="stdout",
                    path="/runs/build/stdout.log",
                    available=False,
                    state_source=local_materialization_source(),
                ),
            ),
        )

    collector = MonitorCollector(
        config_path=tmp_path / "queue.yaml",
        service=service,
        workspace_name="workspace",
        clock=lambda: NOW,
        logs_inspector=inspect_logs,
        run_store=_RunStore(),
    )

    snapshot = collector.refresh_logs("file:///runs/run-1", "build")

    assert snapshot.logs.error is None
    assert snapshot.logs.value is not None
    assert snapshot.logs.value.unavailable_reason == "no log content found"
    assert snapshot.logs.value.streams[0].available is False


def test_app_uses_full_width_detail_below_narrow_breakpoint(
    tmp_path: Path,
) -> None:
    service = _queue_service(tmp_path, claimed=True)
    collector = MonitorCollector(
        config_path=tmp_path / "queue.yaml",
        service=service,
        workspace_name="workspace",
        clock=lambda: NOW,
        authority_probe=lambda: AuthorityData(state="READY", workspace_id="workspace"),
        run_inspector=_inspect_run,
        run_store=_RunStore(),
    )
    app = LoomMonitorApp(
        collector,
        queue_interval=60,
        run_interval=60,
        authority_interval=60,
        scheduler_interval=60,
        log_interval=60,
    )
    assert app.current_view is MonitorView.ALL

    async def exercise() -> None:
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause(0.5)
            work_table = app.query_one("#work-table", DataTable)
            workspace = app.query_one("#workspace", Horizontal)

            assert len(app.query("#attention")) == 0
            assert work_table.row_count == 1
            assert work_table.get_cell("item-1", "queue") == "CLAIMED"
            assert work_table.get_cell("item-1", "run_state") == "RUNNING"
            assert workspace.has_class("narrow")
            assert app.selected_item_id == "item-1"
            await pilot.press("enter")
            await pilot.pause()
            assert workspace.has_class("detail-open")
            assert "item-1" in str(app.query_one("#detail-title", Static).render())
            await pilot.press("escape")
            assert not workspace.has_class("detail-open")
            await pilot.press("?")
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            assert not isinstance(app.screen, HelpScreen)

    asyncio.run(exercise())


def test_app_polls_selected_evidence_jobs_and_logs_without_opening_tabs(
    tmp_path: Path,
) -> None:
    service = QueueService.from_spec(
        normalize_queue_spec(
            {
                "db_path": str(tmp_path / "queue.sqlite"),
                "pools": [{"pool_name": "batch", "mode": "delegated"}],
                "queues": [{"queue_name": "jobs", "pool_name": "batch"}],
            }
        ),
        clock=lambda: "2026-08-19T00:00:00Z",
    )
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="scheduled-item",
            queue_name="jobs",
            run_uri="file:///runs/scheduled-item",
            adapter="slurm",
        )
    )
    service.claim_next("batch", owner_id="controller", claim_id="claim-1")
    calls = {
        "authority": 0,
        "run": 0,
        "selected": 0,
        "jobs": 0,
        "logs": 0,
    }
    original_inspect_item = service.inspect_item

    def inspect_item(queue_item_id: str):  # noqa: ANN202
        calls["selected"] += 1
        return original_inspect_item(queue_item_id)

    def inspect_run(run_uri: str, **_: Any) -> RunStatusSummary:
        calls["run"] += 1
        return _inspect_run(run_uri)

    def inspect_jobs(run_uri: str, **_: Any) -> SlurmJobsStatusReport:
        calls["jobs"] += 1
        return SlurmJobsStatusReport(
            run_uri=run_uri,
            run_status="RUNNING",
            submission={"submission_id": "submission-1", "state": "SUBMITTED"},
            manifest_path="/runs/scheduled-item/slurm/manifest.json",
            manifest_relative_path="slurm/manifest.json",
            jobs=(
                SlurmJobStatusSummary(
                    logical_key="stage:build",
                    scheduler_job_id="12345",
                    status="RUNNING",
                    source="squeue",
                    scheduler_state="RUNNING",
                    loom_run_status="RUNNING",
                    loom_stage_status="RUNNING",
                    stage_name="build",
                ),
            ),
        )

    def inspect_logs(
        run_uri: str,
        stage_name: str,
        *,
        paths_only: bool = False,
        **_: Any,
    ) -> StageLogsSummary:
        calls["logs"] += 1
        return StageLogsSummary(
            run_uri=run_uri,
            stage_name=stage_name,
            paths_only=paths_only,
            streams=(
                LogStreamSummary(
                    stream="stdout",
                    path="/runs/scheduled-item/build.stdout.log",
                    available=True,
                    content=None if paths_only else "progress\n",
                    line_count=1,
                    displayed_line_count=1,
                    state_source=local_materialization_source(),
                ),
            ),
        )

    def probe_authority() -> AuthorityData:
        calls["authority"] += 1
        return AuthorityData(state="READY", workspace_id="workspace")

    service.inspect_item = inspect_item  # type: ignore[method-assign]
    collector = MonitorCollector(
        config_path=tmp_path / "queue.yaml",
        service=service,
        workspace_name="workspace",
        authority_probe=probe_authority,
        run_inspector=inspect_run,
        jobs_inspector=inspect_jobs,
        logs_inspector=inspect_logs,
        run_store=_RunStore(),
    )
    app = LoomMonitorApp(
        collector,
        queue_interval=0.05,
        run_interval=0.05,
        authority_interval=0.05,
        scheduler_interval=0.05,
        log_interval=0.05,
    )

    async def exercise() -> None:
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause(0.65)
            assert (
                app.query_one("#detail-tabs", TabbedContent).active == "overview-pane"
            )
            assert app.selected_item_id == "scheduled-item"
            assert all(count >= 2 for count in calls.values())
            await pilot.press("space")
            await pilot.pause(0.1)
            paused_counts = dict(calls)
            await pilot.pause(0.2)
            assert calls == paused_counts
            await app.workers.wait_for_complete()

    asyncio.run(exercise())


def test_demo_uses_real_queue_state_and_advances_mock_work(tmp_path: Path) -> None:
    clock = _ManualMonotonic()
    session = create_demo_session(
        output_root=tmp_path,
        monotonic=clock,
        seed=7,
    )
    try:
        snapshot = session.collector.refresh_queue()

        assert session.preserved is True
        assert session.config_path.is_file()
        assert (session.workspace_path / "queue.sqlite").is_file()
        assert snapshot.queue.value is not None
        initial = {
            item.queue_item_id: item.status for item in snapshot.queue.value.items
        }
        assert initial["demo-live-analysis"] == "DISPATCHED"
        assert initial["demo-waiting-large"] == "QUEUED"
        assert initial["demo-feature-failed"] == "FAILED"
        assert initial["demo-cancelled"] == "CANCELLED"
        assert initial["demo-recovery-unknown"] == "UNKNOWN"

        clock.value = 20
        advanced = session.collector.refresh_queue()

        assert advanced.queue.value is not None
        current = {
            item.queue_item_id: item.status for item in advanced.queue.value.items
        }
        assert current["demo-live-analysis"] == "SUCCEEDED"
        assert current["demo-slurm-train"] == "SUCCEEDED"
        assert current["demo-waiting-large"] == "DISPATCHED"
        assert current["demo-slurm-dependent"] == "DISPATCHED"
    finally:
        session.close()

    reopened = MonitorCollector.from_config(session.config_path).refresh_queue()
    assert reopened.queue.value is not None
    assert len(reopened.queue.value.items) == 10


def test_demo_projects_scheduler_logs_and_retained_authority_failure() -> None:
    clock = _ManualMonotonic()
    session = create_demo_session(
        scenario="failures",
        monotonic=clock,
        seed=11,
    )
    workspace_path = session.workspace_path
    try:
        snapshot = session.collector.refresh_queue()
        assert snapshot.queue.value is not None
        slurm = next(
            item
            for item in snapshot.queue.value.items
            if item.queue_item_id == "demo-slurm-train"
        )

        jobs_snapshot = session.collector.refresh_jobs(slurm.run_uri)
        assert jobs_snapshot.jobs.value is not None
        assert [job.scheduler_state for job in jobs_snapshot.jobs.value.jobs] == [
            "RUNNING",
            "PENDING",
            "PENDING",
        ]

        run_snapshot = session.collector.refresh_runs((slurm.run_uri,))
        run = run_snapshot.runs[slurm.run_uri].value
        assert run is not None
        logs_snapshot = session.collector.refresh_logs(
            slurm.run_uri,
            run.stages[0].stage_name,
            tail=2,
        )
        assert logs_snapshot.logs.value is not None
        stdout = logs_snapshot.logs.value.streams[0]
        assert stdout.available is True
        assert stdout.displayed_line_count == 2
        assert stdout.truncated is True
        assert Path(stdout.path).is_file()

        ready = session.collector.refresh_authority()
        assert ready.authority.value is not None
        clock.value = 10
        session.collector.refresh_queue()
        stale = session.collector.refresh_authority()
        assert stale.authority.value == ready.authority.value
        assert stale.authority.stale is True
        assert "temporarily offline" in (stale.authority.error or "")
    finally:
        session.close()

    assert not workspace_path.exists()


def test_demo_cli_launches_without_queue_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched: list[LoomMonitorApp] = []

    def run_without_terminal(app: LoomMonitorApp) -> None:
        launched.append(app)

    monkeypatch.setattr(LoomMonitorApp, "run", run_without_terminal)

    assert (
        monitor_main(
            [
                "--demo",
                "--demo-scenario",
                "scheduler",
                "--demo-speed",
                "2",
            ]
        )
        == 0
    )
    assert len(launched) == 1
    assert launched[0].collector.workspace_name == "DEMO · scheduler"
    assert launched[0].current_view is MonitorView.ALL
    assert launched[0].pool_filter == "slurm-pool"
    assert launched[0].queue_interval == 1.0
    assert launched[0].run_interval == 1.0
    assert launched[0].authority_interval == 1.0
    assert launched[0].scheduler_interval == 1.0
    assert launched[0].log_interval == 1.0


def _queue_record(
    queue_item_id: str,
    *,
    status: str = "QUEUED",
    enqueued_at: str = "2026-08-19T00:00:00Z",
    pool_mode: str = "managed",
    active_attempt: ActiveAttempt | None = None,
) -> QueueRecord:
    return QueueRecord(
        queue_item_id=queue_item_id,
        queue_name="default",
        pool_name="local",
        pool_mode=pool_mode,
        run_uri=f"file:///runs/{queue_item_id}",
        status=status,
        enqueued_at=enqueued_at,
        updated_at=enqueued_at,
        dispatch_attempt=1,
        active_attempt=active_attempt,
    )


def _queue_service(tmp_path: Path, *, claimed: bool = False) -> QueueService:
    service = QueueService.from_spec(
        normalize_queue_spec(
            {
                "db_path": str(tmp_path / "queue.sqlite"),
                "pools": [{"pool_name": "local", "mode": "managed"}],
                "queues": [{"queue_name": "default", "pool_name": "local"}],
            }
        ),
        clock=lambda: "2026-08-19T00:00:00Z",
    )
    service.start()
    service.enqueue(
        QueueEnqueueRequest(
            queue_item_id="item-1",
            queue_name="default",
            run_uri="file:///runs/item-1",
            adapter="local",
        )
    )
    if claimed:
        service.claim_next("local", owner_id="controller", claim_id="claim-1")
    return service


def _inspect_run(run_uri: str, **_: Any) -> RunStatusSummary:
    return RunStatusSummary(
        run_uri=run_uri,
        status="RUNNING",
        state_source=authoritative_service_source(),
        stages=(
            StageStatusSummary(
                stage_name="build",
                status="RUNNING",
                attempt=1,
                state_source=authoritative_service_source(),
                log_source=local_materialization_source(),
            ),
        ),
    )


class _RunStore:
    def read_events(self, run_uri: str) -> tuple[object, ...]:
        del run_uri
        return ()


class _ManualMonotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

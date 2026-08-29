"""Textual master-detail application for the repository-local Loom monitor."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, ClassVar

from rich.console import Group
from rich.progress_bar import ProgressBar as RichProgressBar
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from .collector import MonitorCollector
from .models import (
    JobRecord,
    MonitorSnapshot,
    MonitorView,
    Observation,
    QueueRecord,
    RunRecord,
    StageRecord,
    TimelineEntry,
    WorkRecord,
)
from .presenter import (
    ACTIVE_QUEUE_STATUSES,
    build_work_records,
    display_run_name,
    fifo_positions,
    filter_work,
    format_age,
    format_duration,
    job_progress,
    merged_timeline,
    one_line,
    sanitize_terminal_text,
    source_indicator,
    stage_progress,
)


MONITOR_BLUE = "#3BB9FF"
PROGRESS_BACKGROUND = "#3A3A3A"
PROGRESS_ACTIVE = "#F92672"
PROGRESS_FINISHED = "#729C1F"
VIEW_ORDER = tuple(MonitorView)
LOG_STREAM_MODES = ("split", "stdout", "stderr")
TIMELINE_FILTERS = ("all", "queue", "authority", "stage", "scheduler", "warnings")
VISIBLE_RUN_LIMIT = 30


class FollowRichLog(RichLog):
    """RichLog that records whether operator scrolling paused follow mode."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(markup=False, highlight=False, auto_scroll=True, **kwargs)
        self.follow = True

    def action_scroll_up(self) -> None:
        self.follow = False
        super().action_scroll_up()

    def action_page_up(self) -> None:
        self.follow = False
        super().action_page_up()

    def action_scroll_home(self) -> None:
        self.follow = False
        super().action_scroll_home()

    def resume_follow(self) -> None:
        self.follow = True
        self.scroll_end(animate=False, immediate=True)


class HelpScreen(ModalScreen[None]):
    """Compact keyboard and evidence legend."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape,q,?", "close_help", "Close"),
    ]
    CSS = """
    HelpScreen {
        align: center middle;
        background: $background 65%;
    }
    #help {
        width: 86;
        max-width: 92%;
        height: auto;
        max-height: 90%;
        border: round #3BB9FF;
        background: $surface;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[b #3BB9FF]Loom monitor[/]\n\n"
            "↑ ↓ / j k  move        Enter  inspect/select\n"
            "Esc          return      Tab    next panel/tab\n"
            "/            filter      f      cycle work view\n"
            "p            pools       l      logs\n"
            "e            evidence    r      refresh now\n"
            "Space        pause       v      log stream\n"
            "t            timeline filter   End  resume log follow\n"
            "?            help        q      quit\n\n"
            "[b]Evidence[/]: fresh, persisted, stale, unavailable, and DIVERGENT "
            "describe observation quality; they are not lifecycle states.\n"
            "Identity colours distinguish executions only. Queue, run, stage, and "
            "scheduler statuses are always written as words.",
            id="help",
            markup=True,
        )

    def action_close_help(self) -> None:
        self.dismiss()


class LoomMonitorApp(App[None]):
    """Evidence-aware, read-only operational observer for one Loom queue."""

    TITLE = "Loom monitor"
    SUB_TITLE = "read-only operational observer"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_pause", "Pause"),
        Binding("f", "cycle_view", "View"),
        Binding("p", "focus_pools", "Pools"),
        Binding("/", "filter", "Filter"),
        Binding("enter", "inspect", "Inspect"),
        Binding("escape", "return_to_list", "Back", show=False),
        Binding("l", "logs", "Logs"),
        Binding("e", "evidence", "Evidence"),
        Binding("?", "help", "Help"),
        Binding("j", "move_down", "Down", show=False),
        Binding("k", "move_up", "Up", show=False),
        Binding("v", "cycle_log_stream", "Log stream", show=False),
        Binding("t", "cycle_timeline_filter", "Timeline filter", show=False),
        Binding("end", "follow_logs", "Follow logs", show=False),
    ]
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }
    #source-header {
        height: 3;
        border: round #3BB9FF;
        padding: 0 1;
    }
    #pool-table {
        height: 7;
        border: round #3BB9FF;
    }
    #workspace {
        height: 1fr;
        layout: horizontal;
    }
    #work-list-pane {
        width: 55%;
        height: 100%;
        border: round #3BB9FF;
    }
    #detail-pane {
        width: 45%;
        height: 100%;
        border: round #3BB9FF;
    }
    #work-title, #detail-title, .tab-summary, #logs-summary {
        height: auto;
        min-height: 1;
        padding: 0 1;
        color: #3BB9FF;
        text-style: bold;
    }
    #filter-input {
        display: none;
        height: 3;
        border: tall #3BB9FF;
    }
    #filter-input.visible {
        display: block;
    }
    #work-table, #stage-table, #jobs-table, #timeline-table {
        height: 1fr;
    }
    #overview-scroll, #evidence-scroll {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    #logs-view {
        height: 1fr;
        border: none;
        scrollbar-color: #3BB9FF;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    #workspace.narrow #detail-pane {
        display: none;
    }
    #workspace.narrow.detail-open #work-list-pane {
        display: none;
    }
    #workspace.narrow.detail-open #detail-pane {
        display: block;
        width: 100%;
    }
    Footer {
        height: 1;
        background: #3A3A3A;
    }
    """

    def __init__(
        self,
        collector: MonitorCollector,
        *,
        queue_interval: float = 1.0,
        run_interval: float = 1.0,
        authority_interval: float = 1.0,
        scheduler_interval: float = 1.0,
        log_interval: float = 1.0,
        log_tail: int = 100,
    ) -> None:
        super().__init__()
        self.collector = collector
        self.queue_interval = queue_interval
        self.run_interval = run_interval
        self.authority_interval = authority_interval
        self.scheduler_interval = scheduler_interval
        self.log_interval = log_interval
        self.log_tail = log_tail
        self.snapshot = collector.snapshot()
        self.current_view = MonitorView.ALL
        self.pool_filter: str | None = None
        self.text_filter = ""
        self.selected_item_id: str | None = None
        self.selected_stage: str | None = None
        self.log_stream_mode = "split"
        self.timeline_filter = "all"
        self.paused = False
        self.detail_open = False
        self._narrow = False
        self._updating_tables = False
        self._refreshing_sources: set[str] = set()
        self._work: tuple[WorkRecord, ...] = ()
        self._visible_work: tuple[WorkRecord, ...] = ()

    def compose(self) -> ComposeResult:
        yield Static(id="source-header")
        yield DataTable(id="pool-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="workspace"):
            with Vertical(id="work-list-pane"):
                yield Static(id="work-title")
                yield Input(
                    placeholder="Filter item, run, pool, stage, or status",
                    id="filter-input",
                )
                yield DataTable(id="work-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="detail-pane"):
                yield Static(id="detail-title")
                with TabbedContent(initial="overview-pane", id="detail-tabs"):
                    with TabPane("Overview", id="overview-pane"):
                        yield Static(id="overview-scroll")
                    with TabPane("Stages", id="stages-pane"):
                        yield Static(id="stage-summary", classes="tab-summary")
                        yield DataTable(
                            id="stage-table",
                            cursor_type="row",
                            zebra_stripes=True,
                        )
                    with TabPane("Jobs", id="jobs-pane"):
                        yield Static(id="jobs-summary", classes="tab-summary")
                        yield DataTable(
                            id="jobs-table",
                            cursor_type="row",
                            zebra_stripes=True,
                        )
                    with TabPane("Logs", id="logs-pane"):
                        yield Static(id="logs-summary")
                        yield FollowRichLog(id="logs-view", wrap=False, max_lines=500)
                    with TabPane("Timeline", id="timeline-pane"):
                        yield Static(id="timeline-summary", classes="tab-summary")
                        yield DataTable(
                            id="timeline-table",
                            cursor_type="row",
                            zebra_stripes=True,
                        )
                    with TabPane("Evidence", id="evidence-pane"):
                        yield Static(id="evidence-scroll")
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        self._configure_tables()
        self.query_one("#work-table", DataTable).focus()
        self._apply_snapshot(self.snapshot)
        self.set_interval(self.queue_interval, self._schedule_queue)
        self.set_interval(self.run_interval, self._schedule_runs)
        self.set_interval(self.run_interval, self._schedule_selected)
        self.set_interval(self.authority_interval, self._schedule_authority)
        self.set_interval(self.scheduler_interval, self._schedule_jobs)
        self.set_interval(self.log_interval, self._schedule_logs)
        self._schedule_queue(force=True)
        self._schedule_authority(force=True)

    def on_resize(self, event: events.Resize) -> None:
        self._narrow = event.size.width < 112
        workspace = self.query_one("#workspace", Horizontal)
        workspace.set_class(self._narrow, "narrow")
        workspace.set_class(self.detail_open, "detail-open")

    def _configure_tables(self) -> None:
        pool = self.query_one("#pool-table", DataTable)
        for label, key in (
            ("Pool", "pool"),
            ("Mode", "mode"),
            ("Queued", "queued"),
            ("Claimed", "claimed"),
            ("Dispatched", "dispatched"),
            ("Active/Limit", "active"),
            ("Succeeded", "succeeded"),
            ("Failed", "failed"),
            ("Cancelled", "cancelled"),
            ("Unknown", "unknown"),
            ("Oldest", "oldest"),
            ("Recovery", "recovery"),
        ):
            pool.add_column(label, key=key)

        work = self.query_one("#work-table", DataTable)
        for label, key in (
            ("Item", "item"),
            ("Run", "run"),
            ("Pool", "pool"),
            ("Queue state", "queue"),
            ("Run state", "run_state"),
            ("Stage", "current"),
            ("Execution", "execution"),
            ("Age", "age"),
            ("Evidence", "evidence"),
        ):
            work.add_column(label, key=key)

        stages = self.query_one("#stage-table", DataTable)
        for label, key in (
            ("Stage", "stage"),
            ("Stage state", "status"),
            ("Attempt", "attempt"),
            ("Message", "message"),
            ("Inputs", "inputs"),
            ("Outputs", "outputs"),
            ("Backend", "backend"),
            ("Logs", "logs"),
            ("Reliability", "reliability"),
        ):
            stages.add_column(label, key=key)

        jobs = self.query_one("#jobs-table", DataTable)
        for label, key in (
            ("Key", "key"),
            ("Stage", "stage"),
            ("Job", "job"),
            ("Loom", "loom"),
            ("Scheduler", "scheduler"),
            ("Source", "source"),
            ("Reason/dependency", "reason"),
            ("Exit", "exit"),
            ("Logs", "logs"),
            ("Warnings", "warnings"),
        ):
            jobs.add_column(label, key=key)

        timeline = self.query_one("#timeline-table", DataTable)
        for label, key in (
            ("Time", "time"),
            ("Source", "source"),
            ("Event", "event"),
            ("Detail", "detail"),
        ):
            timeline.add_column(label, key=key)

    def _schedule_queue(self, *, force: bool = False) -> None:
        if self.paused and not force:
            return
        self.run_worker(
            self._refresh_queue(),
            group="queue",
            exclusive=True,
            exit_on_error=False,
        )

    def _schedule_authority(self, *, force: bool = False) -> None:
        if self.paused and not force:
            return
        self.run_worker(
            self._refresh_authority(),
            group="authority",
            exclusive=True,
            exit_on_error=False,
        )

    def _schedule_runs(self, *, force: bool = False) -> None:
        if self.paused and not force:
            return
        run_uris = self._run_uris_to_observe()
        if not run_uris:
            return
        self.run_worker(
            self._refresh_runs(run_uris),
            group="runs",
            exclusive=True,
            exit_on_error=False,
        )

    def _schedule_selected(self, *, force: bool = False) -> None:
        if self.paused and not force:
            return
        if self.selected_item_id is None:
            return
        self.run_worker(
            self._refresh_selected(self.selected_item_id),
            group="selected",
            exclusive=True,
            exit_on_error=False,
        )

    def _schedule_jobs(self, *, force: bool = False) -> None:
        if self.paused and not force:
            return
        selected = self._selected_work()
        if selected is None or selected.item.pool_mode != "delegated":
            return
        self.run_worker(
            self._refresh_jobs(selected.item.run_uri),
            group="jobs",
            exclusive=True,
            exit_on_error=False,
        )

    def _schedule_logs(self, *, force: bool = False) -> None:
        if self.paused and not force:
            return
        selected = self._selected_work()
        if selected is None or self.selected_stage is None:
            return
        self.run_worker(
            self._refresh_logs(selected.item.run_uri, self.selected_stage),
            group="logs",
            exclusive=True,
            exit_on_error=False,
        )

    async def _refresh_queue(self) -> None:
        self._begin_refresh("queue")
        try:
            snapshot = await asyncio.to_thread(self.collector.refresh_queue)
        finally:
            self._end_refresh("queue")
        self._apply_snapshot(snapshot)
        if self.selected_item_id is None and self._visible_work:
            self.selected_item_id = self._visible_work[0].item.queue_item_id
            self._schedule_selected(force=True)
            self._schedule_runs(force=True)

    async def _refresh_authority(self) -> None:
        self._begin_refresh("authority")
        try:
            snapshot = await asyncio.to_thread(self.collector.refresh_authority)
        finally:
            self._end_refresh("authority")
        self._apply_snapshot(snapshot)

    async def _refresh_runs(self, run_uris: tuple[str, ...]) -> None:
        self._begin_refresh("runs")
        try:
            snapshot = await asyncio.to_thread(self.collector.refresh_runs, run_uris)
        finally:
            self._end_refresh("runs")
        self._apply_snapshot(snapshot)

    async def _refresh_selected(self, queue_item_id: str) -> None:
        self._begin_refresh("selected")
        try:
            snapshot = await asyncio.to_thread(
                self.collector.refresh_selected,
                queue_item_id,
            )
        finally:
            self._end_refresh("selected")
        if queue_item_id == self.selected_item_id:
            self._apply_snapshot(snapshot)

    async def _refresh_jobs(self, run_uri: str) -> None:
        self._begin_refresh("scheduler")
        try:
            snapshot = await asyncio.to_thread(self.collector.refresh_jobs, run_uri)
        finally:
            self._end_refresh("scheduler")
        selected = self._selected_work()
        if selected is not None and selected.item.run_uri == run_uri:
            self._apply_snapshot(snapshot)

    async def _refresh_logs(self, run_uri: str, stage_name: str) -> None:
        self._begin_refresh("logs")
        try:
            snapshot = await asyncio.to_thread(
                self.collector.refresh_logs,
                run_uri,
                stage_name,
                tail=self.log_tail,
            )
        finally:
            self._end_refresh("logs")
        selected = self._selected_work()
        if (
            selected is not None
            and selected.item.run_uri == run_uri
            and self.selected_stage == stage_name
        ):
            self._apply_snapshot(snapshot)

    def _apply_snapshot(self, snapshot: MonitorSnapshot) -> None:
        self.snapshot = snapshot
        self._work = build_work_records(snapshot)
        self._visible_work = filter_work(
            self._work,
            view=self.current_view,
            pool_name=self.pool_filter,
            query=self.text_filter,
        )
        self._render_header()
        self._render_pools()
        self._render_work()
        self._render_detail()

    def _render_header(self) -> None:
        now = self._now()
        queue = source_indicator(
            self.snapshot.queue,
            now=now,
            ready="Queue READABLE",
            unavailable="UNAVAILABLE",
        )
        authority = self.snapshot.authority
        if authority.error is not None or authority.value is None:
            authority_text = source_indicator(
                authority,
                now=now,
                ready="Authority",
                unavailable="UNOBSERVED",
            )
        else:
            authority_text = f"Authority {authority.value.state}"
            if authority.value.message:
                authority_text += f" — {one_line(authority.value.message)}"
        scheduler = self.snapshot.jobs
        if scheduler.value is None and scheduler.error is None:
            scheduler_text = "SLURM NOT QUERIED"
        elif scheduler.error is None:
            scheduler_text = (
                f"SLURM fresh {format_age(scheduler.last_success_at, now=now)}"
            )
        else:
            scheduler_text = source_indicator(
                scheduler,
                now=now,
                ready="SLURM",
                unavailable="UNAVAILABLE",
            )
        last = max(
            (
                observed.last_success_at
                for observed in (self.snapshot.queue, self.snapshot.authority)
                if observed.last_success_at is not None
            ),
            default=None,
        )
        workspace = (
            self.collector.workspace_name
            if self.snapshot.queue.value is None
            else self.snapshot.queue.value.workspace_name
        )
        if self._refreshing_sources:
            mode = "REFRESHING " + ",".join(sorted(self._refreshing_sources))
        else:
            mode = "PAUSED" if self.paused else f"AUTO {self.queue_interval:g}s"
        line = Text()
        line.append(f"Loom monitor · {workspace}", style=f"bold {MONITOR_BLUE}")
        line.append(f"   {now.astimezone().strftime('%H:%M:%S')}\n")
        line.append(queue)
        line.append(" │ ")
        line.append(authority_text)
        line.append(" │ Runtime UNOBSERVED │ ")
        line.append(scheduler_text)
        line.append(" │ ")
        line.append(mode, style="bold")
        if last is not None:
            line.append(f" │ Last refresh {last.astimezone().strftime('%H:%M:%S')}")
        self.query_one("#source-header", Static).update(line)

    def _render_pools(self) -> None:
        queue = self.snapshot.queue.value
        rows: list[tuple[str, tuple[Any, ...]]] = []
        if queue is not None:
            now = self._now()
            for pool in queue.pools:
                rows.append(
                    (
                        pool.pool_name,
                        (
                            pool.pool_name,
                            pool.mode,
                            pool.queued,
                            pool.claimed,
                            pool.dispatched,
                            f"{pool.active}/{pool.controller_limit}",
                            pool.succeeded,
                            pool.failed,
                            pool.cancelled,
                            pool.unknown,
                            format_age(pool.oldest_queued_at, now=now),
                            pool.recovery_count,
                        ),
                    )
                )
        self._replace_rows(self.query_one("#pool-table", DataTable), rows)

    def _render_work(self) -> None:
        title = f"Work · {self.current_view.value}"
        if self.pool_filter:
            title += f" · pool={self.pool_filter}"
        if self.text_filter:
            title += f" · /{self.text_filter}/"
        title += f" · {len(self._visible_work)}/{len(self._work)}"
        self.query_one("#work-title", Static).update(title)
        now = self._now()
        rows: list[tuple[str, tuple[Any, ...]]] = []
        for work in self._visible_work:
            queue_status = work.item.status
            run_status = (
                "—" if work.run is None or work.run.status is None else work.run.status
            )
            age = _work_age(work.item, now=now)
            rows.append(
                (
                    work.item.queue_item_id,
                    (
                        work.item.queue_item_id,
                        display_run_name(work.item.run_uri),
                        work.item.pool_name,
                        queue_status,
                        run_status,
                        work.current_stage or "—",
                        work.execution,
                        age,
                        work.evidence,
                    ),
                )
            )
        self._replace_rows(self.query_one("#work-table", DataTable), rows)

    def _render_detail(self) -> None:
        selected = self._selected_work()
        if selected is None:
            self.query_one("#detail-title", Static).update("Selected item · —")
            self.query_one("#overview-scroll", Static).update(
                "Select a queue item to inspect its lifecycle layers."
            )
            self._replace_rows(self.query_one("#stage-table", DataTable), [])
            self._replace_rows(self.query_one("#jobs-table", DataTable), [])
            self._replace_rows(self.query_one("#timeline-table", DataTable), [])
            self.query_one("#evidence-scroll", Static).update("")
            return
        mismatch = selected not in self._visible_work
        title = f"Selected · {selected.item.queue_item_id}"
        if mismatch:
            title += f" · no longer matches {self.current_view.value!r}"
        self.query_one("#detail-title", Static).update(title)
        self._ensure_selected_stage(selected.run)
        self.query_one("#overview-scroll", Static).update(
            self._overview_renderable(selected)
        )
        self._render_stages(selected)
        self._render_jobs(selected)
        self._render_logs(selected)
        self._render_timeline(selected)
        self.query_one("#evidence-scroll", Static).update(
            self._evidence_renderable(selected)
        )

    def _overview_renderable(self, work: WorkRecord) -> Group:
        item = work.item
        now = self._now()
        positions = fifo_positions(tuple(record.item for record in self._work))
        queue = _section_table("Queue")
        _add_rows(
            queue,
            (
                ("Item", item.queue_item_id),
                (
                    "Queue / pool",
                    f"{item.queue_name} / {item.pool_name} ({item.pool_mode})",
                ),
                ("Status", item.status),
                ("Enqueued", item.enqueued_at),
                (_age_label(item), _work_age(item, now=now)),
                (
                    "Position",
                    "—"
                    if item.queue_item_id not in positions
                    else (
                        f"{positions[item.queue_item_id][0]} of "
                        f"{positions[item.queue_item_id][1]} waiting"
                    ),
                ),
                ("Dispatch attempt", str(item.dispatch_attempt)),
                ("Resources", _mapping_text(item.requested_resources)),
                ("Claim", _claim_text(item)),
                ("Dispatch", _dispatch_text(item)),
                ("Cancellation", _cancellation_text(item)),
                ("Recovery", _mapping_text(item.recovery_detail or {})),
                ("Latest audit", self._latest_audit_text()),
            ),
        )
        run_table = _section_table("Run")
        run = work.run
        if run is None:
            error = None if work.run_observation is None else work.run_observation.error
            _add_rows(
                run_table,
                (
                    ("URI", item.run_uri),
                    ("Authority", "unavailable" if error else "not observed"),
                    ("Diagnostic", "—" if error is None else one_line(error)),
                ),
            )
        else:
            counts = _stage_counts(run.stages)
            active_operation = next(
                (
                    operation
                    for operation in reversed(run.submitted_operations)
                    if operation.active
                ),
                None,
            )
            _add_rows(
                run_table,
                (
                    ("URI", run.run_uri),
                    ("Authority status", run.status or "—"),
                    ("Stages", counts),
                    ("Current", work.current_stage or "—"),
                    (
                        "Submitted operation",
                        "—"
                        if active_operation is None
                        else f"{active_operation.backend}:{active_operation.state}",
                    ),
                    ("Artifacts", str(run.artifact_count)),
                    ("State source", str(run.state_source.get("label", "unknown"))),
                    (
                        "Observed",
                        "—"
                        if work.run_observation is None
                        else format_age(work.run_observation.last_success_at, now=now)
                        + " ago",
                    ),
                ),
            )
        execution = _section_table("Execution")
        attempt = item.active_attempt
        if item.pool_mode == "managed":
            process = "—" if attempt is None else _mapping_text(attempt.process or {})
            assignment = (
                "—" if attempt is None else _assignment_text(attempt.assignment)
            )
            logs = "—" if attempt is None else _mapping_text(attempt.logs or {})
            _add_rows(
                execution,
                (
                    ("Mode", "managed local"),
                    ("Process", process),
                    ("Owner / session", _owner_session_text(attempt)),
                    ("Assignment", assignment),
                    ("Logs", logs),
                    (
                        "Live observation",
                        "unavailable" if attempt is None else attempt.live_observation,
                    ),
                ),
            )
        else:
            jobs = self._selected_jobs(work)
            job = jobs[0] if jobs else None
            _add_rows(
                execution,
                (
                    ("Mode", "delegated"),
                    ("Backend", item.adapter or "—"),
                    ("Scheduler job", "—" if job is None else job.scheduler_job_id),
                    (
                        "Scheduler state",
                        "not queried" if job is None else job.scheduler_state,
                    ),
                    ("Source", "—" if job is None else job.source),
                    ("Dependency", "—" if job is None else job.dependency_state or "—"),
                    ("Exit", "—" if job is None else job.exit_code or "—"),
                    (
                        "Warnings",
                        "—" if job is None else "; ".join(job.warnings) or "—",
                    ),
                ),
            )
        state_lines = Text()
        state_lines.append("Lifecycle owners\n", style=f"bold {MONITOR_BLUE}")
        state_lines.append(f"Queue       {item.status}\n")
        state_lines.append(
            f"Authority   {run.status if run and run.status else 'unavailable'}\n"
        )
        jobs = self._selected_jobs(work)
        if jobs:
            state_lines.append(f"Scheduler   {jobs[0].scheduler_state}\n")
        observed = [
            f"queue {format_age(self.snapshot.queue.last_success_at, now=now)} ago"
        ]
        if work.run_observation is not None:
            observed.append(
                f"authority {format_age(work.run_observation.last_success_at, now=now)} ago"
            )
        if jobs:
            observed.append(
                f"scheduler {format_age(self.snapshot.jobs.last_success_at, now=now)} ago"
            )
        state_lines.append(f"Observed    {' · '.join(observed)}\n")
        if work.divergent:
            state_lines.append(
                "DIVERGENT — inspect evidence; no state was synthesized",
                style="bold yellow",
            )
        return Group(
            queue, Text(""), run_table, Text(""), execution, Text(""), state_lines
        )

    def _render_stages(self, work: WorkRecord) -> None:
        run = work.run
        rows: list[tuple[str, tuple[Any, ...]]] = []
        if run is None:
            self.query_one("#stage-summary", Static).update("Stages · unavailable")
        else:
            settled, total = stage_progress(run.stages)
            progress = RichProgressBar(
                total=max(total, 1),
                completed=settled,
                width=24,
                style=PROGRESS_BACKGROUND,
                complete_style=PROGRESS_ACTIVE,
                finished_style=PROGRESS_FINISHED,
            )
            counts = _stage_counts(run.stages)
            self.query_one("#stage-summary", Static).update(
                Group(
                    Text(f"Stages · {settled} settled / {total} total · {counts}"),
                    progress,
                )
            )
            backend_by_stage = _backend_by_stage(run)
            for stage in run.stages:
                log_state = (
                    "/".join(
                        stream
                        for stream, available in stage.log_available.items()
                        if available
                    )
                    or "—"
                )
                rows.append(
                    (
                        stage.stage_name,
                        (
                            stage.stage_name,
                            stage.status or "—",
                            stage.attempt or "—",
                            one_line(
                                stage.message or _failure_message(stage.failure) or "—"
                            ),
                            stage.input_count,
                            stage.output_count,
                            backend_by_stage.get(stage.stage_name, "—"),
                            log_state,
                            "WARNING" if stage.reliability_warning_count else "NONE",
                        ),
                    )
                )
        self._replace_rows(self.query_one("#stage-table", DataTable), rows)

    def _render_jobs(self, work: WorkRecord) -> None:
        jobs_observation = self.snapshot.jobs
        jobs = self._selected_jobs(work)
        rows: list[tuple[str, tuple[Any, ...]]] = []
        if jobs_observation.error and not jobs:
            summary: Any = f"Jobs · unavailable — {one_line(jobs_observation.error)}"
        elif not jobs:
            summary = "Jobs · not queried or no SLURM submission"
        else:
            terminal, total = job_progress(jobs)
            progress = RichProgressBar(
                total=max(total, 1),
                completed=terminal,
                width=24,
                style=PROGRESS_BACKGROUND,
                complete_style=PROGRESS_ACTIVE,
                finished_style=PROGRESS_FINISHED,
            )
            data = jobs_observation.value
            submission = "—" if data is None else data.submission_state or "—"
            failed_submissions = 0 if data is None else data.failed_submission_count
            summary = Group(
                Text(
                    f"Jobs · submission={submission} · {terminal} terminal / "
                    f"{total} submitted · failed submissions={failed_submissions}"
                ),
                progress,
            )
            for job in jobs:
                reason = job.dependency_state or ""
                if job.dependency_job_ids:
                    reason = f"{reason} [{', '.join(job.dependency_job_ids)}]".strip()
                rows.append(
                    (
                        job.logical_key,
                        (
                            job.logical_key,
                            job.stage_name or "—",
                            job.scheduler_job_id,
                            f"{submission}/{job.status}",
                            job.scheduler_state,
                            job.source,
                            reason or "—",
                            job.exit_code or "—",
                            _mapping_text(job.log_paths),
                            "; ".join(job.warnings) or "—",
                        ),
                    )
                )
        self.query_one("#jobs-summary", Static).update(summary)
        self._replace_rows(self.query_one("#jobs-table", DataTable), rows)

    def _render_logs(self, work: WorkRecord) -> None:
        observation = self.snapshot.logs
        data = observation.value
        applies = (
            data is not None
            and data.run_uri == work.item.run_uri
            and data.stage_name == self.selected_stage
        )
        log = self.query_one("#logs-view", FollowRichLog)
        if not applies:
            detail = "not queried"
            if observation.error:
                detail = f"unavailable — {one_line(observation.error)}"
            self.query_one("#logs-summary", Static).update(
                f"Logs · stage={self.selected_stage or '—'} · {detail}"
            )
            if not log.lines:
                log.write(
                    "Open this tab or press l to inspect the selected stage logs."
                )
            return
        assert data is not None
        selected_streams = tuple(
            stream
            for stream in data.streams
            if self.log_stream_mode == "split" or stream.stream == self.log_stream_mode
        )
        total = sum(stream.line_count for stream in selected_streams)
        displayed = sum(stream.displayed_line_count for stream in selected_streams)
        truncated = any(stream.truncated for stream in selected_streams)
        path_text = " · ".join(
            f"{stream.stream}={stream.path}" for stream in selected_streams
        )
        follow = "FOLLOW" if log.follow else "PAUSED (End resumes)"
        observed = format_age(observation.last_success_at, now=self._now())
        self.query_one("#logs-summary", Static).update(
            f"Logs · {data.stage_name} · {self.log_stream_mode} · {displayed}/{total} lines"
            f"{' · truncated' if truncated else ''} · observed {observed} ago · "
            f"{follow}\n{path_text}"
        )
        old_y = log.scroll_y
        log.clear()
        wrote = False
        for stream in selected_streams:
            if self.log_stream_mode == "split":
                log.write(f"── {stream.stream} ──", scroll_end=False)
            if stream.available and stream.content is not None:
                log.write(
                    sanitize_terminal_text(stream.content),
                    scroll_end=log.follow,
                )
                wrote = True
            else:
                log.write(
                    f"[{stream.stream}] no durable log content is available",
                    scroll_end=False,
                )
        if not wrote:
            reason = data.unavailable_reason or (
                "The in-process local executor may have emitted directly to its parent terminal."
            )
            log.write(sanitize_terminal_text(reason), scroll_end=False)
        if not log.follow:
            log.scroll_to(y=old_y, animate=False, immediate=True, force=True)

    def _render_timeline(self, work: WorkRecord) -> None:
        selected = self.snapshot.selected.value
        queue_entries = () if selected is None else selected.audit_events
        run_entries = () if selected is None else selected.run_events
        scheduler_entries = tuple(
            TimelineEntry(
                occurred_at=(
                    self.snapshot.jobs.last_success_at.isoformat().replace(
                        "+00:00", "Z"
                    )
                    if self.snapshot.jobs.last_success_at is not None
                    else work.item.updated_at
                ),
                source="SCHEDULER",
                event_type="scheduler.observed",
                summary=f"job {job.scheduler_job_id} observed {job.scheduler_state}",
                stage_name=job.stage_name,
                warning=bool(job.warnings),
            )
            for job in self._selected_jobs(work)
        )
        entries = merged_timeline(
            queue_entries=queue_entries,
            run_entries=run_entries,
            scheduler_entries=scheduler_entries,
        )
        entries = tuple(entry for entry in entries if self._timeline_matches(entry))
        error = (
            ""
            if selected is None or selected.run_events_error is None
            else (f" · run events unavailable: {selected.run_events_error}")
        )
        self.query_one("#timeline-summary", Static).update(
            f"Timeline · filter={self.timeline_filter} · {len(entries)} events{error}"
        )
        rows = [
            (
                f"{entry.source}:{index}",
                (
                    _clock_text(entry.occurred_at),
                    entry.source,
                    (
                        f"WARNING · {entry.event_type}"
                        if entry.warning
                        else entry.event_type
                    ),
                    entry.summary,
                ),
            )
            for index, entry in enumerate(entries)
        ]
        self._replace_rows(self.query_one("#timeline-table", DataTable), rows)

    def _evidence_renderable(self, work: WorkRecord) -> Table:
        table = Table.grid(padding=(0, 2), expand=True)
        table.add_column(style=f"bold {MONITOR_BLUE}", no_wrap=True)
        table.add_column()
        table.add_column()
        now = self._now()
        queue = self.snapshot.queue
        table.add_row(
            "Queue state",
            "queue · persisted SQLite snapshot",
            (
                f"{_observation_detail(queue, now=now)} · "
                f"audit sequence={_latest_audit_sequence(self.snapshot)}"
            ),
        )
        run_observation = work.run_observation
        if run_observation is None:
            table.add_row("Run state", "authority", "unavailable · not observed")
        else:
            label = (
                "unknown"
                if run_observation.value is None
                else str(run_observation.value.state_source.get("label", "unknown"))
            )
            table.add_row(
                "Run state",
                f"authority · {label}",
                _observation_detail(run_observation, now=now),
            )
        stage = (
            None
            if work.run is None
            else next(
                (
                    candidate
                    for candidate in work.run.stages
                    if candidate.stage_name == self.selected_stage
                ),
                None,
            )
        )
        if stage is not None:
            table.add_row(
                f"Stage {stage.stage_name}",
                f"authority · {stage.state_source.get('label', 'unknown')}",
                (
                    f"status={stage.status or '—'} · attempt={stage.attempt or '—'} · "
                    f"reliability warnings={stage.reliability_warning_count}"
                ),
            )
            table.add_row(
                "Stage logs",
                f"materialization · {stage.log_source.get('label', 'unknown')}",
                _mapping_text(stage.log_available),
            )
        attempt = work.item.active_attempt
        table.add_row(
            "Process identity",
            "queue dispatch evidence",
            (
                "unavailable"
                if attempt is None
                else f"persisted · liveness={attempt.live_observation}"
            ),
        )
        table.add_row(
            "Resource slots",
            "queue assignment",
            (
                "unavailable"
                if attempt is None or attempt.assignment is None
                else "persisted assignment · hardware availability not observed"
            ),
        )
        jobs = self._selected_jobs(work)
        table.add_row(
            "Scheduler state",
            "delegated scheduler",
            (
                _observation_detail(self.snapshot.jobs, now=now)
                if jobs
                else "not queried or not applicable"
            ),
        )
        logs = self.snapshot.logs.value
        logs_apply = logs is not None and logs.run_uri == work.item.run_uri
        table.add_row(
            "Logs",
            "local materialization",
            (
                _observation_detail(self.snapshot.logs, now=now)
                if logs_apply
                else "not queried"
            ),
        )
        if work.divergent:
            table.add_row(
                "Lifecycle comparison",
                "derived presentation",
                "DIVERGENT · owners shown separately; no true status synthesized",
            )
        table.caption = (
            "Only allowlisted projections are displayed; raw dispatch evidence, "
            "environment values, and provider-private data are omitted."
        )
        return table

    def _replace_rows(
        self,
        table: DataTable[Any],
        rows: list[tuple[str, tuple[Any, ...]]],
    ) -> None:
        desired_keys = [key for key, _ in rows]
        existing_keys = [key.value for key in table.rows]
        selected_key = None
        if table.row_count:
            try:
                selected_key = list(table.rows)[table.cursor_row].value
            except (IndexError, KeyError):
                selected_key = None
        old_scroll_y = table.scroll_y
        self._updating_tables = True
        try:
            if existing_keys == desired_keys:
                for row_key, values in rows:
                    for column_key, value in zip(table.columns, values, strict=True):
                        table.update_cell(row_key, column_key, value)
            else:
                table.clear()
                for row_key, values in rows:
                    table.add_row(*values, key=row_key)
                if selected_key in desired_keys:
                    table.move_cursor(
                        row=desired_keys.index(selected_key), animate=False
                    )
                elif desired_keys:
                    table.move_cursor(row=0, animate=False)
                table.scroll_to(y=old_scroll_y, animate=False, immediate=True)
        finally:
            self._updating_tables = False

    def _selected_work(self) -> WorkRecord | None:
        if self.selected_item_id is None:
            return None
        return next(
            (
                record
                for record in self._work
                if record.item.queue_item_id == self.selected_item_id
            ),
            None,
        )

    def _begin_refresh(self, source: str) -> None:
        self._refreshing_sources.add(source)
        if self.is_mounted:
            self._render_header()

    def _end_refresh(self, source: str) -> None:
        self._refreshing_sources.discard(source)

    def _selected_jobs(self, work: WorkRecord) -> tuple[JobRecord, ...]:
        data = self.snapshot.jobs.value
        if data is None or data.run_uri != work.item.run_uri:
            return ()
        return data.jobs

    def _ensure_selected_stage(self, run: RunRecord | None) -> None:
        if run is None or not run.stages:
            self.selected_stage = None
            return
        if self.selected_stage not in {stage.stage_name for stage in run.stages}:
            preferred = next(
                (
                    stage
                    for stage in run.stages
                    if stage.status in {"FAILED", "BLOCKED", "RUNNING", "SUBMITTED"}
                ),
                run.stages[0],
            )
            self.selected_stage = preferred.stage_name

    def _run_uris_to_observe(self) -> tuple[str, ...]:
        visible = [
            record.item.run_uri for record in self._visible_work[:VISIBLE_RUN_LIMIT]
        ]
        selected = self._selected_work()
        if selected is not None:
            visible.append(selected.item.run_uri)
        return tuple(dict.fromkeys(visible))

    def _active_detail_tab(self) -> str:
        return self.query_one("#detail-tabs", TabbedContent).active

    def _timeline_matches(self, entry: TimelineEntry) -> bool:
        match self.timeline_filter:
            case "queue":
                return entry.source == "QUEUE"
            case "authority":
                return entry.source == "AUTHORITY"
            case "stage":
                return (
                    self.selected_stage is not None
                    and entry.stage_name == self.selected_stage
                )
            case "scheduler":
                return entry.source == "SCHEDULER"
            case "warnings":
                return entry.warning
            case _:
                return True

    def _latest_audit_text(self) -> str:
        selected = self.snapshot.selected.value
        if selected is None or not selected.audit_events:
            return "—"
        latest = selected.audit_events[-1]
        return f"{latest.event_type} · {latest.summary}"

    def _now(self) -> datetime:
        return self.collector.now()

    def on_data_table_row_highlighted(
        self,
        event: DataTable.RowHighlighted,
    ) -> None:
        if self._updating_tables:
            return
        if event.data_table.id == "work-table" and event.row_key.value is not None:
            self.selected_item_id = event.row_key.value
            self.selected_stage = None
            self._render_detail()
            self._schedule_selected(force=True)
            self._schedule_runs(force=True)
        elif event.data_table.id == "stage-table" and event.row_key.value is not None:
            self.selected_stage = event.row_key.value
            self._render_detail()
            if self._active_detail_tab() == "logs-pane":
                self._schedule_logs(force=True)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "pool-table" and event.row_key.value is not None:
            selected = event.row_key.value
            self.pool_filter = None if self.pool_filter == selected else selected
            self._apply_snapshot(self.snapshot)
            self.query_one("#work-table", DataTable).focus()
            return
        if event.data_table.id == "work-table":
            if event.row_key.value is not None:
                self.selected_item_id = event.row_key.value
            if self._narrow:
                self.detail_open = True
                self.query_one("#workspace", Horizontal).add_class("detail-open")

    def on_tabbed_content_tab_activated(
        self,
        event: TabbedContent.TabActivated,
    ) -> None:
        if event.tabbed_content.id != "detail-tabs":
            return
        if event.pane.id == "jobs-pane":
            self._schedule_jobs(force=True)
        elif event.pane.id == "logs-pane":
            self._schedule_logs(force=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "filter-input":
            return
        self.text_filter = event.value.strip()
        event.input.remove_class("visible")
        self._apply_snapshot(self.snapshot)
        self.query_one("#work-table", DataTable).focus()

    def action_refresh(self) -> None:
        self._schedule_queue(force=True)
        self._schedule_authority(force=True)
        self._schedule_runs(force=True)
        self._schedule_selected(force=True)
        self._schedule_jobs(force=True)
        self._schedule_logs(force=True)

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        self._render_header()

    def action_cycle_view(self) -> None:
        index = VIEW_ORDER.index(self.current_view)
        self.current_view = VIEW_ORDER[(index + 1) % len(VIEW_ORDER)]
        self._apply_snapshot(self.snapshot)

    def action_focus_pools(self) -> None:
        self.query_one("#pool-table", DataTable).focus()

    def action_filter(self) -> None:
        input_widget = self.query_one("#filter-input", Input)
        input_widget.value = self.text_filter
        input_widget.add_class("visible")
        input_widget.focus()

    def action_inspect(self) -> None:
        focused = self.focused
        if isinstance(focused, DataTable) and focused.id == "pool-table":
            if focused.row_count:
                key = list(focused.rows)[focused.cursor_row].value
                if key is not None:
                    self.pool_filter = None if self.pool_filter == key else key
                    self._apply_snapshot(self.snapshot)
            return
        if self.selected_item_id is not None and self._narrow:
            self.detail_open = True
            self.query_one("#workspace", Horizontal).add_class("detail-open")

    def action_return_to_list(self) -> None:
        input_widget = self.query_one("#filter-input", Input)
        if input_widget.has_class("visible"):
            input_widget.remove_class("visible")
            self.query_one("#work-table", DataTable).focus()
            return
        if self.detail_open:
            self.detail_open = False
            self.query_one("#workspace", Horizontal).remove_class("detail-open")
            self.query_one("#work-table", DataTable).focus()

    def action_logs(self) -> None:
        self.query_one("#detail-tabs", TabbedContent).active = "logs-pane"
        if self._narrow:
            self.detail_open = True
            self.query_one("#workspace", Horizontal).add_class("detail-open")
        self._schedule_logs(force=True)

    def action_evidence(self) -> None:
        self.query_one("#detail-tabs", TabbedContent).active = "evidence-pane"
        if self._narrow:
            self.detail_open = True
            self.query_one("#workspace", Horizontal).add_class("detail-open")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_move_down(self) -> None:
        if isinstance(self.focused, DataTable):
            self.focused.action_cursor_down()

    def action_move_up(self) -> None:
        if isinstance(self.focused, DataTable):
            self.focused.action_cursor_up()

    def action_cycle_log_stream(self) -> None:
        if self._active_detail_tab() != "logs-pane":
            return
        index = LOG_STREAM_MODES.index(self.log_stream_mode)
        self.log_stream_mode = LOG_STREAM_MODES[(index + 1) % len(LOG_STREAM_MODES)]
        selected = self._selected_work()
        if selected is not None:
            self._render_logs(selected)

    def action_cycle_timeline_filter(self) -> None:
        if self._active_detail_tab() != "timeline-pane":
            return
        index = TIMELINE_FILTERS.index(self.timeline_filter)
        self.timeline_filter = TIMELINE_FILTERS[(index + 1) % len(TIMELINE_FILTERS)]
        selected = self._selected_work()
        if selected is not None:
            self._render_timeline(selected)

    def action_follow_logs(self) -> None:
        if self._active_detail_tab() == "logs-pane":
            self.query_one("#logs-view", FollowRichLog).resume_follow()


def _section_table(title: str) -> Table:
    table = Table.grid(padding=(0, 2), expand=True)
    table.add_column(style=f"bold {MONITOR_BLUE}", no_wrap=True)
    table.add_column()
    table.title = title
    table.title_style = f"bold {MONITOR_BLUE}"
    return table


def _add_rows(table: Table, rows: tuple[tuple[str, str], ...]) -> None:
    for label, value in rows:
        table.add_row(label, value)


def _mapping_text(value: Any) -> str:
    if not value:
        return "—"
    return " ".join(f"{key}={item}" for key, item in value.items())


def _claim_text(item: QueueRecord) -> str:
    if item.claim_owner is None:
        return "—"
    return f"owner={item.claim_owner} at={item.claimed_at or '—'}"


def _work_age(item: QueueRecord, *, now: datetime) -> str:
    if item.status == "QUEUED":
        return format_duration(item.enqueued_at, now)
    if item.status in ACTIVE_QUEUE_STATUSES:
        started = item.claimed_at or item.dispatched_at or item.updated_at
        return format_duration(started, now)
    return format_duration(item.enqueued_at, item.updated_at)


def _age_label(item: QueueRecord) -> str:
    if item.status == "QUEUED":
        return "Wait age"
    if item.status in ACTIVE_QUEUE_STATUSES:
        return "Active age"
    return "Total age"


def _dispatch_text(item: QueueRecord) -> str:
    if item.dispatch_handle_id is None:
        return f"adapter={item.adapter or '—'}"
    return (
        f"adapter={item.adapter or '—'} handle={item.dispatch_handle_id} "
        f"at={item.dispatched_at or '—'}"
    )


def _cancellation_text(item: QueueRecord) -> str:
    if item.cancellation_requested_at is None:
        return "—"
    return (
        f"at={item.cancellation_requested_at} "
        f"by={item.cancellation_requested_by or '—'} "
        f"reason={item.cancellation_reason or '—'}"
    )


def _owner_session_text(attempt: Any | None) -> str:
    if attempt is None:
        return "—"
    return f"{attempt.owner_id or '—'} / {attempt.session_id or '—'}"


def _assignment_text(assignment: Any | None) -> str:
    if not assignment:
        return "—"
    provider = assignment.get("provider_name", "—")
    slots = assignment.get("slots", ())
    if not isinstance(slots, (list, tuple)):
        return f"provider={provider}"
    labels = []
    for slot in slots:
        if hasattr(slot, "get"):
            identity = slot.get("label") or slot.get("slot_id") or "UNKNOWN"
            resource = slot.get("resource_name") or "resource"
            expiry = slot.get("expires_at") or "UNKNOWN"
            labels.append(f"{resource}:{identity} expires={expiry}")
    return f"provider={provider} slots={','.join(labels) or '—'}"


def _stage_counts(stages: tuple[StageRecord, ...]) -> str:
    counts: dict[str, int] = {}
    for stage in stages:
        key = stage.status or "UNKNOWN"
        counts[key] = counts.get(key, 0) + 1
    return (
        " ".join(
            f"{status.lower()}={count}" for status, count in sorted(counts.items())
        )
        or "—"
    )


def _backend_by_stage(run: RunRecord) -> dict[str, str]:
    active = next(
        (
            operation
            for operation in reversed(run.submitted_operations)
            if operation.active
        ),
        None,
    )
    if active is None:
        return {}
    return {
        stage.stage_name: active.backend
        for stage in run.stages
        if stage.status == "SUBMITTED"
    }


def _failure_message(failure: Any | None) -> str | None:
    if not failure:
        return None
    for key in ("message", "reason", "error"):
        value = failure.get(key)
        if isinstance(value, str):
            return value
    return None


def _clock_text(timestamp: str) -> str:
    try:
        return timestamp.split("T", maxsplit=1)[1].replace("Z", "")
    except IndexError:
        return timestamp


def _observation_detail(observation: Observation[Any], *, now: datetime) -> str:
    if observation.error is not None:
        state = "stale" if observation.value is not None else "unavailable"
        return f"{state} · {one_line(observation.error)}"
    if observation.last_success_at is None:
        return "unavailable"
    return f"observed {format_age(observation.last_success_at, now=now)} ago"


def _latest_audit_sequence(snapshot: MonitorSnapshot) -> str:
    selected = snapshot.selected.value
    if selected is None or not selected.audit_events:
        return "—"
    sequence = selected.audit_events[-1].sequence
    return "—" if sequence is None else str(sequence)


__all__ = ["LoomMonitorApp"]

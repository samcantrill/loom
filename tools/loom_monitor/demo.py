"""Deterministic, isolated playground for the repository-local Loom monitor."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
from threading import RLock
import tempfile
import time
from typing import Any

from loom.diagnostics.inspection import (
    LogStreamSummary,
    RunStatusSummary,
    StageLogsSummary,
    StageStatusSummary,
    SubmittedOperationSummary,
)
from loom.pipeline.executors.slurm.status import (
    SlurmJobStatusSummary,
    SlurmJobsStatusReport,
)
from loom.queue import (
    DispatchHandle,
    QueueEnqueueRequest,
    QueueItem,
    QueueItemStatus,
    QueueService,
    normalize_queue_spec,
)
from loom.serialization import PlainData
from loom.state_sources import (
    authoritative_service_source,
    local_materialization_source,
)
from loom.timestamps import utc_timestamp

from .collector import MonitorCollector
from .models import AuthorityData, MonitorSnapshot, MonitorView


DEMO_SCENARIOS = ("mixed", "failures", "scheduler")
_LOCAL_POOL = "local-pool"
_LOCAL_QUEUE = "local"
_SLURM_POOL = "slurm-pool"
_SLURM_QUEUE = "slurm"
_OWNER_ID = "demo-controller"
_SESSION_ID = "demo-session"


def _claim_demo_item(
    service: QueueService,
    pool_name: str,
    *,
    owner_id: str,
    claim_id: str,
) -> QueueItem | None:
    """Claim the next demo fixture through the current exact-ownership seam."""

    candidate = next(
        (
            item
            for item in service.read_pool_snapshot(pool_name).items
            if QueueItemStatus(item.status) is QueueItemStatus.QUEUED
        ),
        None,
    )
    if candidate is None:
        return None
    claimer = getattr(service.repository, "_claim_selection_candidate", None)
    if not callable(claimer):
        raise RuntimeError("demo queue repository cannot claim an exact selection")
    claimed = claimer(
        candidate.queue_item_id,
        pool_name=pool_name,
        expected_dispatch_attempt=candidate.dispatch_attempt,
        owner_id=owner_id,
        claim_id=claim_id,
        preference_id="loom_monitor.demo",
        reason_code="loom_monitor.demo.fixture",
    )
    if claimed is not None and not isinstance(claimed, QueueItem):
        raise RuntimeError("demo queue repository returned an invalid claim")
    return claimed


@dataclass(slots=True)
class DemoSession:
    """One demo workspace and its collector."""

    collector: MonitorCollector
    workspace_path: Path
    config_path: Path
    preserved: bool
    initial_view: MonitorView = MonitorView.ALL
    initial_pool_filter: str | None = None
    _temporary: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
            self._temporary = None


class _DemoClock:
    def __init__(self) -> None:
        self.base = datetime.now(timezone.utc)
        self.seconds = 0.0

    def now(self) -> datetime:
        return self.base + timedelta(seconds=self.seconds)

    def timestamp(self) -> str:
        return utc_timestamp(self.now())

    def at(self, seconds: float) -> str:
        return utc_timestamp(self.base + timedelta(seconds=seconds))


@dataclass(frozen=True, slots=True)
class _DemoEventScope:
    stage_name: str | None = None


@dataclass(frozen=True, slots=True)
class _DemoRunEvent:
    event_type: str
    occurred_at: str
    payload: Mapping[str, object]
    scope: _DemoEventScope
    sequence: int


class _DemoRunStore:
    def __init__(self, driver: "_DemoDriver") -> None:
        self._driver = driver

    def read_events(self, run_uri: str) -> tuple[_DemoRunEvent, ...]:
        return self._driver.run_events(run_uri)


class _DemoMonitorCollector(MonitorCollector):
    def __init__(self, driver: "_DemoDriver", *, config_path: Path) -> None:
        run_store = _DemoRunStore(driver)
        self._driver = driver
        super().__init__(
            config_path=config_path,
            service=driver.service,
            workspace_name=f"DEMO · {driver.scenario}",
            clock=driver.now,
            run_inspector=driver.inspect_run,
            jobs_inspector=driver.inspect_jobs,
            logs_inspector=driver.inspect_logs,
            authority_probe=driver.probe_authority,
            run_store=run_store,
        )

    def refresh_queue(self) -> MonitorSnapshot:
        self._driver.advance()
        return super().refresh_queue()


class _DemoDriver:
    """Drive real queue records and simulated external observations."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        scenario: str,
        speed: float,
        seed: int,
        monotonic: Callable[[], float],
    ) -> None:
        self.workspace_path = workspace_path
        self.scenario = scenario
        self.speed = speed
        self.seed = seed
        self._monotonic = monotonic
        self._clock = _DemoClock()
        self._lock = RLock()
        self._random = random.Random(seed)
        self._real_started_at = monotonic()
        self._last_virtual_seconds = 0.0
        self._activated_at: dict[str, float] = {}
        self._completed_outcomes: dict[str, QueueItemStatus] = {}
        self._applied_events: set[str] = set()
        self._run_uris: dict[str, str] = {}
        self._item_ids_by_run: dict[str, str] = {}
        self._scheduler_id = self._random.randint(41000, 89000)
        self._pid = self._random.randint(20000, 50000)

        payload = _demo_queue_payload(workspace_path, scenario=scenario)
        self.service = QueueService.from_spec(
            normalize_queue_spec(payload),
            clock=self._clock.timestamp,
        )
        self.service.start()
        self._seed_queue()
        self._clock.seconds = 0.0
        self._real_started_at = monotonic()

    def now(self) -> datetime:
        with self._lock:
            return self._clock.now()

    def advance(self) -> None:
        with self._lock:
            virtual_seconds = max(
                0.0,
                (self._monotonic() - self._real_started_at) * self.speed,
            )
            if virtual_seconds < self._last_virtual_seconds:
                virtual_seconds = self._last_virtual_seconds
            self._clock.seconds = virtual_seconds
            self._last_virtual_seconds = virtual_seconds
            for at, event_name, action in (
                (14.0, "complete-slurm-train", self._complete_slurm_train),
                (16.0, "complete-live-analysis", self._complete_live_analysis),
                (16.0, "activate-slurm-dependent", self._activate_slurm_dependent),
                (18.0, "activate-waiting-large", self._activate_waiting_large),
                (28.0, "complete-waiting-large", self._complete_waiting_large),
                (30.0, "complete-slurm-dependent", self._complete_slurm_dependent),
                (30.0, "activate-waiting-report", self._activate_waiting_report),
                (38.0, "complete-waiting-report", self._complete_waiting_report),
            ):
                if virtual_seconds >= at and event_name not in self._applied_events:
                    action()
                    self._applied_events.add(event_name)

    def probe_authority(self) -> AuthorityData:
        with self._lock:
            if self.scenario == "failures" and 8 <= self._clock.seconds % 30 < 16:
                raise ConnectionError("demo authority endpoint is temporarily offline")
            return AuthorityData(
                state="READY",
                message=f"simulated authority evidence · seed={self.seed}",
                workspace_id="demo-workspace",
                service_generation="demo-generation",
            )

    def inspect_run(self, run_uri: str, **_: Any) -> RunStatusSummary:
        with self._lock:
            item_id = self._item_id(run_uri)
            item = self.service.read_item(item_id)
            if item is None:
                raise ValueError(f"demo run is unavailable: {run_uri}")
            queue_status = QueueItemStatus(item.status).value
            run_status, stages = self._run_projection(item_id, queue_status)
            submitted = self._submitted_operation(item_id, run_status)
            return RunStatusSummary(
                run_uri=run_uri,
                status=run_status,
                message=_run_message(item_id, run_status),
                artifact_count=3 if run_status == "SUCCEEDED" else 1,
                submitted_operations=() if submitted is None else (submitted,),
                stages=stages,
                state_source=authoritative_service_source(),
            )

    def inspect_jobs(self, run_uri: str, **_: Any) -> SlurmJobsStatusReport:
        with self._lock:
            item_id = self._item_id(run_uri)
            if not item_id.startswith("demo-slurm"):
                raise ValueError("selected demo run has no scheduler submission")
            item = self.service.read_item(item_id)
            if item is None:
                raise ValueError(f"demo run is unavailable: {run_uri}")
            queue_status = QueueItemStatus(item.status).value
            jobs = self._slurm_jobs(item_id, queue_status)
            terminal = queue_status in {
                "SUCCEEDED",
                "FAILED",
                "CANCELLED",
                "UNKNOWN",
            }
            submission_state = queue_status if terminal else "SUBMITTED"
            return SlurmJobsStatusReport(
                run_uri=run_uri,
                run_status=self._run_projection(item_id, queue_status)[0],
                submission={
                    "submission_id": f"demo-submission-{self.seed}",
                    "state": submission_state,
                },
                manifest_path=str(self.workspace_path / "slurm" / "manifest.json"),
                manifest_relative_path="slurm/manifest.json",
                jobs=jobs,
            )

    def inspect_logs(
        self,
        run_uri: str,
        stage_name: str,
        *,
        tail: int,
        paths_only: bool = False,
        **_: Any,
    ) -> StageLogsSummary:
        with self._lock:
            item_id = self._item_id(run_uri)
            item = self.service.read_item(item_id)
            if item is None:
                raise ValueError(f"demo run is unavailable: {run_uri}")
            queue_status = QueueItemStatus(item.status).value
            _run_status, stages = self._run_projection(item_id, queue_status)
            if stage_name not in {stage.stage_name for stage in stages}:
                raise ValueError(f"unknown demo stage: {stage_name}")
            stdout_lines, stderr_lines = self._log_lines(
                item_id,
                stage_name,
                queue_status,
            )
            streams = (
                self._log_stream(
                    item_id,
                    stage_name,
                    "stdout",
                    stdout_lines,
                    tail=tail,
                    paths_only=paths_only,
                ),
                self._log_stream(
                    item_id,
                    stage_name,
                    "stderr",
                    stderr_lines,
                    tail=tail,
                    paths_only=paths_only,
                ),
            )
            return StageLogsSummary(
                run_uri=run_uri,
                stage_name=stage_name,
                streams=streams,
                paths_only=paths_only,
                state_source=local_materialization_source(),
            )

    def run_events(self, run_uri: str) -> tuple[_DemoRunEvent, ...]:
        with self._lock:
            item_id = self._item_id(run_uri)
            item = self.service.read_item(item_id)
            if item is None:
                return ()
            run_status, stages = self._run_projection(
                item_id,
                QueueItemStatus(item.status).value,
            )
            events: list[_DemoRunEvent] = [
                _DemoRunEvent(
                    event_type="run.created",
                    occurred_at=self._clock.at(-20),
                    payload={"status": "PENDING", "message": "demo run created"},
                    scope=_DemoEventScope(),
                    sequence=1,
                )
            ]
            for sequence, stage in enumerate(stages, start=2):
                if stage.status == "PENDING":
                    continue
                stage_status = stage.status or "UNKNOWN"
                events.append(
                    _DemoRunEvent(
                        event_type=f"stage.{stage_status.lower()}",
                        occurred_at=self._clock.at(sequence - 2),
                        payload={
                            "status": stage.status or "UNKNOWN",
                            "message": stage.message or "demo stage observation",
                        },
                        scope=_DemoEventScope(stage.stage_name),
                        sequence=sequence,
                    )
                )
            if run_status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                events.append(
                    _DemoRunEvent(
                        event_type=f"run.{run_status.lower()}",
                        occurred_at=self._clock.at(max(1, self._clock.seconds)),
                        payload={"status": run_status},
                        scope=_DemoEventScope(),
                        sequence=len(events) + 1,
                    )
                )
            return tuple(events)

    def _seed_queue(self) -> None:
        self._clock.seconds = -80
        self._enqueue("demo-prep-success", _LOCAL_QUEUE, adapter="local")
        self._activate("demo-prep-success", _LOCAL_POOL)
        self._complete("demo-prep-success", QueueItemStatus.SUCCEEDED)

        self._step_seed_clock()
        self._enqueue("demo-feature-failed", _LOCAL_QUEUE, adapter="local")
        self._activate("demo-feature-failed", _LOCAL_POOL)
        self._complete("demo-feature-failed", QueueItemStatus.FAILED)

        self._step_seed_clock()
        self._enqueue("demo-cancelled", _LOCAL_QUEUE, adapter="local")
        self.service.cancel_item(
            "demo-cancelled",
            requested_by="demo-operator",
            reason="demonstrate explicit cancellation evidence",
        )

        self._step_seed_clock()
        self._enqueue("demo-recovery-unknown", _LOCAL_QUEUE, adapter="local")
        self._activate("demo-recovery-unknown", _LOCAL_POOL)
        self._complete("demo-recovery-unknown", QueueItemStatus.UNKNOWN)

        self._step_seed_clock()
        self._enqueue("demo-divergent", _LOCAL_QUEUE, adapter="local")
        self._activate("demo-divergent", _LOCAL_POOL)
        self._complete("demo-divergent", QueueItemStatus.SUCCEEDED)

        self._step_seed_clock()
        self._enqueue("demo-live-analysis", _LOCAL_QUEUE, adapter="local")
        self._activate("demo-live-analysis", _LOCAL_POOL, activated_at=0)

        self._step_seed_clock()
        self._enqueue("demo-waiting-large", _LOCAL_QUEUE, adapter="local")
        claimed = _claim_demo_item(
            self.service,
            _LOCAL_POOL,
            owner_id=_OWNER_ID,
            claim_id="claim-demo-waiting-large-deferred",
        )
        if claimed is None or claimed.queue_item_id != "demo-waiting-large":
            raise RuntimeError("demo queue did not claim the deferred item")
        self.service.defer_item(
            "demo-waiting-large",
            reason_code="resource.capacity_unavailable",
            expected=claimed,
        )

        self._step_seed_clock()
        self._enqueue("demo-waiting-report", _LOCAL_QUEUE, adapter="local")

        self._step_seed_clock()
        self._enqueue("demo-slurm-train", _SLURM_QUEUE, adapter="slurm")
        self._activate("demo-slurm-train", _SLURM_POOL, activated_at=0)

        self._step_seed_clock()
        self._enqueue("demo-slurm-dependent", _SLURM_QUEUE, adapter="slurm")

    def _enqueue(self, item_id: str, queue_name: str, *, adapter: str) -> None:
        run_path = self.workspace_path / "runs" / item_id
        run_path.mkdir(parents=True, exist_ok=True)
        run_uri = run_path.as_uri()
        self._run_uris[item_id] = run_uri
        self._item_ids_by_run[run_uri] = item_id
        self.service.enqueue(
            QueueEnqueueRequest(
                queue_item_id=item_id,
                queue_name=queue_name,
                run_uri=run_uri,
                adapter=adapter,
                entrypoint="demo",
                resources={"worker": 2 if item_id == "demo-waiting-large" else 1},
                tags={"scenario": self.scenario, "kind": "demo"},
                metadata={"demo": True, "seed": self.seed},
            )
        )

    def _activate(
        self,
        item_id: str,
        pool_name: str,
        *,
        activated_at: float | None = None,
    ) -> None:
        item = _claim_demo_item(
            self.service,
            pool_name,
            owner_id=_OWNER_ID,
            claim_id=f"claim-{item_id}",
        )
        if item is None or item.queue_item_id != item_id:
            raise RuntimeError(
                f"demo queue claimed an unexpected item before {item_id}"
            )
        adapter = item.launch_contract.adapter
        evidence: Mapping[str, PlainData] = {}
        if adapter == "local":
            evidence = self._managed_local_evidence(item_id)
        handle = DispatchHandle(
            adapter=adapter,
            handle_id=f"{adapter}-{item_id}-{self.seed}",
            dispatched_at=self._clock.timestamp(),
            dispatch_attempt=item.dispatch_attempt,
            evidence=evidence,
        )
        self.service.record_dispatch_handle(item_id, handle, expected=item)
        self._activated_at[item_id] = (
            self._clock.seconds if activated_at is None else activated_at
        )

    def _complete(self, item_id: str, status: QueueItemStatus) -> None:
        item = self.service.read_item(item_id)
        if item is None or item.terminal:
            return
        self.service.complete_item(
            item_id,
            status=status,
            reason=f"demo scenario produced {status.value.lower()}",
            expected=item,
            evidence={"demo": True, "scenario": self.scenario},
        )
        self._completed_outcomes[item_id] = status

    def _complete_slurm_train(self) -> None:
        outcome = (
            QueueItemStatus.FAILED
            if self.scenario == "failures"
            else QueueItemStatus.SUCCEEDED
        )
        self._complete("demo-slurm-train", outcome)

    def _complete_live_analysis(self) -> None:
        outcome = (
            QueueItemStatus.FAILED
            if self.scenario == "failures"
            else QueueItemStatus.SUCCEEDED
        )
        self._complete("demo-live-analysis", outcome)

    def _activate_slurm_dependent(self) -> None:
        self._activate("demo-slurm-dependent", _SLURM_POOL)

    def _activate_waiting_large(self) -> None:
        self._activate("demo-waiting-large", _LOCAL_POOL)

    def _complete_waiting_large(self) -> None:
        self._complete("demo-waiting-large", QueueItemStatus.SUCCEEDED)

    def _complete_slurm_dependent(self) -> None:
        self._complete("demo-slurm-dependent", QueueItemStatus.SUCCEEDED)

    def _activate_waiting_report(self) -> None:
        self._activate("demo-waiting-report", _LOCAL_POOL)

    def _complete_waiting_report(self) -> None:
        self._complete("demo-waiting-report", QueueItemStatus.SUCCEEDED)

    def _run_projection(
        self,
        item_id: str,
        queue_status: str,
    ) -> tuple[str | None, tuple[StageStatusSummary, ...]]:
        names = (
            ("fetch", "train", "report")
            if item_id.startswith("demo-slurm")
            else ("prepare", "execute", "publish")
        )
        log_paths = {
            name: {
                "stdout": str(self._log_path(item_id, name, "stdout")),
                "stderr": str(self._log_path(item_id, name, "stderr")),
            }
            for name in names
        }
        if item_id == "demo-divergent":
            statuses = ("SUCCEEDED", "RUNNING", "PENDING")
            run_status: str | None = "RUNNING"
        elif queue_status == "FAILED":
            statuses = ("SUCCEEDED", "FAILED", "BLOCKED")
            run_status = "FAILED"
        elif queue_status == "CANCELLED":
            statuses = ("CANCELLED", "SKIPPED", "SKIPPED")
            run_status = "CANCELLED"
        elif queue_status == "UNKNOWN":
            statuses = ("SUCCEEDED", "RUNNING", "PENDING")
            run_status = "RUNNING"
        elif queue_status == "SUCCEEDED":
            statuses = ("SUCCEEDED", "SUCCEEDED", "SUCCEEDED")
            run_status = "SUCCEEDED"
        elif queue_status in {"CLAIMED", "DISPATCHED"}:
            elapsed = self._elapsed_for(item_id)
            if elapsed < 4:
                statuses = ("RUNNING", "PENDING", "PENDING")
            elif elapsed < 10:
                statuses = ("SUCCEEDED", "RUNNING", "PENDING")
            else:
                statuses = ("SUCCEEDED", "SUCCEEDED", "RUNNING")
            run_status = "RUNNING"
        else:
            statuses = ("PENDING", "PENDING", "PENDING")
            run_status = None
        stages = tuple(
            StageStatusSummary(
                stage_name=name,
                status=status,
                attempt=1 if status != "PENDING" else None,
                message=_stage_message(name, status),
                failure=(
                    {
                        "reason": "demonstration failure",
                        "error": "mock worker exited with status 17",
                    }
                    if status == "FAILED"
                    else None
                ),
                input_count=index,
                output_count=index if status == "SUCCEEDED" else 0,
                provenance_available=status == "SUCCEEDED",
                log_paths=log_paths[name],
                log_available={
                    "stdout": status != "PENDING",
                    "stderr": status == "FAILED",
                },
                state_source=authoritative_service_source(),
                log_source=local_materialization_source(),
            )
            for index, (name, status) in enumerate(zip(names, statuses, strict=True), 1)
        )
        return run_status, stages

    def _submitted_operation(
        self,
        item_id: str,
        run_status: str | None,
    ) -> SubmittedOperationSummary | None:
        if not item_id.startswith("demo-slurm"):
            return None
        active = run_status not in {"SUCCEEDED", "FAILED", "CANCELLED"}
        state = "SUBMITTED" if active else run_status or "UNKNOWN"
        return SubmittedOperationSummary(
            submission_id=f"demo-submission-{self.seed}",
            backend="slurm",
            mode="afterok",
            state=state,
            created_at=self._clock.at(-10),
            updated_at=self._clock.timestamp(),
            manifest_relative_path="slurm/manifest.json",
            summary_counts={"jobs": 3},
            active=active,
            state_source=authoritative_service_source(),
        )

    def _slurm_jobs(
        self,
        item_id: str,
        queue_status: str,
    ) -> tuple[SlurmJobStatusSummary, ...]:
        elapsed = self._elapsed_for(item_id)
        failed = queue_status == "FAILED"
        terminal = queue_status in {"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"}
        if failed:
            states = ("COMPLETED", "FAILED", "CANCELLED")
        elif terminal:
            states = ("COMPLETED", "COMPLETED", "COMPLETED")
        elif elapsed < 4:
            states = ("RUNNING", "PENDING", "PENDING")
        elif elapsed < 10:
            states = ("COMPLETED", "RUNNING", "PENDING")
        else:
            states = ("COMPLETED", "COMPLETED", "RUNNING")
        names = ("fetch", "train", "report")
        jobs: list[SlurmJobStatusSummary] = []
        for index, (name, state) in enumerate(zip(names, states, strict=True)):
            dependency = None
            dependency_ids: tuple[str, ...] = ()
            if state == "PENDING" and index:
                dependency = "Dependency"
                dependency_ids = (str(self._scheduler_id + index - 1),)
            jobs.append(
                SlurmJobStatusSummary(
                    logical_key=f"stage:{name}",
                    scheduler_job_id=str(self._scheduler_id + index),
                    status=state,
                    source="demo-squeue" if not terminal else "demo-sacct",
                    scheduler_state=state,
                    loom_run_status=(
                        "FAILED" if failed else "SUCCEEDED" if terminal else "RUNNING"
                    ),
                    loom_stage_status=state,
                    stage_name=name,
                    exit_code="17:0"
                    if state == "FAILED"
                    else "0:0"
                    if terminal
                    else None,
                    dependency_state=dependency,
                    dependency_job_ids=dependency_ids,
                    log_paths={
                        "stdout": str(self._log_path(item_id, name, "stdout")),
                        "stderr": str(self._log_path(item_id, name, "stderr")),
                    },
                )
            )
        return tuple(jobs)

    def _log_lines(
        self,
        item_id: str,
        stage_name: str,
        queue_status: str,
    ) -> tuple[list[str], list[str]]:
        _, stages = self._run_projection(item_id, queue_status)
        stage = next(stage for stage in stages if stage.stage_name == stage_name)
        if stage.status == "PENDING":
            return [], []
        stdout = [
            f"[{item_id}] stage={stage_name} scenario={self.scenario}",
            f"seed={self.seed} queue_status={queue_status}",
        ]
        if stage.status in {"RUNNING", "SUCCEEDED"}:
            progress = (
                10
                if stage.status == "SUCCEEDED"
                else min(
                    9,
                    max(1, int(self._elapsed_for(item_id)) + 1),
                )
            )
            stdout.extend(f"progress {step}/10" for step in range(1, progress + 1))
        if stage.status == "SUCCEEDED":
            stdout.append("stage completed successfully")
        stderr = (
            ["mock worker error: demonstration failure", "exit status: 17"]
            if stage.status == "FAILED"
            else []
        )
        return stdout, stderr

    def _log_stream(
        self,
        item_id: str,
        stage_name: str,
        stream: str,
        lines: list[str],
        *,
        tail: int,
        paths_only: bool,
    ) -> LogStreamSummary:
        path = self._log_path(item_id, stage_name, stream)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(lines)
        if content:
            content += "\n"
        path.write_text(content, encoding="utf-8")
        displayed = lines[-tail:]
        displayed_content = "\n".join(displayed)
        if displayed_content:
            displayed_content += "\n"
        return LogStreamSummary(
            stream=stream,
            path=str(path),
            available=bool(lines),
            content=None if paths_only or not lines else displayed_content,
            line_count=len(lines),
            displayed_line_count=min(len(lines), tail),
            truncated=len(lines) > tail,
            state_source=local_materialization_source(),
        )

    def _managed_local_evidence(self, item_id: str) -> Mapping[str, PlainData]:
        suffix = item_id.removeprefix("demo-")
        return {
            "managed_local": {
                "schema_version": 1,
                "owner_id": _OWNER_ID,
                "session_id": _SESSION_ID,
                "pid": self._pid,
                "pgid": self._pid,
                "assignment": {
                    "provider_name": "demo-slots",
                    "slots": [
                        {
                            "resource_name": "worker",
                            "slot_id": f"slot-{self._pid % 4}",
                            "lease_id": f"lease-{suffix}",
                            "expires_at": self._clock.at(120),
                            "label": f"demo-worker-{self._pid % 4}",
                        }
                    ],
                },
                "logs": {
                    "stdout_path": f"logs/{item_id}.stdout.log",
                    "stderr_path": f"logs/{item_id}.stderr.log",
                },
            }
        }

    def _elapsed_for(self, item_id: str) -> float:
        activated_at = self._activated_at.get(item_id)
        if activated_at is None:
            return 0.0
        return max(0.0, self._clock.seconds - activated_at)

    def _log_path(self, item_id: str, stage_name: str, stream: str) -> Path:
        return self.workspace_path / "logs" / item_id / f"{stage_name}.{stream}.log"

    def _item_id(self, run_uri: str) -> str:
        try:
            return self._item_ids_by_run[run_uri]
        except KeyError as exc:
            raise ValueError(f"unknown demo run: {run_uri}") from exc

    def _step_seed_clock(self) -> None:
        self._clock.seconds += 8


def create_demo_session(
    *,
    scenario: str = "mixed",
    speed: float = 1.0,
    seed: int = 42,
    output_root: str | Path | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> DemoSession:
    """Create one isolated demo queue and its monitor collector."""

    if scenario not in DEMO_SCENARIOS:
        raise ValueError(
            f"unknown demo scenario {scenario!r}; choose from {', '.join(DEMO_SCENARIOS)}"
        )
    if speed <= 0:
        raise ValueError("demo speed must be greater than zero")
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if output_root is None:
        temporary = tempfile.TemporaryDirectory(prefix="loom-monitor-demo-")
        workspace_path = Path(temporary.name)
        preserved = False
    else:
        parent = Path(output_root).expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        workspace_path = Path(tempfile.mkdtemp(prefix="demo-", dir=parent))
        preserved = True
    try:
        config_path = workspace_path / "queue.yaml"
        payload = _demo_queue_payload(workspace_path, scenario=scenario)
        config_path.write_text(
            json.dumps({"queue": payload}, indent=2) + "\n",
            encoding="utf-8",
        )
        driver = _DemoDriver(
            workspace_path,
            scenario=scenario,
            speed=speed,
            seed=seed,
            monotonic=monotonic,
        )
        collector = _DemoMonitorCollector(driver, config_path=config_path)
        return DemoSession(
            collector=collector,
            workspace_path=workspace_path,
            config_path=config_path,
            preserved=preserved,
            initial_view=MonitorView.ALL,
            initial_pool_filter=_SLURM_POOL if scenario == "scheduler" else None,
            _temporary=temporary,
        )
    except Exception:
        if temporary is not None:
            temporary.cleanup()
        raise


def _demo_queue_payload(workspace_path: Path, *, scenario: str) -> dict[str, object]:
    return {
        "schema_version": 2,
        "service": {"db_path": str(workspace_path / "queue.sqlite")},
        "controller": {
            "owner_id": _OWNER_ID,
            "default_pool_name": _LOCAL_POOL,
            "max_active_items": 3,
        },
        "pools": [
            {"pool_name": _LOCAL_POOL, "mode": "managed"},
            {
                "pool_name": _SLURM_POOL,
                "mode": "delegated",
                "metadata": {"workspace_assumptions_acknowledged": True},
            },
        ],
        "queues": [
            {"queue_name": _LOCAL_QUEUE, "pool_name": _LOCAL_POOL},
            {"queue_name": _SLURM_QUEUE, "pool_name": _SLURM_POOL},
        ],
        "metadata": {
            "workspace": f"DEMO · {scenario}",
            "demo": True,
        },
    }


def _run_message(item_id: str, status: str | None) -> str:
    if item_id == "demo-divergent":
        return "authority still reports work after queue completion"
    if status == "FAILED":
        return "mock worker failed intentionally"
    if status == "RUNNING":
        return "deterministic demo work is progressing"
    if status == "SUCCEEDED":
        return "demo run completed"
    if status == "CANCELLED":
        return "demo operator cancelled this run"
    return "waiting for demo capacity"


def _stage_message(stage_name: str, status: str) -> str:
    messages = {
        "RUNNING": f"{stage_name} is emitting deterministic progress",
        "SUCCEEDED": f"{stage_name} completed",
        "FAILED": f"{stage_name} failed intentionally",
        "BLOCKED": f"{stage_name} blocked by an upstream failure",
        "CANCELLED": f"{stage_name} was cancelled",
        "SKIPPED": f"{stage_name} was skipped",
        "PENDING": f"{stage_name} is waiting",
    }
    return messages[status]


__all__ = ["DEMO_SCENARIOS", "DemoSession", "create_demo_session"]

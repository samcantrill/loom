"""Bounded process-local observations of coordinator waits, independent of authority."""
from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import monotonic_ns
from typing import TYPE_CHECKING

from loom.serialization import PlainData
from ._phase_timing import milestone

if TYPE_CHECKING:
    from loom.pipeline.orchestration import StageWorkRecord
    from ._context_timing import ContextTiming


@dataclass(frozen=True, slots=True)
class _Wait:
    boundary: str
    since: str
    start_ns: int


@dataclass(slots=True)
class _Prequeue:
    ready_ns: int
    since_ns: int
    reason: str
    queued_ns: int | None = None
    totals: dict[str, int] = field(default_factory=dict)

    def wait(self, reason: str, now: int) -> None:
        if self.queued_ns is None and self.reason != reason:
            self.totals[self.reason] = self.totals.get(self.reason, 0) + now - self.since_ns
            self.reason, self.since_ns = reason, now

    def queued(self, stamp: int) -> None:
        if self.queued_ns is None:
            # A reopened projection can reuse a request queued during an earlier
            # reservation. Its preparation time belongs only to that earlier cycle.
            if stamp >= self.since_ns:
                self.wait("queued", stamp)
            self.queued_ns = stamp

    def summary(self, outcome: str) -> dict[str, PlainData]:
        waits: dict[str, PlainData] | None = None
        if self.queued_ns is None:
            status = "inapplicable" if outcome in {"left_ready", "superseded"} else "missing"
        elif self.queued_ns < self.ready_ns:
            status = "reused"
        elif self.reason == "queued":
            waits = dict(self.totals)
            status = "observed"
        else:
            status = "missing"
        return {"prequeue_status": status, "prequeue_wait_ns": waits,
                "prequeue_ready_ns": self.ready_ns, "prequeue_queued_ns": self.queued_ns}


@dataclass(slots=True)
class _Attempt:
    work_id: str
    projection_revision: int
    ready_revision: int
    attempt_id: str
    admission_id: str
    boundary: str
    since_ns: int
    prequeue: _Prequeue
    ready_at: int
    totals: dict[str, int] = field(default_factory=dict)
    offer: str | None = None
    confirmed_ns: int = 0
    expires_ns: int = 0
    eligible_request_ready_ns: int = 0
    saw_eligible_offer: bool = False
    stage_context: dict[str, PlainData] = field(default_factory=dict)

    def transition(self, reason: str, now: int) -> None:
        if self.boundary != reason:
            self.totals[self.boundary] = self.totals.get(self.boundary, 0) + now - self.since_ns
            self.boundary, self.since_ns = reason, now

    def confirm(self, offer: str, expires: int, available: int | None, now: int) -> None:
        # Only count between two observations of the same still-live offer.
        # A new offer cannot establish when the previous offer stopped being usable.
        if self.offer == offer and available is not None:
            start = max(available, self.confirmed_ns)
            overlap = max(0, min(now, self.expires_ns, expires) - start)
            self.eligible_request_ready_ns += overlap
            if overlap:
                self.saw_eligible_offer = True
        self.offer = offer if expires > now else None
        self.confirmed_ns, self.expires_ns = now, expires
        if self.offer is not None and available is not None and available <= now:
            self.saw_eligible_offer = True


class SchedulingWaits:
    """Keep current waits and bounded per-attempt summaries after reservation."""

    _limit = 288

    def __init__(self) -> None:
        self._waits: OrderedDict[tuple[str, str | None], _Wait] = OrderedDict()
        self._attempts: OrderedDict[tuple[str, str], _Attempt] = OrderedDict()
        self._finished: OrderedDict[tuple[str, int], dict[str, PlainData]] = OrderedDict()
        self._epochs: tuple[str | None, str | None] | None = None
        self._lock = Lock()

    def ready(self, record: StageWorkRecord, *, scanned: bool = False) -> None:
        key = record.run_uri, record.stage_name
        with self._lock:
            previous = self._attempts.get(key)
            if previous is not None and previous.work_id == record.stage_work_id:
                if record.projection_revision < previous.ready_revision:
                    return
                previous.projection_revision = max(previous.projection_revision, record.projection_revision)
                if scanned and "first_scan_ns" not in previous.stage_context:
                    now = monotonic_ns()
                    previous.stage_context["first_scan_ns"] = now
                    if previous.prequeue.reason == "first_scan":
                        previous.prequeue.wait("unknown", now)
                return
            if (record.stage_work_id, record.projection_revision) in self._finished:
                return
            if previous is not None:
                self._finish(key, "superseded", None)
            now = monotonic_ns()
            self._attempts[key] = _Attempt(record.stage_work_id, record.projection_revision,
                                           record.projection_revision, record.attempt_id,
                                           record.admission_id, "capacity_unknown", now,
                                           _Prequeue(now, now, "unknown" if scanned else "first_scan"), record.ready_at,
                                           stage_context={"first_scan_ns": now} if scanned else {})
            if len(self._attempts) > self._limit:
                self._finish(next(iter(self._attempts)), "observation_evicted", None)
        milestone("attempt_ready", stage_work_id=record.stage_work_id, attempt_id=record.attempt_id,
                  admission_id=record.admission_id, run_uri=record.run_uri, stage_name=record.stage_name,
                  ready_at=record.ready_at, projection_revision=record.projection_revision)

    def _current_attempt(self, record: StageWorkRecord) -> _Attempt | None:
        attempt = self._attempts.get((record.run_uri, record.stage_name))
        if (attempt is not None and attempt.work_id == record.stage_work_id
            and record.projection_revision >= attempt.ready_revision):
            return attempt
        return None

    def context_demand(self, record: StageWorkRecord, kind: str, timing: ContextTiming | None) -> None:
        with self._lock:
            attempt = self._current_attempt(record)
            if attempt is None or "demand_ns" in attempt.stage_context:
                return
            fields = attempt.stage_context
            now = monotonic_ns()
            fields.update(demand_ns=now, demand_kind=kind, demand_load=timing.identity() if timing else None)
            if "interest_ns" not in fields:
                fields.update(interest_ns=now, interest_kind=kind)

    def context_visit(self, record: StageWorkRecord, timing: ContextTiming | None) -> None:
        with self._lock:
            attempt = self._current_attempt(record)
            if attempt is None:
                return
            fields = attempt.stage_context
            demand = fields.get("demand_load")
            if (timing and isinstance(demand, dict) and "demand_visit_ns" not in fields
                and demand["context_request_id"] == timing.request_id):
                fields.update(demand_installed_ns=timing.installed_ns, demand_visit_ns=monotonic_ns())
            if "visit_ns" in fields:
                return
            now = monotonic_ns()
            if "interest_ns" not in fields:
                fields.update(interest_ns=now, interest_kind="reused")
            fields.update(visit_ns=now, used_load=timing.identity() if timing else None,
                          installed_ns=timing.installed_ns if timing else None)

    def context_progress(self, record: StageWorkRecord, timing: ContextTiming | None,
                         kind: str, stamp: int | None = None) -> None:
        with self._lock:
            attempt = self._current_attempt(record)
            if attempt is None or "progress_ns" in attempt.stage_context:
                return
            now = monotonic_ns() if stamp is None else stamp
            if now < attempt.prequeue.ready_ns or (timing and timing.installed_ns and now < timing.installed_ns):
                return  # A carried request belongs to its earlier context or READY cycle.
            attempt.stage_context.update(progress_ns=now, progress_kind=kind,
                                         progress_load=timing.identity() if timing else None,
                                         progress_installed_ns=timing.installed_ns if timing else None)

    def prequeue(self, record: StageWorkRecord, reason: str) -> None:
        with self._lock:
            attempt = self._attempts.get((record.run_uri, record.stage_name))
            if (attempt is not None and attempt.work_id == record.stage_work_id
                and record.projection_revision >= attempt.ready_revision
                and attempt.prequeue.queued_ns is None and reason != attempt.prequeue.reason):
                attempt.prequeue.wait(reason, monotonic_ns())

    def queued(self, record: StageWorkRecord, stamp: int) -> None:
        with self._lock:
            attempt = self._attempts.get((record.run_uri, record.stage_name))
            if (attempt is not None and attempt.work_id == record.stage_work_id
                and record.projection_revision >= attempt.ready_revision):
                attempt.prequeue.queued(stamp)

    def eligible(self, record: StageWorkRecord, offer: str, expires: int, available: int | None) -> None:
        with self._lock:
            attempt = self._attempts.get((record.run_uri, record.stage_name))
            if attempt is None or attempt.work_id != record.stage_work_id:
                return
            now = monotonic_ns()
            first = attempt.offer != offer or now >= attempt.expires_ns
            attempt.confirm(offer, expires, available, now)
        if first and expires > now:
            milestone("eligible_offer_observed", stage_work_id=record.stage_work_id, attempt_id=record.attempt_id,
                      admission_id=record.admission_id, offer_id=offer)

    def capacity(self, record: StageWorkRecord, reason: str) -> None:
        with self._lock:
            attempt = self._attempts.get((record.run_uri, record.stage_name))
            if attempt is not None and attempt.work_id == record.stage_work_id:
                attempt.offer = None
                attempt.transition(reason, monotonic_ns())

    def current_offers(self, offers: set[str], epochs: tuple[str | None, str | None]) -> None:
        """An offer or scheduling-policy change ends the previous observation."""
        with self._lock:
            changed = self._epochs is not None and epochs != self._epochs
            self._epochs = epochs
            for attempt in self._attempts.values():
                if changed or (attempt.offer is not None and attempt.offer not in offers):
                    attempt.offer = None

    def reserved(self, record: StageWorkRecord, assignment: str, offer: str | None,
                 available: int | None) -> None:
        key = record.run_uri, record.stage_name
        ready_revision = None
        with self._lock:
            attempt = self._attempts.get(key)
            if attempt is not None and attempt.work_id == record.stage_work_id:
                ready_revision = attempt.ready_revision
                if offer is not None and attempt.offer == offer:
                    attempt.confirm(offer, attempt.expires_ns, available, monotonic_ns())
                self._finish(key, "reserved", assignment, available=available)
            if offer is not None:
                # A committed claim consumes this capacity observation for all peers.
                for peer in self._attempts.values():
                    if peer.offer == offer:
                        peer.offer = None
        milestone("reservation_committed", stage_work_id=record.stage_work_id, attempt_id=record.attempt_id,
                  admission_id=record.admission_id, run_uri=record.run_uri, stage_name=record.stage_name,
                  assignment_id=assignment, offer_id=offer, projection_revision=record.projection_revision,
                  ready_projection_revision=ready_revision, request_available_ns=available)

    def _finish(self, key: tuple[str, str], outcome: str, assignment: str | None, *, available: int | None = None) -> None:
        attempt = self._attempts.pop(key)
        attempt.transition("finished", monotonic_ns())
        summary: dict[str, PlainData] = {
            "stage_work_id": attempt.work_id, "attempt_id": attempt.attempt_id,
            "projection_revision": attempt.projection_revision,
            "ready_projection_revision": attempt.ready_revision, "request_available_ns": available,
            "admission_id": attempt.admission_id, "assignment_id": assignment,
            "run_uri": key[0], "stage_name": key[1], "result": outcome,
            "eligible_request_ready_ns": attempt.eligible_request_ready_ns,
            "saw_eligible_offer": attempt.saw_eligible_offer, "wait_ns": dict(attempt.totals),
            "stage_context": attempt.stage_context, **attempt.prequeue.summary(outcome),
        }
        identity = (attempt.work_id, attempt.projection_revision)
        self._finished[identity] = summary
        self._finished.move_to_end(identity)
        if len(self._finished) > self._limit:
            self._finished.popitem(last=False)
        milestone("attempt_scheduling_summary", details=summary)

    def record(self, run_uri: str, stage_name: str | None, boundary: str) -> None:
        key = run_uri, stage_name
        with self._lock:
            now = monotonic_ns()
            wait = self._waits.get(key)
            if wait is None or wait.boundary != boundary:
                self._waits[key] = _Wait(boundary, datetime.now(timezone.utc).isoformat(), now)
            if stage_name is not None and boundary != "host_eligibility":
                attempt = self._attempts.get((run_uri, stage_name))
                if attempt is not None:
                    attempt.transition(boundary, now)
            self._waits.move_to_end(key)
            if len(self._waits) > self._limit:
                self._waits.popitem(last=False)

    def clear(self, run_uri: str, stage_name: str | None) -> None:
        with self._lock:
            self._waits.pop((run_uri, stage_name), None)

    def retain(self, run_uri: str, eligible: set[str]) -> None:
        with self._lock:
            for key in tuple(self._waits):
                if key[0] == run_uri and key[1] not in eligible:
                    del self._waits[key]
            for attempt_key in tuple(self._attempts):
                if attempt_key[0] == run_uri and attempt_key[1] not in eligible:
                    self._finish(attempt_key, "left_ready", None)

    def waiting_reasons(self, admission_ids: set[str]) -> dict[str, str]:
        """Summarize bounded stage observations for a queue page without run-store IO."""
        labels = {
            "snapshot_unavailable": "awaiting authority snapshot",
            "context_unavailable": "loading admission context",
            "capacity_unknown": "awaiting capacity observation",
            "request_preparation": "preparing worker request",
            "input_descriptors": "inspecting worker inputs",
            "attempt_preparation_error": "worker request or input preparation failed",
            "no_eligible_offer": "no eligible offer observed",
            "assignment_slots_full": "assignment slots full",
            "run_parallel_limit": "run parallelism limit",
            "unknown": "awaiting scheduling decision",
            "first_scan": "awaiting first placement scan",
        }
        groups: dict[str, list[tuple[int, str, str]]] = {}
        with self._lock:
            for (_, stage), item in self._attempts.items():
                if item.admission_id not in admission_ids:
                    continue
                reason = item.boundary
                if item.prequeue.queued_ns is None and item.prequeue.reason not in {"unknown", "queued"}:
                    reason = item.prequeue.reason
                groups.setdefault(item.admission_id, []).append(
                    (item.ready_at, stage, labels.get(reason, reason.replace("_", " ")))
                )
        result = {}
        for identity, stages in groups.items():
            _, stage, reason = min(stages)
            summary = f"{stage}: {reason}"
            if len(stages) > 1:
                counts = Counter(label for _, _, label in stages)
                summary += " (" + ", ".join(f"{n} {label}" for label, n in sorted(counts.items())) + ")"
            result[identity] = summary
        return result

    def summaries(self, run_uri: str) -> list[PlainData]:
        with self._lock:
            return [dict(row) for row in self._finished.values() if row["run_uri"] == run_uri]

    def observed(self, run_uri: str) -> list[PlainData]:
        with self._lock:
            now = monotonic_ns()
            return [{"stage": stage, "boundary": wait.boundary, "since": wait.since,
                     "elapsed_nanoseconds": now - wait.start_ns}
                    for (uri, stage), wait in self._waits.items() if uri == run_uri]

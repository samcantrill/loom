"""Bounded process-local observations of coordinator waits, independent of authority."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import monotonic_ns
from typing import TYPE_CHECKING

from loom.serialization import PlainData
from ._phase_timing import milestone

if TYPE_CHECKING:
    from loom.pipeline.orchestration import StageWorkRecord


@dataclass(frozen=True, slots=True)
class _Wait:
    boundary: str
    since: str
    start_ns: int


@dataclass(slots=True)
class _Attempt:
    work_id: str
    attempt_id: str
    admission_id: str
    boundary: str
    since_ns: int
    totals: dict[str, int] = field(default_factory=dict)
    offer: str | None = None
    confirmed_ns: int = 0
    expires_ns: int = 0
    eligible_request_ready_ns: int = 0
    saw_eligible_offer: bool = False

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
        self._finished: OrderedDict[str, dict[str, PlainData]] = OrderedDict()
        self._epochs: tuple[str | None, str | None] | None = None
        self._lock = Lock()

    def ready(self, record: StageWorkRecord) -> None:
        key = record.run_uri, record.stage_name
        with self._lock:
            previous = self._attempts.get(key)
            if previous is not None and previous.work_id == record.stage_work_id:
                return
            if record.stage_work_id in self._finished:
                return
            if previous is not None:
                self._finish(key, "superseded", None)
            self._attempts[key] = _Attempt(record.stage_work_id, record.attempt_id,
                                           record.admission_id, "capacity_unknown", monotonic_ns())
            if len(self._attempts) > self._limit:
                self._finish(next(iter(self._attempts)), "observation_evicted", None)
        milestone("attempt_ready", stage_work_id=record.stage_work_id, attempt_id=record.attempt_id,
                  admission_id=record.admission_id, run_uri=record.run_uri, stage_name=record.stage_name,
                  ready_at=record.ready_at)

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
        with self._lock:
            attempt = self._attempts.get(key)
            if attempt is not None and attempt.work_id == record.stage_work_id:
                if offer is not None and attempt.offer == offer:
                    attempt.confirm(offer, attempt.expires_ns, available, monotonic_ns())
                self._finish(key, "reserved", assignment)
            if offer is not None:
                # A committed claim consumes this capacity observation for all peers.
                for peer in self._attempts.values():
                    if peer.offer == offer:
                        peer.offer = None
        milestone("reservation_committed", stage_work_id=record.stage_work_id, attempt_id=record.attempt_id,
                  admission_id=record.admission_id, run_uri=record.run_uri, stage_name=record.stage_name,
                  assignment_id=assignment, offer_id=offer)

    def _finish(self, key: tuple[str, str], outcome: str, assignment: str | None) -> None:
        attempt = self._attempts.pop(key)
        attempt.transition("finished", monotonic_ns())
        summary: dict[str, PlainData] = {
            "stage_work_id": attempt.work_id, "attempt_id": attempt.attempt_id,
            "admission_id": attempt.admission_id, "assignment_id": assignment,
            "run_uri": key[0], "stage_name": key[1], "result": outcome,
            "eligible_request_ready_ns": attempt.eligible_request_ready_ns,
            "saw_eligible_offer": attempt.saw_eligible_offer, "wait_ns": dict(attempt.totals),
        }
        self._finished[attempt.work_id] = summary
        self._finished.move_to_end(attempt.work_id)
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

    def summaries(self, run_uri: str) -> list[PlainData]:
        with self._lock:
            return [dict(row) for row in self._finished.values() if row["run_uri"] == run_uri]

    def observed(self, run_uri: str) -> list[PlainData]:
        with self._lock:
            now = monotonic_ns()
            return [{"stage": stage, "boundary": wait.boundary, "since": wait.since,
                     "elapsed_nanoseconds": now - wait.start_ns}
                    for (uri, stage), wait in self._waits.items() if uri == run_uri]

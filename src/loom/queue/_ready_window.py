"""Fair bounded traversal of ready work across scheduler turns."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from time import monotonic
from typing import TYPE_CHECKING, Protocol

from loom.pipeline.orchestration import READY_WINDOW_LIMIT

from ._admission_scan import SchedulingAdmissions

if TYPE_CHECKING:
    from loom.pipeline.orchestration import StageWorkRecord

    from ._coordinator_run_progress import LocalDaemonExecutionOutcome
    from .local_daemon import LocalDaemonAdmission


class ReadyWindowReader(Protocol):
    def __call__(
        self, *, after: StageWorkRecord | None, rotate_after: int | None,
        ready_through: int, enqueue_through: int, gpu_heads_only: bool = False,
    ) -> tuple[StageWorkRecord, ...]: ...


type Selection = tuple[str, LocalDaemonExecutionOutcome]
type OfferWindow = Callable[[tuple[StageWorkRecord, ...]], Selection | None]


class ScanYield(Enum):
    MORE = "more"


class ReadyWindowScheduler:
    """Own the two cursors. The caller retains the final reservation decision."""

    def __init__(self, read: ReadyWindowReader, clock: Callable[[], int], wake: Callable[[], None]) -> None:
        self.read = read
        self.clock = clock
        self.wake = wake
        self._ready_scan_after: StageWorkRecord | None = None
        self._ready_scan_boundary: tuple[int, int] | None = None
        self._last_dispatch_enqueue: int | None = None
        self._prefer_gpu_dispatch = True
        self._resume_ordinary = False
        self._gpu_scan_after: StageWorkRecord | None = None
        self._gpu_scan_boundary: tuple[int, int] | None = None
        self._last_gpu_dispatch_enqueue: int | None = None

    def select(
        self, admissions: Mapping[str, LocalDaemonAdmission], offer: OfferWindow, *, deadline: float | None = None,
    ) -> Selection | ScanYield | None:
        if not admissions and not (isinstance(admissions, SchedulingAdmissions) and admissions.enqueue_through):
            self._ready_scan_after = self._ready_scan_boundary = None
            self._gpu_scan_after = self._gpu_scan_boundary = None
            self._resume_ordinary = False
            return None
        if self._ready_scan_boundary is None:
            high_water = (admissions.enqueue_through if isinstance(admissions, SchedulingAdmissions)
                          else max(row.enqueue_sequence for row in admissions.values()))
            self._ready_scan_boundary = (self.clock(), high_water)
        if self._prefer_gpu_dispatch and not self._resume_ordinary:
            outcome = self._gpu_opportunity(admissions, offer, self._ready_scan_boundary)
            if outcome is not None:
                self._ready_scan_after = self._ready_scan_boundary = None
                self._last_dispatch_enqueue = admissions[outcome[0]].enqueue_sequence
                self._prefer_gpu_dispatch = False
                return outcome
            if deadline is not None and monotonic() >= deadline:
                self._resume_ordinary = True
                self.wake()
                return ScanYield.MORE
        self._resume_ordinary = False
        for _ in range(4):
            page = self.read(
                after=self._ready_scan_after, rotate_after=self._last_dispatch_enqueue,
                ready_through=self._ready_scan_boundary[0], enqueue_through=self._ready_scan_boundary[1],
            )
            outcome = offer(page) if page else None
            if outcome is not None:
                self._ready_scan_after = self._ready_scan_boundary = None
                self._last_dispatch_enqueue = admissions[outcome[0]].enqueue_sequence
                self._prefer_gpu_dispatch = not self._prefer_gpu_dispatch
                return outcome
            if len(page) < READY_WINDOW_LIMIT:
                self._ready_scan_after = self._ready_scan_boundary = None
                return None
            self._ready_scan_after = page[-1]
            if deadline is not None and monotonic() >= deadline:
                break
        self.wake()
        return ScanYield.MORE

    def _gpu_opportunity(
        self, admissions: Mapping[str, LocalDaemonAdmission], offer: OfferWindow, boundary: tuple[int, int],
    ) -> Selection | None:
        if self._gpu_scan_boundary is None:
            self._gpu_scan_boundary = boundary
        page = self.read(
            after=self._gpu_scan_after, rotate_after=self._last_gpu_dispatch_enqueue,
            ready_through=self._gpu_scan_boundary[0], enqueue_through=self._gpu_scan_boundary[1],
            gpu_heads_only=True,
        )
        outcome = offer(page) if page else None
        if outcome is not None:
            self._last_gpu_dispatch_enqueue = admissions[outcome[0]].enqueue_sequence
        if outcome is not None or len(page) < READY_WINDOW_LIMIT:
            self._gpu_scan_after = self._gpu_scan_boundary = None
        else:
            self._gpu_scan_after = page[-1]
        return outcome

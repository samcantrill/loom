"""Host GPU observations collected outside the coordinator's scheduling turn."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from ._managed_local import AgentResourceProvider, GpuResourceProvider
from ._phase_timing import reported_phases
from .gpu.occupancy import GpuOccupancyMonitor, GpuOccupancySnapshot, _sample_gpu_occupancy


@dataclass(frozen=True)
class _Sample:
    provider: GpuResourceProvider
    monitor: GpuOccupancyMonitor
    revision: int
    future: Future[GpuOccupancySnapshot]


def _observe(monitor: GpuOccupancyMonitor) -> GpuOccupancySnapshot:
    with reported_phases("coordinator_gpu_occupancy"):
        return _sample_gpu_occupancy(monitor._observer, monitor.selected_uuids,
                                     monitor._utc_clock, monitor._monotonic_clock)


class CoordinatorGpuSamples:
    """One external probe at a time. Only the scheduling owner installs the result."""

    def __init__(self, wake: Callable[[], None]) -> None:
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="loom-coordinator-gpu")
        self._wake = wake
        self._pending: _Sample | None = None

    def advance(self, providers: Sequence[AgentResourceProvider]) -> None:
        monitors = tuple(
            provider for provider in providers
            if isinstance(provider, GpuResourceProvider) and provider._occupancy_monitor is not None
        )
        pending = self._pending
        if pending is not None:
            if not pending.future.done():
                return
            self._pending = None
            sample = pending.future.result()
            if pending.provider in monitors:
                monitor = pending.monitor
                if (
                    pending.provider._occupancy_monitor is monitor
                    and pending.provider._revision == pending.revision
                    and monitor.snapshot_is_fresh(sample)
                ):
                    monitor._apply_snapshot(sample)
                # Rotate even when a stale owner or very short sample interval
                # makes this device due again on the same turn.
                following = monitors.index(pending.provider) + 1
                monitors = monitors[following:] + monitors[:following]
        for provider in monitors:
            monitor = provider._occupancy_monitor
            assert monitor is not None
            if monitor.refresh_due():
                future = self._worker.submit(_observe, monitor)
                self._pending = _Sample(provider, monitor, provider._revision, future)
                future.add_done_callback(lambda _: self._wake())
                return

    def close(self) -> None:
        self._worker.shutdown(wait=True)
        self._pending = None

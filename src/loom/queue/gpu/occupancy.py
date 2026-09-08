"""NVIDIA GPU process observations used for local whole-device admission.

The observer deliberately has no scheduler or claim knowledge.  It reports a
small UUID-keyed snapshot, and the managed GPU provider overlays its current
claims before exposing safe capacity keys to the rest of Loom.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import math
import subprocess
from threading import Lock
from time import monotonic
from typing import Final
from xml.etree import ElementTree

from loom.timestamps import utc_now, utc_timestamp


_PROCESS_TYPES: Final = frozenset({"C", "G", "C+G"})


@dataclass(frozen=True, slots=True)
class GpuOccupancyPolicy:
    """Bounded polling and freshness policy for selected NVIDIA devices."""

    poll_interval_seconds: float = 5
    max_observation_age_seconds: float = 15
    query_timeout_seconds: float = 2

    def __post_init__(self) -> None:
        for name in (
            "poll_interval_seconds",
            "max_observation_age_seconds",
            "query_timeout_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a finite positive number")
            value = float(value)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
            object.__setattr__(self, name, value)
        if self.max_observation_age_seconds <= (
            self.poll_interval_seconds + self.query_timeout_seconds
        ):
            raise ValueError(
                "max_observation_age_seconds must exceed polling interval plus query timeout"
            )

    def to_dict(self) -> dict[str, float]:
        return {
            "poll_interval_seconds": self.poll_interval_seconds,
            "max_observation_age_seconds": self.max_observation_age_seconds,
            "query_timeout_seconds": self.query_timeout_seconds,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "GpuOccupancyPolicy":
        if set(value) != {
            "poll_interval_seconds",
            "max_observation_age_seconds",
            "query_timeout_seconds",
        }:
            raise ValueError("GPU occupancy policy fields are invalid")
        return cls(
            poll_interval_seconds=value["poll_interval_seconds"],  # type: ignore[arg-type]
            max_observation_age_seconds=value["max_observation_age_seconds"],  # type: ignore[arg-type]
            query_timeout_seconds=value["query_timeout_seconds"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class GpuProcessObservation:
    """One selected UUID's process-query outcome, without process details."""

    uuid: str
    query_succeeded: bool
    has_gpu_process: bool
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.uuid, str) or not self.uuid:
            raise ValueError("GPU observation UUID must be a non-empty string")
        if not isinstance(self.query_succeeded, bool) or not isinstance(
            self.has_gpu_process, bool
        ):
            raise ValueError("GPU observation state must be boolean")
        if not isinstance(self.reason_code, str) or not self.reason_code:
            raise ValueError("GPU observation reason must be a non-empty string")
        if self.has_gpu_process and not self.query_succeeded:
            raise ValueError("unknown GPU observation cannot report a process")


@dataclass(frozen=True, slots=True)
class GpuOccupancySnapshot:
    """One atomically completed process sample with local monotonic age evidence."""

    observations: tuple[GpuProcessObservation, ...]
    observed_at: str
    completed_monotonic: float

    def __post_init__(self) -> None:
        if len({item.uuid for item in self.observations}) != len(self.observations):
            raise ValueError("GPU occupancy observations must have unique UUIDs")
        if not isinstance(self.observed_at, str) or not self.observed_at:
            raise ValueError("GPU occupancy observation time must be a timestamp")
        if not isinstance(self.completed_monotonic, (int, float)) or not math.isfinite(
            self.completed_monotonic
        ):
            raise ValueError("GPU occupancy completion time must be finite")

    def for_uuid(self, uuid: str) -> GpuProcessObservation | None:
        return next((item for item in self.observations if item.uuid == uuid), None)

    def is_fresh(self, now_monotonic: float, max_age_seconds: float) -> bool:
        return now_monotonic - self.completed_monotonic <= max_age_seconds


def _default_process_runner(
    argv: Sequence[str], timeout_seconds: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        tuple(argv),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )


@dataclass(frozen=True, slots=True)
class NvidiaSmiGpuProcessObserver:
    """Query selected UUIDs once using NVIDIA's structured XML process output."""

    selected_uuids: tuple[str, ...]
    policy: GpuOccupancyPolicy = GpuOccupancyPolicy()
    command_runner: Callable[
        [Sequence[str], float], subprocess.CompletedProcess[str]
    ] = _default_process_runner

    def __post_init__(self) -> None:
        selected = tuple(self.selected_uuids)
        if not selected or any(
            not isinstance(uuid, str) or not uuid for uuid in selected
        ):
            raise ValueError("selected GPU UUIDs must be non-empty")
        if len(set(selected)) != len(selected):
            raise ValueError("selected GPU UUIDs must be unique")
        object.__setattr__(self, "selected_uuids", selected)
        if not isinstance(self.policy, GpuOccupancyPolicy):
            raise ValueError("GPU occupancy observer policy is invalid")

    def observe(self) -> Mapping[str, GpuProcessObservation]:
        argv = (
            "nvidia-smi",
            "--query",
            "--xml-format",
            "--id=" + ",".join(self.selected_uuids),
        )
        try:
            completed = self.command_runner(argv, self.policy.query_timeout_seconds)
        except subprocess.TimeoutExpired:
            return self._unknown("query_timeout")
        except PermissionError:
            return self._unknown("query_permission_denied")
        except (FileNotFoundError, OSError):
            return self._unknown("query_unavailable")
        except Exception:  # noqa: BLE001 - injectable boundary must fail closed.
            return self._unknown("query_failed")
        if completed.returncode != 0 or not isinstance(completed.stdout, str):
            return self._unknown("query_failed")
        return self._parse(completed.stdout)

    def _unknown(self, reason_code: str) -> Mapping[str, GpuProcessObservation]:
        return {
            uuid: GpuProcessObservation(uuid, False, False, reason_code)
            for uuid in self.selected_uuids
        }

    def _parse(self, stdout: str) -> Mapping[str, GpuProcessObservation]:
        try:
            root = ElementTree.fromstring(stdout)
        except ElementTree.ParseError:
            return self._unknown("query_malformed")
        if root.tag != "nvidia_smi_log":
            return self._unknown("query_malformed")
        observed: dict[str, GpuProcessObservation] = {}
        for gpu in root.findall("gpu"):
            uuid = (gpu.findtext("uuid") or "").strip()
            if uuid not in self.selected_uuids:
                continue
            if uuid in observed:
                observed[uuid] = GpuProcessObservation(
                    uuid, False, False, "query_incomplete"
                )
                continue
            processes = gpu.find("processes")
            if (
                processes is None
                or (processes.text or "").strip()
                or any(child.tag != "process_info" for child in processes)
            ):
                observed[uuid] = GpuProcessObservation(
                    uuid, False, False, "query_incomplete"
                )
                continue
            records = processes.findall("process_info")
            if not records:
                observed[uuid] = GpuProcessObservation(uuid, True, False, "available")
                continue
            types = [(record.findtext("type") or "").strip() for record in records]
            if any(item not in _PROCESS_TYPES for item in types):
                observed[uuid] = GpuProcessObservation(
                    uuid, False, False, "query_incomplete"
                )
            else:
                observed[uuid] = GpuProcessObservation(
                    uuid, True, True, "external_process_detected"
                )
        return {
            uuid: observed.get(
                uuid, GpuProcessObservation(uuid, False, False, "device_missing")
            )
            for uuid in self.selected_uuids
        }


class GpuOccupancyMonitor:
    """Serialize refreshes and retain only the latest UUID-keyed sample."""

    def __init__(
        self,
        selected_uuids: Sequence[str],
        *,
        policy: GpuOccupancyPolicy | None = None,
        observer: NvidiaSmiGpuProcessObserver | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
        utc_clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.policy = policy or GpuOccupancyPolicy()
        selected = tuple(selected_uuids)
        self._observer = observer or NvidiaSmiGpuProcessObserver(selected, self.policy)
        if self._observer.selected_uuids != selected:
            raise ValueError("GPU occupancy observer UUIDs conflict with monitor")
        self._selected_uuids = selected
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock
        self._snapshot: GpuOccupancySnapshot | None = None
        self._refresh_lock = Lock()

    @property
    def selected_uuids(self) -> tuple[str, ...]:
        return self._selected_uuids

    def cached_snapshot(self) -> GpuOccupancySnapshot | None:
        return self._snapshot

    def snapshot_is_fresh(self, snapshot: GpuOccupancySnapshot) -> bool:
        """Check cache age with this monitor's injected monotonic clock."""

        return snapshot.is_fresh(
            self._monotonic_clock(), self.policy.max_observation_age_seconds
        )

    def refresh(self, force: bool = False) -> GpuOccupancySnapshot:
        cached = self._snapshot
        now = self._monotonic_clock()
        if (
            not force
            and cached is not None
            and cached.is_fresh(now, self.policy.poll_interval_seconds)
        ):
            return cached
        with self._refresh_lock:
            cached = self._snapshot
            now = self._monotonic_clock()
            if (
                not force
                and cached is not None
                and cached.is_fresh(now, self.policy.poll_interval_seconds)
            ):
                return cached
            observations = self._observer.observe()
            snapshot = GpuOccupancySnapshot(
                tuple(
                    observations.get(
                        uuid,
                        GpuProcessObservation(uuid, False, False, "device_missing"),
                    )
                    for uuid in self._selected_uuids
                ),
                utc_timestamp(self._utc_clock()),
                self._monotonic_clock(),
            )
            self._snapshot = snapshot
            return snapshot

"""Optional observation retry timing; durable execution state stays in its owner."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile

from .errors import QueueConfigError


@dataclass(frozen=True, slots=True)
class SlurmObservationPolicy:
    """Separate scheduler retries from result delivery using monotonic deadlines."""

    failure_backoff_cap_seconds: float
    max_jobs_per_query: int | None = None
    max_queries_per_cycle: int | None = None
    cycle_budget_seconds: float | None = None

    def __post_init__(self) -> None:
        value = self.failure_backoff_cap_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise QueueConfigError("failure_backoff_cap_seconds must be finite and positive")
        try:
            normalized = float(value)
        except OverflowError as exc:
            raise QueueConfigError("failure_backoff_cap_seconds must be finite and positive") from exc
        if not math.isfinite(normalized) or not 0 < normalized <= 3600:
            raise QueueConfigError("failure_backoff_cap_seconds must be in (0, 3600]")
        object.__setattr__(self, "failure_backoff_cap_seconds", normalized)
        batching = (self.max_jobs_per_query, self.max_queries_per_cycle, self.cycle_budget_seconds)
        if any(value is not None for value in batching):
            for name, limit in (("max_jobs_per_query", 64), ("max_queries_per_cycle", 128)):
                value = getattr(self, name)
                if type(value) is not int or not 1 <= value <= limit:
                    raise QueueConfigError(f"{name} must be an integer in 1..{limit}")
            duration = self.cycle_budget_seconds
            if isinstance(duration, bool) or not isinstance(duration, (int, float)):
                raise QueueConfigError("cycle_budget_seconds must be in (0, 3600]")
            try:
                duration = float(duration)
            except OverflowError as exc:
                raise QueueConfigError("cycle_budget_seconds must be in (0, 3600]") from exc
            if not math.isfinite(duration) or not 0 < duration <= 3600:
                raise QueueConfigError("cycle_budget_seconds must be in (0, 3600]")
            object.__setattr__(self, "cycle_budget_seconds", duration)

    def require_profile(self, profile: SlurmReadyStageProfile) -> None:
        from loom.pipeline.executors.slurm.commands import ready_stage_command_policy

        self.require_interval(profile.poll_interval_seconds)
        if self.max_jobs_per_query is not None and (
            profile.accounting_history is None
            or ready_stage_command_policy(profile.runner) is None
            or not callable(getattr(profile.runner, "discover_named_operations", None))
        ):
            raise QueueConfigError("batched observation requires bounded named-accounting profiles")

    def require_interval(self, normal: float) -> None:
        if normal > self.failure_backoff_cap_seconds:
            raise QueueConfigError("failure_backoff_cap_seconds is below a profile poll interval")

    def delay(self, normal: float, failures: int) -> float:
        return min(self.failure_backoff_cap_seconds, normal * 2 ** min(max(failures - 1, 0), 32))

    def to_dict(self) -> dict[str, float | int]:
        value = {"failure_backoff_cap_seconds": self.failure_backoff_cap_seconds}
        if self.max_jobs_per_query is not None:
            assert self.max_queries_per_cycle is not None and self.cycle_budget_seconds is not None
            value.update(
                max_jobs_per_query=self.max_jobs_per_query,
                max_queries_per_cycle=self.max_queries_per_cycle,
                cycle_budget_seconds=self.cycle_budget_seconds,
            )
        return value


def parse_slurm_observation_policy(value: object) -> SlurmObservationPolicy | None:
    if value is None or isinstance(value, SlurmObservationPolicy):
        return value
    required = {"failure_backoff_cap_seconds"}
    batching = {"max_jobs_per_query", "max_queries_per_cycle", "cycle_budget_seconds"}
    if not isinstance(value, Mapping) or set(value) not in (required, required | batching):
        raise QueueConfigError("slurm_observation_policy requires failure_backoff_cap_seconds")
    if set(value) & batching and any(value[key] is None for key in batching):
        raise QueueConfigError("slurm_observation_policy requires all three batching values")
    return SlurmObservationPolicy(**value)

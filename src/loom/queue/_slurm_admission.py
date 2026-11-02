"""Optional Slurm admission and call pacing; assignment rows own reservations."""

from collections.abc import Mapping
from dataclasses import dataclass
import math

from .errors import QueueConfigError, QueueServiceError


@dataclass(frozen=True, slots=True)
class SlurmAdmissionPolicy:
    """Whole-GPU reservation ceiling; explicit None keeps schema 4 without a cap."""

    max_reserved_gpus: int | None

    def __post_init__(self) -> None:
        validate_gpu_limit(self.max_reserved_gpus)

    def to_dict(self) -> dict[str, int | None]:
        return {"max_reserved_gpus": self.max_reserved_gpus}


def validate_gpu_limit(value: int | None) -> None:
    if value is not None and (type(value) is not int or value < 1):
        raise ValueError("max_reserved_gpus must be a positive integer or null")


def parse_slurm_admission(value: object) -> SlurmAdmissionPolicy | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"max_reserved_gpus"}:
        raise QueueConfigError("slurm_admission requires max_reserved_gpus")
    try:
        return SlurmAdmissionPolicy(value["max_reserved_gpus"])
    except (TypeError, ValueError) as exc:
        raise QueueConfigError(str(exc)) from exc


def submit_interval(value: object) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise QueueConfigError("slurm_submit_interval_seconds must be finite and positive")
    try:
        interval = float(value)
    except OverflowError as exc:
        raise QueueConfigError("slurm_submit_interval_seconds must be finite and positive") from exc
    if not math.isfinite(interval) or interval <= 0:
        raise QueueConfigError("slurm_submit_interval_seconds must be finite and positive")
    return interval


class SlurmAdmissionDeferred(QueueServiceError):
    """A known admission bound, distinct from route/installation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

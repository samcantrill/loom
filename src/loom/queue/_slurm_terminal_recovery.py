"""Opt-in terminal-result recovery policy and exact probe identities."""

from collections.abc import Mapping
from dataclasses import dataclass
import math
from typing import cast

from loom.serialization import PlainData

from .errors import QueueConfigError


@dataclass(frozen=True, slots=True)
class SlurmTerminalRecoveryPolicy:
    terminal_result_grace_seconds: float = 120.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("terminal recovery enabled must be boolean")
        value = self.terminal_result_grace_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("terminal_result_grace_seconds must be finite and nonnegative")

    def to_dict(self) -> dict[str, PlainData]:
        return {"terminal_result_grace_seconds": float(self.terminal_result_grace_seconds), "enabled": self.enabled}


def parse_terminal_recovery(value: object) -> SlurmTerminalRecoveryPolicy | None:
    if value is None:
        return None
    if (not isinstance(value, Mapping) or "terminal_result_grace_seconds" not in value
        or set(value) - {"terminal_result_grace_seconds", "enabled"}):
        raise QueueConfigError("slurm_terminal_recovery requires terminal_result_grace_seconds")
    try:
        return SlurmTerminalRecoveryPolicy(value["terminal_result_grace_seconds"], value.get("enabled", True))
    except (ValueError, TypeError, OverflowError) as exc:
        raise QueueConfigError(str(exc)) from exc


def probe_request(observation: Mapping[str, PlainData]) -> dict[str, PlainData]:
    # The task already carries the assignment and scientific result binding.
    # Repeat only the flat ownership facts needed for this probe. Nesting the
    # entire task identity again exceeds the existing control-protocol depth.
    identity = cast(Mapping[str, PlainData], observation["identity"])
    result = cast(Mapping[str, PlainData], identity["result"])
    assignment = cast(Mapping[str, PlainData], result["assignment"])
    return {
        "coordinator_id": result["coordinator_id"],
        "assignment_id": assignment["assignment_id"],
        "incarnation": result["incarnation"],
        "fence": result["fence"],
        "accounting_identity": identity["accounting"],
        "scheduler_state": identity["scheduler_state"],
        "first_observed_at": observation["first_observed_at"],
    }

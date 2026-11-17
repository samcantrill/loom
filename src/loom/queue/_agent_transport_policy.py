"""Protected per-attempt HTTP budgets, independent of workload lifetime."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import cast

from .errors import QueueConfigError


@dataclass(frozen=True, slots=True)
class AgentTransportPolicy:
    connect_timeout_seconds: float = 10.0
    response_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 300:
                raise QueueConfigError(f"transport_policy.{name} must be positive and at most 300 seconds")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def parse_transport_policy(value: object) -> AgentTransportPolicy:
    if value is None:
        return AgentTransportPolicy()
    if isinstance(value, AgentTransportPolicy):
        return value
    if not isinstance(value, Mapping) or set(value) != {
        "connect_timeout_seconds", "response_timeout_seconds",
    }:
        raise QueueConfigError("transport_policy requires connect and response timeout seconds")
    return AgentTransportPolicy(
        connect_timeout_seconds=cast(float, value["connect_timeout_seconds"]),
        response_timeout_seconds=cast(float, value["response_timeout_seconds"]),
    )

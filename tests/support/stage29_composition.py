"""Trusted test-site targets for Stage 29 protected role composition."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib

from loom.pipeline.runtime import CpuResourcePlanner
from loom.queue._managed_local import AgentResourceProvider, AtomResourceProvider
from loom.queue._remote_stage_execution import ResidentExecutionProfile
from loom.scheduling import CapacityAtom, ExactQuantity, SchedulingComponentDescriptor


class FixedPriorityResolver:
    def __init__(self, *, priority: int) -> None:
        self.priority = priority

    def __call__(self, _run_uri: str) -> int:
        return self.priority


class ConfiguredCpuProvider(AtomResourceProvider):
    def __init__(self, *, capacity: int, capacity_key: str = "configured-cpu") -> None:
        planner = CpuResourcePlanner()
        configured = CapacityAtom(
            "cpu",
            capacity_key,
            ExactQuantity(capacity),
            "count",
            ExactQuantity(1),
        )
        descriptor = SchedulingComponentDescriptor(
            kind="cpu",
            contract_version=1,
            implementation_version="stage29-test-v1",
            implementation_fingerprint="tests.stage29.configured-cpu-provider",
            configuration_fingerprint=hashlib.sha256(
                f"{capacity_key}\0{capacity}".encode("utf-8")
            ).hexdigest(),
        )
        super().__init__(descriptor, planner.claim_contracts, (configured,))


class ResidentProviderFactory:
    def __init__(self, *, capacity: int) -> None:
        self.capacity = capacity
        self.calls = 0

    def __call__(
        self, agent_id: str, _profile: ResidentExecutionProfile
    ) -> Sequence[AgentResourceProvider]:
        self.calls += 1
        return (
            ConfiguredCpuProvider(
                capacity=self.capacity,
                capacity_key=f"{agent_id}:cpu",
            ),
        )

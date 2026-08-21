"""Executor protocol for pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from loom.pipeline.executors.errors import ExecutorError
from loom.pipeline.runtime.capabilities import ExecutorDescriptor, ExecutorDescriptorRegistry

if TYPE_CHECKING:
    from loom.pipeline.execution.models import (
        StageExecutionRequest,
        StageExecutionResult,
    )
    from loom.pipeline.execution.services import RuntimeServices
    from loom.pipeline.runtime import RunOptions


@runtime_checkable
class Executor(Protocol):
    name: str

    def execute(self, request: StageExecutionRequest) -> StageExecutionResult: ...


class ExecutorFactory(Protocol):
    """Build one ordinary executor from the runtime dependencies it consumes."""

    def __call__(self, *, services: "RuntimeServices", options: "RunOptions") -> Executor: ...


@dataclass(frozen=True, slots=True)
class ExecutorRegistration:
    """The descriptor and factory for one ordinary executor."""

    descriptor: ExecutorDescriptor
    factory: ExecutorFactory

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, ExecutorDescriptor):
            raise ExecutorError("ExecutorRegistration.descriptor must be an ExecutorDescriptor")
        if not callable(self.factory):
            raise ExecutorError("ExecutorRegistration.factory must be callable")


@dataclass(slots=True)
class ExecutorRegistry:
    """Instance-local registrations for ordinary dispatch executors."""

    _registrations: dict[str, ExecutorRegistration] = field(default_factory=dict)

    def register(self, registration: ExecutorRegistration) -> None:
        if not isinstance(registration, ExecutorRegistration):
            raise ExecutorError("ExecutorRegistry.register requires an ExecutorRegistration")
        name = registration.descriptor.name
        if name in self._registrations:
            raise ExecutorError(f"executor already registered for name {name!r}")
        self._registrations[name] = registration

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    @property
    def descriptor_registry(self) -> ExecutorDescriptorRegistry:
        return ExecutorDescriptorRegistry(
            {name: registration.descriptor for name, registration in self._registrations.items()}
        )

    def resolve(self, name: str | None) -> ExecutorRegistration:
        descriptor = self.descriptor_registry.resolve(name)
        return self._registrations[descriptor.name]

    def build(self, name: str | None, *, services: "RuntimeServices", options: "RunOptions") -> Executor:
        registration = self.resolve(name)
        executor = registration.factory(services=services, options=options)
        if not isinstance(executor, Executor):
            raise ExecutorError(
                f"executor factory for {registration.descriptor.name!r} did not return an Executor"
            )
        if executor.name != registration.descriptor.name:
            raise ExecutorError(
                "executor factory result name must match registration descriptor: "
                f"expected {registration.descriptor.name!r}, got {executor.name!r}"
            )
        return executor


__all__ = ["Executor", "ExecutorFactory", "ExecutorRegistration", "ExecutorRegistry"]

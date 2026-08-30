"""Queue-owned authority construction for coordinator execution.

The execution engine receives a per-run factory.  The embedded composition is
kept here so execution never reaches into a SQLite authority implementation.
Persistent compositions may provide an authenticated factory with the same
prepared-attempt execution contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from loom.artifacts import ArtifactRef
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.authority import (
    ExecutionFence,
    PreparedAttemptExecutionAuthority,
    PreparedAttemptRequest,
    PreparedAttemptReceipt,
    StatusTransition,
)
from loom.pipeline.stores.read_models import LifecycleReason
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


class CoordinatorAuthorityStore(Protocol):
    """The deliberately narrow existing coordinator authority surface."""

    def open_run(self, run_uri: str) -> object: ...


class AuthenticatedPreparedAttemptTransport(PreparedAttemptExecutionAuthority, Protocol):
    """Authenticated service transport restricted to coordinator/run calls."""

    def open_run(self, run_uri: str) -> object: ...


class AuthenticatedCoordinatorAuthority(PreparedAttemptExecutionAuthority):
    """Run-scoped mirror of the existing prepared-attempt authority contract.

    Authentication, service identity, and workspace scope belong to the
    supplied transport.  This adapter adds the queue's run fence and exposes
    no discovery, database, or generic CRUD capability.
    """

    def __init__(
        self, run_uri: str, transport: AuthenticatedPreparedAttemptTransport
    ) -> None:
        if not isinstance(run_uri, str) or not run_uri:
            raise ValueError("authenticated coordinator run URI is required")
        if not isinstance(transport, PreparedAttemptExecutionAuthority):
            raise TypeError("authenticated authority transport is invalid")
        self._run_uri = run_uri
        self._transport = transport

    def _run(self, run_uri: str) -> None:
        if run_uri != self._run_uri:
            raise ValueError("authenticated coordinator authority run conflicts")

    def open_run(self, run_uri: str) -> object:
        self._run(run_uri)
        return self._transport.open_run(run_uri)

    def ensure_prepared_attempt(
        self, run_uri: str, request: PreparedAttemptRequest
    ) -> PreparedAttemptReceipt:
        self._run(run_uri)
        return self._transport.ensure_prepared_attempt(run_uri, request)

    def bind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._run(run_uri)
        self._transport.bind_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def unbind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._run(run_uri)
        self._transport.unbind_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def grant_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> ExecutionFence:
        self._run(run_uri)
        return self._transport.grant_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def confirm_execution_started(self, run_uri: str, *, fence: ExecutionFence) -> None:
        self._run(run_uri)
        self._transport.confirm_execution_started(run_uri, fence=fence)

    def record_managed_attempt_terminal(
        self,
        run_uri: str,
        *,
        fence: ExecutionFence,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        self._run(run_uri)
        return self._transport.record_managed_attempt_terminal(
            run_uri, fence=fence, status=status, reason=reason
        )

    def close_managed_attempt_fence(
        self,
        run_uri: str,
        *,
        recovery_id: str,
        fence: ExecutionFence,
        expected_state_version: int,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        self._run(run_uri)
        return self._transport.close_managed_attempt_fence(
            run_uri,
            recovery_id=recovery_id,
            fence=fence,
            expected_state_version=expected_state_version,
            status=status,
            reason=reason,
        )

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        supersedes_commit_id: str | None = None,
        reason: LifecycleReason | None = None,
        assignment_id: str | None = None,
    ) -> Any:
        self._run(run_uri)
        return self._transport.record_output_commit(
            run_uri,
            stage_name,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            outputs=outputs,
            supersedes_commit_id=supersedes_commit_id,
            reason=reason,
            assignment_id=assignment_id,
        )


CoordinatorAuthorityFactory = Callable[[str], CoordinatorAuthorityStore]


def embedded_coordinator_authority(run_uri: str) -> CoordinatorAuthorityStore:
    """Open the explicit trusted embedded authority owner for one run."""

    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.open_run(run_uri)
    return authority


def authenticated_coordinator_authority_factory(
    transport: AuthenticatedPreparedAttemptTransport,
) -> CoordinatorAuthorityFactory:
    """Bind one authenticated transport into per-run queue authority views."""

    return lambda run_uri: AuthenticatedCoordinatorAuthority(run_uri, transport)


__all__ = [
    "CoordinatorAuthorityFactory",
    "CoordinatorAuthorityStore",
    "AuthenticatedCoordinatorAuthority",
    "AuthenticatedPreparedAttemptTransport",
    "authenticated_coordinator_authority_factory",
    "embedded_coordinator_authority",
]

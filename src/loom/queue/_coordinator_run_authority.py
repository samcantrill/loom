"""Existing least-privilege adapter for one run and coordinator binding.

The adapter checks scope and guarded-recovery mutation restrictions. It does not
accept new work, select placement, own processes or replace per-run authority.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from .errors import QueueConflictError

if TYPE_CHECKING:
    from loom.artifacts import ArtifactRef
    from loom.pipeline.status import RunStatus, StageStatus
    from loom.pipeline.stores import CancellationEpochRequest
    from loom.pipeline.stores.authority import ExecutionFence, PreparedAttemptRequest, StatusTransition
    from loom.pipeline.stores.read_models import AuthoritativeRunSnapshot, LifecycleReason
    from .coordinator_authority import CoordinatorAuthorityStore


class _ScopedCoordinatorAuthority:
    """Least-privilege run/coordinator view used by orchestration and the agent.

    The SQLite authority remains an implementation detail of the daemon.  This
    adapter deliberately exposes only the exact Phase 1/2 calls needed after
    the coordinator binding has been accepted.
    """

    def __init__(
        self,
        store: CoordinatorAuthorityStore,
        *,
        run_uri: str,
        coordinator_id: str,
        ordinary_mutation_frozen: Callable[[str], bool] | None = None,
        on_grant: Callable[[str, ExecutionFence], None] | None = None,
    ) -> None:
        self._store = store
        self._run_uri = run_uri
        self._coordinator_id = coordinator_id
        self._ordinary_mutation_frozen = ordinary_mutation_frozen
        self._on_grant = on_grant

    def _require_ordinary_mutation(self, assignment_id: str) -> None:
        frozen = self._ordinary_mutation_frozen
        if frozen is not None and frozen(assignment_id):
            raise QueueConflictError(
                "ordinary terminal mutation is frozen by guarded recovery"
            )

    def _run(self, run_uri: str) -> None:
        if run_uri != self._run_uri:
            raise QueueConflictError("scoped authority run conflicts")

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        self._run(run_uri)
        return self._store.open_run(run_uri)

    def transition_run(self, run_uri: str, **kwargs: object) -> StatusTransition:
        self._run(run_uri)
        return self._store.transition_run(run_uri, **kwargs)  # type: ignore[arg-type]

    def transition_stage(
        self, run_uri: str, stage_name: str, **kwargs: object
    ) -> StatusTransition:
        self._run(run_uri)
        return self._store.transition_stage(run_uri, stage_name, **kwargs)  # type: ignore[arg-type]

    def ensure_prepared_attempt(self, run_uri: str, request: PreparedAttemptRequest):
        self._run(run_uri)
        return self._store.ensure_prepared_attempt(run_uri, request)

    def bind_action_result(self, run_uri: str, stage_name: str, binding, *, expected_revision=None):
        self._run(run_uri)
        return self._store.bind_action_result(run_uri, stage_name, binding, expected_revision=expected_revision)

    def bind_action_producer(self, run_uri: str, binding) -> None:
        self._run(run_uri)
        self._store.bind_action_producer(run_uri, binding)

    def release_action_producer(self, run_uri: str, binding) -> None:
        self._run(run_uri)
        self._store.release_action_producer(run_uri, binding)

    def bind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._run(run_uri)
        self._store.bind_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def unbind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._run(run_uri)
        self._store.unbind_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )

    def grant_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ):
        self._run(run_uri)
        fence = self._store.grant_prepared_attempt(
            run_uri, assignment_id=assignment_id, attempt_id=attempt_id
        )
        if self._on_grant is not None:
            self._on_grant(run_uri, fence)
        return fence

    def confirm_execution_started(self, run_uri: str, *, fence: ExecutionFence) -> None:
        self._run(run_uri)
        self._store.confirm_execution_started(run_uri, fence=fence)

    def install_cancellation_epoch(
        self, run_uri: str, request: CancellationEpochRequest
    ):
        self._run(run_uri)
        if request.coordinator_id != self._coordinator_id:
            raise QueueConflictError("scoped authority coordinator conflicts")
        return self._store.install_cancellation_epoch(run_uri, request)

    def read_cancellation_epoch_receipt(self, run_uri: str, operation_id: str):
        self._run(run_uri)
        return self._store.read_cancellation_epoch_receipt(run_uri, operation_id)

    def finalize_cancellation(
        self, run_uri: str, request: CancellationEpochRequest
    ) -> RunStatus:
        self._run(run_uri)
        if request.coordinator_id != self._coordinator_id:
            raise QueueConflictError("scoped authority coordinator conflicts")
        return self._store.finalize_cancellation(run_uri, request)

    def record_managed_attempt_terminal(
        self,
        run_uri: str,
        *,
        fence: ExecutionFence,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        self._run(run_uri)
        self._require_ordinary_mutation(fence.assignment_id)
        return self._store.record_managed_attempt_terminal(
            run_uri, fence=fence, status=status, reason=reason
        )

    def close_managed_attempt_fence(self, run_uri: str, **kwargs: object):
        self._run(run_uri)
        return self._store.close_managed_attempt_fence(run_uri, **kwargs)  # type: ignore[arg-type]

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
    ):
        self._run(run_uri)
        if assignment_id is not None:
            self._require_ordinary_mutation(assignment_id)
        return self._store.record_output_commit(
            run_uri,
            stage_name,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            outputs=outputs,
            supersedes_commit_id=supersedes_commit_id,
            reason=reason,
            assignment_id=assignment_id,
        )

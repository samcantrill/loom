"""Server-side authority mutation protocol adapter."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup.records import CleanupReport, CleanupResult
from loom.pipeline.offline_evidence import OfflineEvidenceManifest
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.stores import (
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRejection,
    AuthorityProtocolRequest,
    AuthorityProtocolResponse,
    AuthorityProtocolResult,
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    CleanupReportFact,
    CleanupResultFact,
    CancellationEpochRequest,
    CoordinatorAdmissionRequest,
    LeaseRecord,
    LifecycleReason,
    OutputCommit,
    OutputCommitRecord,
    PreparedAttemptRequest,
    RecoveryRecord,
    ReliabilityPolicyFact,
    StageAttempt,
    SweepIdentity,
    ConcurrencyCounter,
    CoordinationFailureKind,
    CoordinationRecoveryRecord,
    CoordinationStoreError,
    ResourceLeaseRecord,
    TrialLeaseRecord,
    TrialReference,
    WorkspaceIdentity,
    accepted_authority_response,
    rejected_authority_response,
)
from loom.pipeline.stores.authority import ExecutionFence
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData

from ._repository import (
    AuthorityRepository,
    AuthorityRepositoryCompatibilityError,
    AuthorityRepositoryCompatibilityKind,
    AuthorityRepositoryError,
)
from .offline_import import (
    OfflineImportError,
    OfflineImportRejectionKind,
    import_offline_evidence_manifest,
)


class AuthorityMutationOperation(StrEnum):
    """Server-supported mutation route operations."""

    ADMIT_RUN = "admit_run"
    OPEN_RUN = "open_run"
    SCAN_RUN_RECOVERY = "scan_run_recovery"
    TRANSITION_RUN = "transition_run"
    ACQUIRE_CONTROLLER_LEASE = "acquire_controller_lease"
    RENEW_CONTROLLER_LEASE = "renew_controller_lease"
    RELEASE_CONTROLLER_LEASE = "release_controller_lease"
    FAIL_CONTROLLER_LEASE = "fail_controller_lease"
    WRITE_SUBMITTED_OPERATION = "write_submitted_operation"
    READ_SUBMITTED_OPERATION = "read_submitted_operation"
    LIST_SUBMITTED_OPERATIONS = "list_submitted_operations"
    APPEND_CLEANUP_REPORT = "append_cleanup_report"
    LIST_CLEANUP_REPORTS = "list_cleanup_reports"
    APPEND_CLEANUP_RESULT = "append_cleanup_result"
    LIST_CLEANUP_RESULTS = "list_cleanup_results"
    TRANSITION_STAGE = "transition_stage"
    ALLOCATE_STAGE_ATTEMPT = "allocate_stage_attempt"
    RENEW_STAGE_LEASE = "renew_stage_lease"
    RELEASE_STAGE_LEASE = "release_stage_lease"
    FAIL_STAGE_LEASE = "fail_stage_lease"
    FINISH_STAGE_ATTEMPT = "finish_stage_attempt"
    RECORD_OUTPUT_COMMIT = "record_output_commit"
    LIST_OUTPUT_COMMITS = "list_output_commits"
    CREATE_WORKSPACE = "create_workspace"
    CREATE_SWEEP = "create_sweep"
    RECORD_TRIAL = "record_trial"
    IMPORT_OFFLINE_EVIDENCE = "import_offline_evidence"
    LIST_TRIALS = "list_trials"
    ACQUIRE_TRIAL_LEASE = "acquire_trial_lease"
    RENEW_COORDINATION_LEASE = "renew_coordination_lease"
    RELEASE_COORDINATION_LEASE = "release_coordination_lease"
    FAIL_COORDINATION_LEASE = "fail_coordination_lease"
    SET_COUNTER_LIMIT = "set_counter_limit"
    INCREMENT_COUNTER = "increment_counter"
    DECREMENT_COUNTER = "decrement_counter"
    READ_COUNTER = "read_counter"
    SCAN_COORDINATION_RECOVERY = "scan_coordination_recovery"
    ACQUIRE_RESOURCE_LEASE = "acquire_resource_lease"
    SET_RESOURCE_LIMIT = "set_resource_limit"
    ENSURE_RESOURCE_LIMITS = "ensure_resource_limits"
    READ_RESOURCE_LIMIT = "read_resource_limit"
    COORDINATOR_OPEN_RUN = "coordinator_open_run"
    COORDINATOR_TRANSITION_RUN = "coordinator_transition_run"
    COORDINATOR_TRANSITION_STAGE = "coordinator_transition_stage"
    BIND_COORDINATOR_ADMISSION = "bind_coordinator_admission"
    INSTALL_CANCELLATION_EPOCH = "install_cancellation_epoch"
    READ_CANCELLATION_EPOCH = "read_cancellation_epoch"
    FINALIZE_CANCELLATION = "finalize_cancellation"
    ENSURE_PREPARED_ATTEMPT = "ensure_prepared_attempt"
    BIND_PREPARED_ATTEMPT = "bind_prepared_attempt"
    UNBIND_PREPARED_ATTEMPT = "unbind_prepared_attempt"
    GRANT_PREPARED_ATTEMPT = "grant_prepared_attempt"
    CONFIRM_EXECUTION_STARTED = "confirm_execution_started"
    RECORD_MANAGED_TERMINAL = "record_managed_terminal"
    CLOSE_MANAGED_FENCE = "close_managed_fence"
    RECORD_MANAGED_OUTPUT = "record_managed_output"
    WRITE_RELIABILITY_POLICY = "write_reliability_policy"
    LIST_RELIABILITY_POLICIES = "list_reliability_policies"
    WRITE_RELIABILITY_STATUS = "write_reliability_status"
    LIST_RELIABILITY_STATUSES = "list_reliability_statuses"
    WRITE_ATTEMPT_TRANSACTION = "write_attempt_transaction"
    READ_TRANSACTION_CHAIN = "read_transaction_chain"
    LIST_ATTEMPT_TRANSACTIONS = "list_attempt_transactions"
    WRITE_RETRY_DECISION = "write_retry_decision"
    LIST_RETRY_DECISIONS = "list_retry_decisions"
    WRITE_TIMEOUT_OUTCOME = "write_timeout_outcome"
    LIST_TIMEOUT_OUTCOMES = "list_timeout_outcomes"


class AuthorityMutationValidationError(ValueError):
    """Raised when a mutation request body cannot be adapted."""


_COORDINATOR_EXECUTION_MUTATIONS = frozenset(
    {
        AuthorityMutationOperation.COORDINATOR_OPEN_RUN,
        AuthorityMutationOperation.COORDINATOR_TRANSITION_RUN,
        AuthorityMutationOperation.COORDINATOR_TRANSITION_STAGE,
        AuthorityMutationOperation.BIND_COORDINATOR_ADMISSION,
        AuthorityMutationOperation.INSTALL_CANCELLATION_EPOCH,
        AuthorityMutationOperation.READ_CANCELLATION_EPOCH,
        AuthorityMutationOperation.FINALIZE_CANCELLATION,
        AuthorityMutationOperation.ENSURE_PREPARED_ATTEMPT,
        AuthorityMutationOperation.BIND_PREPARED_ATTEMPT,
        AuthorityMutationOperation.UNBIND_PREPARED_ATTEMPT,
        AuthorityMutationOperation.GRANT_PREPARED_ATTEMPT,
        AuthorityMutationOperation.CONFIRM_EXECUTION_STARTED,
        AuthorityMutationOperation.RECORD_MANAGED_TERMINAL,
        AuthorityMutationOperation.CLOSE_MANAGED_FENCE,
        AuthorityMutationOperation.RECORD_MANAGED_OUTPUT,
    }
)
_RELIABILITY_MUTATIONS = frozenset(
    {
        AuthorityMutationOperation.WRITE_RELIABILITY_POLICY,
        AuthorityMutationOperation.LIST_RELIABILITY_POLICIES,
        AuthorityMutationOperation.WRITE_RELIABILITY_STATUS,
        AuthorityMutationOperation.LIST_RELIABILITY_STATUSES,
        AuthorityMutationOperation.WRITE_ATTEMPT_TRANSACTION,
        AuthorityMutationOperation.READ_TRANSACTION_CHAIN,
        AuthorityMutationOperation.LIST_ATTEMPT_TRANSACTIONS,
        AuthorityMutationOperation.WRITE_RETRY_DECISION,
        AuthorityMutationOperation.LIST_RETRY_DECISIONS,
        AuthorityMutationOperation.WRITE_TIMEOUT_OUTCOME,
        AuthorityMutationOperation.LIST_TIMEOUT_OUTCOMES,
    }
)
_SCOPED_COORDINATOR_MUTATIONS = (
    _COORDINATOR_EXECUTION_MUTATIONS | _RELIABILITY_MUTATIONS
)


_OPERATION_KIND_BY_MUTATION: Mapping[
    AuthorityMutationOperation,
    AuthorityProtocolOperationKind,
] = {
    AuthorityMutationOperation.ADMIT_RUN: AuthorityProtocolOperationKind.RUN_LIFECYCLE,
    AuthorityMutationOperation.OPEN_RUN: AuthorityProtocolOperationKind.RUN_SNAPSHOT,
    AuthorityMutationOperation.SCAN_RUN_RECOVERY: (
        AuthorityProtocolOperationKind.RECOVERY_SCAN
    ),
    AuthorityMutationOperation.TRANSITION_RUN: (
        AuthorityProtocolOperationKind.RUN_LIFECYCLE
    ),
    AuthorityMutationOperation.ACQUIRE_CONTROLLER_LEASE: (
        AuthorityProtocolOperationKind.LEASE
    ),
    AuthorityMutationOperation.RENEW_CONTROLLER_LEASE: (
        AuthorityProtocolOperationKind.LEASE
    ),
    AuthorityMutationOperation.RELEASE_CONTROLLER_LEASE: (
        AuthorityProtocolOperationKind.LEASE
    ),
    AuthorityMutationOperation.FAIL_CONTROLLER_LEASE: (
        AuthorityProtocolOperationKind.LEASE
    ),
    AuthorityMutationOperation.WRITE_SUBMITTED_OPERATION: (
        AuthorityProtocolOperationKind.SUBMITTED_OPERATION
    ),
    AuthorityMutationOperation.READ_SUBMITTED_OPERATION: (
        AuthorityProtocolOperationKind.SUBMITTED_OPERATION
    ),
    AuthorityMutationOperation.LIST_SUBMITTED_OPERATIONS: (
        AuthorityProtocolOperationKind.SUBMITTED_OPERATION
    ),
    AuthorityMutationOperation.APPEND_CLEANUP_REPORT: (
        AuthorityProtocolOperationKind.CLEANUP_REPORTS
    ),
    AuthorityMutationOperation.LIST_CLEANUP_REPORTS: (
        AuthorityProtocolOperationKind.CLEANUP_REPORTS
    ),
    AuthorityMutationOperation.APPEND_CLEANUP_RESULT: (
        AuthorityProtocolOperationKind.CLEANUP_RESULTS
    ),
    AuthorityMutationOperation.LIST_CLEANUP_RESULTS: (
        AuthorityProtocolOperationKind.CLEANUP_RESULTS
    ),
    AuthorityMutationOperation.TRANSITION_STAGE: (
        AuthorityProtocolOperationKind.STAGE_LIFECYCLE
    ),
    AuthorityMutationOperation.ALLOCATE_STAGE_ATTEMPT: (
        AuthorityProtocolOperationKind.STAGE_ATTEMPT
    ),
    AuthorityMutationOperation.RENEW_STAGE_LEASE: AuthorityProtocolOperationKind.LEASE,
    AuthorityMutationOperation.RELEASE_STAGE_LEASE: AuthorityProtocolOperationKind.LEASE,
    AuthorityMutationOperation.FAIL_STAGE_LEASE: AuthorityProtocolOperationKind.LEASE,
    AuthorityMutationOperation.FINISH_STAGE_ATTEMPT: (
        AuthorityProtocolOperationKind.STAGE_ATTEMPT
    ),
    AuthorityMutationOperation.RECORD_OUTPUT_COMMIT: (
        AuthorityProtocolOperationKind.OUTPUT_COMMIT
    ),
    AuthorityMutationOperation.LIST_OUTPUT_COMMITS: (
        AuthorityProtocolOperationKind.OUTPUT_COMMIT
    ),
    AuthorityMutationOperation.CREATE_WORKSPACE: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.CREATE_SWEEP: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.RECORD_TRIAL: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.IMPORT_OFFLINE_EVIDENCE: (
        AuthorityProtocolOperationKind.OFFLINE_IMPORT
    ),
    AuthorityMutationOperation.LIST_TRIALS: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.ACQUIRE_TRIAL_LEASE: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.RENEW_COORDINATION_LEASE: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.RELEASE_COORDINATION_LEASE: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.FAIL_COORDINATION_LEASE: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.SET_COUNTER_LIMIT: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.INCREMENT_COUNTER: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.DECREMENT_COUNTER: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.READ_COUNTER: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.SCAN_COORDINATION_RECOVERY: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.ACQUIRE_RESOURCE_LEASE: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.SET_RESOURCE_LIMIT: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.ENSURE_RESOURCE_LIMITS: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    AuthorityMutationOperation.READ_RESOURCE_LIMIT: (
        AuthorityProtocolOperationKind.WORKSPACE_COORDINATION
    ),
    **{
        operation: AuthorityProtocolOperationKind.COORDINATOR_EXECUTION
        for operation in _COORDINATOR_EXECUTION_MUTATIONS
    },
    **{
        operation: AuthorityProtocolOperationKind.RELIABILITY_FACTS
        for operation in _RELIABILITY_MUTATIONS
    },
}

_COMPATIBILITY_CATEGORY_BY_KIND: Mapping[
    AuthorityRepositoryCompatibilityKind,
    AuthorityProtocolErrorCategory,
] = {
    AuthorityRepositoryCompatibilityKind.MISSING: (
        AuthorityProtocolErrorCategory.UNAVAILABLE_SERVICE
    ),
    AuthorityRepositoryCompatibilityKind.UNSUPPORTED_OLDER: (
        AuthorityProtocolErrorCategory.VALIDATION
    ),
    AuthorityRepositoryCompatibilityKind.UNSUPPORTED_NEWER: (
        AuthorityProtocolErrorCategory.VALIDATION
    ),
    AuthorityRepositoryCompatibilityKind.CORRUPT: (
        AuthorityProtocolErrorCategory.VALIDATION
    ),
}


class AuthorityMutationService:
    """Apply protocol mutation requests to a private authority repository."""

    def __init__(
        self,
        repository: AuthorityRepository,
        *,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> None:
        self._repository = repository
        identity = repository.read_identity()
        self._service_generation = service_generation or identity.service_generation
        self._workspace_id = workspace_id

    @property
    def service_generation(self) -> str:
        return self._service_generation

    @property
    def workspace_id(self) -> str | None:
        return self._workspace_id

    def handle(
        self,
        operation: AuthorityMutationOperation,
        payload: Mapping[str, object],
    ) -> AuthorityProtocolResponse:
        """Return a structured protocol response for one mutation payload."""

        metadata = _fallback_metadata(
            operation,
            payload,
            service_generation=self._service_generation,
            workspace_id=self._workspace_id,
        )
        try:
            request = AuthorityProtocolRequest.from_dict(payload)
            metadata = request.metadata
            if operation in _SCOPED_COORDINATOR_MUTATIONS:
                self._require_coordinator_scope(operation, request)
            result = self._dispatch(operation, request)
            return accepted_authority_response(metadata, result)
        except AuthorityRepositoryCompatibilityError as exc:
            return rejected_authority_response(
                metadata,
                _compatibility_rejection(exc),
            )
        except AuthorityRepositoryError as exc:
            return rejected_authority_response(
                metadata,
                _repository_rejection(exc, request_detail=_request_detail(payload)),
            )
        except OfflineImportError as exc:
            return rejected_authority_response(
                metadata,
                _offline_import_rejection(exc, request_detail=_request_detail(payload)),
            )
        except CoordinationStoreError as exc:
            return rejected_authority_response(
                metadata,
                _coordination_rejection(exc, request_detail=_request_detail(payload)),
            )
        except (AuthorityMutationValidationError, TypeError) as exc:
            return rejected_authority_response(
                metadata,
                AuthorityProtocolRejection(
                    category=AuthorityProtocolErrorCategory.VALIDATION,
                    code="authority_mutation_validation",
                    message=str(exc),
                    detail=_request_detail(payload),
                ),
            )
        except ValueError as exc:
            return rejected_authority_response(
                metadata,
                _value_error_rejection(exc, request_detail=_request_detail(payload)),
            )
        except Exception as exc:
            return rejected_authority_response(
                metadata,
                AuthorityProtocolRejection(
                    category=AuthorityProtocolErrorCategory.INTERNAL_ERROR,
                    code="authority_mutation_internal_error",
                    message="authority mutation failed",
                    detail={"error_type": type(exc).__name__},
                ),
            )

    def _dispatch(
        self,
        operation: AuthorityMutationOperation,
        request: AuthorityProtocolRequest,
    ) -> AuthorityProtocolResult:
        match operation:
            case AuthorityMutationOperation.ADMIT_RUN:
                return self._admit_run(request)
            case AuthorityMutationOperation.OPEN_RUN:
                return self._open_run(request)
            case AuthorityMutationOperation.SCAN_RUN_RECOVERY:
                return self._scan_run_recovery(request)
            case AuthorityMutationOperation.TRANSITION_RUN:
                return self._transition_run(request)
            case AuthorityMutationOperation.ACQUIRE_CONTROLLER_LEASE:
                return self._acquire_controller_lease(request)
            case AuthorityMutationOperation.RENEW_CONTROLLER_LEASE:
                return self._renew_controller_lease(request)
            case AuthorityMutationOperation.RELEASE_CONTROLLER_LEASE:
                return self._release_controller_lease(request)
            case AuthorityMutationOperation.FAIL_CONTROLLER_LEASE:
                return self._fail_controller_lease(request)
            case AuthorityMutationOperation.WRITE_SUBMITTED_OPERATION:
                return self._write_submitted_operation(request)
            case AuthorityMutationOperation.READ_SUBMITTED_OPERATION:
                return self._read_submitted_operation(request)
            case AuthorityMutationOperation.LIST_SUBMITTED_OPERATIONS:
                return self._list_submitted_operations(request)
            case AuthorityMutationOperation.APPEND_CLEANUP_REPORT:
                return self._append_cleanup_report(request)
            case AuthorityMutationOperation.LIST_CLEANUP_REPORTS:
                return self._list_cleanup_reports(request)
            case AuthorityMutationOperation.APPEND_CLEANUP_RESULT:
                return self._append_cleanup_result(request)
            case AuthorityMutationOperation.LIST_CLEANUP_RESULTS:
                return self._list_cleanup_results(request)
            case AuthorityMutationOperation.TRANSITION_STAGE:
                return self._transition_stage(request)
            case AuthorityMutationOperation.ALLOCATE_STAGE_ATTEMPT:
                return self._allocate_stage_attempt(request)
            case AuthorityMutationOperation.RENEW_STAGE_LEASE:
                return self._renew_stage_lease(request)
            case AuthorityMutationOperation.RELEASE_STAGE_LEASE:
                return self._release_stage_lease(request)
            case AuthorityMutationOperation.FAIL_STAGE_LEASE:
                return self._fail_stage_lease(request)
            case AuthorityMutationOperation.FINISH_STAGE_ATTEMPT:
                return self._finish_stage_attempt(request)
            case AuthorityMutationOperation.RECORD_OUTPUT_COMMIT:
                return self._record_output_commit(request)
            case AuthorityMutationOperation.LIST_OUTPUT_COMMITS:
                return self._list_output_commits(request)
            case AuthorityMutationOperation.CREATE_WORKSPACE:
                return self._create_workspace(request)
            case AuthorityMutationOperation.CREATE_SWEEP:
                return self._create_sweep(request)
            case AuthorityMutationOperation.RECORD_TRIAL:
                return self._record_trial(request)
            case AuthorityMutationOperation.IMPORT_OFFLINE_EVIDENCE:
                return self._import_offline_evidence(request)
            case AuthorityMutationOperation.LIST_TRIALS:
                return self._list_trials(request)
            case AuthorityMutationOperation.ACQUIRE_TRIAL_LEASE:
                return self._acquire_trial_lease(request)
            case AuthorityMutationOperation.RENEW_COORDINATION_LEASE:
                return self._renew_coordination_lease(request)
            case AuthorityMutationOperation.RELEASE_COORDINATION_LEASE:
                return self._release_coordination_lease(request)
            case AuthorityMutationOperation.FAIL_COORDINATION_LEASE:
                return self._fail_coordination_lease(request)
            case AuthorityMutationOperation.SET_COUNTER_LIMIT:
                return self._set_counter_limit(request)
            case AuthorityMutationOperation.INCREMENT_COUNTER:
                return self._increment_counter(request)
            case AuthorityMutationOperation.DECREMENT_COUNTER:
                return self._decrement_counter(request)
            case AuthorityMutationOperation.READ_COUNTER:
                return self._read_counter(request)
            case AuthorityMutationOperation.SCAN_COORDINATION_RECOVERY:
                return self._scan_coordination_recovery(request)
            case AuthorityMutationOperation.ACQUIRE_RESOURCE_LEASE:
                return self._acquire_resource_lease(request)
            case AuthorityMutationOperation.SET_RESOURCE_LIMIT:
                return self._set_resource_limit(request)
            case AuthorityMutationOperation.ENSURE_RESOURCE_LIMITS:
                return self._ensure_resource_limits(request)
            case AuthorityMutationOperation.READ_RESOURCE_LIMIT:
                return self._read_resource_limit(request)
            case AuthorityMutationOperation.BIND_COORDINATOR_ADMISSION:
                return self._bind_coordinator_admission(request)
            case AuthorityMutationOperation.COORDINATOR_OPEN_RUN:
                return self._coordinator_open_run(request)
            case AuthorityMutationOperation.COORDINATOR_TRANSITION_RUN:
                return self._coordinator_transition_run(request)
            case AuthorityMutationOperation.COORDINATOR_TRANSITION_STAGE:
                return self._coordinator_transition_stage(request)
            case AuthorityMutationOperation.INSTALL_CANCELLATION_EPOCH:
                return self._install_cancellation_epoch(request)
            case AuthorityMutationOperation.READ_CANCELLATION_EPOCH:
                return self._read_cancellation_epoch(request)
            case AuthorityMutationOperation.FINALIZE_CANCELLATION:
                return self._finalize_cancellation(request)
            case AuthorityMutationOperation.ENSURE_PREPARED_ATTEMPT:
                return self._ensure_prepared_attempt(request)
            case AuthorityMutationOperation.BIND_PREPARED_ATTEMPT:
                return self._bind_prepared_attempt(request)
            case AuthorityMutationOperation.UNBIND_PREPARED_ATTEMPT:
                return self._unbind_prepared_attempt(request)
            case AuthorityMutationOperation.GRANT_PREPARED_ATTEMPT:
                return self._grant_prepared_attempt(request)
            case AuthorityMutationOperation.CONFIRM_EXECUTION_STARTED:
                return self._confirm_execution_started(request)
            case AuthorityMutationOperation.RECORD_MANAGED_TERMINAL:
                return self._record_managed_terminal(request)
            case AuthorityMutationOperation.CLOSE_MANAGED_FENCE:
                return self._close_managed_fence(request)
            case AuthorityMutationOperation.RECORD_MANAGED_OUTPUT:
                return self._record_managed_output(request)
            case AuthorityMutationOperation.WRITE_RELIABILITY_POLICY:
                return self._write_reliability_policy(request)
            case AuthorityMutationOperation.LIST_RELIABILITY_POLICIES:
                return self._list_reliability_policies(request)
            case AuthorityMutationOperation.WRITE_RELIABILITY_STATUS:
                return self._write_reliability_status(request)
            case AuthorityMutationOperation.LIST_RELIABILITY_STATUSES:
                return self._list_reliability_statuses(request)
            case AuthorityMutationOperation.WRITE_ATTEMPT_TRANSACTION:
                return self._write_attempt_transaction(request)
            case AuthorityMutationOperation.READ_TRANSACTION_CHAIN:
                return self._read_transaction_chain(request)
            case AuthorityMutationOperation.LIST_ATTEMPT_TRANSACTIONS:
                return self._list_attempt_transactions(request)
            case AuthorityMutationOperation.WRITE_RETRY_DECISION:
                return self._write_retry_decision(request)
            case AuthorityMutationOperation.LIST_RETRY_DECISIONS:
                return self._list_retry_decisions(request)
            case AuthorityMutationOperation.WRITE_TIMEOUT_OUTCOME:
                return self._write_timeout_outcome(request)
            case AuthorityMutationOperation.LIST_TIMEOUT_OUTCOMES:
                return self._list_timeout_outcomes(request)

    def _require_coordinator_scope(
        self,
        operation: AuthorityMutationOperation,
        request: AuthorityProtocolRequest,
    ) -> None:
        expected_kind = operation_kind_for(operation)
        if request.metadata.operation_kind is not expected_kind:
            raise AuthorityMutationValidationError(
                "coordinator authority operation kind conflicts with route"
            )
        if request.metadata.service_generation != self._service_generation:
            raise AuthorityRepositoryError("stale service generation")
        if self._workspace_id is None:
            raise AuthorityMutationValidationError(
                "coordinator authority requires a configured workspace"
            )
        if request.metadata.workspace_id != self._workspace_id:
            raise AuthorityMutationValidationError(
                "coordinator authority workspace conflicts"
            )

    def _coordinator_open_run(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            service_generation=self._service_generation,
            snapshot=snapshot,
        )

    def _coordinator_transition_run(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        transition = self._repository.transition_run(
            _required_run_uri(request),
            from_status=RunStatus(_required_body_value(request, "from_status")),
            to_status=RunStatus(_required_body_value(request, "to_status")),
            expected_revision=request.expected_revision,
            intent=TransitionIntent(
                cast(str, request.body.get("intent", TransitionIntent.NORMAL.value))
            ),
            reason=_optional_reason(request),
        )
        return _result(
            revision=transition.revision,
            service_generation=self._service_generation,
            body={"transition": transition.to_dict()},
        )

    def _coordinator_transition_stage(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        raw_from = request.body.get("from_status")
        transition = self._repository.transition_stage(
            _required_run_uri(request),
            _required_stage_name(request),
            from_status=None if raw_from is None else StageStatus(raw_from),
            to_status=StageStatus(_required_body_value(request, "to_status")),
            expected_revision=request.expected_revision,
            intent=TransitionIntent(
                cast(str, request.body.get("intent", TransitionIntent.NORMAL.value))
            ),
            reason=_optional_reason(request),
        )
        return _result(
            revision=transition.revision,
            service_generation=self._service_generation,
            body={"transition": transition.to_dict()},
        )

    def _bind_coordinator_admission(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        receipt = self._repository.bind_coordinator_admission(
            _required_run_uri(request),
            CoordinatorAdmissionRequest.from_dict(
                _required_body_value(request, "request")
            ),
        )
        return _result(
            service_generation=self._service_generation,
            body={"receipt": receipt.to_dict()},
        )

    def _install_cancellation_epoch(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        receipt = self._repository.install_cancellation_epoch(
            _required_run_uri(request),
            CancellationEpochRequest.from_dict(
                _required_body_value(request, "request")
            ),
        )
        return _result(
            revision=self._repository.open_run(_required_run_uri(request)).revision,
            service_generation=self._service_generation,
            body={"receipt": receipt.to_dict()},
        )

    def _read_cancellation_epoch(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        receipt = self._repository.read_cancellation_epoch_receipt(
            _required_run_uri(request),
            _required_body_string(request, "operation_id"),
        )
        return _result(
            service_generation=self._service_generation,
            body={"receipt": None if receipt is None else receipt.to_dict()},
        )

    def _finalize_cancellation(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        status = self._repository.finalize_cancellation(
            _required_run_uri(request),
            CancellationEpochRequest.from_dict(
                _required_body_value(request, "request")
            ),
        )
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            service_generation=self._service_generation,
            body={"status": status.value},
        )

    def _ensure_prepared_attempt(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        receipt = self._repository.ensure_prepared_attempt(
            _required_run_uri(request),
            PreparedAttemptRequest.from_dict(
                _required_body_value(request, "request")
            ),
        )
        return _result(
            revision=receipt.attempt.revision,
            service_generation=self._service_generation,
            body={"receipt": receipt.to_dict()},
        )

    def _bind_prepared_attempt(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        self._repository.bind_prepared_attempt(
            _required_run_uri(request),
            assignment_id=_required_body_string(request, "assignment_id"),
            attempt_id=_required_body_string(request, "attempt_id"),
        )
        return self._coordinator_ack(request)

    def _unbind_prepared_attempt(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        self._repository.unbind_prepared_attempt(
            _required_run_uri(request),
            assignment_id=_required_body_string(request, "assignment_id"),
            attempt_id=_required_body_string(request, "attempt_id"),
        )
        return self._coordinator_ack(request)

    def _grant_prepared_attempt(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        fence = self._repository.grant_prepared_attempt(
            _required_run_uri(request),
            assignment_id=_required_body_string(request, "assignment_id"),
            attempt_id=_required_body_string(request, "attempt_id"),
        )
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            service_generation=self._service_generation,
            body={"fence": _execution_fence_dict(fence)},
        )

    def _confirm_execution_started(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        self._repository.confirm_execution_started(
            _required_run_uri(request), fence=_execution_fence(request)
        )
        return self._coordinator_ack(request)

    def _record_managed_terminal(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        transition = self._repository.record_managed_attempt_terminal(
            _required_run_uri(request),
            fence=_execution_fence(request),
            status=StageStatus(_required_body_value(request, "status")),
            reason=_required_reason(request),
        )
        return _result(
            revision=transition.revision,
            service_generation=self._service_generation,
            body={"transition": transition.to_dict()},
        )

    def _close_managed_fence(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        expected_state_version = _required_body_value(
            request, "expected_state_version"
        )
        if isinstance(expected_state_version, bool) or not isinstance(
            expected_state_version, int
        ):
            raise AuthorityMutationValidationError(
                "expected_state_version must be an integer"
            )
        transition = self._repository.close_managed_attempt_fence(
            _required_run_uri(request),
            recovery_id=_required_body_string(request, "recovery_id"),
            fence=_execution_fence(request),
            expected_state_version=expected_state_version,
            status=StageStatus(_required_body_value(request, "status")),
            reason=_required_reason(request),
        )
        return _result(
            revision=transition.revision,
            service_generation=self._service_generation,
            body={"transition": transition.to_dict()},
        )

    def _record_managed_output(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        commit = self._repository.record_managed_output_commit(
            _required_run_uri(request),
            _required_stage_name(request),
            assignment_id=_required_body_string(request, "assignment_id"),
            attempt_id=_required_body_string(request, "attempt_id"),
            fencing_token=_required_fencing_token(request),
            outputs=_outputs(request),
            supersedes_commit_id=_optional_body_string(
                request, "supersedes_commit_id"
            ),
            reason=_optional_reason(request),
        )
        return _result(
            revision=commit.commit.revision,
            service_generation=self._service_generation,
            body={"commit": commit.to_dict()},
        )

    def _write_reliability_policy(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        revision = self._repository.write_reliability_policy_fact(
            _required_run_uri(request),
            ReliabilityPolicyFact.from_dict(
                _required_body_value(request, "fact")
            ),
        )
        return _result(revision=revision, service_generation=self._service_generation)

    def _list_reliability_policies(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        facts = self._repository.list_reliability_policy_facts(
            _required_run_uri(request),
            stage_name=_optional_body_string(request, "stage_name"),
        )
        return _result(
            service_generation=self._service_generation,
            body={"facts": [fact.to_dict() for fact in facts]},
        )

    def _write_reliability_status(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        revision = self._repository.write_reliability_status_detail(
            _required_run_uri(request),
            ReliabilityStatusDetail.from_dict(
                _required_body_value(request, "detail")
            ),
        )
        return _result(revision=revision, service_generation=self._service_generation)

    def _list_reliability_statuses(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        details = self._repository.list_reliability_status_details(
            _required_run_uri(request),
            stage_name=_optional_body_string(request, "stage_name"),
        )
        return _result(
            service_generation=self._service_generation,
            body={"details": [detail.to_dict() for detail in details]},
        )

    def _write_attempt_transaction(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        revision = self._repository.write_stage_attempt_transaction(
            _required_run_uri(request),
            StageAttemptTransaction.from_dict(
                _required_body_value(request, "transaction")
            ),
        )
        return _result(revision=revision, service_generation=self._service_generation)

    def _read_transaction_chain(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        transactions = self._repository.read_transaction_chain(
            _required_run_uri(request),
            _required_body_string(request, "transaction_id"),
        )
        return _result(
            service_generation=self._service_generation,
            body={
                "transactions": [transaction.to_dict() for transaction in transactions]
            },
        )

    def _list_attempt_transactions(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        transactions = self._repository.list_stage_attempt_transactions(
            _required_run_uri(request),
            stage_name=_optional_body_string(request, "stage_name"),
        )
        return _result(
            service_generation=self._service_generation,
            body={
                "transactions": [transaction.to_dict() for transaction in transactions]
            },
        )

    def _write_retry_decision(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        revision = self._repository.write_retry_decision(
            _required_run_uri(request),
            RetryDecisionRecord.from_dict(
                _required_body_value(request, "decision")
            ),
        )
        return _result(revision=revision, service_generation=self._service_generation)

    def _list_retry_decisions(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        decisions = self._repository.list_retry_decisions(
            _required_run_uri(request),
            stage_name=_optional_body_string(request, "stage_name"),
        )
        return _result(
            service_generation=self._service_generation,
            body={"decisions": [decision.to_dict() for decision in decisions]},
        )

    def _write_timeout_outcome(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        revision = self._repository.write_timeout_outcome(
            _required_run_uri(request),
            TimeoutOutcomeRecord.from_dict(
                _required_body_value(request, "outcome")
            ),
        )
        return _result(revision=revision, service_generation=self._service_generation)

    def _list_timeout_outcomes(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        outcomes = self._repository.list_timeout_outcomes(
            _required_run_uri(request),
            stage_name=_optional_body_string(request, "stage_name"),
        )
        return _result(
            service_generation=self._service_generation,
            body={"outcomes": [outcome.to_dict() for outcome in outcomes]},
        )

    def _coordinator_ack(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            service_generation=self._service_generation,
        )

    def _admit_run(self, request: AuthorityProtocolRequest) -> AuthorityProtocolResult:
        revision = self._repository.admit_run(
            _required_run_uri(request),
            status=RunStatus(_body_value(request, "status", RunStatus.CREATED.value)),
            metadata=_optional_body_mapping(request, "metadata"),
            idempotency_key=request.metadata.idempotency_key,
        )
        return _result(revision=revision, service_generation=self._service_generation)

    def _open_run(self, request: AuthorityProtocolRequest) -> AuthorityProtocolResult:
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            snapshot=snapshot,
            service_generation=self._service_generation,
        )

    def _transition_run(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        transition = self._repository.transition_run(
            _required_run_uri(request),
            from_status=RunStatus(_required_body_value(request, "from_status")),
            to_status=RunStatus(_required_body_value(request, "to_status")),
            expected_revision=request.expected_revision,
            intent=TransitionIntent(
                cast(str, request.body.get("intent", TransitionIntent.NORMAL.value))
            ),
            reason=_optional_reason(request),
        )
        return _result(
            revision=transition.revision,
            service_generation=self._service_generation,
            body={"transition": transition.to_dict()},
        )

    def _scan_run_recovery(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        run_uri = _required_run_uri(request)
        records = self._repository.scan_recovery(run_uri)
        return _result(
            service_generation=self._service_generation,
            recovery_records=records,
        )

    def _acquire_controller_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.acquire_controller_lease(
            _required_run_uri(request),
            owner_id=_required_owner_id(request),
            lease_ttl_seconds=_required_positive_seconds(request),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _renew_controller_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.renew_controller_lease(
            _required_run_uri(request),
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            lease_ttl_seconds=_required_positive_seconds(request),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _release_controller_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.release_controller_lease(
            _required_run_uri(request),
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            expected_revision=request.expected_revision,
            reason=_optional_reason(request),
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _fail_controller_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.fail_controller_lease(
            _required_run_uri(request),
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            reason=_required_reason(request),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _write_submitted_operation(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        record = SubmittedOperationRecord.from_dict(
            _required_body_value(request, "record")
        )
        revision = self._repository.write_submitted_operation(
            _required_run_uri(request),
            record,
            expected_revision=request.expected_revision,
        )
        return _result(revision=revision, service_generation=self._service_generation)

    def _read_submitted_operation(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        operation = self._repository.read_submitted_operation(
            _required_run_uri(request),
            _required_submission_id(request),
        )
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            submitted_operation=operation,
            service_generation=self._service_generation,
        )

    def _list_submitted_operations(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        operations = self._repository.list_submitted_operations(
            _required_run_uri(request)
        )
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            submitted_operations=operations,
            service_generation=self._service_generation,
        )

    def _transition_stage(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        from_status_value = request.body.get("from_status")
        transition = self._repository.transition_stage(
            _required_run_uri(request),
            _required_stage_name(request),
            from_status=None
            if from_status_value is None
            else StageStatus(cast(str, from_status_value)),
            to_status=StageStatus(_required_body_value(request, "to_status")),
            expected_revision=request.expected_revision,
            intent=TransitionIntent(
                cast(str, request.body.get("intent", TransitionIntent.NORMAL.value))
            ),
            reason=_optional_reason(request),
        )
        return _result(
            revision=transition.revision,
            service_generation=self._service_generation,
            body={"transition": transition.to_dict()},
        )

    def _allocate_stage_attempt(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        allocation = self._repository.allocate_stage_attempt(
            _required_run_uri(request),
            _required_stage_name(request),
            owner_id=_required_owner_id(request),
            lease_ttl_seconds=_optional_positive_seconds(request),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=allocation.attempt.revision,
            service_generation=self._service_generation,
            stage_attempt=allocation.attempt,
            lease=allocation.lease,
        )

    def _renew_stage_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.renew_stage_lease(
            _required_run_uri(request),
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            lease_ttl_seconds=_required_positive_seconds(request),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _release_stage_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.release_stage_lease(
            _required_run_uri(request),
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            expected_revision=request.expected_revision,
            reason=_optional_reason(request),
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _fail_stage_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.fail_stage_lease(
            _required_run_uri(request),
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            reason=_required_reason(request),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _finish_stage_attempt(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        attempt = self._repository.finish_stage_attempt(
            _required_run_uri(request),
            _required_stage_name(request),
            attempt_id=_required_body_string(request, "attempt_id"),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            to_status=StageStatus(_required_body_value(request, "to_status")),
            expected_revision=request.expected_revision,
            service_generation=request.metadata.service_generation,
            reason=_optional_reason(request),
        )
        return _result(
            revision=attempt.revision,
            service_generation=self._service_generation,
            stage_attempt=attempt,
        )

    def _record_output_commit(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        commit = self._repository.record_output_commit(
            _required_run_uri(request),
            _required_stage_name(request),
            attempt_id=_required_body_string(request, "attempt_id"),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            outputs=_outputs(request),
            supersedes_commit_id=_optional_body_string(request, "supersedes_commit_id"),
            expected_revision=request.expected_revision,
            service_generation=request.metadata.service_generation,
            reason=_optional_reason(request),
        )
        return _result(
            revision=commit.commit.revision,
            service_generation=self._service_generation,
            output_commit=commit.commit,
            artifact_facts=commit.artifact_facts,
            cleanup_candidates=commit.cleanup_candidates,
        )

    def _list_output_commits(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        commits = self._repository.list_output_commits(
            _required_run_uri(request), stage_name=request.stage_name
        )
        snapshot = self._repository.open_run(_required_run_uri(request))
        return _result(
            revision=snapshot.revision,
            service_generation=self._service_generation,
            output_commits=commits,
        )

    def _append_cleanup_report(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        fact = self._repository.append_cleanup_report(
            _required_run_uri(request),
            CleanupReport.from_dict(_required_body_value(request, "report")),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=fact.revision,
            service_generation=self._service_generation,
            cleanup_reports=(fact,),
        )

    def _list_cleanup_reports(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        facts = self._repository.list_cleanup_reports(_required_run_uri(request))
        return _result(
            service_generation=self._service_generation,
            cleanup_reports=facts,
        )

    def _append_cleanup_result(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        fact = self._repository.append_cleanup_result(
            _required_run_uri(request),
            CleanupResult.from_dict(_required_body_value(request, "result")),
            expected_revision=request.expected_revision,
        )
        return _result(
            revision=fact.revision,
            service_generation=self._service_generation,
            cleanup_results=(fact,),
        )

    def _list_cleanup_results(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        facts = self._repository.list_cleanup_results(_required_run_uri(request))
        return _result(
            service_generation=self._service_generation,
            cleanup_results=facts,
        )

    def _create_workspace(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        workspace = WorkspaceIdentity.from_dict(
            _required_body_value(request, "workspace")
        )
        revision = self._repository.create_workspace(workspace)
        return _result(
            revision=revision,
            service_generation=self._service_generation,
            workspace=workspace,
        )

    def _create_sweep(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        sweep = SweepIdentity.from_dict(_required_body_value(request, "sweep"))
        revision = self._repository.create_sweep(sweep)
        return _result(
            revision=revision,
            service_generation=self._service_generation,
            sweep=sweep,
        )

    def _record_trial(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        trial = TrialReference.from_dict(_required_body_value(request, "trial"))
        revision = self._repository.record_trial(trial)
        return _result(
            revision=revision,
            service_generation=self._service_generation,
            trial=trial,
        )

    def _import_offline_evidence(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        manifest_data = _required_body_value(request, "manifest")
        manifest = OfflineEvidenceManifest.from_dict(manifest_data)
        result = import_offline_evidence_manifest(
            self._repository,
            manifest,
            imported_by=_body_string(request, "imported_by", "authority-service"),
            workspace_id=self._workspace_id,
        )
        return _result(
            revision=self._repository.open_run(result.run_uri).revision,
            service_generation=self._service_generation,
            body={"offline_import": result.to_dict()},
        )

    def _list_trials(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        trials = self._repository.list_trials(
            _required_body_string(request, "sweep_id")
        )
        return _result(service_generation=self._service_generation, trials=trials)

    def _acquire_trial_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.acquire_trial_lease(
            _required_body_string(request, "sweep_id"),
            _required_body_string(request, "trial_id"),
            owner_id=_required_owner_id(request),
            lease_ttl_seconds=_required_positive_seconds(request),
        )
        return _result(
            revision=lease.lease.revision,
            service_generation=self._service_generation,
            lease=lease.lease,
            trial_lease=lease,
        )

    def _acquire_resource_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.acquire_resource_lease(
            _required_body_string(request, "workspace_id"),
            _required_body_string(request, "resource_key"),
            owner_id=_required_owner_id(request),
            amount=_optional_body_positive_int(request, "amount", default=1),
            lease_ttl_seconds=_required_positive_seconds(request),
        )
        return _result(
            revision=lease.lease.revision,
            service_generation=self._service_generation,
            lease=lease.lease,
            resource_lease=lease,
        )

    def _renew_coordination_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.renew_coordination_lease(
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            lease_ttl_seconds=_required_positive_seconds(request),
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _release_coordination_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.release_coordination_lease(
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            reason=_optional_reason(request),
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _fail_coordination_lease(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        lease = self._repository.fail_coordination_lease(
            _required_lease_id(request),
            owner_id=_required_owner_id(request),
            fencing_token=_required_fencing_token(request),
            reason=_required_reason(request),
        )
        return _result(
            revision=lease.revision,
            service_generation=self._service_generation,
            lease=lease,
        )

    def _set_counter_limit(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        counter = self._repository.set_counter_limit(
            _required_body_string(request, "workspace_id"),
            _required_body_string(request, "counter_name"),
            limit=_optional_body_int(request, "limit"),
        )
        return _result(
            revision=counter.revision,
            service_generation=self._service_generation,
            counter=counter,
        )

    def _set_resource_limit(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        counter = self._repository.set_resource_limit(
            _required_body_string(request, "workspace_id"),
            _required_body_string(request, "resource_key"),
            limit=_optional_body_int(request, "limit"),
        )
        return _result(
            revision=counter.revision,
            service_generation=self._service_generation,
            counter=counter,
        )

    def _ensure_resource_limits(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        counters = self._repository.ensure_resource_limits(
            _required_body_string(request, "workspace_id"),
            _required_body_positive_int_mapping(request, "limits"),
        )
        return _result(
            revision=max(
                (counter.revision for counter in counters),
                key=lambda item: item.sequence,
                default=None,
            ),
            service_generation=self._service_generation,
            body={"counters": [counter.to_dict() for counter in counters]},
        )

    def _read_resource_limit(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        counter = self._repository.read_resource_limit(
            _required_body_string(request, "workspace_id"),
            _required_body_string(request, "resource_key"),
        )
        return _result(service_generation=self._service_generation, counter=counter)

    def _increment_counter(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        counter = self._repository.increment_counter(
            _required_body_string(request, "workspace_id"),
            _required_body_string(request, "counter_name"),
            amount=_optional_body_positive_int(request, "amount", default=1),
            limit=_optional_body_int(request, "limit"),
        )
        return _result(
            revision=counter.revision,
            service_generation=self._service_generation,
            counter=counter,
        )

    def _decrement_counter(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        counter = self._repository.decrement_counter(
            _required_body_string(request, "workspace_id"),
            _required_body_string(request, "counter_name"),
            amount=_optional_body_positive_int(request, "amount", default=1),
        )
        return _result(
            revision=counter.revision,
            service_generation=self._service_generation,
            counter=counter,
        )

    def _read_counter(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        counter = self._repository.read_counter(
            _required_body_string(request, "workspace_id"),
            _required_body_string(request, "counter_name"),
        )
        return _result(service_generation=self._service_generation, counter=counter)

    def _scan_coordination_recovery(
        self, request: AuthorityProtocolRequest
    ) -> AuthorityProtocolResult:
        records = self._repository.scan_coordination_recovery(
            _required_body_string(request, "workspace_id")
        )
        return _result(
            service_generation=self._service_generation,
            coordination_recovery_records=records,
        )


def unsupported_mutation_response(
    operation: AuthorityMutationOperation,
    payload: Mapping[str, object],
    *,
    service_generation: str,
    workspace_id: str | None,
) -> AuthorityProtocolResponse:
    """Return a structured unsupported-capability response for skeleton apps."""

    metadata = _fallback_metadata(
        operation,
        payload,
        service_generation=service_generation,
        workspace_id=workspace_id,
    )
    return rejected_authority_response(
        metadata,
        AuthorityProtocolRejection(
            category=AuthorityProtocolErrorCategory.UNSUPPORTED_CAPABILITY,
            code="authority_mutations_not_configured",
            message="authority mutation service is not configured",
            detail={"operation": operation.value},
        ),
    )


def operation_kind_for(
    operation: AuthorityMutationOperation,
) -> AuthorityProtocolOperationKind:
    """Return the protocol operation family for a route operation."""

    return _OPERATION_KIND_BY_MUTATION[operation]


def _result(
    *,
    revision: BackendRevision | None = None,
    service_generation: str | None = None,
    lease: LeaseRecord | None = None,
    snapshot: AuthoritativeRunSnapshot | None = None,
    stage_attempt: StageAttempt | None = None,
    output_commit: OutputCommitRecord | None = None,
    output_commits: tuple[OutputCommit, ...] = (),
    submitted_operation: SubmittedOperationRecord | None = None,
    workspace: WorkspaceIdentity | None = None,
    sweep: SweepIdentity | None = None,
    trial: TrialReference | None = None,
    trial_lease: TrialLeaseRecord | None = None,
    resource_lease: ResourceLeaseRecord | None = None,
    counter: ConcurrencyCounter | None = None,
    artifact_facts: tuple[ArtifactFactRecord, ...] = (),
    submitted_operations: tuple[SubmittedOperationRecord, ...] = (),
    trials: tuple[TrialReference, ...] = (),
    cleanup_candidates: tuple[CleanupCandidate, ...] = (),
    cleanup_reports: tuple[CleanupReportFact, ...] = (),
    cleanup_results: tuple[CleanupResultFact, ...] = (),
    recovery_records: tuple[RecoveryRecord, ...] = (),
    coordination_recovery_records: tuple[CoordinationRecoveryRecord, ...] = (),
    body: Mapping[str, PlainData] | None = None,
) -> AuthorityProtocolResult:
    return AuthorityProtocolResult(
        revision=revision,
        service_generation=service_generation,
        lease=lease,
        snapshot=snapshot,
        stage_attempt=stage_attempt,
        output_commit=output_commit,
        output_commits=output_commits,
        submitted_operation=submitted_operation,
        workspace=workspace,
        sweep=sweep,
        trial=trial,
        trial_lease=trial_lease,
        resource_lease=resource_lease,
        counter=counter,
        artifact_facts=artifact_facts,
        submitted_operations=submitted_operations,
        trials=trials,
        cleanup_candidates=cleanup_candidates,
        cleanup_reports=cleanup_reports,
        cleanup_results=cleanup_results,
        recovery_records=recovery_records,
        coordination_recovery_records=coordination_recovery_records,
        body={} if body is None else body,
    )


def _required_run_uri(request: AuthorityProtocolRequest) -> str:
    if request.run_uri is None:
        raise AuthorityMutationValidationError("run_uri is required")
    return request.run_uri


def _required_stage_name(request: AuthorityProtocolRequest) -> str:
    if request.stage_name is None:
        raise AuthorityMutationValidationError("stage_name is required")
    return request.stage_name


def _required_submission_id(request: AuthorityProtocolRequest) -> str:
    if request.submission_id is None:
        raise AuthorityMutationValidationError("submission_id is required")
    return request.submission_id


def _required_lease_id(request: AuthorityProtocolRequest) -> str:
    if request.lease_id is None:
        raise AuthorityMutationValidationError("lease_id is required")
    return request.lease_id


def _required_fencing_token(request: AuthorityProtocolRequest) -> str:
    if request.fencing_token is None:
        raise AuthorityMutationValidationError("fencing_token is required")
    return request.fencing_token


def _required_owner_id(request: AuthorityProtocolRequest) -> str:
    if request.owner_id is None:
        raise AuthorityMutationValidationError("owner_id is required")
    return request.owner_id


def _required_body_value(
    request: AuthorityProtocolRequest,
    field: str,
) -> PlainData:
    if field not in request.body:
        raise AuthorityMutationValidationError(f"{field} is required")
    return request.body[field]


def _body_value(
    request: AuthorityProtocolRequest,
    field: str,
    default: PlainData,
) -> PlainData:
    return request.body.get(field, default)


def _required_body_string(request: AuthorityProtocolRequest, field: str) -> str:
    value = _required_body_value(request, field)
    if not isinstance(value, str) or not value:
        raise AuthorityMutationValidationError(f"{field} must be a non-empty string")
    return value


def _body_string(request: AuthorityProtocolRequest, field: str, default: str) -> str:
    value = request.body.get(field, default)
    if not isinstance(value, str) or not value:
        raise AuthorityMutationValidationError(f"{field} must be a non-empty string")
    return value


def _optional_body_string(request: AuthorityProtocolRequest, field: str) -> str | None:
    value = request.body.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise AuthorityMutationValidationError(f"{field} must be a non-empty string")
    return value


def _optional_body_mapping(
    request: AuthorityProtocolRequest,
    field: str,
) -> Mapping[str, PlainData] | None:
    value = request.body.get(field)
    if value is None:
        return None
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise AuthorityMutationValidationError(f"{field} must be a mapping")
    return cast(Mapping[str, PlainData], value)


def _required_body_positive_int_mapping(
    request: AuthorityProtocolRequest, field: str
) -> Mapping[str, int]:
    value = _required_body_value(request, field)
    if not isinstance(value, Mapping):
        raise AuthorityMutationValidationError(f"{field} must be a mapping")
    normalized: dict[str, int] = {}
    for key, limit in value.items():
        if not isinstance(key, str) or not key:
            raise AuthorityMutationValidationError(
                f"{field} keys must be non-empty strings"
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise AuthorityMutationValidationError(
                f"{field} values must be positive integers"
            )
        normalized[key] = limit
    return normalized


def _required_positive_seconds(request: AuthorityProtocolRequest) -> int:
    value = _required_body_value(request, "lease_ttl_seconds")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthorityMutationValidationError(
            "lease_ttl_seconds must be a positive integer"
        )
    return value


def _optional_positive_seconds(request: AuthorityProtocolRequest) -> int | None:
    value = request.body.get("lease_ttl_seconds")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthorityMutationValidationError(
            "lease_ttl_seconds must be a positive integer"
        )
    return value


def _optional_body_int(request: AuthorityProtocolRequest, field: str) -> int | None:
    value = request.body.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AuthorityMutationValidationError(f"{field} must be an integer or null")
    return value


def _optional_body_positive_int(
    request: AuthorityProtocolRequest, field: str, *, default: int
) -> int:
    value = request.body.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AuthorityMutationValidationError(f"{field} must be a positive integer")
    return value


def _optional_reason(request: AuthorityProtocolRequest) -> LifecycleReason | None:
    reason = request.body.get("reason")
    if reason is None:
        return None
    return LifecycleReason.from_dict(reason)


def _required_reason(request: AuthorityProtocolRequest) -> LifecycleReason:
    reason = _optional_reason(request)
    if reason is None:
        raise AuthorityMutationValidationError("reason is required")
    return reason


def _outputs(request: AuthorityProtocolRequest) -> Mapping[str, ArtifactRef]:
    value = _required_body_value(request, "outputs")
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise AuthorityMutationValidationError("outputs must be a mapping")
    return {
        key: ArtifactRef.from_dict(artifact)
        for key, artifact in cast(Mapping[str, object], value).items()
    }


def _execution_fence(request: AuthorityProtocolRequest) -> ExecutionFence:
    value = _required_body_value(request, "fence")
    if not isinstance(value, Mapping):
        raise AuthorityMutationValidationError("fence must be a mapping")
    allowed = {"assignment_id", "attempt_id", "fencing_token"}
    if set(value) != allowed:
        raise AuthorityMutationValidationError(
            "fence must contain assignment_id, attempt_id, and fencing_token"
        )
    return ExecutionFence(
        assignment_id=_mapping_string(value, "assignment_id"),
        attempt_id=_mapping_string(value, "attempt_id"),
        fencing_token=_mapping_string(value, "fencing_token"),
    )


def _execution_fence_dict(fence: ExecutionFence) -> dict[str, PlainData]:
    return {
        "assignment_id": fence.assignment_id,
        "attempt_id": fence.attempt_id,
        "fencing_token": fence.fencing_token,
    }


def _mapping_string(value: Mapping[str, PlainData], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise AuthorityMutationValidationError(f"{field} must be a non-empty string")
    return item


def _fallback_metadata(
    operation: AuthorityMutationOperation,
    payload: Mapping[str, object],
    *,
    service_generation: str,
    workspace_id: str | None,
) -> AuthorityProtocolMetadata:
    request_id = "invalid-request"
    operation_kind = operation_kind_for(operation)
    idempotency_key = None
    raw_metadata = payload.get("metadata")
    if isinstance(raw_metadata, Mapping):
        raw_request_id = raw_metadata.get("request_id")
        if isinstance(raw_request_id, str) and raw_request_id:
            request_id = raw_request_id
        raw_operation_kind = raw_metadata.get("operation_kind")
        if isinstance(raw_operation_kind, str):
            try:
                operation_kind = AuthorityProtocolOperationKind(raw_operation_kind)
            except ValueError:
                operation_kind = operation_kind_for(operation)
        raw_idempotency_key = raw_metadata.get("idempotency_key")
        if isinstance(raw_idempotency_key, str) and raw_idempotency_key:
            idempotency_key = raw_idempotency_key
    return AuthorityProtocolMetadata(
        request_id=request_id,
        operation_kind=operation_kind,
        service_generation=service_generation,
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
    )


def _compatibility_rejection(
    exc: AuthorityRepositoryCompatibilityError,
) -> AuthorityProtocolRejection:
    return AuthorityProtocolRejection(
        category=_COMPATIBILITY_CATEGORY_BY_KIND[exc.failure.kind],
        code=exc.failure.code,
        message=exc.failure.message,
        detail=exc.failure.to_dict(),
    )


def _repository_rejection(
    exc: AuthorityRepositoryError,
    *,
    request_detail: Mapping[str, PlainData],
) -> AuthorityProtocolRejection:
    message = str(exc)
    category = _repository_category(message)
    return AuthorityProtocolRejection(
        category=category,
        code=_repository_code(category, message),
        message=message,
        detail=request_detail,
    )


def _offline_import_rejection(
    exc: OfflineImportError,
    *,
    request_detail: Mapping[str, PlainData],
) -> AuthorityProtocolRejection:
    category = (
        AuthorityProtocolErrorCategory.CONFLICT
        if exc.kind is OfflineImportRejectionKind.CONFLICT
        else AuthorityProtocolErrorCategory.INTERNAL_ERROR
        if exc.kind is OfflineImportRejectionKind.TRANSACTION
        else AuthorityProtocolErrorCategory.VALIDATION
    )
    return AuthorityProtocolRejection(
        category=category,
        code=f"authority_offline_import_{exc.kind.value}",
        message=str(exc),
        detail={
            **dict(request_detail),
            "diagnostics": [diagnostic.to_dict() for diagnostic in exc.diagnostics],
        },
    )


def _value_error_rejection(
    exc: ValueError,
    *,
    request_detail: Mapping[str, PlainData],
) -> AuthorityProtocolRejection:
    message = str(exc)
    category = _repository_category(message)
    code = (
        "authority_mutation_conflict"
        if category is AuthorityProtocolErrorCategory.CONFLICT
        else "authority_mutation_validation"
    )
    return AuthorityProtocolRejection(
        category=category,
        code=code,
        message=message,
        detail=request_detail,
    )


def _coordination_rejection(
    exc: CoordinationStoreError,
    *,
    request_detail: Mapping[str, PlainData],
) -> AuthorityProtocolRejection:
    category = {
        CoordinationFailureKind.CAPACITY: AuthorityProtocolErrorCategory.CONFLICT,
        CoordinationFailureKind.INVALID_OR_UNSUPPORTED: (
            AuthorityProtocolErrorCategory.VALIDATION
        ),
        CoordinationFailureKind.UNAVAILABLE: (
            AuthorityProtocolErrorCategory.UNAVAILABLE_SERVICE
        ),
        CoordinationFailureKind.OWNERSHIP_LOST: (
            AuthorityProtocolErrorCategory.STALE_FENCING
        ),
        CoordinationFailureKind.INTERNAL: AuthorityProtocolErrorCategory.INTERNAL_ERROR,
    }[exc.kind]
    return AuthorityProtocolRejection(
        category=category,
        code=f"coordination_{exc.kind.value}",
        message=str(exc),
        detail=request_detail,
    )


def _repository_category(message: str) -> AuthorityProtocolErrorCategory:
    if message == "stale service generation":
        return AuthorityProtocolErrorCategory.STALE_GENERATION
    if message == "stale or foreign fencing token":
        return AuthorityProtocolErrorCategory.STALE_FENCING
    if "lease has expired" in message or "lease is not active" in message:
        return AuthorityProtocolErrorCategory.STALE_FENCING
    if message.startswith("stale "):
        return AuthorityProtocolErrorCategory.STALE_REVISION
    if (
        "already" in message
        or "terminal" in message
        or "not running" in message
        or "active lease" in message
        or "counter limit" in message
        or "resource limit" in message
    ):
        return AuthorityProtocolErrorCategory.CONFLICT
    return AuthorityProtocolErrorCategory.VALIDATION


def _repository_code(
    category: AuthorityProtocolErrorCategory,
    message: str,
) -> str:
    if category is AuthorityProtocolErrorCategory.STALE_GENERATION:
        return "authority_repository_stale_generation"
    if category is AuthorityProtocolErrorCategory.STALE_REVISION:
        return "authority_repository_stale_revision"
    if category is AuthorityProtocolErrorCategory.STALE_FENCING:
        return "authority_repository_stale_fencing"
    if category is AuthorityProtocolErrorCategory.CONFLICT:
        return "authority_repository_conflict"
    if "unknown run" in message:
        return "authority_repository_unknown_run"
    return "authority_repository_validation"


def _request_detail(payload: Mapping[str, object]) -> Mapping[str, PlainData]:
    detail: dict[str, PlainData] = {}
    run_uri = payload.get("run_uri")
    if isinstance(run_uri, str):
        detail["run_uri"] = run_uri
    stage_name = payload.get("stage_name")
    if isinstance(stage_name, str):
        detail["stage_name"] = stage_name
    lease_id = payload.get("lease_id")
    if isinstance(lease_id, str):
        detail["lease_id"] = lease_id
    expected_revision = payload.get("expected_revision")
    if isinstance(expected_revision, Mapping):
        detail["expected_revision"] = dict(
            cast(Mapping[str, PlainData], expected_revision)
        )
    return detail


__all__ = [
    "AuthorityMutationOperation",
    "AuthorityMutationService",
    "AuthorityMutationValidationError",
    "operation_kind_for",
    "unsupported_mutation_response",
]

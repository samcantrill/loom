"""Public authority-store factory."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup.records import CleanupReport, CleanupResult
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData

from .authority import (
    AttemptAllocation,
    AuthorityStoreError,
    OutputCommit,
    PerRunAuthorityStore,
    RunStore,
    StageStore,
    StatusTransition,
)
from .capabilities import BackendCapabilitySet
from .config import AuthorityBackendKind, AuthorityConfig
from .authority_factory import (
    AuthorityFactoryError,
    config_from_authority_reference,
    require_online_authority,
    resolve_authority_for_factory,
)
from .authority_resolution import AuthorityResolutionMode
from .read_models import (
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    CleanupReportFact,
    CleanupResultFact,
    LeaseRecord,
    LifecycleReason,
    RecoveryRecord,
    ReliabilityPolicyFact,
    StageLifecycleSnapshot,
)
from .schema_policy import AuthoritySchemaCheck


def create_run_store(
    config: AuthorityConfig | Mapping[str, object] | None = None,
    *,
    authority_store: PerRunAuthorityStore | None = None,
    authority_mode: AuthorityResolutionMode = AuthorityResolutionMode.ONLINE_MUTATION,
    workspace_root: str | Path | None = None,
    allocation_id: str | None = None,
    expected_workspace_id: str | None = None,
    expected_generation: str | None = None,
) -> RunStore:
    """Create the public authority-backed run-store surface.

    The default runtime authority is service-backed. Explicit per-run authority
    store injection remains available for tests and custom integrations.
    """

    if authority_store is not None:
        resolved_config = _resolve_config(config, authority_store=authority_store)
        _validate_authority_store(authority_store)
        return _PerRunAuthorityRunStore(authority_store, resolved_config)
    resolved_input_config = _resolve_config(config, authority_store=None)
    if resolved_input_config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
        raise AuthorityStoreError(_removed_sqlite_authority_message())
    resolution = resolve_authority_for_factory(
        resolved_input_config,
        authority_mode=authority_mode,
        workspace_root=workspace_root,
        allocation_id=allocation_id,
        expected_workspace_id=expected_workspace_id,
        expected_generation=expected_generation,
    )
    reference = require_online_authority(
        resolution,
        purpose="public run-store factory",
    )
    resolved_config = config_from_authority_reference(reference)
    if resolved_config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
        raise AuthorityStoreError(_removed_sqlite_authority_message())
    if resolved_config.endpoint is not None and _is_http_endpoint(resolved_config.endpoint):
        raise AuthorityFactoryError(
            "public run-store factory cannot adapt HTTP authority endpoints until "
            "the runner online path migrates to AuthorityClient",
            code="authority_factory.http_store_adapter_deferred",
            resolution=resolution.result,
            context={
                "endpoint": resolved_config.endpoint,
                "deferred_to": "v10_phase_11",
            },
        )
    if resolved_config.backend_kind in {
        AuthorityBackendKind.CO_LOCATED_SERVICE,
        AuthorityBackendKind.MANAGED_SERVICE,
        AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
    }:
        from .service_authority import create_service_authority_store

        authority_store = create_service_authority_store(resolved_config)
        return _PerRunAuthorityRunStore(
            authority_store,
            _config_from_authority_store(authority_store, fallback=resolved_config),
        )
    raise AuthorityStoreError(
        "authority backend is not implemented in this phase: "
        f"{resolved_config.backend_kind.value}"
    )


class _PerRunAuthorityRunStore:
    def __init__(
        self, authority_store: PerRunAuthorityStore, config: AuthorityConfig
    ) -> None:
        self._authority_store = authority_store
        self._config = config

    def authority_config(self) -> AuthorityConfig:
        return self._config

    def capabilities(self) -> BackendCapabilitySet:
        return self._authority_store.capabilities()

    def check_schema(self, run_uri: str) -> AuthoritySchemaCheck:
        return self._authority_store.check_schema(run_uri)

    def admit_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
        idempotency_key: str | None = None,
    ) -> BackendRevision:
        return self._authority_store.create_run(
            run_uri,
            status=status,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return self._authority_store.open_run(run_uri)

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: LifecycleReason | None = None,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
    ) -> StatusTransition:
        return self._authority_store.transition_run(
            run_uri,
            from_status=from_status,
            to_status=to_status,
            expected_revision=expected_revision,
            intent=intent,
            reason=reason,
        )

    def acquire_run_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        return self._authority_store.acquire_controller_lease(
            run_uri,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        return self._authority_store.renew_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        return self._authority_store.release_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            reason=reason,
        )

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        return self._authority_store.fail_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            reason=reason,
        )

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> BackendRevision:
        return self._authority_store.write_submitted_operation(run_uri, record)

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        return self._authority_store.read_submitted_operation(run_uri, submission_id)

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        return self._authority_store.list_submitted_operations(run_uri)

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        return self._authority_store.write_reliability_policy_fact(run_uri, fact)

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        return self._authority_store.list_reliability_policy_facts(
            run_uri,
            stage_name=stage_name,
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        return self._authority_store.write_reliability_status_detail(run_uri, detail)

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return self._authority_store.list_reliability_status_details(
            run_uri,
            stage_name=stage_name,
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision:
        return self._authority_store.write_stage_attempt_transaction(
            run_uri,
            transaction,
        )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._authority_store.read_transaction_chain(run_uri, transaction_id)

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._authority_store.list_stage_attempt_transactions(
            run_uri,
            stage_name=stage_name,
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision:
        return self._authority_store.write_retry_decision(run_uri, decision)

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        return self._authority_store.list_retry_decisions(
            run_uri,
            stage_name=stage_name,
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision:
        return self._authority_store.write_timeout_outcome(run_uri, outcome)

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        return self._authority_store.list_timeout_outcomes(
            run_uri,
            stage_name=stage_name,
        )

    def stage_store(self, run_uri: str, stage_name: str) -> StageStore:
        _non_empty(run_uri, "run_uri")
        _non_empty(stage_name, "stage_name")
        return _PerRunAuthorityStageStore(self._authority_store, run_uri, stage_name)

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return self._authority_store.snapshot(run_uri)

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        return self._authority_store.scan_recovery(run_uri)

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        return self._authority_store.list_cleanup_candidates(run_uri)

    def append_cleanup_report(
        self, run_uri: str, report: CleanupReport
    ) -> CleanupReportFact:
        return self._authority_store.append_cleanup_report(run_uri, report)

    def list_cleanup_reports(self, run_uri: str) -> tuple[CleanupReportFact, ...]:
        return self._authority_store.list_cleanup_reports(run_uri)

    def append_cleanup_result(
        self, run_uri: str, result: CleanupResult
    ) -> CleanupResultFact:
        return self._authority_store.append_cleanup_result(run_uri, result)

    def list_cleanup_results(self, run_uri: str) -> tuple[CleanupResultFact, ...]:
        return self._authority_store.list_cleanup_results(run_uri)


class _PerRunAuthorityStageStore:
    def __init__(
        self, authority_store: PerRunAuthorityStore, run_uri: str, stage_name: str
    ) -> None:
        self._authority_store = authority_store
        self._run_uri = _non_empty(run_uri, "run_uri")
        self._stage_name = _non_empty(stage_name, "stage_name")

    @property
    def run_uri(self) -> str:
        return self._run_uri

    @property
    def stage_name(self) -> str:
        return self._stage_name

    def capabilities(self) -> BackendCapabilitySet:
        return self._authority_store.capabilities()

    def transition(
        self,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        reason: LifecycleReason | None = None,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
    ) -> StatusTransition:
        return self._authority_store.transition_stage(
            self._run_uri,
            self._stage_name,
            from_status=from_status,
            to_status=to_status,
            expected_revision=expected_revision,
            intent=intent,
            reason=reason,
        )

    def allocate_attempt(
        self,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation:
        return self._authority_store.allocate_stage_attempt(
            self._run_uri,
            self._stage_name,
            owner_id=owner_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        return self._authority_store.renew_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        return self._authority_store.release_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            reason=reason,
        )

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        return self._authority_store.fail_lease(
            lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            reason=reason,
        )

    def write_submitted_operation(
        self, record: SubmittedOperationRecord
    ) -> BackendRevision:
        return self._authority_store.write_submitted_operation(self._run_uri, record)

    def read_submitted_operation(
        self, submission_id: str
    ) -> SubmittedOperationRecord | None:
        return self._authority_store.read_submitted_operation(
            self._run_uri,
            submission_id,
        )

    def list_submitted_operations(self) -> tuple[SubmittedOperationRecord, ...]:
        return self._authority_store.list_submitted_operations(self._run_uri)

    def write_reliability_policy_fact(
        self, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        if fact.stage_name not in {None, self._stage_name}:
            raise AuthorityStoreError("reliability policy fact stage_name mismatch")
        return self._authority_store.write_reliability_policy_fact(
            self._run_uri,
            fact,
        )

    def list_reliability_policy_facts(self) -> tuple[ReliabilityPolicyFact, ...]:
        return self._authority_store.list_reliability_policy_facts(
            self._run_uri,
            stage_name=self._stage_name,
        )

    def write_reliability_status_detail(
        self, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        if detail.stage_id != self._stage_name:
            raise AuthorityStoreError("reliability status detail stage_id mismatch")
        return self._authority_store.write_reliability_status_detail(
            self._run_uri,
            detail,
        )

    def list_reliability_status_details(
        self,
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return self._authority_store.list_reliability_status_details(
            self._run_uri,
            stage_name=self._stage_name,
        )

    def write_stage_attempt_transaction(
        self, transaction: StageAttemptTransaction
    ) -> BackendRevision:
        if transaction.stage_id != self._stage_name:
            raise AuthorityStoreError("reliability transaction stage_id mismatch")
        return self._authority_store.write_stage_attempt_transaction(
            self._run_uri,
            transaction,
        )

    def read_transaction_chain(
        self, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._authority_store.read_transaction_chain(
            self._run_uri,
            transaction_id,
        )

    def list_stage_attempt_transactions(
        self,
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._authority_store.list_stage_attempt_transactions(
            self._run_uri,
            stage_name=self._stage_name,
        )

    def write_retry_decision(
        self, decision: RetryDecisionRecord
    ) -> BackendRevision:
        if decision.status.stage_id != self._stage_name:
            raise AuthorityStoreError("retry decision stage_id mismatch")
        return self._authority_store.write_retry_decision(self._run_uri, decision)

    def list_retry_decisions(self) -> tuple[RetryDecisionRecord, ...]:
        return self._authority_store.list_retry_decisions(
            self._run_uri,
            stage_name=self._stage_name,
        )

    def write_timeout_outcome(
        self, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision:
        if outcome.status.stage_id != self._stage_name:
            raise AuthorityStoreError("timeout outcome stage_id mismatch")
        return self._authority_store.write_timeout_outcome(self._run_uri, outcome)

    def list_timeout_outcomes(self) -> tuple[TimeoutOutcomeRecord, ...]:
        return self._authority_store.list_timeout_outcomes(
            self._run_uri,
            stage_name=self._stage_name,
        )

    def record_output_commit(
        self,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        reason: LifecycleReason | None = None,
    ) -> OutputCommit:
        return self._authority_store.record_output_commit(
            self._run_uri,
            self._stage_name,
            attempt_id=attempt_id,
            fencing_token=fencing_token,
            outputs=outputs,
            reason=reason,
        )

    def snapshot(self) -> StageLifecycleSnapshot:
        snapshot = self._authority_store.snapshot(self._run_uri)
        for stage in snapshot.stages:
            if stage.stage_name == self._stage_name:
                return stage
        return StageLifecycleSnapshot(
            stage_name=self._stage_name,
            status=StageStatus.PENDING,
            revision=snapshot.revision,
        )

    def scan_recovery(self) -> tuple[RecoveryRecord, ...]:
        return tuple(
            record
            for record in self._authority_store.scan_recovery(self._run_uri)
            if record.stage_name in {None, self._stage_name}
        )

    def list_cleanup_candidates(self) -> tuple[CleanupCandidate, ...]:
        return self._authority_store.list_cleanup_candidates(self._run_uri)


def _resolve_config(
    config: AuthorityConfig | Mapping[str, object] | None,
    *,
    authority_store: PerRunAuthorityStore | None,
) -> AuthorityConfig:
    if config is None:
        if authority_store is not None:
            return _config_from_authority_store(
                authority_store,
                fallback=AuthorityConfig(backend_kind=AuthorityBackendKind.TEST_FAKE),
            )
        return AuthorityConfig()
    if isinstance(config, AuthorityConfig):
        return config
    return AuthorityConfig.from_dict(config)


def _config_from_authority_store(
    authority_store: PerRunAuthorityStore,
    *,
    fallback: AuthorityConfig,
) -> AuthorityConfig:
    raw_config = getattr(authority_store, "authority_config", None)
    if isinstance(raw_config, AuthorityConfig):
        return raw_config
    if callable(raw_config):
        value = raw_config()
        if isinstance(value, AuthorityConfig):
            return value
    return fallback


def _validate_authority_store(authority_store: PerRunAuthorityStore) -> None:
    if not isinstance(authority_store, PerRunAuthorityStore):
        raise TypeError("authority_store must satisfy PerRunAuthorityStore")


def _removed_sqlite_authority_message() -> str:
    return (
        "transitional SQLite authority is no longer a supported runtime backend; "
        "use co_located_service, managed_service, or allocation_scoped_service "
        "authority"
    )


def _is_http_endpoint(endpoint: str) -> bool:
    return endpoint.startswith(("http://", "https://"))


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityStoreError(f"{field} must be a non-empty string")
    return value


__all__ = ["create_run_store"]

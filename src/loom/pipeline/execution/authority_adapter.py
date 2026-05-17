"""Execution adapter for authority-backed serial runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.event_sinks import EventObserverLinkRecord, EventSinkFailureRecord
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.locks import RunLockRecord
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus, StageStatusRecord
from loom.pipeline.stores import (
    AttemptAllocation,
    AuthorityBackendKind,
    AuthorityClient,
    AuthorityConfig,
    AuthorityFactoryError,
    AuthorityProtocolReadiness,
    AuthorityProtocolResponse,
    AuthorityProtocolResult,
    AuthorityResolutionMode,
    AuthorityResolutionResult,
    AuthorityStoreError,
    BackendCapabilitySet,
    LeaseKind,
    LocalRunStore,
    OutputCommit,
    PerRunAuthorityStore,
    ServiceWorkspaceCoordinationStore,
    StatusTransition,
    WorkspaceCoordinationStore,
    config_from_authority_reference,
    create_authority_client,
    format_artifact_key,
    require_online_authority,
    resolve_authority_for_factory,
)
from loom.pipeline.stores.inspection import RunStateInspection
from loom.pipeline.stores.read_models import (
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    LeaseRecord,
    LifecycleReason,
    RecoveryRecord,
    ReliabilityPolicyFact,
    StageAttempt,
    StageLifecycleSnapshot,
)
from loom.pipeline.stores.run_store import RunFreshnessRecord
from loom.pipeline.stores.run_uri import validate_run_uri
from loom.pipeline.stores.schema_policy import AuthoritySchemaCheck
from loom.pipeline.submitted import (
    SubmittedOperationRecord,
    latest_active_submitted_operation,
    latest_submitted_operation,
    sort_submitted_operations,
)
from loom.serialization import PlainData, ensure_plain_data, thaw_plain_data
from loom.timestamps import utc_timestamp


_CONTROLLER_LEASE_TTL_SECONDS = 24 * 60 * 60
_STAGE_LEASE_TTL_SECONDS = 24 * 60 * 60
_AUTHORITY_METADATA_KEY = "authority_attempt"
_HTTP_RELIABILITY_WRITE_GAP = (
    "HTTP authority reliability fact writes are not implemented in this phase"
)


@dataclass(frozen=True, slots=True)
class _AttemptLease:
    attempt: StageAttempt
    lease: LeaseRecord


@dataclass(frozen=True, slots=True)
class _ControllerLease:
    owner_id: str
    lease: LeaseRecord


class AuthorityClientBackedPerRunAuthorityStore(PerRunAuthorityStore):
    """Per-run authority adapter backed by the repository-free HTTP client."""

    requires_live_endpoint_readiness = True

    def __init__(
        self,
        *,
        client: AuthorityClient,
        config: AuthorityConfig,
        readiness: AuthorityProtocolReadiness,
    ) -> None:
        if not isinstance(client, AuthorityClient):
            raise TypeError("client must be AuthorityClient")
        if not isinstance(config, AuthorityConfig):
            raise TypeError("config must be AuthorityConfig")
        if not isinstance(readiness, AuthorityProtocolReadiness):
            raise TypeError("readiness must be AuthorityProtocolReadiness")
        self._client = client
        self._config = config
        self._readiness = readiness
        self._capabilities = readiness.capabilities or BackendCapabilitySet(
            backend_name="http-authority",
            records=(),
        )
        self._leases: dict[str, LeaseRecord] = {}
        self._event_sequences: dict[str, int] = {}
        self._event_sink_failures: dict[str, list[EventSinkFailureRecord]] = {}
        self._event_observer_links: dict[str, list[EventObserverLinkRecord]] = {}

    @property
    def authority_config(self) -> AuthorityConfig:
        return self._config

    def capabilities(self) -> BackendCapabilitySet:
        return self._capabilities

    def check_schema(self, run_uri: str) -> AuthoritySchemaCheck:
        _ = run_uri
        return self._readiness.version.schema_check

    def create_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> BackendRevision:
        result = self._result(
            self._client.admit_run(
                run_uri,
                status=status,
                metadata=metadata,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="admit run",
        )
        if result.revision is None:
            raise AuthorityStoreError("authority admit run response omitted revision")
        return result.revision

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        result = self._result(
            self._client.open_run(
                run_uri,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="open run",
        )
        if result.snapshot is None:
            raise AuthorityStoreError("authority open run response omitted snapshot")
        self._remember_snapshot_leases(result.snapshot)
        return result.snapshot

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        result = self._result(
            self._client.transition_run(
                run_uri,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="transition run",
        )
        return _transition_from_result(result, "transition run")

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        result = self._result(
            self._client.transition_stage(
                run_uri,
                stage_name,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="transition stage",
        )
        return _transition_from_result(result, "transition stage")

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation:
        result = self._result(
            self._client.allocate_stage_attempt(
                run_uri,
                stage_name,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="allocate stage attempt",
        )
        if result.stage_attempt is None:
            raise AuthorityStoreError(
                "authority allocate stage attempt response omitted attempt"
            )
        if result.lease is not None:
            self._remember_lease(result.lease)
        return AttemptAllocation(attempt=result.stage_attempt, lease=result.lease)

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        result = self._result(
            self._client.acquire_controller_lease(
                run_uri,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="acquire controller lease",
        )
        return self._lease_from_result(result, "acquire controller lease")

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        lease = self._known_lease(lease_id)
        if lease.kind is LeaseKind.CONTROLLER:
            response = self._client.renew_controller_lease(
                _lease_run_uri(lease),
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                lease_ttl_seconds=lease_ttl_seconds,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        elif lease.kind is LeaseKind.STAGE:
            response = self._client.renew_stage_lease(
                _lease_run_uri(lease),
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                lease_ttl_seconds=lease_ttl_seconds,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        else:
            raise AuthorityStoreError(f"cannot renew {lease.kind.value} lease")
        return self._lease_from_result(
            self._result(response, operation="renew lease"),
            "renew lease",
        )

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        lease = self._known_lease(lease_id)
        if lease.kind is LeaseKind.CONTROLLER:
            response = self._client.release_controller_lease(
                _lease_run_uri(lease),
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        elif lease.kind is LeaseKind.STAGE:
            response = self._client.release_stage_lease(
                _lease_run_uri(lease),
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        else:
            raise AuthorityStoreError(f"cannot release {lease.kind.value} lease")
        return self._lease_from_result(
            self._result(response, operation="release lease"),
            "release lease",
        )

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        lease = self._known_lease(lease_id)
        if lease.kind is LeaseKind.CONTROLLER:
            response = self._client.fail_controller_lease(
                _lease_run_uri(lease),
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        elif lease.kind is LeaseKind.STAGE:
            response = self._client.fail_stage_lease(
                _lease_run_uri(lease),
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        else:
            raise AuthorityStoreError(f"cannot fail {lease.kind.value} lease")
        return self._lease_from_result(
            self._result(response, operation="fail lease"),
            "fail lease",
        )

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> BackendRevision:
        result = self._result(
            self._client.write_submitted_operation(
                run_uri,
                record,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="write submitted operation",
        )
        if result.revision is None:
            raise AuthorityStoreError(
                "authority write submitted operation response omitted revision"
            )
        return result.revision

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        result = self._result(
            self._client.read_submitted_operation(
                run_uri,
                submission_id,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="read submitted operation",
        )
        return result.submitted_operation

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        result = self._result(
            self._client.list_submitted_operations(
                run_uri,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="list submitted operations",
        )
        return result.submitted_operations

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        _ = (run_uri, fact)
        raise AuthorityStoreError(
            "HTTP authority reliability fact writes are not implemented in this phase"
        )

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        if stage_name is None:
            return self.snapshot(run_uri).reliability_policy_facts
        return tuple(
            fact
            for stage in self.snapshot(run_uri).stages
            if stage.stage_name == stage_name
            for fact in stage.reliability_policy_facts
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        _ = (run_uri, detail)
        raise AuthorityStoreError(
            "HTTP authority reliability fact writes are not implemented in this phase"
        )

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return tuple(
            detail
            for stage in self.snapshot(run_uri).stages
            if stage_name is None or stage.stage_name == stage_name
            for detail in stage.reliability_status_details
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision:
        _ = (run_uri, transaction)
        raise AuthorityStoreError(
            "HTTP authority reliability fact writes are not implemented in this phase"
        )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        transactions = {
            transaction.transaction_id: transaction
            for transaction in self.list_stage_attempt_transactions(run_uri)
        }
        current = transactions.get(transaction_id)
        if current is None:
            return ()
        chain: list[StageAttemptTransaction] = []
        seen: set[str] = set()
        while current is not None:
            if current.transaction_id in seen:
                raise AuthorityStoreError(
                    "reliability transaction chain contains a cycle"
                )
            seen.add(current.transaction_id)
            chain.append(current)
            parent_id = current.causal_parent_id
            current = None if parent_id is None else transactions.get(parent_id)
        return tuple(reversed(chain))

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        return tuple(
            transaction
            for stage in self.snapshot(run_uri).stages
            if stage_name is None or stage.stage_name == stage_name
            for transaction in stage.reliability_transactions
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision:
        _ = (run_uri, decision)
        raise AuthorityStoreError(
            "HTTP authority reliability fact writes are not implemented in this phase"
        )

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        return tuple(
            decision
            for stage in self.snapshot(run_uri).stages
            if stage_name is None or stage.stage_name == stage_name
            for decision in stage.retry_decisions
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision:
        _ = (run_uri, outcome)
        raise AuthorityStoreError(
            "HTTP authority reliability fact writes are not implemented in this phase"
        )

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        return tuple(
            outcome
            for stage in self.snapshot(run_uri).stages
            if stage_name is None or stage.stage_name == stage_name
            for outcome in stage.timeout_outcomes
        )

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        reason: LifecycleReason | None = None,
    ) -> OutputCommit:
        owner_id = self._owner_for_stage_lease(run_uri, stage_name, fencing_token)
        result = self._result(
            self._client.record_output_commit(
                run_uri,
                stage_name,
                attempt_id=attempt_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                outputs=outputs,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            ),
            operation="record output commit",
        )
        if result.output_commit is None:
            raise AuthorityStoreError(
                "authority record output commit response omitted output commit"
            )
        return OutputCommit(
            commit=result.output_commit,
            artifact_facts=result.artifact_facts,
            cleanup_candidates=result.cleanup_candidates,
        )

    def append_audit_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord:
        # The HTTP mutation protocol has no audit-event route yet. Keep runner
        # events local in Phase 11 while lifecycle mutations go through HTTP.
        sequence = self._event_sequences.get(run_uri, 0) + 1
        self._event_sequences[run_uri] = sequence
        payload = cast(
            Mapping[str, PlainData],
            thaw_plain_data(event.payload, path="event.payload"),
        )
        return PipelineEventRecord(
            run_uri=run_uri,
            sequence=sequence,
            timestamp=event.timestamp or utc_timestamp(),
            scope=event.scope,
            event_type=event.event_type,
            payload=payload,
        )

    def append_event_sink_failure(
        self, run_uri: str, failure: EventSinkFailureRecord
    ) -> BackendRevision:
        if failure.run_uri != run_uri:
            raise AuthorityStoreError("event sink failure run_uri does not match run")
        self.open_run(run_uri)
        self._event_sink_failures.setdefault(run_uri, []).append(failure)
        return self.snapshot(run_uri).revision

    def read_event_sink_failures(
        self, run_uri: str
    ) -> tuple[EventSinkFailureRecord, ...]:
        self.open_run(run_uri)
        return tuple(self._event_sink_failures.get(run_uri, ()))

    def append_event_observer_link(
        self, run_uri: str, link: EventObserverLinkRecord
    ) -> BackendRevision:
        if link.run_uri != run_uri:
            raise AuthorityStoreError("event observer link run_uri does not match run")
        self.open_run(run_uri)
        self._event_observer_links.setdefault(run_uri, []).append(link)
        return self.snapshot(run_uri).revision

    def read_event_observer_links(
        self, run_uri: str
    ) -> tuple[EventObserverLinkRecord, ...]:
        self.open_run(run_uri)
        return tuple(self._event_observer_links.get(run_uri, ()))

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return self.open_run(run_uri)

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        _ = run_uri
        return ()

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        return self.open_run(run_uri).cleanup_candidates

    @property
    def _service_generation(self) -> str | None:
        return self._readiness.service_generation

    @property
    def _workspace_id(self) -> str | None:
        return self._readiness.workspace_id

    def _result(
        self,
        response: AuthorityProtocolResponse,
        *,
        operation: str,
    ) -> AuthorityProtocolResult:
        if response.accepted and response.result is not None:
            return response.result
        if response.rejection is not None:
            raise AuthorityStoreError(
                f"authority rejected {operation}: {response.rejection.message}"
            )
        raise AuthorityStoreError(f"authority {operation} response was incomplete")

    def _lease_from_result(
        self,
        result: AuthorityProtocolResult,
        operation: str,
    ) -> LeaseRecord:
        if result.lease is None:
            raise AuthorityStoreError(f"authority {operation} response omitted lease")
        return self._remember_lease(result.lease)

    def _remember_lease(self, lease: LeaseRecord) -> LeaseRecord:
        self._leases[lease.lease_id] = lease
        return lease

    def _remember_snapshot_leases(self, snapshot: AuthoritativeRunSnapshot) -> None:
        for stage in snapshot.stages:
            if stage.active_lease is not None:
                self._remember_lease(stage.active_lease)

    def _known_lease(self, lease_id: str) -> LeaseRecord:
        lease = self._leases.get(lease_id)
        if lease is None:
            raise AuthorityStoreError(f"unknown authority lease: {lease_id}")
        return lease

    def _owner_for_stage_lease(
        self, run_uri: str, stage_name: str, fencing_token: str
    ) -> str:
        for lease in self._leases.values():
            if (
                lease.kind is LeaseKind.STAGE
                and lease.run_uri == run_uri
                and lease.stage_name == stage_name
                and lease.fencing_token == fencing_token
            ):
                return lease.owner_id
        snapshot = self.open_run(run_uri)
        for stage in snapshot.stages:
            lease = stage.active_lease
            if (
                stage.stage_name == stage_name
                and lease is not None
                and lease.fencing_token == fencing_token
            ):
                self._remember_lease(lease)
                return lease.owner_id
        raise AuthorityStoreError("unknown authority stage lease fencing token")


class AuthorityBackedSerialRunStore:
    """RunStore-shaped adapter with backend authority as active write truth."""

    def __init__(
        self,
        *,
        local_store: LocalRunStore,
        authority_store: PerRunAuthorityStore,
        authority_config: AuthorityConfig | None = None,
        workspace_coordination_store: WorkspaceCoordinationStore | None = None,
        workspace_id: str | None = None,
        owner_id: str = "serial-controller",
    ) -> None:
        if not isinstance(local_store, LocalRunStore):
            raise TypeError("local_store must be LocalRunStore")
        if not isinstance(authority_store, PerRunAuthorityStore):
            raise TypeError("authority_store must satisfy PerRunAuthorityStore")
        if not owner_id:
            raise ValueError("owner_id must be non-empty")
        self.local_store = local_store
        self.authority_store = authority_store
        self.workspace_coordination_store = workspace_coordination_store
        self._authority_config = authority_config or _config_from_authority_store(
            authority_store,
            fallback=AuthorityConfig(backend_kind=AuthorityBackendKind.TEST_FAKE),
        )
        self.workspace_id = workspace_id or self._authority_config.workspace_id
        self.owner_id = owner_id
        self._attempt_leases: dict[tuple[str, str, int], _AttemptLease] = {}
        self._controller_leases: dict[str, _ControllerLease] = {}

    def authority_config(self) -> AuthorityConfig:
        return self._authority_config

    def resolve_run_uri(self, run_uri: str) -> str:
        return self.local_store.resolve_run_uri(run_uri)

    def allocate_run_uri(self) -> str:
        return self.local_store.allocate_run_uri()

    def create_run(
        self, run_uri: str, *, metadata: Mapping[str, PlainData] | None = None
    ) -> None:
        self.local_store.create_run(run_uri, metadata=metadata)
        self.authority_store.create_run(run_uri, metadata=metadata or {})

    def open_run(self, run_uri: str) -> None:
        self.local_store.open_run(run_uri)
        self.authority_store.open_run(run_uri)

    def run_uri_exists(self, run_uri: str) -> bool:
        return self.local_store.run_uri_exists(run_uri)

    def read_run_document(self, run_uri: str) -> dict[str, PlainData]:
        return self.local_store.read_run_document(run_uri)

    def read_run_user_metadata(self, run_uri: str) -> dict[str, PlainData]:
        return self.local_store.read_run_user_metadata(run_uri)

    def write_run_user_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None:
        self.local_store.write_run_user_metadata(run_uri, metadata)

    def read_run_freshness(self, run_uri: str) -> RunFreshnessRecord | None:
        try:
            revision = self.authority_store.snapshot(run_uri).revision
        except Exception:
            return None
        return RunFreshnessRecord(
            run_uri=run_uri,
            token=revision.token,
            updated_at=revision.created_at or utc_timestamp(),
            revision=revision.sequence,
            reason="authority_revision",
        )

    def read_run_status(self, run_uri: str) -> RunStatusRecord | None:
        local_status = self.local_store.read_run_status(run_uri)
        try:
            snapshot = self.authority_store.snapshot(run_uri)
        except Exception:
            return local_status
        created_at = _created_at(self.local_store, run_uri, snapshot.revision.created_at)
        updated_at = snapshot.revision.created_at or created_at
        local_matches = local_status is not None and local_status.status is snapshot.status
        local_projection = local_status if local_matches else None
        return RunStatusRecord(
            run_uri=run_uri,
            status=snapshot.status,
            created_at=created_at,
            updated_at=local_projection.updated_at
            if local_projection is not None
            else updated_at,
            started_at=(
                local_projection.started_at
                if local_projection is not None
                else created_at if snapshot.status not in {RunStatus.CREATED} else None
            ),
            finished_at=(
                local_projection.finished_at
                if local_projection is not None
                else updated_at
                if snapshot.status
                in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
                else None
            ),
            message=local_projection.message if local_projection is not None else None,
            metadata=local_projection.metadata if local_projection is not None else {},
        )

    def write_run_status(self, run_uri: str, status: RunStatusRecord) -> None:
        current = self.authority_store.snapshot(run_uri).status
        if current is not status.status:
            self.authority_store.transition_run(
                run_uri,
                from_status=current,
                to_status=status.status,
                reason=_reason(
                    f"run_{status.status.value.lower()}",
                    status.message,
                    status.metadata,
                ),
            )
        self.local_store.write_run_status(run_uri, status)

    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None:
        return self.local_store.read_plan(run_uri)

    def write_plan(self, run_uri: str, plan: Mapping[str, PlainData]) -> None:
        self.local_store.write_plan(run_uri, plan)

    def read_prepared_run(self, run_uri: str) -> dict[str, PlainData] | None:
        return self.local_store.read_prepared_run(run_uri)

    def write_prepared_run(
        self, run_uri: str, prepared_run: Mapping[str, PlainData]
    ) -> None:
        self.local_store.write_prepared_run(run_uri, prepared_run)

    def read_runtime_metadata(self, run_uri: str) -> dict[str, PlainData] | None:
        return self.local_store.read_runtime_metadata(run_uri)

    def write_runtime_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None:
        self.local_store.write_runtime_metadata(run_uri, metadata)

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> None:
        self.authority_store.write_submitted_operation(run_uri, record)
        self.local_store.write_submitted_operation(run_uri, record)

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        return self.authority_store.read_submitted_operation(run_uri, submission_id)

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        return sort_submitted_operations(
            self.authority_store.list_submitted_operations(run_uri)
        )

    def latest_submitted_operation(
        self, run_uri: str
    ) -> SubmittedOperationRecord | None:
        return latest_submitted_operation(self.list_submitted_operations(run_uri))

    def latest_active_submitted_operation(
        self, run_uri: str
    ) -> SubmittedOperationRecord | None:
        return latest_active_submitted_operation(
            self.list_submitted_operations(run_uri)
        )

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> None:
        try:
            self.authority_store.write_reliability_policy_fact(run_uri, fact)
        except AuthorityStoreError as exc:
            if not _is_http_reliability_write_gap(self.authority_store, exc):
                raise
        self.local_store.write_reliability_policy_fact(run_uri, fact)

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        records = self.authority_store.list_reliability_policy_facts(
            run_uri,
            stage_name=stage_name,
        )
        if records or not isinstance(
            self.authority_store,
            AuthorityClientBackedPerRunAuthorityStore,
        ):
            return records
        return self.local_store.list_reliability_policy_facts(
            run_uri,
            stage_name=stage_name,
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> None:
        try:
            self.authority_store.write_reliability_status_detail(run_uri, detail)
        except AuthorityStoreError as exc:
            if not _is_http_reliability_write_gap(self.authority_store, exc):
                raise
        self.local_store.write_reliability_status_detail(run_uri, detail)

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        records = self.authority_store.list_reliability_status_details(
            run_uri,
            stage_name=stage_name,
        )
        if records or not isinstance(
            self.authority_store,
            AuthorityClientBackedPerRunAuthorityStore,
        ):
            return records
        return self.local_store.list_reliability_status_details(
            run_uri,
            stage_name=stage_name,
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> None:
        try:
            self.authority_store.write_stage_attempt_transaction(run_uri, transaction)
        except AuthorityStoreError as exc:
            if not _is_http_reliability_write_gap(self.authority_store, exc):
                raise
        self.local_store.write_stage_attempt_transaction(run_uri, transaction)

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        chain = self.authority_store.read_transaction_chain(run_uri, transaction_id)
        if chain or not isinstance(
            self.authority_store,
            AuthorityClientBackedPerRunAuthorityStore,
        ):
            return chain
        return self.local_store.read_transaction_chain(run_uri, transaction_id)

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        records = self.authority_store.list_stage_attempt_transactions(
            run_uri,
            stage_name=stage_name,
        )
        if records or not isinstance(
            self.authority_store,
            AuthorityClientBackedPerRunAuthorityStore,
        ):
            return records
        return self.local_store.list_stage_attempt_transactions(
            run_uri,
            stage_name=stage_name,
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> None:
        try:
            self.authority_store.write_retry_decision(run_uri, decision)
        except AuthorityStoreError as exc:
            if not _is_http_reliability_write_gap(self.authority_store, exc):
                raise
        self.local_store.write_retry_decision(run_uri, decision)

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        records = self.authority_store.list_retry_decisions(
            run_uri,
            stage_name=stage_name,
        )
        if records or not isinstance(
            self.authority_store,
            AuthorityClientBackedPerRunAuthorityStore,
        ):
            return records
        return self.local_store.list_retry_decisions(
            run_uri,
            stage_name=stage_name,
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> None:
        try:
            self.authority_store.write_timeout_outcome(run_uri, outcome)
        except AuthorityStoreError as exc:
            if not _is_http_reliability_write_gap(self.authority_store, exc):
                raise
        self.local_store.write_timeout_outcome(run_uri, outcome)

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        records = self.authority_store.list_timeout_outcomes(
            run_uri,
            stage_name=stage_name,
        )
        if records or not isinstance(
            self.authority_store,
            AuthorityClientBackedPerRunAuthorityStore,
        ):
            return records
        return self.local_store.list_timeout_outcomes(
            run_uri,
            stage_name=stage_name,
        )

    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]:
        index: dict[str, ArtifactRef] = {}
        for stage in self.authority_store.snapshot(run_uri).stages:
            for fact in stage.artifact_facts:
                index[format_artifact_key(stage.stage_name, fact.artifact_name)] = (
                    fact.artifact
                )
        return index

    def write_artifact_index(
        self, run_uri: str, index: Mapping[str, ArtifactRef]
    ) -> None:
        self.local_store.write_artifact_index(run_uri, index)

    def read_config_snapshot(self, run_uri: str, name: str) -> str | None:
        return self.local_store.read_config_snapshot(run_uri, name)

    def write_config_snapshot(self, run_uri: str, name: str, content: str) -> None:
        self.local_store.write_config_snapshot(run_uri, name, content)

    def read_composition_manifest(
        self, run_uri: str
    ) -> dict[str, PlainData] | None:
        return self.local_store.read_composition_manifest(run_uri)

    def write_composition_manifest(
        self, run_uri: str, manifest: Mapping[str, PlainData]
    ) -> None:
        self.local_store.write_composition_manifest(run_uri, manifest)

    def read_recipe_manifest(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...] | None:
        return self.local_store.read_recipe_manifest(run_uri)

    def write_recipe_manifest(
        self, run_uri: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None:
        self.local_store.write_recipe_manifest(run_uri, records)

    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None:
        return self.local_store.read_provenance_document(run_uri, name)

    def write_provenance_document(
        self, run_uri: str, name: str, document: Mapping[str, PlainData]
    ) -> None:
        self.local_store.write_provenance_document(run_uri, name, document)

    def append_event(self, run_uri: str, event: PipelineEvent) -> PipelineEventRecord:
        authority_event = PipelineEvent(
            scope=event.scope,
            event_type=event.event_type,
            timestamp=event.timestamp,
            payload=cast(
                Mapping[str, PlainData],
                thaw_plain_data(event.payload, path="event.payload"),
            ),
        )
        record = self.authority_store.append_audit_event(run_uri, authority_event)
        self.local_store.append_event(run_uri, event)
        return record

    def read_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]:
        return self.local_store.read_events(run_uri)

    def append_event_sink_failure(
        self, run_uri: str, failure: EventSinkFailureRecord
    ) -> None:
        self.authority_store.append_event_sink_failure(run_uri, failure)
        self.local_store.append_event_sink_failure(run_uri, failure)

    def read_event_sink_failures(
        self, run_uri: str
    ) -> tuple[EventSinkFailureRecord, ...]:
        return self.local_store.read_event_sink_failures(run_uri)

    def append_event_observer_link(
        self, run_uri: str, link: EventObserverLinkRecord
    ) -> None:
        self.authority_store.append_event_observer_link(run_uri, link)
        self.local_store.append_event_observer_link(run_uri, link)

    def read_event_observer_links(
        self, run_uri: str
    ) -> tuple[EventObserverLinkRecord, ...]:
        return self.local_store.read_event_observer_links(run_uri)

    def acquire_run_lock(
        self,
        run_uri: str,
        *,
        owner: Mapping[str, PlainData] | None = None,
    ) -> RunLockRecord:
        if _is_stage_job_owner(owner):
            return self.local_store.acquire_run_lock(run_uri, owner=owner)
        owner_id = _owner_id(owner, fallback=self.owner_id)
        lease = self.authority_store.acquire_controller_lease(
            run_uri,
            owner_id=owner_id,
            lease_ttl_seconds=_CONTROLLER_LEASE_TTL_SECONDS,
        )
        token = _lease_token(lease)
        self._controller_leases[token] = _ControllerLease(owner_id=owner_id, lease=lease)
        return RunLockRecord(
            run_uri=run_uri,
            token=token,
            acquired_at=lease.acquired_at,
            owner=owner or {},
        )

    def read_run_lock(self, run_uri: str) -> RunLockRecord | None:
        materialization_lock = self.local_store.read_run_lock(run_uri)
        if materialization_lock is not None:
            return materialization_lock
        for token, active in self._controller_leases.items():
            if active.lease.run_uri == run_uri:
                return RunLockRecord(
                    run_uri=run_uri,
                    token=token,
                    acquired_at=active.lease.acquired_at,
                    owner={"owner_id": active.owner_id},
                )
        return None

    def release_run_lock(self, run_uri: str, token: str) -> None:
        active = self._controller_leases.pop(token, None)
        if active is None:
            self.local_store.release_run_lock(run_uri, token)
            return
        self.authority_store.release_lease(
            active.lease.lease_id,
            owner_id=active.owner_id,
            fencing_token=active.lease.fencing_token,
            reason=LifecycleReason(code="controller_released"),
        )

    def list_run_stages(self, run_uri: str) -> tuple[str, ...]:
        return tuple(stage.stage_name for stage in self.authority_store.snapshot(run_uri).stages)

    def inspect_run_state(self, run_uri: str) -> RunStateInspection:
        return self.local_store.inspect_run_state(run_uri)

    def read_stage_status(
        self, run_uri: str, stage_name: str
    ) -> StageStatusRecord | None:
        local_status = self.local_store.read_stage_status(run_uri, stage_name)
        stage = self._stage_snapshot(run_uri, stage_name)
        if stage is None:
            return local_status
        attempt = stage.attempts[-1].attempt if stage.attempts else 1
        updated_at = stage.revision.created_at or utc_timestamp()
        metadata = _reason_detail(stage.reason)
        local_matches = (
            local_status is not None
            and local_status.status is stage.status
            and local_status.attempt == attempt
        )
        local_projection = local_status if local_matches else None
        if local_projection is not None:
            metadata = {**metadata, **local_projection.metadata}
        return StageStatusRecord(
            run_uri=run_uri,
            stage_name=stage.stage_name,
            status=stage.status,
            attempt=attempt,
            updated_at=local_projection.updated_at
            if local_projection is not None
            else updated_at,
            started_at=local_projection.started_at
            if local_projection is not None
            else _stage_started_at(stage),
            finished_at=local_projection.finished_at
            if local_projection is not None
            else _stage_finished_at(stage, updated_at),
            message=(None if stage.reason is None else stage.reason.message)
            or (None if local_status is None else local_status.message),
            owner=local_projection.owner
            if local_projection is not None and local_projection.owner
            else _stage_owner(stage),
            metadata=metadata,
        )

    def write_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        self._validate_stage_status(run_uri, stage_name, status)
        if status.status in {
            StageStatus.PENDING,
            StageStatus.RUNNING,
            StageStatus.SUBMITTED,
        }:
            self._ensure_stage_attempt(run_uri, stage_name, status.attempt)
        current_stage = self._stage_snapshot(run_uri, stage_name)
        current = None if current_stage is None else current_stage.status
        if current is not status.status:
            if current is StageStatus.SUCCEEDED and status.status is StageStatus.SUCCEEDED:
                pass
            else:
                self.authority_store.transition_stage(
                    run_uri,
                    stage_name,
                    from_status=current,
                    to_status=status.status,
                    reason=_reason(
                        f"stage_{status.status.value.lower()}",
                        status.message,
                        status.metadata,
                    ),
                )
        if status.status is StageStatus.FAILED:
            self._fail_stage_lease(run_uri, stage_name, status.attempt, status)
        self.local_store.write_stage_status(run_uri, stage_name, status)

    def read_stage_inputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        return self.local_store.read_stage_inputs(run_uri, stage_name)

    def write_stage_inputs(
        self,
        run_uri: str,
        stage_name: str,
        inputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        self._ensure_stage_attempt(run_uri, stage_name, attempt)
        self.local_store.write_stage_inputs(run_uri, stage_name, inputs, attempt=attempt)

    def read_stage_outputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        stage = self._stage_snapshot(run_uri, stage_name)
        if stage is None or not stage.artifact_facts:
            return None
        return {fact.artifact_name: fact.artifact for fact in stage.artifact_facts}

    def write_stage_outputs(
        self,
        run_uri: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        self.local_store.write_stage_outputs(
            run_uri, stage_name, outputs, attempt=attempt
        )
        active = self._require_stage_lease(run_uri, stage_name, attempt)
        try:
            self.authority_store.record_output_commit(
                run_uri,
                stage_name,
                attempt_id=active.attempt.attempt_id,
                fencing_token=active.lease.fencing_token,
                outputs=outputs,
                reason=LifecycleReason(code="stage_outputs_committed"),
            )
        except Exception:
            self._fail_stage_lease_by_record(active)
            raise

    def read_stage_fingerprint(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return self.local_store.read_stage_fingerprint(run_uri, stage_name)

    def write_stage_fingerprint(
        self,
        run_uri: str,
        stage_name: str,
        fingerprint: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        self.local_store.write_stage_fingerprint(
            run_uri, stage_name, fingerprint, attempt=attempt
        )

    def read_stage_failure(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return self.local_store.read_stage_failure(run_uri, stage_name)

    def write_stage_failure(
        self,
        run_uri: str,
        stage_name: str,
        failure: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        self.local_store.write_stage_failure(
            run_uri, stage_name, failure, attempt=attempt
        )

    def read_stage_worker_request(
        self, run_uri: str, stage_name: str, *, attempt: int
    ) -> dict[str, PlainData] | None:
        return self.local_store.read_stage_worker_request(
            run_uri, stage_name, attempt=attempt
        )

    def write_stage_worker_request(
        self,
        run_uri: str,
        stage_name: str,
        request: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        payload = _plain_mapping(request, "worker_request")
        active = self._attempt_leases.get((run_uri, stage_name, attempt))
        if active is not None:
            metadata = dict(cast(Mapping[str, PlainData], payload.get("metadata", {})))
            metadata[_AUTHORITY_METADATA_KEY] = {
                "attempt_id": active.attempt.attempt_id,
                "lease_id": active.lease.lease_id,
                "fencing_token": active.lease.fencing_token,
                "owner_id": active.lease.owner_id,
            }
            metadata["authority"] = _authority_handoff_metadata(self._authority_config)
            payload["metadata"] = metadata
        self.local_store.write_stage_worker_request(
            run_uri, stage_name, payload, attempt=attempt
        )

    def stage_job_run_finalization_allowed(self) -> bool:
        return False

    def validate_stage_job_authority(
        self,
        run_uri: str,
        stage_name: str,
        attempt: int,
        *,
        authority_attempt_id: str,
        authority_lease_id: str,
        authority_owner_id: str,
        authority_fencing_token: str,
        worker_metadata: Mapping[str, PlainData],
    ) -> None:
        provided = {
            "attempt_id": authority_attempt_id,
            "lease_id": authority_lease_id,
            "owner_id": authority_owner_id,
            "fencing_token": authority_fencing_token,
        }
        metadata = _authority_attempt_metadata(worker_metadata)
        metadata_mismatches = _value_mismatches(expected=provided, actual=metadata)
        if metadata_mismatches:
            raise AuthorityStoreError(
                "stage-job authority fencing does not match worker metadata"
            )
        stage = self._stage_snapshot(run_uri, stage_name)
        if stage is None:
            raise AuthorityStoreError("stage has no authoritative lifecycle state")
        attempt_record = next(
            (
                stage_attempt
                for stage_attempt in stage.attempts
                if stage_attempt.attempt == attempt
                and stage_attempt.attempt_id == authority_attempt_id
            ),
            None,
        )
        if attempt_record is None:
            raise AuthorityStoreError("stage-job authority attempt is not current")
        active_lease = stage.active_lease
        if active_lease is None:
            self.authority_store.renew_lease(
                authority_lease_id,
                owner_id=authority_owner_id,
                fencing_token=authority_fencing_token,
                lease_ttl_seconds=_STAGE_LEASE_TTL_SECONDS,
            )
            raise AuthorityStoreError("missing active stage lease")
        lease_expected = {
            "run_uri": run_uri,
            "stage_name": stage_name,
            "attempt_id": authority_attempt_id,
            "lease_id": authority_lease_id,
            "owner_id": authority_owner_id,
            "fencing_token": authority_fencing_token,
        }
        lease_actual = {
            "run_uri": active_lease.run_uri,
            "stage_name": active_lease.stage_name,
            "attempt_id": active_lease.attempt_id,
            "lease_id": active_lease.lease_id,
            "owner_id": active_lease.owner_id,
            "fencing_token": active_lease.fencing_token,
        }
        lease_mismatches = _value_mismatches(
            expected=lease_expected, actual=lease_actual
        )
        if lease_mismatches:
            raise AuthorityStoreError(
                "stage-job authority fencing does not match active backend lease"
            )
        renewed = self.authority_store.renew_lease(
            authority_lease_id,
            owner_id=authority_owner_id,
            fencing_token=authority_fencing_token,
            lease_ttl_seconds=_STAGE_LEASE_TTL_SECONDS,
        )
        self._attempt_leases[(run_uri, stage_name, attempt)] = _AttemptLease(
            attempt=attempt_record,
            lease=renewed,
        )

    def read_stage_worker_result(
        self, run_uri: str, stage_name: str, *, attempt: int
    ) -> dict[str, PlainData] | None:
        return self.local_store.read_stage_worker_result(
            run_uri, stage_name, attempt=attempt
        )

    def write_stage_worker_result(
        self,
        run_uri: str,
        stage_name: str,
        result: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        self.local_store.write_stage_worker_result(
            run_uri, stage_name, result, attempt=attempt
        )

    def renew_stage_attempt_lease(
        self,
        run_uri: str,
        stage_name: str,
        attempt: int,
    ) -> None:
        active = self._require_stage_lease(run_uri, stage_name, attempt)
        renewed = self.authority_store.renew_lease(
            active.lease.lease_id,
            owner_id=active.lease.owner_id,
            fencing_token=active.lease.fencing_token,
            lease_ttl_seconds=_STAGE_LEASE_TTL_SECONDS,
        )
        self._attempt_leases[(run_uri, stage_name, attempt)] = _AttemptLease(
            attempt=active.attempt,
            lease=renewed,
        )

    def read_stage_provenance(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        return self.local_store.read_stage_provenance(run_uri, stage_name)

    def write_stage_provenance(
        self,
        run_uri: str,
        stage_name: str,
        provenance: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        self.local_store.write_stage_provenance(
            run_uri, stage_name, provenance, attempt=attempt
        )

    def read_stage_log(self, run_uri: str, stage_name: str, stream: str) -> str | None:
        return self.local_store.read_stage_log(run_uri, stage_name, stream)

    def write_stage_log(
        self, run_uri: str, stage_name: str, stream: str, content: str
    ) -> None:
        self.local_store.write_stage_log(run_uri, stage_name, stream, content)

    def prepare_stage_workspace(self, run_uri: str, stage_name: str) -> None:
        self.local_store.prepare_stage_workspace(run_uri, stage_name)

    def local_run_dir(self, run_uri: str) -> Path:
        return self.local_store.local_run_dir(run_uri)

    def local_stage_dir(self, run_uri: str, stage_name: str) -> Path:
        return self.local_store.local_stage_dir(run_uri, stage_name)

    def local_artifact_root(self, run_uri: str) -> Path:
        return self.local_store.local_artifact_root(run_uri)

    def local_stage_artifact_dir(self, run_uri: str, stage_name: str) -> Path:
        return self.local_store.local_stage_artifact_dir(run_uri, stage_name)

    def local_config_path(self, run_uri: str, name: str) -> Path:
        return self.local_store.local_config_path(run_uri, name)

    def local_provenance_path(self, run_uri: str, name: str) -> Path:
        return self.local_store.local_provenance_path(run_uri, name)

    def local_stage_log_path(
        self, run_uri: str, stage_name: str, stream: str
    ) -> Path:
        return self.local_store.local_stage_log_path(run_uri, stage_name, stream)

    def local_stage_worker_request_path(self, run_uri: str, stage_name: str) -> Path:
        return self.local_store.local_stage_worker_request_path(run_uri, stage_name)

    def local_stage_worker_result_path(self, run_uri: str, stage_name: str) -> Path:
        return self.local_store.local_stage_worker_result_path(run_uri, stage_name)

    def local_stage_workspace_dir(self, run_uri: str, stage_name: str) -> Path:
        return self.local_store.local_stage_workspace_dir(run_uri, stage_name)

    def local_generated_artifact_path(self, run_uri: str, relative_path: str) -> Path:
        return self.local_store.local_generated_artifact_path(run_uri, relative_path)

    def local_run_freshness_path(self, run_uri: str) -> Path:
        return self.local_store.local_run_freshness_path(run_uri)

    def local_event_sink_failures_path(self, run_uri: str) -> Path:
        return self.local_store.local_event_sink_failures_path(run_uri)

    def local_event_observer_links_path(self, run_uri: str) -> Path:
        return self.local_store.local_event_observer_links_path(run_uri)

    def _ensure_stage_attempt(
        self, run_uri: str, stage_name: str, attempt: int
    ) -> _AttemptLease:
        key = (run_uri, stage_name, attempt)
        existing = self._attempt_leases.get(key)
        if existing is not None:
            return existing
        from_snapshot = self._attempt_lease_from_snapshot(run_uri, stage_name, attempt)
        if from_snapshot is not None:
            self._attempt_leases[key] = from_snapshot
            return from_snapshot
        allocation = self.authority_store.allocate_stage_attempt(
            run_uri,
            stage_name,
            owner_id=self.owner_id,
            lease_ttl_seconds=_STAGE_LEASE_TTL_SECONDS,
        )
        if allocation.attempt.attempt != attempt:
            raise AuthorityStoreError(
                f"authority allocated attempt {allocation.attempt.attempt}, expected {attempt}"
            )
        if allocation.lease is None:
            raise AuthorityStoreError("authority did not allocate a stage lease")
        active = _AttemptLease(attempt=allocation.attempt, lease=allocation.lease)
        self._attempt_leases[key] = active
        return active

    def _attempt_lease_from_snapshot(
        self, run_uri: str, stage_name: str, attempt: int
    ) -> _AttemptLease | None:
        stage = self._stage_snapshot(run_uri, stage_name)
        if stage is None or stage.active_lease is None:
            return None
        for stage_attempt in stage.attempts:
            if (
                stage_attempt.attempt == attempt
                and stage_attempt.attempt_id == stage.active_lease.attempt_id
            ):
                return _AttemptLease(attempt=stage_attempt, lease=stage.active_lease)
        return None

    def _require_stage_lease(
        self, run_uri: str, stage_name: str, attempt: int
    ) -> _AttemptLease:
        active = self._attempt_leases.get((run_uri, stage_name, attempt))
        if active is not None:
            return active
        active = self._attempt_lease_from_snapshot(run_uri, stage_name, attempt)
        if active is None:
            raise AuthorityStoreError("missing active stage lease")
        self._attempt_leases[(run_uri, stage_name, attempt)] = active
        return active

    def _fail_stage_lease(
        self,
        run_uri: str,
        stage_name: str,
        attempt: int,
        status: StageStatusRecord,
    ) -> None:
        active = self._attempt_leases.get((run_uri, stage_name, attempt))
        if active is None:
            active = self._attempt_lease_from_snapshot(run_uri, stage_name, attempt)
        if active is None:
            return
        self._fail_stage_lease_by_record(
            active,
            reason=_reason("stage_failed", status.message, status.metadata),
        )

    def _fail_stage_lease_by_record(
        self,
        active: _AttemptLease,
        reason: LifecycleReason | None = None,
    ) -> None:
        try:
            self.authority_store.fail_lease(
                active.lease.lease_id,
                owner_id=active.lease.owner_id,
                fencing_token=active.lease.fencing_token,
                reason=reason or LifecycleReason(code="stage_commit_failed"),
            )
        except Exception:
            pass

    def _stage_snapshot(
        self, run_uri: str, stage_name: str
    ) -> StageLifecycleSnapshot | None:
        for stage in self.authority_store.snapshot(run_uri).stages:
            if stage.stage_name == stage_name:
                return stage
        return None

    def _validate_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        if status.run_uri != validate_run_uri(run_uri):
            raise AuthorityStoreError("stage status run_uri mismatch")
        if status.stage_name != stage_name:
            raise AuthorityStoreError("stage status stage_name mismatch")


def create_authority_backed_serial_run_store(
    root: str | Path,
    *,
    authority_config: AuthorityConfig | Mapping[str, object] | None = None,
    authority_store: PerRunAuthorityStore | None = None,
    authority_mode: AuthorityResolutionMode = AuthorityResolutionMode.ONLINE_MUTATION,
    workspace_root: str | Path | None = None,
    workspace_coordination_store: WorkspaceCoordinationStore | None = None,
    allocation_id: str | None = None,
    expected_workspace_id: str | None = None,
    expected_generation: str | None = None,
    owner_id: str = "serial-controller",
) -> AuthorityBackedSerialRunStore:
    """Create the default authority-backed local serial run store."""

    readiness: AuthorityProtocolReadiness | None = None
    should_create_coordination_store = authority_store is None
    if authority_store is None:
        input_config = _resolve_authority_config(authority_config, authority_store)
        if input_config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
            raise AuthorityStoreError(_removed_sqlite_authority_message())
        resolution = resolve_authority_for_factory(
            input_config,
            authority_mode=authority_mode,
            workspace_root=workspace_root,
            allocation_id=allocation_id,
            expected_workspace_id=expected_workspace_id,
            expected_generation=expected_generation,
        )
        reference = require_online_authority(
            resolution,
            purpose="authority-backed serial run-store factory",
        )
        resolved_config = config_from_authority_reference(reference)
        readiness = resolution.readiness
        authority_store = _authority_store_from_config(
            resolved_config,
            resolution=resolution.result,
            readiness=readiness,
        )
        resolved_config = _config_from_authority_store(
            authority_store,
            fallback=resolved_config,
        )
    else:
        resolved_config = _resolve_authority_config(authority_config, authority_store)

    coordination_store = workspace_coordination_store
    if coordination_store is None and should_create_coordination_store:
        coordination_store = _coordination_store_from_config(
            resolved_config,
            readiness=readiness,
        )
    return AuthorityBackedSerialRunStore(
        local_store=LocalRunStore(root),
        authority_store=authority_store,
        authority_config=resolved_config,
        workspace_coordination_store=coordination_store,
        workspace_id=_coordination_workspace_id(resolved_config, readiness),
        owner_id=owner_id,
    )


def _resolve_authority_config(
    config: AuthorityConfig | Mapping[str, object] | None,
    authority_store: PerRunAuthorityStore | None,
) -> AuthorityConfig:
    if config is not None:
        if isinstance(config, AuthorityConfig):
            return config
        return AuthorityConfig.from_dict(config)
    if authority_store is not None:
        return _config_from_authority_store(
            authority_store,
            fallback=AuthorityConfig(backend_kind=AuthorityBackendKind.TEST_FAKE),
        )
    return AuthorityConfig()


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


def _authority_store_from_config(
    config: AuthorityConfig,
    *,
    resolution: AuthorityResolutionResult | None = None,
    readiness: AuthorityProtocolReadiness | None = None,
) -> PerRunAuthorityStore:
    if config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
        raise AuthorityStoreError(_removed_sqlite_authority_message())
    if config.endpoint is not None and config.endpoint.startswith(
        ("http://", "https://")
    ):
        if readiness is None:
            raise AuthorityFactoryError(
                "authority-backed serial run store requires HTTP readiness facts",
                code="authority_factory.missing_readiness",
                resolution=resolution,
                context={"endpoint": config.endpoint},
            )
        return AuthorityClientBackedPerRunAuthorityStore(
            client=create_authority_client(config),
            config=config,
            readiness=readiness,
        )
    if config.backend_kind in {
        AuthorityBackendKind.CO_LOCATED_SERVICE,
        AuthorityBackendKind.MANAGED_SERVICE,
        AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
    }:
        from loom.pipeline.stores.service_authority import create_service_authority_store

        return create_service_authority_store(config)
    raise AuthorityStoreError(
        "authority-backed serial store does not support backend "
        f"{config.backend_kind.value}"
    )


def _coordination_store_from_config(
    config: AuthorityConfig,
    *,
    readiness: AuthorityProtocolReadiness | None,
) -> WorkspaceCoordinationStore | None:
    if config.endpoint is None or not config.endpoint.startswith(("http://", "https://")):
        return None
    return ServiceWorkspaceCoordinationStore(
        create_authority_client(config),
        workspace_id=_coordination_workspace_id(config, readiness),
        service_generation=None if readiness is None else readiness.service_generation,
    )


def _coordination_workspace_id(
    config: AuthorityConfig,
    readiness: AuthorityProtocolReadiness | None,
) -> str | None:
    if readiness is not None and readiness.workspace_id is not None:
        return readiness.workspace_id
    return config.workspace_id


def _transition_from_result(
    result: AuthorityProtocolResult,
    operation: str,
) -> StatusTransition:
    transition = result.body.get("transition")
    if transition is None:
        raise AuthorityStoreError(f"authority {operation} response omitted transition")
    return StatusTransition.from_dict(transition)


def _lease_run_uri(lease: LeaseRecord) -> str:
    if lease.run_uri is None:
        raise AuthorityStoreError("authority lease is missing run_uri")
    return lease.run_uri


def _removed_sqlite_authority_message() -> str:
    return (
        "transitional SQLite authority is no longer a supported runtime backend; "
        "use co_located_service, managed_service, or allocation_scoped_service "
        "authority"
    )


def _authority_handoff_metadata(config: AuthorityConfig) -> dict[str, PlainData]:
    reference = config.to_reference()
    return {
        "backend_kind": config.backend_kind.value,
        "deployment_profile": config.deployment_profile.value,
        "reference": reference.to_dict(),
        "reference_redacted": reference.redacted_dict(config.redaction_keys),
    }


def _created_at(
    local_store: LocalRunStore, run_uri: str, fallback: str | None
) -> str:
    try:
        document = local_store.read_run_document(run_uri)
    except Exception:
        return fallback or utc_timestamp()
    created = document.get("created_at")
    return created if isinstance(created, str) else fallback or utc_timestamp()


def _reason(
    code: str,
    message: str | None = None,
    detail: Mapping[str, PlainData] | None = None,
) -> LifecycleReason:
    return LifecycleReason(code=code, message=message, detail=detail or {})


def _reason_detail(reason: LifecycleReason | None) -> dict[str, PlainData]:
    return {} if reason is None else dict(reason.detail)


def _stage_started_at(stage: StageLifecycleSnapshot) -> str | None:
    if not stage.attempts:
        return None
    return stage.attempts[-1].created_at


def _stage_finished_at(stage: StageLifecycleSnapshot, updated_at: str) -> str | None:
    if stage.status is StageStatus.SUCCEEDED and stage.latest_commit is not None:
        return stage.latest_commit.committed_at
    if stage.status in {
        StageStatus.FAILED,
        StageStatus.BLOCKED,
        StageStatus.SKIPPED,
        StageStatus.CANCELLED,
    }:
        return updated_at
    return None


def _stage_owner(stage: StageLifecycleSnapshot) -> Mapping[str, PlainData]:
    if stage.active_lease is not None:
        return {"owner_id": stage.active_lease.owner_id}
    if stage.attempts and stage.attempts[-1].owner is not None:
        return {"owner_id": stage.attempts[-1].owner}
    return {}


def _is_stage_job_owner(owner: Mapping[str, PlainData] | None) -> bool:
    return owner is not None and owner.get("component") == "StageJobRunner"


def _owner_id(owner: Mapping[str, PlainData] | None, *, fallback: str) -> str:
    if owner is None:
        return fallback
    component = owner.get("component")
    run_uri = owner.get("run_uri")
    executor = owner.get("executor")
    parts = [part for part in (component, executor, run_uri) if isinstance(part, str)]
    return ":".join(parts) if parts else fallback


def _lease_token(lease: LeaseRecord) -> str:
    return f"{lease.lease_id}:{lease.fencing_token}"


def _plain_mapping(value: object, path: str) -> dict[str, PlainData]:
    normalized = ensure_plain_data(value, path=path)
    if not isinstance(normalized, dict):
        raise AuthorityStoreError(f"{path} must be a mapping")
    return cast(dict[str, PlainData], normalized)


def _authority_attempt_metadata(
    metadata: Mapping[str, PlainData],
) -> dict[str, str]:
    raw = metadata.get(_AUTHORITY_METADATA_KEY)
    if not isinstance(raw, Mapping):
        raise AuthorityStoreError("worker request is missing authority_attempt metadata")
    payload = _plain_mapping(raw, f"metadata.{_AUTHORITY_METADATA_KEY}")
    required = ("attempt_id", "lease_id", "owner_id", "fencing_token")
    values: dict[str, str] = {}
    for key in required:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise AuthorityStoreError(
                f"worker request authority_attempt.{key} must be a non-empty string"
            )
        values[key] = value
    return values


def _value_mismatches(
    *,
    expected: Mapping[str, object],
    actual: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    return {
        key: {"expected": expected_value, "actual": actual.get(key)}
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
    }


def _is_http_reliability_write_gap(
    authority_store: PerRunAuthorityStore,
    exc: AuthorityStoreError,
) -> bool:
    return (
        isinstance(authority_store, AuthorityClientBackedPerRunAuthorityStore)
        and _HTTP_RELIABILITY_WRITE_GAP in str(exc)
    )


__all__ = [
    "AuthorityBackedSerialRunStore",
    "AuthorityClientBackedPerRunAuthorityStore",
    "create_authority_backed_serial_run_store",
]

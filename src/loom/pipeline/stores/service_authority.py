"""Stdlib local service authority backend."""

from __future__ import annotations

import atexit
import base64
import secrets
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from multiprocessing.managers import BaseManager
from typing import Any, cast
from urllib.parse import urlparse

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup.records import CleanupReport, CleanupResult
from loom.pipeline.event_sinks import EventObserverLinkRecord, EventSinkFailureRecord
from loom.pipeline.events import EventScope, PipelineEvent, PipelineEventRecord
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData, thaw_plain_data

from .authority import (
    AttemptAllocation,
    AuthorityStoreError,
    OutputCommit,
    PerRunAuthorityStore,
    StatusTransition,
)
from .capabilities import (
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    CapabilitySupport,
)
from .config import (
    AuthorityBackendKind,
    AuthorityConfig,
    AuthorityDeploymentProfile,
)
from .read_models import (
    ArtifactFactRecord,
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    CleanupReportFact,
    CleanupResultFact,
    LeaseKind,
    LeaseRecord,
    LeaseState,
    LifecycleReason,
    OutputCommitRecord,
    RecoveryKind,
    RecoveryRecord,
    ReliabilityPolicyFact,
    StageAttempt,
    StageLifecycleSnapshot,
)
from .reliability_facts import (
    reliability_payload_matches,
    reliability_policy_fact_key,
    reliability_record_stage_name,
    reliability_status_detail_key,
    validate_policy_fact_run,
    validate_retry_decision_run,
    validate_status_detail_run,
    validate_timeout_outcome_run,
    validate_transaction_run,
)
from .schema_policy import (
    AUTHORITY_SCHEMA_VERSION,
    AuthoritySchemaCheck,
    check_authority_schema_version,
)
from .run_uri import validate_run_uri


_DEFAULT_HOST = "127.0.0.1"
_AUTHKEY_METADATA_KEY = "authkey"
_SERVICE_BACKEND_KINDS = {
    AuthorityBackendKind.CO_LOCATED_SERVICE,
    AuthorityBackendKind.MANAGED_SERVICE,
    AuthorityBackendKind.ALLOCATION_SCOPED_SERVICE,
}
_EXPOSED = (
    "advance_time",
    "append_audit_event",
    "capabilities",
    "check_schema",
    "create_run",
    "health",
    "open_run",
    "transition_run",
    "transition_stage",
    "allocate_stage_attempt",
    "acquire_controller_lease",
    "renew_lease",
    "release_lease",
    "fail_lease",
    "write_submitted_operation",
    "read_submitted_operation",
    "list_submitted_operations",
    "write_reliability_policy_fact",
    "list_reliability_policy_facts",
    "write_reliability_status_detail",
    "list_reliability_status_details",
    "write_stage_attempt_transaction",
    "read_transaction_chain",
    "list_stage_attempt_transactions",
    "write_retry_decision",
    "list_retry_decisions",
    "write_timeout_outcome",
    "list_timeout_outcomes",
    "record_output_commit",
    "append_event_sink_failure",
    "read_event_sink_failures",
    "append_event_observer_link",
    "read_event_observer_links",
    "snapshot",
    "scan_recovery",
    "list_cleanup_candidates",
    "append_cleanup_report",
    "list_cleanup_reports",
    "append_cleanup_result",
    "list_cleanup_results",
)


class AuthorityServiceUnavailable(AuthorityStoreError):
    """Raised when a configured authority service endpoint cannot be used."""


@dataclass(frozen=True, slots=True)
class LocalAuthorityService:
    """Own a deterministic local authority service process for tests."""

    endpoint: str
    authkey: bytes
    _manager: BaseManager

    @classmethod
    def start(
        cls,
        *,
        host: str = _DEFAULT_HOST,
        port: int = 0,
        authkey: bytes | None = None,
    ) -> "LocalAuthorityService":
        if not host:
            raise AuthorityStoreError("service host must be non-empty")
        if port < 0:
            raise AuthorityStoreError("service port must be non-negative")
        resolved_authkey = authkey or secrets.token_bytes(32)
        core = _ServiceAuthorityCore()
        manager_type = _server_manager_type(core)
        manager = manager_type(address=(host, port), authkey=resolved_authkey)
        manager.start()
        address = cast(tuple[str, int], manager.address)
        return cls(
            endpoint=f"tcp://{address[0]}:{address[1]}",
            authkey=resolved_authkey,
            _manager=manager,
        )

    def config(
        self,
        *,
        backend_kind: AuthorityBackendKind = AuthorityBackendKind.CO_LOCATED_SERVICE,
        deployment_profile: AuthorityDeploymentProfile = (
            AuthorityDeploymentProfile.CO_LOCATED
        ),
        reference_id: str = "local-authority-service",
    ) -> AuthorityConfig:
        return AuthorityConfig(
            backend_kind=backend_kind,
            deployment_profile=deployment_profile,
            endpoint=self.endpoint,
            reference_id=reference_id,
            metadata={_AUTHKEY_METADATA_KEY: _encode_authkey(self.authkey)},
        )

    def health(self) -> Mapping[str, PlainData]:
        return cast(Mapping[str, PlainData], self._proxy().health())

    def advance_time(self, seconds: int) -> None:
        self._proxy().advance_time(seconds)

    def stop(self) -> None:
        self._manager.shutdown()

    def __enter__(self) -> "LocalAuthorityService":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def _proxy(self) -> Any:
        return self._manager.authority()  # type: ignore[attr-defined]


_SHARED_SERVICE_LOCK = threading.Lock()
_SHARED_CO_LOCATED_SERVICE: LocalAuthorityService | None = None
_SHARED_SERVICE_ATEXIT_REGISTERED = False


class ServiceAuthorityStore(PerRunAuthorityStore):
    """Per-run authority client that communicates only through a service proxy."""

    def __init__(self, proxy: Any, config: AuthorityConfig) -> None:
        self._proxy = proxy
        self._config = config
        self._call_lock = threading.Lock()

    @property
    def authority_config(self) -> AuthorityConfig:
        return self._config

    def health(self) -> Mapping[str, PlainData]:
        return cast(Mapping[str, PlainData], self._call("health"))

    def advance_time(self, seconds: int) -> None:
        self._call("advance_time", seconds)

    def capabilities(self) -> BackendCapabilitySet:
        return cast(BackendCapabilitySet, self._call("capabilities"))

    def check_schema(self, run_uri: str) -> AuthoritySchemaCheck:
        return cast(AuthoritySchemaCheck, self._call("check_schema", run_uri))

    def create_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call(
                "create_run",
                run_uri,
                status=status,
                metadata=_plain_mapping_or_none(metadata, "metadata"),
            ),
        )

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return AuthoritativeRunSnapshot.from_dict(self._call("open_run", run_uri))

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        return StatusTransition.from_dict(
            self._call(
                "transition_run",
                run_uri,
                from_status=from_status,
                to_status=to_status,
                reason=_reason_to_wire(reason),
            ),
        )

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        return StatusTransition.from_dict(
            self._call(
                "transition_stage",
                run_uri,
                stage_name,
                from_status=from_status,
                to_status=to_status,
                reason=_reason_to_wire(reason),
            ),
        )

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation:
        return cast(
            AttemptAllocation,
            self._call(
                "allocate_stage_attempt",
                run_uri,
                stage_name,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
            ),
        )

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        return cast(
            LeaseRecord,
            self._call(
                "acquire_controller_lease",
                run_uri,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
            ),
        )

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        return cast(
            LeaseRecord,
            self._call(
                "renew_lease",
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                lease_ttl_seconds=lease_ttl_seconds,
            ),
        )

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        return LeaseRecord.from_dict(
            self._call(
                "release_lease",
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=_reason_to_wire(reason),
            ),
        )

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        return LeaseRecord.from_dict(
            self._call(
                "fail_lease",
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=_reason_to_wire(reason),
            ),
        )

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call("write_submitted_operation", run_uri, record.to_dict()),
        )

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        return cast(
            SubmittedOperationRecord | None,
            _submitted_operation_or_none(
                self._call("read_submitted_operation", run_uri, submission_id)
            ),
        )

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        return cast(
            tuple[SubmittedOperationRecord, ...],
            tuple(
                SubmittedOperationRecord.from_dict(record)
                for record in cast(
                    tuple[object, ...],
                    self._call("list_submitted_operations", run_uri),
                )
            ),
        )

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call("write_reliability_policy_fact", run_uri, fact.to_dict()),
        )

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        return tuple(
            ReliabilityPolicyFact.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call(
                    "list_reliability_policy_facts",
                    run_uri,
                    stage_name=stage_name,
                ),
            )
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call("write_reliability_status_detail", run_uri, detail.to_dict()),
        )

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return tuple(
            ReliabilityStatusDetail.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call(
                    "list_reliability_status_details",
                    run_uri,
                    stage_name=stage_name,
                ),
            )
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call(
                "write_stage_attempt_transaction",
                run_uri,
                transaction.to_dict(),
            ),
        )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        return tuple(
            StageAttemptTransaction.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call("read_transaction_chain", run_uri, transaction_id),
            )
        )

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        return tuple(
            StageAttemptTransaction.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call(
                    "list_stage_attempt_transactions",
                    run_uri,
                    stage_name=stage_name,
                ),
            )
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call("write_retry_decision", run_uri, decision.to_dict()),
        )

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        return tuple(
            RetryDecisionRecord.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call("list_retry_decisions", run_uri, stage_name=stage_name),
            )
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call("write_timeout_outcome", run_uri, outcome.to_dict()),
        )

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        return tuple(
            TimeoutOutcomeRecord.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call("list_timeout_outcomes", run_uri, stage_name=stage_name),
            )
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
        return cast(
            OutputCommit,
            OutputCommit.from_dict(
                self._call(
                    "record_output_commit",
                    run_uri,
                    stage_name,
                    attempt_id=attempt_id,
                    fencing_token=fencing_token,
                    outputs={
                        name: artifact.to_dict() for name, artifact in outputs.items()
                    },
                    reason=_reason_to_wire(reason),
                )
            ),
        )

    def append_audit_event(
        self, run_uri: str, event: PipelineEvent
    ) -> PipelineEventRecord:
        return PipelineEventRecord.from_dict(
            self._call(
                "append_audit_event",
                run_uri,
                event.to_dict(),
            ),
        )

    def append_event_sink_failure(
        self, run_uri: str, failure: EventSinkFailureRecord
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call("append_event_sink_failure", run_uri, failure.to_dict()),
        )

    def read_event_sink_failures(
        self, run_uri: str
    ) -> tuple[EventSinkFailureRecord, ...]:
        return tuple(
            EventSinkFailureRecord.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call("read_event_sink_failures", run_uri),
            )
        )

    def append_event_observer_link(
        self, run_uri: str, link: EventObserverLinkRecord
    ) -> BackendRevision:
        return cast(
            BackendRevision,
            self._call("append_event_observer_link", run_uri, link.to_dict()),
        )

    def read_event_observer_links(
        self, run_uri: str
    ) -> tuple[EventObserverLinkRecord, ...]:
        return tuple(
            EventObserverLinkRecord.from_dict(record)
            for record in cast(
                tuple[object, ...],
                self._call("read_event_observer_links", run_uri),
            )
        )

    def snapshot(self, run_uri: str) -> AuthoritativeRunSnapshot:
        return AuthoritativeRunSnapshot.from_dict(self._call("snapshot", run_uri))

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        return cast(tuple[RecoveryRecord, ...], self._call("scan_recovery", run_uri))

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        return cast(
            tuple[CleanupCandidate, ...],
            self._call("list_cleanup_candidates", run_uri),
        )

    def append_cleanup_report(
        self, run_uri: str, report: CleanupReport
    ) -> CleanupReportFact:
        return CleanupReportFact.from_dict(
            self._call("append_cleanup_report", run_uri, report.to_dict())
        )

    def list_cleanup_reports(self, run_uri: str) -> tuple[CleanupReportFact, ...]:
        return tuple(
            CleanupReportFact.from_dict(record)
            for record in cast(
                tuple[object, ...], self._call("list_cleanup_reports", run_uri)
            )
        )

    def append_cleanup_result(
        self, run_uri: str, result: CleanupResult
    ) -> CleanupResultFact:
        return CleanupResultFact.from_dict(
            self._call("append_cleanup_result", run_uri, result.to_dict())
        )

    def list_cleanup_results(self, run_uri: str) -> tuple[CleanupResultFact, ...]:
        return tuple(
            CleanupResultFact.from_dict(record)
            for record in cast(
                tuple[object, ...], self._call("list_cleanup_results", run_uri)
            )
        )

    def _call(self, method_name: str, *args: object, **kwargs: object) -> object:
        try:
            with self._call_lock:
                method = getattr(self._proxy, method_name)
                return method(*args, **kwargs)
        except (ConnectionError, EOFError, OSError) as exc:
            raise AuthorityServiceUnavailable(
                "authority service is unavailable"
            ) from exc
        except ValueError as exc:
            raise AuthorityStoreError(str(exc)) from exc


def create_service_authority_store(config: AuthorityConfig) -> ServiceAuthorityStore:
    """Create a service authority client from public authority configuration."""

    if config.backend_kind not in _SERVICE_BACKEND_KINDS:
        raise AuthorityStoreError(
            "service authority requires a service backend kind, got "
            f"{config.backend_kind.value}"
        )
    if config.state_path is not None:
        raise AuthorityStoreError(
            "service authority clients must not use a direct state_path"
        )
    if config.endpoint is None:
        raise AuthorityStoreError(
            f"{config.backend_kind.value} authority requires an explicit endpoint; "
            "start or select an authority service before constructing a client"
        )
    host, port = _parse_endpoint(config.endpoint)
    authkey = _decode_authkey(config.metadata.get(_AUTHKEY_METADATA_KEY))
    manager_type = _client_manager_type()
    manager = manager_type(address=(host, port), authkey=authkey)
    try:
        manager.connect()
        proxy = manager.authority()  # type: ignore[attr-defined]
        proxy.health()
    except Exception as exc:
        raise AuthorityServiceUnavailable(
            f"authority service is unavailable at {config.endpoint}"
        ) from exc
    return ServiceAuthorityStore(proxy, config)


def _shared_co_located_service() -> LocalAuthorityService:
    global _SHARED_CO_LOCATED_SERVICE, _SHARED_SERVICE_ATEXIT_REGISTERED
    with _SHARED_SERVICE_LOCK:
        if _SHARED_CO_LOCATED_SERVICE is None:
            _SHARED_CO_LOCATED_SERVICE = LocalAuthorityService.start()
        if not _SHARED_SERVICE_ATEXIT_REGISTERED:
            atexit.register(_stop_shared_co_located_service)
            _SHARED_SERVICE_ATEXIT_REGISTERED = True
        return _SHARED_CO_LOCATED_SERVICE


def _stop_shared_co_located_service() -> None:
    global _SHARED_CO_LOCATED_SERVICE
    with _SHARED_SERVICE_LOCK:
        service = _SHARED_CO_LOCATED_SERVICE
        _SHARED_CO_LOCATED_SERVICE = None
    if service is not None:
        service.stop()


def _config_for_local_service(
    config: AuthorityConfig,
    service: LocalAuthorityService,
) -> AuthorityConfig:
    metadata = dict(config.metadata)
    metadata[_AUTHKEY_METADATA_KEY] = _encode_authkey(service.authkey)
    return AuthorityConfig(
        backend_kind=config.backend_kind,
        deployment_profile=config.deployment_profile,
        endpoint=service.endpoint,
        workspace_id=config.workspace_id,
        state_path=None,
        reference_id=config.reference_id,
        redaction_keys=config.redaction_keys,
        metadata=metadata,
    )


class _RunState:
    def __init__(self, run_uri: str, status: RunStatus, revision: BackendRevision):
        self.run_uri = run_uri
        self.status = status
        self.revision = revision
        self.stage_statuses: dict[str, StageStatus] = {}
        self.attempts: dict[str, list[StageAttempt]] = {}
        self.leases: dict[str, LeaseRecord] = {}
        self.submitted: dict[str, SubmittedOperationRecord] = {}
        self.commits: dict[str, OutputCommitRecord] = {}
        self.facts: dict[str, list[ArtifactFactRecord]] = {}
        self.cleanup: list[CleanupCandidate] = []
        self.cleanup_reports: dict[str, CleanupReportFact] = {}
        self.cleanup_results: dict[str, CleanupResultFact] = {}
        self.events: list[PipelineEventRecord] = []
        self.event_sink_failures: list[EventSinkFailureRecord] = []
        self.event_observer_links: list[EventObserverLinkRecord] = []
        self.reliability_policy_facts: dict[str, ReliabilityPolicyFact] = {}
        self.reliability_status_details: dict[str, ReliabilityStatusDetail] = {}
        self.reliability_transactions: dict[str, StageAttemptTransaction] = {}
        self.retry_decisions: dict[str, RetryDecisionRecord] = {}
        self.timeout_outcomes: dict[str, TimeoutOutcomeRecord] = {}


class _ServiceAuthorityCore:
    def __init__(self) -> None:
        self._runs: dict[str, _RunState] = {}
        self._revision = 0
        self._tick = 0
        self._lease_expiry_ticks: dict[str, int] = {}
        self._lock = threading.RLock()

    def health(self) -> dict[str, PlainData]:
        with self._lock:
            return {
                "ok": True,
                "backend_name": "local-authority-service",
                "runs": len(self._runs),
                "revision": self._revision,
            }

    def capabilities(self) -> BackendCapabilitySet:
        supported = (
            BackendCapability.RUN_ADMISSION,
            BackendCapability.ATOMIC_TRANSITIONS,
            BackendCapability.ATTEMPT_ALLOCATION,
            BackendCapability.RUN_LEASES,
            BackendCapability.STAGE_LEASES,
            BackendCapability.LEASE_TTL,
            BackendCapability.FENCING_TOKENS,
            BackendCapability.BACKEND_LEASE_TIME,
            BackendCapability.ATOMIC_OUTPUT_COMMIT,
            BackendCapability.ARTIFACT_FACTS,
            BackendCapability.RELIABILITY_FACTS,
            BackendCapability.SUBMITTED_OPERATIONS,
            BackendCapability.REVISIONED_SNAPSHOTS,
            BackendCapability.MONOTONIC_REVISIONS,
            BackendCapability.RECOVERY_SCANS,
            BackendCapability.CONSISTENT_READS,
            BackendCapability.TRANSACTION_ISOLATION,
            BackendCapability.CLOCK_SEMANTICS,
            BackendCapability.MATERIALIZATION_REFS,
            BackendCapability.AUDIT_EVENTS,
            BackendCapability.PER_RUN_COORDINATION,
            BackendCapability.SINGLE_HOST_AUTHORITY,
            BackendCapability.SERVICE_ENDPOINT,
        )
        unsupported = {
            BackendCapability.MULTI_HOST_AUTHORITY:
                "the local service fixture proves endpoint semantics but not "
                "production multi-host deployment",
            BackendCapability.SHARED_FILESYSTEM_SAFE:
                "clients do not share direct authority files",
            BackendCapability.DEFERRED_FINALIZATION:
                "deferred finalization is defined by a later deployment phase",
            BackendCapability.CROSS_RUN_COORDINATION:
                "workspace-level coordination is not implemented by this backend",
            BackendCapability.GLOBAL_COUNTERS:
                "workspace-level counters are not implemented by this backend",
        }
        return BackendCapabilitySet(
            backend_name="local-authority-service",
            records=tuple(
                BackendCapabilityRecord(
                    capability=capability,
                    scope=CapabilityScope.PER_RUN,
                    detail={"service_boundary": True},
                )
                for capability in supported
            )
            + tuple(
                BackendCapabilityRecord(
                    capability=capability,
                    scope=CapabilityScope.CROSS_RUN
                    if capability
                    in {
                        BackendCapability.CROSS_RUN_COORDINATION,
                        BackendCapability.GLOBAL_COUNTERS,
                    }
                    else CapabilityScope.PER_RUN,
                    support=CapabilitySupport.UNSUPPORTED,
                    message=message,
                    detail={"service_boundary": True},
                )
                for capability, message in unsupported.items()
            ),
        )

    def check_schema(self, run_uri: str) -> AuthoritySchemaCheck:
        validate_run_uri(run_uri)
        with self._lock:
            return check_authority_schema_version(
                {"schema_version": AUTHORITY_SCHEMA_VERSION}
            )

    def create_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
    ) -> BackendRevision:
        validate_run_uri(run_uri)
        with self._lock:
            if run_uri in self._runs:
                raise ValueError(f"run already exists: {run_uri}")
            revision = self._next_revision()
            self._runs[run_uri] = _RunState(run_uri, RunStatus(status), revision)
            return revision

    def open_run(self, run_uri: str) -> dict[str, PlainData]:
        return self.snapshot(run_uri)

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        reason: object = None,
    ) -> dict[str, PlainData]:
        with self._lock:
            state = self._require_run(run_uri)
            if state.status is not from_status:
                raise ValueError("stale run transition")
            previous = state.status
            state.status = to_status
            state.revision = self._next_revision()
            return StatusTransition(
                run_uri=run_uri,
                previous_status=previous,
                status=to_status,
                revision=state.revision,
                reason=_reason_from_wire(reason),
            ).to_dict()

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        reason: object = None,
    ) -> dict[str, PlainData]:
        with self._lock:
            state = self._require_run(run_uri)
            current = state.stage_statuses.get(stage_name)
            if current is not from_status:
                raise ValueError("stale stage transition")
            state.stage_statuses[stage_name] = to_status
            state.revision = self._next_revision()
            return StatusTransition(
                run_uri=run_uri,
                stage_name=stage_name,
                previous_status=current,
                status=to_status,
                revision=state.revision,
                reason=_reason_from_wire(reason),
            ).to_dict()

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
    ) -> AttemptAllocation:
        with self._lock:
            state = self._require_run(run_uri)
            if stage_name in state.commits:
                raise ValueError("stage already has an output commit")
            if (
                lease_ttl_seconds is not None
                and self._active_stage_lease(state, stage_name) is not None
            ):
                raise ValueError("stage already has an active lease")
            attempt_number = len(state.attempts.get(stage_name, ())) + 1
            revision = self._next_revision()
            attempt = StageAttempt(
                run_uri=run_uri,
                stage_name=stage_name,
                attempt=attempt_number,
                attempt_id=f"{stage_name}-{attempt_number}",
                status=StageStatus.RUNNING,
                revision=revision,
                created_at=self._now(),
                owner=owner_id,
            )
            state.attempts.setdefault(stage_name, []).append(attempt)
            state.stage_statuses[stage_name] = StageStatus.RUNNING
            lease = None
            if lease_ttl_seconds is not None:
                lease = self._new_lease(
                    state,
                    kind=LeaseKind.STAGE,
                    owner_id=owner_id,
                    lease_ttl_seconds=lease_ttl_seconds,
                    stage_name=stage_name,
                    attempt_id=attempt.attempt_id,
                )
            return AttemptAllocation(attempt=attempt, lease=lease)

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        with self._lock:
            state = self._require_run(run_uri)
            return self._new_lease(
                state,
                kind=LeaseKind.CONTROLLER,
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
        with self._lock:
            state, lease = self._require_lease(lease_id, owner_id, fencing_token)
            renewed = self._replace_lease(
                state,
                lease,
                renewed_at=self._now(),
                expires_at=self._at_tick(self._tick + lease_ttl_seconds),
                revision=self._next_revision(),
            )
            self._lease_expiry_ticks[lease_id] = self._tick + lease_ttl_seconds
            return renewed

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: object = None,
    ) -> dict[str, PlainData]:
        with self._lock:
            state, lease = self._require_lease(lease_id, owner_id, fencing_token)
            return self._replace_lease(
                state,
                lease,
                state_value=LeaseState.RELEASED,
                revision=self._next_revision(),
                reason=_reason_from_wire(reason),
            ).to_dict()

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: object,
    ) -> dict[str, PlainData]:
        with self._lock:
            state, lease = self._require_lease(lease_id, owner_id, fencing_token)
            return self._replace_lease(
                state,
                lease,
                state_value=LeaseState.FAILED,
                revision=self._next_revision(),
                reason=_reason_from_wire(reason),
            ).to_dict()

    def write_submitted_operation(
        self, run_uri: str, record: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = SubmittedOperationRecord.from_dict(record)
            state.submitted[record.submission_id] = record
            state.revision = self._next_revision()
            return state.revision

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> dict[str, PlainData] | None:
        with self._lock:
            record = self._require_run(run_uri).submitted.get(submission_id)
            return None if record is None else record.to_dict()

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                record.to_dict()
                for record in self._require_run(run_uri).submitted.values()
            )

    def write_reliability_policy_fact(
        self, run_uri: str, fact: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = ReliabilityPolicyFact.from_dict(fact)
            validate_policy_fact_run(record, run_uri)
            return self._store_immutable_reliability_fact(
                state.reliability_policy_facts,
                reliability_policy_fact_key(record),
                record,
                state,
            )

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            facts = self._require_run(run_uri).reliability_policy_facts.values()
            return tuple(
                fact.to_dict()
                for fact in sorted(
                    (
                        fact
                        for fact in facts
                        if stage_name is None or fact.stage_name == stage_name
                    ),
                    key=lambda fact: (
                        fact.scope.value,
                        fact.stage_name or "",
                        fact.attempt or 0,
                        fact.recorded_at,
                    ),
                )
            )

    def write_reliability_status_detail(
        self, run_uri: str, detail: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = ReliabilityStatusDetail.from_dict(detail)
            validate_status_detail_run(record, run_uri)
            return self._store_immutable_reliability_fact(
                state.reliability_status_details,
                reliability_status_detail_key(record),
                record,
                state,
            )

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                record.to_dict()
                for record in self._stage_reliability_records(
                    self._require_run(run_uri).reliability_status_details.values(),
                    stage_name=stage_name,
                    sort_key=lambda detail: (
                        detail.stage_id,
                        detail.attempt,
                        detail.created_at,
                    ),
                )
            )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = StageAttemptTransaction.from_dict(transaction)
            validate_transaction_run(record, run_uri)
            return self._store_immutable_reliability_fact(
                state.reliability_transactions,
                record.transaction_id,
                record,
                state,
            )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            transactions = self._require_run(run_uri).reliability_transactions
            current = transactions.get(transaction_id)
            if current is None:
                return ()
            chain: list[StageAttemptTransaction] = []
            seen: set[str] = set()
            while current is not None:
                if current.transaction_id in seen:
                    raise ValueError("reliability transaction chain contains a cycle")
                seen.add(current.transaction_id)
                chain.append(current)
                parent_id = current.causal_parent_id
                current = None if parent_id is None else transactions.get(parent_id)
            return tuple(record.to_dict() for record in reversed(chain))

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                record.to_dict()
                for record in self._stage_reliability_records(
                    self._require_run(run_uri).reliability_transactions.values(),
                    stage_name=stage_name,
                    sort_key=lambda transaction: (
                        transaction.stage_id,
                        transaction.attempt,
                        transaction.transaction_id,
                    ),
                )
            )

    def write_retry_decision(
        self, run_uri: str, decision: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = RetryDecisionRecord.from_dict(decision)
            validate_retry_decision_run(record, run_uri)
            return self._store_immutable_reliability_fact(
                state.retry_decisions,
                record.decision_id,
                record,
                state,
            )

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                record.to_dict()
                for record in self._stage_reliability_records(
                    self._require_run(run_uri).retry_decisions.values(),
                    stage_name=stage_name,
                    sort_key=lambda decision: (
                        decision.status.stage_id,
                        decision.status.attempt,
                        decision.decision_id,
                    ),
                )
            )

    def write_timeout_outcome(
        self, run_uri: str, outcome: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = TimeoutOutcomeRecord.from_dict(outcome)
            validate_timeout_outcome_run(record, run_uri)
            return self._store_immutable_reliability_fact(
                state.timeout_outcomes,
                record.outcome_id,
                record,
                state,
            )

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                record.to_dict()
                for record in self._stage_reliability_records(
                    self._require_run(run_uri).timeout_outcomes.values(),
                    stage_name=stage_name,
                    sort_key=lambda outcome: (
                        outcome.status.stage_id,
                        outcome.status.attempt,
                        outcome.outcome_id,
                    ),
                )
            )

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        fencing_token: str,
        outputs: Mapping[str, object],
        reason: object = None,
    ) -> dict[str, PlainData]:
        with self._lock:
            state = self._require_run(run_uri)
            if stage_name in state.commits:
                raise ValueError("stage already has an output commit")
            lease = self._require_stage_fence(
                state, stage_name, attempt_id, fencing_token
            )
            revision = self._next_revision()
            commit = OutputCommitRecord(
                commit_id=f"{stage_name}-{attempt_id}-commit",
                run_uri=run_uri,
                stage_name=stage_name,
                attempt_id=attempt_id,
                committed_at=self._now(),
                revision=revision,
                output_names=tuple(outputs),
            )
            facts = tuple(
                ArtifactFactRecord(
                    artifact_name=name,
                    artifact=ArtifactRef.from_dict(artifact),
                    commit_id=commit.commit_id,
                    revision=revision,
                )
                for name, artifact in outputs.items()
            )
            state.commits[stage_name] = commit
            state.facts[stage_name] = list(facts)
            self._replace_lease(
                state,
                lease,
                revision=revision,
                state_value=LeaseState.RELEASED,
                reason=_reason_from_wire(reason),
            )
            state.attempts[stage_name] = [
                StageAttempt(
                    run_uri=attempt.run_uri,
                    stage_name=attempt.stage_name,
                    attempt=attempt.attempt,
                    attempt_id=attempt.attempt_id,
                    status=StageStatus.SUCCEEDED
                    if attempt.attempt_id == attempt_id
                    else attempt.status,
                    revision=revision
                    if attempt.attempt_id == attempt_id
                    else attempt.revision,
                    created_at=attempt.created_at,
                    owner=attempt.owner,
                    reason=_reason_from_wire(reason)
                    if attempt.attempt_id == attempt_id
                    else attempt.reason,
                )
                for attempt in state.attempts.get(stage_name, ())
            ]
            state.stage_statuses[stage_name] = StageStatus.SUCCEEDED
            state.revision = revision
            return OutputCommit(commit=commit, artifact_facts=facts).to_dict()

    def append_audit_event(self, run_uri: str, event: object) -> dict[str, PlainData]:
        with self._lock:
            state = self._require_run(run_uri)
            resolved_event = _pipeline_event_from_wire(event)
            record = PipelineEventRecord(
                run_uri=run_uri,
                sequence=len(state.events) + 1,
                timestamp=resolved_event.timestamp or self._now(),
                scope=resolved_event.scope,
                event_type=resolved_event.event_type,
                payload=_plain_mapping_from_wire(
                    resolved_event.payload, "PipelineEventRecord.payload"
                ),
            )
            state.events.append(record)
            state.revision = self._next_revision()
            return record.to_dict()

    def append_event_sink_failure(
        self, run_uri: str, failure: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = EventSinkFailureRecord.from_dict(failure)
            _validate_observer_fact_run_uri(record.run_uri, run_uri, "event sink failure")
            state.event_sink_failures.append(record)
            state.revision = self._next_revision()
            return state.revision

    def read_event_sink_failures(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                failure.to_dict()
                for failure in self._require_run(run_uri).event_sink_failures
            )

    def append_event_observer_link(
        self, run_uri: str, link: object
    ) -> BackendRevision:
        with self._lock:
            state = self._require_run(run_uri)
            record = EventObserverLinkRecord.from_dict(link)
            _validate_observer_fact_run_uri(record.run_uri, run_uri, "event observer link")
            state.event_observer_links.append(record)
            state.revision = self._next_revision()
            return state.revision

    def read_event_observer_links(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                link.to_dict()
                for link in self._require_run(run_uri).event_observer_links
            )

    def snapshot(self, run_uri: str) -> dict[str, PlainData]:
        with self._lock:
            state = self._require_run(run_uri)
            stage_names = set(state.stage_statuses)
            stage_names.update(state.attempts)
            stage_names.update(state.commits)
            stage_names.update(
                fact.stage_name
                for fact in state.reliability_policy_facts.values()
                if fact.stage_name is not None
            )
            stage_names.update(
                detail.stage_id
                for detail in state.reliability_status_details.values()
            )
            stage_names.update(
                transaction.stage_id
                for transaction in state.reliability_transactions.values()
            )
            stage_names.update(
                decision.status.stage_id
                for decision in state.retry_decisions.values()
            )
            stage_names.update(
                outcome.status.stage_id
                for outcome in state.timeout_outcomes.values()
            )
            stages = tuple(
                StageLifecycleSnapshot(
                    stage_name=stage_name,
                    status=state.stage_statuses.get(stage_name, StageStatus.PENDING),
                    revision=state.revision,
                    attempts=tuple(state.attempts.get(stage_name, ())),
                    active_lease=self._active_stage_lease(state, stage_name),
                    latest_commit=state.commits.get(stage_name),
                    artifact_facts=tuple(state.facts.get(stage_name, ())),
                    reliability_policy_facts=tuple(
                        ReliabilityPolicyFact.from_dict(record)
                        for record in self.list_reliability_policy_facts(
                            run_uri,
                            stage_name=stage_name,
                        )
                    ),
                    reliability_status_details=tuple(
                        ReliabilityStatusDetail.from_dict(record)
                        for record in self.list_reliability_status_details(
                            run_uri,
                            stage_name=stage_name,
                        )
                    ),
                    reliability_transactions=tuple(
                        StageAttemptTransaction.from_dict(record)
                        for record in self.list_stage_attempt_transactions(
                            run_uri,
                            stage_name=stage_name,
                        )
                    ),
                    retry_decisions=tuple(
                        RetryDecisionRecord.from_dict(record)
                        for record in self.list_retry_decisions(
                            run_uri,
                            stage_name=stage_name,
                        )
                    ),
                    timeout_outcomes=tuple(
                        TimeoutOutcomeRecord.from_dict(record)
                        for record in self.list_timeout_outcomes(
                            run_uri,
                            stage_name=stage_name,
                        )
                    ),
                )
                for stage_name in sorted(stage_names)
            )
            return AuthoritativeRunSnapshot(
                run_uri=run_uri,
                status=state.status,
                schema_version=AUTHORITY_SCHEMA_VERSION,
                revision=state.revision,
                stages=stages,
                submitted_operations=tuple(state.submitted.values()),
                cleanup_candidates=tuple(state.cleanup),
                cleanup_reports=tuple(state.cleanup_reports.values()),
                cleanup_results=tuple(state.cleanup_results.values()),
                reliability_policy_facts=tuple(
                    fact
                    for fact in state.reliability_policy_facts.values()
                    if fact.stage_name is None
                ),
            ).to_dict()

    def scan_recovery(self, run_uri: str) -> tuple[RecoveryRecord, ...]:
        with self._lock:
            state = self._require_run(run_uri)
            records: list[RecoveryRecord] = []
            for lease_id, lease in state.leases.items():
                if lease.state is LeaseState.ACTIVE and (
                    self._lease_expiry_ticks.get(lease_id, self._tick + 1)
                    <= self._tick
                ):
                    records.append(
                        RecoveryRecord(
                            recovery_id=f"expired-{lease_id}",
                            kind=RecoveryKind.EXPIRED_LEASE,
                            reason=LifecycleReason(code="lease_expired"),
                            detected_at=self._now(),
                            revision=state.revision,
                            run_uri=run_uri,
                            stage_name=lease.stage_name,
                            attempt_id=lease.attempt_id,
                        )
                    )
            return tuple(records)

    def list_cleanup_candidates(self, run_uri: str) -> tuple[CleanupCandidate, ...]:
        with self._lock:
            return tuple(self._require_run(run_uri).cleanup)

    def append_cleanup_report(
        self, run_uri: str, report: Mapping[str, PlainData]
    ) -> dict[str, PlainData]:
        parsed = CleanupReport.from_dict(report)
        if parsed.run_uri != run_uri:
            raise ValueError("cleanup report run_uri does not match run")
        with self._lock:
            state = self._require_run(run_uri)
            existing = state.cleanup_reports.get(parsed.report_id)
            if existing is not None:
                if existing.report.to_dict() == parsed.to_dict():
                    return existing.to_dict()
                raise ValueError("conflicting cleanup report already exists")
            state.revision = self._next_revision()
            fact = CleanupReportFact(
                report=parsed,
                recorded_at=self._now(),
                revision=state.revision,
            )
            state.cleanup_reports[parsed.report_id] = fact
            return fact.to_dict()

    def list_cleanup_reports(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                fact.to_dict()
                for fact in self._require_run(run_uri).cleanup_reports.values()
            )

    def append_cleanup_result(
        self, run_uri: str, result: Mapping[str, PlainData]
    ) -> dict[str, PlainData]:
        parsed = CleanupResult.from_dict(result)
        if parsed.run_uri != run_uri:
            raise ValueError("cleanup result run_uri does not match run")
        with self._lock:
            state = self._require_run(run_uri)
            existing = state.cleanup_results.get(parsed.result_id)
            if existing is not None:
                if existing.result.to_dict() == parsed.to_dict():
                    return existing.to_dict()
                raise ValueError("conflicting cleanup result already exists")
            state.revision = self._next_revision()
            fact = CleanupResultFact(
                result=parsed,
                recorded_at=self._now(),
                revision=state.revision,
            )
            state.cleanup_results[parsed.result_id] = fact
            return fact.to_dict()

    def list_cleanup_results(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...]:
        with self._lock:
            return tuple(
                fact.to_dict()
                for fact in self._require_run(run_uri).cleanup_results.values()
            )

    def advance_time(self, seconds: int) -> None:
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        with self._lock:
            self._tick += seconds

    def _store_immutable_reliability_fact[T](
        self,
        records: dict[str, T],
        key: str,
        record: T,
        state: _RunState,
    ) -> BackendRevision:
        existing = records.get(key)
        if existing is not None:
            existing_payload = getattr(existing, "to_dict")()
            record_payload = getattr(record, "to_dict")()
            if reliability_payload_matches(existing_payload, record_payload):
                return state.revision
            raise ValueError("conflicting reliability fact already exists")
        records[key] = record
        state.revision = self._next_revision()
        return state.revision

    def _stage_reliability_records[T](
        self,
        records: Iterable[T],
        *,
        stage_name: str | None,
        sort_key: Callable[[T], tuple[object, ...]],
    ) -> tuple[T, ...]:
        values = tuple(records)
        filtered = (
            record
            for record in values
            if stage_name is None
            or reliability_record_stage_name(
                cast(
                    ReliabilityStatusDetail
                    | StageAttemptTransaction
                    | RetryDecisionRecord
                    | TimeoutOutcomeRecord,
                    record,
                )
            )
            == stage_name
        )
        return tuple(sorted(filtered, key=sort_key))

    def _require_run(self, run_uri: str) -> _RunState:
        validate_run_uri(run_uri)
        try:
            return self._runs[run_uri]
        except KeyError as exc:
            raise ValueError(f"unknown run: {run_uri}") from exc

    def _next_revision(self) -> BackendRevision:
        self._revision += 1
        return BackendRevision(
            sequence=self._revision,
            token=f"service-rev-{self._revision}",
            created_at=self._now(),
        )

    def _new_lease(
        self,
        state: _RunState,
        *,
        kind: LeaseKind,
        owner_id: str,
        lease_ttl_seconds: int,
        stage_name: str | None = None,
        attempt_id: str | None = None,
    ) -> LeaseRecord:
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        revision = self._next_revision()
        lease_id = f"service-lease-{revision.sequence}"
        lease = LeaseRecord(
            lease_id=lease_id,
            kind=kind,
            owner_id=owner_id,
            fencing_token=f"service-fence-{revision.sequence}",
            acquired_at=self._now(),
            renewed_at=self._now(),
            expires_at=self._at_tick(self._tick + lease_ttl_seconds),
            revision=revision,
            run_uri=state.run_uri,
            stage_name=stage_name,
            attempt_id=attempt_id,
        )
        state.leases[lease_id] = lease
        self._lease_expiry_ticks[lease_id] = self._tick + lease_ttl_seconds
        state.revision = revision
        return lease

    def _require_lease(
        self, lease_id: str, owner_id: str, fencing_token: str
    ) -> tuple[_RunState, LeaseRecord]:
        for state in self._runs.values():
            lease = state.leases.get(lease_id)
            if lease is None:
                continue
            if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
                raise ValueError("stale or foreign lease token")
            if lease.state is not LeaseState.ACTIVE:
                raise ValueError("lease is not active")
            if self._lease_expired(lease):
                raise ValueError("lease has expired")
            return state, lease
        raise ValueError(f"unknown lease: {lease_id}")

    def _replace_lease(
        self,
        state: _RunState,
        lease: LeaseRecord,
        *,
        renewed_at: str | None = None,
        expires_at: str | None = None,
        revision: BackendRevision,
        state_value: LeaseState | None = None,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        updated = LeaseRecord(
            lease_id=lease.lease_id,
            kind=lease.kind,
            owner_id=lease.owner_id,
            fencing_token=lease.fencing_token,
            acquired_at=lease.acquired_at,
            renewed_at=renewed_at or lease.renewed_at,
            expires_at=expires_at or lease.expires_at,
            revision=revision,
            state=state_value or lease.state,
            run_uri=lease.run_uri,
            stage_name=lease.stage_name,
            attempt_id=lease.attempt_id,
            reason=reason or lease.reason,
        )
        state.leases[lease.lease_id] = updated
        state.revision = revision
        return updated

    def _require_stage_fence(
        self,
        state: _RunState,
        stage_name: str,
        attempt_id: str,
        fencing_token: str,
    ) -> LeaseRecord:
        for lease in state.leases.values():
            if (
                lease.kind is LeaseKind.STAGE
                and lease.stage_name == stage_name
                and lease.attempt_id == attempt_id
                and lease.fencing_token == fencing_token
            ):
                if self._lease_expired(lease):
                    raise ValueError("stage lease has expired")
                if lease.state is not LeaseState.ACTIVE:
                    raise ValueError("stage lease is not active")
                return lease
        raise ValueError("missing active stage lease for output commit")

    def _active_stage_lease(
        self, state: _RunState, stage_name: str
    ) -> LeaseRecord | None:
        for lease in state.leases.values():
            if (
                lease.kind is LeaseKind.STAGE
                and lease.stage_name == stage_name
                and lease.state is LeaseState.ACTIVE
                and not self._lease_expired(lease)
            ):
                return lease
        return None

    def _lease_expired(self, lease: LeaseRecord) -> bool:
        return (
            self._lease_expiry_ticks.get(lease.lease_id, self._tick + 1) <= self._tick
        )

    def _now(self) -> str:
        return self._at_tick(self._tick)

    @staticmethod
    def _at_tick(tick: int) -> str:
        value = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(seconds=tick)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _server_manager_type(core: _ServiceAuthorityCore) -> type[BaseManager]:
    class AuthorityServiceManager(BaseManager):
        pass

    AuthorityServiceManager.register(
        "authority",
        callable=lambda: core,
        exposed=_EXPOSED,
    )
    return AuthorityServiceManager


def _client_manager_type() -> type[BaseManager]:
    class AuthorityServiceManager(BaseManager):
        pass

    AuthorityServiceManager.register("authority", exposed=_EXPOSED)
    return AuthorityServiceManager


def _parse_endpoint(endpoint: str | None) -> tuple[str, int]:
    if endpoint is None:
        raise AuthorityStoreError("service authority requires endpoint")
    parsed = urlparse(endpoint)
    if parsed.scheme != "tcp" or not parsed.hostname or parsed.port is None:
        raise AuthorityStoreError(
            "service authority endpoint must use tcp://host:port"
        )
    return parsed.hostname, parsed.port


def _submitted_operation_or_none(value: object) -> SubmittedOperationRecord | None:
    if value is None:
        return None
    return SubmittedOperationRecord.from_dict(value)


def _plain_mapping_or_none(
    value: Mapping[str, PlainData] | None, path: str
) -> dict[str, PlainData] | None:
    if value is None:
        return None
    normalized = thaw_plain_data(value, path=path)
    if not isinstance(normalized, dict):
        raise AuthorityStoreError(f"{path} must be a mapping")
    return cast(dict[str, PlainData], normalized)


def _reason_to_wire(reason: LifecycleReason | None) -> dict[str, PlainData] | None:
    return None if reason is None else reason.to_dict()


def _reason_from_wire(reason: object) -> LifecycleReason | None:
    if reason is None:
        return None
    if isinstance(reason, LifecycleReason):
        return reason
    return LifecycleReason.from_dict(reason)


def _pipeline_event_from_wire(value: object) -> PipelineEvent:
    if isinstance(value, PipelineEvent):
        return value
    mapping = _object_mapping(value, "PipelineEvent")
    timestamp = mapping.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, str):
        raise AuthorityStoreError("PipelineEvent.timestamp must be a string or null")
    event_type = mapping.get("event_type")
    if not isinstance(event_type, str):
        raise AuthorityStoreError("PipelineEvent.event_type must be a string")
    return PipelineEvent(
        scope=EventScope.from_dict(mapping.get("scope")),
        event_type=event_type,
        payload=_plain_mapping_from_wire(mapping.get("payload", {}), "PipelineEvent.payload"),
        timestamp=timestamp,
    )


def _plain_mapping_from_wire(value: object, path: str) -> dict[str, PlainData]:
    normalized = thaw_plain_data(value, path=path)
    if not isinstance(normalized, dict):
        raise AuthorityStoreError(f"{path} must be a mapping")
    return cast(dict[str, PlainData], normalized)


def _validate_observer_fact_run_uri(actual: str, expected: str, label: str) -> None:
    if actual != expected:
        raise AuthorityStoreError(
            f"{label} run_uri {actual!r} does not match {expected!r}"
        )


def _object_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityStoreError(f"{field} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise AuthorityStoreError(f"{field} must have string keys")
    return cast(Mapping[str, object], value)


def _encode_authkey(authkey: bytes) -> str:
    return base64.urlsafe_b64encode(authkey).decode("ascii")


def _decode_authkey(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise AuthorityStoreError("service authority requires metadata.authkey")
    try:
        return base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception as exc:
        raise AuthorityStoreError("service authority authkey is invalid") from exc


__all__ = [
    "AuthorityServiceUnavailable",
    "LocalAuthorityService",
    "ServiceAuthorityStore",
    "create_service_authority_store",
]

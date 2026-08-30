"""Concrete embedded and authenticated coordinator authority adapters."""

from __future__ import annotations

import hashlib
import json
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib import request

from loom.artifacts import ArtifactRef
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import TransitionIntent
from loom.serialization import PlainData

from .authority import (
    AuthorityStoreError,
    CancellationEpochReceipt,
    CancellationEpochRequest,
    CoordinatorAdmissionReceipt,
    CoordinatorAdmissionRequest,
    ExecutionFence,
    OutputCommit,
    PreparedAttemptReceipt,
    PreparedAttemptRequest,
    StatusTransition,
)
from .authority_client import AuthorityClient
from .authority_protocol import (
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolReadiness,
    AuthorityProtocolRequest,
    AuthorityProtocolResult,
)
from .read_models import (
    AuthoritativeRunSnapshot,
    BackendRevision,
    LifecycleReason,
    ReliabilityPolicyFact,
)


COORDINATOR_AUTHORITY_ROUTE_PREFIX = "/v1/authority/coordinator"
COORDINATOR_AUTHORITY_SERVICE_HEADER = "X-Loom-Authority-Service"
COORDINATOR_OPEN_RUN_PATH = f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/runs/open"
COORDINATOR_TRANSITION_RUN_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/runs/transition"
)
COORDINATOR_TRANSITION_STAGE_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/stages/transition"
)
COORDINATOR_BIND_ADMISSION_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/admissions/bind"
)
COORDINATOR_INSTALL_CANCELLATION_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/cancellation/install"
)
COORDINATOR_READ_CANCELLATION_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/cancellation/read"
)
COORDINATOR_FINALIZE_CANCELLATION_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/cancellation/finalize"
)
COORDINATOR_PREPARE_ATTEMPT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/prepare"
)
COORDINATOR_BIND_ATTEMPT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/bind"
)
COORDINATOR_UNBIND_ATTEMPT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/unbind"
)
COORDINATOR_GRANT_ATTEMPT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/grant"
)
COORDINATOR_START_ATTEMPT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/start"
)
COORDINATOR_TERMINAL_ATTEMPT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/terminal"
)
COORDINATOR_CLOSE_ATTEMPT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/recovery-close"
)
COORDINATOR_COMMIT_OUTPUT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/attempts/output-commit"
)
COORDINATOR_WRITE_POLICY_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/policies/write"
)
COORDINATOR_LIST_POLICIES_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/policies/list"
)
COORDINATOR_WRITE_STATUS_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/statuses/write"
)
COORDINATOR_LIST_STATUSES_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/statuses/list"
)
COORDINATOR_WRITE_TRANSACTION_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/transactions/write"
)
COORDINATOR_READ_TRANSACTION_CHAIN_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/transactions/chain"
)
COORDINATOR_LIST_TRANSACTIONS_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/transactions/list"
)
COORDINATOR_WRITE_RETRY_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/retries/write"
)
COORDINATOR_LIST_RETRIES_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/retries/list"
)
COORDINATOR_WRITE_TIMEOUT_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/timeouts/write"
)
COORDINATOR_LIST_TIMEOUTS_PATH = (
    f"{COORDINATOR_AUTHORITY_ROUTE_PREFIX}/reliability/timeouts/list"
)


class AuthenticatedCoordinatorAuthorityError(AuthorityStoreError):
    """Typed rejection returned by the authenticated authority service."""

    def __init__(
        self,
        message: str,
        *,
        category: AuthorityProtocolErrorCategory,
        code: str,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code


@dataclass(frozen=True, slots=True)
class CoordinatorAuthorityTlsConfig:
    """Mutual-TLS files used by one protected coordinator role."""

    ca_path: Path
    certificate_path: Path
    private_key_path: Path

    def __post_init__(self) -> None:
        for name in ("ca_path", "certificate_path", "private_key_path"):
            value = Path(getattr(self, name))
            if not value.is_file():
                raise AuthorityStoreError(f"authority TLS {name} is unavailable")
            object.__setattr__(self, name, value)


def embedded_coordinator_authority(run_uri: str):
    """Open the explicit trusted embedded authority owner for one run."""

    from .sqlite_authority import SQLitePerRunAuthorityStore

    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.open_run(run_uri)
    return authority


def initialize_embedded_coordinator_authority(run_uri: str) -> None:
    """Create the embedded authority record for one prepared managed run.

    Project setup code uses this boundary before daemon admission. Runtime
    execution continues to receive only the narrow coordinator-authority
    adapter and never constructs or reaches into the concrete store.
    """

    from .sqlite_authority import SQLitePerRunAuthorityStore

    SQLitePerRunAuthorityStore(run_uri).create_run(run_uri, status=RunStatus.RUNNING)


def authenticated_coordinator_authority_factory(
    client: AuthorityClient,
    *,
    service_id: str,
    workspace_id: str,
    service_generation: str,
) -> Callable[[str], "AuthenticatedCoordinatorAuthority"]:
    """Bind a pinned client identity into run-scoped authority views."""

    return _AuthenticatedCoordinatorAuthorityFactory(
        client=client,
        service_id=_non_empty(service_id, "service_id"),
        workspace_id=_non_empty(workspace_id, "workspace_id"),
        service_generation=_non_empty(service_generation, "service_generation"),
    )


def https_coordinator_authority_factory(
    endpoint: str,
    *,
    service_id: str,
    workspace_id: str,
    tls: CoordinatorAuthorityTlsConfig,
    timeout_seconds: float = 30.0,
) -> Callable[[str], "AuthenticatedCoordinatorAuthority"]:
    """Probe and pin one HTTPS/mTLS authority before exposing its factory."""

    endpoint = _non_empty(endpoint, "endpoint").rstrip("/")
    if not endpoint.startswith("https://"):
        raise AuthorityStoreError("authenticated authority endpoint must use HTTPS")
    if not isinstance(tls, CoordinatorAuthorityTlsConfig):
        raise AuthorityStoreError("authenticated authority TLS config is invalid")
    transport = _MutualTlsJsonTransport(tls, service_id=service_id)
    readiness = AuthorityProtocolReadiness.from_dict(
        transport.get(f"{endpoint}/ready", timeout_seconds)
    )
    if not readiness.ready:
        raise AuthorityStoreError("authenticated authority service is not ready")
    if readiness.workspace_id != workspace_id:
        raise AuthorityStoreError("authenticated authority workspace conflicts")
    if readiness.service_generation is None:
        raise AuthorityStoreError(
            "authenticated authority service generation is unavailable"
        )
    return authenticated_coordinator_authority_factory(
        AuthorityClient(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            transport=transport,
        ),
        service_id=service_id,
        workspace_id=workspace_id,
        service_generation=readiness.service_generation,
    )


@dataclass(frozen=True, slots=True)
class _AuthenticatedCoordinatorAuthorityFactory:
    client: AuthorityClient
    service_id: str
    workspace_id: str
    service_generation: str

    def __call__(self, run_uri: str) -> "AuthenticatedCoordinatorAuthority":
        return AuthenticatedCoordinatorAuthority(
            run_uri,
            self.client,
            service_id=self.service_id,
            workspace_id=self.workspace_id,
            service_generation=self.service_generation,
        )


class AuthenticatedCoordinatorAuthority:
    """Run-scoped least-privilege mirror of coordinator authority operations."""

    def __init__(
        self,
        run_uri: str,
        client: AuthorityClient,
        *,
        service_id: str,
        workspace_id: str,
        service_generation: str,
    ) -> None:
        self._run_uri = _non_empty(run_uri, "run_uri")
        if not isinstance(client, AuthorityClient):
            raise AuthorityStoreError("authenticated authority client is invalid")
        self._client = client
        self._service_id = _non_empty(service_id, "service_id")
        self._workspace_id = _non_empty(workspace_id, "workspace_id")
        self._service_generation = _non_empty(
            service_generation, "service_generation"
        )

    def open_run(self, run_uri: str) -> AuthoritativeRunSnapshot:
        result = self._call(COORDINATOR_OPEN_RUN_PATH, run_uri)
        if result.snapshot is None:
            raise AuthorityStoreError("authority response has no run snapshot")
        return result.snapshot

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        result = self._call(
            COORDINATOR_TRANSITION_RUN_PATH,
            run_uri,
            expected_revision=expected_revision,
            body={
                "from_status": RunStatus(from_status).value,
                "to_status": RunStatus(to_status).value,
                "intent": TransitionIntent(intent).value,
                "reason": None if reason is None else reason.to_dict(),
            },
        )
        return StatusTransition.from_dict(_body_required(result, "transition"))

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
    ) -> StatusTransition:
        result = self._call(
            COORDINATOR_TRANSITION_STAGE_PATH,
            run_uri,
            stage_name=stage_name,
            expected_revision=expected_revision,
            body={
                "from_status": None
                if from_status is None
                else StageStatus(from_status).value,
                "to_status": StageStatus(to_status).value,
                "intent": TransitionIntent(intent).value,
                "reason": None if reason is None else reason.to_dict(),
            },
        )
        return StatusTransition.from_dict(_body_required(result, "transition"))

    def bind_coordinator_admission(
        self, run_uri: str, request_value: CoordinatorAdmissionRequest
    ) -> CoordinatorAdmissionReceipt:
        result = self._call(
            COORDINATOR_BIND_ADMISSION_PATH,
            run_uri,
            body={"request": request_value.to_dict()},
        )
        return CoordinatorAdmissionReceipt.from_dict(_body_required(result, "receipt"))

    def install_cancellation_epoch(
        self, run_uri: str, request_value: CancellationEpochRequest
    ) -> CancellationEpochReceipt:
        result = self._call(
            COORDINATOR_INSTALL_CANCELLATION_PATH,
            run_uri,
            body={"request": request_value.to_dict()},
        )
        return CancellationEpochReceipt.from_dict(_body_required(result, "receipt"))

    def read_cancellation_epoch_receipt(
        self, run_uri: str, operation_id: str
    ) -> CancellationEpochReceipt | None:
        result = self._call(
            COORDINATOR_READ_CANCELLATION_PATH,
            run_uri,
            body={"operation_id": _non_empty(operation_id, "operation_id")},
        )
        value = result.body.get("receipt")
        return None if value is None else CancellationEpochReceipt.from_dict(value)

    def finalize_cancellation(
        self, run_uri: str, request_value: CancellationEpochRequest
    ) -> RunStatus:
        result = self._call(
            COORDINATOR_FINALIZE_CANCELLATION_PATH,
            run_uri,
            body={"request": request_value.to_dict()},
        )
        return RunStatus(_body_required(result, "status"))

    def ensure_prepared_attempt(
        self, run_uri: str, request_value: PreparedAttemptRequest
    ) -> PreparedAttemptReceipt:
        result = self._call(
            COORDINATOR_PREPARE_ATTEMPT_PATH,
            run_uri,
            body={"request": request_value.to_dict()},
        )
        return PreparedAttemptReceipt.from_dict(_body_required(result, "receipt"))

    def bind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._attempt_pair(
            COORDINATOR_BIND_ATTEMPT_PATH, run_uri, assignment_id, attempt_id
        )

    def unbind_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> None:
        self._attempt_pair(
            COORDINATOR_UNBIND_ATTEMPT_PATH, run_uri, assignment_id, attempt_id
        )

    def grant_prepared_attempt(
        self, run_uri: str, *, assignment_id: str, attempt_id: str
    ) -> ExecutionFence:
        result = self._call(
            COORDINATOR_GRANT_ATTEMPT_PATH,
            run_uri,
            body=_attempt_pair_body(assignment_id, attempt_id),
        )
        return _execution_fence(_body_required(result, "fence"))

    def confirm_execution_started(
        self, run_uri: str, *, fence: ExecutionFence
    ) -> None:
        self._call(
            COORDINATOR_START_ATTEMPT_PATH,
            run_uri,
            body={"fence": _execution_fence_dict(fence)},
        )

    def record_managed_attempt_terminal(
        self,
        run_uri: str,
        *,
        fence: ExecutionFence,
        status: StageStatus,
        reason: LifecycleReason,
    ) -> StatusTransition:
        result = self._call(
            COORDINATOR_TERMINAL_ATTEMPT_PATH,
            run_uri,
            body={
                "fence": _execution_fence_dict(fence),
                "status": StageStatus(status).value,
                "reason": reason.to_dict(),
            },
        )
        return StatusTransition.from_dict(_body_required(result, "transition"))

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
        result = self._call(
            COORDINATOR_CLOSE_ATTEMPT_PATH,
            run_uri,
            body={
                "recovery_id": _non_empty(recovery_id, "recovery_id"),
                "fence": _execution_fence_dict(fence),
                "expected_state_version": expected_state_version,
                "status": StageStatus(status).value,
                "reason": reason.to_dict(),
            },
        )
        return StatusTransition.from_dict(_body_required(result, "transition"))

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
    ) -> OutputCommit:
        if assignment_id is None:
            raise AuthorityStoreError(
                "authenticated output commit requires an assignment"
            )
        result = self._call(
            COORDINATOR_COMMIT_OUTPUT_PATH,
            run_uri,
            stage_name=stage_name,
            fencing_token=fencing_token,
            body={
                "assignment_id": assignment_id,
                "attempt_id": attempt_id,
                "outputs": {
                    name: artifact.to_dict() for name, artifact in outputs.items()
                },
                "supersedes_commit_id": supersedes_commit_id,
                "reason": None if reason is None else reason.to_dict(),
            },
        )
        return OutputCommit.from_dict(_body_required(result, "commit"))

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> BackendRevision:
        return _required_revision(
            self._call(
                COORDINATOR_WRITE_POLICY_PATH,
                run_uri,
                kind=AuthorityProtocolOperationKind.RELIABILITY_FACTS,
                body={"fact": fact.to_dict()},
            )
        )

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        result = self._reliability_list(
            COORDINATOR_LIST_POLICIES_PATH, run_uri, stage_name
        )
        return tuple(
            ReliabilityPolicyFact.from_dict(item)
            for item in _body_sequence(result, "facts")
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> BackendRevision:
        return _required_revision(
            self._call(
                COORDINATOR_WRITE_STATUS_PATH,
                run_uri,
                kind=AuthorityProtocolOperationKind.RELIABILITY_FACTS,
                body={"detail": detail.to_dict()},
            )
        )

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        result = self._reliability_list(
            COORDINATOR_LIST_STATUSES_PATH, run_uri, stage_name
        )
        return tuple(
            ReliabilityStatusDetail.from_dict(item)
            for item in _body_sequence(result, "details")
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> BackendRevision:
        return _required_revision(
            self._call(
                COORDINATOR_WRITE_TRANSACTION_PATH,
                run_uri,
                kind=AuthorityProtocolOperationKind.RELIABILITY_FACTS,
                body={"transaction": transaction.to_dict()},
            )
        )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        result = self._call(
            COORDINATOR_READ_TRANSACTION_CHAIN_PATH,
            run_uri,
            kind=AuthorityProtocolOperationKind.RELIABILITY_FACTS,
            body={"transaction_id": transaction_id},
        )
        return tuple(
            StageAttemptTransaction.from_dict(item)
            for item in _body_sequence(result, "transactions")
        )

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        result = self._reliability_list(
            COORDINATOR_LIST_TRANSACTIONS_PATH, run_uri, stage_name
        )
        return tuple(
            StageAttemptTransaction.from_dict(item)
            for item in _body_sequence(result, "transactions")
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> BackendRevision:
        return _required_revision(
            self._call(
                COORDINATOR_WRITE_RETRY_PATH,
                run_uri,
                kind=AuthorityProtocolOperationKind.RELIABILITY_FACTS,
                body={"decision": decision.to_dict()},
            )
        )

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        result = self._reliability_list(
            COORDINATOR_LIST_RETRIES_PATH, run_uri, stage_name
        )
        return tuple(
            RetryDecisionRecord.from_dict(item)
            for item in _body_sequence(result, "decisions")
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> BackendRevision:
        return _required_revision(
            self._call(
                COORDINATOR_WRITE_TIMEOUT_PATH,
                run_uri,
                kind=AuthorityProtocolOperationKind.RELIABILITY_FACTS,
                body={"outcome": outcome.to_dict()},
            )
        )

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        result = self._reliability_list(
            COORDINATOR_LIST_TIMEOUTS_PATH, run_uri, stage_name
        )
        return tuple(
            TimeoutOutcomeRecord.from_dict(item)
            for item in _body_sequence(result, "outcomes")
        )

    def _attempt_pair(
        self, path: str, run_uri: str, assignment_id: str, attempt_id: str
    ) -> None:
        self._call(path, run_uri, body=_attempt_pair_body(assignment_id, attempt_id))

    def _reliability_list(
        self, path: str, run_uri: str, stage_name: str | None
    ) -> AuthorityProtocolResult:
        return self._call(
            path,
            run_uri,
            kind=AuthorityProtocolOperationKind.RELIABILITY_FACTS,
            body={"stage_name": stage_name},
        )

    def _call(
        self,
        path: str,
        run_uri: str,
        *,
        kind: AuthorityProtocolOperationKind = (
            AuthorityProtocolOperationKind.COORDINATOR_EXECUTION
        ),
        stage_name: str | None = None,
        expected_revision: BackendRevision | None = None,
        fencing_token: str | None = None,
        body: Mapping[str, PlainData] | None = None,
    ) -> AuthorityProtocolResult:
        if run_uri != self._run_uri:
            raise AuthorityStoreError("authenticated coordinator authority run conflicts")
        plain_body = {} if body is None else dict(body)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "path": path,
                    "run_uri": run_uri,
                    "stage_name": stage_name,
                    "expected_revision": None
                    if expected_revision is None
                    else expected_revision.to_dict(),
                    "fencing_token": fencing_token,
                    "body": plain_body,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        response = self._client.send(
            path,
            AuthorityProtocolRequest(
                metadata=AuthorityProtocolMetadata(
                    request_id=f"coordinator-{digest[:32]}",
                    operation_kind=kind,
                    service_generation=self._service_generation,
                    workspace_id=self._workspace_id,
                    idempotency_key=digest,
                ),
                run_uri=run_uri,
                stage_name=stage_name,
                expected_revision=expected_revision,
                fencing_token=fencing_token,
                body=plain_body,
            ),
        )
        if not response.accepted:
            rejection = response.rejection
            if rejection is None:
                raise AuthorityStoreError("authority returned an invalid rejection")
            raise AuthenticatedCoordinatorAuthorityError(
                rejection.message,
                category=rejection.category,
                code=rejection.code,
            )
        result = response.result
        if result is None or result.service_generation != self._service_generation:
            raise AuthenticatedCoordinatorAuthorityError(
                "stale service generation",
                category=AuthorityProtocolErrorCategory.STALE_GENERATION,
                code="authority_repository_stale_generation",
            )
        return result


class _MutualTlsJsonTransport:
    def __init__(
        self, config: CoordinatorAuthorityTlsConfig, *, service_id: str
    ) -> None:
        context = ssl.create_default_context(cafile=str(config.ca_path))
        context.load_cert_chain(
            certfile=str(config.certificate_path),
            keyfile=str(config.private_key_path),
        )
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        self._context = context
        self._service_id = _non_empty(service_id, "service_id")

    def __call__(
        self,
        url: str,
        payload: Mapping[str, PlainData],
        timeout_seconds: float | None,
    ) -> Mapping[str, object]:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        req = request.Request(
            url,
            data=encoded,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                COORDINATOR_AUTHORITY_SERVICE_HEADER: self._service_id,
            },
        )
        with request.urlopen(
            req, timeout=timeout_seconds, context=self._context
        ) as response:
            return _json_mapping(response.read())

    def get(self, url: str, timeout_seconds: float | None) -> Mapping[str, object]:
        req = request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                COORDINATOR_AUTHORITY_SERVICE_HEADER: self._service_id,
            },
        )
        with request.urlopen(
            req, timeout=timeout_seconds, context=self._context
        ) as response:
            return _json_mapping(response.read())


def _json_mapping(value: bytes) -> Mapping[str, object]:
    decoded = json.loads(value.decode("utf-8"))
    if not isinstance(decoded, Mapping):
        raise AuthorityStoreError("authority returned a non-mapping JSON response")
    return cast(Mapping[str, object], decoded)


def _attempt_pair_body(assignment_id: str, attempt_id: str) -> dict[str, PlainData]:
    return {
        "assignment_id": _non_empty(assignment_id, "assignment_id"),
        "attempt_id": _non_empty(attempt_id, "attempt_id"),
    }


def _execution_fence_dict(fence: ExecutionFence) -> dict[str, PlainData]:
    if not isinstance(fence, ExecutionFence):
        raise AuthorityStoreError("execution fence is invalid")
    return {
        "assignment_id": fence.assignment_id,
        "attempt_id": fence.attempt_id,
        "fencing_token": fence.fencing_token,
    }


def _execution_fence(value: object) -> ExecutionFence:
    mapping = _mapping(value, "fence")
    if set(mapping) != {"assignment_id", "attempt_id", "fencing_token"}:
        raise AuthorityStoreError("authority returned an invalid execution fence")
    return ExecutionFence(
        _mapping_string(mapping, "assignment_id"),
        _mapping_string(mapping, "attempt_id"),
        _mapping_string(mapping, "fencing_token"),
    )


def _body_required(result: AuthorityProtocolResult, field: str) -> PlainData:
    if field not in result.body:
        raise AuthorityStoreError(f"authority response has no {field}")
    return result.body[field]


def _required_revision(result: AuthorityProtocolResult) -> BackendRevision:
    if result.revision is None:
        raise AuthorityStoreError("authority response has no backend revision")
    return result.revision


def _body_sequence(
    result: AuthorityProtocolResult, field: str
) -> tuple[PlainData, ...]:
    value = _body_required(result, field)
    if not isinstance(value, list):
        raise AuthorityStoreError(f"authority response {field} is invalid")
    return tuple(value)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AuthorityStoreError(f"authority response {field} is invalid")
    return cast(Mapping[str, object], value)


def _mapping_string(value: Mapping[str, object], field: str) -> str:
    return _non_empty(value.get(field), field)


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityStoreError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "AuthenticatedCoordinatorAuthority",
    "AuthenticatedCoordinatorAuthorityError",
    "CoordinatorAuthorityTlsConfig",
    "authenticated_coordinator_authority_factory",
    "embedded_coordinator_authority",
    "initialize_embedded_coordinator_authority",
    "https_coordinator_authority_factory",
]

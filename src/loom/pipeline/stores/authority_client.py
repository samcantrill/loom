"""Repository-free authority HTTP client adapter."""

from __future__ import annotations

import json
import socket
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast
from urllib import error, request

from loom.artifacts import ArtifactRef
from loom.pipeline.cleanup.records import CleanupReport, CleanupResult
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.transition_policy import TransitionIntent
from loom.pipeline.submitted import SubmittedOperationRecord
from loom.serialization import PlainData, ensure_plain_data
from loom.serialization.errors import PlainDataError

from .authority_protocol import (
    AuthorityProtocolError,
    AuthorityProtocolErrorCategory,
    AuthorityProtocolMetadata,
    AuthorityProtocolOperationKind,
    AuthorityProtocolRejection,
    AuthorityProtocolRequest,
    AuthorityProtocolResponse,
    rejected_authority_response,
)
from .coordination import SweepIdentity, TrialReference, WorkspaceIdentity
from .read_models import BackendRevision, LifecycleReason


AUTHORITY_MUTATION_ROUTE_PREFIX = "/v1/authority"
AUTHORITY_MUTATION_RUN_ADMIT_PATH = f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/admit"
AUTHORITY_MUTATION_OPEN_RUN_PATH = f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/open"
AUTHORITY_MUTATION_RUN_TRANSITION_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/transition"
)
AUTHORITY_MUTATION_STAGE_TRANSITION_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/stages/transition"
)
AUTHORITY_MUTATION_ALLOCATE_STAGE_ATTEMPT_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/stages/attempts/allocate"
)
AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/stages/outputs/commit"
)
AUTHORITY_MUTATION_LIST_OUTPUT_COMMITS_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/stages/outputs/list"
)
AUTHORITY_MUTATION_CONTROLLER_LEASE_ACQUIRE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/leases/acquire"
)
AUTHORITY_MUTATION_CONTROLLER_LEASE_RENEW_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/leases/renew"
)
AUTHORITY_MUTATION_CONTROLLER_LEASE_RELEASE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/leases/release"
)
AUTHORITY_MUTATION_CONTROLLER_LEASE_FAIL_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/leases/fail"
)
AUTHORITY_MUTATION_STAGE_LEASE_RENEW_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/stages/leases/renew"
)
AUTHORITY_MUTATION_STAGE_LEASE_RELEASE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/stages/leases/release"
)
AUTHORITY_MUTATION_STAGE_LEASE_FAIL_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/stages/leases/fail"
)
AUTHORITY_MUTATION_SUBMITTED_WRITE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/submitted/write"
)
AUTHORITY_MUTATION_SUBMITTED_READ_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/submitted/read"
)
AUTHORITY_MUTATION_SUBMITTED_LIST_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/submitted/list"
)
AUTHORITY_MUTATION_CLEANUP_REPORT_APPEND_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/cleanup/reports/append"
)
AUTHORITY_MUTATION_CLEANUP_REPORT_LIST_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/cleanup/reports/list"
)
AUTHORITY_MUTATION_CLEANUP_RESULT_APPEND_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/cleanup/results/append"
)
AUTHORITY_MUTATION_CLEANUP_RESULT_LIST_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/runs/cleanup/results/list"
)
AUTHORITY_MUTATION_OFFLINE_IMPORT_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/import/offline-evidence"
)
AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/workspaces/create"
)
AUTHORITY_COORDINATION_SWEEP_CREATE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/sweeps/create"
)
AUTHORITY_COORDINATION_TRIAL_RECORD_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/trials/record"
)
AUTHORITY_COORDINATION_TRIAL_LIST_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/trials/list"
)
AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/trials/leases/acquire"
)
AUTHORITY_COORDINATION_LEASE_RENEW_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/leases/renew"
)
AUTHORITY_COORDINATION_LEASE_RELEASE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/leases/release"
)
AUTHORITY_COORDINATION_LEASE_FAIL_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/leases/fail"
)
AUTHORITY_COORDINATION_COUNTER_LIMIT_SET_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/counters/limit"
)
AUTHORITY_COORDINATION_COUNTER_INCREMENT_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/counters/increment"
)
AUTHORITY_COORDINATION_COUNTER_DECREMENT_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/counters/decrement"
)
AUTHORITY_COORDINATION_COUNTER_READ_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/counters/read"
)
AUTHORITY_COORDINATION_RECOVERY_SCAN_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/recovery/scan"
)
AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/resources/leases/acquire"
)
AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/resources/limit"
)
AUTHORITY_COORDINATION_RESOURCE_LIMIT_READ_PATH = (
    f"{AUTHORITY_MUTATION_ROUTE_PREFIX}/coordination/resources/limit/read"
)

AuthorityHttpTransport = Callable[
    [str, Mapping[str, PlainData], float | None],
    Mapping[str, object],
]


class AuthorityClientError(ValueError):
    """Raised when an authority client cannot be configured."""


@dataclass(frozen=True, slots=True)
class AuthorityClient:
    """Minimal HTTP transport adapter for authority protocol requests."""

    endpoint: str
    timeout_seconds: float | None = 30.0
    transport: AuthorityHttpTransport | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint, str) or not self.endpoint:
            raise AuthorityClientError("endpoint must be a non-empty string")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise AuthorityClientError("timeout_seconds must be positive or None")

    def send(
        self,
        path: str,
        request_payload: AuthorityProtocolRequest,
    ) -> AuthorityProtocolResponse:
        """Send one protocol request and return a structured response."""

        if not path.startswith("/"):
            raise AuthorityClientError("path must start with '/'")
        payload = request_payload.to_dict()
        try:
            raw_response = (self.transport or _stdlib_post_json)(
                _join_url(self.endpoint, path),
                payload,
                self.timeout_seconds,
            )
        except (TimeoutError, socket.timeout) as exc:
            return _transport_rejection(
                request_payload.metadata,
                code="authority_client_timeout",
                message="authority service request timed out",
                exc=exc,
            )
        except (ConnectionError, OSError, error.URLError) as exc:
            return _transport_rejection(
                request_payload.metadata,
                code="authority_client_unavailable",
                message="authority service is unavailable",
                exc=exc,
            )
        except Exception as exc:
            return _transport_rejection(
                request_payload.metadata,
                code="authority_client_transport_error",
                message="authority service transport failed",
                exc=exc,
            )
        try:
            return AuthorityProtocolResponse.from_dict(raw_response)
        except AuthorityProtocolError as exc:
            return rejected_authority_response(
                request_payload.metadata,
                AuthorityProtocolRejection(
                    category=AuthorityProtocolErrorCategory.INTERNAL_ERROR,
                    code="authority_client_invalid_response",
                    message="authority service returned an invalid protocol response",
                    detail={"error": str(exc)},
                ),
            )

    def admit_run(
        self,
        run_uri: str,
        *,
        status: RunStatus = RunStatus.CREATED,
        metadata: Mapping[str, PlainData] | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Admit a run through the authority service."""

        run_metadata = dict(_plain_mapping(metadata or {}, "metadata"))
        body: dict[str, PlainData] = {
            "status": RunStatus(status).value,
            "metadata": run_metadata,
        }
        return self.send(
            AUTHORITY_MUTATION_RUN_ADMIT_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.RUN_LIFECYCLE,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                body=body,
            ),
        )

    def open_run(
        self,
        run_uri: str,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Read a run snapshot through the authority service."""

        return self.send(
            AUTHORITY_MUTATION_OPEN_RUN_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.RUN_SNAPSHOT,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
            ),
        )

    def import_offline_evidence(
        self,
        manifest: Mapping[str, PlainData],
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
        imported_by: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Import a complete v10 offline evidence manifest."""

        manifest_body = dict(_plain_mapping(manifest, "manifest"))
        body: dict[str, PlainData] = {"manifest": manifest_body}
        if imported_by is not None:
            if not isinstance(imported_by, str) or not imported_by:
                raise AuthorityClientError("imported_by must be a non-empty string")
            body["imported_by"] = imported_by
        run_uri = manifest_body.get("run_uri")
        if not isinstance(run_uri, str) or not run_uri:
            raise AuthorityClientError("manifest.run_uri must be a non-empty string")
        return self.send(
            AUTHORITY_MUTATION_OFFLINE_IMPORT_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.OFFLINE_IMPORT,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                body=body,
            ),
        )

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        expected_revision: BackendRevision | None = None,
        intent: TransitionIntent = TransitionIntent.NORMAL,
        reason: LifecycleReason | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Apply a run status transition through the service."""

        return self.send(
            AUTHORITY_MUTATION_RUN_TRANSITION_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.RUN_LIFECYCLE,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                expected_revision=expected_revision,
                body={
                    "from_status": RunStatus(from_status).value,
                    "to_status": RunStatus(to_status).value,
                    "intent": TransitionIntent(intent).value,
                    "reason": None if reason is None else reason.to_dict(),
                },
            ),
        )

    def acquire_controller_lease(
        self,
        run_uri: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Acquire a run controller lease through the service."""

        return self.send(
            AUTHORITY_MUTATION_CONTROLLER_LEASE_ACQUIRE_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.LEASE,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                owner_id=owner_id,
                expected_revision=expected_revision,
                body={"lease_ttl_seconds": lease_ttl_seconds},
            ),
        )

    def renew_controller_lease(
        self,
        run_uri: str,
        *,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Renew a run controller lease through the service."""

        return self._lease_request(
            AUTHORITY_MUTATION_CONTROLLER_LEASE_RENEW_PATH,
            run_uri=run_uri,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            lease_ttl_seconds=lease_ttl_seconds,
            expected_revision=expected_revision,
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def release_controller_lease(
        self,
        run_uri: str,
        *,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        expected_revision: BackendRevision | None = None,
        reason: LifecycleReason | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Release a run controller lease through the service."""

        return self._lease_request(
            AUTHORITY_MUTATION_CONTROLLER_LEASE_RELEASE_PATH,
            run_uri=run_uri,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            reason=reason,
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def fail_controller_lease(
        self,
        run_uri: str,
        *,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Fail a run controller lease through the service."""

        return self._lease_request(
            AUTHORITY_MUTATION_CONTROLLER_LEASE_FAIL_PATH,
            run_uri=run_uri,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            reason=reason,
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

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
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Apply a stage status transition through the service."""

        return self.send(
            AUTHORITY_MUTATION_STAGE_TRANSITION_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.STAGE_LIFECYCLE,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
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
            ),
        )

    def allocate_stage_attempt(
        self,
        run_uri: str,
        stage_name: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int | None = None,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Allocate a stage attempt through the service."""

        return self.send(
            AUTHORITY_MUTATION_ALLOCATE_STAGE_ATTEMPT_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.STAGE_ATTEMPT,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                stage_name=stage_name,
                owner_id=owner_id,
                expected_revision=expected_revision,
                body={"lease_ttl_seconds": lease_ttl_seconds},
            ),
        )

    def renew_stage_lease(
        self,
        run_uri: str,
        *,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Renew a stage lease through the service."""

        return self._lease_request(
            AUTHORITY_MUTATION_STAGE_LEASE_RENEW_PATH,
            run_uri=run_uri,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            lease_ttl_seconds=lease_ttl_seconds,
            expected_revision=expected_revision,
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def release_stage_lease(
        self,
        run_uri: str,
        *,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        expected_revision: BackendRevision | None = None,
        reason: LifecycleReason | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Release a stage lease through the service."""

        return self._lease_request(
            AUTHORITY_MUTATION_STAGE_LEASE_RELEASE_PATH,
            run_uri=run_uri,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            reason=reason,
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def fail_stage_lease(
        self,
        run_uri: str,
        *,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Fail a stage lease through the service."""

        return self._lease_request(
            AUTHORITY_MUTATION_STAGE_LEASE_FAIL_PATH,
            run_uri=run_uri,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            expected_revision=expected_revision,
            reason=reason,
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        owner_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
        supersedes_commit_id: str | None = None,
        expected_revision: BackendRevision | None = None,
        reason: LifecycleReason | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Record a fenced stage output commit through the service."""

        return self.send(
            AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.OUTPUT_COMMIT,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                stage_name=stage_name,
                owner_id=owner_id,
                fencing_token=fencing_token,
                expected_revision=expected_revision,
                body={
                    "attempt_id": attempt_id,
                    "outputs": {
                        name: artifact.to_dict() for name, artifact in outputs.items()
                    },
                    "supersedes_commit_id": supersedes_commit_id,
                    "reason": None if reason is None else reason.to_dict(),
                },
            ),
        )

    def list_output_commits(
        self,
        run_uri: str,
        *,
        stage_name: str | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """List append-only output commit history through the service."""

        return self.send(
            AUTHORITY_MUTATION_LIST_OUTPUT_COMMITS_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.OUTPUT_COMMIT,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                stage_name=stage_name,
            ),
        )

    def write_submitted_operation(
        self,
        run_uri: str,
        record: SubmittedOperationRecord,
        *,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Persist a submitted-operation record through the service."""

        return self.send(
            AUTHORITY_MUTATION_SUBMITTED_WRITE_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.SUBMITTED_OPERATION,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                expected_revision=expected_revision,
                body={"record": record.to_dict()},
            ),
        )

    def read_submitted_operation(
        self,
        run_uri: str,
        submission_id: str,
        *,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Read a submitted-operation record through the service."""

        return self.send(
            AUTHORITY_MUTATION_SUBMITTED_READ_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.SUBMITTED_OPERATION,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                submission_id=submission_id,
                expected_revision=expected_revision,
            ),
        )

    def list_submitted_operations(
        self,
        run_uri: str,
        *,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """List submitted-operation records through the service."""

        return self.send(
            AUTHORITY_MUTATION_SUBMITTED_LIST_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.SUBMITTED_OPERATION,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                expected_revision=expected_revision,
            ),
        )

    def append_cleanup_report(
        self,
        run_uri: str,
        report: CleanupReport,
        *,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Append a cleanup report fact through the service."""

        return self.send(
            AUTHORITY_MUTATION_CLEANUP_REPORT_APPEND_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.CLEANUP_REPORTS,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                expected_revision=expected_revision,
                body={"report": report.to_dict()},
            ),
        )

    def list_cleanup_reports(
        self,
        run_uri: str,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """List cleanup report facts through the service."""

        return self.send(
            AUTHORITY_MUTATION_CLEANUP_REPORT_LIST_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.CLEANUP_REPORTS,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
            ),
        )

    def append_cleanup_result(
        self,
        run_uri: str,
        result: CleanupResult,
        *,
        expected_revision: BackendRevision | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Append a cleanup result fact through the service."""

        return self.send(
            AUTHORITY_MUTATION_CLEANUP_RESULT_APPEND_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.CLEANUP_RESULTS,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                expected_revision=expected_revision,
                body={"result": result.to_dict()},
            ),
        )

    def list_cleanup_results(
        self,
        run_uri: str,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """List cleanup result facts through the service."""

        return self.send(
            AUTHORITY_MUTATION_CLEANUP_RESULT_LIST_PATH,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.CLEANUP_RESULTS,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
            ),
        )

    def create_workspace(
        self,
        identity: WorkspaceIdentity,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Create a workspace identity through the authority service."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH,
            body={"workspace": identity.to_dict()},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=identity.workspace_id,
        )

    def create_sweep(
        self,
        identity: SweepIdentity,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Create a sweep identity through the authority service."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_SWEEP_CREATE_PATH,
            body={"sweep": identity.to_dict()},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=identity.workspace_id,
        )

    def record_trial(
        self,
        trial: TrialReference,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Record a sweep trial reference through the authority service."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_TRIAL_RECORD_PATH,
            body={"trial": trial.to_dict()},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def list_trials(
        self,
        sweep_id: str,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """List trial references for a sweep through the service."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_TRIAL_LIST_PATH,
            body={"sweep_id": sweep_id},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def acquire_trial_lease(
        self,
        sweep_id: str,
        trial_id: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Acquire a trial coordination lease through the service."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH,
            owner_id=owner_id,
            body={
                "sweep_id": sweep_id,
                "trial_id": trial_id,
                "lease_ttl_seconds": lease_ttl_seconds,
            },
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def renew_coordination_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Renew a workspace coordination lease through the service."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_LEASE_RENEW_PATH,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            body={"lease_ttl_seconds": lease_ttl_seconds},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def release_coordination_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Release a workspace coordination lease through the service."""

        body: dict[str, PlainData] = {}
        if reason is not None:
            body["reason"] = reason.to_dict()
        return self._coordination_request(
            AUTHORITY_COORDINATION_LEASE_RELEASE_PATH,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            body=body,
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def fail_coordination_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Fail a workspace coordination lease through the service."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_LEASE_FAIL_PATH,
            lease_id=lease_id,
            owner_id=owner_id,
            fencing_token=fencing_token,
            body={"reason": reason.to_dict()},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def set_counter_limit(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        limit: int | None,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Set a non-resource coordination counter limit."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_COUNTER_LIMIT_SET_PATH,
            body={
                "workspace_id": workspace_id,
                "counter_name": counter_name,
                "limit": limit,
            },
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def increment_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int = 1,
        limit: int | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Increment a non-resource coordination counter."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_COUNTER_INCREMENT_PATH,
            body={
                "workspace_id": workspace_id,
                "counter_name": counter_name,
                "amount": amount,
                "limit": limit,
            },
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def decrement_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int = 1,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Decrement a non-resource coordination counter."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_COUNTER_DECREMENT_PATH,
            body={
                "workspace_id": workspace_id,
                "counter_name": counter_name,
                "amount": amount,
            },
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def read_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Read a non-resource coordination counter."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_COUNTER_READ_PATH,
            body={"workspace_id": workspace_id, "counter_name": counter_name},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def scan_coordination_recovery(
        self,
        workspace_id: str,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Scan workspace coordination recovery records."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_RECOVERY_SCAN_PATH,
            body={"workspace_id": workspace_id},
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def acquire_resource_lease(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        owner_id: str,
        amount: int,
        lease_ttl_seconds: int,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Request a resource lease from authority-backed coordination."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH,
            owner_id=owner_id,
            body={
                "workspace_id": workspace_id,
                "resource_key": resource_key,
                "amount": amount,
                "lease_ttl_seconds": lease_ttl_seconds,
            },
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def set_resource_limit(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        limit: int | None,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Set a resource limit in authority-backed coordination."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH,
            body={
                "workspace_id": workspace_id,
                "resource_key": resource_key,
                "limit": limit,
            },
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def read_resource_limit(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        request_id: str | None = None,
        service_generation: str | None = None,
    ) -> AuthorityProtocolResponse:
        """Read a resource limit from authority-backed coordination."""

        return self._coordination_request(
            AUTHORITY_COORDINATION_RESOURCE_LIMIT_READ_PATH,
            body={
                "workspace_id": workspace_id,
                "resource_key": resource_key,
            },
            request_id=request_id,
            service_generation=service_generation,
            workspace_id=workspace_id,
        )

    def _lease_request(
        self,
        path: str,
        *,
        run_uri: str,
        lease_id: str,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int | None = None,
        expected_revision: BackendRevision | None = None,
        reason: LifecycleReason | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        body: dict[str, PlainData] = {}
        if lease_ttl_seconds is not None:
            body["lease_ttl_seconds"] = lease_ttl_seconds
        if reason is not None:
            body["reason"] = reason.to_dict()
        return self.send(
            path,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.LEASE,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                run_uri=run_uri,
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                expected_revision=expected_revision,
                body=body,
            ),
        )

    def _coordination_request(
        self,
        path: str,
        *,
        body: Mapping[str, PlainData],
        lease_id: str | None = None,
        owner_id: str | None = None,
        fencing_token: str | None = None,
        request_id: str | None = None,
        service_generation: str | None = None,
        workspace_id: str | None = None,
    ) -> AuthorityProtocolResponse:
        return self.send(
            path,
            AuthorityProtocolRequest(
                metadata=_metadata(
                    AuthorityProtocolOperationKind.WORKSPACE_COORDINATION,
                    request_id=request_id,
                    service_generation=service_generation,
                    workspace_id=workspace_id,
                ),
                lease_id=lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                body=body,
            ),
        )


def _metadata(
    operation_kind: AuthorityProtocolOperationKind,
    *,
    request_id: str | None,
    idempotency_key: str | None = None,
    service_generation: str | None,
    workspace_id: str | None,
) -> AuthorityProtocolMetadata:
    return AuthorityProtocolMetadata(
        request_id=request_id or f"authority-client-{uuid.uuid4().hex}",
        operation_kind=operation_kind,
        service_generation=service_generation,
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
    )


def _stdlib_post_json(
    url: str,
    payload: Mapping[str, PlainData],
    timeout_seconds: float | None,
) -> Mapping[str, object]:
    data = json.dumps(payload).encode("utf-8")
    request_obj = request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(request_obj, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, Mapping):
        raise AuthorityClientError("authority response must be a mapping")
    return cast(Mapping[str, object], parsed)


def _transport_rejection(
    metadata: AuthorityProtocolMetadata,
    *,
    code: str,
    message: str,
    exc: BaseException,
) -> AuthorityProtocolResponse:
    return rejected_authority_response(
        metadata,
        AuthorityProtocolRejection(
            category=AuthorityProtocolErrorCategory.UNAVAILABLE_SERVICE,
            code=code,
            message=message,
            detail={"error_type": type(exc).__name__},
        ),
    )


def _join_url(endpoint: str, path: str) -> str:
    return f"{endpoint.rstrip('/')}{path}"


def _plain_mapping(value: object, field: str) -> Mapping[str, PlainData]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise AuthorityClientError(f"{field} must be a mapping")
    try:
        return cast(Mapping[str, PlainData], ensure_plain_data(dict(value)))
    except (PlainDataError, TypeError) as exc:
        raise AuthorityClientError(f"{field} must contain plain data") from exc


__all__ = [
    "AUTHORITY_MUTATION_ROUTE_PREFIX",
    "AUTHORITY_MUTATION_RUN_ADMIT_PATH",
    "AUTHORITY_MUTATION_OPEN_RUN_PATH",
    "AUTHORITY_MUTATION_RUN_TRANSITION_PATH",
    "AUTHORITY_MUTATION_STAGE_TRANSITION_PATH",
    "AUTHORITY_MUTATION_ALLOCATE_STAGE_ATTEMPT_PATH",
    "AUTHORITY_MUTATION_RECORD_OUTPUT_COMMIT_PATH",
    "AUTHORITY_MUTATION_LIST_OUTPUT_COMMITS_PATH",
    "AUTHORITY_MUTATION_CONTROLLER_LEASE_ACQUIRE_PATH",
    "AUTHORITY_MUTATION_CONTROLLER_LEASE_RENEW_PATH",
    "AUTHORITY_MUTATION_CONTROLLER_LEASE_RELEASE_PATH",
    "AUTHORITY_MUTATION_CONTROLLER_LEASE_FAIL_PATH",
    "AUTHORITY_MUTATION_STAGE_LEASE_RENEW_PATH",
    "AUTHORITY_MUTATION_STAGE_LEASE_RELEASE_PATH",
    "AUTHORITY_MUTATION_STAGE_LEASE_FAIL_PATH",
    "AUTHORITY_MUTATION_SUBMITTED_WRITE_PATH",
    "AUTHORITY_MUTATION_SUBMITTED_READ_PATH",
    "AUTHORITY_MUTATION_SUBMITTED_LIST_PATH",
    "AUTHORITY_MUTATION_CLEANUP_REPORT_APPEND_PATH",
    "AUTHORITY_MUTATION_CLEANUP_REPORT_LIST_PATH",
    "AUTHORITY_MUTATION_CLEANUP_RESULT_APPEND_PATH",
    "AUTHORITY_MUTATION_CLEANUP_RESULT_LIST_PATH",
    "AUTHORITY_MUTATION_OFFLINE_IMPORT_PATH",
    "AUTHORITY_COORDINATION_WORKSPACE_CREATE_PATH",
    "AUTHORITY_COORDINATION_SWEEP_CREATE_PATH",
    "AUTHORITY_COORDINATION_TRIAL_RECORD_PATH",
    "AUTHORITY_COORDINATION_TRIAL_LIST_PATH",
    "AUTHORITY_COORDINATION_TRIAL_LEASE_ACQUIRE_PATH",
    "AUTHORITY_COORDINATION_LEASE_RENEW_PATH",
    "AUTHORITY_COORDINATION_LEASE_RELEASE_PATH",
    "AUTHORITY_COORDINATION_LEASE_FAIL_PATH",
    "AUTHORITY_COORDINATION_COUNTER_LIMIT_SET_PATH",
    "AUTHORITY_COORDINATION_COUNTER_INCREMENT_PATH",
    "AUTHORITY_COORDINATION_COUNTER_DECREMENT_PATH",
    "AUTHORITY_COORDINATION_COUNTER_READ_PATH",
    "AUTHORITY_COORDINATION_RECOVERY_SCAN_PATH",
    "AUTHORITY_COORDINATION_RESOURCE_LEASE_ACQUIRE_PATH",
    "AUTHORITY_COORDINATION_RESOURCE_LIMIT_READ_PATH",
    "AUTHORITY_COORDINATION_RESOURCE_LIMIT_SET_PATH",
    "AuthorityClient",
    "AuthorityClientError",
    "AuthorityHttpTransport",
]

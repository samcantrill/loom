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
from loom.pipeline.status import RunStatus, StageStatus
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

    def transition_run(
        self,
        run_uri: str,
        *,
        from_status: RunStatus,
        to_status: RunStatus,
        expected_revision: BackendRevision | None = None,
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
                    "reason": None if reason is None else reason.to_dict(),
                },
            ),
        )

    def transition_stage(
        self,
        run_uri: str,
        stage_name: str,
        *,
        from_status: StageStatus | None,
        to_status: StageStatus,
        expected_revision: BackendRevision | None = None,
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

    def record_output_commit(
        self,
        run_uri: str,
        stage_name: str,
        *,
        attempt_id: str,
        owner_id: str,
        fencing_token: str,
        outputs: Mapping[str, ArtifactRef],
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
                    "reason": None if reason is None else reason.to_dict(),
                },
            ),
        )


def _metadata(
    operation_kind: AuthorityProtocolOperationKind,
    *,
    request_id: str | None,
    service_generation: str | None,
    workspace_id: str | None,
) -> AuthorityProtocolMetadata:
    return AuthorityProtocolMetadata(
        request_id=request_id or f"authority-client-{uuid.uuid4().hex}",
        operation_kind=operation_kind,
        service_generation=service_generation,
        workspace_id=workspace_id,
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
    "AuthorityClient",
    "AuthorityClientError",
    "AuthorityHttpTransport",
]

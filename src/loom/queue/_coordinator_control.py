"""Native coordinator control values, codecs and authenticated dispatch.

Both transports and both Python adapters share this application boundary. It
does not import diagnostics, the integration facade, or worker process owners.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import math
from typing import Any, cast

from loom.serialization import PlainData, thaw_plain_data

from .errors import (
    QueueConflictError,
    QueueError,
    QueueServiceError,
    QueueStorageError,
    QueueValidationError,
)
from .local_daemon import (
    AdmissionNotFoundError,
    AdmissionPage,
    AdmissionWaitKind,
    AdmissionWaitResult,
    AgentPage,
    AgentProjection,
    DaemonStatus,
    LocalDaemon,
    LocalDaemonAdmission,
    LocalDaemonAdmissionDetail,
    LocalDaemonAdmissionRequest,
    LocalDaemonOperation,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    OperationWaitResult,
)
from .preparation import PrepareRunRequest


CONTROL_CAPABILITY = "daemon-control-v1"
MAX_RESPONSE_BYTES = 1_048_576
MAX_OBSERVATION_SECONDS = 25.0
CONTROL_OPERATIONS = frozenset(
    {
        "handshake",
        "status",
        "admissions",
        "admission",
        "admission_for_queue_item",
        "agents",
        "agent",
        "inspect_run",
        "operation",
        "wait_operation",
        "prepare_run",
        "cancel_preparation",
        "submit",
        "wait_admission",
        "cancel",
    }
)
WAIT_OPERATIONS = frozenset({"wait_operation", "wait_admission"})
MUTATION_OPERATIONS = frozenset({"submit", "cancel", "prepare_run", "cancel_preparation"})


class CoordinatorClientError(QueueServiceError):
    """Classified control failure, preserving request IDs and commitment evidence."""

    def __init__(
        self,
        code: str,
        *,
        boundary: str,
        operation: str,
        ids: Mapping[str, PlainData] | None = None,
        evidence_refs: tuple[PlainData, ...] = (),
        mutation_outcome: str | None = None,
        message: str | None = None,
    ) -> None:
        super().__init__(message or f"coordinator {operation} failed: {code}")
        self.code = code
        self.boundary = boundary
        self.operation = operation
        self.ids = dict(ids or {})
        self.evidence_refs = tuple(evidence_refs)
        self.mutation_outcome = mutation_outcome

    def to_dict(self) -> dict[str, PlainData]:
        """Return the additive native schema-1 error detail."""
        return {
            "schema_version": 1,
            "code": self.code,
            "boundary": self.boundary,
            "operation": self.operation,
            "ids": dict(self.ids),
            "evidence_refs": list(self.evidence_refs),
            "mutation_outcome": self.mutation_outcome,
        }


def request_ids(payload: Mapping[str, object]) -> dict[str, PlainData]:
    ids: dict[str, PlainData] = {}
    for key in (
        "admission_id",
        "queue_item_id",
        "operation_id",
        "run_uri",
        "expected_coordinator_id",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            ids[key] = value
    request = payload.get("request")
    if isinstance(request, Mapping):
        ids.update(request_ids(request))
    return ids


def control_error(
    code: str,
    operation: str,
    payload: Mapping[str, object],
    *,
    boundary: str = "client_protocol",
    dispatched: bool = False,
    applied: bool = False,
    ids: Mapping[str, PlainData] | None = None,
) -> CoordinatorClientError:
    identity = request_ids(payload)
    identity.update(ids or {})
    outcome = None
    if operation in MUTATION_OPERATIONS:
        outcome = "applied" if applied else "unknown" if dispatched else "not_applied"
    return CoordinatorClientError(
        code,
        boundary=boundary,
        operation=operation,
        ids=identity,
        mutation_outcome=outcome,
    )


def error_envelope(error: CoordinatorClientError) -> dict[str, PlainData]:
    return {"ok": False, "error": str(error), "error_detail": error.to_dict()}


@dataclass(frozen=True, slots=True)
class CoordinatorConnectionDescription:
    """Observed native connection identity and enabled safe aliases."""

    protocol_version: str
    transport: str
    coordinator_id: str
    coordinator_epoch: str
    capabilities: tuple[str, ...]
    source_modes: tuple[str, ...]
    preparation_profiles: tuple[str, ...]
    source_roots: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> CoordinatorConnectionDescription:
        strings = (
            "protocol_version",
            "transport",
            "coordinator_id",
            "coordinator_epoch",
        )
        lists = ("capabilities", "source_modes", "preparation_profiles", "source_roots")
        if any(
            not isinstance(value.get(key), str) or not value[key] for key in strings
        ):
            raise ValueError("connection identity is invalid")
        sequences: list[tuple[str, ...]] = []
        for key in lists:
            items = value.get(key)
            if not isinstance(items, list) or any(
                not isinstance(item, str) for item in items
            ):
                raise ValueError("connection capabilities are invalid")
            sequences.append(tuple(items))
        return cls(
            cast(str, value["protocol_version"]),
            cast(str, value["transport"]),
            cast(str, value["coordinator_id"]),
            cast(str, value["coordinator_epoch"]),
            sequences[0],
            sequences[1],
            sequences[2],
            sequences[3],
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "protocol_version": self.protocol_version,
            "transport": self.transport,
            "coordinator_id": self.coordinator_id,
            "coordinator_epoch": self.coordinator_epoch,
            "capabilities": list(self.capabilities),
            "source_modes": list(self.source_modes),
            "preparation_profiles": list(self.preparation_profiles),
            "source_roots": list(self.source_roots),
        }


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def decode_wire(raw: bytes) -> Mapping[str, object]:
    """Decode bounded native control JSON; model owners validate its subtrees.

    Control responses can contain the native nested failure union. They must
    not pass through the shallow worker request decoder or lose that evidence.
    """
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("control message is too large")
    value = json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )
    if not isinstance(value, Mapping):
        raise ValueError("control message is not an object")
    return value


def encode_wire(value: Mapping[str, PlainData]) -> bytes:
    return json.dumps(
        thaw_plain_data(value, path="coordinator control"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def decode_envelope(
    response: Mapping[str, object], operation: str, request: Mapping[str, object]
) -> Mapping[str, object]:
    invalid = control_error("invalid_response", operation, request, dispatched=True)
    if response.get("ok") is True:
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise invalid
        return result
    detail = response.get("error_detail")
    if isinstance(detail, Mapping):
        fields = {
            "schema_version",
            "code",
            "boundary",
            "operation",
            "ids",
            "evidence_refs",
            "mutation_outcome",
        }
        if (
            set(detail) != fields
            or type(detail.get("schema_version")) is not int
            or detail["schema_version"] != 1
        ):
            raise invalid
        if any(
            not isinstance(detail.get(key), str) or not detail[key]
            for key in ("code", "boundary", "operation")
        ):
            raise invalid
        ids, refs, outcome = (
            detail["ids"],
            detail["evidence_refs"],
            detail["mutation_outcome"],
        )
        if not isinstance(ids, Mapping) or not isinstance(refs, list):
            raise invalid
        if outcome not in (None, "not_applied", "applied", "unknown"):
            raise invalid
        if (operation in MUTATION_OPERATIONS) != (outcome is not None):
            raise invalid
        raise CoordinatorClientError(
            cast(str, detail["code"]),
            boundary=cast(str, detail["boundary"]),
            operation=operation,
            ids={**cast(Mapping[str, PlainData], ids), **request_ids(request)},
            evidence_refs=tuple(cast(list[PlainData], refs)),
            mutation_outcome=cast(str | None, outcome),
            message=cast(str, response["error"])
            if isinstance(response.get("error"), str)
            else None,
        )
    # Saturation can be refused before a Unix server has read its envelope.
    # These established codes prove non-dispatch. A bare HTTP 403 proves no
    # such outcome and is deliberately not guessed to mean unauthorized.
    if response.get("error") in (
        "local_daemon_worker_capacity_exhausted",
        "local_daemon_wait_capacity_exhausted",
    ):
        raise control_error(
            "capacity_exhausted", operation, request, boundary="coordinator"
        )
    if operation == "handshake" and response.get("ok") is False:
        raise control_error("unsupported", operation, request)
    raise invalid


def decode_result(operation: str, value: Mapping[str, object]) -> Any:
    """Decode each native result at one owner shared by both Python adapters."""
    if operation == "handshake":
        return CoordinatorConnectionDescription.from_dict(value)
    if operation == "status":
        return DaemonStatus.from_dict(value)
    if operation in {"submit", "cancel", "admission_for_queue_item"}:
        return LocalDaemonAdmission.from_dict(value)
    if operation == "admission":
        return LocalDaemonAdmissionDetail.from_dict(value)
    if operation == "admissions":
        rows, cursor = value.get("admissions"), value.get("next_cursor")
        if not isinstance(rows, list) or any(
            not isinstance(item, Mapping) for item in rows
        ):
            raise ValueError("admission page is invalid")
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError("admission cursor is invalid")
        return AdmissionPage(
            tuple(LocalDaemonAdmission.from_dict(item) for item in rows), cursor
        )
    if operation == "agents":
        return AgentPage.from_dict(value)
    if operation == "agent":
        return AgentProjection.from_dict(value)
    if operation in {"operation", "prepare_run", "cancel_preparation"}:
        return LocalDaemonOperation.from_dict(value)
    if operation == "wait_operation":
        return OperationWaitResult.from_dict(value)
    if operation == "wait_admission":
        kind, admission, revision = (
            value.get("kind"),
            value.get("admission"),
            value.get("revision"),
        )
        if (
            not isinstance(kind, str)
            or not isinstance(admission, Mapping)
            or type(revision) is not int
        ):
            raise ValueError("admission wait is invalid")
        return AdmissionWaitResult(
            AdmissionWaitKind(kind), LocalDaemonAdmission.from_dict(admission), revision
        )
    if operation == "inspect_run":
        return value  # The diagnostic union decoder belongs above queue.
    raise ValueError("control result operation is unsupported")


def optional_id(value: object) -> str | None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError("expected coordinator ID must be a nonempty string")
    return cast(str | None, value)


def observation_timeout(value: object, *, legacy: bool = False) -> float | None:
    if legacy and value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError("observation timeout is invalid")
    if not legacy and value > MAX_OBSERVATION_SECONDS:
        raise ValueError("observation timeout exceeds 25 seconds")
    return float(value)


def validate_request(
    operation: str, payload: Mapping[str, object], *, legacy: bool = False
) -> dict[str, object]:
    """Validate the finite public request before invoking application owners."""
    fields = {
        "handshake": set(),
        "status": set(),
        "submit": {"request"},
        "cancel": {"queue_item_id"},
        "prepare_run": {"request"},
        "cancel_preparation": {"operation_id"},
        "admissions": {"limit", "cursor"},
        "agents": {"limit", "cursor"},
        "admission": {"admission_id"},
        "admission_for_queue_item": {"queue_item_id"},
        "agent": {"agent_id"},
        "operation": {"operation_id"},
        "inspect_run": {"run_uri"},
        "wait_operation": {"operation_id", "timeout"},
        "wait_admission": {"admission_id", "expected_revision", "timeout"},
    }
    if operation not in fields:
        raise control_error("unsupported", operation, payload)
    value = dict(payload)
    value.pop("expected_coordinator_id", None)
    if legacy and operation in {"admissions", "agents"}:
        value.setdefault("limit", 100)
        value.setdefault("cursor", None)
    if legacy and operation in WAIT_OPERATIONS:
        value.setdefault("timeout", None)
    if set(value) != fields[operation]:
        raise ValueError("control request fields are invalid")
    for key in ("admission_id", "queue_item_id", "agent_id", "operation_id", "run_uri"):
        if key in value and (not isinstance(value[key], str) or not value[key]):
            raise ValueError(f"control {key} is invalid")
    if "limit" in value:
        limit, cursor = value["limit"], value["cursor"]
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("page limit must be an integer from 1 to 100")
        if cursor is not None and not isinstance(cursor, str):
            raise ValueError("page cursor is invalid")
    if "expected_revision" in value:
        revision = value["expected_revision"]
        if type(revision) is not int or revision < 0:
            raise ValueError("admission revision is invalid")
    if "timeout" in value:
        value["timeout"] = observation_timeout(value["timeout"], legacy=legacy)
    if operation == "submit":
        request = value["request"]
        if not isinstance(request, Mapping):
            raise ValueError("admission request must be an object")
        value["request"] = LocalDaemonAdmissionRequest.from_dict(request)
    if operation == "prepare_run":
        request = value["request"]
        if not isinstance(request, Mapping):
            raise ValueError("prepare request must be an object")
        value["request"] = PrepareRunRequest.from_dict(request)
    return value


def dispatch_control(
    daemon: LocalDaemon,
    principal: LocalDaemonPrincipal,
    operation: str,
    payload: Mapping[str, object],
    *,
    transport: str,
    wait_slice: float,
    inspect_run: Callable[[str], Mapping[str, PlainData]] | None,
    legacy: bool = False,
) -> Mapping[str, PlainData]:
    """Authorize, guard and dispatch once, preserving mutation commitment truth."""
    dispatched = applied = False
    try:
        try:
            if not (legacy and transport == "unix" and operation == "inspect_run"):
                daemon._require_view_role(principal, LocalDaemonRole.CLIENT)
        except QueueError as exc:
            raise control_error(
                "unauthorized", operation, payload, boundary="authentication"
            ) from exc
        try:
            expected = optional_id(payload.get("expected_coordinator_id"))
        except ValueError as exc:
            raise control_error(
                "invalid_request", operation, payload, boundary="coordinator"
            ) from exc
        observed = daemon._require_started() if expected is not None else None
        if expected is not None and observed != expected:
            raise control_error(
                "conflict",
                operation,
                payload,
                boundary="coordinator",
                ids={
                    "expected_coordinator_id": expected,
                    "observed_coordinator_id": observed,
                },
            )
        try:
            value = validate_request(operation, payload, legacy=legacy)
        except (ValueError, TypeError, QueueError) as exc:
            if isinstance(exc, CoordinatorClientError):
                raise
            raise control_error(
                "invalid_request", operation, payload, boundary="coordinator"
            ) from exc
        view = daemon.client_view(principal)
        result: Any
        if operation == "handshake":
            status = view.status()
            preparation = daemon.config.preparation_policy
            result = CoordinatorConnectionDescription(
                "1",
                transport,
                status.coordinator_id,
                status.coordinator_epoch,
                (CONTROL_CAPABILITY, *( ("agent-preparation-v1",) if daemon.config.preparation_enabled else () )),
                (() if preparation is None else preparation.effective_modes),
                (() if preparation is None else preparation.effective_profiles),
                (() if preparation is None else preparation.effective_roots),
            )
        elif operation == "status":
            result = view.status()
        elif operation == "admissions":
            result = view.admissions(
                limit=cast(int, value["limit"]),
                cursor=cast(str | None, value["cursor"]),
            )
        elif operation == "admission":
            result = view.admission(cast(str, value["admission_id"]))
        elif operation == "admission_for_queue_item":
            result = view.admission_for_queue_item(cast(str, value["queue_item_id"]))
        elif operation == "agents":
            result = view.agents(
                limit=cast(int, value["limit"]),
                cursor=cast(str | None, value["cursor"]),
            )
        elif operation == "agent":
            result = view.agent(cast(str, value["agent_id"]))
        elif operation == "operation":
            result = view.operation(cast(str, value["operation_id"]))
        elif operation in WAIT_OPERATIONS:
            duration = cast(float | None, value["timeout"])
            timeout = wait_slice if duration is None else min(wait_slice, duration)
            if operation == "wait_operation":
                result = view.wait_operation(
                    cast(str, value["operation_id"]), timeout=timeout
                )
            else:
                result = view.wait_admission(
                    cast(str, value["admission_id"]),
                    expected_revision=cast(int, value["expected_revision"]),
                    timeout=timeout,
                )
        elif operation == "inspect_run":
            if inspect_run is None:
                raise control_error(
                    "unsupported", operation, payload, boundary="coordinator"
                )
            run_uri = cast(str, value["run_uri"])
            if not legacy or transport == "https":
                daemon.admission_for_run_uri(run_uri)
            result = inspect_run(run_uri)
        elif operation == "submit":
            dispatched = True
            result = view.submit(cast(LocalDaemonAdmissionRequest, value["request"]))
            applied = True
        elif operation == "prepare_run":
            request = cast(PrepareRunRequest, value["request"])
            if not daemon.config.preparation_enabled or request.source.mode != "shared":
                raise control_error("unsupported", operation, payload, boundary="coordinator")
            dispatched = True
            result = view.prepare_run(request)
            applied = True
        elif operation == "cancel_preparation":
            dispatched = True
            result = view.cancel_preparation(cast(str, value["operation_id"]))
            applied = True
        elif operation == "cancel":
            dispatched = True
            result = view.cancel(cast(str, value["queue_item_id"]))
            applied = True
        else:
            raise control_error(
                "unsupported", operation, payload, boundary="coordinator"
            )
        plain = dict(result) if isinstance(result, Mapping) else result.to_dict()
        if len(encode_wire({"ok": True, "result": plain})) > MAX_RESPONSE_BYTES:
            raise control_error(
                "result_too_large",
                operation,
                payload,
                boundary="coordinator",
                dispatched=dispatched,
                applied=applied,
            )
        return cast(Mapping[str, PlainData], plain)
    except CoordinatorClientError:
        raise
    except Exception as exc:
        if legacy:
            raise
        if isinstance(exc, AdmissionNotFoundError) or (
            isinstance(exc, QueueServiceError)
            and str(exc)
            in {
                "managed agent was not found",
                "managed operation was not found",
            }
        ):
            code = "not_found"
        elif isinstance(exc, QueueConflictError):
            code = "conflict"
        elif isinstance(exc, (QueueValidationError, ValueError, TypeError)):
            code = "invalid_request" if not dispatched else "internal_error"
        elif isinstance(exc, (QueueStorageError, QueueServiceError, OSError)):
            code = "unavailable"
        else:
            code = "internal_error"
        raise control_error(
            code,
            operation,
            payload,
            boundary="coordinator",
            dispatched=dispatched,
            applied=applied,
        ) from exc

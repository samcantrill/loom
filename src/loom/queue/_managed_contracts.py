"""Shared resident assignment, provider and journal contracts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from loom._sqlite_policy import SQLitePolicy, connect_existing, initialize_database
from loom.pipeline.execution.models import (
    StageWorkerResult,
)
from loom.pipeline.stores import (
    OutputCommit,
)
from loom.pipeline.stores.authority import (
    ExecutionFence,
)
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data
from loom.timestamps import parse_timestamp

from ._agent_progress import _cooperative, _Progress, _steps


class ManagedLocalError(ValueError):
    """An assignment, journal, or provider invariant was violated."""

    __module__ = "loom.queue._managed_local"  # Retained failure type in worker records.


class ManagedOfferUnavailable(ManagedLocalError):
    """The selected offer failed a definitive check before acquiring a claim."""


GPU_DECLINE_REASONS = frozenset(
    {
        "external_process_detected",
        "observation_unavailable",
        "observation_stale",
        "device_missing",
        "loom_claimed",
    }
)


def _read_decline_reason(
    conn: sqlite3.Connection, table: str, assignment_id: str
) -> str | None:
    row = conn.execute(
        f"SELECT payload_json FROM {table} WHERE assignment_id = ? AND event_id = ?",
        (assignment_id, f"{assignment_id}:definitive_decline"),
    ).fetchone()
    return _decode_decline_reason(row[0]) if row is not None else None


def _decode_decline_reason(payload: object) -> str:
    reason = json.loads(str(payload)).get("reason_code")
    if not isinstance(reason, str) or reason not in GPU_DECLINE_REASONS:
        raise ManagedLocalError("assignment decline reason is invalid")
    return reason


class ManagedProcessStartError(ManagedLocalError):
    """The launcher proved that no managed root was created or can later run."""

    __module__ = "loom.queue._managed_local"  # Retained failure type in worker records.


class _ManagedApplicationSuspended(ManagedLocalError):
    """The application stopped while its independent supervisor kept ownership."""

    __module__ = "loom.queue._managed_local"  # Retained failure type in worker records.


class ClaimOutcome(StrEnum):
    PREPARED = "prepared"
    DECLINED = "declined"
    ACTIVE = "active"
    RELEASED = "released"
    INDETERMINATE = "indeterminate"


class AssignmentState(StrEnum):
    REQUEST_DURABLE = "request_durable"
    DECLINED = "declined"
    PREPARE_UNKNOWN = "prepare_unknown"
    PREPARED = "prepared"
    ACCEPTED = "accepted"
    GRANTED = "granted"
    ACTIVE = "active"
    ACTIVATION_UNKNOWN = "activation_unknown"
    START_INTENT = "start_intent"
    PROCESS_STARTED = "process_started"
    START_FAILED = "start_failed"
    START_UNKNOWN = "start_unknown"
    RESULT_DURABLE = "result_durable"
    TERMINAL_ACKNOWLEDGED = "terminal_acknowledged"
    PROVIDERS_RELEASED = "providers_released"
    RELEASED = "released"


_AGENT_SUCCESS_ORDER = (
    AssignmentState.REQUEST_DURABLE,
    AssignmentState.PREPARED,
    AssignmentState.ACCEPTED,
    AssignmentState.GRANTED,
    AssignmentState.ACTIVE,
    AssignmentState.START_INTENT,
    AssignmentState.PROCESS_STARTED,
    AssignmentState.RESULT_DURABLE,
    AssignmentState.TERMINAL_ACKNOWLEDGED,
    AssignmentState.PROVIDERS_RELEASED,
    AssignmentState.RELEASED,
)


_COORDINATOR_SUCCESS_ORDER = (
    "reserved",
    "bound",
    "accepted",
    "granted",
    "running",
    "terminal",
    "logical_released",
    "released",
)


@dataclass(frozen=True, slots=True)
class ManagedAssignment:
    """The closed managed-agent target and the exact Phase 1 attempt binding."""

    assignment_id: str
    run_uri: str
    stage_work_id: str
    stage_name: str
    attempt: int
    attempt_id: str
    agent_id: str
    session_id: str
    offer_id: str
    claim_id: str

    def __post_init__(self) -> None:
        for name in (
            "assignment_id",
            "run_uri",
            "stage_work_id",
            "stage_name",
            "attempt_id",
            "agent_id",
            "session_id",
            "offer_id",
            "claim_id",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ManagedLocalError(f"{name} must be a non-empty string")
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 1
        ):
            raise ManagedLocalError("attempt must be a positive integer")


@dataclass(frozen=True, slots=True)
class ProviderReleaseEvidence:
    """Agent-journal proof that one exact composite claim is fully released."""

    assignment: ManagedAssignment
    execution_fence: str
    availability_revision: str

    def __post_init__(self) -> None:
        if not self.execution_fence:
            raise ManagedLocalError("provider release fence is required")
        if not self.availability_revision:
            raise ManagedLocalError("provider release availability is required")


@dataclass(frozen=True, slots=True)
class ManagedExecutionReceipt:
    assignment: ManagedAssignment
    fence: ExecutionFence
    worker_result: StageWorkerResult
    output_commit: OutputCommit | None
    availability_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, ManagedAssignment):
            raise ManagedLocalError("receipt assignment is invalid")
        if not isinstance(self.fence, ExecutionFence):
            raise ManagedLocalError("receipt fence is invalid")
        if not isinstance(self.worker_result, StageWorkerResult):
            raise ManagedLocalError("receipt worker result is invalid")
        if self.output_commit is not None and not isinstance(
            self.output_commit, OutputCommit
        ):
            raise ManagedLocalError("receipt output commit is invalid")
        if (
            not isinstance(self.availability_revision, str)
            or not self.availability_revision
        ):
            raise ManagedLocalError("receipt availability revision is required")


@dataclass(frozen=True, slots=True)
class _ProbeClaimOwner:
    """Diagnostic ownership keys for the existing provider command contract.

    A probe has no run, attempt, coordinator grant, or worker result. Providers
    address its local ownership scope through their existing command keys.
    """

    probe_id: str
    agent_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.probe_id, str) or not self.probe_id.startswith(
            "diagnostic-probe:"
        ):
            raise ManagedLocalError("diagnostic probe identity is invalid")
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise ManagedLocalError("diagnostic probe agent is invalid")

    @property
    def assignment_id(self) -> str:
        return self.probe_id

    @property
    def session_id(self) -> str:
        return self.probe_id

    @property
    def claim_id(self) -> str:
        return self.probe_id


@dataclass(frozen=True, slots=True)
class ClaimCommand:
    """Idempotent provider command; its operation ID is stable across replay."""

    assignment: ManagedAssignment | _ProbeClaimOwner
    operation_id: str
    claim: ResourceClaim
    provider_descriptor: SchedulingComponentDescriptor

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, ManagedAssignment | _ProbeClaimOwner):
            raise ManagedLocalError("command assignment is invalid")
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ManagedLocalError("operation_id must be a non-empty string")
        if not isinstance(self.claim, ResourceClaim):
            raise ManagedLocalError("claim must be a ResourceClaim")
        if not isinstance(self.provider_descriptor, SchedulingComponentDescriptor):
            raise ManagedLocalError(
                "provider_descriptor must be a scheduling component descriptor"
            )
        if self.provider_descriptor.kind != self.claim.resource_kind:
            raise ManagedLocalError(
                "provider descriptor kind must match the claim resource kind"
            )


@dataclass(frozen=True, slots=True)
class ClaimResult:
    outcome: ClaimOutcome
    operation_id: str
    claim_fingerprint: str
    detail: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", ClaimOutcome(self.outcome))
        for name in ("operation_id", "claim_fingerprint"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ManagedLocalError(f"{name} must be a non-empty string")
        if self.detail is not None and not isinstance(self.detail, str):
            raise ManagedLocalError("detail must be a string when set")


@dataclass(frozen=True, slots=True)
class ObserveRequest:
    agent_id: str
    session_id: str
    operation_id: str

    def __post_init__(self) -> None:
        for name in ("agent_id", "session_id", "operation_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ManagedLocalError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityStatus:
    """Safe decision for one configured resource capacity key.

    ``observed_at`` is display metadata only.  It is intentionally absent from
    :meth:`decision_dict` so a timestamp-only probe cannot change scheduling
    identity.
    """

    resource_kind: str
    local_capacity_key: str
    available: bool
    reason_code: str
    observed_at: str | None

    def __post_init__(self) -> None:
        for name in ("resource_kind", "local_capacity_key", "reason_code"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ManagedLocalError(
                    f"resource status {name} must be a non-empty string"
                )
        if not isinstance(self.available, bool):
            raise ManagedLocalError("resource status availability must be boolean")
        if self.observed_at is not None:
            if not isinstance(self.observed_at, str):
                raise ManagedLocalError("resource status observation time is invalid")
            try:
                parse_timestamp(self.observed_at)
            except ValueError as exc:
                raise ManagedLocalError(
                    "resource status observation time is invalid"
                ) from exc

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "resource_kind": self.resource_kind,
            "local_capacity_key": self.local_capacity_key,
            "available": self.available,
            "reason_code": self.reason_code,
            "observed_at": self.observed_at,
        }

    def decision_dict(self) -> dict[str, PlainData]:
        return {
            "resource_kind": self.resource_kind,
            "local_capacity_key": self.local_capacity_key,
            "available": self.available,
            "reason_code": self.reason_code,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ResourceAvailabilityStatus":
        expected = {
            "resource_kind",
            "local_capacity_key",
            "available",
            "reason_code",
            "observed_at",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ManagedLocalError("resource status fields are invalid")
        return cls(
            cast(str, value["resource_kind"]),
            cast(str, value["local_capacity_key"]),
            cast(bool, value["available"]),
            cast(str, value["reason_code"]),
            cast(str | None, value["observed_at"]),
        )


@dataclass(frozen=True, slots=True)
class ObserveResult:
    operation_id: str
    availability_revision: str
    atoms: tuple[CapacityAtom, ...]
    live_claim_ids: tuple[str, ...]
    resource_status: tuple[ResourceAvailabilityStatus, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise ManagedLocalError("operation_id must be a non-empty string")
        if (
            not isinstance(self.availability_revision, str)
            or not self.availability_revision
        ):
            raise ManagedLocalError("availability_revision must be a non-empty string")
        if any(not isinstance(atom, CapacityAtom) for atom in self.atoms):
            raise ManagedLocalError("observe atoms must be CapacityAtom values")
        if any(
            not isinstance(value, str) or not value for value in self.live_claim_ids
        ):
            raise ManagedLocalError("live claim IDs must be non-empty strings")
        if len(set(self.live_claim_ids)) != len(self.live_claim_ids):
            raise ManagedLocalError("live claim IDs must be unique")
        if any(
            not isinstance(value, ResourceAvailabilityStatus)
            for value in self.resource_status
        ):
            raise ManagedLocalError("resource statuses must be availability statuses")
        if len(
            {
                (value.resource_kind, value.local_capacity_key)
                for value in self.resource_status
            }
        ) != len(self.resource_status):
            raise ManagedLocalError("resource status keys must be unique")


@dataclass(frozen=True, slots=True)
class ManagedOfferSnapshot:
    """Coordinator-retained, one-use view of one agent availability revision."""

    agent_id: str
    session_id: str
    offer_revision: str
    snapshot_revision: str
    inventory_revision: str
    availability_revision: str
    component_descriptors: tuple[SchedulingComponentDescriptor, ...]
    provider_descriptors: tuple[SchedulingComponentDescriptor, ...]
    atoms: tuple[CapacityAtom, ...]
    reflected_claim_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "agent_id",
            "session_id",
            "offer_revision",
            "snapshot_revision",
            "inventory_revision",
            "availability_revision",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ManagedLocalError(f"{name} must be a non-empty string")
        if not self.component_descriptors or any(
            not isinstance(item, SchedulingComponentDescriptor)
            for item in self.component_descriptors
        ):
            raise ManagedLocalError("offer component descriptors must not be empty")
        if len({item.kind for item in self.component_descriptors}) != len(
            self.component_descriptors
        ):
            raise ManagedLocalError("offer component descriptor kinds must be unique")
        if not self.provider_descriptors or any(
            not isinstance(item, SchedulingComponentDescriptor)
            for item in self.provider_descriptors
        ):
            raise ManagedLocalError("offer provider descriptors must not be empty")
        if len({item.kind for item in self.provider_descriptors}) != len(
            self.provider_descriptors
        ):
            raise ManagedLocalError("offer provider descriptor kinds must be unique")
        if any(not isinstance(item, CapacityAtom) for item in self.atoms) or len(
            {item.key for item in self.atoms}
        ) != len(self.atoms):
            raise ManagedLocalError("offer capacity atoms must be unique")
        component_kinds = {item.kind for item in self.component_descriptors}
        provider_kinds = {item.kind for item in self.provider_descriptors}
        atom_kinds = {item.owner_resource_kind for item in self.atoms}
        if component_kinds != provider_kinds:
            raise ManagedLocalError(
                "offer planner and provider descriptor kinds must match"
            )
        if not atom_kinds.issubset(component_kinds):
            raise ManagedLocalError(
                "offer capacity atom owners require planner and provider descriptors"
            )
        if any(
            not isinstance(value, str) or not value
            for value in self.reflected_claim_ids
        ) or len(set(self.reflected_claim_ids)) != len(self.reflected_claim_ids):
            raise ManagedLocalError(
                "offer reflected claim IDs must be non-empty and unique"
            )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "offer_revision": self.offer_revision,
            "snapshot_revision": self.snapshot_revision,
            "inventory_revision": self.inventory_revision,
            "availability_revision": self.availability_revision,
            "component_descriptors": [
                item.to_dict() for item in self.component_descriptors
            ],
            "provider_descriptors": [
                item.to_dict() for item in self.provider_descriptors
            ],
            "atoms": [item.to_dict() for item in self.atoms],
            "reflected_claim_ids": list(self.reflected_claim_ids),
        }


@runtime_checkable
class AgentResourceProvider(Protocol):
    """Versioned physical-resource lifecycle; outcomes never imply OS isolation."""

    descriptor: SchedulingComponentDescriptor
    claim_contracts: tuple[ResourceClaimContractDescriptor, ...]

    def observe(self, request: ObserveRequest) -> ObserveResult: ...
    def restore_capacity_holding(self, command: ClaimCommand) -> None: ...
    def prepare(self, command: ClaimCommand) -> ClaimResult: ...
    def reconcile(self, command: ClaimCommand) -> ClaimResult: ...
    def activate(self, command: ClaimCommand) -> ClaimResult: ...
    def abort(self, command: ClaimCommand) -> ClaimResult: ...
    def release(self, command: ClaimCommand) -> ClaimResult: ...

    def worker_environment(self, command: ClaimCommand) -> Mapping[str, str]: ...


def _connect_sqlite(
    path: Path, *, require_existing: bool = False, sqlite_policy: SQLitePolicy | None = None
) -> sqlite3.Connection:
    if sqlite_policy is not None:
        connect = connect_existing if require_existing else initialize_database
        return connect(path, policy=sqlite_policy, isolation_level="")
    target: str | Path = (
        f"{path.resolve().as_uri()}?mode=rw" if require_existing else path
    )
    return sqlite3.connect(target, uri=require_existing)


def _require_sqlite_columns(
    conn: sqlite3.Connection,
    table: str,
    required: set[str],
    owner: str,
) -> None:
    try:
        columns = {
            str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")
        }
    except sqlite3.DatabaseError as exc:
        raise ManagedLocalError(f"{owner} schema is unavailable") from exc
    if not required.issubset(columns):
        raise ManagedLocalError(f"{owner} schema is unsupported")


def _assignment_dict(value: ManagedAssignment) -> dict[str, PlainData]:
    return {name: getattr(value, name) for name in value.__dataclass_fields__}


def _assignment_from_dict(value: object) -> ManagedAssignment:
    expected = set(ManagedAssignment.__dataclass_fields__)
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ManagedLocalError("retained assignment identity is invalid")
    try:
        return ManagedAssignment(
            assignment_id=cast(str, value["assignment_id"]),
            run_uri=cast(str, value["run_uri"]),
            stage_work_id=cast(str, value["stage_work_id"]),
            stage_name=cast(str, value["stage_name"]),
            attempt=cast(int, value["attempt"]),
            attempt_id=cast(str, value["attempt_id"]),
            agent_id=cast(str, value["agent_id"]),
            session_id=cast(str, value["session_id"]),
            offer_id=cast(str, value["offer_id"]),
            claim_id=cast(str, value["claim_id"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ManagedLocalError("retained assignment identity is invalid") from exc


def _agent_at_or_after(state: AssignmentState, checkpoint: AssignmentState) -> bool:
    try:
        return _AGENT_SUCCESS_ORDER.index(state) >= _AGENT_SUCCESS_ORDER.index(
            checkpoint
        )
    except ValueError:
        return False


def _coordinator_at_or_after(state: str, checkpoint: str) -> bool:
    try:
        return _COORDINATOR_SUCCESS_ORDER.index(
            state
        ) >= _COORDINATOR_SUCCESS_ORDER.index(checkpoint)
    except ValueError:
        return False


def _claim_command_dict(command: ClaimCommand) -> dict[str, PlainData]:
    claim = command.claim
    return {
        "assignment_id": command.assignment.assignment_id,
        "operation_id": command.operation_id,
        "provider_descriptor": command.provider_descriptor.to_dict(),
        "resource_kind": claim.resource_kind,
        "contract": claim.contract.to_dict(),
        "atoms": [atom.to_dict() for atom in claim.atoms],
        "provider_data_version": claim.provider_data_version,
        "provider_data": thaw_plain_data(
            claim.provider_data, path="claim.provider_data"
        ),
        "claim_fingerprint": claim.fingerprint,
    }


def _claim_command_from_dict(
    assignment: ManagedAssignment | _ProbeClaimOwner, data: object
) -> ClaimCommand:
    expected = {
        "assignment_id",
        "operation_id",
        "provider_descriptor",
        "resource_kind",
        "contract",
        "atoms",
        "provider_data_version",
        "provider_data",
        "claim_fingerprint",
    }
    if not isinstance(data, Mapping) or set(data) != expected:
        raise ManagedLocalError("retained claim command is invalid")
    if data.get("assignment_id") != assignment.assignment_id:
        raise ManagedLocalError("retained claim assignment conflicts")
    atoms_data = data.get("atoms")
    if not isinstance(atoms_data, Sequence):
        raise ManagedLocalError("retained claim atoms are invalid")
    claim = ResourceClaim(
        resource_kind=cast(str, data.get("resource_kind")),
        contract=ResourceClaimContractDescriptor.from_dict(data.get("contract")),
        atoms=tuple(
            _capacity_atom_from_dict(cast(Mapping[str, object], atom))
            for atom in atoms_data
        ),
        provider_data_version=cast(int, data.get("provider_data_version")),
        provider_data=cast(Mapping[str, PlainData], data.get("provider_data", {})),
    )
    if data.get("claim_fingerprint") != claim.fingerprint:
        raise ManagedLocalError("retained claim fingerprint conflicts")
    try:
        provider_descriptor = SchedulingComponentDescriptor.from_dict(
            data["provider_descriptor"]
        )
    except Exception as exc:
        raise ManagedLocalError(
            "retained claim provider descriptor is invalid"
        ) from exc
    return ClaimCommand(
        assignment,
        cast(str, data["operation_id"]),
        claim,
        provider_descriptor,
    )


def _operation_command(command: ClaimCommand, operation: str) -> ClaimCommand:
    return ClaimCommand(
        assignment=command.assignment,
        operation_id=f"{command.operation_id}:{operation}",
        claim=command.claim,
        provider_descriptor=command.provider_descriptor,
    )


@_cooperative
def _provider_call(
    operation: Callable[[ClaimCommand], ClaimResult], command: ClaimCommand
) -> Generator[_Progress, Any, ClaimResult]:
    try:
        result = yield from _steps(operation, command)
    except Exception as exc:  # noqa: BLE001 - provider failures are indeterminate facts.
        return ClaimResult(
            ClaimOutcome.INDETERMINATE,
            command.operation_id,
            command.claim.fingerprint,
            f"provider raised {type(exc).__name__}",
        )
    if not isinstance(result, ClaimResult):
        return ClaimResult(
            ClaimOutcome.INDETERMINATE,
            command.operation_id,
            command.claim.fingerprint,
            "provider returned a malformed result",
        )
    if (
        result.operation_id != command.operation_id
        or result.claim_fingerprint != command.claim.fingerprint
    ):
        return ClaimResult(
            ClaimOutcome.INDETERMINATE,
            command.operation_id,
            command.claim.fingerprint,
            "provider result identity mismatch",
        )
    return result


def _capacity_atom_from_dict(value: Mapping[str, object]) -> CapacityAtom:
    try:
        return CapacityAtom(
            owner_resource_kind=cast(str, value["owner_resource_kind"]),
            local_capacity_key=cast(str, value["local_capacity_key"]),
            amount=ExactQuantity.from_dict(value["amount"]),
            unit=cast(str, value["unit"]),
            granularity=ExactQuantity.from_dict(value["granularity"]),
        )
    except Exception as exc:
        raise ManagedLocalError(
            "durable offer contains an invalid capacity atom"
        ) from exc


def _json(value: Mapping[str, PlainData]) -> str:
    try:
        frozen = freeze_plain_data(value, path="managed local journal")
    except ValueError as exc:
        raise ManagedLocalError(str(exc)) from exc
    return json.dumps(
        thaw_plain_data(frozen, path="managed local journal"),
        sort_keys=True,
        separators=(",", ":"),
    )

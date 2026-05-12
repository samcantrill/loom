"""Service-backed workspace coordination store adapter."""

from __future__ import annotations

from typing import TypeVar

from .authority_client import AuthorityClient
from .authority_protocol import AuthorityProtocolResponse, AuthorityProtocolResult
from .capabilities import (
    BackendCapability,
    BackendCapabilityRecord,
    BackendCapabilitySet,
    CapabilityScope,
    CapabilitySupport,
)
from .coordination import (
    ConcurrencyCounter,
    CoordinationRecoveryRecord,
    CoordinationStoreError,
    ResourceLeaseRecord,
    SweepIdentity,
    TrialLeaseRecord,
    TrialReference,
    WorkspaceIdentity,
)
from .read_models import BackendRevision, LeaseRecord, LifecycleReason
from .schema_policy import AUTHORITY_SCHEMA_VERSION, check_authority_schema_version


_T = TypeVar("_T")


class ServiceWorkspaceCoordinationStore:
    """Workspace coordination adapter backed by an authority service."""

    def __init__(
        self,
        client: AuthorityClient,
        *,
        workspace_id: str | None = None,
        service_generation: str | None = None,
    ) -> None:
        self._client = client
        self._workspace_id = workspace_id
        self._service_generation = service_generation

    def capabilities(self) -> BackendCapabilitySet:
        return BackendCapabilitySet(
            backend_name="authority-service-workspace-coordination",
            records=(
                _supported(BackendCapability.CROSS_RUN_COORDINATION),
                _supported(BackendCapability.GLOBAL_COUNTERS),
                _supported(BackendCapability.RECOVERY_SCANS),
                _supported(BackendCapability.BACKEND_LEASE_TIME),
                _supported(BackendCapability.CONSISTENT_READS),
                _supported(BackendCapability.REVISIONED_SNAPSHOTS),
                _supported(BackendCapability.SERVICE_ENDPOINT),
                BackendCapabilityRecord(
                    capability=BackendCapability.PER_RUN_COORDINATION,
                    scope=CapabilityScope.PER_RUN,
                    support=CapabilitySupport.UNSUPPORTED,
                    message=(
                        "workspace coordination is cross-run service state; "
                        "per-run coordination is not a Phase 15 service capability"
                    ),
                ),
            ),
        )

    def check_schema(self):
        return check_authority_schema_version(
            {"schema_version": AUTHORITY_SCHEMA_VERSION}
        )

    def create_workspace(self, identity: WorkspaceIdentity) -> BackendRevision:
        result = _accepted(
            self._client.create_workspace(
                identity,
                service_generation=self._service_generation,
            )
        )
        return _required(result.revision, "revision")

    def create_sweep(self, identity: SweepIdentity) -> BackendRevision:
        result = _accepted(
            self._client.create_sweep(
                identity,
                service_generation=self._service_generation,
            )
        )
        return _required(result.revision, "revision")

    def record_trial(self, trial: TrialReference) -> BackendRevision:
        result = _accepted(
            self._client.record_trial(
                trial,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        )
        return _required(result.revision, "revision")

    def list_trials(self, sweep_id: str) -> tuple[TrialReference, ...]:
        result = _accepted(
            self._client.list_trials(
                sweep_id,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        )
        return result.trials

    def acquire_trial_lease(
        self,
        sweep_id: str,
        trial_id: str,
        *,
        owner_id: str,
        lease_ttl_seconds: int,
    ) -> TrialLeaseRecord:
        result = _accepted(
            self._client.acquire_trial_lease(
                sweep_id,
                trial_id,
                owner_id=owner_id,
                lease_ttl_seconds=lease_ttl_seconds,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        )
        return _required(result.trial_lease, "trial_lease")

    def acquire_resource_lease(
        self,
        workspace_id: str,
        resource_key: str,
        *,
        owner_id: str,
        amount: int,
        lease_ttl_seconds: int,
    ) -> ResourceLeaseRecord:
        result = _accepted(
            self._client.acquire_resource_lease(
                workspace_id,
                resource_key,
                owner_id=owner_id,
                amount=amount,
                lease_ttl_seconds=lease_ttl_seconds,
                service_generation=self._service_generation,
            )
        )
        return _required(result.resource_lease, "resource_lease")

    def renew_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        lease_ttl_seconds: int,
    ) -> LeaseRecord:
        result = _accepted(
            self._client.renew_coordination_lease(
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                lease_ttl_seconds=lease_ttl_seconds,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        )
        return _required(result.lease, "lease")

    def release_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason | None = None,
    ) -> LeaseRecord:
        result = _accepted(
            self._client.release_coordination_lease(
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        )
        return _required(result.lease, "lease")

    def fail_lease(
        self,
        lease_id: str,
        *,
        owner_id: str,
        fencing_token: str,
        reason: LifecycleReason,
    ) -> LeaseRecord:
        result = _accepted(
            self._client.fail_coordination_lease(
                lease_id,
                owner_id=owner_id,
                fencing_token=fencing_token,
                reason=reason,
                service_generation=self._service_generation,
                workspace_id=self._workspace_id,
            )
        )
        return _required(result.lease, "lease")

    def set_resource_limit(
        self, workspace_id: str, resource_key: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        result = _accepted(
            self._client.set_resource_limit(
                workspace_id,
                resource_key,
                limit=limit,
                service_generation=self._service_generation,
            )
        )
        return _required(result.counter, "counter")

    def set_counter_limit(
        self, workspace_id: str, counter_name: str, *, limit: int | None
    ) -> ConcurrencyCounter:
        result = _accepted(
            self._client.set_counter_limit(
                workspace_id,
                counter_name,
                limit=limit,
                service_generation=self._service_generation,
            )
        )
        return _required(result.counter, "counter")

    def increment_counter(
        self,
        workspace_id: str,
        counter_name: str,
        *,
        amount: int = 1,
        limit: int | None = None,
    ) -> ConcurrencyCounter:
        result = _accepted(
            self._client.increment_counter(
                workspace_id,
                counter_name,
                amount=amount,
                limit=limit,
                service_generation=self._service_generation,
            )
        )
        return _required(result.counter, "counter")

    def decrement_counter(
        self, workspace_id: str, counter_name: str, *, amount: int = 1
    ) -> ConcurrencyCounter:
        result = _accepted(
            self._client.decrement_counter(
                workspace_id,
                counter_name,
                amount=amount,
                service_generation=self._service_generation,
            )
        )
        return _required(result.counter, "counter")

    def read_counter(
        self, workspace_id: str, counter_name: str
    ) -> ConcurrencyCounter | None:
        result = _accepted(
            self._client.read_counter(
                workspace_id,
                counter_name,
                service_generation=self._service_generation,
            )
        )
        return result.counter

    def scan_recovery(
        self, workspace_id: str
    ) -> tuple[CoordinationRecoveryRecord, ...]:
        result = _accepted(
            self._client.scan_coordination_recovery(
                workspace_id,
                service_generation=self._service_generation,
            )
        )
        return result.coordination_recovery_records


def _supported(capability: BackendCapability) -> BackendCapabilityRecord:
    return BackendCapabilityRecord(
        capability=capability,
        scope=CapabilityScope.CROSS_RUN,
    )


def _accepted(response: AuthorityProtocolResponse) -> AuthorityProtocolResult:
    if response.accepted and response.result is not None:
        return response.result
    rejection = response.rejection
    if rejection is None:
        raise CoordinationStoreError("authority coordination response was invalid")
    raise CoordinationStoreError(
        f"{rejection.code}: {rejection.message}; detail={dict(rejection.detail)}"
    )


def _required(value: _T | None, field: str) -> _T:
    if value is None:
        raise CoordinationStoreError(f"authority response missing {field}")
    return value


__all__ = ["ServiceWorkspaceCoordinationStore"]

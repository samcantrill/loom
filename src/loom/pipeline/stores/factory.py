"""Public authority-store factory."""

from __future__ import annotations

from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline.status import RunStatus, StageStatus
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
from .read_models import (
    AuthoritativeRunSnapshot,
    BackendRevision,
    CleanupCandidate,
    LeaseRecord,
    LifecycleReason,
    RecoveryRecord,
    StageLifecycleSnapshot,
)
from .schema_policy import AuthoritySchemaCheck


def create_run_store(
    config: AuthorityConfig | Mapping[str, object] | None = None,
    *,
    authority_store: PerRunAuthorityStore | None = None,
) -> RunStore:
    """Create the public authority-backed run-store surface.

    Phase 2 supports explicit per-run authority stores and the transitional
    SQLite authority backend. Later phases add service/database implementations
    behind this same factory path.
    """

    resolved_config = _resolve_config(config, authority_store=authority_store)
    if authority_store is not None:
        _validate_authority_store(authority_store)
        return _PerRunAuthorityRunStore(authority_store, resolved_config)
    if resolved_config.backend_kind is AuthorityBackendKind.TRANSITIONAL_SQLITE:
        from .sqlite_authority import SQLitePerRunAuthorityStore

        return _PerRunAuthorityRunStore(
            SQLitePerRunAuthorityStore(),
            resolved_config,
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
    ) -> BackendRevision:
        return self._authority_store.create_run(
            run_uri,
            status=status,
            metadata=metadata,
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
    ) -> StatusTransition:
        return self._authority_store.transition_run(
            run_uri,
            from_status=from_status,
            to_status=to_status,
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
    ) -> StatusTransition:
        return self._authority_store.transition_stage(
            self._run_uri,
            self._stage_name,
            from_status=from_status,
            to_status=to_status,
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
            return AuthorityConfig(backend_kind=AuthorityBackendKind.TEST_FAKE)
        return AuthorityConfig()
    if isinstance(config, AuthorityConfig):
        return config
    return AuthorityConfig.from_dict(config)


def _validate_authority_store(authority_store: PerRunAuthorityStore) -> None:
    if not isinstance(authority_store, PerRunAuthorityStore):
        raise TypeError("authority_store must satisfy PerRunAuthorityStore")


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise AuthorityStoreError(f"{field} must be a non-empty string")
    return value


__all__ = ["create_run_store"]

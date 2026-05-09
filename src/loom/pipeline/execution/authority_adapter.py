"""Internal execution adapter for authority-backed serial runs.

This module is intentionally not exported from the public pipeline package.
Phase 4 uses it from tests to exercise the backend write path before Phase 5
changes public backend selection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.pipeline.events import PipelineEvent, PipelineEventRecord
from loom.pipeline.locks import RunLockRecord
from loom.pipeline.status import RunStatus, RunStatusRecord, StageStatus, StageStatusRecord
from loom.pipeline.stores import (
    AuthorityStoreError,
    LocalRunStore,
    PerRunAuthorityStore,
    format_artifact_key,
)
from loom.pipeline.stores.inspection import RunStateInspection
from loom.pipeline.stores.read_models import (
    LeaseRecord,
    LifecycleReason,
    StageAttempt,
    StageLifecycleSnapshot,
)
from loom.pipeline.stores.run_store import RunFreshnessRecord
from loom.pipeline.stores.run_uri import validate_run_uri
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


@dataclass(frozen=True, slots=True)
class _AttemptLease:
    attempt: StageAttempt
    lease: LeaseRecord


@dataclass(frozen=True, slots=True)
class _ControllerLease:
    owner_id: str
    lease: LeaseRecord


class AuthorityBackedSerialRunStore:
    """RunStore-shaped adapter with backend authority as active write truth."""

    def __init__(
        self,
        *,
        local_store: LocalRunStore,
        authority_store: PerRunAuthorityStore,
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
        self.owner_id = owner_id
        self._attempt_leases: dict[tuple[str, str, int], _AttemptLease] = {}
        self._controller_leases: dict[str, _ControllerLease] = {}

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
        return self.local_store.read_run_freshness(run_uri)

    def read_run_status(self, run_uri: str) -> RunStatusRecord | None:
        try:
            snapshot = self.authority_store.snapshot(run_uri)
        except Exception:
            return None
        created_at = _created_at(self.local_store, run_uri, snapshot.revision.created_at)
        updated_at = snapshot.revision.created_at or created_at
        return RunStatusRecord(
            run_uri=run_uri,
            status=snapshot.status,
            created_at=created_at,
            updated_at=updated_at,
            started_at=created_at if snapshot.status not in {RunStatus.CREATED} else None,
            finished_at=updated_at
            if snapshot.status
            in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
            else None,
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

    def acquire_run_lock(
        self,
        run_uri: str,
        *,
        owner: Mapping[str, PlainData] | None = None,
    ) -> RunLockRecord:
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
        active = self._controller_leases.pop(token)
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
        stage = self._stage_snapshot(run_uri, stage_name)
        if stage is None:
            return None
        attempt = stage.attempts[-1].attempt if stage.attempts else 1
        updated_at = stage.revision.created_at or utc_timestamp()
        metadata = _reason_detail(stage.reason)
        return StageStatusRecord(
            run_uri=run_uri,
            stage_name=stage.stage_name,
            status=stage.status,
            attempt=attempt,
            updated_at=updated_at,
            started_at=_stage_started_at(stage),
            finished_at=_stage_finished_at(stage, updated_at),
            message=None if stage.reason is None else stage.reason.message,
            owner=_stage_owner(stage),
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
            payload["metadata"] = metadata
        self.local_store.write_stage_worker_request(
            run_uri, stage_name, payload, attempt=attempt
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
    authority_store: PerRunAuthorityStore,
    owner_id: str = "serial-controller",
) -> AuthorityBackedSerialRunStore:
    """Create the internal/test-selectable Phase 4 authority-backed store."""

    return AuthorityBackedSerialRunStore(
        local_store=LocalRunStore(root),
        authority_store=authority_store,
        owner_id=owner_id,
    )


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


__all__ = [
    "AuthorityBackedSerialRunStore",
    "create_authority_backed_serial_run_store",
]

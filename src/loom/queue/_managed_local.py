"""Durable, assignment-scoped local admission primitives.

This module is deliberately independent of the legacy ``run_stage_job`` path.
It is the small local half of the Stage 29 saga: coordinator code owns logical
reservations, this journal owns physical claims and the worker receives one
already-granted assignment.  In particular, none of these operations allocate
an attempt or take a run lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from ._embedded_recovery import EmbeddedRecovery

from loom.artifacts import ArtifactRef
from loom.io.uris import uri_to_path
from loom.pipeline.execution.models import (
    EXECUTION_FAILURE_SCHEMA_VERSION,
    STAGE_WORKER_RESULT_SCHEMA_VERSION,
    ExecutionFailure,
    StageWorkerRequest,
    StageWorkerResult,
)
from loom.pipeline.planning import StageFingerprintRecord
from loom.pipeline.resources import ResourceEntry
from loom.pipeline.runtime._resource_controls import (
    ControlDisposition,
    _validated_resource_controls,
    resource_control_records,
)
from loom.pipeline.runtime.resource_policy import ResourcePolicy
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import (
    LifecycleReason,
    LocalArtifactStore,
    LocalRunStore,
    OutputCommit,
)
from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.stores.authority import (
    ExecutionFence,
    PreparedAttemptExecutionAuthority,
)
from loom.scheduling import (
    ResourceClaim,
    SchedulingComponentDescriptor,
)
from loom.serialization import PlainData, thaw_plain_data
from loom.serialization._diagnostic_capture import _capture_exception_details
from loom.timestamps import utc_timestamp

from ._attempt_timing import assignment_milestone
from ._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorError,
    ResidentWorkerLaunch,
    ResidentWorkerLaunchProfile,
    SupervisorLaunchState,
    _launch_from_value,
    _launch_value,
)
from ._managed_agent_journal import (
    _require_agent_journal_schema as _require_agent_journal_schema,
    SQLiteAgentJournal,
)
from ._managed_contracts import (
    _agent_at_or_after,
    _assignment_dict as _assignment_dict,
    _assignment_from_dict as _assignment_from_dict,
    _json,
    _ManagedApplicationSuspended as _ManagedApplicationSuspended,
    _operation_command as _operation_command,
    _ProbeClaimOwner as _ProbeClaimOwner,
    _provider_call as _provider_call,
    _read_decline_reason as _read_decline_reason,
    AgentResourceProvider,
    AssignmentState,
    ClaimCommand,
    ClaimOutcome,
    ClaimResult,
    GPU_DECLINE_REASONS as GPU_DECLINE_REASONS,
    ManagedAssignment,
    ManagedExecutionReceipt,
    ManagedLocalError,
    ManagedOfferSnapshot,
    ManagedProcessStartError,
    ObserveRequest,
    ObserveResult,
    ProviderReleaseEvidence as ProviderReleaseEvidence,
    ResourceAvailabilityStatus,
)
from ._managed_coordinator_assignments import (
    _require_coordinator_assignment_schema as _require_coordinator_assignment_schema,
    _validate_decision_receipt,
    SQLiteCoordinatorAssignments,
)
from ._managed_providers import (
    _compose_agent_resource_providers as _compose_agent_resource_providers,
    _CompositeAgentResourceProvider as _CompositeAgentResourceProvider,
    _configured_provider_descriptor as _configured_provider_descriptor,
    _provider_group_descriptor as _provider_group_descriptor,
    AtomResourceProvider,
    CpuResourceProvider,
    GpuResourceProvider,
    MemoryResourceProvider,
)
from ._remote_stage_execution import (
    MAX_TRANSFER_BYTES,
    ResidentProfileDescriptor,
    _PreparationReportRetentionError,
    _read_regular_file_bytes,
    _RemoteArtifact,
    _RemoteExecutionReport,
    _RemoteOutputArtifact,
    _RemoteTransferLimitError,
    _resident_input_refs,
    _ResidentAssignmentBundle,
    _ResidentAssignmentWorkspace,
)


def grant_and_start_managed_assignment(
    *,
    authority: PreparedAttemptExecutionAuthority,
    journal: SQLiteAgentJournal,
    assignment: ManagedAssignment,
    request: Mapping[str, PlainData],
    commands: Sequence[ClaimCommand],
    providers: Mapping[str, AgentResourceProvider],
    launcher: Callable[[], str],
    start_failure: Callable[[ManagedProcessStartError], StageWorkerResult],
    process_execution_id: str | None = None,
) -> ExecutionFence:
    """Execute the bounded local admission-to-start saga for one reservation.

    The caller has already made the coordinator's logical reservation.  This
    function deliberately has no run lock and neither allocates attempts nor
    lets the worker write authority lifecycle truth.
    """
    authority.bind_prepared_attempt(
        assignment.run_uri,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.attempt_id,
    )
    journal.persist_request(assignment, request)
    prepared = journal.prepare_composite(assignment, commands, providers)
    if prepared is AssignmentState.DECLINED:
        authority.unbind_prepared_attempt(
            assignment.run_uri,
            assignment_id=assignment.assignment_id,
            attempt_id=assignment.attempt_id,
        )
        raise ManagedLocalError("managed assignment was definitively declined")
    if not _agent_at_or_after(prepared, AssignmentState.PREPARED):
        raise ManagedLocalError("managed assignment preparation is indeterminate")
    journal.accept(assignment.assignment_id)
    fence = authority.grant_prepared_attempt(
        assignment.run_uri,
        assignment_id=assignment.assignment_id,
        attempt_id=assignment.attempt_id,
    )
    journal.grant(assignment.assignment_id, fence.fencing_token)
    activation = journal.activate_composite(
        assignment.assignment_id, commands, providers
    )
    if not _agent_at_or_after(activation, AssignmentState.ACTIVE):
        raise ManagedLocalError("managed assignment activation is indeterminate")
    process_id = process_execution_id or f"{assignment.assignment_id}:root"
    journal.start_once(
        assignment.assignment_id, process_id, launcher, start_failure=start_failure
    )
    authority.confirm_execution_started(assignment.run_uri, fence=fence)
    return fence


@dataclass(frozen=True)
class _PreparedLocalWorkspace:
    assignment: ManagedAssignment
    worker_request: StageWorkerRequest
    commands: tuple[ClaimCommand, ...]
    workspace: _ResidentAssignmentWorkspace
    delivered: _ResidentAssignmentBundle
    predecessor: str | None
    continuing: bool


def _prepare_local_workspace(
    *, assignment: ManagedAssignment, worker_request: StageWorkerRequest,
    claims: Sequence[ResourceClaim], providers: Mapping[str, AgentResourceProvider],
    journal: SQLiteAgentJournal, run_store: LocalRunStore,
    decision_receipt: Mapping[str, PlainData], agent_root: Path,
    resident_launch_profile: ResidentWorkerLaunchProfile,
    durable_files: Literal["best_effort", "strict"],
    embedded_recovery: EmbeddedRecovery | None,
) -> _PreparedLocalWorkspace:
    """Stage the exact restartable workspace before acquiring coordinator capacity."""
    _require_worker_assignment_match(assignment, worker_request)
    predecessor = worker_request.metadata.get("managed_output_predecessor")
    if predecessor is not None and (
        not isinstance(predecessor, str) or not predecessor
    ):
        raise ManagedLocalError("managed output predecessor is invalid")
    if not isinstance(run_store, LocalRunStore):
        raise ManagedLocalError(
            "managed parent requires the configured local run store"
        )
    claims = tuple(sorted(claims, key=lambda item: item.resource_kind))
    claim_kinds = tuple(claim.resource_kind for claim in claims)
    if len(set(claim_kinds)) != len(claim_kinds):
        raise ManagedLocalError(
            "managed assignment requires one claim per resource kind"
        )
    validated_decision = cast(
        Mapping[str, object],
        json.loads(
            _validate_decision_receipt(
                decision_receipt,
                assignment=assignment,
                claims=claims,
            )
        ),
    )
    recorded_provider_descriptors = {
        descriptor.kind: descriptor
        for descriptor in (
            SchedulingComponentDescriptor.from_dict(item)
            for item in cast(
                Sequence[Mapping[str, object]],
                validated_decision["provider_descriptors"],
            )
        )
    }
    commands = tuple(
        ClaimCommand(
            assignment,
            f"{assignment.assignment_id}:prepare:{index}",
            claim,
            recorded_provider_descriptors[claim.resource_kind],
        )
        for index, claim in enumerate(claims)
    )
    for claim, command in zip(claims, commands, strict=True):
        provider = providers.get(claim.resource_kind)
        if provider is None:
            raise ManagedLocalError("no provider for claim resource kind")
        if command.provider_descriptor != recorded_provider_descriptors.get(
            claim.resource_kind
        ):
            raise ManagedLocalError(
                "command provider descriptor does not match decision evidence"
            )
        if provider.descriptor != command.provider_descriptor:
            raise ManagedLocalError(
                "decision provider descriptor does not match configured provider"
            )
        if claim.contract not in provider.claim_contracts:
            raise ManagedLocalError(
                "decision claim contract is not supported by configured provider"
            )
    profile = ResidentProfileDescriptor.from_dict(resident_launch_profile.descriptor)
    workspace = _ResidentAssignmentWorkspace(
        agent_root, assignment.assignment_id, sqlite_policy=journal._sqlite_policy,
        durable_files=durable_files,
        _allow_initialize=None if journal._sqlite_policy is None else (
            journal.find_state(assignment.assignment_id) is None
        ),
    )
    retained_inputs = (
        {item.logical_name: item for item in workspace.request().inputs}
        if workspace.has_request() and workspace.state() in {"GRANTED", "STARTED", "RESULT"}
        else None
    )
    remote_inputs: list[_RemoteArtifact] = []
    input_paths: dict[str, Path] = {}
    input_refs: dict[str, ArtifactRef] = {}
    total_input_bytes = 0
    transfer_refs = _resident_input_refs(
        worker_request.inputs,
        cast(StageFingerprintRecord, worker_request.fingerprint).to_dict(),
        worker_request.metadata,
    )
    if retained_inputs is not None and set(retained_inputs) != set(transfer_refs):
        raise ManagedLocalError("retained resident input interface conflicts")
    for logical_name, ref in sorted(transfer_refs.items()):
        transfer_id = (
            "input-"
            + hashlib.sha256(
                (
                    assignment.assignment_id
                    + "\0"
                    + logical_name
                    + "\0"
                    + ref.artifact_id
                ).encode("utf-8")
            ).hexdigest()
        )
        if retained_inputs is None:
            artifact, source = _RemoteArtifact.from_local_ref(
                transfer_id=transfer_id, logical_name=logical_name, ref=ref
            )
            input_paths[transfer_id] = source
            input_refs[transfer_id] = ref
        else:
            artifact = retained_inputs[logical_name]
            if (
                artifact.transfer_id != transfer_id
                or artifact.artifact_id != ref.artifact_id
                or artifact.artifact_type != ref.artifact_type
                or artifact.codec_key != ref.codec_key
                or artifact.artifact_schema_version != ref.schema_version
                or artifact.fingerprint != ref.fingerprint
                or artifact.producer_stage != ref.producer_stage
                or artifact.created_at != ref.created_at
                or artifact.metadata != ref.metadata
                or ref.checksum is not None and ref.checksum != f"sha256:{artifact.digest}"
            ):
                raise ManagedLocalError("retained resident input identity conflicts")
        from loom.pipeline.stores.shared_artifacts import binding
        total_input_bytes += artifact.size_bytes if binding(artifact.metadata) is None else 0
        if total_input_bytes > MAX_TRANSFER_BYTES:
            raise ManagedLocalError("resident assignment inputs exceed the bound")
        remote_inputs.append(artifact)
    fingerprint = cast(StageFingerprintRecord, worker_request.fingerprint)
    from loom.pipeline._project_contracts import EXECUTION

    from ._execution_binding import execution_binding
    from .shared_execution import SHARED_EXECUTION_SCOPE, scope
    shared = scope(fingerprint.payload.fingerprint_fields.get(SHARED_EXECUTION_SCOPE))
    continuing = shared is not None and "staging_continuation" in shared
    if continuing and embedded_recovery is None:
        raise ManagedLocalError("embedded output staging continuation is unavailable")
    worker_request = replace(worker_request, metadata={**worker_request.metadata,
        EXECUTION: execution_binding(worker_request, profile.environment_fingerprint,
            store=None if continuing else run_store, launch=resident_launch_profile,
            workspace=agent_root / "assignments" / assignment.assignment_id)})
    delivered = _ResidentAssignmentBundle.from_worker_request(
        assignment_id=assignment.assignment_id,
        stage_work_id=assignment.stage_work_id,
        attempt_id=assignment.attempt_id,
        offer_id=assignment.offer_id,
        claim_id=assignment.claim_id,
        worker_request=worker_request,
        profile=profile,
        inputs=tuple(remote_inputs),
        declared_outputs=tuple(sorted(fingerprint.payload.declared_outputs)),
        claims=claims,
        provider_descriptors=tuple(command.provider_descriptor for command in commands),
    )
    from ._remote_stage_execution import _assignment_local_scope
    from .preparation import _require_local_binding

    _require_local_binding(_assignment_local_scope(delivered), resident_launch_profile,
                           agent_id=assignment.agent_id)
    if continuing:
        assert embedded_recovery is not None
        from ._shared_recovery import WIRE, validate_wire
        from ._shared_staging_continuation import WIRE as staging_wire

        if workspace.has_request():
            retained = workspace.request()
            base_metadata = {key: value for key, value in retained.worker_metadata.items()
                             if key not in {WIRE, staging_wire}}
            if replace(retained, worker_metadata=base_metadata) != delivered or validate_wire(retained) is None:
                raise ManagedLocalError("retained embedded recovery delivery conflicts")
            delivered = retained
        else:
            delivered = embedded_recovery.bind(delivered, assignment)
    workspace.persist_request(delivered, resident_launch_profile)
    for artifact in remote_inputs if retained_inputs is None else ():
        from loom.pipeline.stores.shared_artifacts import binding
        if binding(artifact.metadata) is not None:
            continue
        _stage_same_host_input_closure(
            workspace=workspace,
            artifact=artifact,
            ref=input_refs[artifact.transfer_id],
            source=input_paths[artifact.transfer_id],
            run_store=run_store,
            run_uri=worker_request.run_uri,
        )
        workspace.stage_input(
            artifact.transfer_id,
            _read_regular_file_bytes(input_paths[artifact.transfer_id]),
        )
    workspace_state = workspace.state()
    if workspace_state in {"DELIVERED", "ACCEPTED"}:
        workspace.accept()
    elif workspace_state not in {"GRANTED", "STARTED", "RESULT"}:
        raise ManagedLocalError("resident workspace state is not replayable")

    return _PreparedLocalWorkspace(assignment, worker_request, commands, workspace, delivered, predecessor, continuing)


def run_managed_local_assignment(
    *,
    coordinator: SQLiteCoordinatorAssignments,
    authority: PreparedAttemptExecutionAuthority,
    journal: SQLiteAgentJournal,
    assignment: ManagedAssignment,
    worker_request: StageWorkerRequest,
    claims: Sequence[ResourceClaim],
    providers: Mapping[str, AgentResourceProvider],
    run_store: LocalRunStore,
    max_parallel_stages: int | None,
    decision_receipt: Mapping[str, PlainData],
    agent_root: Path,
    supervisor: AgentProcessSupervisorClient,
    resident_launch_profile: ResidentWorkerLaunchProfile,
    durable_files: Literal["best_effort", "strict"] = "best_effort",
    cancellation_requested: Callable[[], bool] | None = None,
    suspend_requested: Callable[[], bool] | None = None,
    execution_started: Callable[[], None] | None = None,
    reservation_guard: Callable[[], AbstractContextManager[None]] | None = None,
    _reservation_transaction: Callable[[], AbstractContextManager[sqlite3.Connection]] | None = None,
    embedded_recovery: EmbeddedRecovery | None = None,
) -> ManagedExecutionReceipt:
    """Run one exact local assignment through the durable Phase 2 saga.

    The coordinator, authority, and journal remain separate transaction owners.
    Each cross-owner fact is replayable, while this bounded composition drives
    them synchronously for local tests and later command facades.
    """

    prepared = _prepare_local_workspace(
        assignment=assignment, worker_request=worker_request, claims=claims,
        providers=providers, journal=journal, run_store=run_store,
        decision_receipt=decision_receipt, agent_root=agent_root,
        resident_launch_profile=resident_launch_profile, durable_files=durable_files,
        embedded_recovery=embedded_recovery,
    )
    # The assignment-local bundle and exact bytes precede the logical reserve.
    # A crash after reserve can therefore reconstruct claims and launch identity
    # without serializing the coordinator run URI into the child workspace.
    with reservation_guard() if reservation_guard is not None else nullcontext():
        coordinator.reserve(
            assignment,
            claims,
            max_parallel_stages=max_parallel_stages,
            decision_receipt=decision_receipt,
            _reservation_transaction=_reservation_transaction,
        )
    return _run_reserved_local_assignment(
        prepared, coordinator=coordinator, authority=authority, journal=journal,
        providers=providers, run_store=run_store, supervisor=supervisor,
        resident_launch_profile=resident_launch_profile, cancellation_requested=cancellation_requested,
        suspend_requested=suspend_requested, execution_started=execution_started, embedded_recovery=embedded_recovery,
    )


@dataclass(frozen=True, slots=True)
class _ReservedLocalExecution:
    """One resident invocation with independently replayable journal checkpoints."""

    staged: _PreparedLocalWorkspace
    coordinator: SQLiteCoordinatorAssignments
    authority: PreparedAttemptExecutionAuthority
    journal: SQLiteAgentJournal
    providers: Mapping[str, AgentResourceProvider]
    run_store: LocalRunStore
    supervisor: AgentProcessSupervisorClient
    resident_launch_profile: ResidentWorkerLaunchProfile
    cancellation_requested: Callable[[], bool] | None
    suspend_requested: Callable[[], bool] | None
    execution_started: Callable[[], None] | None
    embedded_recovery: EmbeddedRecovery | None

    def prepare_grant(self) -> ExecutionFence:
        assignment = self.staged.assignment
        worker_request = self.staged.worker_request
        commands = self.staged.commands
        workspace = self.staged.workspace
        delivered = self.staged.delivered
        self.authority.bind_prepared_attempt(
            assignment.run_uri,
            assignment_id=assignment.assignment_id,
            attempt_id=assignment.attempt_id,
        )
        self.coordinator.advance(
            assignment.assignment_id, expected="reserved", next_state="bound"
        )
        self.journal.persist_request(assignment, delivered.to_dict())
        if self.journal.read_state(assignment.assignment_id) is AssignmentState.START_FAILED:
            retained_fence = self.journal.read_grant_fence(assignment.assignment_id)
            if retained_fence is None:
                raise ManagedLocalError("failed launch has no retained grant")
            self.journal.require_failed_before_start(
                assignment.assignment_id, fence=retained_fence
            )
            retained_result = self.journal.read_result(assignment.assignment_id)
            child_result = (
                _map_resident_result_identity(
                    retained_result, worker_request=workspace.worker_request(), outputs={}
                )
                if retained_result is not None
                else workspace.worker_result()
            )
            if child_result is None:
                result_path = workspace.root / "worker-result.json"
                if not result_path.is_file():
                    raise ManagedLocalError(
                        "failed launch has no durable diagnostic result"
                    )
                child_result = StageWorkerResult.from_dict(
                    json.loads(result_path.read_text())
                )
            retained_launch = workspace.supervisor_launch_json() is not None
            if retained_launch and not self.supervisor.reject_unstarted_assignment(assignment.assignment_id):
                raise ManagedLocalError("failed launch ownership is unresolved")
            result_path = workspace.root / "worker-result.json"
            if not result_path.is_file():
                atomic_write_bytes(result_path, _json(child_result.to_dict()).encode(), durability=workspace.durable_files)
            workspace.persist_failed_before_start(
                child_result, fence=retained_fence, supervisor_rejected=retained_launch
            )
            self.journal.record_result(
                assignment.assignment_id,
                _map_resident_result_identity(
                    child_result, worker_request=worker_request, outputs={}
                ).to_dict(),
            )
        _emit_assignment_event(
            self.journal,
            self.coordinator,
            assignment.assignment_id,
            "request_and_inputs_durable",
            {"attempt_id": assignment.attempt_id},
        )

        prepared = self.journal.prepare_composite(assignment, commands, self.providers)
        if prepared is AssignmentState.DECLINED:
            self.authority.unbind_prepared_attempt(
                assignment.run_uri,
                assignment_id=assignment.assignment_id,
                attempt_id=assignment.attempt_id,
            )
            availability_revision = _release_revision(
                journal=self.journal,
                assignment=assignment,
                providers=self.providers,
                operation="declined",
                release=self.journal.release_declined,
            )
            reason_code = self.journal.read_decline_reason(assignment.assignment_id)
            if reason_code is not None:
                _emit_assignment_event(
                    self.journal,
                    self.coordinator,
                    assignment.assignment_id,
                    "definitive_decline",
                    {"reason_code": reason_code},
                )
            _emit_assignment_event(
                self.journal,
                self.coordinator,
                assignment.assignment_id,
                "definitive_decline_released",
                {"availability_revision": availability_revision},
            )
            self.coordinator.release_unaccepted(assignment.assignment_id)
            raise ManagedLocalError("managed assignment was definitively declined")
        if not _agent_at_or_after(prepared, AssignmentState.PREPARED):
            self.coordinator.advance(
                assignment.assignment_id, expected="bound", next_state="unknown"
            )
            _emit_assignment_event(
                self.journal,
                self.coordinator,
                assignment.assignment_id,
                "preparation_unknown",
                {"attempt_id": assignment.attempt_id},
            )
            raise ManagedLocalError("managed assignment preparation is indeterminate")

        self.journal.accept(assignment.assignment_id)
        self.coordinator.advance(
            assignment.assignment_id, expected="bound", next_state="accepted"
        )
        _emit_assignment_event(
            self.journal,
            self.coordinator,
            assignment.assignment_id,
            "accepted",
            {"claim_id": assignment.claim_id},
        )
        fence = self.authority.grant_prepared_attempt(
            assignment.run_uri,
            assignment_id=assignment.assignment_id,
            attempt_id=assignment.attempt_id,
        )
        self.journal.grant(assignment.assignment_id, fence.fencing_token)
        workspace_state = workspace.state()
        if workspace_state == "ACCEPTED":
            workspace.grant(fence.fencing_token)
        elif workspace_state not in {"GRANTED", "STARTED", "RESULT"}:
            raise ManagedLocalError("resident workspace grant state conflicts")
        self.coordinator.advance(
            assignment.assignment_id, expected="accepted", next_state="granted"
        )
        activation = self.journal.activate_composite(
            assignment.assignment_id, commands, self.providers
        )
        if not _agent_at_or_after(activation, AssignmentState.ACTIVE):
            self.coordinator.advance(
                assignment.assignment_id, expected="granted", next_state="unknown"
            )
            _emit_assignment_event(
                self.journal,
                self.coordinator,
                assignment.assignment_id,
                "activation_unknown",
                {"fence": fence.fencing_token},
            )
            raise ManagedLocalError("managed assignment activation is indeterminate")

        return fence

    def launch_or_resume(self, fence: ExecutionFence) -> tuple[StageWorkerResult, str]:
        assignment = self.staged.assignment
        worker_request = self.staged.worker_request
        commands = self.staged.commands
        workspace = self.staged.workspace
        delivered = self.staged.delivered
        continuing = self.staged.continuing
        durable_result = self.journal.read_result(assignment.assignment_id)
        if durable_result is not None:
            coordinator_state = self.coordinator.state(assignment.assignment_id)
            return durable_result, "granted" if coordinator_state == "granted" else "running"

        if (
            self.journal.read_state(assignment.assignment_id) is AssignmentState.ACTIVE
            and self.cancellation_requested is not None
            and self.cancellation_requested()
        ):
            child_result = _cancelled_worker_result(workspace.worker_request())
            atomic_write_bytes(
                workspace.root / "worker-result.json",
                _json(child_result.to_dict()).encode("utf-8"), durability=workspace.durable_files)
            workspace.persist_cancelled_before_start(child_result)
            worker_result = _map_resident_result_identity(
                child_result, worker_request=worker_request, outputs={}
            )
            self.journal.record_cancelled_before_start(
                assignment.assignment_id, worker_result.to_dict()
            )
            return worker_result, "granted"

        process_id = f"{assignment.assignment_id}:root"

        def start_failure(error: ManagedProcessStartError) -> StageWorkerResult:
            return _map_resident_result_identity(
                _start_failed_worker_result(workspace.worker_request(), error),
                worker_request=worker_request,
                outputs={},
            )

        try:
            environment = _worker_environment(
                self.resident_launch_profile,
                workspace.root,
                commands,
                self.providers,
                cast(
                    Mapping[str, object],
                    delivered.resolved_runtime.get("resource_selection"),
                ),
            )
        except ManagedProcessStartError as exc:

            def fail_before_supervisor(error: ManagedProcessStartError = exc) -> str:
                raise error

            try:
                self.journal.start_once(
                    assignment.assignment_id,
                    process_id,
                    fail_before_supervisor,
                    start_failure=start_failure,
                )
            except ManagedProcessStartError:
                pass
            self.journal.require_failed_before_start(
                assignment.assignment_id, fence=fence.fencing_token
            )
            worker_result = cast(
                StageWorkerResult, self.journal.read_result(assignment.assignment_id)
            )
            child_result = _map_resident_result_identity(
                worker_result, worker_request=workspace.worker_request(), outputs={}
            )
            atomic_write_bytes(
                workspace.root / "worker-result.json",
                _json(child_result.to_dict()).encode("utf-8"), durability=workspace.durable_files)
            workspace.persist_failed_before_start(child_result, fence=fence.fencing_token)
            self.journal.record_result(assignment.assignment_id, worker_result.to_dict())
            return worker_result, "granted"
        expected_launch = ResidentWorkerLaunch(
            supervisor_id=self.supervisor.supervisor_id,
            continuity_epoch=self.supervisor.continuity_epoch,
            agent_id=self.supervisor.agent_id,
            session_id=assignment.session_id,
            assignment_id=assignment.assignment_id,
            process_execution_id=process_id,
            execution_fence=fence.fencing_token,
            launch_operation_id=f"{assignment.assignment_id}:launch:{fence.fencing_token}",
            bundle_digest=hashlib.sha256(
                _json(delivered.to_dict()).encode("utf-8")
            ).hexdigest(),
            workspace_root=workspace.root,
            profile=self.resident_launch_profile,
            environment=environment,
            resource_controls=_managed_resource_controls(
                worker_request.resolved_runtime, bindings_prepared=True
            ),
        )
        encoded_launch = workspace.supervisor_launch_json()
        if expected_launch.profile.container is not None:
            from loom.pipeline.runtime._resource_controls import (
                _validated_resource_controls,
            )

            expected_launch = replace(expected_launch, resource_controls=_validated_resource_controls(
                expected_launch.container_command.metadata.get("resource_controls")
            ))
        launch = (
            expected_launch
            if encoded_launch is None
            else _launch_from_value(json.loads(encoded_launch))
        )
        _require_retained_launch_match(launch, expected_launch)

        def launch_exact_worker() -> str:
            workspace.persist_supervisor_launch(
                json.dumps(_launch_value(launch), sort_keys=True, separators=(",", ":"))
            )
            try:
                receipt = self.supervisor.launch(launch)
            except AgentProcessSupervisorError as exc:
                from ._agent_process_supervisor import _SupervisorNoStartError

                if isinstance(exc, _SupervisorNoStartError):
                    if not self.supervisor.reject_unstarted_assignment(assignment.assignment_id):
                        raise ManagedLocalError("rejected launch ownership is unresolved") from exc
                    raise ManagedProcessStartError(str(exc)) from exc
                raise
            if (
                receipt.state
                in {SupervisorLaunchState.NOT_ACCEPTED, SupervisorLaunchState.UNKNOWN}
                or not receipt.started
            ):
                raise ManagedLocalError(
                    "supervisor has not established whether a process root was created"
                )
            workspace.mark_process_started(process_id, receipt.process_id)
            return process_id

        state = self.journal.read_state(assignment.assignment_id)
        if state is AssignmentState.ACTIVE:
            if continuing:
                assert self.embedded_recovery is not None
                self.embedded_recovery.grant(
                    delivered, assignment, fence.fencing_token,
                    self.resident_launch_profile.shared_roots, self.authority,
                )
            try:
                self.journal.start_once(
                    assignment.assignment_id,
                    process_id,
                    launch_exact_worker,
                    start_failure=start_failure,
                )
            except ManagedProcessStartError:
                worker_result = cast(
                    StageWorkerResult, self.journal.read_result(assignment.assignment_id)
                )
                if not self.supervisor.reject_unstarted_assignment(assignment.assignment_id):
                    raise ManagedLocalError("failed launch ownership is unresolved")
                child_result = _map_resident_result_identity(
                    worker_result, worker_request=workspace.worker_request(), outputs={}
                )
                atomic_write_bytes(
                    workspace.root / "worker-result.json", _json(child_result.to_dict()).encode(), durability=workspace.durable_files)
                workspace.persist_failed_before_start(
                    child_result, fence=fence.fencing_token, supervisor_rejected=True
                )
                self.journal.record_result(assignment.assignment_id, worker_result.to_dict())
                return worker_result, "granted"
            except Exception:
                self.coordinator.advance(
                    assignment.assignment_id, expected="granted", next_state="unknown"
                )
                raise
        elif state in {AssignmentState.START_INTENT, AssignmentState.START_UNKNOWN}:
            if encoded_launch is None:
                raise ManagedLocalError(
                    "retained start has no supervisor operation and cannot be relaunched"
                )
            receipt = self.supervisor.query_wait(launch)
            if receipt.state is SupervisorLaunchState.NOT_ACCEPTED:
                from ._agent_process_supervisor import _SupervisorNoStartError

                try:
                    receipt = self.supervisor.launch(launch)
                except _SupervisorNoStartError as exc:
                    if not self.supervisor.reject_unstarted_assignment(assignment.assignment_id):
                        raise ManagedLocalError("rejected launch ownership is unresolved") from exc
                    worker_result = start_failure(ManagedProcessStartError(str(exc)))
                    self.journal.record_supervisor_rejected_start(
                        assignment.assignment_id, fence=fence.fencing_token, result=worker_result
                    )
                    child_result = _map_resident_result_identity(
                        worker_result, worker_request=workspace.worker_request(), outputs={}
                    )
                    atomic_write_bytes(
                        workspace.root / "worker-result.json", _json(child_result.to_dict()).encode(), durability=workspace.durable_files)
                    workspace.persist_failed_before_start(
                        child_result, fence=fence.fencing_token, supervisor_rejected=True
                    )
                    return worker_result, self.coordinator.state(assignment.assignment_id)
            if receipt.state is SupervisorLaunchState.UNKNOWN or not receipt.started:
                raise ManagedLocalError("supervisor process outcome is unknown")
            workspace.mark_process_started(process_id, receipt.process_id)
            self.journal.confirm_supervised_start(assignment.assignment_id, process_id)
        elif not _agent_at_or_after(state, AssignmentState.PROCESS_STARTED):
            raise ManagedLocalError("resident assignment cannot join its launch")

        self.authority.confirm_execution_started(assignment.run_uri, fence=fence)
        self.coordinator.confirm_supervised_running(assignment.assignment_id)
        _emit_assignment_event(
            self.journal,
            self.coordinator,
            assignment.assignment_id,
            "process_started",
            {"process_execution_id": process_id, "fence": fence.fencing_token},
        )
        return self.collect_result(launch)

    def collect_result(self, launch: ResidentWorkerLaunch) -> tuple[StageWorkerResult, str]:
        assignment = self.staged.assignment
        worker_request = self.staged.worker_request
        workspace = self.staged.workspace
        worker_result = self.journal.read_result(assignment.assignment_id)
        if worker_result is None:
            if self.execution_started is not None:
                self.execution_started()
            cancellation_seen = False
            while True:
                receipt = self.supervisor.query(launch)
                if receipt.state in {
                    SupervisorLaunchState.EXITED,
                    SupervisorLaunchState.CONTAINED,
                }:
                    break
                if receipt.state is SupervisorLaunchState.UNKNOWN:
                    raise ManagedLocalError("supervisor process outcome is unknown")
                if self.cancellation_requested is not None and self.cancellation_requested():
                    cancellation_seen = True
                    self.supervisor.request_stop_wait(launch)
                if self.suspend_requested is not None and self.suspend_requested():
                    raise _ManagedApplicationSuspended(
                        "local application stopped with supervised work retained"
                    )
                sleep(0.05)
            result_path = workspace.root / "worker-result.json"
            if (
                not result_path.is_file()
                and self.cancellation_requested is not None
                and self.cancellation_requested()
            ):
                cancellation_seen = True
            if not result_path.is_file() and cancellation_seen:
                cancelled = _cancelled_worker_result(workspace.worker_request())
                atomic_write_bytes(result_path, _json(cancelled.to_dict()).encode("utf-8"), durability=workspace.durable_files)
            if not result_path.is_file():
                missing = ManagedLocalError(
                    "resident worker exited without a durable worker result"
                )
                failed = _managed_root_failed_worker_result(
                    workspace.worker_request(),
                    missing,
                    process_exit_code=receipt.exit_code,
                )
                atomic_write_bytes(result_path, _json(failed.to_dict()).encode("utf-8"), durability=workspace.durable_files)
            contained = self.supervisor.contain(launch)
            if contained.state is not SupervisorLaunchState.CONTAINED:
                raise ManagedLocalError("supervisor process-group containment is unknown")
            if (
                contained.worker_result_digest
                != hashlib.sha256(result_path.read_bytes()).hexdigest()
            ):
                raise ManagedLocalError("supervisor result containment proof conflicts")
            child_result = StageWorkerResult.from_dict(json.loads(result_path.read_text()))
            workspace.persist_worker_result(child_result)
            child_result = cast(StageWorkerResult, workspace.worker_result())
            if (
                child_result.status is StageStatus.SUCCEEDED
                and not contained.qualified_success
            ):
                worker_result = _managed_root_failed_worker_result(
                    worker_request,
                    ManagedLocalError(
                        contained.temporary_storage_error
                        or "worker success lacks successful complete owned-group exit"
                    ),
                    process_exit_code=contained.exit_code,
                    worker_result_state="unqualified_success",
                )
                if contained.temporary_storage_error is not None:
                    worker_result = replace(worker_result, executor_metadata={
                        **worker_result.executor_metadata,
                        "temporary_storage_cleanup_error": contained.temporary_storage_error,
                    })
                return worker_result, "running"
            try:
                report = workspace.retain_outputs()
            except _PreparationReportRetentionError as exc:
                worker_result = _managed_root_failed_worker_result(
                    worker_request, exc, process_exit_code=contained.exit_code,
                    worker_result_state="invalid_preparation_report_closure",
                )
                return worker_result, "running"
            except _RemoteTransferLimitError as exc:
                # The exact owned group has exited and its result is contained.
                # An over-limit output is a known publication failure, not unknown work.
                worker_result = _managed_root_failed_worker_result(
                    worker_request,
                    exc,
                    process_exit_code=contained.exit_code,
                    worker_result_state="output_exceeds_byte_bound",
                )
                return worker_result, "running"
            worker_result = _project_resident_result(
                child_result,
                report=report,
                workspace=workspace,
                worker_request=worker_request,
                run_store=self.run_store,
            )
            # The parent owns this fact; never inherit a worker-supplied qualification.
            # Result replay survives clean supervisor continuity rotation.
            metadata = dict(worker_result.executor_metadata)
            metadata.pop("managed_successful_exit", None)
            metadata.pop("managed_backend_success", None)
            metadata.pop("temporary_storage_cleanup_error", None)
            if contained.temporary_storage_error is not None:
                metadata["temporary_storage_cleanup_error"] = contained.temporary_storage_error
            if worker_result.status is StageStatus.SUCCEEDED:
                metadata[
                    "managed_backend_success"
                    if launch.backend_kind == "docker"
                    else "managed_successful_exit"
                ] = contained.qualified_success
            worker_result = replace(worker_result, executor_metadata=metadata)
            self.journal.record_result(assignment.assignment_id, worker_result.to_dict())
        return worker_result, "running"

    def settle(self, fence: ExecutionFence, worker_result: StageWorkerResult, coordinator_expected: str) -> ManagedExecutionReceipt:
        assignment = self.staged.assignment
        commands = self.staged.commands
        delivered = self.staged.delivered
        predecessor = self.staged.predecessor
        continuing = self.staged.continuing
        if (
            worker_result.status is StageStatus.SUCCEEDED
            and worker_result.executor_metadata.get(
                "managed_backend_success"
                if self.resident_launch_profile.container is not None
                and self.resident_launch_profile.container["kind"] == "docker"
                else "managed_successful_exit"
            )
            is not True
        ):
            raise ManagedLocalError(
                "successful result has no successful owned-group exit"
            )
        if self.journal.read_state(assignment.assignment_id) is AssignmentState.RELEASED:
            output_commit: OutputCommit | None = None
            if worker_result.status is StageStatus.SUCCEEDED:
                output_commit = self.authority.record_output_commit(
                    assignment.run_uri,
                    assignment.stage_name,
                    attempt_id=assignment.attempt_id,
                    fencing_token=fence.fencing_token,
                    outputs=worker_result.outputs,
                    supersedes_commit_id=predecessor,
                    assignment_id=assignment.assignment_id,
                )
            _persist_managed_result(self.run_store, worker_result)
            availability_revision = _release_revision(
                journal=self.journal,
                assignment=assignment,
                providers=self.providers,
                operation="released",
                release=self.journal.publish_availability,
            )
            _emit_assignment_event(
                self.journal,
                self.coordinator,
                assignment.assignment_id,
                "provider_released_availability_fresh",
                {"availability_revision": availability_revision},
            )
            if continuing:
                assert self.embedded_recovery is not None
                self.embedded_recovery.retain(delivered, assignment, self.resident_launch_profile.shared_roots)
            if self.coordinator.state(assignment.assignment_id) == "logical_released":
                self.coordinator.advance(
                    assignment.assignment_id,
                    expected="logical_released",
                    next_state="released",
                )
                assignment_milestone("assignment_released", assignment)
            return ManagedExecutionReceipt(
                assignment=assignment,
                fence=fence,
                worker_result=worker_result,
                output_commit=output_commit,
                availability_revision=availability_revision,
            )
        self.journal.record_result(assignment.assignment_id, worker_result.to_dict())
        _emit_assignment_event(
            self.journal,
            self.coordinator,
            assignment.assignment_id,
            "result_and_output_durable",
            {"status": worker_result.status.value},
        )
        output_commit: OutputCommit | None = None
        if worker_result.status is StageStatus.SUCCEEDED:
            output_commit = self.authority.record_output_commit(
                assignment.run_uri,
                assignment.stage_name,
                attempt_id=assignment.attempt_id,
                fencing_token=fence.fencing_token,
                outputs=worker_result.outputs,
                supersedes_commit_id=predecessor,
                assignment_id=assignment.assignment_id,
            )
        else:
            self.authority.record_managed_attempt_terminal(
                assignment.run_uri,
                fence=fence,
                status=worker_result.status,
                reason=_worker_terminal_reason(worker_result),
            )
        _persist_managed_result(self.run_store, worker_result)
        self.coordinator.advance(
            assignment.assignment_id,
            expected=coordinator_expected,
            next_state="terminal",
        )
        self.journal.acknowledge_terminal(assignment.assignment_id)
        assignment_milestone("terminal_acknowledged", assignment)
        self.coordinator.advance(
            assignment.assignment_id,
            expected="terminal",
            next_state="logical_released",
        )
        _emit_assignment_event(
            self.journal,
            self.coordinator,
            assignment.assignment_id,
            "authority_terminal_logical_release",
            {"status": worker_result.status.value},
        )
        for command in commands:
            provider = self.providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            release_command = _operation_command(command, "release")
            released = _provider_call(provider.release, release_command)
            if released.outcome is not ClaimOutcome.RELEASED:
                raise ManagedLocalError("provider release is indeterminate")
        self.journal.mark_providers_released(assignment.assignment_id)
        availability_revision = _release_revision(
            journal=self.journal,
            assignment=assignment,
            providers=self.providers,
            operation="released",
            release=self.journal.publish_availability,
        )
        _emit_assignment_event(
            self.journal,
            self.coordinator,
            assignment.assignment_id,
            "provider_released_availability_fresh",
            {"availability_revision": availability_revision},
        )
        if continuing:
            assert self.embedded_recovery is not None
            self.embedded_recovery.retain(delivered, assignment, self.resident_launch_profile.shared_roots)
        self.coordinator.advance(
            assignment.assignment_id,
            expected="logical_released",
            next_state="released",
        )
        assignment_milestone("assignment_released", assignment)
        return ManagedExecutionReceipt(
            assignment=assignment,
            fence=fence,
            worker_result=worker_result,
            output_commit=output_commit,
            availability_revision=availability_revision,
        )


def _run_reserved_local_assignment(
    staged: _PreparedLocalWorkspace, *, coordinator: SQLiteCoordinatorAssignments,
    authority: PreparedAttemptExecutionAuthority, journal: SQLiteAgentJournal,
    providers: Mapping[str, AgentResourceProvider], run_store: LocalRunStore,
    supervisor: AgentProcessSupervisorClient, resident_launch_profile: ResidentWorkerLaunchProfile,
    cancellation_requested: Callable[[], bool] | None,
    suspend_requested: Callable[[], bool] | None, execution_started: Callable[[], None] | None,
    embedded_recovery: EmbeddedRecovery | None,
) -> ManagedExecutionReceipt:
    """Resume each checkpoint against the durable assignment and its retained owners."""
    execution = _ReservedLocalExecution(
        staged, coordinator, authority, journal, providers, run_store, supervisor,
        resident_launch_profile, cancellation_requested, suspend_requested, execution_started, embedded_recovery,
    )
    assignment_milestone("assignment_received", staged.assignment)
    fence = execution.prepare_grant()
    result, expected = execution.launch_or_resume(fence)
    return execution.settle(fence, result, expected)


def _persist_managed_result(
    run_store: LocalRunStore, result: StageWorkerResult
) -> None:
    """Publish result/diagnostics after fenced acceptance and before release.

    Existing attempt files are repairable projections of the retained terminal
    report. A failed write must propagate so commit replay repairs it before
    release is acknowledged.
    """

    run_store.write_stage_worker_result(
        result.run_uri, result.stage_name, result.to_dict(), attempt=result.attempt
    )
    if result.status is StageStatus.FAILED:
        run_store.write_stage_failure(
            result.run_uri,
            result.stage_name,
            cast(ExecutionFailure, result.failure).to_dict(),
            attempt=result.attempt,
        )


def _require_retained_launch_match(
    retained: ResidentWorkerLaunch, expected: ResidentWorkerLaunch
) -> None:
    if (
        retained.supervisor_id != expected.supervisor_id
        or retained.continuity_epoch != expected.continuity_epoch
        or retained.agent_id != expected.agent_id
        or retained.session_id != expected.session_id
        or retained.assignment_id != expected.assignment_id
        or retained.process_execution_id != expected.process_execution_id
        or retained.execution_fence != expected.execution_fence
        or retained.launch_operation_id != expected.launch_operation_id
        or retained.bundle_digest != expected.bundle_digest
        or retained.workspace_root != expected.workspace_root
        or retained.profile.fingerprint != expected.profile.fingerprint
        or (
            retained.schema_version is not None
            and retained.resource_controls != expected.resource_controls
        )
    ):
        raise ManagedLocalError("retained supervisor launch identity conflicts")


def _map_resident_result_identity(
    result: StageWorkerResult,
    *,
    worker_request: StageWorkerRequest,
    outputs: Mapping[str, ArtifactRef],
) -> StageWorkerResult:
    failure = result.failure
    mapped_failure = (
        None
        if failure is None
        else replace(cast(ExecutionFailure, failure), run_uri=worker_request.run_uri)
    )
    return replace(
        result,
        run_uri=worker_request.run_uri,
        outputs=dict(outputs),
        failure=mapped_failure,
    )


def _project_resident_result(
    result: StageWorkerResult,
    *,
    report: _RemoteExecutionReport,
    workspace: _ResidentAssignmentWorkspace,
    worker_request: StageWorkerRequest,
    run_store: LocalRunStore,
) -> StageWorkerResult:
    if (
        report.assignment_id != workspace.assignment_id
        or report.stage_name != worker_request.stage_name
        or report.attempt != worker_request.attempt
        or report.status is not result.status
    ):
        raise ManagedLocalError("resident result report identity conflicts")
    if report.executor_metadata and report.executor_metadata.get("executor") in (
        "docker",
        "apptainer",
    ):
        metadata = {**result.executor_metadata, **dict(report.executor_metadata or {})}
        failure = cast(ExecutionFailure | None, result.failure)
        result = replace(
            result,
            executor_metadata=metadata,
            failure=None
            if failure is None
            else replace(
                failure, executor_metadata={**failure.executor_metadata, **metadata}
            ),
        )
    from ._shared_publication import publish, selected, workspace_facts
    if selected(workspace.request()) is not None:
        outputs = {}
        if result.status is StageStatus.SUCCEEDED:
            launch, owner = workspace_facts(workspace)
            outputs = publish(workspace.request(), report, launch["profile"]["shared_roots"],
                              agent_id=str(owner["agent_id"]), fence=str(owner["fence"]))
        return _map_resident_result_identity(result, worker_request=worker_request, outputs=outputs)
    from ._preparation_report_transfer import native_role
    if (
        report.status is StageStatus.SUCCEEDED
        and native_role(workspace.request().fingerprint)
        and report.output_kind != "preparation_report"
    ):
        raise ManagedLocalError("native preparation transfer capability is missing")
    artifact_store = LocalArtifactStore(
        run_store.local_artifact_root(worker_request.run_uri)
    )
    retained: list[tuple[_RemoteOutputArtifact, Path]] = []
    aliases: dict[Path, Path] = {}
    target_root = artifact_store.local_stage_dir(worker_request.stage_name)
    source_root = workspace.root / "artifacts" / worker_request.stage_name
    for item in report.outputs:
        data = bytearray()
        offset = 0
        while True:
            chunk, final = workspace.output_chunk(item.transfer_id, offset)
            data.extend(chunk)
            offset += len(chunk)
            if final:
                break
        digest = hashlib.sha256(data).hexdigest()
        if digest != item.digest or len(data) != item.size_bytes:
            raise ManagedLocalError("resident retained output identity conflicts")
        if item.preparation_report_transfer is not None:
            from ._preparation_report_transfer import native_role, publish
            if not native_role(workspace.request().fingerprint):
                raise ManagedLocalError("preparation transfer targets another stage role")
            ref = publish(item, workspace.root / "retained-outputs" / item.logical_name, target_root=target_root)
            return _map_resident_result_identity(result, worker_request=worker_request, outputs={item.logical_name: ref})
        try:
            source = uri_to_path(result.outputs[item.logical_name].uri)
            if source.is_symlink():
                raise ValueError("resident output is a link")
            relative = source.resolve(strict=True).relative_to(
                source_root.resolve(strict=True)
            )
        except (KeyError, OSError, RuntimeError, ValueError) as exc:
            raise ManagedLocalError(
                "resident output is outside its stage artifact directory"
            ) from exc
        target = target_root / relative
        aliases[relative] = workspace.root / "retained-outputs" / item.logical_name
        retained.append((item, target))

    if retained:
        _publish_regular_file_tree(
            source_root=source_root,
            target_root=target_root,
            aliases=aliases,
            field="resident output artifact directory",
        )

    outputs: dict[str, ArtifactRef] = {}
    for item, target in retained:
        if _regular_file_size_and_digest(target) != (item.size_bytes, item.digest):
            raise ManagedLocalError(
                "published resident output conflicts with retained bytes"
            )
        outputs[item.logical_name] = ArtifactRef(
            artifact_id=item.artifact_id,
            uri=target.resolve().as_uri(),
            artifact_type=item.artifact_type,
            codec_key=item.codec_key,
            schema_version=item.artifact_schema_version,
            checksum=f"sha256:{item.digest}",
            fingerprint=item.fingerprint,
            producer_stage=item.producer_stage,
            created_at=item.created_at,
            metadata=item.metadata,
        )
    return _map_resident_result_identity(
        result, worker_request=worker_request, outputs=outputs
    )


def _stage_same_host_input_closure(
    *,
    workspace: _ResidentAssignmentWorkspace,
    artifact: _RemoteArtifact,
    ref: ArtifactRef,
    source: Path,
    run_store: LocalRunStore,
    run_uri: str,
) -> None:
    """Mirror one prior local stage directory beside its isolated primary input."""

    producer_stage = ref.producer_stage
    if producer_stage is None:
        return
    artifact_root = run_store.local_artifact_root(run_uri)
    source_root = LocalArtifactStore(artifact_root).local_stage_dir(producer_stage)
    try:
        source.resolve(strict=True).relative_to(source_root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        # External and source artifacts retain the regular-file-only behavior.
        return
    _publish_regular_file_tree(
        source_root=source_root,
        target_root=workspace.input_root(artifact.logical_name),
        aliases={Path(workspace.input_path(artifact.logical_name).name): source},
        field=f"resident input {artifact.logical_name!r} artifact directory",
    )


def _publish_regular_file_tree(
    *,
    source_root: Path,
    target_root: Path,
    aliases: Mapping[Path, Path],
    field: str,
) -> None:
    """Atomically publish a regular-file tree and replay only exact bytes."""

    sources = _regular_tree_sources(source_root, field=field)
    for relative, source in aliases.items():
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ManagedLocalError(f"{field} alias is unsafe")
        previous = sources.get(relative)
        if previous is not None and not _regular_files_match(previous, source):
            raise ManagedLocalError(f"{field} aliases conflicting bytes")
        sources[relative] = source

    try:
        target_details = target_root.lstat()
    except FileNotFoundError:
        target_details = None
    except OSError as exc:
        raise ManagedLocalError(f"{field} target could not be inspected") from exc
    if target_details is not None:
        if stat.S_ISLNK(target_details.st_mode) or not stat.S_ISDIR(
            target_details.st_mode
        ):
            raise ManagedLocalError(f"{field} target is unsafe")
        if not _regular_tree_matches(sources, target_root, field=field):
            raise ManagedLocalError(f"{field} replay conflicts")
        return

    target_root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{target_root.name}.managed-", dir=target_root.parent)
    )
    try:
        for relative, source in sorted(
            sources.items(), key=lambda item: item[0].as_posix()
        ):
            _copy_regular_file(source, temporary / relative, field=field)
        _fsync_local_tree(temporary)
        try:
            os.replace(temporary, target_root)
        except OSError as exc:
            if not _regular_tree_matches(sources, target_root, field=field):
                raise ManagedLocalError(f"{field} could not be published") from exc
        _fsync_local_directory(target_root.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _regular_tree_sources(source_root: Path, *, field: str) -> dict[Path, Path]:
    try:
        details = source_root.lstat()
        canonical_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise ManagedLocalError(f"{field} source is unavailable") from exc
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or canonical_root != source_root
    ):
        raise ManagedLocalError(f"{field} source is not a canonical directory")

    sources: dict[Path, Path] = {}
    for current, directory_names, file_names in os.walk(
        source_root, topdown=True, followlinks=False
    ):
        directory_names.sort()
        file_names.sort()
        current_path = Path(current)
        for name in directory_names:
            candidate = current_path / name
            candidate_details = candidate.lstat()
            if stat.S_ISLNK(candidate_details.st_mode) or not stat.S_ISDIR(
                candidate_details.st_mode
            ):
                raise ManagedLocalError(f"{field} contains an unsafe directory")
        for name in file_names:
            candidate = current_path / name
            candidate_details = candidate.lstat()
            if stat.S_ISLNK(candidate_details.st_mode) or not stat.S_ISREG(
                candidate_details.st_mode
            ):
                raise ManagedLocalError(f"{field} contains a non-regular file")
            sources[candidate.relative_to(source_root)] = candidate
    return sources


def _copy_regular_file(source: Path, target: Path, *, field: str) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise ManagedLocalError(f"{field} contains an unreadable file") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ManagedLocalError(f"{field} contains a non-regular file")
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with os.fdopen(descriptor, "rb", closefd=False) as source_stream:
            with target.open("xb") as target_stream:
                shutil.copyfileobj(source_stream, target_stream, length=1024 * 1024)
                target_stream.flush()
                os.fsync(target_stream.fileno())
    except OSError as exc:
        raise ManagedLocalError(f"{field} file could not be copied") from exc
    finally:
        os.close(descriptor)


def _regular_files_match(first: Path, second: Path) -> bool:
    try:
        return _regular_file_size_and_digest(first) == _regular_file_size_and_digest(
            second
        )
    except ManagedLocalError:
        return False


def _regular_tree_matches(
    sources: Mapping[Path, Path], target_root: Path, *, field: str
) -> bool:
    try:
        targets = _regular_tree_sources(target_root, field=field)
    except ManagedLocalError:
        return False
    return sources.keys() == targets.keys() and all(
        _regular_files_match(source, targets[relative])
        for relative, source in sources.items()
    )


def _regular_file_size_and_digest(path: Path) -> tuple[int, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ManagedLocalError(
            "resident artifact is not a readable regular file"
        ) from exc
    digest = hashlib.sha256()
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ManagedLocalError("resident artifact is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return details.st_size, digest.hexdigest()
    finally:
        os.close(descriptor)


def _fsync_local_tree(root: Path) -> None:
    directories = [root]
    directories.extend(path for path in root.rglob("*") if path.is_dir())
    for directory in sorted(
        directories, key=lambda path: len(path.parts), reverse=True
    ):
        _fsync_local_directory(directory)


def _fsync_local_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _managed_resource_controls(
    runtime: Mapping[str, object],
    *,
    bindings_prepared: bool = False,
    disposition: ControlDisposition = "requested",
) -> tuple[Mapping[str, PlainData], ...] | None:
    """Describe admitted demand using the actual managed environment owner.

    Legacy handoffs without policy evidence stay unreported. A mechanism is
    attributed only after the provider has supplied the selected binding.
    """

    if any(
        key not in runtime
        for key in ("resources", "resource_policy", "resource_selection")
    ):
        return None
    resources = cast(Mapping[str, object], runtime["resources"])
    raw_entries = cast(Mapping[str, object], resources["entries"])
    entries = {
        kind: ResourceEntry.from_dict(thaw_plain_data(value, path="resource entry"))
        for kind, value in raw_entries.items()
    }
    selection = cast(Mapping[str, Sequence[str]], runtime["resource_selection"])
    policy = ResourcePolicy.from_dict(
        thaw_plain_data(runtime["resource_policy"], path="resource policy")
    )
    return _validated_resource_controls(
        resource_control_records(
            entries=entries,
            policy=policy,
            selection=selection,
            owner="managed_provider",
            mechanisms={
                kind: "provider_environment_binding" for kind in selection["enforce"]
            }
            if bindings_prepared
            else {},
            selected_disposition=disposition,
        )
    )


def _worker_environment(
    profile: ResidentWorkerLaunchProfile,
    workspace: Path,
    commands: Sequence[ClaimCommand],
    providers: Mapping[str, AgentResourceProvider],
    resource_selection: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Construct the complete worker environment without ambient inheritance."""

    environment = {
        "PATH": str(profile.python_executable.parent),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "TMPDIR": str(workspace),
        **dict(profile.environment),
    }
    enforce = None if resource_selection is None else resource_selection.get("enforce")
    if enforce is not None and (
        isinstance(enforce, str)
        or not isinstance(enforce, Sequence)
        or any(not isinstance(kind, str) for kind in enforce)
    ):
        raise ManagedLocalError("worker resource selection is invalid")
    enforced_kinds = None if enforce is None else frozenset(enforce)
    if profile.container is not None and enforced_kinds is not None:
        enforced_kinds = enforced_kinds - {"cpu", "memory"}
    commands_by_kind = {command.claim.resource_kind: command for command in commands}
    if enforced_kinds is not None:
        for kind in sorted(enforced_kinds):
            if kind not in commands_by_kind:
                raise ManagedProcessStartError(
                    f"selected {kind!r} control has no active claim; remove it from enforce, use enforce: [], or select a supporting execution owner"
                )
            if kind not in providers:
                raise ManagedProcessStartError(
                    f"selected {kind!r} control has no supporting provider; remove it from enforce, use enforce: [], or select a supporting execution owner"
                )
    for command in commands:
        if (
            enforced_kinds is not None
            and command.claim.resource_kind not in enforced_kinds
        ):
            continue
        try:
            contribution = dict(
                providers[command.claim.resource_kind].worker_environment(command)
            )
        except Exception as exc:
            raise ManagedProcessStartError(
                f"selected {command.claim.resource_kind!r} control binding failed before worker launch; "
                "check the active provider binding, remove it from enforce, use enforce: [], "
                "or select a supporting execution owner"
            ) from exc
        if enforced_kinds is not None and not contribution:
            raise ManagedProcessStartError(
                f"selected {command.claim.resource_kind!r} control has no provider binding; remove it from enforce, use enforce: [], or select a supporting execution owner"
            )
        if any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in contribution.items()
        ):
            raise ManagedProcessStartError(
                f"selected {command.claim.resource_kind!r} provider supplied an invalid worker environment; "
                "correct the provider binding or remove this control from enforce"
            )
        environment.update(contribution)
    if profile.container is not None and resource_selection is not None:
        from loom.pipeline.executors.containers import ContainerOptionError

        from ._container_worker import build_container_worker
        from ._remote_stage_execution import _ResidentAssignmentWorkspace

        try:
            request = _ResidentAssignmentWorkspace(
                workspace.parent.parent, workspace.name, _allow_initialize=False,
            ).worker_request()
            build_container_worker(
                profile,
                workspace=workspace,
                worker=(str(profile.container["python_executable"]),),
                environment=environment,
                runtime=request.resolved_runtime,
            )
        except (ValueError, ContainerOptionError) as exc:
            raise ManagedProcessStartError(
                "selected container resource control is unavailable"
            ) from exc
    return environment


def _require_worker_assignment_match(
    assignment: ManagedAssignment, request: StageWorkerRequest
) -> None:
    if not isinstance(request, StageWorkerRequest):
        raise ManagedLocalError("worker_request must be a StageWorkerRequest")
    if (
        request.run_uri != assignment.run_uri
        or request.stage_name != assignment.stage_name
        or request.attempt != assignment.attempt
    ):
        raise ManagedLocalError(
            "worker request does not match the exact assigned attempt"
        )


def _emit_assignment_event(
    journal: SQLiteAgentJournal,
    coordinator: SQLiteCoordinatorAssignments,
    assignment_id: str,
    kind: str,
    payload: Mapping[str, PlainData],
) -> None:
    event_id = f"{assignment_id}:{kind}"
    event_payload: dict[str, PlainData] = {"kind": kind, **dict(payload)}
    sequence = journal.append_event(assignment_id, event_id, event_payload)
    coordinator.record_event(assignment_id, sequence, event_id, event_payload)
    journal.acknowledge(assignment_id, sequence)


def _release_revision(
    *,
    journal: SQLiteAgentJournal,
    assignment: ManagedAssignment,
    providers: Mapping[str, AgentResourceProvider],
    operation: str,
    release: Callable[[str, str], AssignmentState],
) -> str:
    """Freshly observe release truth while preserving a committed revision."""

    state = journal.read_state(assignment.assignment_id)
    observed = _fresh_availability_revision(
        assignment=assignment, providers=providers, operation=operation
    )
    if state is AssignmentState.RELEASED:
        saved = journal.read_availability_revision(assignment.assignment_id)
        if saved is None:
            raise ManagedLocalError("released assignment lacks availability revision")
        return saved
    release(assignment.assignment_id, observed)
    return observed


def _fresh_availability_revision(
    *,
    assignment: ManagedAssignment,
    providers: Mapping[str, AgentResourceProvider],
    operation: str,
) -> str:
    observations: list[PlainData] = []
    for resource_kind, provider in sorted(providers.items()):
        result = provider.observe(
            ObserveRequest(
                assignment.agent_id,
                assignment.session_id,
                f"{assignment.assignment_id}:observe:{operation}:{resource_kind}",
            )
        )
        if assignment.claim_id in result.live_claim_ids:
            raise ManagedLocalError(
                "fresh availability still reflects the released assignment as live"
            )
        observations.append(
            {
                "resource_kind": resource_kind,
                "descriptor": provider.descriptor.to_dict(),
                "availability_revision": result.availability_revision,
                "atoms": [atom.to_dict() for atom in result.atoms],
                "live_claim_ids": list(result.live_claim_ids),
            }
        )
    encoded = _json({"observations": observations})
    return "availability-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _worker_terminal_reason(result: StageWorkerResult) -> LifecycleReason:
    if result.status is StageStatus.FAILED:
        failure = result.failure
        return LifecycleReason(
            code="managed_worker_failed",
            message=(
                failure.message if isinstance(failure, ExecutionFailure) else None
            ),
            detail={"attempt": result.attempt},
        )
    if result.status is StageStatus.CANCELLED:
        reason = result.executor_metadata.get("lifecycle_reason")
        if isinstance(reason, Mapping) and reason.get("code") == "early_stop":
            return LifecycleReason.from_dict(reason)
        return LifecycleReason(
            code="managed_worker_cancelled",
            message="managed worker cancelled",
            detail={"attempt": result.attempt},
        )
    raise ManagedLocalError("successful worker result has no failure reason")


def _start_failed_worker_result(
    request: StageWorkerRequest, error: ManagedProcessStartError
) -> StageWorkerResult:
    failed_at = utc_timestamp()
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        failed_at=failed_at,
        executor=request.executor_name,
        failure_type="executor_infrastructure",
        message=str(error),
        exception_type=type(error).__name__,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        details=_capture_exception_details(error, details={"process_created": False}),
    )
    controls = _managed_resource_controls(
        request.resolved_runtime, disposition="unavailable"
    )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.FAILED,
        started_at=failed_at,
        finished_at=failed_at,
        executor_name=request.executor_name,
        failure=failure,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        executor_metadata={
            "request": request.to_safe_metadata(),
            "process_created": False,
            **(
                {"resource_controls": [dict(item) for item in controls]}
                if controls is not None
                else {}
            ),
        },
    )


def _cancelled_worker_result(request: StageWorkerRequest) -> StageWorkerResult:
    cancelled_at = utc_timestamp()
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.CANCELLED,
        started_at=cancelled_at,
        finished_at=cancelled_at,
        executor_name=request.executor_name,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        executor_metadata={
            "request": request.to_safe_metadata(),
            "cancellation_epoch_effective": True,
        },
    )


def _managed_root_failed_worker_result(
    request: StageWorkerRequest,
    error: BaseException,
    *,
    process_exit_code: int | None = None,
    worker_result_state: str = "missing",
) -> StageWorkerResult:
    failed_at = utc_timestamp()
    message = str(error) or type(error).__name__
    observed_exit_code = 1 if process_exit_code is None else process_exit_code
    process_signal = -observed_exit_code if observed_exit_code < 0 else None
    exit_code = None if process_signal is not None else observed_exit_code
    failure = ExecutionFailure(
        schema_version=EXECUTION_FAILURE_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        failed_at=failed_at,
        executor=request.executor_name,
        failure_type="executor_infrastructure",
        message=message,
        exception_type=f"{type(error).__module__}.{type(error).__name__}",
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        exit_code=exit_code,
        signal=process_signal,
        details=_capture_exception_details(
            error,
            details={"process_created": True, "worker_result": worker_result_state},
        ),
    )
    return StageWorkerResult(
        schema_version=STAGE_WORKER_RESULT_SCHEMA_VERSION,
        run_uri=request.run_uri,
        stage_name=request.stage_name,
        attempt=request.attempt,
        status=StageStatus.FAILED,
        started_at=failed_at,
        finished_at=failed_at,
        executor_name=request.executor_name,
        failure=failure,
        stdout_path=request.stdout_path,
        stderr_path=request.stderr_path,
        traceback_path=request.traceback_path,
        exit_code=exit_code,
        signal=process_signal,
        executor_metadata={
            "request": request.to_safe_metadata(),
            "process_created": True,
            "worker_result": worker_result_state,
        },
    )


__all__ = [
    "AgentResourceProvider",
    "AssignmentState",
    "AtomResourceProvider",
    "ClaimCommand",
    "ClaimOutcome",
    "ClaimResult",
    "CpuResourceProvider",
    "ManagedAssignment",
    "ManagedExecutionReceipt",
    "ManagedLocalError",
    "ManagedOfferSnapshot",
    "ManagedProcessStartError",
    "MemoryResourceProvider",
    "GpuResourceProvider",
    "ObserveRequest",
    "ObserveResult",
    "ResourceAvailabilityStatus",
    "SQLiteAgentJournal",
    "SQLiteCoordinatorAssignments",
    "grant_and_start_managed_assignment",
    "run_managed_local_assignment",
]

"""Assignment progression on the existing cooperative outbound client owner.

Delivered and retained assignments converge on one settlement operation: prove
containment, retain and publish results, await authority acknowledgement, release
provider claims, then publish fresh capacity. The native supervisor owns physical
processes; the session and execution journals retain their existing transactions.
These functions add no mutable owner or external-work lane. Client entry points
used by the service and cancellation/release fault consumers remain on the client.
"""
from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any, cast

from loom.serialization import PlainData, freeze_plain_data
from loom.pipeline.executors.containers import ContainerOptionError
from loom.pipeline.execution.models import StageWorkerResult
from loom.pipeline.status import StageStatus
from loom.pipeline.stores.atomic import atomic_write_bytes
from ._managed_local import (
    AgentResourceProvider, AssignmentState, ClaimCommand, ClaimOutcome,
    ManagedAssignment, ManagedLocalError, ManagedProcessStartError,
    ObserveRequest, SQLiteAgentJournal, _cancelled_worker_result,
    _managed_root_failed_worker_result, _managed_resource_controls,
    _start_failed_worker_result, _worker_environment,
)
from .agent_sessions import AgentSession
from ._remote_stage_execution import _ResidentAssignmentBundle, _ResidentAssignmentWorkspace
from ._agent_process_supervisor import (
    ResidentWorkerLaunch, SupervisorReceipt, SupervisorLaunchState,
    _launch_from_value, _launch_value,
)
from ._agent_session_journal import _canonical_json
from ._agent_session_protocol import _raise_if_application_suspended
from ._agent_progress import _Progress, _steps, _external, _delay, _serialized
from .errors import QueueConflictError, QueueError

if TYPE_CHECKING:
    from .agent_session_transport import LocalDaemonAgentHttpClient


def _execute_delivered_assignment(
    self: LocalDaemonAgentHttpClient,
    session_id: str,
    request: _ResidentAssignmentBundle,
    *,
    suspend_requested: Callable[[], bool] | None = None,
) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
    """Drive one already durable delivery through the native input/grant path."""
    profile = self._profile_for_descriptor(request.profile)
    if profile is None:
        raise QueueConflictError(
            "delivered assignment has no exact resident profile"
        )
    session = self._require_journal().session(session_id)
    workspace = _ResidentAssignmentWorkspace(
        cast(Path, self._config.agent_root), request.assignment_id
    )
    (yield from _external("bulk", workspace.persist_request, request, profile))
    self._require_journal().retain_assignment_reference(
        session_id, request.assignment_id
    )
    providers, execution_journal = self._runtime_owners(session)
    assignment = ManagedAssignment(
        assignment_id=request.assignment_id,
        run_uri=f"loom-agent:{request.assignment_id}",
        stage_work_id=request.stage_work_id,
        stage_name=request.stage_name,
        attempt=request.attempt,
        attempt_id=request.attempt_id,
        agent_id=session.agent_id,
        session_id=session.session_id,
        offer_id=request.offer_id,
        claim_id=request.claim_id,
    )
    commands = tuple(
        ClaimCommand(
            assignment,
            f"{request.assignment_id}:prepare:{index}",
            claim,
            {
                descriptor.kind: descriptor
                for descriptor in request.provider_descriptors
            }[claim.resource_kind],
        )
        for index, claim in enumerate(request.claims)
    )
    execution_journal.persist_request(assignment, request.to_dict())
    cancelled = (yield from _steps(self._cancel_pregrant_if_requested,
        session,
        request.assignment_id,
        assignment,
        commands,
        providers,
        execution_journal,
    ))
    if cancelled is not None:
        return cancelled

    authorization = (yield from _steps(self._fresh_transfer_authorization,
        session_id=session_id,
        assignment_id=request.assignment_id,
        expected_revision=0,
    ))
    authorization_id = cast(str, authorization["authorization_id"])
    authorization_revision = cast(int, authorization["revision"])
    for item in request.inputs:
        from loom.pipeline.stores.shared_artifacts import binding
        if binding(item.metadata) is not None:
            continue
        offset = 0
        while True:
            response, authorization_id, authorization_revision = (
                (yield from _steps(self._authorized_transfer_call,
                    session_id=session_id,
                    assignment_id=request.assignment_id,
                    authorization_id=authorization_id,
                    authorization_revision=authorization_revision,
                    operation=lambda current_id, current_revision: (
                        _steps(self.read_input_chunk,
                            session_id,
                            request.assignment_id,
                            item.transfer_id,
                            offset=offset,
                            authorization_id=current_id,
                            authorization_revision=current_revision,
                        )
                    ),
                ))
            )
            data, next_offset, final = cast(tuple[bytes, int, bool], response)
            (yield from _external("bulk", workspace.stage_input_chunk,
                item.transfer_id,
                offset,
                data,
                final=final,
            ))
            _raise_if_application_suspended(suspend_requested)
            offset = next_offset
            (yield from _steps(self._maintain_resource_offer))
            if final:
                break
    if execution_journal.read_grant_fence(assignment.assignment_id) is None:
        (yield from _external("bulk", workspace.accept))
    prepared = yield from _steps(
        execution_journal.prepare_composite, assignment, commands, providers
    )
    self._next_resource_maintenance = 0
    if prepared is AssignmentState.DECLINED:
        return (yield from _steps(_decline_pregrant_assignment, self,
            session, assignment, commands, providers, execution_journal))
    if prepared not in {
        AssignmentState.PREPARED,
        AssignmentState.ACCEPTED,
        AssignmentState.GRANTED,
        AssignmentState.ACTIVE,
        AssignmentState.PROCESS_STARTED,
        AssignmentState.RESULT_DURABLE,
    }:
        raise QueueConflictError("remote physical admission is indeterminate")
    execution_journal.accept(assignment.assignment_id)
    workspace.append_event(
        f"{request.assignment_id}:request-inputs-durable",
        {"kind": "request_and_inputs_durable"},
    )
    cancelled = (yield from _steps(self._cancel_pregrant_if_requested,
        session,
        request.assignment_id,
        assignment,
        commands,
        providers,
        execution_journal,
    ))
    if cancelled is not None:
        return cancelled
    request_json = json.dumps(
        request.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    try:
        grant = cast(
            Mapping[str, PlainData],
            (yield from _steps(self._assignment_call,
                session_id,
                request.assignment_id,
                lambda: _steps(self.accept_assignment,
                    session_id,
                    request.assignment_id,
                    request_digest=hashlib.sha256(
                        request_json.encode()
                    ).hexdigest(),
                ),
            )),
        )
    except QueueConflictError as conflict:
        deadline = monotonic() + 5
        while monotonic() < deadline:
            cancelled = (yield from _steps(self._cancel_pregrant_if_requested,
                session,
                request.assignment_id,
                assignment,
                commands,
                providers,
                execution_journal,
            ))
            if cancelled is not None:
                return cancelled
            (yield from _delay(0.05))
        raise conflict
    fence = cast(str, grant["fence"])
    execution_journal.grant(assignment.assignment_id, fence)
    workspace.grant(fence)
    activated = execution_journal.activate_composite(
        assignment.assignment_id, commands, providers
    )
    if activated not in {
        AssignmentState.ACTIVE,
        AssignmentState.PROCESS_STARTED,
        AssignmentState.RESULT_DURABLE,
    }:
        raise QueueConflictError("remote physical activation is indeterminate")

    execution_id = f"{request.assignment_id}:root"
    supervisor = self._supervisor
    if supervisor is None:
        raise QueueConflictError("remote resident execution has no supervisor")
    launch: ResidentWorkerLaunch | None = None
    result_path = workspace.root / "worker-result.json"
    completed_before_start = False
    if execution_journal.read_state(assignment.assignment_id) in {
        AssignmentState.ACTIVE,
    }:

        def start_supervisor_launch() -> Generator[_Progress, Any, str]:
            nonlocal launch
            while self._epoch_reconciliation_pending:
                _raise_if_application_suspended(suspend_requested)
                yield from _delay(0.01)
            try:
                launch = build_supervisor_launch()
            except (ValueError, QueueError, OSError, ContainerOptionError) as exc:
                # No supervisor call has occurred: construction failure is
                # definite no-start evidence, not an uncertain process.
                raise ManagedProcessStartError(str(exc)) from exc
            workspace.persist_supervisor_launch(
                json.dumps(
                    _launch_value(launch), sort_keys=True, separators=(",", ":")
                )
            )
            from ._agent_process_supervisor import _SupervisorNoStartError

            try:
                receipt = (yield from _external("bulk", supervisor.launch, launch))
            except _SupervisorNoStartError as exc:
                if not (yield from _external("control", supervisor.reject_unstarted_assignment,
                                            request.assignment_id)):
                    raise QueueConflictError("rejected launch ownership is unresolved") from exc
                raise ManagedProcessStartError(str(exc)) from exc
            self._observe_supervisor_ownership(receipt)
            if (
                receipt.state
                in {
                    SupervisorLaunchState.NOT_ACCEPTED,
                    SupervisorLaunchState.UNKNOWN,
                }
                or not receipt.started
            ):
                raise QueueConflictError(
                    "remote supervisor has not established whether a process root was created"
                )
            workspace.mark_process_started(execution_id, receipt.process_id)
            return execution_id

        def build_supervisor_launch() -> ResidentWorkerLaunch:
            environment = _worker_environment(
                profile.launch_profile,
                workspace.root,
                commands,
                providers,
                cast(
                    Mapping[str, object],
                    request.resolved_runtime.get("resource_selection"),
                ),
            )
            candidate = ResidentWorkerLaunch(
                supervisor_id=supervisor.supervisor_id,
                continuity_epoch=supervisor.continuity_epoch,
                agent_id=supervisor.agent_id,
                session_id=session.session_id,
                assignment_id=request.assignment_id,
                process_execution_id=execution_id,
                execution_fence=fence,
                launch_operation_id=f"{request.assignment_id}:launch:{fence}",
                bundle_digest=hashlib.sha256(
                    _canonical_json(request.to_dict()).encode("utf-8")
                ).hexdigest(),
                workspace_root=workspace.root,
                profile=profile.launch_profile,
                environment=environment,
                resource_controls=_managed_resource_controls(
                    request.resolved_runtime, bindings_prepared=True
                ),
            )
            if candidate.profile.container is not None:
                from loom.pipeline.runtime._resource_controls import _validated_resource_controls

                candidate = replace(candidate, resource_controls=_validated_resource_controls(
                    candidate.container_command.metadata.get("resource_controls")
                ))
            return candidate

        with self._control_lock:
            _raise_if_application_suspended(suspend_requested)
            permitted = cast(
                bool,
                (yield from _steps(self._assignment_call,
                    session_id,
                    request.assignment_id,
                    lambda: _steps(self.start_permit,
                        session_id, request.assignment_id, fence=fence
                    ),
                )),
            )
            if permitted and request.assignment_id in self._received_cancellations:
                rejected = yield from _external("control", supervisor.reject_unstarted_assignment, request.assignment_id)
                if not rejected:
                    raise QueueConflictError("cancelled assignment start ownership is unresolved")
                permitted = False
            if not permitted:
                result = _cancelled_worker_result(workspace.worker_request())
                atomic_write_bytes(
                    result_path,
                    json.dumps(
                        result.to_dict(),
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode(),
                )
                workspace.persist_cancelled_before_start(result)
                execution_journal.record_cancelled_before_start(
                    assignment.assignment_id, result.to_dict()
                )
                completed_before_start = True
            else:
                try:
                    yield from _start_once_steps(
                        execution_journal,
                        assignment.assignment_id,
                        execution_id,
                        start_supervisor_launch,
                        start_failure=lambda error: _start_failed_worker_result(
                            workspace.worker_request(), error
                        ),
                    )
                except ManagedProcessStartError:
                    result = cast(
                        StageWorkerResult,
                        execution_journal.read_result(assignment.assignment_id),
                    )
                    atomic_write_bytes(
                        result_path,
                        json.dumps(
                            result.to_dict(),
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode(),
                    )
                    execution_journal.require_failed_before_start(
                        assignment.assignment_id, fence=fence
                    )
                    workspace.persist_failed_before_start(
                        result, fence=fence, supervisor_rejected=launch is not None
                    )
                    execution_journal.record_result(
                        assignment.assignment_id, result.to_dict()
                    )
                    completed_before_start = True
                else:
                    workspace.append_event(
                        f"{request.assignment_id}:agent-process-started",
                        {"kind": "process_started"},
                    )
                    (yield from _steps(self._assignment_call,
                        session_id,
                        request.assignment_id,
                        lambda: _steps(self.confirm_started,
                            session_id,
                            request.assignment_id,
                            fence=fence,
                            process_execution_id=execution_id,
                        ),
                    ))
    if not completed_before_start:
        (yield from _steps(self._flush_workspace_events, session_id, workspace))
    if launch is None:
        retained_launch = workspace.supervisor_launch_json()
        if retained_launch is not None:
            launch = _launch_from_value(json.loads(retained_launch))
    if launch is not None and not completed_before_start:
        while True:
            _raise_if_application_suspended(suspend_requested)
            receipt = (yield from _external("control", supervisor.query, launch))
            self._observe_supervisor_ownership(receipt)
            if receipt.state in {
                SupervisorLaunchState.EXITED,
                SupervisorLaunchState.CONTAINED,
            }:
                break
            if receipt.state is SupervisorLaunchState.UNKNOWN:
                raise QueueConflictError("remote supervisor continuity is unknown")
            (yield from _steps(self.poll_assignment_control, session_id))
            (yield from _steps(self._maintain_resource_offer))
            (yield from _delay(0.05))
        if not (yield from _steps(_settle_supervised_worker_result, self, workspace, launch, receipt)):
            raise QueueConflictError("remote process group containment is unknown")
    elif not result_path.is_file():
        raise QueueConflictError(
            "remote process outcome is unknown and cannot be relaunched"
        )
    return (yield from _steps(_complete_remote_result_and_release, self,
        session,
        request,
        workspace,
        assignment,
        commands,
        providers,
        execution_journal,
        fence=fence,
        authorization_revision=authorization_revision,
        persist_result=not completed_before_start,
        result_path_label="remote execution completion",
        # A proven no-start outcome completes without a supervisor to join.
        suspend_requested=suspend_requested if launch is not None else None,
    ))



def _resume_retained_assignments(
    self: LocalDaemonAgentHttpClient, references, *, suspend_requested=None
):
    """Shared exact recovery transitions; the service gives each ID a view."""
    _raise_if_application_suspended(suspend_requested)
    journal = self._require_journal()
    execution_journal = self._execution_journal
    supervisor = self._supervisor
    if (
        not self._config.resident_profiles
        and not journal.unresolved_assignment_references()
    ):
        self._restart_with_retained_work = False
        return ()
    if execution_journal is None or supervisor is None:
        raise QueueConflictError("remote restart has no supervisor journal")
    completed: list[Mapping[str, PlainData]] = []
    for session_id, assignment_id in references:
        _raise_if_application_suspended(suspend_requested)
        session = journal.session(session_id)
        workspace = _ResidentAssignmentWorkspace(
            cast(Path, self._config.agent_root), assignment_id
        )
        raw_delivery = journal.delivery_request(session_id, assignment_id)
        if not workspace.has_request():
            if raw_delivery is None:
                raise QueueConflictError("retained assignment delivery is unavailable")
            (yield from _steps(self._assignment_call, session_id, assignment_id, lambda: _steps(self.poll_assignment_control, session_id)))
            if (session_id, assignment_id) not in journal.unresolved_assignment_references():
                continue
            request = (yield from _steps(self._resolve_delivery, session_id, raw_delivery))
            completed.append((yield from _steps(self._execute_delivered_assignment, session_id, request, suspend_requested=suspend_requested)))
            continue
        request = workspace.request()
        if raw_delivery is not None:
            from ._shared_assignment import reference, verify_bundle
            ref = reference(raw_delivery)
            if ref is not None:
                verify_bundle(ref, request, session_id=session_id)
        request.validate_remote_transport()
        profile = self._profile_for_descriptor(request.profile)
        if profile is None:
            raise QueueConflictError("retained assignment has no resident profile")
        assignment = ManagedAssignment(
            assignment_id=request.assignment_id,
            run_uri=f"loom-agent:{request.assignment_id}",
            stage_work_id=request.stage_work_id,
            stage_name=request.stage_name,
            attempt=request.attempt,
            attempt_id=request.attempt_id,
            agent_id=session.agent_id,
            session_id=session.session_id,
            offer_id=request.offer_id,
            claim_id=request.claim_id,
        )
        # Workspace publication may have committed immediately before the
        # application stopped, before the execution journal saw the bundle.
        execution_journal.persist_request(assignment, request.to_dict())
        providers, _ = self._runtime_owners(session)
        if execution_journal.read_state(assignment_id) is AssignmentState.RELEASED:
            # The release reply may be lost after coordinator acceptance.
            # Replay its retained proof, not an already committed output manifest.
            retained_fence = execution_journal.read_grant_fence(assignment_id)
            revision = cast(str, execution_journal.read_availability_revision(assignment_id))
            if retained_fence is None:
                released = yield from _steps(
                    self.decline_assignment, session_id, assignment_id,
                    availability_revision=revision,
                    reason_code=execution_journal.read_decline_reason(assignment_id),
                )
            else:
                released = yield from _steps(
                    self.release_assignment, session_id, assignment_id,
                    fence=retained_fence, availability_revision=revision,
                )
            completed.append(freeze_plain_data({
                "result": "assignment", "assignment_id": assignment_id,
                "state": "RELEASED", "session": released.value(),
            }, path="remote release restart completion"))
            continue
        launch_json = workspace.supervisor_launch_json()
        if (
            launch_json is None
            and execution_journal.read_state(assignment_id)
            in {
                AssignmentState.REQUEST_DURABLE,
                AssignmentState.PREPARED,
                AssignmentState.ACCEPTED,
                AssignmentState.GRANTED,
                AssignmentState.ACTIVE,
            }
        ):
            # Continue this exact delivery. The service separately proves
            # the whole inventory before admission; commands may not yet
            # exist when the interruption was during input.
            completed.append(
                (yield from _steps(self._execute_delivered_assignment,
                    session_id, request, suspend_requested=suspend_requested
                ))
            )
            continue
        commands = execution_journal.assignment_claim_commands(assignment_id)
        if launch_json is None or execution_journal.definitive_start_failed(assignment_id):
            retained_fence = execution_journal.read_grant_fence(assignment_id)
            if launch_json is not None and not (yield from _external(
                "control", supervisor.reject_unstarted_assignment, assignment_id
            )):
                raise QueueConflictError("failed launch ownership is unresolved")
            with self._control_lock:
                if (
                    retained_fence is not None
                    and workspace.supervisor_launch_json() is None
                    and execution_journal.read_state(assignment_id) in {
                        AssignmentState.START_INTENT, AssignmentState.START_UNKNOWN
                    }
                ):
                    # The supervisor atomically checks historical acceptance
                    # and fences all future launches. Absence alone is not proof.
                    if not (yield from _external("bulk", supervisor.reject_unstarted_assignment, assignment_id)):
                        continue
                    execution_journal.record_supervisor_rejected_start(
                        assignment_id, fence=retained_fence,
                        result=_start_failed_worker_result(
                            workspace.worker_request(),
                            ManagedProcessStartError(
                                "supervisor durably rejected unstarted assignment during recovery"
                            ),
                        ),
                    )
            retained_result = (
                execution_journal.read_result(assignment_id)
                if execution_journal.definitive_start_failed(assignment_id)
                else workspace.worker_result()
            )
            if retained_fence is None:
                continue
            if (
                retained_result is None
                and execution_journal.read_state(assignment_id)
                is AssignmentState.START_FAILED
            ):
                result_path = workspace.root / "worker-result.json"
                if result_path.is_file():
                    retained_result = StageWorkerResult.from_dict(
                        json.loads(result_path.read_text())
                    )
            if (
                retained_result is not None
                and retained_result.status is StageStatus.FAILED
            ):
                execution_journal.require_failed_before_start(
                    assignment_id, fence=retained_fence
                )
                result_path = workspace.root / "worker-result.json"
                if not result_path.is_file():
                    atomic_write_bytes(
                        result_path,
                        _canonical_json(retained_result.to_dict()).encode(),
                    )
                workspace.persist_failed_before_start(
                    retained_result, fence=retained_fence,
                    supervisor_rejected=launch_json is not None,
                )
                execution_journal.record_result(
                    assignment_id, retained_result.to_dict()
                )
            elif (
                retained_result is not None
                and retained_result.status is StageStatus.CANCELLED
            ):
                if execution_journal.read_result(assignment_id) != retained_result:
                    continue
            else:
                # Absence of a launch alone cannot establish safe release.
                continue
            completed.append(
                (yield from _steps(_complete_remote_result_and_release, self,
                    session,
                    request,
                    workspace,
                    assignment,
                    commands,
                    providers,
                    execution_journal,
                    fence=retained_fence,
                    authorization_revision=0,
                    persist_result=False,
                    result_path_label="remote no-start restart completion",
                    suspend_requested=suspend_requested,
                ))
            )
            continue
        launch = _launch_from_value(json.loads(launch_json))
        receipt = (yield from _external("bulk", supervisor.query_wait, launch))
        self._observe_supervisor_ownership(receipt)
        if (
            launch.continuity_epoch in supervisor.reboot_generations
            and receipt.exit_code is None
        ):
            # A reboot proves containment, never a scientific terminal result.
            # Keep capacity withheld until the operator's guarded close wins.
            (yield from _steps(self._assignment_call,
                session_id,
                assignment_id,
                lambda: _steps(self.poll_assignment_control, session_id),
            ))
            ready = (yield from _steps(self._assignment_call,
                session_id,
                assignment_id,
                lambda: _steps(self._call,
                    "recovery_release_ready",
                    {
                        "session_id": session_id,
                        "assignment_id": assignment_id,
                        "fence": launch.execution_fence,
                    },
                ),
            ))
            if ready.get("ready") is True:
                (yield from _steps(self._assignment_call,
                    session_id,
                    assignment_id,
                    lambda: _steps(self.release_contained_assignment,
                        session_id,
                        assignment_id,
                        fence=launch.execution_fence,
                    ),
                ))
            continue
        if receipt.state is SupervisorLaunchState.NOT_ACCEPTED:
            # The complete exact operation was journaled before the service
            # call. Submitting that operation is replay, never relaunch.
            while self._epoch_reconciliation_pending:
                _raise_if_application_suspended(suspend_requested)
                yield from _delay(0.01)
            from ._agent_process_supervisor import _SupervisorNoStartError

            try:
                receipt = (yield from _external("bulk", supervisor.launch, launch))
            except _SupervisorNoStartError as exc:
                if not (yield from _external("control", supervisor.reject_unstarted_assignment,
                                            assignment_id)):
                    raise QueueConflictError("rejected launch ownership is unresolved") from exc
                execution_journal.record_supervisor_rejected_start(
                    assignment_id, fence=launch.execution_fence,
                    result=_start_failed_worker_result(
                        workspace.worker_request(), ManagedProcessStartError(str(exc))
                    ),
                )
                completed.extend((yield from _steps(
                    self._resume_retained_assignments, ((session_id, assignment_id),),
                    suspend_requested=suspend_requested,
                )))
                continue
            self._observe_supervisor_ownership(receipt)
        if receipt.state is SupervisorLaunchState.UNKNOWN:
            continue
        needs_start_join = execution_journal.read_state(assignment_id) in {
            AssignmentState.START_INTENT,
            AssignmentState.START_UNKNOWN,
            AssignmentState.PROCESS_STARTED,
        }
        if needs_start_join and receipt.started:
            (yield from _steps(_join_retained_supervised_start, self,
                session,
                request,
                workspace,
                execution_journal,
                launch,
                receipt.process_id,
            ))
            needs_start_join = False
        while receipt.state in {
            SupervisorLaunchState.STARTING,
            SupervisorLaunchState.RUNNING,
        }:
            _raise_if_application_suspended(suspend_requested)
            (yield from _steps(self.poll_assignment_control, session_id))
            (yield from _delay(0.05))
            receipt = (yield from _external("control", supervisor.query, launch))
            self._observe_supervisor_ownership(receipt)
            if needs_start_join and receipt.started:
                (yield from _steps(_join_retained_supervised_start, self,
                    session,
                    request,
                    workspace,
                    execution_journal,
                    launch,
                    receipt.process_id,
                ))
                needs_start_join = False
            if receipt.state is SupervisorLaunchState.UNKNOWN:
                break
        if receipt.state is SupervisorLaunchState.UNKNOWN:
            continue
        if not (yield from _steps(_settle_supervised_worker_result, self, workspace, launch, receipt)):
            continue
        completed.append(
            (yield from _steps(_complete_remote_result_and_release, self,
                session,
                request,
                workspace,
                assignment,
                commands,
                providers,
                execution_journal,
                fence=launch.execution_fence,
                authorization_revision=0,
                persist_result=True,
                result_path_label="remote restart completion",
                suspend_requested=suspend_requested,
            ))
        )
    if not self._service_progress:
        self._restart_with_retained_work = self._has_retained_agent_work()
    return tuple(completed)



def _settle_supervised_worker_result(
    self: LocalDaemonAgentHttpClient,
    workspace: _ResidentAssignmentWorkspace,
    launch: ResidentWorkerLaunch,
    receipt: SupervisorReceipt,
) -> Generator[_Progress, Any, bool]:
    """Close a known root exit only with continuous group/result evidence."""

    if receipt.state not in {
        SupervisorLaunchState.EXITED,
        SupervisorLaunchState.CONTAINED,
    }:
        return False
    supervisor = self._supervisor
    if supervisor is None:
        raise QueueConflictError("remote completion has no process owner")
    if workspace.assignment_id in self._received_cancellations:
        yield from _steps(self.poll_assignment_control, launch.session_id)
    result_path = workspace.root / "worker-result.json"
    if not result_path.is_file():
        if workspace.assignment_id in self._cancelled_assignments:
            self._record_contained_cancellation(workspace)
        else:
            result = _managed_root_failed_worker_result(
                workspace.worker_request(),
                ManagedLocalError(
                    "resident worker exited without a durable worker result"
                ),
                process_exit_code=receipt.exit_code,
            )
            atomic_write_bytes(
                result_path,
                json.dumps(
                    result.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode(),
            )
    contained = (yield from _external("bulk", supervisor.contain, launch))
    self._observe_supervisor_ownership(contained)
    if contained.state is not SupervisorLaunchState.CONTAINED:
        return False
    if (
        contained.worker_result_digest
        != hashlib.sha256(result_path.read_bytes()).hexdigest()
    ):
        raise QueueConflictError(
            "remote supervisor result evidence does not match the workspace"
        )
    return True



def _join_retained_supervised_start(
    self: LocalDaemonAgentHttpClient,
    session: AgentSession,
    request: _ResidentAssignmentBundle,
    workspace: _ResidentAssignmentWorkspace,
    execution_journal: SQLiteAgentJournal,
    launch: ResidentWorkerLaunch,
    process_id: int | None,
) -> Generator[_Progress, Any, None]:
    """Join one exact accepted launch across the application crash barrier."""

    workspace.mark_process_started(launch.process_execution_id, process_id)
    execution_journal.confirm_supervised_start(
        request.assignment_id, launch.process_execution_id
    )
    workspace.append_event(
        f"{request.assignment_id}:agent-process-started",
        {"kind": "process_started"},
    )
    (yield from _steps(self._assignment_call,
        session.session_id,
        request.assignment_id,
        lambda: _steps(self.confirm_started,
            session.session_id,
            request.assignment_id,
            fence=launch.execution_fence,
            process_execution_id=launch.process_execution_id,
        ),
    ))
    (yield from _steps(self._flush_workspace_events, session.session_id, workspace))



def _complete_remote_result_and_release(
    self: LocalDaemonAgentHttpClient,
    session: AgentSession,
    request: _ResidentAssignmentBundle,
    workspace: _ResidentAssignmentWorkspace,
    assignment: ManagedAssignment,
    commands: tuple[ClaimCommand, ...],
    providers: Mapping[str, AgentResourceProvider],
    execution_journal: SQLiteAgentJournal,
    *,
    fence: str,
    authorization_revision: int,
    persist_result: bool,
    result_path_label: str,
    suspend_requested: Callable[[], bool] | None = None,
) -> Generator[_Progress, Any, Mapping[str, PlainData]]:
    """Own normal and restart result/output/outbox completion ordering."""

    yield from _steps(self._assignment_call, session.session_id, request.assignment_id,
                      lambda: _steps(self.poll_assignment_control, session.session_id))
    result_path = workspace.root / "worker-result.json"
    result = (
        StageWorkerResult.from_dict(json.loads(result_path.read_text()))
        if persist_result
        else workspace.worker_result()
    )
    if result is None:
        raise QueueConflictError("remote completion has no durable result")
    completed_before_start = (
        result.status in {StageStatus.CANCELLED, StageStatus.FAILED}
        and (workspace.supervisor_launch_json() is None
             or execution_journal.definitive_start_failed(request.assignment_id))
    )
    if completed_before_start and result.status is StageStatus.FAILED:
        execution_journal.require_failed_before_start(
            request.assignment_id, fence=fence
        )
        retained_launch = workspace.supervisor_launch_json() is not None
        if retained_launch and (
            self._supervisor is None or not (yield from _external(
                "control", self._supervisor.reject_unstarted_assignment, request.assignment_id
            ))
        ):
            raise QueueConflictError("failed launch ownership is unresolved")
        workspace.persist_failed_before_start(
            result, fence=fence, supervisor_rejected=retained_launch
        )
    if persist_result:
        retained = workspace.worker_result()
        if retained is not None:
            result = retained
        elif workspace.supervisor_launch_json() is not None:
            launch = _launch_from_value(
                json.loads(cast(str, workspace.supervisor_launch_json()))
            )
            if self._supervisor is None:
                raise QueueConflictError("remote completion lost its supervisor")
            evidence = (yield from _external("bulk", self._supervisor.query_wait, launch))
            self._observe_supervisor_ownership(evidence)
            if evidence.state is not SupervisorLaunchState.CONTAINED:
                raise QueueConflictError("remote completion lacks containment")
            if (
                result.status is StageStatus.SUCCEEDED
                and not evidence.qualified_success
            ):
                result = _managed_root_failed_worker_result(
                    workspace.worker_request(),
                    ManagedLocalError("worker backend success is unqualified"),
                    process_exit_code=evidence.exit_code,
                )
            metadata = dict(result.executor_metadata)
            metadata.pop("managed_successful_exit", None)
            metadata.pop("managed_backend_success", None)
            if result.status is StageStatus.SUCCEEDED:
                metadata[
                    "managed_backend_success"
                    if launch.backend_kind == "docker"
                    else "managed_successful_exit"
                ] = evidence.qualified_success
            result = replace(result, executor_metadata=metadata)
        (yield from _external("bulk", workspace.persist_worker_result, result))
        result = cast(StageWorkerResult, workspace.worker_result())
        execution_journal.record_result(assignment.assignment_id, result.to_dict())
    report = (yield from _external("bulk", workspace.retain_outputs))
    workspace.append_event(
        f"{request.assignment_id}:result-output-durable",
        {"kind": "result_and_output_durable", "status": report.status.value},
    )
    if not completed_before_start:
        (yield from _steps(self._flush_workspace_events, session.session_id, workspace))
    authorization = (yield from _steps(self._fresh_transfer_authorization,
        session_id=session.session_id,
        assignment_id=request.assignment_id,
        expected_revision=authorization_revision,
    ))
    authorization_id = cast(str, authorization["authorization_id"])
    authorization_revision = cast(int, authorization["revision"])
    _, authorization_id, authorization_revision = (yield from _steps(self._authorized_transfer_call,
        session_id=session.session_id,
        assignment_id=request.assignment_id,
        authorization_id=authorization_id,
        authorization_revision=authorization_revision,
        operation=lambda current_id, current_revision: _steps(self.declare_outputs,
            session.session_id,
            request.assignment_id,
            fence=fence,
            authorization_id=current_id,
            authorization_revision=current_revision,
            report=report,
        ),
    ))
    for item in report.outputs:
        from loom.pipeline.stores.shared_artifacts import binding
        if binding(item.metadata) is not None:
            continue
        offset = 0
        while True:
            _raise_if_application_suspended(suspend_requested)
            data, final = (yield from _external("bulk", workspace.output_chunk, item.transfer_id, offset))
            response, authorization_id, authorization_revision = (
                (yield from _steps(self._authorized_transfer_call,
                    session_id=session.session_id,
                    assignment_id=request.assignment_id,
                    authorization_id=authorization_id,
                    authorization_revision=authorization_revision,
                    operation=lambda current_id, current_revision: (
                        _steps(self.upload_output_chunk,
                            session.session_id,
                            request.assignment_id,
                            item.transfer_id,
                            offset=offset,
                            data=data,
                            final=final,
                            authorization_id=current_id,
                            authorization_revision=current_revision,
                        )
                    ),
                ))
            )
            offset = cast(
                int, cast(Mapping[str, PlainData], response)["received_bytes"]
            )
            (yield from _steps(self._maintain_resource_offer))
            if final:
                break
    _raise_if_application_suspended(suspend_requested)
    yield from _steps(self.poll_assignment_control, session.session_id)
    (yield from _steps(self._assignment_call,
        session.session_id,
        request.assignment_id,
        lambda: _steps(self.commit_result,
            session.session_id, request.assignment_id, fence=fence
        ),
    ))
    if completed_before_start:
        (yield from _steps(self._flush_workspace_events, session.session_id, workspace))
    released_session = yield from _steps(
        _release_completed_assignment, self, session, assignment, commands,
        providers, execution_journal, fence=fence,
    )
    self._next_resource_maintenance = 0
    self._cancelled_assignments.discard(request.assignment_id)
    self._received_cancellations.discard(request.assignment_id)
    self._joined_starts.discard(request.assignment_id)
    return freeze_plain_data(
        {
            "result": "assignment",
            "assignment_id": request.assignment_id,
            "state": "RELEASED",
            "session": released_session.value(),
        },
        path=result_path_label,
    )



@_serialized("_mutation_gate")
def _release_completed_assignment(
    self: LocalDaemonAgentHttpClient, session, assignment, commands, providers, execution_journal, *, fence
):
    next_revision = self._release_provider_claims(
        session,
        assignment,
        commands,
        providers,
        execution_journal,
    )
    released_session = cast(
        AgentSession,
        (yield from _steps(self._assignment_call,
            session.session_id,
            assignment.assignment_id,
            lambda: _steps(self.release_assignment,
                session.session_id,
                assignment.assignment_id,
                fence=fence,
                availability_revision=next_revision,
            ),
        )),
    )
    return released_session



def _cancel_pregrant_if_requested(
    self: LocalDaemonAgentHttpClient,
    session: AgentSession,
    assignment_id: str,
    assignment: ManagedAssignment,
    commands: tuple[ClaimCommand, ...],
    providers: Mapping[str, AgentResourceProvider],
    execution_journal: SQLiteAgentJournal,
) -> Generator[_Progress, Any, Mapping[str, PlainData] | None]:
    for _ in range(32):
        control = (yield from _steps(self._assignment_call,
            session.session_id,
            assignment_id,
            lambda: _steps(self.poll_assignment_control, session.session_id),
        ))
        if control is None:
            return None
        if control.assignment_id != assignment_id:
            continue
        if execution_journal.read_state(assignment_id) not in {
            AssignmentState.REQUEST_DURABLE, AssignmentState.PREPARED, AssignmentState.ACCEPTED,
        }:
            return None
        return (yield from _steps(_decline_pregrant_assignment, self,
            session, assignment, commands, providers, execution_journal, cancelled=True))
    raise QueueConflictError("assignment control delivery exceeds its bound")



@_serialized("_mutation_gate")
def _decline_pregrant_assignment(
    self: LocalDaemonAgentHttpClient, session, assignment, commands, providers, execution_journal, *, cancelled=False
):
    assignment_id = assignment.assignment_id
    if cancelled:
        if execution_journal.read_state(assignment_id) is AssignmentState.REQUEST_DURABLE:
            execution_journal.decline_before_prepare(assignment_id)
        else:
            execution_journal.abort_pregrant(assignment_id, commands, providers)
    reason_code = execution_journal.read_decline_reason(assignment_id)
    revision = _availability_revision(session, assignment_id, providers)
    execution_journal.release_declined(assignment_id, revision)
    released = yield from _steps(self._assignment_call, session.session_id, assignment_id,
        lambda: _steps(self.decline_assignment, session.session_id, assignment_id,
                      availability_revision=revision, reason_code=reason_code))
    return freeze_plain_data({
        "result": "assignment", "assignment_id": assignment_id,
        "state": "CANCELLED_BEFORE_GRANT" if cancelled else "DECLINED",
        **({} if cancelled else {"reason_code": reason_code}),
        "session": released.value(),
    }, path="remote pre-grant completion")



def _release_provider_claims(
    self: LocalDaemonAgentHttpClient,
    session: AgentSession,
    assignment: ManagedAssignment,
    commands: tuple[ClaimCommand, ...],
    providers: Mapping[str, AgentResourceProvider],
    execution_journal: SQLiteAgentJournal,
) -> str:
    """Release the exact composite and persist fresh capacity before RPC."""

    local_state = execution_journal.acknowledge_terminal(assignment.assignment_id)
    if local_state is AssignmentState.RELEASED:
        # Re-observe the reconstructed providers, then replay only the
        # availability revision already committed by this old root.
        _availability_revision(session, assignment.assignment_id, providers)
        retained_revision = execution_journal.read_availability_revision(
            assignment.assignment_id
        )
        if retained_revision is None:
            raise QueueConflictError(
                "released remote availability evidence is unavailable"
            )
        return retained_revision
    if local_state is not AssignmentState.PROVIDERS_RELEASED:
        for command in commands:
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise QueueConflictError(
                    "remote provider release owner is unavailable"
                )
            released = provider.release(
                ClaimCommand(
                    assignment,
                    f"{command.operation_id}:release",
                    command.claim,
                    command.provider_descriptor,
                )
            )
            if released.outcome is not ClaimOutcome.RELEASED:
                raise QueueConflictError("remote provider release is indeterminate")
        execution_journal.mark_providers_released(assignment.assignment_id)
    next_revision = _availability_revision(
        session, assignment.assignment_id, providers
    )
    execution_journal.publish_availability(assignment.assignment_id, next_revision)
    return next_revision



def _availability_revision(
    session: AgentSession,
    assignment_id: str,
    providers: Mapping[str, AgentResourceProvider],
) -> str:
    observations = {
        kind: provider.observe(
            ObserveRequest(
                session.agent_id,
                session.session_id,
                f"{assignment_id}:released:{kind}",
            )
        )
        for kind, provider in providers.items()
    }
    return (
        "availability-"
        + hashlib.sha256(
            "\0".join(
                observations[kind].availability_revision
                for kind in sorted(observations)
            ).encode()
        ).hexdigest()
    )



def _start_once_steps(journal, assignment_id, execution_id, launcher, *, start_failure):
    existing = journal._prepare_process_start(assignment_id, execution_id)
    if existing is not None:
        return existing
    try:
        process_id = yield from launcher()
    except ManagedProcessStartError as error:
        journal._set_start_failed(assignment_id, execution_id, start_failure(error))
        raise
    except Exception:
        journal._set_state(assignment_id, AssignmentState.START_UNKNOWN)
        raise
    return journal._complete_process_start(assignment_id, execution_id, process_id, start_failure)

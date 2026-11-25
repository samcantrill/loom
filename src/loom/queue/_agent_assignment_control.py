"""Agent-local ownership of assignment cancellation, replay, and containment."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
import json
from typing import Any

from loom.pipeline.status import StageStatus
from loom.serialization import PlainData

from ._agent_process_supervisor import (
    AgentProcessSupervisorClient, AgentProcessSupervisorError, ResidentWorkerLaunch,
    SupervisorLaunchState, SupervisorReceipt, _launch_from_value,
)
from ._agent_progress import _Progress, _steps
from ._agent_session_journal import _RemoteAgentJournal
from ._managed_local import AssignmentState, SQLiteAgentJournal
from ._remote_stage_execution import _ResidentAssignmentWorkspace
from .agent_sessions import AgentAssignmentControl, _managed_containment_evidence
from .errors import QueueConflictError, QueueError

ControlResult = tuple[str, Mapping[str, PlainData] | None]


@dataclass(frozen=True, slots=True)
class AssignmentControlInbox:
    """Replay received commands and durable results before accepting another command."""

    journal: _RemoteAgentJournal
    received_cancellations: set[str]
    cancelled_assignments: set[str]

    def poll(
        self,
        session_id: str,
        *,
        assignment_id: str | None,
        owned: Callable[[str], bool],
        fetch: Callable[[str], Generator[_Progress, Any, AgentAssignmentControl | None]] | None,
        apply: Callable[[AgentAssignmentControl], ControlResult],
        acknowledge: Callable[[str, AgentAssignmentControl, str, Mapping[str, PlainData] | None], None],
    ) -> Generator[_Progress, Any, AgentAssignmentControl | None]:
        journal = self.journal
        pending = journal.next_unacknowledged_assignment_control(assignment_id=assignment_id, owned=owned)
        if pending is not None:
            control, code, evidence = pending
            if control.session_id != session_id:
                raise QueueConflictError(
                    "retained assignment control belongs to another session"
                )
            if code == "contained":
                self.cancelled_assignments.add(control.assignment_id)
            yield from _steps(acknowledge, session_id, control, code, evidence)
            return control
        control = journal.next_received_assignment_control(assignment_id=assignment_id, owned=owned)
        if control is None:
            if fetch is None:
                return None
            control = yield from fetch(session_id)
            if control is None:
                return None
        if control.session_id != session_id:
            raise QueueConflictError("retained assignment control belongs to another session")
        self.received_cancellations.add(control.assignment_id)
        if not owned(control.assignment_id):
            journal.prepare_assignment_control(control)
            return None
        prior = journal.prepare_assignment_control(control)
        if prior is not None:
            code, evidence = prior
            yield from _steps(acknowledge, session_id, control, code, evidence)
            return control
        code, evidence = yield from _steps(apply, control)
        journal.record_assignment_control_result(control, code, evidence)
        yield from _steps(acknowledge, session_id, control, code, evidence)
        return control


@dataclass(frozen=True, slots=True)
class ControlledAssignment:
    """Resolve a cancellation against the exact durable assignment and launch fence."""

    session_journal: _RemoteAgentJournal
    execution: SQLiteAgentJournal
    workspace: _ResidentAssignmentWorkspace
    supervisor: AgentProcessSupervisorClient | None

    def prepare(self, control: AgentAssignmentControl) -> str | tuple[ResidentWorkerLaunch, str]:
        workspace, journal = self.workspace, self.execution
        raw = self.session_journal.delivery_request(control.session_id, control.assignment_id)
        from ._shared_assignment import reference
        if (not workspace.has_request() and reference(raw) is not None
            and control.fence is None and journal.find_state(control.assignment_id) is None):
            return "never_started"
        try:
            state = journal.read_state(control.assignment_id)
            fence = journal.read_grant_fence(control.assignment_id)
        except Exception:
            return "unknown"
        if control.fence != fence:
            return "unknown"
        encoded_launch = workspace.supervisor_launch_json()
        if encoded_launch is None:
            if state in {
                AssignmentState.RESULT_DURABLE,
                AssignmentState.TERMINAL_ACKNOWLEDGED,
                AssignmentState.PROVIDERS_RELEASED,
                AssignmentState.RELEASED,
            }:
                result = journal.read_result(control.assignment_id)
                if result is not None and result.status is StageStatus.CANCELLED:
                    # With no persisted launch, this result can only come
                    # from the native ACTIVE/no-start cancellation transition.
                    return "never_started"
                return "terminal"
            if state in {
                AssignmentState.REQUEST_DURABLE,
                AssignmentState.PREPARED,
                AssignmentState.ACCEPTED,
                AssignmentState.GRANTED,
                AssignmentState.ACTIVE,
            }:
                return "never_started"
            return "unknown"
        if control.process_execution_id not in {
            None,
            f"{control.assignment_id}:root",
        }:
            return "unknown"
        if self.supervisor is None:
            return "unknown"
        try:
            launch = _launch_from_value(json.loads(encoded_launch))
            if (
                launch.assignment_id != control.assignment_id
                or launch.session_id != control.session_id
                or (
                    control.process_execution_id is not None
                    and launch.process_execution_id != control.process_execution_id
                )
                or launch.execution_fence != control.fence
            ):
                return "unknown"
            if state is AssignmentState.RELEASED:
                # Release already proved containment and returned claims.
                # A late command cannot change its committed result.
                return "terminal"
        except (AgentProcessSupervisorError, QueueError, ValueError):
            return "unknown"
        return launch, encoded_launch

    def finish(
        self,
        control: AgentAssignmentControl,
        launch: ResidentWorkerLaunch,
        contained: SupervisorReceipt,
        launch_json: str,
        *,
        observe: Callable[[SupervisorReceipt], None],
        record_cancellation: Callable[[_ResidentAssignmentWorkspace], None],
        agent_id: str | None,
    ) -> ControlResult:
        if (contained.launch != launch or self.workspace.supervisor_launch_json() != launch_json
                or self.execution.read_grant_fence(control.assignment_id) != control.fence):
            return "unknown", None
        observe(contained)
        if contained.state is not SupervisorLaunchState.CONTAINED:
            return "unknown", None
        if self.execution.read_state(control.assignment_id) is AssignmentState.RELEASED:
            return "terminal", None
        record_cancellation(self.workspace)
        if agent_id is None:
            return "unknown", None
        return "contained", _supervisor_containment_evidence(
            contained, agent_id=agent_id
        )


def _supervisor_containment_evidence(
    receipt: SupervisorReceipt, *, agent_id: str
) -> Mapping[str, PlainData]:
    """Serialize the exact persisted process-owner receipt without paths."""

    launch = receipt.launch
    return _managed_containment_evidence(
        {
            "kind": "managed_supervisor",
            "state": "CONTAINED",
            "supervisor_id": launch.supervisor_id,
            "continuity_epoch": launch.continuity_epoch,
            "agent_id": agent_id,
            "supervisor_agent_id": launch.agent_id,
            "session_id": launch.session_id,
            "assignment_id": launch.assignment_id,
            "process_execution_id": launch.process_execution_id,
            "execution_fence": launch.execution_fence,
            "launch_operation_id": launch.launch_operation_id,
            "launch_spec_digest": launch.spec_digest,
            "supervisor_revision": receipt.supervisor_revision,
            "worker_result_digest": receipt.worker_result_digest,
        }
    )

"""Agent-owned durable resident claims, launches and releases."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from loom._sqlite_policy import SQLitePolicy
from loom.pipeline.execution.models import (
    StageWorkerResult,
)
from loom.pipeline.status import StageStatus
from loom.serialization import PlainData

from ._agent_progress import _cooperative, _Progress, _steps
from ._managed_contracts import (
    GPU_DECLINE_REASONS,
    AgentResourceProvider,
    AssignmentState,
    ClaimCommand,
    ClaimOutcome,
    ManagedAssignment,
    ManagedLocalError,
    ManagedProcessStartError,
    ProviderReleaseEvidence,
    _agent_at_or_after,
    _assignment_dict,
    _assignment_from_dict,
    _claim_command_dict,
    _claim_command_from_dict,
    _connect_sqlite,
    _json,
    _operation_command,
    _ProbeClaimOwner,
    _provider_call,
    _read_decline_reason,
    _require_sqlite_columns,
)


class SQLiteAgentJournal:
    """Durable local journal for the agent-owned side of an assignment.

    The journal is intentionally append/replay oriented.  ``record_event``
    makes a fact durable before it can be delivered and refuses an event gap.
    """

    def __init__(self, path: str | Path, *, _allow_initialize: bool = True, sqlite_policy: SQLitePolicy | None = None) -> None:
        self.path = Path(path)
        self._allow_initialize = _allow_initialize and sqlite_policy is None
        self._sqlite_policy = sqlite_policy

    def _initialize(self) -> None:
        """Create the current journal schema at an explicit owner boundary."""

        previous = self._allow_initialize
        self._allow_initialize = True
        try:
            with self._transaction():
                pass
        finally:
            self._allow_initialize = previous

    def _open_existing(self) -> None:
        """Verify the current journal without creating or repairing it."""

        if not self.path.is_file():
            raise ManagedLocalError("agent journal is missing")
        with _connect_sqlite(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            _require_agent_journal_schema(conn)

    def reserve_probe(self, command: ClaimCommand) -> None:
        """Persist exact diagnostic ownership before any provider activation."""
        owner = command.assignment
        if not isinstance(owner, _ProbeClaimOwner):
            raise ManagedLocalError("diagnostic probe owner is required")
        with self._transaction() as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM diagnostic_probes WHERE probe_id = ?",
                    (owner.probe_id,),
                ).fetchone()
                is not None
            ):
                raise ManagedLocalError("diagnostic probe cannot be relaunched")
            conn.execute(
                "INSERT INTO diagnostic_probes (probe_id, agent_id, command_json, state) "
                "VALUES (?, ?, ?, 'reserved')",
                (owner.probe_id, owner.agent_id, _json(_claim_command_dict(command))),
            )

    def mark_probe_launch_intent(self, probe_id: str) -> None:
        """Make launch intent durable before invoking the one process creator."""
        self._advance_probe(probe_id, ("reserved",), "launch_intent")

    def mark_probe_contained(self, probe_id: str) -> None:
        """Record the owned runner's proof that no created process is uncertain."""
        self._advance_probe(probe_id, ("reserved", "launch_intent"), "contained")

    def release_probe(
        self, probe_id: str, providers: Mapping[str, AgentResourceProvider]
    ) -> bool:
        """Release only a contained probe, retaining indeterminate provider release."""
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT * FROM diagnostic_probes WHERE probe_id = ?", (probe_id,)
            ).fetchone()
            if row is None:
                raise ManagedLocalError("diagnostic probe is missing")
            command = _probe_command_from_row(row)
            if row["state"] == "released":
                return True
            if row["state"] != "contained":
                raise ManagedLocalError("diagnostic probe cleanup is unproven")
        provider = providers.get(command.claim.resource_kind)
        if provider is None:
            raise ManagedLocalError("diagnostic probe provider is unavailable")
        result = _provider_call(
            provider.release, _operation_command(command, "release")
        )
        if result.outcome is not ClaimOutcome.RELEASED:
            return False
        self._advance_probe(probe_id, ("contained",), "released")
        return True

    def _advance_probe(self, probe_id: str, prior: tuple[str, ...], state: str) -> None:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM diagnostic_probes WHERE probe_id = ?", (probe_id,)
            ).fetchone()
            if row is None or row["state"] not in prior:
                raise ManagedLocalError("diagnostic probe lifecycle conflicts")
            conn.execute(
                "UPDATE diagnostic_probes SET state = ? WHERE probe_id = ?",
                (state, probe_id),
            )

    def persist_request(
        self, assignment: ManagedAssignment, request: Mapping[str, PlainData]
    ) -> AssignmentState:
        payload = _json(request)
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT request_json, state FROM assignments WHERE assignment_id = ?",
                (assignment.assignment_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO assignments (assignment_id, identity_json, request_json, state, grant_fence, process_execution_id, result_json) VALUES (?, ?, ?, ?, NULL, NULL, NULL)",
                    (
                        assignment.assignment_id,
                        _json(_assignment_dict(assignment)),
                        payload,
                        AssignmentState.REQUEST_DURABLE.value,
                    ),
                )
                return AssignmentState.REQUEST_DURABLE
            if row["request_json"] != payload:
                raise ManagedLocalError(
                    "assignment request conflicts with durable request"
                )
            return AssignmentState(row["state"])

    @_cooperative
    def prepare_composite(
        self,
        assignment: ManagedAssignment,
        commands: Sequence[ClaimCommand],
        providers: Mapping[str, AgentResourceProvider],
    ) -> Generator[_Progress, Any, AssignmentState]:
        self._require_request(assignment)
        ordered = tuple(sorted(commands, key=lambda item: item.claim.resource_kind))
        encoded_commands = _json(
            {"commands": [_claim_command_dict(command) for command in ordered]}
        )
        with self._transaction() as conn:
            row = self._assignment(conn, assignment.assignment_id)
            state = AssignmentState(row["state"])
            if (
                row["claims_json"] is not None
                and row["claims_json"] != encoded_commands
            ):
                raise ManagedLocalError("assignment claim commands conflict")
            if row["claims_json"] is None:
                conn.execute(
                    "UPDATE assignments SET claims_json = ? WHERE assignment_id = ?",
                    (encoded_commands, assignment.assignment_id),
                )
            if bool(row["declined"]):
                return AssignmentState.DECLINED
            if state in {
                AssignmentState.PREPARED,
                AssignmentState.ACCEPTED,
                AssignmentState.GRANTED,
                AssignmentState.ACTIVE,
                AssignmentState.ACTIVATION_UNKNOWN,
                AssignmentState.START_INTENT,
                AssignmentState.PROCESS_STARTED,
                AssignmentState.START_FAILED,
                AssignmentState.START_UNKNOWN,
                AssignmentState.RESULT_DURABLE,
                AssignmentState.TERMINAL_ACKNOWLEDGED,
                AssignmentState.PROVIDERS_RELEASED,
                AssignmentState.RELEASED,
            }:
                return state
            if state is AssignmentState.DECLINED:
                return state
            if state not in {
                AssignmentState.REQUEST_DURABLE,
                AssignmentState.PREPARE_UNKNOWN,
            }:
                raise ManagedLocalError("assignment cannot prepare in current state")
            reconcile = state is AssignmentState.PREPARE_UNKNOWN

        prepared: list[tuple[AgentResourceProvider, ClaimCommand]] = []
        for command in ordered:
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            result = yield from _steps(
                _provider_call,
                provider.reconcile if reconcile else provider.prepare,
                command,
            )
            if result.outcome is not ClaimOutcome.PREPARED:
                aborts = [
                    _provider_call(previous.abort, previous_command)
                    for previous, previous_command in reversed(prepared)
                ]
                aborts_complete = all(
                    item.outcome is ClaimOutcome.RELEASED for item in aborts
                )
                if result.outcome is ClaimOutcome.DECLINED and aborts_complete:
                    return self._set_declined(assignment.assignment_id, result.detail)
                return self._set_state(
                    assignment.assignment_id, AssignmentState.PREPARE_UNKNOWN
                )
            prepared.append((provider, command))
        return self._set_state(assignment.assignment_id, AssignmentState.PREPARED)

    def accept(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id, AssignmentState.PREPARED, AssignmentState.ACCEPTED
        )

    def decline_before_prepare(self, assignment_id: str) -> AssignmentState:
        """Prove a durable request acquired no provider claims."""

        return self._advance(
            assignment_id, AssignmentState.REQUEST_DURABLE, AssignmentState.DECLINED
        )

    def abort_pregrant(
        self,
        assignment_id: str,
        commands: Sequence[ClaimCommand],
        providers: Mapping[str, AgentResourceProvider],
    ) -> AssignmentState:
        """Release every exact prepared claim before remote grant."""

        with self._transaction() as conn:
            state = AssignmentState(self._assignment(conn, assignment_id)["state"])
            if state is AssignmentState.DECLINED:
                return state
            if state not in {AssignmentState.PREPARED, AssignmentState.ACCEPTED}:
                raise ManagedLocalError("only prepared pre-grant claims can be aborted")
        return self._abort_exact_claims(assignment_id, commands, providers)

    def _abort_exact_claims(
        self, assignment_id: str, commands: Sequence[ClaimCommand],
        providers: Mapping[str, AgentResourceProvider],
    ) -> AssignmentState:
        for command in sorted(
            commands, key=lambda item: item.claim.resource_kind, reverse=True
        ):
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            if (
                _provider_call(provider.abort, command).outcome
                is not ClaimOutcome.RELEASED
            ):
                raise ManagedLocalError("pre-grant claim abort is indeterminate")
        return self._set_declined(assignment_id)

    def cancel_pregrant(
        self, assignment_id: str, providers: Mapping[str, AgentResourceProvider]
    ) -> AssignmentState:
        """Settle exact claims after the authority has unbound the attempt."""
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if row["grant_fence"] is not None or row["process_execution_id"] is not None:
                raise ManagedLocalError("local assignment has a grant or process")
            if state is AssignmentState.DECLINED:
                return state
            if state is AssignmentState.RELEASED and row["declined"] and row["availability_revision"]:
                return state
            if state is AssignmentState.REQUEST_DURABLE and row["claims_json"] is None:
                conn.execute(
                    "UPDATE assignments SET state = ?, declined = 1 WHERE assignment_id = ?",
                    (AssignmentState.DECLINED.value, assignment_id),
                )
                return AssignmentState.DECLINED
            if state not in {
                AssignmentState.REQUEST_DURABLE, AssignmentState.PREPARE_UNKNOWN,
                AssignmentState.PREPARED, AssignmentState.ACCEPTED,
            }:
                raise ManagedLocalError("local assignment is not proven pre-grant")
            # The commands precede the first physical prepare. A crash can leave
            # any prefix applied while the overall state still reads REQUEST_DURABLE.
            commands = _claim_commands_from_row(row)
        return self._abort_exact_claims(assignment_id, commands, providers)

    def grant(self, assignment_id: str, fence: str) -> AssignmentState:
        if not fence:
            raise ManagedLocalError("grant fence is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["grant_fence"]
            if current is not None and current != fence:
                raise ManagedLocalError("assignment grant fence conflicts")
            if _agent_at_or_after(state, AssignmentState.GRANTED):
                return state
            if state is not AssignmentState.ACCEPTED:
                raise ManagedLocalError("assignment is not accepted")
            conn.execute(
                "UPDATE assignments SET state = ?, grant_fence = ? WHERE assignment_id = ?",
                (AssignmentState.GRANTED.value, fence, assignment_id),
            )
            return AssignmentState.GRANTED

    def activate_composite(
        self,
        assignment_id: str,
        commands: Sequence[ClaimCommand],
        providers: Mapping[str, AgentResourceProvider],
    ) -> AssignmentState:
        """Activate granted claims, reconciling restored providers before launch.

        An ACTIVE journal records prior activation, but reconstructed providers
        may hold only a PREPARED reservation. Reconcile that exact claim and
        reactivate only a positively prepared reservation under the same grant.
        Uncertain restoration leaves the durable activation record intact and
        blocks launch; process-started and later states never reactivate here.
        """
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            restoring_active = state is AssignmentState.ACTIVE
            if _agent_at_or_after(state, AssignmentState.ACTIVE) and not restoring_active:
                return state
            if state not in {
                AssignmentState.GRANTED,
                AssignmentState.ACTIVE,
                AssignmentState.ACTIVATION_UNKNOWN,
            }:
                raise ManagedLocalError("assignment is not grant-activatable")
            reconcile = restoring_active or state is AssignmentState.ACTIVATION_UNKNOWN
        for command in sorted(commands, key=lambda item: item.claim.resource_kind):
            provider = providers.get(command.claim.resource_kind)
            if provider is None:
                raise ManagedLocalError("no provider for claim resource kind")
            result = _provider_call(
                provider.reconcile if reconcile else provider.activate,
                command,
            )
            if restoring_active and result.outcome is ClaimOutcome.PREPARED:
                result = _provider_call(provider.activate, command)
            if result.outcome is not ClaimOutcome.ACTIVE:
                if restoring_active:
                    raise ManagedLocalError("retained active provider claim is unavailable")
                return self._set_state(
                    assignment_id, AssignmentState.ACTIVATION_UNKNOWN
                )
        if restoring_active:
            return state
        return self._set_state(assignment_id, AssignmentState.ACTIVE)

    def start_once(
        self,
        assignment_id: str,
        process_execution_id: str,
        launcher: Callable[[], str],
        *,
        start_failure: Callable[[ManagedProcessStartError], StageWorkerResult],
    ) -> str:
        """Persist intent before one launch, and no-start proof with its result.

        The caller projects a definitive start error into its assignment's result
        identity. That portable result commits with the no-start fact, before
        workspace or coordinator persistence can be interrupted.
        """
        existing = self._prepare_process_start(assignment_id, process_execution_id)
        if existing is not None:
            return existing
        try:
            process_id = launcher()
        except ManagedProcessStartError as exc:
            self._set_start_failed(
                assignment_id, process_execution_id, start_failure(exc)
            )
            raise
        except Exception:
            self._set_state(assignment_id, AssignmentState.START_UNKNOWN)
            raise
        return self._complete_process_start(assignment_id, process_execution_id, process_id, start_failure)

    def _prepare_process_start(self, assignment_id: str, process_execution_id: str) -> str | None:
        """Persist the native start intent before an external launch exchange."""
        if not isinstance(process_execution_id, str) or not process_execution_id:
            raise ManagedLocalError("process_execution_id is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if _agent_at_or_after(state, AssignmentState.PROCESS_STARTED):
                existing = str(row["process_execution_id"])
                if existing != process_execution_id:
                    raise ManagedLocalError("process execution identity conflicts")
                return existing
            if state in {AssignmentState.START_INTENT, AssignmentState.START_UNKNOWN}:
                raise ManagedLocalError(
                    "launch outcome is unknown and cannot be invoked again"
                )
            if state is not AssignmentState.ACTIVE:
                raise ManagedLocalError("assignment is not active for launch")
            conn.execute(
                "UPDATE assignments SET state = ?, process_execution_id = ? "
                "WHERE assignment_id = ?",
                (
                    AssignmentState.START_INTENT.value,
                    process_execution_id,
                    assignment_id,
                ),
            )
        return None

    def _complete_process_start(
        self, assignment_id: str, process_execution_id: str, process_id: str,
        start_failure: Callable[[ManagedProcessStartError], StageWorkerResult],
    ) -> str:
        """Apply a launch result on the journal's owning thread."""
        if not isinstance(process_id, str) or not process_id:
            exc = ManagedProcessStartError("launcher proved no process identifier")
            self._set_start_failed(
                assignment_id, process_execution_id, start_failure(exc)
            )
            raise exc
        if process_id != process_execution_id:
            self._set_state(assignment_id, AssignmentState.START_UNKNOWN)
            raise ManagedLocalError("launcher returned an unexpected process identity")
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (AssignmentState.PROCESS_STARTED.value, assignment_id),
            )
        return process_id

    def confirm_supervised_start(
        self, assignment_id: str, process_execution_id: str
    ) -> AssignmentState:
        """Join an exact durable supervisor receipt after application restart."""

        if not isinstance(process_execution_id, str) or not process_execution_id:
            raise ManagedLocalError("process_execution_id is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["process_execution_id"]
            if current is None or str(current) != process_execution_id:
                raise ManagedLocalError("process execution identity conflicts")
            if _agent_at_or_after(state, AssignmentState.PROCESS_STARTED):
                return state
            if state not in {
                AssignmentState.START_INTENT,
                AssignmentState.START_UNKNOWN,
            }:
                raise ManagedLocalError(
                    "assignment has no supervised start intent to confirm"
                )
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (AssignmentState.PROCESS_STARTED.value, assignment_id),
            )
        return AssignmentState.PROCESS_STARTED

    def definitive_start_failed(self, assignment_id: str) -> bool:
        with self._transaction() as conn:
            return bool(self._assignment(conn, assignment_id)["start_failed"])

    def record_event(
        self,
        assignment_id: str,
        sequence: int,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> int:
        if sequence < 1 or not event_id:
            raise ManagedLocalError("event sequence and ID are required")
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT event_id, payload_json FROM events WHERE assignment_id = ? AND sequence = ?",
                (assignment_id, sequence),
            ).fetchone()
            encoded = _json(payload)
            if existing is not None:
                if (
                    existing["event_id"] != event_id
                    or existing["payload_json"] != encoded
                ):
                    raise ManagedLocalError("event replay conflicts")
                return sequence
            expected = int(
                conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchone()[0]
            )
            if sequence != expected:
                raise ManagedLocalError("agent event sequence gap")
            conn.execute(
                "INSERT INTO events (assignment_id, sequence, event_id, payload_json, acknowledged_sequence) VALUES (?, ?, ?, ?, NULL)",
                (assignment_id, sequence, event_id, encoded),
            )
            return sequence

    def append_event(
        self,
        assignment_id: str,
        event_id: str,
        payload: Mapping[str, PlainData],
    ) -> int:
        if not event_id:
            raise ManagedLocalError("event ID is required")
        with self._transaction() as conn:
            return self._append_event(conn, assignment_id, event_id, _json(payload))

    def _append_event(
        self, conn: sqlite3.Connection, assignment_id: str, event_id: str, encoded: str
    ) -> int:
        self._assignment(conn, assignment_id)
        existing = conn.execute(
            "SELECT sequence, payload_json FROM events "
            "WHERE assignment_id = ? AND event_id = ?",
            (assignment_id, event_id),
        ).fetchone()
        if existing is not None:
            if existing["payload_json"] != encoded:
                raise ManagedLocalError("event replay conflicts")
            return cast(int, existing["sequence"])
        sequence = cast(
            int,
            conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events "
                "WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()[0],
        )
        conn.execute(
            "INSERT INTO events "
            "(assignment_id, sequence, event_id, payload_json, acknowledged_sequence) "
            "VALUES (?, ?, ?, ?, NULL)",
            (assignment_id, sequence, event_id, encoded),
        )
        return sequence

    def acknowledge(self, assignment_id: str, sequence: int) -> int:
        with self._transaction() as conn:
            if sequence and conn.execute(
                "SELECT 1 FROM events WHERE assignment_id = ? AND sequence = ?",
                (assignment_id, sequence),
            ).fetchone() is None:
                raise ManagedLocalError("cannot acknowledge an event gap")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS events_pending_sequence ON events(assignment_id, sequence) "
                "WHERE acknowledged_sequence IS NULL"
            )
            conn.execute(
                "UPDATE events INDEXED BY events_pending_sequence SET acknowledged_sequence = ? "
                "WHERE assignment_id = ? AND acknowledged_sequence IS NULL AND sequence <= ?",
                (sequence, assignment_id, sequence),
            )
            return sequence

    def record_result(
        self, assignment_id: str, result: Mapping[str, PlainData]
    ) -> AssignmentState:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            start_failed = state is AssignmentState.START_FAILED
            if not start_failed and not _agent_at_or_after(
                state, AssignmentState.PROCESS_STARTED
            ):
                raise ManagedLocalError("result requires a confirmed process start")
            encoded = _json(result)
            if (
                start_failed
                and StageWorkerResult.from_dict(result).status is not StageStatus.FAILED
            ):
                raise ManagedLocalError(
                    "definitive start failure requires a failed result"
                )
            if row["result_json"] is not None and row["result_json"] != encoded:
                raise ManagedLocalError("result conflicts with durable result")
            if _agent_at_or_after(state, AssignmentState.RESULT_DURABLE):
                if row["result_json"] is None:
                    raise ManagedLocalError("durable result payload is missing")
                return state
            conn.execute(
                "UPDATE assignments SET state = ?, result_json = ? WHERE assignment_id = ?",
                (AssignmentState.RESULT_DURABLE.value, encoded, assignment_id),
            )
            return AssignmentState.RESULT_DURABLE

    def record_recovered_start_result(
        self,
        assignment_id: str,
        *,
        fence: str,
        result: Mapping[str, PlainData],
    ) -> AssignmentState:
        """Settle an uncertain start after guarded containment/authority closure.

        The remote release owner verifies both proofs before calling this method.
        Keep the uncertain process identity; do not fabricate a confirmed start.
        """
        parsed = StageWorkerResult.from_dict(result)
        if parsed.status not in {StageStatus.CANCELLED, StageStatus.FAILED}:
            raise ManagedLocalError("recovered start cannot establish success")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            if row["grant_fence"] != fence or row["state"] not in {
                AssignmentState.START_INTENT.value,
                AssignmentState.START_UNKNOWN.value,
            }:
                raise ManagedLocalError("recovered start identity is stale")
            conn.execute(
                "UPDATE assignments SET state = ?, result_json = ? WHERE assignment_id = ?",
                (AssignmentState.RESULT_DURABLE.value, _json(result), assignment_id),
            )
            return AssignmentState.RESULT_DURABLE

    def record_cancelled_before_start(
        self, assignment_id: str, result: Mapping[str, PlainData]
    ) -> AssignmentState:
        """Record positive no-launch cancellation without fabricating a start."""

        parsed = StageWorkerResult.from_dict(result)
        if parsed.status is not StageStatus.CANCELLED:
            raise ManagedLocalError("no-start result must be cancelled")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            encoded = _json(result)
            if state is AssignmentState.RESULT_DURABLE:
                if row["result_json"] != encoded:
                    raise ManagedLocalError("result conflicts with durable result")
                return state
            if state is not AssignmentState.ACTIVE:
                raise ManagedLocalError(
                    "no-start cancellation requires an active unstarted assignment"
                )
            if row["process_execution_id"] is not None:
                raise ManagedLocalError(
                    "no-start cancellation conflicts with start intent"
                )
            conn.execute(
                "UPDATE assignments SET state = ?, result_json = ? "
                "WHERE assignment_id = ?",
                (AssignmentState.RESULT_DURABLE.value, encoded, assignment_id),
            )
            return AssignmentState.RESULT_DURABLE

    def acknowledge_terminal(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id,
            AssignmentState.RESULT_DURABLE,
            AssignmentState.TERMINAL_ACKNOWLEDGED,
        )

    def mark_providers_released(self, assignment_id: str) -> AssignmentState:
        return self._advance(
            assignment_id,
            AssignmentState.TERMINAL_ACKNOWLEDGED,
            AssignmentState.PROVIDERS_RELEASED,
        )

    def publish_availability(
        self, assignment_id: str, availability_revision: str
    ) -> AssignmentState:
        if not isinstance(availability_revision, str) or not availability_revision:
            raise ManagedLocalError("fresh availability revision is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["availability_revision"]
            if state is AssignmentState.RELEASED:
                if current != availability_revision:
                    raise ManagedLocalError("availability revision conflicts")
                return state
            if state is not AssignmentState.PROVIDERS_RELEASED:
                raise ManagedLocalError(
                    "fresh availability requires released providers"
                )
            conn.execute(
                "UPDATE assignments SET state = ?, availability_revision = ? "
                "WHERE assignment_id = ?",
                (
                    AssignmentState.RELEASED.value,
                    availability_revision,
                    assignment_id,
                ),
            )
            return AssignmentState.RELEASED

    def release_declined(
        self, assignment_id: str, availability_revision: str
    ) -> AssignmentState:
        if not isinstance(availability_revision, str) or not availability_revision:
            raise ManagedLocalError("fresh availability revision is required")
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            current = row["availability_revision"]
            if state is AssignmentState.RELEASED:
                if current != availability_revision:
                    raise ManagedLocalError("availability revision conflicts")
                return state
            if state is not AssignmentState.DECLINED:
                raise ManagedLocalError("assignment is not definitively declined")
            conn.execute(
                "UPDATE assignments SET state = ?, availability_revision = ? "
                "WHERE assignment_id = ?",
                (
                    AssignmentState.RELEASED.value,
                    availability_revision,
                    assignment_id,
                ),
            )
            return AssignmentState.RELEASED

    def read_state(self, assignment_id: str) -> AssignmentState:
        with self._transaction() as conn:
            return AssignmentState(self._assignment(conn, assignment_id)["state"])

    def find_state(self, assignment_id: str) -> AssignmentState | None:
        """Return one exact durable local fact without treating absence as progress."""

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM assignments WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchone()
            return None if row is None else AssignmentState(row["state"])

    def read_grant_fence(self, assignment_id: str) -> str | None:
        with self._transaction() as conn:
            value = self._assignment(conn, assignment_id)["grant_fence"]
        return None if value is None else str(value)

    def recovery_record(self, assignment: ManagedAssignment) -> dict[str, Any] | None:
        from ._shared_recovery import WIRE

        with self._transaction() as conn:
            row = conn.execute(
                "SELECT identity_json, request_json, state, grant_fence, "
                "process_execution_id, result_json, availability_revision "
                "FROM assignments WHERE assignment_id = ?", (assignment.assignment_id,),
            ).fetchone()
        if row is None or WIRE not in json.loads(row["request_json"]).get("worker_metadata", {}):
            return None
        if _assignment_from_dict(json.loads(row["identity_json"])) != assignment:
            raise ManagedLocalError("local recovery assignment identity conflicts")
        return {
            "assignment_id": assignment.assignment_id, "run_uri": assignment.run_uri,
            "stage_name": assignment.stage_name, "attempt_id": assignment.attempt_id,
            "attempt": assignment.attempt, "agent_id": assignment.agent_id,
            "state": str(row["state"]).upper(), "fence": row["grant_fence"],
            "start_permitted": row["process_execution_id"] is not None,
            "request_json": row["request_json"], "report_json": row["result_json"],
            "provider_release_proof_json": row["availability_revision"]
            if row["state"] == AssignmentState.RELEASED.value else None,
        }

    def require_failed_before_start(self, assignment_id: str, *, fence: str) -> None:
        """Require the exact owner-recorded failed launch, not a worker assertion."""

        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if (
                row["grant_fence"] != fence
                or not row["start_failed"]
                or (
                    state is not AssignmentState.START_FAILED
                    and not _agent_at_or_after(state, AssignmentState.RESULT_DURABLE)
                )
            ):
                raise ManagedLocalError(
                    "assignment lacks exact definitive no-start failure proof"
                )

    def read_availability_revision(self, assignment_id: str) -> str | None:
        """Return the already-published release revision for outbox replay."""

        with self._transaction() as conn:
            value = self._assignment(conn, assignment_id)["availability_revision"]
        return None if value is None else str(value)

    def read_decline_reason(self, assignment_id: str) -> str | None:
        """Read the bounded reason retained at definitive pre-grant refusal."""

        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            return _read_decline_reason(conn, "events", assignment_id)

    def read_result(self, assignment_id: str) -> StageWorkerResult | None:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            if row["result_json"] is None:
                return None
            return StageWorkerResult.from_dict(
                json.loads(cast(str, row["result_json"]))
            )

    def provider_release_evidence(self, assignment_id: str) -> ProviderReleaseEvidence:
        """Read the exact immutable fact created after every provider released."""

        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if state is not AssignmentState.RELEASED:
                raise ManagedLocalError(
                    "assignment has no durable provider release evidence"
                )
            if row["claims_json"] is None:
                raise ManagedLocalError("assignment claim evidence is unavailable")
            fence = row["grant_fence"]
            availability_revision = row["availability_revision"]
            if not isinstance(fence, str) or not isinstance(availability_revision, str):
                raise ManagedLocalError(
                    "assignment provider release evidence is incomplete"
                )
            assignment = _assignment_from_dict(
                json.loads(cast(str, row["identity_json"]))
            )
            commands = _claim_commands_from_row(row)
            if any(command.assignment != assignment for command in commands):
                raise ManagedLocalError(
                    "assignment provider release evidence is incomplete"
                )
            return ProviderReleaseEvidence(assignment, fence, availability_revision)

    def retained_claim_commands(self) -> tuple[ClaimCommand, ...]:
        """Return exact claims still lacking durable provider-release proof."""
        if not self.path.is_file():
            if not self._allow_initialize:
                raise ManagedLocalError("agent journal is missing")
            return ()
        with _connect_sqlite(self.path, sqlite_policy=self._sqlite_policy, require_existing=True) as conn:
            conn.row_factory = sqlite3.Row
            try:
                rows = tuple(
                    conn.execute(
                        "SELECT identity_json, claims_json, state FROM assignments "
                        "WHERE claims_json IS NOT NULL"
                    )
                )
                probes = tuple(
                    conn.execute(
                        "SELECT * FROM diagnostic_probes WHERE state != 'released'"
                    )
                )
            except sqlite3.DatabaseError as exc:
                raise ManagedLocalError(
                    "agent journal retained-claim read failed"
                ) from exc
        retained: list[ClaimCommand] = []
        released = {
            AssignmentState.DECLINED.value,
            AssignmentState.PROVIDERS_RELEASED.value,
            AssignmentState.RELEASED.value,
        }
        for row in rows:
            if cast(str, row["state"]) in released:
                continue
            retained.extend(_claim_commands_from_row(row))
        retained.extend(_probe_command_from_row(row) for row in probes)
        return tuple(retained)

    def assignment_claim_commands(self, assignment_id: str) -> tuple[ClaimCommand, ...]:
        """Return an assignment's exact commands, including after release."""

        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            if row["claims_json"] is None:
                raise ManagedLocalError("assignment claim evidence is unavailable")
            return _claim_commands_from_row(row)

    @contextmanager
    def _transaction(self):
        if not self.path.is_file():
            if not self._allow_initialize:
                raise ManagedLocalError("agent journal is missing")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with _connect_sqlite(
            self.path, sqlite_policy=self._sqlite_policy, require_existing=not self._allow_initialize
        ) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            if not self._allow_initialize:
                _require_agent_journal_schema(conn)
                try:
                    yield conn
                except Exception:
                    conn.rollback()
                    raise
                else:
                    conn.commit()
                return
            conn.execute(
                "CREATE TABLE IF NOT EXISTS assignments ("
                "assignment_id TEXT PRIMARY KEY, identity_json TEXT NOT NULL, "
                "request_json TEXT NOT NULL, claims_json TEXT, state TEXT NOT NULL, "
                "grant_fence TEXT, process_execution_id TEXT, result_json TEXT, "
                "availability_revision TEXT, declined INTEGER NOT NULL DEFAULT 0, "
                "start_failed INTEGER NOT NULL DEFAULT 0)"
            )
            columns = {
                cast(str, row["name"])
                for row in conn.execute("PRAGMA table_info(assignments)")
            }
            if "claims_json" not in columns:
                conn.execute("ALTER TABLE assignments ADD COLUMN claims_json TEXT")
            if "availability_revision" not in columns:
                conn.execute(
                    "ALTER TABLE assignments ADD COLUMN availability_revision TEXT"
                )
            if "declined" not in columns:
                conn.execute(
                    "ALTER TABLE assignments ADD COLUMN declined INTEGER NOT NULL "
                    "DEFAULT 0"
                )
            if "start_failed" not in columns:
                conn.execute(
                    "ALTER TABLE assignments ADD COLUMN start_failed INTEGER NOT NULL "
                    "DEFAULT 0"
                )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events (assignment_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, payload_json TEXT NOT NULL, acknowledged_sequence INTEGER, PRIMARY KEY (assignment_id, sequence), UNIQUE (assignment_id, event_id))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS diagnostic_probes ("
                "probe_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, "
                "command_json TEXT NOT NULL, state TEXT NOT NULL "
                "CHECK (state IN ('reserved','launch_intent','contained','released')))"
            )
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _require_request(self, assignment: ManagedAssignment) -> None:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment.assignment_id)
            if row["identity_json"] != _json(_assignment_dict(assignment)):
                raise ManagedLocalError("assignment identity conflicts")

    def _advance(
        self, assignment_id: str, prior: AssignmentState, next_state: AssignmentState
    ) -> AssignmentState:
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            state = AssignmentState(row["state"])
            if state is next_state:
                return state
            if _agent_at_or_after(state, next_state):
                return state
            if state is not prior:
                raise ManagedLocalError(f"assignment is not {prior.value}")
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (next_state.value, assignment_id),
            )
            return next_state

    def _set_state(self, assignment_id: str, state: AssignmentState) -> AssignmentState:
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            conn.execute(
                "UPDATE assignments SET state = ? WHERE assignment_id = ?",
                (state.value, assignment_id),
            )
        return state

    def _set_declined(
        self, assignment_id: str, detail: str | None = None
    ) -> AssignmentState:
        with self._transaction() as conn:
            self._assignment(conn, assignment_id)
            if detail in GPU_DECLINE_REASONS:
                self._append_event(
                    conn,
                    assignment_id,
                    f"{assignment_id}:definitive_decline",
                    _json({"kind": "definitive_decline", "reason_code": detail}),
                )
            conn.execute(
                "UPDATE assignments SET state = ?, declined = 1 "
                "WHERE assignment_id = ?",
                (AssignmentState.DECLINED.value, assignment_id),
            )
        return AssignmentState.DECLINED

    def record_supervisor_rejected_start(
        self, assignment_id: str, *, fence: str, result: StageWorkerResult
    ) -> AssignmentState:
        """Record no-start after the supervisor durably forbids this assignment.

        The remote recovery owner obtains the positive rejection before calling;
        missing launch records alone are not sufficient evidence.
        """
        return self._set_start_failed(
            assignment_id, f"{assignment_id}:root", result, rejected_fence=fence
        )

    def _set_start_failed(
        self,
        assignment_id: str,
        process_execution_id: str,
        result: StageWorkerResult,
        *,
        rejected_fence: str | None = None,
    ) -> AssignmentState:
        if result.status is not StageStatus.FAILED:
            raise ManagedLocalError("definitive start failure requires a failed result")
        encoded = _json(result.to_dict())
        with self._transaction() as conn:
            row = self._assignment(conn, assignment_id)
            identity = json.loads(cast(str, row["identity_json"]))
            permitted_states = {AssignmentState.START_INTENT.value}
            if rejected_fence is not None:
                if row["grant_fence"] != rejected_fence:
                    raise ManagedLocalError("rejected start fence is stale")
                permitted_states.add(AssignmentState.START_UNKNOWN.value)
            if (
                row["state"] not in permitted_states
                or row["process_execution_id"] != process_execution_id
                or row["grant_fence"] is None
                or result.run_uri != identity["run_uri"]
                or result.stage_name != identity["stage_name"]
                or result.attempt != identity["attempt"]
            ):
                raise ManagedLocalError(
                    "no-start result conflicts with launch identity"
                )
            conn.execute(
                "UPDATE assignments SET state = ?, start_failed = 1, result_json = ? "
                "WHERE assignment_id = ?",
                (AssignmentState.START_FAILED.value, encoded, assignment_id),
            )
        return AssignmentState.START_FAILED

    @staticmethod
    def _assignment(conn: sqlite3.Connection, assignment_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM assignments WHERE assignment_id = ?", (assignment_id,)
        ).fetchone()
        if row is None:
            raise ManagedLocalError("assignment is not durable")
        return row


def _claim_commands_from_row(row: sqlite3.Row) -> tuple[ClaimCommand, ...]:
    try:
        identity = json.loads(cast(str, row["identity_json"]))
        assignment = ManagedAssignment(
            assignment_id=cast(str, identity["assignment_id"]),
            run_uri=cast(str, identity["run_uri"]),
            stage_work_id=cast(str, identity["stage_work_id"]),
            stage_name=cast(str, identity["stage_name"]),
            attempt=cast(int, identity["attempt"]),
            attempt_id=cast(str, identity["attempt_id"]),
            agent_id=cast(str, identity["agent_id"]),
            session_id=cast(str, identity["session_id"]),
            offer_id=cast(str, identity["offer_id"]),
            claim_id=cast(str, identity["claim_id"]),
        )
        commands = json.loads(cast(str, row["claims_json"]))
        values = commands.get("commands") if isinstance(commands, dict) else None
        if not isinstance(values, list):
            raise ManagedLocalError("retained agent claims are corrupt")
        return tuple(_claim_command_from_dict(assignment, value) for value in values)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ManagedLocalError("retained agent claims are corrupt") from exc


def _require_agent_journal_schema(conn: sqlite3.Connection) -> None:
    _require_sqlite_columns(
        conn,
        "diagnostic_probes",
        {"probe_id", "agent_id", "command_json", "state"},
        "agent journal",
    )
    _require_sqlite_columns(
        conn,
        "assignments",
        {
            "assignment_id",
            "identity_json",
            "request_json",
            "claims_json",
            "state",
            "grant_fence",
            "process_execution_id",
            "result_json",
            "availability_revision",
            "declined",
            "start_failed",
        },
        "agent journal",
    )
    _require_sqlite_columns(
        conn,
        "events",
        {
            "assignment_id",
            "sequence",
            "event_id",
            "payload_json",
            "acknowledged_sequence",
        },
        "agent journal",
    )


def _probe_command_from_row(row: sqlite3.Row) -> ClaimCommand:
    if row["state"] not in {"reserved", "launch_intent", "contained", "released"}:
        raise ManagedLocalError("diagnostic probe state is invalid")
    try:
        owner = _ProbeClaimOwner(row["probe_id"], row["agent_id"])
        return _claim_command_from_dict(owner, json.loads(row["command_json"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise ManagedLocalError("diagnostic probe claim is invalid") from exc

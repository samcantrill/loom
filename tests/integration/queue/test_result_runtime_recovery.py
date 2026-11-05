"""Native recovery eligibility never equates completed work with settlement."""
from threading import Event
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from loom.queue import _shared_publication
from loom.queue.agent_session_transport import _read_remote_agent_root_id
from loom.queue.service_upgrade import (
    inspect_agent_result_recovery,
    inspect_service_settlement,
    inspect_coordinator_result_recovery,
    require_result_recovery,
)
from tests.integration.queue.test_concurrent_outbound_agent import (
    _service, _submit, _submit_gated, _release_gate, _eventually,
)

pytestmark = pytest.mark.integration


def test_admitted_publication_finishes_after_authorization_expiry(monkeypatch):
    from loom.queue.local_daemon import LocalDaemonPrincipal, LocalDaemonRole
    from loom.queue.agent_sessions import AgentTransferAuthorizationStaleError
    from loom.queue._remote_stage_execution import _RemoteExecutionReport
    import json

    prepare = _shared_publication.prepare_publication
    now = [datetime.now(timezone.utc).replace(microsecond=0)]
    verified = []

    def slow_prepare(request, *args, **kwargs):
        result = prepare(request, *args, **kwargs)
        verified.append(request.assignment_id)
        now[0] += timedelta(seconds=61)
        return result

    monkeypatch.setattr(_shared_publication, "prepare_publication", slow_prepare)
    with _service(monkeypatch, shared=True, clock=lambda: now[0].isoformat().replace("+00:00", "Z")) as case:
        uri, authority = _submit(case, "slow-publication")
        assert case.client.wait("slow-publication", timeout_seconds=30).state.value == "SUCCEEDED"
        assert len(verified) == 1
        assert len(authority.list_output_commits(uri)) == 1
        with sqlite3.connect(case.database) as conn:
            assignment, session, fence, encoded = conn.execute(
                "SELECT assignment_id, session_id, fence, report_json FROM remote_assignments"
            ).fetchone()
            authorization, revision = conn.execute(
                "SELECT authorization_id, revision FROM remote_transfer_authorizations "
                "WHERE assignment_id = ? ORDER BY revision DESC LIMIT 1", (assignment,)
            ).fetchone()
        view = case.daemon.agent_view(
            LocalDaemonPrincipal("principal", LocalDaemonRole.AGENT, "credential")
        )
        # Completion does not extend the grant or authorize another RPC.
        with pytest.raises(AgentTransferAuthorizationStaleError):
            view.declare_outputs(
                session, assignment, fence=fence, authorization_id=authorization,
                authorization_revision=revision,
                report=_RemoteExecutionReport.from_dict(json.loads(encoded)),
            )
        _eventually(lambda: case.operator.observe_assignment(assignment).value["remote_state"] == "RELEASED")


def test_expired_authorization_history_beyond_64_recovers_over_tls(monkeypatch):
    from loom.queue.local_daemon import LocalDaemonPrincipal, LocalDaemonRole

    entered, release = Event(), Event()
    retain = _shared_publication.retain
    now = [datetime.now(timezone.utc).replace(microsecond=0)]

    def hold(workspace, result):
        entered.set()
        assert release.wait(60)
        return retain(workspace, result)

    monkeypatch.setattr(_shared_publication, "retain", hold)
    with _service(monkeypatch, shared=True, clock=lambda: now[0].isoformat().replace("+00:00", "Z")) as case:
        try:
            _submit(case, "expired-history")
            assert entered.wait(20), case.failures
            with sqlite3.connect(case.database) as conn:
                assignment, session = conn.execute(
                    "SELECT assignment_id, session_id FROM remote_assignments"
                ).fetchone()
            view = case.daemon.agent_view(
                LocalDaemonPrincipal("principal", LocalDaemonRole.AGENT, "credential")
            )
            # Native authorization requests reproduce a long-lived publication.
            # The agent will replay this same-epoch history after the barrier.
            first = None
            for revision in range(66):
                grant = view.authorize_transfers(
                    session, assignment, expected_revision=revision,
                    operation_id=f"{assignment}:authorize:{revision + 1}",
                )
                if first is None:
                    first = grant
            assert view.authorize_transfers(
                session, assignment, expected_revision=0,
                operation_id=f"{assignment}:authorize:1",
            ) == first
            history = case.operator.observe_assignment(assignment).value["transfer_authorization"]
            assert history["retained_count"] == history["latest_revision"] == 66
            assert history["history_limit"] == 1_000_000
            now[0] += timedelta(seconds=61)
            release.set()
            assert case.client.wait("expired-history", timeout_seconds=60).state.value == "SUCCEEDED"
            _eventually(lambda: case.operator.observe_assignment(assignment).value["remote_state"] == "RELEASED")
            assert case.operator.observe_assignment(assignment).value["transfer_authorization"]["latest_revision"] > 66
        finally:
            release.set()


@pytest.mark.parametrize("cancelled", [False, True])
def test_retained_success_is_recoverable_but_not_settled(monkeypatch, cancelled):
    entered, release = Event(), Event()
    retain = _shared_publication.retain
    before_result, resume_completion = Event(), Event()

    if cancelled:
        from loom.queue import _agent_assignment
        from loom.queue._agent_progress import _delay, _steps

        complete = _agent_assignment._complete_remote_result_and_release

        def cancel_before_completion(client, session, *args, **kwargs):
            before_result.set()
            while not resume_completion.is_set():
                yield from _delay(0.01)
            # Deliver the real cancellation after worker success but before
            # result retention, reproducing the fleet's contained late result.
            while (yield from _steps(client.poll_assignment_control, session.session_id)) is None:
                yield from _delay(0.01)
            return (yield from complete(client, session, *args, **kwargs))

        monkeypatch.setattr(_agent_assignment, "_complete_remote_result_and_release", cancel_before_completion)

    def hold(workspace, result):
        entered.set()
        assert release.wait(60)
        return retain(workspace, result)

    monkeypatch.setattr(_shared_publication, "retain", hold)
    with _service(monkeypatch, shared=True) as case:
        try:
            _submit(case, "recover-result")
            if cancelled:
                assert before_result.wait(20), case.failures
                case.client.cancel("recover-result")
                resume_completion.set()
            assert entered.wait(20), case.failures
            if cancelled:
                def contained():
                    with sqlite3.connect(case.database) as conn:
                        return conn.execute(
                            "SELECT 1 FROM remote_assignment_controls WHERE "
                            "state = 'applied' AND result_code = 'contained' AND acknowledged = 1"
                        ).fetchone()
                _eventually(contained)
            identity = _read_remote_agent_root_id(case.agent_root)
            observation = inspect_agent_result_recovery(
                case.agent_root, expected_root_id=identity,
            )
            assert observation.availability == "available", observation.to_dict()
            results = observation.value["results"]
            assert len(results) == 1
            assert results[0]["stage_name"] == "build"
            assert results[0]["attempt"] == 1
            coordinator = case.daemon.config.coordinator_root
            coordinator_id = case.daemon.status().coordinator_id
            matched = inspect_coordinator_result_recovery(
                coordinator, expected_root_id=coordinator_id,
                agent_results=observation.to_dict()["value"]["results"],
            )
            assert matched.availability == "available", matched.reason
            missing = inspect_coordinator_result_recovery(
                coordinator, expected_root_id=coordinator_id, agent_results=[],
            )
            assert missing.availability == "unavailable"
            assert "matching agent proof" in missing.reason
            from loom.queue.errors import QueueConflictError
            with pytest.raises(QueueConflictError, match="cohort changed"):
                require_result_recovery(
                    case.agent_root, expected_root_id=identity,
                    role="agent", agent_results=[],
                )
            require_result_recovery(
                case.agent_root, expected_root_id=identity, role="agent",
                agent_results=observation.to_dict()["value"]["results"],
            )
            settled = inspect_service_settlement(case.agent_root, expected_root_id=identity)
            assert not settled.value["settled"]
            assert "local_assignment_or_release" in settled.value["wait_reasons"]
            # External result-file mutation must refuse, without repairing bytes.
            path = case.agent_root / "assignments" / results[0]["assignment_id"] / "worker-result.json"
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"\n")
                refused = inspect_agent_result_recovery(case.agent_root, expected_root_id=identity)
                assert refused.availability == "unavailable"
                assert "digest changed" in refused.reason
                assert path.read_bytes() == original + b"\n"
            finally:
                path.write_bytes(original)
            release.set()
            assert case.client.wait("recover-result", timeout_seconds=30).state.value == (
                "CANCELLED" if cancelled else "SUCCEEDED"
            )
        finally:
            resume_completion.set()
            release.set()


def test_live_worker_cannot_qualify_for_result_recovery(monkeypatch):
    with _service(monkeypatch, memory=2 * 1024**3) as case:
        gate, _, _ = _submit_gated(case, "still-running")
        try:
            _eventually(lambda: gate.exists() and list(gate.glob("*.started")))
            fact = inspect_agent_result_recovery(
                case.agent_root, expected_root_id=_read_remote_agent_root_id(case.agent_root),
            )
            assert fact.availability == "unavailable"
            assert "containment" in fact.reason or "durable result" in fact.reason
        finally:
            _release_gate(gate)
        assert case.client.wait("still-running", timeout_seconds=30).state.value == "SUCCEEDED"

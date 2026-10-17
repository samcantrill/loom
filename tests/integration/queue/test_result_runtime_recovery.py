"""Native recovery eligibility never equates completed work with settlement."""
from threading import Event

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


def test_retained_success_is_recoverable_but_not_settled(monkeypatch):
    entered, release = Event(), Event()
    retain = _shared_publication.retain

    def hold(workspace, result):
        entered.set()
        assert release.wait(60)
        return retain(workspace, result)

    monkeypatch.setattr(_shared_publication, "retain", hold)
    with _service(monkeypatch, shared=True) as case:
        try:
            _submit(case, "recover-result")
            assert entered.wait(20), case.failures
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
            assert case.client.wait("recover-result", timeout_seconds=30).state.value == "SUCCEEDED"
        finally:
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

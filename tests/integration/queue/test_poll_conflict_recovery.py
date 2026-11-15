"""Stopped-owner repair against real authenticated coordinator poll receipts."""
from dataclasses import replace

import pytest

from loom.queue._poll_recovery import recover_wait_poll
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue.errors import QueueConflictError, QueueServiceError
from .test_concurrent_outbound_agent import _service, _rows, _submit

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("outcome", ["wait", "assignment"])
def test_conflicting_poll_requires_terminal_wait_and_preserves_history(monkeypatch, outcome):
    with _service(monkeypatch) as case:
        case.stop.set()
        case.thread.join(20)
        assert not case.thread.is_alive()
        owner = LocalDaemonAgentHttpClient(case.config.client)
        try:
            owner._resume_pending_poll(wait_timeout_ms=100)
            journal = owner._require_journal()
            session = journal.active_session()
            sequence = journal.next_poll_sequence(session.session_id)
            original = dict(session_id=session.session_id,
                            availability_revision=session.availability_revision,
                            sequence=sequence, wait_timeout_ms=100)
            if outcome == "assignment":
                _submit(case, "retained-delivery")
            # Reproduce the observed split evidence through native boundaries:
            # the coordinator has consumed the sequence before the local variant.
            receipt = owner._call("poll", original)
            if outcome == "assignment":
                for _ in range(100):
                    if receipt["result"] == "assignment":
                        break
                    journal.prepare_poll(session.session_id, original["availability_revision"], sequence, original)
                    journal.complete_poll(session.session_id, sequence, receipt)
                    sequence += 1
                    original["sequence"] = sequence
                    receipt = owner._call("poll", original)
            assert receipt["result"] == outcome
            current = journal.current_resource_offer(session.session_id)
            owner.publish_offer(replace(current, availability_revision="changed-capacity"),
                                idempotency_key="changed-offer",
                                expected_availability_revision=session.availability_revision)
            pending = {**original, "availability_revision": "changed-capacity"}
            journal.prepare_poll(session.session_id, "changed-capacity", sequence, pending)
            with pytest.raises(QueueConflictError):
                owner._resume_pending_poll(wait_timeout_ms=100)
            args = dict(operation_id="repair-1", sequence=sequence,
                        committed_revision=original["availability_revision"], wait_timeout_ms=100)
            with pytest.raises(QueueServiceError, match="already locked"):
                recover_wait_poll(case.config.client, **args)
        finally:
            owner.close()
        # Submitted-container hosts carry explicit inventory. Recovery's
        # authentication client must not inherit any execution selection.
        repair_config = replace(case.config.client, resource_inventory=case.config.client.execution_inventory)
        before = _rows(case.agent_root / "control.sqlite", "SELECT * FROM agent_poll_state_local")
        with pytest.raises(QueueConflictError):
            recover_wait_poll(repair_config, **{**args, "committed_revision": "wrong-revision"})
        assert _rows(case.agent_root / "control.sqlite", "SELECT * FROM agent_poll_state_local") == before
        if outcome == "assignment":
            with pytest.raises(QueueConflictError, match="no-delivery"):
                recover_wait_poll(repair_config, **args)
            assert _rows(case.agent_root / "control.sqlite", "SELECT * FROM agent_poll_state_local") == before
            return
        result = recover_wait_poll(repair_config, **args)
        assert result["state"] == "reconciled"
        assert result["proof"] == {**receipt, "state": "committed"}
        assert recover_wait_poll(repair_config, **args) == result
        with pytest.raises(QueueConflictError, match="selection changed"):
            recover_wait_poll(repair_config, **{**args, "sequence": sequence + 1})
        owner = LocalDaemonAgentHttpClient(case.config.client)
        try:
            assert owner._require_journal().pending_poll() is None
            assert owner.next_poll_sequence(session.session_id) == sequence + 1
            with pytest.raises(QueueConflictError):
                owner._call("poll", pending)
            # A delayed old request still cannot become a new assignment.
            try:
                assert owner._call("poll", original) == receipt
            except QueueConflictError:
                pass  # Capacity has changed; rejection is also safe.
            owner.shutdown_clean()
        finally:
            owner.close()
        _submit(case, "after-repair")
        case.stop.clear()
        from threading import Thread
        from loom.queue import LocalDaemonAdmissionState
        case.thread = Thread(target=case.serve)
        case.thread.start()
        assert case.client.wait("after-repair", timeout_seconds=30).state is LocalDaemonAdmissionState.SUCCEEDED


def test_poll_recovery_cli_dispatches_explicit_selection(monkeypatch, capsys):
    from types import SimpleNamespace
    from pathlib import Path
    import json
    from loom.cli.main import main
    from loom.queue import deployment, _poll_recovery

    selected = object()
    calls = []
    monkeypatch.setattr(deployment, "load_outbound_agent_service_config",
                        lambda config, env_file: SimpleNamespace(client=selected))

    def recover(config, **kwargs):
        assert config is selected
        calls.append(kwargs)
        return {"state": "reconciled", "sequence": kwargs["sequence"]}

    monkeypatch.setattr(_poll_recovery, "recover_wait_poll", recover)
    assert main(["queue", "agent-recover-poll", str(Path("/protected/agent.json")),
                 "--operation-id", "repair", "--sequence", "123",
                 "--committed-availability-revision", "original", "--wait-timeout-ms", "5000",
                 "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["state"] == "reconciled"
    assert calls == [dict(operation_id="repair", sequence=123,
                          committed_revision="original", wait_timeout_ms=5000)]

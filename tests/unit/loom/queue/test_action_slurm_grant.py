"""SLURM grants join the native action claim in the existing control transaction."""

from types import SimpleNamespace

from loom.pipeline.stores.authority import (
    ActionProducerBinding,
    CancellationEpochRequest,
)
from loom.queue.local_daemon_execution import LocalDaemonExecution
from tests.unit.loom.queue.test_action_results import _store
from tests.integration.authority.test_action_result_binding import _consumer
from tests.integration.authority.test_action_producer_cancellation import _prepare


def test_slurm_shared_grant_and_start_use_exact_live_demand(tmp_path, monkeypatch):
    actions = _store(tmp_path)
    with actions.connection() as conn:
        conn.execute(
            "CREATE TABLE managed_admissions(run_uri TEXT, cancellation_operation_id TEXT)"
        )
    uri, authority, _, _ = _consumer(tmp_path, "embedded")
    selected = actions.select(
        run_uri=uri,
        node="producer",
        scope={},
        identity={"digest": "key"},
        attempt_id="producer-1",
    )
    claim_id = selected["claim"]["claim_id"]
    actions.select(
        run_uri="run://consumer", node="renamed", scope={}, identity={"digest": "key"}
    )
    binding = ActionProducerBinding(claim_id, "producer", "producer-1")
    authority.bind_action_producer(uri, binding)
    _prepare(authority, uri, "producer")
    authority.bind_prepared_attempt(
        uri, assignment_id="slurm-assignment", attempt_id="producer-1"
    )
    actions.detach_graph(uri, "cancel-original")
    with actions.connection() as conn:
        conn.execute(
            "INSERT INTO managed_admissions VALUES (?, 'cancel-original')", (uri,)
        )
    authority.install_cancellation_epoch(
        uri,
        CancellationEpochRequest(
            operation_id="cancel-original",
            coordinator_id="coordinator",
            run_uri=uri,
            stage_names=("producer",),
        ),
    )
    record = SimpleNamespace(
        input_ready=True,
        fence=None,
        state="inputs_ready",
        assignment=SimpleNamespace(run_uri=uri, attempt_id="producer-1"),
    )
    execution = object.__new__(LocalDaemonExecution)
    monkeypatch.setattr(
        execution,
        "config",
        SimpleNamespace(control_database=tmp_path / "actions.sqlite"),
        raising=False,
    )
    monkeypatch.setattr(execution, "_slurm_authorized_record", lambda *args: record)
    monkeypatch.setattr(execution, "_remote_authority", lambda run_uri: authority)
    consumed = []

    def mark_granted(assignment_id, incarnation, fence):
        record.fence, record.state = fence, "granted"

    monkeypatch.setattr(
        execution,
        "slurm_assignments",
        SimpleNamespace(
            mark_granted=mark_granted,
            consume_start=lambda assignment_id: consumed.append(assignment_id) or True,
        ),
        raising=False,
    )
    request = dict(
        principal_id="slurm-agent",
        credential_id="credential",
        assignment_id="slurm-assignment",
        incarnation="incarnation",
    )
    fence = execution.slurm_grant(**request)
    assert actions.claim(claim_id)["fencing_token"] == fence
    assert actions.claim(claim_id)["assignment_id"] == "slurm-assignment"
    assert execution.slurm_start_permit(**request, fence=fence)
    actions.detach_graph("run://consumer", "cancel-final")
    authority.release_action_producer(uri, binding)
    assert not execution.slurm_start_permit(**request, fence=fence)
    assert consumed == ["slurm-assignment"]
    assert (
        execution.slurm_grant(**request) == fence
    )  # Retained grant reply is idempotent; start is revoked.

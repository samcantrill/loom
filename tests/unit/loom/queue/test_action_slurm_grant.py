"""Slurm grant projection preserves exact shared-action demand during cancellation."""

import sqlite3
from types import SimpleNamespace

import pytest

from loom.pipeline.stores.authority import (
    ActionProducerBinding,
    CancellationEpochRequest,
)
from tests.support.slurm_bootstrap import registered_bootstrap
from tests.unit.loom.queue.test_action_results import _store
from tests.integration.authority.test_action_result_binding import _consumer
from tests.integration.authority.test_action_producer_cancellation import _prepare


@pytest.mark.parametrize("request_id, interrupted", [(None, False), ("live-request", False), ("live-request", True)])
def test_slurm_shared_grant_and_start_use_exact_live_demand(tmp_path, request_id, interrupted):
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
        state="accepted",
        assignment=SimpleNamespace(run_uri=uri, attempt_id="producer-1"),
    )
    from tests.unit.loom.queue.test_remote_stage_execution import _profile, _request
    record.delivery = _request(_profile(tmp_path))
    consumed = []

    def mark_granted(assignment_id, incarnation, fence):
        if interrupted and not consumed_projection:
            consumed_projection.append(fence)
            raise OSError("projection interrupted")
        record.fence, record.state = fence, "granted"

    consumed_projection: list[str] = []

    def grant(*args, **kwargs):
        fence = authority.grant_prepared_attempt(*args, **kwargs)
        if interrupted:
            actions.detach_graph("run://consumer", "cancel-final")
        return fence

    execution = registered_bootstrap(
        record, assignment_id="slurm-assignment", incarnation="incarnation",
        connect=lambda: sqlite3.connect(tmp_path / "actions.sqlite"),
        authority_for=lambda _: SimpleNamespace(grant_prepared_attempt=grant), mark_granted=mark_granted,
        consume_start=lambda assignment_id, **kwargs: consumed.append(assignment_id) or True,
    )
    request = dict(
        principal_id="slurm-agent",
        credential_id="credential",
        assignment_id="slurm-assignment",
        incarnation="incarnation",
    )
    if interrupted:
        with pytest.raises(OSError, match="projection interrupted"):
            execution.slurm_grant(**request)
        assert actions.claim(claim_id)["fencing_token"] == consumed_projection[0]
        assert record.fence is None
        assert actions.claim(claim_id)["state"] == "settling"
        # The authority won before the final demand detached. A fresh
        # coordinator must restore its fence without reviving that claim.
        restarted = registered_bootstrap(
            record, assignment_id="slurm-assignment", incarnation="incarnation",
            connect=lambda: sqlite3.connect(tmp_path / "actions.sqlite"), authority_for=lambda _: authority,
            mark_granted=mark_granted, consume_start=lambda *a, **kw: pytest.fail("cancelled start"),
        )
        assert restarted.settlement.needs_observation("slurm-assignment")
        retained = restarted.settlement.assignments.read("slurm-assignment")
        restarted.settlement.recover_grant(retained, authority)
        assert record.fence == consumed_projection[0]
        assert actions.claim(claim_id)["state"] == "settling"
        assert not restarted.slurm_start_permit(**request, fence=consumed_projection[0], request_id=request_id)
        return
    fence = execution.slurm_grant(**request)
    assert actions.claim(claim_id)["fencing_token"] == fence
    assert actions.claim(claim_id)["assignment_id"] == "slurm-assignment"
    assert execution.slurm_start_permit(**request, fence=fence, request_id=request_id)
    actions.detach_graph("run://consumer", "cancel-final")
    authority.release_action_producer(uri, binding)
    assert not execution.slurm_start_permit(**request, fence=fence, request_id=request_id)
    assert consumed == ["slurm-assignment"]
    assert (
        execution.slurm_grant(**request) == fence
    )  # Retained grant reply is idempotent; start is revoked.

"""Native reasons preserve owner evidence across pure, CLI and wire projections."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping
from typing import cast, Any

from tests.integration.queue.test_operator_observations import owner as owner
from tests.integration.queue.test_agent_session_transport import (
    native_control_endpoint as native_control_endpoint,
)
import io
import json
from types import SimpleNamespace

import pytest

from loom.coordinator import (
    CoordinatorClient,
    CoordinatorConnectionDescription,
    RunObservation,
)
from loom.diagnostics.run_explanation import explain_run
from loom.diagnostics.run_inspection import (
    RunInspectionAxis,
    RunInspectionAxisName as Axis,
    RunInspectionResult,
    RunInspectionTruncation,
)
from loom.queue.local_daemon import (
    LocalDaemonOperation,
    LocalDaemonAdmission,
    LocalDaemonAdmissionState,
    LocalDaemonAdmissionDetail,
)
from loom.queue._coordinator_control import control_error
from tests.contracts.test_run_inspection_contract import _all_axes

pytestmark = pytest.mark.integration


def _fact(name=Axis.SCHEDULING, state="ready", code=None, **kw):
    return RunInspectionAxis(
        name,
        kw.get("owner", "native-owner"),
        kw.get("availability", "available"),
        state,
        17,
        "2026-10-07T00:00:00Z",
        kw.get("freshness", "current"),
        code,
    )


def _inspection(*facts):
    return RunInspectionResult(
        "file:///runs/explain",
        "2026-10-07T00:00:00Z",
        "SUCCEEDED",
        _all_axes(_fact(Axis.LIFECYCLE, "SUCCEEDED", owner="authority"), *facts),
        (),
        (),
        (
            RunInspectionTruncation("stages", 0, 0),
            RunInspectionTruncation("locations", 0, 0),
        ),
    )


def _admission():
    return LocalDaemonAdmission(
        "a",
        "q",
        "coordinator",
        "file:///runs/explain",
        "digest",
        "managed-stage",
        LocalDaemonAdmissionState.WAITING,
        "2026-10-07T00:00:00Z",
        "bind",
    )


def _observation(state, code=None):
    connection = CoordinatorConnectionDescription(
        "13", "unix", "owner", "epoch", (), (), (), ()
    )
    return RunObservation(
        "run-1",
        LocalDaemonOperation("run-1", "run", state, code, {}),
        None,
        None,
        connection,
    )


@pytest.mark.parametrize(
    ("fact", "family"),
    [
        (_fact(), "waiting_for_resources"),
        (_fact(code="incompatible_profile"), "incompatible_profile"),
        (
            _fact(Axis.ASSIGNMENT, "drained", "agent_disconnected_or_drained"),
            "agent_disconnected_or_drained",
        ),
        (_fact(Axis.TRANSFER_RESULT, "start_unknown"), "unknown_process_ownership"),
        (_fact(Axis.TRANSFER_RESULT, "result_durable"), "publication_pending"),
        (_fact(Axis.CANCELLATION, "settling"), "cancellation_awaiting_containment"),
        (
            _fact(
                Axis.SERVICE_HEALTH,
                "unavailable",
                "owner_status_unavailable",
                availability="unavailable",
            ),
            "owner_unavailable",
        ),
    ],
)
def test_reason_matrix_preserves_native_evidence(fact, family):
    explanation = explain_run(_inspection(fact))
    assert (family, fact) in explanation.reasons
    assert explanation.summary == "SUCCEEDED"
    assert fact.to_dict() in explanation.to_dict()["facts"]
    assert str(fact.revision) in explanation.format_text()


@pytest.mark.parametrize(
    ("state", "code", "family"),
    [
        ("pending", None, "preparation_incomplete"),
        ("failed", "preparation_child_failed", "preparation_failed"),
        ("conflict", "candidate_publication_failed", "publication_failed"),
    ],
)
def test_preparation_before_admission(state, code, family):
    result = explain_run(None, observation=_observation(state, code))
    assert result.reasons[0][0] == family
    assert result.reasons[0][1].code == code
    assert result.reasons[0][1].observed_at is None
    assert result.reasons[0][1].freshness == "unknown"


def test_refusal_requires_retained_native_error_and_missing_stays_missing():
    refused = explain_run(
        None, operation_id="refused", error_code="maintenance_in_progress"
    )
    missing = explain_run(None, operation_id="refused", error_code="not_found")
    assert refused.reasons[0][0] == "maintenance_refusal"
    assert missing.summary == "not_found" and not missing.reasons


def test_success_cleanup_stale_missing_and_unavailable_are_independent():
    cleanup = _fact(Axis.ASSIGNMENT, "logical_released", freshness="stale")
    result = explain_run(
        _inspection(cleanup),
        operation_id="run 1",
        deployment="my deployment.yaml",
        error_code="unavailable",
    )
    assert result.summary == "SUCCEEDED"
    assert ("cleanup_pending", cleanup) in result.reasons
    assert "stale" in result.format_text()
    assert "revision None" in result.format_text()
    assert (
        result.next_actions[0]
        == "loom runs follow --operation-id 'run 1' --deployment 'my deployment.yaml'"
    )
    assert "do not submit a replacement" in result.format_text()
    raw = _inspection(cleanup)
    assert RunInspectionResult.from_dict(raw.to_dict()) == raw
    legacy = _inspection()
    assert "evidence" not in legacy.to_dict()
    assert RunInspectionResult.from_dict(legacy.to_dict()) == legacy


def test_owner_rows_supply_reasons_without_leaking_journal_payloads():
    admission = _admission()
    detail = LocalDaemonAdmissionDetail(
        admission=admission,
        authority={},
        owners={
            "scheduling": {
                "owner": "scheduler",
                "availability": "available",
                "state": "populated",
                "freshness": "current",
                "revision": 4,
                "work": [
                    {
                        "state": "ready",
                        "diagnostic": "incompatible_profile",
                        "private": "/secret",
                    }
                ],
            },
            "execution": {
                "owner": "agent",
                "availability": "available",
                "state": "populated",
                "freshness": "current",
                "revision": 5,
                "journal": [
                    {"state": "result_durable", "process_execution_id": "private"}
                ],
            },
        },
    )
    result = explain_run(_inspection(), detail=detail)
    assert {family for family, _ in result.reasons} >= {
        "incompatible_profile",
        "publication_pending",
    }
    assert "private" not in json.dumps(result.to_dict())
    assert "/secret" not in json.dumps(result.to_dict())


def test_client_retains_success_when_inspection_owner_fails(monkeypatch):
    observation = replace(
        _observation("applied"),
        admission=SimpleNamespace(
            state=SimpleNamespace(value="SUCCEEDED"),
            revision=5,
            accepted_at="2026-10-07T00:00:00Z",
            blocked_reason=None,
        ),
    )

    def steps(*args, **kwargs):
        yield observation
        raise control_error("unavailable", "inspect_run", {})

    client = CoordinatorClient.from_unix_socket("/not-contacted")
    monkeypatch.setattr(client, "_native_call", lambda *a, **kw: observation.connection)
    monkeypatch.setattr(client, "_run_observation_steps", steps)
    result = client.explain_run("run-1")
    assert result.summary == "SUCCEEDED"
    assert "owner_unavailable" in {family for family, _ in result.reasons}


@pytest.mark.optional_dependency
def test_cli_python_same_projection_and_missing_do_not_initialize(
    tmp_path, monkeypatch
):
    from loom.cli.main import main
    from loom.deployment import connect_deployment, load_deployment
    from tests.integration.config.test_cli_run_observation import _owner, _run, _counts

    with _owner(tmp_path) as (path, daemon):
        assert _run(path, identity="explain-me")[0] == 0
        with connect_deployment(load_deployment(path)) as client:
            client.observe_run("explain-me", timeout_seconds=30)
            python = client.explain_run("explain-me", deployment=str(path))
        before = _counts(daemon)
        import loom.deployment as deployment

        monkeypatch.setattr(
            deployment,
            "_bind",
            lambda *a, **k: pytest.fail("observer initialized services"),
        )
        output = io.StringIO()
        assert (
            main(
                [
                    "runs",
                    "explain",
                    "--operation-id",
                    "explain-me",
                    "--deployment",
                    str(path),
                    "--format",
                    "json",
                ],
                stdout=output,
            )
            == 0
        )
        cli = json.loads(output.getvalue())["result"]
        assert cli["summary"] == python.summary == "SUCCEEDED"
        assert cli["next_actions"] == list(python.next_actions)
        output = io.StringIO()
        assert (
            main(
                [
                    "runs",
                    "explain",
                    "--operation-id",
                    "missing",
                    "--deployment",
                    str(path),
                    "--format",
                    "json",
                ],
                stdout=output,
            )
            != 0
        )
        assert json.loads(output.getvalue())["result"]["summary"] == "not_found"
        assert _counts(daemon) == before


@pytest.mark.parametrize("compatible", [False, True])
def test_native_ready_work_reports_profile_compatibility(tmp_path, compatible):
    from loom.queue.local_daemon import (
        LocalDaemon,
        LocalDaemonConfig,
        LocalDaemonAdmission,
        LocalDaemonAdmissionState,
    )
    from loom.queue.local_daemon_execution import build_local_daemon_owner_views
    from loom.queue._remote_stage_execution import ResidentProfileDescriptor
    from tests.unit.loom.queue.test_managed_local import _seed_stage_work, _assignment

    config = LocalDaemonConfig(
        tmp_path / "coordinator",
        None,
        tmp_path / "runs",
        None,
        cpu_capacity=0,
        remote_profiles=(
            ResidentProfileDescriptor(
                "p", "1", "test-project", "test-environment", "test-executor"
            ),
        )
        if compatible
        else (),
    )
    LocalDaemon.initialize(config)
    assignment = _assignment()
    _seed_stage_work(config.execution_database, assignment)
    admission = LocalDaemonAdmission(
        "admission-1",
        "q",
        "coordinator",
        assignment.run_uri,
        "digest",
        "managed-stage",
        LocalDaemonAdmissionState.WAITING,
        "2026-10-07T00:00:00Z",
        "bind",
    )
    import sqlite3

    with sqlite3.connect(config.control_database) as conn:
        coordinator_id = conn.execute(
            "SELECT value FROM root_metadata WHERE key = 'stable_id'"
        ).fetchone()[0]
    agent_id = None
    view = build_local_daemon_owner_views(
        config, (admission,), coordinator_id=coordinator_id, agent_id=agent_id
    )[0]
    scheduling = cast(Mapping[str, Any], view["scheduling"])
    assert scheduling["availability"] == "available"
    assert scheduling["work"][0]["diagnostic"] == (
        None if compatible else "incompatible_profile"
    )


@pytest.mark.parametrize("case", ["occupancy", "drained", "disconnected"])
def test_assignment_agent_reason_uses_native_session_not_capacity(
    owner, monkeypatch, case
):
    from tests.integration.queue.test_operator_observations import offer, drain

    daemon, agent, session, operator = owner
    offer(agent, session, busy=case == "occupancy")
    if case == "drained":
        operator.control_agent(drain(session))
    if case == "disconnected":
        monkeypatch.setattr(daemon, "_clock", lambda: "2099-01-01T00:00:00Z")
    admission = _admission()
    detail = LocalDaemonAdmissionDetail(
        admission=admission,
        authority={},
        owners={
            "assignment": {
                "owner": "coordinator-assignments",
                "availability": "available",
                "state": "populated",
                "freshness": "current",
                "assignments": [{"agent_id": session.agent_id, "state": "running"}],
            }
        },
    )
    monkeypatch.setattr(daemon, "_admission", lambda aid: admission)
    monkeypatch.setattr(
        "loom.queue.local_daemon_execution.build_local_daemon_owner_views",
        lambda *args, **kwargs: ({"authority": {}, **detail.owners},),
    )
    observed = daemon.admission(admission.admission_id)
    facts = explain_run(_inspection(), detail=observed).facts
    agent_fact = next(
        fact for fact in facts if fact.owner == f"agent-session:{session.agent_id}"
    )
    assert agent_fact.state == ("connected" if case == "occupancy" else case)
    assert (agent_fact.code is None) == (case == "occupancy")
    assert agent_fact.observed_at is not None
    assert agent_fact.freshness == ("retained" if case == "disconnected" else "current")


def test_wait_projection_is_not_resource_wait_and_text_retains_ids_and_truncation():
    fact = _fact(Axis.SCHEDULING, "wait", "authority_state_mismatch")
    raw = replace(
        _inspection(fact),
        admission_id="admission-1",
        queue_item_id="queue-1",
        truncation=(
            RunInspectionTruncation("stages", 3, 0),
            RunInspectionTruncation("locations", 0, 0),
        ),
    )
    explanation = explain_run(raw)
    assert "waiting_for_resources" not in {family for family, _ in explanation.reasons}
    assert "admission: admission-1" in explanation.format_text()
    assert "queue item: queue-1" in explanation.format_text()
    assert "stages: 0/3 facts returned" in explanation.format_text()


@pytest.mark.parametrize("transport", ["unix", "https"])
def test_direct_and_transports_explain_same_native_detail(
    native_control_endpoint, monkeypatch, transport
):
    from loom.queue import LocalDaemonSocketServer

    daemon, _http, connection_path, _credentials = native_control_endpoint
    admission = _admission()
    detail = LocalDaemonAdmissionDetail(
        admission,
        {},
        {
            "execution": {
                "owner": "agent",
                "availability": "available",
                "state": "populated",
                "revision": 9,
                "observed_at": "2026-10-07T00:00:00Z",
                "freshness": "stale",
                "journal": [{"state": "result_durable"}],
            }
        },
    )
    monkeypatch.setattr(daemon, "admission", lambda admission_id: detail)
    socket = LocalDaemonSocketServer(daemon, daemon.config.endpoint)
    socket.start()
    try:
        with (
            CoordinatorClient.from_unix_socket(daemon.config.endpoint)
            if transport == "unix"
            else CoordinatorClient.from_connection_file(connection_path)
        ) as client:
            remote = client.admission(admission.admission_id)
        direct = explain_run(_inspection(), detail=detail)
        transported = explain_run(_inspection(), detail=remote)
        assert transported.to_dict() == direct.to_dict()
        assert "publication_pending" in {family for family, _ in transported.reasons}
        assert "stale" in transported.format_text()
    finally:
        socket.stop()


@pytest.mark.optional_dependency
def test_public_observation_retains_detail_after_inspection_interrupt(
    tmp_path, monkeypatch
):
    from loom.deployment import connect_deployment, load_deployment
    from tests.integration.config.test_cli_run_observation import _owner, _run, _counts

    with _owner(tmp_path) as (path, daemon):
        assert _run(path, identity="retain-detail")[0] == 0
        with connect_deployment(load_deployment(path)) as client:
            completed = client.observe_run("retain-detail", timeout_seconds=30)
            assert completed.detail is not None
            assert completed.detail.admission == completed.admission
            assert completed.inspection is not None
            before = _counts(daemon)
            retained = []
            read = client._native_call

            def capture(operation, *args, **kwargs):
                value = read(operation, *args, **kwargs)
                if operation == "admission":
                    retained.append(value)
                return value

            def interrupt(*args, **kwargs):
                raise KeyboardInterrupt()

            monkeypatch.setattr(client, "_native_call", capture)
            monkeypatch.setattr(client, "_inspect_run", interrupt)
            observation = client.observe_run("retain-detail", wait=False)
            assert len(retained) == 1
            assert observation.detail == retained[0]
            assert observation.admission == retained[0].admission
            assert observation.inspection is None
            assert "detail" not in observation.to_dict()
            explanation = explain_run(observation.inspection, observation=observation)
            assert explanation.summary == "SUCCEEDED"
            scheduling = next(
                fact for fact in explanation.facts if fact.name is Axis.SCHEDULING
            )
            assert scheduling.owner == retained[0].owners["scheduling"]["owner"]
            assert scheduling.revision == retained[0].owners["scheduling"]["revision"]
            assert scheduling.availability == "available"
        assert _counts(daemon) == before

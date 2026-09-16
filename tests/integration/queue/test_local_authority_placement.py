"""Managed publication, inspection and retry with local authority/shared files."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest

from loom.coordinator import CoordinatorClient
from loom.diagnostics.run_inspection import RunInspectionAxisName, RunInspectionResult
from loom.diagnostics.run_inspection import projection_callable, RunInspectionProjection
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import AuthoritySchemaError, LocalRunStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonSocketServer
from loom.queue.deployment import load_coordinator_service_config
from tests.integration.queue.test_preparation_operations import _request, _service


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_native_preparation_restart_inspection_and_explicit_failed_retry(
    tmp_path: Path,
) -> None:
    _service(tmp_path, local=True)
    state_root = tmp_path / "local-authority"
    state_root.mkdir(mode=0o700)
    config_path = tmp_path / "coordinator.json"
    config = json.loads(config_path.read_text())
    config["authority"]["state_root"] = str(state_root)
    config_path.write_text(json.dumps(config))
    pipeline = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(pipeline.read_text())
    stage = authored["pipeline"]["stages"][0]
    stage["factory"]["_target_"] = (
        "tests.support.pipeline_execution_stages.FailOnceThenProduceStage"
    )
    stage["config"] = {"marker_path": str(tmp_path / "failed-once")}
    pipeline.write_text(json.dumps(authored))
    service = load_coordinator_service_config(config_path)
    LocalDaemon.initialize_deployment(service.daemon)

    def start(service):
        daemon = LocalDaemon(
            service.daemon, preparation=CoordinatorPreparation(service)
        )
        server = LocalDaemonSocketServer(
            daemon,
            service.daemon.endpoint,
            inspect_run=projection_callable(
                daemon=daemon, run_store=LocalRunStore(service.daemon.run_store_root)
            ),
        )
        daemon.start()
        server.start()
        return daemon, server

    daemon, server = start(service)
    try:
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            accepted = client.prepare_run(_request())
            completed = client.wait_operation(
                accepted.operation_id, timeout_seconds=25
            ).operation
            assert completed.state == "applied", completed.to_dict()
            assert isinstance(completed.result, Mapping)
            receipt = completed.result["prepared_run"]
            assert isinstance(receipt, Mapping)
            run_uri = receipt["run_uri"]
            assert isinstance(run_uri, str)
            factory = service.daemon.coordinator_authority_factory
            assert factory is not None
            snapshot = factory(run_uri).open_run(run_uri)
            assert snapshot.status is RunStatus.PLANNED
            inspected = RunInspectionProjection(daemon=daemon).inspect(run_uri)
            assert isinstance(inspected, RunInspectionResult)
            assert (
                next(
                    axis
                    for axis in inspected.axes
                    if axis.name is RunInspectionAxisName.LIFECYCLE
                ).state
                == "PLANNED"
            )
            request = LocalDaemonAdmissionRequest("execute-target", run_uri)
            client.submit(request)
            failed = client.wait("execute-target", timeout_seconds=25)
            assert failed.state.value == "FAILED", failed
            failed_snapshot = factory(run_uri).open_run(run_uri)
            assert failed_snapshot.stages[0].attempts[0].status is StageStatus.FAILED
            assert client.submit(request) == failed
        server.stop()
        daemon.stop()
        service = load_coordinator_service_config(config_path)
        factory = service.daemon.coordinator_authority_factory
        assert factory is not None
        assert factory(run_uri).open_run(run_uri) == failed_snapshot
        daemon, server = start(service)
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            assert client.prepare_run(_request()) == completed
            assert client.submit(request) == failed
            client.submit(
                LocalDaemonAdmissionRequest(
                    "execute-target",
                    run_uri,
                    retry_failed_revision=failed.revision,
                )
            )
            succeeded = client.wait("execute-target", timeout_seconds=25)
            assert succeeded.state.value == "SUCCEEDED", succeeded
            final = factory(run_uri).open_run(run_uri)
            assert final.status is RunStatus.SUCCEEDED
            assert [item.attempt for item in final.stages[0].attempts] == [1, 2]
            assert final.stages[0].attempts[0] == failed_snapshot.stages[0].attempts[0]
            inspected = client.inspect_run(run_uri)
            assert isinstance(inspected, RunInspectionResult)
            assert (
                next(
                    axis
                    for axis in inspected.axes
                    if axis.name is RunInspectionAxisName.LIFECYCLE
                ).state
                == "SUCCEEDED"
            )
            assert inspected.stages[0].attempt == 2
            assert str(state_root) not in json.dumps(inspected.to_dict())
        assert not list(service.daemon.run_store_root.rglob("*.sqlite*"))
        # Both the preparation child and its published target use the same owner.
        databases = list(state_root.rglob("authority.sqlite3"))
        assert len(databases) == 2
        assert service.daemon.agent_root is not None
        requests = list(service.daemon.agent_root.rglob("resident.sqlite"))
        assert len(requests) == 3
        for path in requests:
            with sqlite3.connect(path) as conn:
                request_json = conn.execute(
                    "SELECT value_json FROM request"
                ).fetchone()[0]
                assert str(state_root) not in request_json
    finally:
        server.stop()
        daemon.stop()
    for database in databases:
        database.unlink()
    with pytest.raises(AuthoritySchemaError, match="missing"):
        factory(run_uri)
    assert not list(state_root.rglob("authority.sqlite3"))

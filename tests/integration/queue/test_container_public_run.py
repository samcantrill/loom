"""Configured resident container delivery through the public run lifecycle."""

import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Mapping

import loom
import pytest
from loom.coordinator import RunRequest
from tests.integration.queue.test_service_lifetime import _selection
from tests.integration.queue.test_preparation_operations import _request
from examples.execution.containers.docker.daemon_fixture import fake_docker

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@contextmanager
def _backend(kind, root):
    if kind == "docker":
        with fake_docker(root / "fake") as value:
            yield value
    elif kind == "apptainer":
        from examples.execution.containers.apptainer_fixture import fake_apptainer

        with fake_apptainer() as binding:
            yield binding, []
    else:
        yield None, []


@pytest.mark.parametrize("kind", ["native", "docker", "apptainer"])
def test_container_public_run_and_retained_replay(tmp_path_factory, kind):
    tmp_path = tmp_path_factory.mktemp("worker")
    selection = _selection(tmp_path)
    cache = tmp_path / "local-cache"
    with _backend(kind, tmp_path) as (binding, calls):
        if binding is not None:
            cache.mkdir(mode=0o700)
            binding = {**binding, "container": {**binding["container"], "mounts": [
                {"source": str(cache), "target": "/loom/cache", "mode": "rw"}
            ]}}
            agent_path = tmp_path / "agent.json"
            agent = json.loads(agent_path.read_text())
            agent["resident_profiles"][0]["container"] = binding
            agent["resident_profiles"][0]["temporary_mounts"] = ["/loom/cache"]
            agent_path.write_text(json.dumps(agent))
        result = loom.run(
            RunRequest(_request(), "target-queue"),
            deployment=selection,
            timeout_seconds=60,
        )
        assert result.observation.admission is not None
        assert isinstance(result.cleanup["coordinator"], Mapping)
        assert result.observation.admission.state.value == "SUCCEEDED"
        assert result.cleanup["coordinator"]["state"] == "stopped"
        if binding is not None:
            assert list((cache / "attempts").iterdir()) == []
            with sqlite3.connect(tmp_path / "deployment/agent/supervisor/supervisor.sqlite") as conn:
                rows = conn.execute("SELECT state, temporary_storage_pending, temporary_storage_error FROM launches").fetchall()
            assert len(rows) == 2  # Preparation and the pipeline stage.
            assert all(row == ("contained", 0, None) for row in rows)
        from loom.io.uris import uri_to_path

        run_root = uri_to_path(result.observation.admission.run_uri)
        assert json.loads((run_root / "artifacts/produce/data.json").read_text()) == {
            "value": 41
        }
        result_record = json.loads(
            (run_root / "stages/produce/worker_result.json").read_text()
        )["worker_result"]
        metadata = result_record["executor_metadata"]
        if kind == "docker":
            assert metadata["managed_backend_success"] is True
            assert "managed_successful_exit" not in metadata
            assert metadata["executor"] == "docker"
        else:
            assert metadata["managed_successful_exit"] is True
        again = loom.run(
            RunRequest(_request(), "target-queue"),
            deployment=selection,
            timeout_seconds=60,
        )
        assert again.observation.admission is not None
        assert isinstance(again.cleanup["coordinator"], Mapping)
        assert (
            again.observation.admission.admission_id
            == result.observation.admission.admission_id
        )
        assert again.cleanup["coordinator"]["state"] == "stopped"
        if kind == "docker":
            workers = [
                call
                for call in calls
                if call[0] == "create" and "loom.queue._resident_stage_worker" in call
            ]
            assert len(workers) == 2  # preparation and the target stage


@pytest.mark.parametrize("fault", ["storage", "cleanup", "science_and_cleanup"])
@pytest.mark.parametrize("delivery", ["local", "remote"])
def test_temporary_storage_failures_release_assignment_claims(tmp_path, fault, delivery):
    """Real parent/worker IPC, with storage faults injected in the process owner."""
    from examples.execution.containers.apptainer_fixture import fake_apptainer
    from loom.io.uris import uri_to_path
    from loom.queue._managed_local import AssignmentState

    if delivery == "remote":
        from tests.integration.queue.test_service_lifetime import _mixed_selection

        selection = _mixed_selection(tmp_path, "run", "run")
    else:
        selection = _selection(tmp_path)
    if fault == "science_and_cleanup":
        recipe = tmp_path / "projects/pipeline.yaml"
        value = json.loads(recipe.read_text())
        value["pipeline"]["stages"][0]["factory"]["_target_"] = (
            "tests.support.pipeline_execution_stages.ReportedFailureStage"
        )
        recipe.write_text(json.dumps(value))
    cache = tmp_path / "local-cache"
    cache.mkdir(mode=0o700)
    with fake_apptainer() as binding:
        fixture = Path(binding["options"]["command"]).parent / "sitecustomize.py"
        with fixture.open("a") as stream:
            stream.write(f'''
import errno
from loom.queue import _temporary_storage as storage
from loom.queue._remote_stage_execution import _ResidentAssignmentWorkspace as Workspace
prepare_storage = storage.prepare_assignment_storage
cleanup_storage = storage.cleanup_assignment_storage
def prepare(profile, *, workspace, agent_id):
    prepare_storage(profile, workspace=workspace, agent_id=agent_id)
    if Workspace.read_request(workspace).stage_name == "produce":
        for directory in storage.assignment_mounts(profile, workspace=workspace, agent_id=agent_id).values():
            (directory / "prepared").write_bytes(b"prepared sample")
        if {fault!r} == "storage":
            raise OSError(errno.ENOSPC, "injected cache storage exhaustion")
def cleanup(profile, *, workspace, agent_id):
    if Workspace.read_request(workspace).stage_name == "produce" and {fault!r} != "storage":
        raise PermissionError("injected temporary storage deletion failure")
    cleanup_storage(profile, workspace=workspace, agent_id=agent_id)
storage.prepare_assignment_storage = prepare
storage.cleanup_assignment_storage = cleanup
''')
        binding = {**binding, "container": {**binding["container"], "mounts": [
            {"source": str(cache), "target": "/loom/cache", "mode": "rw"}
        ]}}
        agent_path = tmp_path / "agent.json"
        agent = json.loads(agent_path.read_text())
        agent["resident_profiles"][0].update(container=binding, temporary_mounts=["/loom/cache"])
        agent_path.write_text(json.dumps(agent))
        if delivery == "remote":
            from loom.queue.deployment import load_outbound_agent_service_config

            profile = load_outbound_agent_service_config(agent_path).client.resident_profiles[0]
            coordinator_path = tmp_path / "coordinator.json"
            coordinator = json.loads(coordinator_path.read_text())
            coordinator["remote_profiles"] = [profile.descriptor.to_dict()]
            coordinator_path.write_text(json.dumps(coordinator))
        result = loom.run(
            RunRequest(_request(), "storage-failure"), deployment=selection, timeout_seconds=60
        )
        assert result.observation.admission is not None
        assert result.observation.admission.state.value == "FAILED"
        run_root = uri_to_path(result.observation.admission.run_uri)
        worker = json.loads((run_root / "stages/produce/worker_result.json").read_text())["worker_result"]
        assert worker["status"] == "FAILED"
        if fault == "storage":
            assert "injected cache storage exhaustion" in worker["failure"]["message"]
            assert list((cache / "attempts").iterdir()) == []
        else:
            assert "deletion failure" in worker["executor_metadata"]["temporary_storage_cleanup_error"]
            assert len(list((cache / "attempts").iterdir())) == 1
            if fault == "science_and_cleanup":
                assert "deletion failure" not in worker["failure"]["message"]
                assert worker["failure"]["exception_type"] == "loom.pipeline.execution.StageReportedFailure"
                assert worker["failure"]["details"]["domain_failure"] == {"record": {"items": [1, None, "safe"]}}
        agent_root = tmp_path / ("outbound" if delivery == "remote" else "deployment/agent")
        with sqlite3.connect(agent_root / "journal.sqlite") as conn:
            rows = conn.execute("SELECT state FROM assignments").fetchall()
        assert len(rows) == 2
        assert all(row[0] == AssignmentState.RELEASED.value for row in rows)
        assert isinstance(result.cleanup["coordinator"], Mapping)
        assert result.cleanup["coordinator"]["state"] == "stopped"

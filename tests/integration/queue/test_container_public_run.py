"""Configured resident container delivery through the public run lifecycle."""

import json
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
    with _backend(kind, tmp_path) as (binding, calls):
        if binding is not None:
            agent_path = tmp_path / "agent.json"
            agent = json.loads(agent_path.read_text())
            agent["resident_profiles"][0]["container"] = binding
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

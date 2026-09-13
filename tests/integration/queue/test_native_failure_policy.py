"""Preserved authored independent-branch behavior at the native lifecycle."""

from dataclasses import replace
import json
from copy import deepcopy

import pytest

from loom.coordinator import RunRequest
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from tests.integration.queue.test_run_operations import _two_stage_service, _request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize(
    "policy, second_status",
    [
        ("continue_independent", "SUCCEEDED"),
        ("stop_on_first_failure", "PENDING"),
    ],
)
def test_native_failure_policy_settles_unrelated_work(tmp_path, policy, second_status):
    service = _two_stage_service(tmp_path, failing=True)
    path = tmp_path / "projects" / "pipeline.yaml"
    config = json.loads(path.read_text())
    config["pipeline"]["stages"][1].pop("depends_on")
    after_ok = deepcopy(config["pipeline"]["stages"][1])
    after_ok["name"] = "after_ok"
    after_ok["depends_on"] = ["second"]
    after_failure = deepcopy(config["pipeline"]["stages"][1])
    after_failure["name"] = "after_failure"
    after_failure["depends_on"] = ["produce"]
    config["pipeline"]["stages"].extend([after_ok, after_failure])
    path.write_text(json.dumps(config))
    service = replace(service, daemon=replace(service.daemon, cpu_capacity=1))
    request = RunRequest(
        replace(
            _request(),
            run_options={
                "execution": {
                    "settings": {"max_parallel_stages": 2, "failure_policy": policy}
                },
            },
        ),
        "target-admission",
    )
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        daemon.start_run(request, principal_id="caller")
        operation = daemon.wait_operation("prepare-1", timeout=60).operation
        assert operation.state == "applied", operation
        admission = daemon._wait("target-admission", timeout_seconds=60)
        assert admission.state.value == "FAILED"
        authority = SQLitePerRunAuthorityStore(admission.run_uri)
        stages = {
            stage.stage_name: stage
            for stage in authority.open_run(admission.run_uri).stages
        }
        assert stages["produce"].status.value == "FAILED"
        assert stages["second"].status.value == second_status
        assert ("after_ok" in stages) == (second_status == "SUCCEEDED")
        if second_status == "SUCCEEDED":
            assert stages["after_ok"].status.value == "SUCCEEDED"
        assert "after_failure" not in stages
        assert (stages["second"].latest_commit is not None) == (
            second_status == "SUCCEEDED"
        )
    finally:
        daemon.stop()

"""Candidate capture keeps submitted execution without an installed profile."""

from dataclasses import replace
import json

import pytest

from loom.fleet import _check_preflight
from loom.queue.preparation import PreparationChildInput
from loom.serialization import thaw_plain_data
from tests.integration.queue.test_preparation_operations import _service, _request
from tests.integration.queue.test_submitted_container_agents import _fixture

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("selected_inputs", [False, True])
def test_capture_submitted_candidate_without_resident_profile(tmp_path, monkeypatch, selected_inputs):
    from loom.fleet.self_tests import _check_input_locations
    from loom.queue.submitted_execution import SELECTED_INPUT_WORKER_CONTRACT
    _service(tmp_path)
    policy, execution, _ = _fixture(tmp_path)
    if selected_inputs:
        extra = tmp_path / "unselected"
        extra.mkdir()
        policy = replace(policy, worker_contracts=(SELECTED_INPUT_WORKER_CONTRACT,),
            shared_roots={**policy.shared_roots, "unselected": {
                "host_path": str(extra), "container_path": "/loom/unselected", "access": "ro",
                "qualification": {"kind": "input_directory"},
            }})
        execution = replace(execution, worker_contract=SELECTED_INPUT_WORKER_CONTRACT)
    config = tmp_path / "coordinator.json"
    declaration = json.loads(config.read_text())
    declaration.update(local_agent=None, remote_profiles=[],
        shared_roots=thaw_plain_data(policy.shared_roots), container_capabilities=[policy.capability.to_dict()])
    declaration["preparation"]["profiles"] = {
        "containers": {
            "container_policy_id": policy.policy_id, "allowed_source_roots": ["projects"],
            "source_modes": ["shared"], "runtime_options": {"executor": "local"},
            "configuration_policy": "shared", "shared_locations": [],
        },
    }
    monkeypatch.setattr(_check_preflight, "owner", lambda request: {"owner": "coordinator-id"})
    request = replace(_request(), preparation_profile="containers", execution=execution,
                      input_locations=_check_input_locations(execution))
    result = _check_preflight.capture({
        "name": "coordinator", "config": str(config), "expected_root_id": "coordinator-id",
        "candidate_declaration": declaration, "checks": {"cpu": request.to_dict()},
    })
    binding = PreparationChildInput.from_dict(result["bindings"]["cpu"])
    assert binding.profile_descriptor is None
    assert binding.execution == execution
    assert binding.container_capability is not None
    assert (policy.capability.permits(binding.container_capability) if selected_inputs
            else binding.container_capability == policy.capability)
    assert "unselected" not in binding.container_capability.shared_roots
    assert "unselected" not in binding.shared_scope["roots"]
    assert binding.input_receipt.root == "projects"
    assert binding.config_path == "pipeline.yaml"
    assert not (tmp_path / "runs/target-1").exists()

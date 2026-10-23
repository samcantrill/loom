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


def test_capture_submitted_candidate_without_resident_profile(tmp_path, monkeypatch):
    _service(tmp_path)
    policy, execution, _ = _fixture(tmp_path)
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
    request = replace(_request(), preparation_profile="containers", execution=execution)
    result = _check_preflight.capture({
        "name": "coordinator", "config": str(config), "expected_root_id": "coordinator-id",
        "candidate_declaration": declaration, "checks": {"cpu": request.to_dict()},
    })
    binding = PreparationChildInput.from_dict(result["bindings"]["cpu"])
    assert binding.profile_descriptor is None
    assert binding.execution == execution
    assert binding.container_capability == policy.capability
    assert binding.input_receipt.root == "projects"
    assert binding.config_path == "pipeline.yaml"
    assert not (tmp_path / "runs/target-1").exists()

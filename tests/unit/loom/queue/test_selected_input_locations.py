"""Request-selected inputs preserve authority without coupling unrelated roots."""

from dataclasses import replace

import pytest

from loom.pipeline.orchestration import SubmittedContainerRequirement
from loom.queue.errors import QueueServiceError
from loom.queue.preparation import PreparationChildInput, PrepareRunRequest, SharedInputReceipt
from loom.queue.shared_execution import stage_scope
from loom.queue.submitted_execution import (
    SELECTED_INPUT_WORKER_CONTRACT,
    SubmittedContainerCapability,
)
from tests.unit.loom.queue.test_submitted_execution import _capability, _execution, _policy, _request


def _location(alias):
    return {"kind": "loom.shared-location", "schema_version": 1, "root_id": alias, "path": "."}


def _catalog(tmp_path):
    base = _capability(tmp_path)
    return replace(base, worker_contracts=(SELECTED_INPUT_WORKER_CONTRACT,), shared_roots={
        **base.shared_roots,
        **{alias: {"container_path": "/loom/inputs/" + alias, "access": "ro",
                   "qualification": {"kind": "input_directory"}}
           for alias in ("alpha", "beta", "gamma")},
        "runs": {"container_path": "/loom/runs", "access": "rw",
                 "challenge": {"path": "challenge", "sha256": "b" * 64}},
    })


def _selected_policy(tmp_path):
    policy = _policy(tmp_path)
    profile = replace(policy.profiles["shared-container"], capability=_catalog(tmp_path))
    return replace(policy, profiles={"shared-container": profile})


def _selected_request(*aliases):
    return replace(_request(), execution=replace(_execution(), worker_contract=SELECTED_INPUT_WORKER_CONTRACT),
                   input_locations=tuple(_location(alias) for alias in aliases))


def test_request_retains_canonical_immutable_selection_and_legacy_encoding():
    request = _selected_request("beta", "alpha", "alpha")
    assert [item["root_id"] for item in request.input_locations] == ["alpha", "beta"]
    assert PrepareRunRequest.from_dict(request.to_dict()) == request
    with pytest.raises(TypeError):
        request.input_locations[0]["path"] = "changed"
    assert request.intent_digest("owner") != _selected_request("alpha").intent_digest("owner")
    assert "input_locations" not in _request().to_dict()
    with pytest.raises(QueueServiceError, match="v3"):
        replace(request, execution=_execution())
    with pytest.raises(QueueServiceError, match="sequence"):
        PrepareRunRequest.from_dict({**request.to_dict(), "input_locations": None})


def test_preparation_selects_only_requested_inputs_and_infrastructure(tmp_path):
    selected = _selected_policy(tmp_path).select(_selected_request("alpha", "beta"))["profile"]
    assert set(selected["shared_scope"]["roots"]) == {"alpha", "beta", "runs"}
    assert selected["shared_scope"]["locations"] == [_location("alpha"), _location("beta")]
    capability = SubmittedContainerCapability.from_dict(selected["container_capability"])
    assert set(capability.shared_roots) == {"alpha", "beta", "runs", "workloads"}
    execution = replace(_selected_request().execution, project_integration=None)
    binding = PreparationChildInput(
        "selection", "shared-container", "config/pipeline.yaml",
        SharedInputReceipt("sha256:" + "a" * 64, "projects", "capture"), None,
        execution=execution, shared_scope=selected["shared_scope"], container_capability=capability,
    )
    assert PreparationChildInput.from_dict(binding.to_dict()) == binding


@pytest.mark.parametrize("alias", ["unknown", "runs", "workloads"])
def test_unpermitted_or_writable_input_rejected_before_preparation(tmp_path, alias):
    with pytest.raises(QueueServiceError, match="authorized read-only"):
        _selected_policy(tmp_path).select(_selected_request(alias))


def test_stage_override_cannot_expand_retained_input_selection(tmp_path):
    profile = _selected_policy(tmp_path).select(_selected_request("alpha"))["profile"]
    with pytest.raises(QueueServiceError, match="outside the preparation selection"):
        stage_scope({"input": _location("beta")}, {}, profile["shared_scope"])


def test_preparation_preserves_read_only_capture_storage_without_mounting_unselected_inputs(tmp_path):
    policy = _selected_policy(tmp_path)
    profile = policy.profiles["shared-container"]
    capability = replace(profile.capability, shared_roots={**profile.capability.shared_roots,
        "captures": {"container_path": "/loom/captures", "access": "ro",
                     "challenge": {"path": "challenge", "sha256": "d" * 64}}})
    policy = replace(policy, profiles={"shared-container": replace(profile, capability=capability)})
    selected = policy.select(_selected_request("alpha"))["profile"]
    assert set(selected["shared_scope"]["roots"]) == {"alpha", "runs", "captures"}
    assert selected["shared_scope"]["locations"] == [_location("alpha")]


def test_worker_with_different_catalog_matches_selected_qualified_roots(tmp_path):
    catalog = _catalog(tmp_path)
    selected = catalog.select_roots({"alpha": catalog.shared_roots["alpha"]})
    execution = _selected_request().execution
    requirement = selected.requirement(execution)
    assert requirement.schema_version == 2
    assert SubmittedContainerRequirement.from_dict(requirement.to_dict()) == requirement
    assert catalog.satisfies(requirement)
    assert selected.satisfies(requirement)  # Neither beta nor gamma is needed.
    assert not replace(selected, environment_fingerprint="sha256:" + "9" * 64).satisfies(requirement)
    changed = replace(selected, shared_roots={**selected.shared_roots,
        "alpha": {**selected.shared_roots["alpha"], "container_path": "/loom/different"}})
    assert not changed.satisfies(requirement)
    assert not _capability(tmp_path).satisfies(requirement)  # An older worker cannot run v3.


def test_catalog_growth_does_not_change_request_or_selected_policy(tmp_path):
    policy = _selected_policy(tmp_path)
    request = _selected_request("alpha")
    before = policy.select(request)
    profile = policy.profiles["shared-container"]
    catalog = profile.capability
    grown = replace(catalog, shared_roots={**catalog.shared_roots,
        "delta": {**catalog.shared_roots["beta"], "container_path": "/loom/inputs/delta"}})
    after = replace(policy, profiles={"shared-container": replace(profile, capability=grown)}).select(request)
    assert before == after
    legacy = _capability(tmp_path)
    old_requirement = legacy.requirement(_execution())
    assert old_requirement.schema_version == 1
    assert not replace(legacy, shared_roots={**legacy.shared_roots,
        "extra": {"container_path": "/loom/extra", "access": "ro",
                  "challenge": {"path": "challenge", "sha256": "c" * 64}}}).satisfies(old_requirement)


def test_old_image_rejects_selected_input_contract_before_loading_worker(tmp_path, monkeypatch):
    import runpy
    import sys
    from loom.queue import submitted_execution

    monkeypatch.setattr(submitted_execution, "SUPPORTED_WORKER_CONTRACTS", (
        "resident-submitted-container-v1", "resident-submitted-container-v2",
    ))
    monkeypatch.setattr(runpy, "run_module", lambda *args, **kwargs: pytest.fail("older worker was entered"))
    command = submitted_execution.submitted_worker_command(_selected_request().execution, tmp_path)
    monkeypatch.setattr(sys, "argv", [command[0], *command[3:]])
    with pytest.raises(SystemExit, match="does not support required worker contract"):
        exec(command[2], {})
    assert SELECTED_INPUT_WORKER_CONTRACT in (tmp_path / "logs" / "stderr.log").read_text()


def test_action_reuse_joins_projected_capability_to_retained_preparation(tmp_path):
    from types import SimpleNamespace
    from loom.queue._action_result_resolution import _report_implementation
    from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE
    from loom.queue.submitted_execution import SUBMITTED_EXECUTION_SCOPE, submitted_implementation

    capability = _catalog(tmp_path)
    execution = _selected_request().execution
    shared = {"capability": "shared-execution-v1", "roots": {"alpha": capability.shared_roots["alpha"]},
              "locations": [_location("alpha")]}
    selected = capability.select_roots(shared["roots"])
    report = {"execution": execution.to_dict(), "container_capability": capability.to_dict(),
              "project_preparation": {"processor": dict(execution.project_integration)}}
    stage = SimpleNamespace(fingerprint_fields={
        SHARED_EXECUTION_SCOPE: shared,
        SUBMITTED_EXECUTION_SCOPE: {"execution": execution.to_dict(), "container_capability": selected.to_dict()},
    })
    assert _report_implementation(report, selected.requirement(execution), stage) == submitted_implementation(execution, selected)

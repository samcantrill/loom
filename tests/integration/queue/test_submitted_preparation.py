"""Selected execution survives native preparation, report decoding and publication."""

from copy import deepcopy
from dataclasses import replace
import json
from typing import Any, cast

import pytest

from loom.pipeline.context import StageContext
from loom.pipeline.orchestration import SubmittedContainerRequirement
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.specs import OutputSpec
from loom.pipeline.stores import LocalArtifactStore
from loom.preparation import PreparationStage, decode_preparation_report, load_preparation_report, prepare_child_run
from loom.queue.errors import QueueConflictError
from loom.queue.local_daemon_execution import load_managed_local_intent
from loom.queue.preparation import PreparationChildInput, PreparationSource, PrepareRunRequest, PREPARATION_INPUT_CONTEXT_ENV, capture_shared_input
from loom.queue.submitted_execution import SUBMITTED_EXECUTION_SCOPE, submitted_binding
from tests.integration.queue.test_preparation_operations import _service
from tests.integration.queue.test_submitted_container_agents import _fixture

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _run(tmp_path, monkeypatch, *, stage_update=None, selected_inputs=False, slurm=False, configuration_update=None):
    service = _service(tmp_path)
    policy, execution, _ = _fixture(tmp_path)
    if selected_inputs:
        from loom.queue.submitted_execution import SELECTED_INPUT_WORKER_CONTRACT
        execution = replace(execution, worker_contract=SELECTED_INPUT_WORKER_CONTRACT)
        policy = replace(policy, worker_contracts=(SELECTED_INPUT_WORKER_CONTRACT,))
    if slurm:
        from loom.queue._preparation_policy import load_preparation_policy
        from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
        from tests.integration.queue.test_slurm_ready_stage import _profile

        profile = replace(_profile(FakeSlurmCommandRunner(), capability_path=tmp_path / "job-capability"), profile_id="batch",
                          submitted_container_policy=policy.to_dict())
        preparation_policy = load_preparation_policy({
            "source_roots": {"projects": {"path": str(tmp_path / "projects"), "shared_snapshot_root": str(tmp_path / "captures")}},
            "profiles": {"containers": {
                "container_policy_id": policy.policy_id, "allowed_source_roots": ["projects"],
                "source_modes": ["shared"], "runtime_options": {"executor": "local"},
                "execution_route": {"kind": "slurm", "profile": "batch"},
            }},
        }, base=tmp_path, descriptors=(), container_capabilities=(policy.capability,), shared_roots=policy.shared_roots)
        service = replace(service, daemon=replace(
            service.daemon, slurm_profiles=(profile,), container_capabilities=(policy.capability,),
            shared_roots=policy.shared_roots, preparation_policy=preparation_policy,
        ))
    if stage_update is not None:
        path = tmp_path / "projects/pipeline.yaml"
        configuration = json.loads(path.read_text())
        configuration["pipeline"]["stages"][0].update(stage_update)
        path.write_text(json.dumps(configuration))
    if configuration_update is not None:
        path = tmp_path / "projects/pipeline.yaml"
        configuration = json.loads(path.read_text())
        configuration_update(configuration)
        path.write_text(json.dumps(configuration))
    request = PrepareRunRequest("submitted", "target", PreparationSource("shared", "projects", ".", ("pipeline.yaml",)),
                                "pipeline.yaml", "containers", execution=execution)
    receipt = capture_shared_input(request, source_root=tmp_path / "projects", snapshot_root=tmp_path / "captures")
    locations = [{"kind": "loom.shared-location", "schema_version": 1, "root_id": "data", "path": "."}] if selected_inputs else []
    binding = PreparationChildInput(request.operation_id, request.preparation_profile, request.config_path, receipt,
        None, shared_scope={"capability": "shared-execution-v1", "roots": policy.capability.workload_roots, "locations": locations},
        execution=execution, container_capability=policy.capability)
    assert binding.shared_scope is not None
    monkeypatch.setenv(PREPARATION_INPUT_CONTEXT_ENV, json.dumps({
        "schema_version": 7, **binding.execution_data(), "scope": {"kind": "shared", "binding": dict(binding.shared_scope)},
        "purpose": {"kind": "generic"}, "input": {"kind": "shared", "roots": {"projects": str(tmp_path / "captures")}},
    }))
    store = LocalArtifactStore(tmp_path / "artifacts")
    context = StageContext(run_uri=tmp_path.as_uri(), stage_name="prepare", resolved_config={}, stage_config=binding.to_dict(),
        artifact_store=store, output_specs={"report": OutputSpec("json", "json.v1")},
        local_output_dir=store.local_artifact_path(stage_name="prepare", name="report", codec_key="json.v1").parent, local_workspace_dir=tmp_path / "workspace")
    outputs = PreparationStage().run(context, {})
    report = load_preparation_report(outputs["report"], store.local_path(outputs["report"]))
    return service, binding, cast(dict[str, Any], report)


def test_selected_inputs_are_narrowed_per_action_and_retained_for_replay(tmp_path, monkeypatch):
    service, binding, report = _run(tmp_path, monkeypatch, selected_inputs=True)
    composed, requirements, preflight = decode_preparation_report(report, expected=binding)
    assert preflight.status.value == "PASS"
    # Preparation may inspect data; this stage only produces a constant and
    # therefore needs no dataset. Host-only image and control storage remain.
    assert "data" in binding.container_capability.shared_roots
    requirement = requirements["produce"]
    assert requirement.schema_version == 2
    assert set(requirement.shared_root_requirements) == {"workloads", "control"}
    assert binding.container_capability.satisfies(requirement)
    stage = cast(Any, composed).resolved["pipeline"]["stages"][0]
    _, selected = submitted_binding(stage["fingerprint"][SUBMITTED_EXECUTION_SCOPE])
    assert selected.requirement(binding.execution) == requirement
    child = prepare_child_run(service, binding, "selected-child", runtime_options=RunOptions(executor="local"))
    intent = load_managed_local_intent(service.daemon, child.run_uri)
    assert "data" in intent.execution_requirements["prepare"].shared_root_requirements


def test_selected_input_override_fails_before_report_publication(tmp_path, monkeypatch):
    from loom.queue.errors import QueueServiceError
    with pytest.raises(QueueServiceError, match="outside the preparation selection"):
        _run(tmp_path, monkeypatch, selected_inputs=True, stage_update={"config": {
            "value": 41, "input": {"kind": "loom.shared-location", "schema_version": 1,
                                   "root_id": "undeclared", "path": "."},
        }})
    assert not list((tmp_path / "artifacts").rglob("*.json"))


def test_selected_locations_survive_sorted_report_without_rewriting_retained_scope(tmp_path, monkeypatch):
    from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE

    def location(path):
        return {"kind": "loom.shared-location", "schema_version": 1,
                "root_id": "data", "path": path}

    _, binding, report = _run(tmp_path, monkeypatch, selected_inputs=True, stage_update={
        "config": {"value": 41, "z_first": location("left"), "a_second": location("right")},
    })
    # The supported report writer sorts mapping keys, while preserving the
    # location list bound by the worker before serialization.
    stage = report["composition"]["resolved"]["pipeline"]["stages"][0]
    retained = stage["fingerprint"][SHARED_EXECUTION_SCOPE]
    assert retained["locations"] == [location("left"), location("right")]
    assert list(stage["config"]) == ["a_second", "value", "z_first"]
    before = json.dumps(report, sort_keys=True)
    composed, _, preflight = decode_preparation_report(report, expected=binding)
    assert preflight.status.value == "PASS"
    assert cast(Any, composed).resolved["pipeline"]["stages"][0]["fingerprint"][SHARED_EXECUTION_SCOPE] == retained
    assert json.dumps(report, sort_keys=True) == before

    changed = deepcopy(report)
    changed["composition"]["resolved"]["pipeline"]["stages"][0]["config"]["a_second"] = location("other")
    with pytest.raises(QueueConflictError, match="shared selection conflicts"):
        decode_preparation_report(changed, expected=binding)


def test_native_report_and_child_plan_retain_submitted_execution(tmp_path, monkeypatch):
    service, binding, report = _run(tmp_path, monkeypatch)
    assert binding.execution is not None and binding.container_capability is not None
    assert report["schema_version"] == 11
    assert "profile_descriptor" not in report
    assert report["execution"] == binding.execution.to_dict()
    composed, requirements, preflight = decode_preparation_report(report, expected=binding)
    assert preflight.status.value == "PASS"
    assert all(isinstance(value, SubmittedContainerRequirement) for value in requirements.values())
    assert requirements["produce"] == binding.container_capability.requirement(binding.execution)
    stage = cast(Any, composed).resolved["pipeline"]["stages"][0]
    assert stage["config"] == {"value": 41}
    assert stage["resources"]["entries"]["cpu"] == {"kind": "cpu", "amount": 1, "unit": "count"}
    assert stage["fingerprint"][SUBMITTED_EXECUTION_SCOPE] == binding.execution_data()
    child = prepare_child_run(service, binding, "submitted-child", runtime_options=RunOptions(executor="local"))
    intent = load_managed_local_intent(service.daemon, child.run_uri)
    assert intent.execution_requirements["prepare"] == requirements["produce"]
    assert submitted_binding(intent.pipeline.stages[0].fingerprint_fields[SUBMITTED_EXECUTION_SCOPE]) == (binding.execution, binding.container_capability)


def test_report_rejects_changed_image_or_published_node_binding(tmp_path, monkeypatch):
    _, binding, report = _run(tmp_path, monkeypatch)
    assert binding.execution is not None
    different = replace(binding, execution=replace(binding.execution, image=replace(binding.execution.image, sha256="d" * 64)))
    with pytest.raises(QueueConflictError, match="installation identity"):
        decode_preparation_report(report, expected=different)
    changed = deepcopy(report)
    changed["composition"]["resolved"]["pipeline"]["stages"][0]["fingerprint"][SUBMITTED_EXECUTION_SCOPE] = different.execution_data()
    with pytest.raises(QueueConflictError, match="submitted execution conflicts"):
        decode_preparation_report(changed, expected=binding)


@pytest.mark.parametrize("stage_update, message", [
    ({"fingerprint": {SUBMITTED_EXECUTION_SCOPE: {"image": "another.sif"}}},
     "captured configuration cannot select protected preparation scope"),
])
def test_authored_per_stage_execution_overrides_refuse_before_publication(
    tmp_path, monkeypatch, stage_update, message,
):
    with pytest.raises(QueueConflictError, match=message):
        _run(tmp_path, monkeypatch, stage_update=stage_update)
    assert not list((tmp_path / "artifacts").rglob("*.json"))


@pytest.mark.parametrize("selected_inputs", [False, True])
def test_submitted_slurm_preparation_preserves_route_and_requires_matching_policy(tmp_path, monkeypatch, selected_inputs):
    from loom.queue.managed_local_preparation import prepare_managed_run
    from loom.queue.errors import QueueServiceError

    route = {"kind": "slurm", "profile": "batch"}
    service, binding, report = _run(tmp_path, monkeypatch, slurm=True, selected_inputs=selected_inputs,
                                  stage_update={"placement": {"execution_route": route}})
    composed, requirements, preflight = decode_preparation_report(report, expected=binding)
    assert preflight.status.value == "PASS"
    assert composed.resolved["pipeline"]["stages"][0]["placement"]["execution_route"] == route
    child = prepare_child_run(service, binding, "slurm-child", runtime_options=RunOptions(executor="local"))
    child_intent = load_managed_local_intent(service.daemon, child.run_uri)
    assert child_intent.pipeline.stages[0].placement["execution_route"] == route
    prepared = prepare_managed_run(service, composed, "slurm-workload", execution_requirements=requirements)
    intent = load_managed_local_intent(service.daemon, prepared.run_uri)
    assert intent.execution_requirements == requirements
    wrong = replace(service, daemon=replace(service.daemon, slurm_profiles=(
        replace(service.daemon.slurm_profiles[0], submitted_container_policy=None),
    )))
    with pytest.raises(QueueServiceError, match="container policy does not satisfy"):
        prepare_managed_run(wrong, composed, "wrong-slurm-workload", execution_requirements=requirements)
    assert not (service.daemon.run_store_root / "wrong-slurm-workload").exists()


@pytest.mark.parametrize("selected_inputs", [False, True])
@pytest.mark.parametrize("shape", ["pipeline", "stages", "stage", "fingerprint", "literal"])
def test_submitted_preparation_preserves_diagnostic_interpolations(tmp_path, monkeypatch, selected_inputs, shape):
    from loom.queue.shared_execution import SHARED_EXECUTION_SCOPE

    def configure(config):
        pipeline = config["pipeline"]
        stage = pipeline["stages"][0]
        stage["fingerprint"] = {"api_token": "private-fixture-value"}
        if shape == "pipeline":
            config["matrix"] = {"pipeline": pipeline}
            config["pipeline"] = "${matrix.pipeline}"
        elif shape == "stages":
            config["matrix"] = {"stages": pipeline["stages"]}
            pipeline["stages"] = "${matrix.stages}"
        elif shape == "stage":
            config["matrix"] = {"stage": stage}
            pipeline["stages"] = ["${matrix.stage}"]
        elif shape == "fingerprint":
            config["secret_fingerprint"] = stage["fingerprint"]
            stage["fingerprint"] = "${secret_fingerprint}"

    _, binding, report = _run(tmp_path, monkeypatch, selected_inputs=selected_inputs,
                              configuration_update=configure)
    composed, requirements, preflight = decode_preparation_report(report, expected=binding)
    assert preflight.status.value == "PASS"
    resolved = cast(Any, composed).resolved["pipeline"]["stages"][0]
    assert resolved["fingerprint"]["api_token"] == "private-fixture-value"
    assert SHARED_EXECUTION_SCOPE in resolved["fingerprint"]
    execution, capability = submitted_binding(resolved["fingerprint"][SUBMITTED_EXECUTION_SCOPE])
    assert execution == binding.execution
    assert capability.requirement(execution) == requirements["produce"]
    diagnostic = report["composition"]["redacted"]
    assert "private-fixture-value" not in json.dumps(diagnostic)
    if shape == "pipeline":
        assert diagnostic["pipeline"] == "${matrix.pipeline}"
    elif shape == "stages":
        assert diagnostic["pipeline"]["stages"] == "${matrix.stages}"
    elif shape == "stage":
        assert diagnostic["pipeline"]["stages"] == ["${matrix.stage}"]
    elif shape == "fingerprint":
        assert diagnostic["pipeline"]["stages"][0]["fingerprint"] == "${secret_fingerprint}"
    else:
        fingerprint = diagnostic["pipeline"]["stages"][0]["fingerprint"]
        assert fingerprint["api_token"] == "***REDACTED***"
        assert fingerprint[SHARED_EXECUTION_SCOPE] == resolved["fingerprint"][SHARED_EXECUTION_SCOPE]
        assert fingerprint[SUBMITTED_EXECUTION_SCOPE] == resolved["fingerprint"][SUBMITTED_EXECUTION_SCOPE]

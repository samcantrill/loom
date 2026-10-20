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


def _run(tmp_path, monkeypatch, *, stage_update=None):
    service = _service(tmp_path)
    policy, execution, _ = _fixture(tmp_path)
    if stage_update is not None:
        path = tmp_path / "projects/pipeline.yaml"
        configuration = json.loads(path.read_text())
        configuration["pipeline"]["stages"][0].update(stage_update)
        path.write_text(json.dumps(configuration))
    request = PrepareRunRequest("submitted", "target", PreparationSource("shared", "projects", ".", ("pipeline.yaml",)),
                                "pipeline.yaml", "containers", execution=execution)
    receipt = capture_shared_input(request, source_root=tmp_path / "projects", snapshot_root=tmp_path / "captures")
    binding = PreparationChildInput(request.operation_id, request.preparation_profile, request.config_path, receipt,
        None, shared_scope={"capability": "shared-execution-v1", "roots": policy.capability.workload_roots, "locations": []},
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
    ({"placement": {"execution_route": {"kind": "slurm", "profile": "batch"}}},
     "submitted containers require the managed agent route"),
])
def test_authored_per_stage_execution_overrides_refuse_before_publication(
    tmp_path, monkeypatch, stage_update, message,
):
    with pytest.raises(QueueConflictError, match=message):
        _run(tmp_path, monkeypatch, stage_update=stage_update)
    assert not list((tmp_path / "artifacts").rglob("*.json"))

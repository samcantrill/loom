"""Real resident child composition and plain coordinator publication boundaries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from loom.diagnostics import PreflightStatus
from loom.pipeline.execution.models import (
    STAGE_WORKER_REQUEST_SCHEMA_VERSION,
    StageWorkerRequest,
    StageWorkerResult,
)
from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.runtime.options import RunOptions
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.preparation import (
    decode_preparation_report,
    preparation_checks_allow_publication,
    prepare_child_run,
)
from loom.queue._agent_process_supervisor import ResidentWorkerLaunch, _launch_value
from loom.queue._remote_stage_execution import (
    ResidentExecutionProfile,
    ResidentProfileDescriptor,
    _ResidentAssignmentBundle,
    _ResidentAssignmentWorkspace,
)
from loom.queue.deployment import load_coordinator_service_config
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.managed_local_preparation import prepare_managed_run
from loom.queue.preparation import (
    PreparationChildInput,
    PreparationSource,
    PrepareRunRequest,
    capture_shared_input,
)
from loom.scheduling import (
    CapacityAtom,
    ExactQuantity,
    ResourceClaim,
    ResourceClaimContractDescriptor,
    SchedulingComponentDescriptor,
)


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _child(tmp_path: Path, *, fault: str | None = None):
    pytest.importorskip("weave")
    installation = tmp_path / "worker-installation"
    installation.mkdir()
    counter = installation / "recipe-count.txt"
    # An installed recipe entry point is visible only in the selected child
    # interpreter's search path. The coordinator never imports this module.
    (installation / "prepared_project.py").write_text(
        "from pathlib import Path\n"
        "def recipe():\n"
        "    path = Path(__file__).with_name('recipe-count.txt')\n"
        "    count = int(path.read_text()) + 1 if path.exists() else 1\n"
        "    path.write_text(str(count))\n"
        "    return {'value': 40 + count}\n"
    )
    distribution = installation / "prepared_project-1.0.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: prepared-project\nVersion: 1.0\n"
    )
    (distribution / "entry_points.txt").write_text(
        "[loom.recipes]\nprepared-value = prepared_project:recipe\n"
    )

    authored = tmp_path / "projects" / "example"
    authored.mkdir(parents=True)
    config = {
        "pipeline": {
            "name": "prepared-example",
            "stages": [
                {
                    "name": "produce",
                    "factory": {"_target_": "prepared_project.Stage"},
                    "config": {"_recipe_": "prepared-value"},
                    "outputs": {
                        "data": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                }
            ],
        },
        "runtime": {"executor": "local"},
    }
    if fault == "checks":
        config["pipeline"]["stages"][0]["inputs"] = {"missing": "unknown.data"}
    elif fault == "compose":
        config["pipeline"]["stages"][0]["config"] = {"_recipe_": "uninstalled-recipe"}
    elif fault == "portability":
        config["pipeline"]["stages"][0]["config"] = {
            "input_path": str(installation / "private-input")
        }
    config_path = authored / "pipeline.yaml"
    config_path.write_text(json.dumps(config))
    request = PrepareRunRequest(
        "prepare-1",
        "target-1",
        PreparationSource("shared", "projects", "example", ("pipeline.yaml",)),
        "pipeline.yaml",
        "existing-project",
    )
    snapshots = tmp_path / "shared-snapshots"
    receipt = capture_shared_input(
        request, source_root=tmp_path / "projects", snapshot_root=snapshots
    )
    # Editing the authoring directory after capture must not affect composition.
    config_path.write_text("invalid changed authoring bytes")
    descriptor = ResidentProfileDescriptor(
        "existing", "v1", "project-1", "environment-1", "executor-1"
    )
    binding = PreparationChildInput(
        request.operation_id,
        request.preparation_profile,
        request.config_path,
        receipt,
        descriptor.to_dict(),
    )
    profile = ResidentExecutionProfile(
        descriptor,
        installation,
        Path(sys.executable),
        preparation_shared_roots={} if fault == "mapping" else {"projects": snapshots},
    )

    coordinator_path = tmp_path / "coordinator.json"
    coordinator_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "kind": "loom.coordinator-service",
                "deployment_root": "deployment",
                "run_store_root": "runs",
                "machine_id": "coordinator",
                "local_agent": None,
                "poll_interval_seconds": 0.01,
                "max_accepted_time_step_seconds": 60,
                "remote_profiles": [],
                "agent_server": None,
                "agent_policy": {
                    "revision": "policy-1",
                    "agents": [],
                    "principals": [],
                },
                "authority": {"kind": "embedded"},
            }
        )
    )
    coordinator_path.chmod(0o600)
    service = load_coordinator_service_config(coordinator_path)
    child = prepare_child_run(
        service,
        binding,
        "internal-child-1",
        runtime_options=RunOptions.from_dict({"executor": "local"}),
    )
    store = LocalRunStore(service.daemon.run_store_root)
    plan_data = store.read_plan(child.run_uri)
    assert plan_data is not None
    plan = ExecutionPlan.from_dict(plan_data)
    assert plan.stage_plans[0].fingerprint is not None
    worker_request = StageWorkerRequest(
        STAGE_WORKER_REQUEST_SCHEMA_VERSION,
        child.run_uri,
        "prepare",
        1,
        "2026-09-11T00:00:00Z",
        "local",
        {},
        plan.stage_plans[0].fingerprint,
        "/coordinator/stdout",
        "/coordinator/stderr",
        "/coordinator/trace",
        "/coordinator/result",
        {
            "stage_id": "prepare",
            "executor": "local",
            "resources": {"entries": {}},
            "resource_policy": {"account_for": "all", "enforce": []},
            "resource_selection": {"account_for": [], "enforce": []},
        },
    )
    claim = ResourceClaim(
        "cpu",
        ResourceClaimContractDescriptor("cpu", 1, "loom.cpu.claim.v1"),
        (
            CapacityAtom(
                "cpu", "worker:cpu", ExactQuantity(1), "count", ExactQuantity(1)
            ),
        ),
        1,
    )
    bundle = _ResidentAssignmentBundle.from_worker_request(
        assignment_id="assignment-1",
        stage_work_id="work-1",
        attempt_id="attempt-1",
        offer_id="offer-1",
        claim_id="claim-1",
        worker_request=worker_request,
        profile=descriptor,
        inputs=(),
        declared_outputs=("report",),
        claims=(claim,),
        provider_descriptors=(
            SchedulingComponentDescriptor(
                "cpu", 1, "1", "test-cpu-provider", "test-cpu-config"
            ),
        ),
    )
    delivered = _ResidentAssignmentBundle.from_remote_dict(bundle.to_dict())
    assert delivered.preparation_input == binding
    assert str(snapshots) not in json.dumps(bundle.to_dict())
    workspace = _ResidentAssignmentWorkspace(tmp_path / "worker", bundle.assignment_id)
    workspace.persist_request(delivered, profile)
    workspace.accept()
    workspace.grant("fence-1")
    launch = ResidentWorkerLaunch(
        supervisor_id="supervisor-1",
        continuity_epoch="epoch-1",
        agent_id="worker",
        session_id="session-1",
        assignment_id=bundle.assignment_id,
        process_execution_id="execution-1",
        execution_fence="fence-1",
        launch_operation_id="launch-1",
        bundle_digest=hashlib.sha256(
            json.dumps(bundle.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        workspace_root=workspace.root,
        profile=profile.launch_profile,
        environment={},
    )
    workspace.persist_supervisor_launch(json.dumps(_launch_value(launch)))
    workspace.mark_process_started("execution-1", 101)
    (workspace.root / "run.grant").write_text("granted")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(installation), str(Path(__file__).resolve().parents[3] / "src"))
    )
    completed = subprocess.run(
        [
            str(profile.python_executable),
            "-m",
            "loom.queue._resident_stage_worker",
            "--workspace",
            str(workspace.root),
        ],
        cwd=installation,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result = StageWorkerResult.from_dict(
        json.loads((workspace.root / "worker-result.json").read_text())
    )
    workspace.persist_worker_result(result)
    retained = workspace.retain_outputs()
    assert retained.assignment_id == bundle.assignment_id
    assert "prepared_project" not in sys.modules
    return service, binding, result, workspace, counter


def test_real_child_composes_once_and_publisher_replays_plain_recipe_evidence(
    tmp_path: Path,
) -> None:
    service, binding, result, workspace, counter = _child(tmp_path)
    assert result.status is StageStatus.SUCCEEDED, result.failure
    report = LocalArtifactStore(workspace.root / "artifacts").load(
        result.outputs["report"]
    )
    assert isinstance(report, dict)
    composed, requirements, preflight = decode_preparation_report(
        report, expected=binding
    )
    assert preflight.status is PreflightStatus.PASS
    assert preparation_checks_allow_publication(preflight)
    assert counter.read_text() == "1"
    assert report["composition"]["recipe_manifest"]
    assert str(workspace.root) not in json.dumps(report["composition"]["resolved"])

    # IDs received over the artifact boundary must join the accepted operation,
    # even when all other returned configuration data is valid.
    for field in ("operation_id", "input_manifest_digest", "preparation_profile"):
        mismatched = deepcopy(report)
        mismatched[field] = "another-value"
        with pytest.raises(QueueConflictError, match="identity"):
            decode_preparation_report(mismatched, expected=binding)
    missing_requirement = deepcopy(report)
    missing_requirement["execution_requirements"] = {}
    with pytest.raises(QueueConflictError, match="requirements"):
        decode_preparation_report(missing_requirement, expected=binding)
    assert not (service.daemon.run_store_root / "target-1").exists()

    receipt = prepare_managed_run(
        service, composed, "target-1", execution_requirements=requirements
    )
    store = LocalRunStore(service.daemon.run_store_root)
    snapshot = store.read_config_snapshot(receipt.run_uri, "resolved")
    assert snapshot is not None
    resolved = json.loads(snapshot)
    assert resolved["pipeline"]["stages"][0]["config"] == {"value": 41}
    assert store.read_recipe_manifest(receipt.run_uri) == tuple(
        report["composition"]["recipe_manifest"]
    )
    assert (
        store.read_composition_manifest(receipt.run_uri)
        == report["composition"]["manifest"]
    )
    assert store.read_run_user_metadata(receipt.run_uri) == {
        "config_provenance": report["composition"]["provenance"]
    }
    target = store.local_run_dir(receipt.run_uri)
    before = {
        path.relative_to(target): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in target.rglob("*")
        if path.is_file()
    }
    assert (
        prepare_managed_run(
            service, composed, "target-1", execution_requirements=requirements
        )
        == receipt
    )
    assert {
        path.relative_to(target): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in target.rglob("*")
        if path.is_file()
    } == before
    assert counter.read_text() == "1"
    assert "prepared_project" not in sys.modules


@pytest.mark.parametrize("fault", ("checks", "compose", "mapping", "portability"))
def test_real_child_preserves_failed_checks_or_native_worker_failure(
    tmp_path: Path, fault: str
) -> None:
    service, binding, result, workspace, _counter = _child(tmp_path, fault=fault)
    if fault in {"compose", "mapping"}:
        assert result.status is StageStatus.FAILED
        assert result.failure is not None and not result.outputs
    else:
        assert result.status is StageStatus.SUCCEEDED, result.failure
        report = LocalArtifactStore(workspace.root / "artifacts").load(
            result.outputs["report"]
        )
        if fault == "portability":
            with pytest.raises(QueueServiceError, match="path-bearing"):
                decode_preparation_report(report, expected=binding)
        else:
            _composed, _requirements, preflight = decode_preparation_report(
                report, expected=binding
            )
            assert preflight.status is PreflightStatus.FAIL
            assert not preparation_checks_allow_publication(preflight)
    assert not (service.daemon.run_store_root / "target-1").exists()


def test_preparation_report_requires_its_exact_selected_profile(tmp_path: Path) -> None:
    _service, binding, result, workspace, _counter = _child(tmp_path)
    assert result.status is StageStatus.SUCCEEDED
    report = LocalArtifactStore(workspace.root / "artifacts").load(
        result.outputs["report"]
    )
    other = replace(
        binding, profile_descriptor={**binding.profile_descriptor, "revision": "v2"}
    )
    with pytest.raises(QueueConflictError, match="identity"):
        decode_preparation_report(report, expected=other)
    with pytest.raises(QueueConflictError, match="profile"):
        replace(
            workspace.request(),
            profile=ResidentProfileDescriptor.from_dict(other.profile_descriptor),
        )

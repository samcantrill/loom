"""Stable host authorization and assignment-owned submitted container launches."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import pytest

from loom.pipeline.planning import StageFingerprintRecord
from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisor,
    AgentProcessSupervisorError,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
    _launch_from_value,
    _launch_json,
    _launch_value,
    _profile_value,
    _service_configuration,
)
from loom.queue._remote_stage_execution import _ResidentAssignmentBundle, _ResidentAssignmentWorkspace
from loom.queue._submitted_container_policy import SubmittedContainerPolicy
from loom.queue.errors import QueueServiceError
from loom.queue.submitted_execution import (
    SUBMITTED_CONTAINER_WORKER_CONTRACT,
    SUBMITTED_EXECUTION_SCOPE,
    SubmittedContainerExecution,
    SubmittedImage,
)
from tests.unit.loom.queue.test_agent_process_supervisor import _launch, _shared_container_request


def _submitted(tmp_path):
    resident, request, _ = _shared_container_request(tmp_path)
    images = tmp_path / "workloads"
    images.mkdir()
    (images / "challenge").write_bytes(b"images")
    image = images / "aaa" / "image.sif"
    image.parent.mkdir()
    image.write_bytes(b"synthetic image aaa")
    image.chmod(0o444)
    roots = {
        **resident.shared_roots,
        "workloads": {
            "host_path": str(images), "container_path": None, "access": "ro",
            "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"images").hexdigest()},
        },
    }
    policy = SubmittedContainerPolicy(
        "containers", {"command": sys.executable}, roots, ("workloads",),
    )
    execution = SubmittedContainerExecution(
        "apptainer",
        SubmittedImage(
            {"kind": "loom.shared-location", "schema_version": 1,
             "root_id": "workloads", "path": "aaa/image.sif"},
            hashlib.sha256(image.read_bytes()).hexdigest(), image.stat().st_size,
        ),
        "/contained/python", SUBMITTED_CONTAINER_WORKER_CONTRACT,
    )
    original = StageFingerprintRecord.from_dict(request.fingerprint)
    fingerprint = StageFingerprintRecord.create(
        algorithm=original.algorithm,
        payload=replace(original.payload, fingerprint_fields={
            **original.payload.fingerprint_fields,
            SUBMITTED_EXECUTION_SCOPE: {
                "execution": execution.to_dict(),
                "container_capability": policy.capability.to_dict(),
            },
        }),
        inputs_summary=original.inputs_summary,
    )
    request = replace(
        request, profile=policy.capability, fingerprint=fingerprint.to_dict(),
        worker_metadata={**request.worker_metadata, "loom.execution_binding": {
            **request.worker_metadata["loom.execution_binding"],
            "environment_fingerprint": policy.capability.environment_fingerprint,
        }},
    )
    return policy, execution, request, image


def _retained_launch(tmp_path, policy, execution, request):
    agent = tmp_path / "agent"
    agent.mkdir()
    supervisor = AgentProcessSupervisor.initialize(
        agent, agent_id="agent-A", profiles=(), container_policies=(policy,),
    )
    workspace = _ResidentAssignmentWorkspace(agent, request.assignment_id)
    profile = policy.launch_profile(execution, workspace=workspace.root)
    workspace.persist_request(request, profile)
    workspace.stage_input("input-1", b"input")
    workspace.accept()
    workspace.grant("fence-A")
    launch = replace(
        _launch(supervisor, workspace.root), assignment_id=request.assignment_id,
        profile=profile,
        bundle_digest=hashlib.sha256(json.dumps(
            request.to_dict(), sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest(),
    )
    launch = replace(
        launch, resource_controls=launch.container_command.metadata.get("resource_controls"),
    )
    workspace.persist_supervisor_launch(_launch_json(launch))
    return supervisor, workspace, launch


def test_container_only_supervisor_configuration_is_stable_across_images(tmp_path):
    policy, first, _, _ = _submitted(tmp_path)
    configuration = SupervisorLaunchConfiguration("agent-A", (), (policy,))
    second = replace(first, image=replace(first.image, sha256="b" * 64))
    before = configuration.fingerprint
    launch_a = policy.launch_profile(first, workspace=tmp_path / "work-a")
    launch_b = policy.launch_profile(second, workspace=tmp_path / "work-b")
    assert launch_a.fingerprint != launch_b.fingerprint
    assert configuration.fingerprint == before
    assert "profile_id" not in launch_a.descriptor
    assert policy.qualify() == policy.capability
    assert SubmittedContainerPolicy.from_dict(policy.to_dict()) == policy
    agent = tmp_path / "service"
    agent.mkdir()
    AgentProcessSupervisorService.initialize_process_free(agent, configuration=configuration)
    assert _service_configuration(agent / "supervisor") == configuration
    with pytest.raises(AgentProcessSupervisorError, match="policy set"):
        SupervisorLaunchConfiguration("agent-A", ())
    with pytest.raises(AgentProcessSupervisorError, match="profile set"):
        SupervisorLaunchConfiguration("agent-A", (launch_a,))


def test_portable_policy_excludes_host_prefix_but_retains_environment(tmp_path):
    policy, _, _, _ = _submitted(tmp_path)
    moved = replace(policy, shared_roots={
        alias: {**root, "host_path": "/different-host/" + alias}
        for alias, root in policy.shared_roots.items()
    })
    assert moved.capability == policy.capability
    assert moved.fingerprint != policy.fingerprint
    assert replace(policy, environment={"MODEL_BACKEND": "other"}).capability != policy.capability


def test_submitted_bundle_path_guard_only_admits_typed_contained_python(tmp_path):
    policy, execution, request, _ = _submitted(tmp_path)
    assert _ResidentAssignmentBundle.from_remote_dict(request.to_dict()) == request
    assert request.submitted_execution == execution
    original = StageFingerprintRecord.from_dict(request.fingerprint)
    invalid = replace(request, fingerprint=StageFingerprintRecord.create(
        algorithm=original.algorithm,
        payload=replace(original.payload, fingerprint_fields={
            **original.payload.fingerprint_fields,
            "untyped_executable": "/host/python",
        }),
        inputs_summary=original.inputs_summary,
    ).to_dict())
    with pytest.raises(QueueServiceError, match="paths"):
        _ResidentAssignmentBundle.from_remote_dict(invalid.to_dict())
    assert policy.capability.requirement(execution).runtime == "apptainer"


def test_supervisor_qualifies_retained_image_and_grant_before_new_launch(tmp_path):
    policy, execution, request, image = _submitted(tmp_path)
    supervisor, workspace, launch = _retained_launch(tmp_path, policy, execution, request)
    supervisor._validate_launch(launch)
    supervisor._qualify_new_launch(launch)
    with pytest.raises(AgentProcessSupervisorError, match="grant"):
        supervisor._qualify_new_launch(replace(launch, execution_fence="another-fence"))
    image.chmod(0o644)
    image.write_bytes(b"x" * execution.image.size_bytes)
    image.chmod(0o444)
    with pytest.raises(AgentProcessSupervisorError, match="image bytes"):
        supervisor._qualify_new_launch(launch)
    with supervisor._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM launches").fetchone()[0] == 0
    assert workspace.state() == "GRANTED"


def test_saved_submitted_launch_decodes_and_authorizes_without_storage(tmp_path, monkeypatch):
    policy, execution, request, _ = _submitted(tmp_path)
    supervisor, _, launch = _retained_launch(tmp_path, policy, execution, request)
    saved = _launch_value(launch)
    profile = _profile_value(launch.profile)

    def forbid(*args, **kwargs):
        raise AssertionError("saved launch authorization must not inspect storage")

    with monkeypatch.context() as blocked:
        for name in ("resolve", "exists", "is_dir", "is_file", "stat", "lstat"):
            blocked.setattr(Path, name, forbid)
        restored = _launch_from_value(saved)
        supervisor._validate_launch(restored)
        assert _profile_value(restored.profile) == profile
        assert restored.spec_digest == launch.spec_digest
    altered = replace(launch.profile, environment={"UNAUTHORIZED": "value"})
    with pytest.raises(AgentProcessSupervisorError, match="identity mismatch"):
        supervisor._validate_launch(replace(launch, profile=altered))

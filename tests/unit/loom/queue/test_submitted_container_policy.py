"""Stable host authorization and assignment-owned submitted container launches."""

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import Event

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
from loom.queue import _submitted_image_launch as physical
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
            **cast(dict[str, Any], request.worker_metadata["loom.execution_binding"]),
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
        for alias, root in cast(dict[str, dict[str, Any]], policy.shared_roots).items()
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


def test_physical_command_executes_verified_image_after_source_replacement(tmp_path):
    from loom.pipeline.executors.apptainer.commands import ApptainerExecCommand
    policy, execution, _, source = _submitted(tmp_path)
    original = source.read_bytes()
    command = ApptainerExecCommand.from_argv(("apptainer", "exec", str(source), "--worker", str(source)),
        metadata={"worker_command": ["--worker", str(source)]})
    cache = physical.VerifiedImageCache(tmp_path)
    with physical.image_for_launch(execution.image, policy.shared_roots, "first", cache=cache) as paths:
        replaced = tmp_path / "replacement.sif"
        replaced.write_bytes(b"x" * len(original))
        replaced.chmod(0o444)
        replaced.replace(source)
        argv = physical.physical_command(command, paths).argv
        assert Path(argv[2]).read_bytes() == original and argv[-1] == str(source)
        with pytest.raises(ValueError, match="image bytes"):
            with physical.image_for_launch(execution.image, policy.shared_roots, "second", cache=cache):
                pytest.fail("replaced source passed verification")
    assert not Path(argv[2]).exists()


@pytest.fixture
def mounted_image(tmp_path):
    source_name = os.environ.get("LOOM_TEST_IMMUTABLE_IMAGE")
    if source_name is None:
        pytest.skip("requires an image on a mounted kernel snapshot")
    source = Path(source_name)
    policy, execution, _, _ = _submitted(tmp_path)
    workload = policy.shared_roots["workloads"]
    assert isinstance(workload, Mapping)
    root = {**workload, "host_path": str(source.parent)}
    selected = replace(execution.image, location={**execution.image.location, "path": source.name},
                       size_bytes=source.stat().st_size, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    return selected, {"workloads": root}


def test_concurrent_launches_share_only_the_mounted_image_snapshot(mounted_image, monkeypatch):
    selected, roots = mounted_image
    original = physical._copy_verified
    copies = []
    def copy(*args):
        copies.append(True)
        original(*args)
    monkeypatch.setattr(physical, "_copy_verified", copy)
    with physical.image_for_launch(selected, roots, "first") as first:
        with physical.image_for_launch(selected, roots, "second") as second:
            assert second == first and copies == [True]
        assert first[1].exists()
    assert not first[1].exists()


def test_mounted_image_is_warm_until_supervisor_restart(tmp_path, mounted_image, monkeypatch):
    from loom.queue._phase_timing import observe_phases
    image, roots = mounted_image
    owner = tmp_path / "supervisor"
    owner.mkdir(mode=0o700)
    copies, spans = [], []
    original = physical._copy_verified

    def copy(source, selected, private):
        copies.append(private)
        original(source, selected, private)

    monkeypatch.setattr(physical, "_copy_verified", copy)
    cache = physical.VerifiedImageCache(owner)
    with observe_phases(spans.append):
        for operation in ("cold", "warm"):
            with physical.image_for_launch(image, roots, operation, cache=cache) as (_, path):
                assert path == copies[0]
                assert path.stat().st_mode & 0o777 == 0o400
        assert [record["spans"][0]["attributes"]["shared_verification"] for record in spans] == [False, True]
        assert len(copies) == 1
    restarted = physical.VerifiedImageCache(owner)
    # A preceding, possibly active path is never an input to a fresh supervisor.
    restarted.recover_scratch(owner, lambda: False)
    with physical.image_for_launch(image, roots, "restart", cache=restarted) as (_, fresh):
        assert fresh != path and path.exists()
        assert len(copies) == 2
    assert not fresh.exists()
    quiescent = physical.VerifiedImageCache(owner)
    quiescent.recover_scratch(owner, lambda: True)
    assert not path.exists()
    with physical.image_for_launch(image, roots, "new-epoch", cache=quiescent) as (_, rebuilt):
        assert rebuilt.is_relative_to(owner) and len(copies) == 3
    with pytest.raises(ValueError, match="retained intent"):
        changed = replace(image, sha256="0" * 64)
        with physical.image_for_launch(changed, roots, "changed-digest", cache=quiescent):
            pytest.fail("a different expected digest reused verified bytes")
    quiescent.clear_idle()
    cache.clear_idle()


def test_competing_image_fills_share_work_and_reserve_space_before_copy(tmp_path, monkeypatch):
    from loom.queue import _immutable_tree
    policy, execution, _, source = _submitted(tmp_path)
    monkeypatch.setattr(_immutable_tree, "_snapshot", lambda fd: 42)
    root = tmp_path / "supervisor"
    root.mkdir(mode=0o700)
    cache = physical.VerifiedImageCache(root, max_bytes=execution.image.size_bytes)
    other_source = source.with_name("other.sif")
    other_source.write_bytes(source.read_bytes())
    other_source.chmod(0o444)
    other = replace(execution.image, location={**execution.image.location, "path": "aaa/other.sif"})
    original_copy = physical._copy_verified
    started, release, joined = Event(), Event(), Event()
    original_acquire = cache.acquire
    copies = []

    def acquire(key, size):
        entry, owner = original_acquire(key, size)
        if not owner:
            joined.set()
        return entry, owner

    def copy(stream, image, private):
        copies.append(private)
        if image == execution.image:
            started.set()
            assert release.wait(5)
        original_copy(stream, image, private)

    monkeypatch.setattr(cache, "acquire", acquire)
    monkeypatch.setattr(physical, "_copy_verified", copy)

    def launch(image):
        with physical.image_for_launch(image, policy.shared_roots, "concurrent", cache=cache) as (_, private):
            assert private.read_bytes() == source.read_bytes()
            return private

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(launch, execution.image)
        try:
            assert started.wait(5)
            peer = pool.submit(launch, execution.image)
            assert joined.wait(5)
            fallback = launch(other)
            assert not fallback.is_relative_to(root) and not fallback.exists()
        finally:
            release.set()
        first = owner.result()
        assert first == peer.result() and first.exists()
    assert len(copies) == 2
    with physical.image_for_launch(execution.image, policy.shared_roots, "active", cache=cache):
        assert not launch(other).exists()
        assert first.exists()
    retained = launch(other)
    assert retained.is_relative_to(root) and retained.exists() and not first.exists()
    cache.clear_idle()
    assert not retained.exists()


def test_failed_fill_removes_partial_allows_retry_and_qualifies_root(tmp_path, monkeypatch):
    from loom.queue import _immutable_tree
    policy, execution, _, _ = _submitted(tmp_path)
    monkeypatch.setattr(_immutable_tree, "_snapshot", lambda fd: 42)
    owner = tmp_path / "supervisor"
    owner.mkdir(mode=0o700)
    cache = physical.VerifiedImageCache(owner, max_bytes=execution.image.size_bytes)
    def fail(source, image, private):
        private.write_bytes(b"partial")
        raise OSError("disk full")

    with monkeypatch.context() as failing:
        failing.setattr(physical, "_copy_verified", fail)
        with pytest.raises(OSError, match="disk full"):
            with physical.image_for_launch(execution.image, policy.shared_roots, "failed", cache=cache):
                pytest.fail("unverified image published")
    assert not list(owner.iterdir())
    with physical.image_for_launch(execution.image, policy.shared_roots, "retry", cache=cache) as (_, first):
        assert first.is_relative_to(owner)
    alternate = {"alternate": policy.shared_roots["workloads"]}
    selected = replace(execution.image, location={**execution.image.location, "root_id": "alternate"})
    with physical.image_for_launch(selected, alternate, "other-root", cache=cache) as (_, second):
        assert second != first and not first.exists()
    cache.clear_idle()


def test_guest_writable_supervisor_parent_disables_retention(tmp_path):
    from loom.pipeline.executors.containers import ContainerMount
    policy, _, _, _ = _submitted(tmp_path)
    owner = tmp_path / "agent/supervisor"
    protected = SupervisorLaunchConfiguration("agent", (), (policy,))
    assert physical.VerifiedImageCache.for_supervisor(owner, protected).directory == owner
    exposed = replace(policy, mounts=(ContainerMount(str(owner.parent), "/scratch", "rw"),))
    assert physical.VerifiedImageCache.for_supervisor(owner, replace(protected, container_policies=(exposed,))).directory is None

"""Submitted workloads retain exact image intent without host path authority."""

from dataclasses import replace
from typing import Any, cast

import pytest

from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.preparation import PreparationSource, PrepareRunRequest
from loom.queue.run import RunRequest
from loom.queue.submitted_execution import (
    SUBMITTED_CONTAINER_WORKER_CONTRACT,
    SubmittedContainerExecution,
    SubmittedContainerCapability,
    SubmittedImage,
    retain_submitted_image,
)


def _execution():
    return SubmittedContainerExecution(
        runtime="apptainer",
        image=SubmittedImage(
            {
                "kind": "loom.shared-location",
                "schema_version": 1,
                "root_id": "workloads",
                "path": "images/aaa/image.sif",
            },
            "a" * 64,
            1024,
        ),
        python_executable="/opt/project/venv/bin/python",
        worker_contract=SUBMITTED_CONTAINER_WORKER_CONTRACT,
        project_integration={
            "schema_version": 3,
            "callable": "example.inspection:inspect",
            "evidence_namespace": "example",
            "target_prefix": "example-",
        },
    )


def _request():
    return PrepareRunRequest(
        "submission-a",
        "run-a",
        PreparationSource("shared", "projects", "example", ("config",)),
        "config/pipeline.yaml",
        "shared-container",
    )


def test_omitted_execution_keeps_installed_request_wire():
    request = _request()
    assert request.to_dict() == {
        "operation_id": "submission-a",
        "run_name": "run-a",
        "source": {
            "mode": "shared",
            "root": "projects",
            "path": "example",
            "include": ["config"],
        },
        "config_path": "config/pipeline.yaml",
        "preparation_profile": "shared-container",
        "overlays": [],
        "overrides": [],
        "run_options": {},
    }
    assert PrepareRunRequest.from_dict(request.to_dict()) == request


def test_request_retains_image_and_freezes_nested_selection():
    execution = _execution()
    payload = cast(dict[str, Any], execution.to_dict())
    retained = SubmittedContainerExecution.from_dict(payload)
    payload["image"]["location"]["path"] = "another.sif"
    payload["project_integration"]["callable"] = "another:inspect"
    assert retained == execution
    with pytest.raises(TypeError):
        cast(Any, retained.image.location)["path"] = "another.sif"
    with pytest.raises(TypeError):
        cast(Any, retained.project_integration)["callable"] = "another:inspect"
    request = replace(_request(), execution=execution)
    run = RunRequest(request, queue_item_id="queued-a")
    assert RunRequest.from_dict(run.to_dict()) == run
    assert PrepareRunRequest.from_dict(request.to_dict()) == request
    assert request.intent_digest("client-a") != _request().intent_digest("client-a")
    different_image = replace(execution, image=replace(execution.image, sha256="b" * 64))
    assert request.intent_digest("client-a") != replace(
        request, execution=different_image,
    ).intent_digest("client-a")


def test_generic_container_has_explicit_null_integration():
    execution = replace(_execution(), project_integration=None)
    assert execution.to_dict()["project_integration"] is None
    assert SubmittedContainerExecution.from_dict(execution.to_dict()) == execution


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"kind": "installed"},
        {"runtime": "docker"},
        {"python_executable": "python"},
        {"python_executable": "/opt/../bin/python"},
        {"python_executable": "/opt//bin/python"},
        {"host_path": "/tmp/image.sif"},
    ],
)
def test_wire_rejects_unsupported_execution_or_host_authority(change):
    with pytest.raises(QueueServiceError):
        SubmittedContainerExecution.from_dict({**_execution().to_dict(), **change})


def test_wire_does_not_admit_null_execution_or_missing_integration():
    with pytest.raises(QueueServiceError, match="execution"):
        PrepareRunRequest.from_dict({**_request().to_dict(), "execution": None})
    payload = _execution().to_dict()
    del payload["project_integration"]
    with pytest.raises(QueueServiceError):
        SubmittedContainerExecution.from_dict(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"sha256": "aaa"},
        {"sha256": "A" * 64},
        {"size_bytes": True},
        {"size_bytes": 0},
        {"size_bytes": 1.5},
    ],
)
def test_image_identity_is_complete_and_size_is_bytes(change):
    with pytest.raises(QueueServiceError):
        SubmittedImage.from_dict({**_execution().image.to_dict(), **change})


def test_contained_python_is_not_resolved_as_a_host_executable(tmp_path):
    absent = tmp_path / "not-installed" / "python"
    execution = replace(_execution(), python_executable=str(absent))
    assert not absent.exists()
    assert SubmittedContainerExecution.from_dict(execution.to_dict()) == execution


def _roots(tmp_path):
    return {
        "workloads": {
            "host_path": str(tmp_path / "workloads"),
            "container_path": None,
            "access": "ro",
            "challenge": {"path": "challenge", "sha256": "f" * 64},
        },
    }


def _capability(tmp_path):
    return SubmittedContainerCapability(
        "shared-container", "apptainer", (SUBMITTED_CONTAINER_WORKER_CONTRACT,),
        ("workloads",),
        {
            key: {name: item for name, item in root.items() if name != "host_path"}
            for key, root in _roots(tmp_path).items()
        },
        "sha256:" + "e" * 64,
    )


def _policy(tmp_path):
    from loom.queue._preparation_policy import load_preparation_policy
    from loom.queue._remote_stage_execution import ResidentProfileDescriptor

    descriptor = ResidentProfileDescriptor("installed", "v1", "project", "env", "worker")
    common = {
        "allowed_source_roots": ["projects"],
        "source_modes": ["shared"],
        "runtime_options": {"executor": "local"},
    }
    policy = load_preparation_policy(
        {
            "source_roots": {"projects": {
                "path": str(tmp_path / "projects"),
                "shared_snapshot_root": str(tmp_path / "snapshots"),
            }},
            "profiles": {
                "shared-container": {"container_policy_id": "shared-container", **common},
                "installed": {"resident_profile_id": "installed", **common},
            },
        },
        base=tmp_path, descriptors=(descriptor,),
        container_capabilities=(_capability(tmp_path),), shared_roots=_roots(tmp_path),
    )
    assert policy is not None
    return policy


def test_policy_selects_capability_without_an_installed_descriptor(tmp_path):
    policy = _policy(tmp_path)
    request = replace(_request(), execution=_execution())
    selected = policy.select(request)
    profile = cast(dict[str, Any], selected["profile"])
    assert "profile_descriptor" not in profile
    assert profile["container_capability"] == _capability(tmp_path).to_dict()
    assert profile["project_processor"] == _execution().to_dict()["project_integration"]
    assert str(tmp_path) not in str(policy.safe_identity())
    assert SubmittedContainerCapability.from_dict(
        _capability(tmp_path).to_dict()
    ) == _capability(tmp_path)
    # The policy stays stable when a new image is submitted.
    another = replace(_execution(), image=replace(_execution().image, sha256="b" * 64))
    assert policy.select(replace(request, execution=another)) == selected


def test_installed_and_submitted_modes_never_fall_back(tmp_path):
    policy = _policy(tmp_path)
    with pytest.raises(QueueServiceError, match="requires submitted"):
        policy.select(_request())
    with pytest.raises(QueueServiceError, match="does not support"):
        policy.select(replace(_request(), preparation_profile="installed", execution=_execution()))
    assert "profile_descriptor" in cast(dict[str, Any], policy.select(
        replace(_request(), preparation_profile="installed")
    )["profile"])
    with pytest.raises(QueueServiceError, match="not allowed"):
        policy.select(replace(
            _request(), execution=replace(_execution(), worker_contract="future-worker"),
        ))
    execution = replace(
        _execution(),
        image=replace(_execution().image, location={
            **_execution().image.location, "root_id": "unapproved",
        }),
    )
    with pytest.raises(QueueServiceError, match="not allowed"):
        policy.select(replace(_request(), execution=execution))


def test_large_image_is_pinned_without_entering_configuration_capture(tmp_path):
    from loom.pipeline.cleanup.preparation_pins import preparation_path_is_retained
    from loom.queue.preparation import capture_shared_input

    image_path = tmp_path / "workloads" / "images" / "aaa" / "image.sif"
    image_path.parent.mkdir(parents=True)
    size = 65 * 1024 * 1024
    with image_path.open("wb") as stream:
        stream.truncate(size)
    image_path.chmod(0o444)
    image = replace(_execution().image, size_bytes=size)
    for _ in range(2):
        retain_submitted_image(
            image, _roots(tmp_path), coordinator_id="coordinator", operation_id="submission-a",
        )
    assert preparation_path_is_retained(image_path)
    assert preparation_path_is_retained(image_path.parent.parent)
    config = tmp_path / "projects" / "example" / "config" / "pipeline.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("pipeline: {}\n")
    receipt = capture_shared_input(
        replace(_request(), execution=replace(_execution(), image=image)),
        source_root=tmp_path / "projects", snapshot_root=tmp_path / "snapshots",
    )
    files = tmp_path / "snapshots" / receipt.path / "files"
    assert sorted(str(path.relative_to(files)) for path in files.rglob("*") if path.is_file()) == [
        "config/pipeline.yaml",
    ]


def test_retention_refuses_missing_changed_size_writable_or_symlinked_image(tmp_path):
    path = tmp_path / "workloads" / "images" / "aaa" / "image.sif"
    path.parent.mkdir(parents=True)
    image = _execution().image

    def retain():
        retain_submitted_image(image, _roots(tmp_path), coordinator_id="c", operation_id="a")

    with pytest.raises(QueueServiceError, match="unavailable"):
        retain()
    path.write_bytes(b"x" * image.size_bytes)
    with pytest.raises(QueueServiceError, match="read-only"):
        retain()
    path.write_bytes(b"short")
    path.chmod(0o444)
    with pytest.raises(QueueServiceError, match="complete"):
        retain()
    target = path.with_name("other.sif")
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(QueueServiceError, match="symbolic"):
        retain()


def test_native_acceptance_replays_image_intent_and_refuses_retargeting(tmp_path):
    from loom.preparation import CoordinatorPreparation
    from loom.queue.deployment import CoordinatorServiceConfig
    from loom.queue.errors import QueueConflictError
    from loom.queue.local_daemon import (
        LocalDaemon, LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole,
    )

    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator",
        agent_root=None,
        run_store_root=tmp_path / "runs",
        resident_worker_launch_profile=None,
        cpu_capacity=0,
        preparation_policy=_policy(tmp_path),
    )
    LocalDaemon.initialize(config)
    service = CoordinatorServiceConfig(
        config, None, tmp_path / "coordinator.json", "immutable", "active",
    )
    daemon = LocalDaemon(config, preparation=CoordinatorPreparation(service))
    # Hold progression to inspect the acceptance transaction separately from IO.
    daemon._preparations._reconcile_lock.acquire()
    daemon.start()
    try:
        client = daemon.client_view(LocalDaemonPrincipal("client-a", LocalDaemonRole.CLIENT))
        request = replace(_request(), execution=_execution())
        accepted = client.prepare_run(request)
        assert client.prepare_run(request) == accepted
        assert accepted.state == "pending"
        assert cast(dict[str, Any], accepted.result)["image_retained"] is False
        with pytest.raises(QueueConflictError, match="intent conflicts"):
            client.prepare_run(replace(
                request, execution=replace(
                    _execution(), image=replace(_execution().image, sha256="b" * 64),
                ),
            ))
        assert not (tmp_path / "workloads").exists()
        client.cancel_preparation(request.operation_id)
        daemon._preparations._reconcile_lock.release()
        assert daemon.wait_operation(request.operation_id, timeout=10).operation.state == "cancelled"
    finally:
        if daemon._preparations._reconcile_lock.locked():
            daemon._preparations._reconcile_lock.release()
        daemon.stop()


def test_child_and_requirement_retain_execution_without_installed_fields(tmp_path):
    from loom.pipeline.orchestration import ExecutionRequirement, SubmittedContainerRequirement
    from loom.queue.preparation import PreparationChildInput, SharedInputReceipt

    capability = _capability(tmp_path)
    execution = replace(_execution(), project_integration=None)
    shared = _policy(tmp_path).profiles["shared-container"].shared_scope
    binding = PreparationChildInput(
        "submission-a", "shared-container", "config/pipeline.yaml",
        SharedInputReceipt("sha256:" + "a" * 64, "projects", "capture"),
        None, shared_scope=shared, execution=execution, container_capability=capability,
    )
    wire = binding.to_dict()
    assert "profile_descriptor" not in wire
    assert wire["schema_version"] == 11
    assert PreparationChildInput.from_dict(wire) == binding
    requirement = capability.requirement(execution)
    assert isinstance(requirement, SubmittedContainerRequirement)
    assert ExecutionRequirement.from_dict(requirement.to_dict()) == requirement
    assert capability.satisfies(requirement)
    assert not replace(capability, environment_fingerprint="sha256:" + "b" * 64).satisfies(requirement)
    with pytest.raises(QueueServiceError, match="binding"):
        replace(binding, profile_descriptor={"profile_id": "unrelated"})
    with pytest.raises(QueueServiceError, match="integration"):
        replace(binding, execution=_execution())


@pytest.mark.parametrize("crash_after", ["capture", "pin"])
def test_preparation_resumes_retention_before_dispatch_without_recapturing(
    tmp_path, monkeypatch, crash_after,
):
    import json
    from loom.pipeline.cleanup.preparation_pins import preparation_path_is_retained
    from loom.preparation import CoordinatorPreparation
    from loom.queue import submitted_execution
    from loom.queue.deployment import CoordinatorServiceConfig
    from loom.queue.local_daemon import (
        LocalDaemon, LocalDaemonConfig, LocalDaemonPrincipal, LocalDaemonRole,
    )

    class Interrupted(BaseException):
        pass

    class AtDispatch(BaseException):
        pass

    config_path = tmp_path / "projects" / "example" / "config" / "pipeline.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("original configuration")
    image_path = tmp_path / "workloads" / "images" / "aaa" / "image.sif"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"x" * 1024)
    image_path.chmod(0o444)
    config = LocalDaemonConfig(
        coordinator_root=tmp_path / "coordinator", agent_root=None,
        run_store_root=tmp_path / "runs", resident_worker_launch_profile=None,
        cpu_capacity=0, preparation_policy=_policy(tmp_path),
        container_capabilities=(_capability(tmp_path),),
    )
    LocalDaemon.initialize(config)
    callbacks = CoordinatorPreparation(CoordinatorServiceConfig(
        config, None, tmp_path / "coordinator.json", "immutable", "active",
    ))
    daemon = LocalDaemon(config, preparation=callbacks)
    operation = daemon._preparations
    operation._reconcile_lock.acquire()
    daemon.start()
    request = replace(_request(), execution=_execution())
    client = daemon.client_view(LocalDaemonPrincipal("client-a", LocalDaemonRole.CLIENT))
    try:
        client.prepare_run(request)
        with monkeypatch.context() as patch:
            if crash_after == "capture":
                store = operation._store_result

                def interrupt_after_store(value):
                    store(value)
                    raise Interrupted

                patch.setattr(operation, "_store_result", interrupt_after_store)
            else:
                retain = submitted_execution.retain_submitted_image

                def interrupt_after_pin(*args, **kwargs):
                    retain(*args, **kwargs)
                    raise Interrupted

                patch.setattr(submitted_execution, "retain_submitted_image", interrupt_after_pin)
            with pytest.raises(Interrupted):
                operation._advance(operation._read(request.operation_id))
        captured = json.loads(operation._read(request.operation_id)["result_json"])
        assert captured["input_receipt"] is not None
        assert captured["image_retained"] is False
        if crash_after == "pin":
            assert preparation_path_is_retained(image_path)
        config_path.write_text("changed after capture")

        def inspect_dispatch(config, binding, run_name, options):
            assert preparation_path_is_retained(image_path)
            assert binding.execution == request.execution
            assert binding.input_receipt.to_dict() == captured["input_receipt"]
            snapshot = tmp_path / "snapshots" / binding.input_receipt.path
            assert (snapshot / "files" / request.config_path).read_text() == "original configuration"
            raise AtDispatch

        monkeypatch.setattr(callbacks, "prepare_child", inspect_dispatch)
        with pytest.raises(AtDispatch):
            operation._advance(operation._read(request.operation_id))
        resumed = json.loads(operation._read(request.operation_id)["result_json"])
        assert resumed["image_retained"] is True
        assert resumed["input_receipt"] == captured["input_receipt"]
        client.cancel_preparation(request.operation_id)
        operation._reconcile_lock.release()
        assert daemon.wait_operation(request.operation_id, timeout=10).operation.state == "cancelled"
    finally:
        if operation._reconcile_lock.locked():
            operation._reconcile_lock.release()
        daemon.stop()


def test_implementation_identity_tracks_bytes_and_environment_not_locations(tmp_path):
    from loom.queue.submitted_execution import submitted_implementation

    execution, capability = _execution(), _capability(tmp_path)
    identity = submitted_implementation(execution, capability)
    moved = replace(execution, image=replace(execution.image, location={
        **execution.image.location, "path": "archive/aaa/image.sif"}))
    assert submitted_implementation(moved, capability) == identity
    assert submitted_implementation(replace(execution, image=replace(execution.image, sha256="b" * 64)), capability) != identity
    assert submitted_implementation(execution, replace(capability, environment_fingerprint="sha256:" + "c" * 64)) != identity
    assert submitted_implementation(replace(execution, python_executable="/other/python"), capability) != identity
    assert "location" not in identity and "policy_id" not in identity


def test_action_implementation_joins_the_report_image_to_its_admitted_node(tmp_path):
    from types import SimpleNamespace
    from loom.queue._action_result_resolution import _report_implementation
    from loom.queue.submitted_execution import SUBMITTED_EXECUTION_SCOPE, submitted_implementation

    execution, capability = _execution(), _capability(tmp_path)
    binding = {"execution": execution.to_dict(), "container_capability": capability.to_dict()}
    assert execution.project_integration is not None
    report = {**binding, "project_preparation": {"processor": dict(execution.project_integration)}}
    stage = SimpleNamespace(fingerprint_fields={SUBMITTED_EXECUTION_SCOPE: binding})
    requirement = capability.requirement(execution)
    assert _report_implementation(report, requirement, stage) == submitted_implementation(execution, capability)
    changed = replace(execution, image=replace(execution.image, sha256="b" * 64))
    with pytest.raises(QueueConflictError, match="implementation differs"):
        _report_implementation({**report, "execution": changed.to_dict()}, requirement, stage)

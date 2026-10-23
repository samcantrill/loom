"""Actual preparation compatibility without pipeline execution or publication."""

from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from loom.fleet.probes import probe_configuration
from loom.queue._agent_process_supervisor import ResidentWorkerLaunchProfile
from loom.queue._preparation_probe import probe_preparation
from loom.queue._remote_stage_execution import ResidentProfileDescriptor
from loom.queue.errors import QueueConflictError
from loom.queue.preparation import (
    PreparationChildInput, PreparationSource, PrepareRunRequest, capture_shared_input,
)

pytestmark = [pytest.mark.unit, pytest.mark.optional_dependency]


def fixture(tmp_path, *, invalid=False, check="cpu"):
    pytest.importorskip("weave")
    source = tmp_path / "source"
    source.mkdir()
    (source / "probe.json").write_text(
        "pipeline: [invalid" if invalid else json.dumps(probe_configuration(check, "worker"))
    )
    snapshot = tmp_path / "snapshots"
    request = PrepareRunRequest(
        "preflight", "check", PreparationSource("shared", "project", ".", ("probe.json",)),
        "probe.json", "candidate",
    )
    receipt = capture_shared_input(request, source_root=source, snapshot_root=snapshot)
    descriptor = ResidentProfileDescriptor("candidate", "v2", "project", "environment", "executor")
    profile = ResidentWorkerLaunchProfile(
        project_root=tmp_path, python_executable=Path(sys.executable),
        descriptor=descriptor.to_dict(), preparation_shared_roots={"project": snapshot},
    )
    binding = PreparationChildInput(
        request.operation_id, request.preparation_profile, request.config_path,
        receipt, descriptor.to_dict(),
    )
    return profile, binding


@pytest.mark.parametrize("check", ["cpu", "storage", "gpu"])
def test_real_stage_prepares_candidate_without_running_probe(tmp_path, check):
    profile, binding = fixture(tmp_path, check=check)
    result = probe_preparation(profile, binding, agent_id="worker")
    assert result["allowed"] is True
    assert result["profile_descriptor"] == dict(profile.descriptor)
    assert result["input_manifest_digest"] == binding.input_receipt.manifest_digest
    assert not list(tmp_path.glob("**/values.bin"))


def test_invalid_source_refuses_preparation(tmp_path):
    profile, binding = fixture(tmp_path, invalid=True)
    with pytest.raises(QueueConflictError, match="preparation is incompatible"):
        probe_preparation(profile, binding, agent_id="worker")


def test_candidate_project_hook_runs_and_rejects_generic_probe(tmp_path):
    profile, binding = fixture(tmp_path)
    installed = tmp_path / "candidate_hook.py"
    marker = tmp_path / "hook-called"
    installed.write_text(
        "from pathlib import Path\n"
        "def inspect(request):\n"
        "    assert request['composition']['resolved']['pipeline']['name'] == 'fleet-check'\n"
        "    assert request['profile_descriptor']['revision'] == 'v2'\n"
        f"    Path({str(marker)!r}).write_text('candidate')\n"
        "    raise ValueError('generic infrastructure probe is not scientific input')\n"
    )
    profile = replace(profile, environment={"PYTHONPATH": str(tmp_path)})
    binding = replace(
        binding, local_scope={"agent_id": "worker", "binding_fingerprint": profile.fingerprint},
        project_preparation={
            "processor": {"schema_version": 3, "callable": "candidate_hook:inspect",
                          "evidence_namespace": "test", "target_prefix": "check-"},
            "target_run_uri": (tmp_path / "unpublished" / "check").as_uri(),
        },
    )
    with pytest.raises(QueueConflictError, match="config.project_preparation"):
        probe_preparation(profile, binding, agent_id="worker")
    assert marker.read_text() == "candidate"
    assert not (tmp_path / "unpublished").exists()


def test_old_installation_cannot_prove_candidate_preparation(tmp_path):
    profile, binding = fixture(tmp_path)
    old = replace(profile, descriptor={**profile.descriptor, "revision": "v1"})
    with pytest.raises(QueueConflictError, match="installation differs"):
        probe_preparation(old, binding, agent_id="worker")


@pytest.mark.parametrize("fault", [None, "changed_image", "different_execution"])
def test_submitted_candidate_prepares_in_selected_runtime(tmp_path, monkeypatch, fault):
    """Fake mount translation exercises actual preparation, not physical isolation."""
    from copy import deepcopy
    import hashlib
    from examples.execution.containers.apptainer_fixture import fake_apptainer
    from loom.queue import _preparation_probe
    from tests.integration.queue.test_submitted_container_agents import _fixture

    _, installed = fixture(tmp_path)
    policy, execution, _ = _fixture(tmp_path)
    snapshot = tmp_path / "snapshots"
    (snapshot / "challenge").write_bytes(b"snapshots")
    policy = replace(policy, preparation_shared_roots={"project": snapshot}, shared_roots={
        **policy.shared_roots,
        "snapshots": {"host_path": str(snapshot), "container_path": "/loom/snapshots", "access": "ro",
                      "challenge": {"path": "challenge", "sha256": hashlib.sha256(b"snapshots").hexdigest()}},
    })
    with fake_apptainer() as runtime:
        command = Path(runtime["options"]["command"])
        command.write_text(command.read_text().replace(
            "os.chdir(value)", f"os.chdir(value.replace('/loom/snapshots', {str(snapshot)!r}))"
        ))
        policy = replace(policy, runtime_options=runtime["options"])
        execution = replace(execution, python_executable=sys.executable)
        binding = replace(installed, profile_descriptor=None, execution=execution,
            container_capability=policy.capability,
            shared_scope={"capability": "shared-execution-v1", "roots": policy.capability.workload_roots, "locations": []})
        launch = policy.launch_profile(execution, workspace=tmp_path)
        actual = _preparation_probe.run_resident_probe
        from loom.pipeline.executors.apptainer.commands import SubprocessApptainerExecRunner
        run = SubprocessApptainerExecRunner.run

        def checked_run(self, *args, **kwargs):
            result = run(self, *args, **kwargs)
            assert result.returncode == 0, result.stderr
            return result

        monkeypatch.setattr(SubprocessApptainerExecRunner, "run", checked_run)
        observed = []

        def probe(profile, script, payload, **kwargs):
            observed.append(payload["context"]["input"]["roots"])
            translated = deepcopy(payload)
            # The fake runtime has no mount namespace. Translate only its
            # captured-input root to the corresponding host-visible bytes.
            translated["context"]["input"]["roots"] = {"project": str(snapshot)}
            return actual(profile, script, translated, **kwargs)

        monkeypatch.setattr(_preparation_probe, "run_resident_probe", probe)
        if fault == "changed_image":
            image = tmp_path / "workloads/aaa/image.sif"
            image.chmod(0o600)
            image.write_bytes(b"changed image bytes")
            image.chmod(0o444)
        elif fault == "different_execution":
            launch = replace(launch, submitted_execution=replace(execution, image=replace(execution.image, sha256="d" * 64)))
        if fault:
            with pytest.raises(QueueConflictError, match="submitted execution differs|candidate preparation probe failed"):
                probe_preparation(launch, binding, agent_id="worker")
        else:
            from types import SimpleNamespace
            from loom.fleet import _check_preflight
            from loom.queue import deployment
            from tests.integration.queue.test_submitted_container_agents import _config

            service = SimpleNamespace(client=_config(tmp_path, policy))
            monkeypatch.setattr(deployment, "load_outbound_agent_service_config", lambda *args, **kwargs: service)
            monkeypatch.setattr(_check_preflight, "owner", lambda request: {"owner": "retained-agent"})
            result = _check_preflight.prepare({
                "name": "worker", "agent_id": "worker", "config": str(tmp_path / "candidate.json"),
                "candidate_declaration": {}, "expected_root_id": "retained-agent",
                "bindings": {"cpu": binding.to_dict()},
            })["checks"]["cpu"]
            assert result["allowed"] is True
            assert result["execution"] == execution.to_dict()
            assert result["container_capability"] == policy.capability.to_dict()
            assert result["input_manifest_digest"] == installed.input_receipt.manifest_digest
            assert observed == [{"project": "/loom/snapshots"}]
        assert not list(tmp_path.glob("**/values.bin"))

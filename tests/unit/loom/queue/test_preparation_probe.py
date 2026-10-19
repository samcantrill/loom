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

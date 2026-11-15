"""Protected batch entry works independently of allocation PATH and home."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from loom.pipeline.executors.slurm import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.errors import SlurmPlanningError
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile, _request


def test_omitted_batch_paths_preserve_legacy_identity_and_script():
    profile = _profile(FakeSlurmCommandRunner())
    unchanged = replace(profile, batch_shell=None, batch_working_directory=None, batch_output_path=None)
    assert unchanged.configuration_fingerprint == profile.configuration_fingerprint
    assert _request(unchanged) == _request(profile)
    assert _request(profile).script.startswith("#!/usr/bin/env bash\n")


def test_selected_batch_paths_bind_replay_and_render_directives():
    profile = _profile(FakeSlurmCommandRunner())
    fields = {
        "batch_shell": "/bin/bash",
        "batch_working_directory": "/shared/owner/logs",
        "batch_output_path": "/shared/owner/logs/slurm-%j.out",
    }
    for name, value in fields.items():
        selected = replace(profile, **{name: value})
        assert selected.configuration_fingerprint != profile.configuration_fingerprint
        assert _request(selected).digest != _request(profile).digest
    request = _request(replace(profile, **fields))
    assert request.script.startswith("#!/bin/bash\n")
    assert "#SBATCH --chdir=/shared/owner/logs\n" in request.script
    assert "#SBATCH --output=/shared/owner/logs/slurm-%j.out\n" in request.script
    assert type(request).from_dict(request.to_dict()) == request
    assert _request(replace(profile, **fields)) == request


@pytest.mark.parametrize("name,value", [
    ("batch_shell", "bash"),
    ("batch_shell", "/bin/bash -l"),
    ("batch_working_directory", "/shared/../other"),
    ("batch_output_path", "/shared/log\n#SBATCH --export=ALL"),
    ("batch_output_path", "/shared/quoted'path"),
    ("batch_output_path", "/shared/escaped\\path"),
    ("batch_shell", 1),
])
def test_invalid_batch_paths_fail_before_submission(name, value):
    with pytest.raises(SlurmPlanningError, match=name):
        replace(_profile(FakeSlurmCommandRunner()), **{name: value})


def test_absolute_batch_shell_reaches_exact_bootstrap_with_unusable_path(tmp_path):
    if not Path("/bin/bash").is_file():
        pytest.skip("requires an observed absolute Bash interpreter")
    bootstrap = tmp_path / "loom"
    bootstrap.write_text(f"#!{sys.executable}\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
    bootstrap.chmod(0o700)
    profile = replace(_profile(FakeSlurmCommandRunner()), bootstrap_argv=(str(bootstrap), "slurm-bootstrap"))
    script = tmp_path / "batch.sh"
    script.write_text(_request(profile).script)
    script.chmod(0o700)
    environment = {"PATH": str(tmp_path / "no-programs")}
    before = subprocess.run([str(script)], env=environment, capture_output=True, text=True, check=False)
    assert before.returncode == 127
    selected = _request(replace(profile, batch_shell="/bin/bash"))
    script.write_text(selected.script)
    after = subprocess.run([str(script)], env=environment, capture_output=True, text=True, check=False)
    assert after.returncode == 0, after.stderr
    assert json.loads(after.stdout) == [
        "slurm-bootstrap", "--operation-id", selected.operation_id,
        "--request-digest", selected.digest,
    ]

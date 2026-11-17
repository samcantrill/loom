"""Explicit scheduler-client settings stay separate from the submitted job."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

from typing import cast

import pytest

from loom.pipeline.executors.slurm.commands import (
    FakeSlurmCommandRunner, SlurmCommandPolicy, SubprocessSlurmCommandRunner,
)
from loom.pipeline.executors.slurm.errors import SlurmCommandUnavailableError, SlurmPlanningError
from loom.pipeline.executors.slurm.history import SlurmAccountingIdentity, operation_job_name
from loom.pipeline.executors.slurm.ready_stage import ReadyStageState, SQLiteReadyStageSubmissions
from loom.pipeline.executors.slurm.trusted_user import SlurmUserPrivateFileProvider
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile, _request, _script


def _selection(tmp_path):
    for name in ("bin", "tmp", "lib"):
        (tmp_path / name).mkdir(exist_ok=True)
    return {
        "PATH": str(tmp_path / "bin"),
        "TMPDIR": str(tmp_path / "tmp"),
        "TMP": str(tmp_path / "tmp"),
        "TEMP": str(tmp_path / "tmp"),
        "LD_LIBRARY_PATH": str(tmp_path / "lib"),
        "LC_ALL": "C",
        "TZ": "Australia/Sydney",
    }


def _identity():
    return SlurmAccountingIdentity(
        job_id="17", cluster="cluster-a", job_name=operation_job_name("operation-1"),
        user_id=1000, submitted_at="2026-11-02T00:00:00Z", db_index="42", sluid="sFixture",
    )


def _calls(runner, script):
    identity = _identity()
    return [
        runner.sbatch(script),
        runner.sbatch(script, environment={}),
        runner.squeue(job_ids=("17",)),
        runner.sacct(job_ids=("17",)),
        runner.scancel(job_ids=("17",)),
        runner.discover_live_operations(),
        runner.discover_accounted_operations(started_after="2026-11-02T00:00:00Z"),
        runner.discover_named_operation(
            job_name=identity.job_name, user_id=1000, cluster="cluster-a",
            started_after="2026-11-01T23:59:00Z", ended_before="2026-11-02T00:01:00Z",
        ),
        runner.scancel_named_operation(identity),
    ]


@pytest.mark.parametrize("bounded", [False, True])
def test_selected_lookup_environment_and_job_export_reach_every_command(tmp_path, monkeypatch, bounded):
    selected = _selection(tmp_path)
    parent = tmp_path / "parent-bin"
    parent.mkdir()
    forbidden = ("HTTPS_PROXY", "SBATCH_PARTITION", "SLURM_CLUSTERS", "PYTHONPATH", "LD_PRELOAD")
    for key in forbidden:
        monkeypatch.setenv(key, "parent-only")
    monkeypatch.setenv("PATH", str(parent))
    keys = (*selected, "SLURM_TIME_FORMAT", *forbidden)
    for command in ("sbatch", "squeue", "sacct", "scancel"):
        wrong = parent / command
        wrong.write_text(f"#!{sys.executable}\nprint('WRONG EXECUTABLE')\n")
        wrong.chmod(0o700)
        executable = Path(selected["PATH"]) / command
        executable.write_text(
            f"#!{sys.executable}\nimport json,os,sys,tempfile\n"
            f"print(json.dumps({{'env': {{k: os.environ.get(k) for k in {keys!r}}}, "
            "'argv': sys.argv[1:], 'temp': tempfile.gettempdir()}))\n"
        )
        executable.chmod(0o700)
    runner = SubprocessSlurmCommandRunner(
        command_policy=SlurmCommandPolicy(10, 60, 10) if bounded else None,
        client_environment=selected,
    )
    fake = FakeSlurmCommandRunner(client_environment=selected)
    results = _calls(runner, tmp_path / "job.sh")
    _calls(fake, tmp_path / "job.sh")
    for result, simulated in zip(results, fake.client_environments, strict=True):
        assert result.ok, result.stderr
        report = json.loads(result.stdout)
        expected = dict(selected)
        if result.command == "sacct":
            expected.update(TZ="UTC", SLURM_TIME_FORMAT="%Y-%m-%dT%H:%M:%S")
        assert simulated == expected
        assert {key: value for key, value in report["env"].items() if value is not None} == expected
        assert report["temp"] == selected["TMPDIR"]
        assert report["argv"] == list(result.argv[1:])
        if result.command == "sbatch":
            assert report["argv"].count("--export=NIL") == 1
    assert [result.argv for result in results] == [argv for _command, argv in fake.calls]


def test_selected_path_does_not_fall_back_to_parent_path(tmp_path, monkeypatch):
    selected = _selection(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    executable = parent / "squeue"
    executable.write_text(f"#!{sys.executable}\nraise SystemExit('must not run')\n")
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(parent))
    runner = SubprocessSlurmCommandRunner(client_environment=selected)
    with pytest.raises(SlurmCommandUnavailableError, match="selected PATH"):
        runner.require("squeue")
    with pytest.raises(SlurmCommandUnavailableError, match="selected PATH"):
        runner.squeue()


def test_batch_uses_selected_environment_and_remaining_deadline_in_real_process(tmp_path):
    selected = _selection(tmp_path)
    executable = Path(selected["PATH"]) / "sacct"
    executable.write_text(
        f"#!{sys.executable}\nimport json,os,sys\n"
        "print(json.dumps([sys.argv[1:], os.environ['TZ'], os.environ['TMPDIR']]))\n"
    )
    executable.chmod(0o700)
    runner = SubprocessSlurmCommandRunner(command_policy=SlurmCommandPolicy(10, 60, 10), client_environment=selected)
    selection = {
        "job_names": [operation_job_name("one"), operation_job_name("two")],
        "user_id": 1000, "cluster": "cluster-a",
        "started_after": "2026-11-01T23:59:00Z", "ended_before": "2026-11-02T00:01:00Z",
        "timeout_seconds": 1,
    }
    result = runner.discover_named_operations(**selection)
    argv, zone, temporary = json.loads(result.stdout)
    assert "--name=" + ",".join(selection["job_names"]) in argv
    assert zone == "UTC" and temporary == selected["TMPDIR"]
    executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(60)\n")
    with pytest.raises(subprocess.TimeoutExpired) as raised:
        runner.discover_named_operations(**{**selection, "timeout_seconds": 0.1})
    assert raised.value.timeout == 0.1


@pytest.mark.parametrize("value", [
    {}, [], {"PATH": "relative"}, {"PATH": "/bin:"}, {"PATH": "/bin:.:/usr/bin"},
    {"PATH": "/bin", "TMPDIR": "/scratch/../tmp"},
    {"PATH": "/bin", "LD_LIBRARY_PATH": ":/lib"},
    {"PATH": "/bin", "LC_ALL": "C\n"}, {"PATH": "/bin", "LANG": False},
    *({"PATH": "/bin", key: "unapproved"} for key in (
        "SBATCH_PARTITION", "SCANCEL_STATE", "SQUEUE_FORMAT", "SACCT_FORMAT",
        "SLURM_CONF", "SLURM_TIME_FORMAT", "HTTPS_PROXY", "LD_PRELOAD", "PYTHONPATH",
    )),
])
def test_invalid_selection_is_rejected_by_real_and_fake_before_side_effects(value, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("started a command"))
    for constructor in (SubprocessSlurmCommandRunner, FakeSlurmCommandRunner):
        with pytest.raises(SlurmPlanningError, match="client_environment"):
            constructor(client_environment=value)


def test_per_call_override_is_rejected_without_a_submission(tmp_path, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("started a command"))
    for constructor in (SubprocessSlurmCommandRunner, FakeSlurmCommandRunner):
        runner = constructor(client_environment=_selection(tmp_path))
        with pytest.raises(SlurmPlanningError, match="per-call environment"):
            runner.sbatch("job.sh", environment={"PATH": "/different/bin"})
        if isinstance(runner, FakeSlurmCommandRunner):
            assert runner.calls == []
            assert runner.environments == []


def test_environment_is_immutable_and_bound_only_when_selected(tmp_path):
    legacy = _profile(FakeSlurmCommandRunner())
    omitted = replace(legacy, runner=FakeSlurmCommandRunner(client_environment=None))
    assert omitted.configuration_fingerprint == legacy.configuration_fingerprint
    selected = _selection(tmp_path)
    real = SubprocessSlurmCommandRunner(client_environment=selected)
    fake = FakeSlurmCommandRunner(client_environment=selected)
    profile = replace(legacy, runner=real)
    assert profile.configuration_fingerprint != legacy.configuration_fingerprint
    assert replace(legacy, runner=fake).configuration_fingerprint == profile.configuration_fingerprint
    assert replace(legacy, runner=SubprocessSlurmCommandRunner(
        client_environment=dict(reversed(list(selected.items()))),
    )).configuration_fingerprint == profile.configuration_fingerprint
    for key, value in (("PATH", "/other/bin"), ("TMPDIR", "/other/tmp"),
                       ("LD_LIBRARY_PATH", "/other/lib"), ("TZ", "UTC")):
        changed = replace(legacy, runner=FakeSlurmCommandRunner(client_environment={**selected, key: value}))
        assert changed.configuration_fingerprint != profile.configuration_fingerprint
    selected["PATH"] = "/mutated/bin"
    for runner in (real, fake):
        assert runner.client_environment is not None
        assert runner.client_environment["PATH"] != selected["PATH"]
        with pytest.raises(TypeError):
            cast(dict[str, str], runner.client_environment)["PATH"] = "/also-mutated/bin"


def test_ready_stage_submits_once_with_selected_client_environment(tmp_path, monkeypatch):
    selected = _selection(tmp_path)
    capture = tmp_path / "client-call.json"
    executable = Path(selected["PATH"]) / "sbatch"
    executable.write_text(
        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        f"with Path({str(capture)!r}).open('x') as output:\n"
        "    json.dump({'argv': sys.argv[1:], 'tmp': os.environ.get('TMPDIR')}, output)\n"
        "print('17')\n"
    )
    executable.chmod(0o700)
    for command in ("squeue", "sacct", "scancel"):
        (Path(selected["PATH"]) / command).symlink_to(executable)
    monkeypatch.setenv("PATH", "/nonexistent-parent-path")
    runner = SubprocessSlurmCommandRunner(
        command_policy=SlurmCommandPolicy(10, 60, 10), client_environment=selected,
    )
    profile = replace(_profile(runner), job_private_file_provider=SlurmUserPrivateFileProvider(
        root=tmp_path / "credentials", descriptor="client-environment-test",
    ))
    request = _request(profile)
    script = _script(tmp_path, request)
    store = SQLiteReadyStageSubmissions(tmp_path / "journal.sqlite")
    submitted = store.submit(request, profile, script)
    assert submitted.state is ReadyStageState.ACCEPTED
    assert submitted.job_id == "17"
    captured = json.loads(capture.read_text())
    assert captured["tmp"] == selected["TMPDIR"]
    assert captured["argv"].count("--export=NIL") == 1
    assert captured["argv"][-1] == str(script)
    reopened = SQLiteReadyStageSubmissions(store.path, _allow_initialize=False)
    assert reopened.submit(request, profile, script) == submitted

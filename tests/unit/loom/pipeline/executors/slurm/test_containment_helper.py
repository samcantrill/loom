"""Bounded helper IO and process groups, independent of site containment proof."""

from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import time

import pytest

from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
from loom.pipeline.executors.slurm.errors import SlurmPlanningError
from loom.pipeline.executors.slurm.ready_stage import SlurmContainmentHelper
from tests.unit.loom.pipeline.executors.slurm.test_command_policy import _assert_child_stopped
from tests.unit.loom.pipeline.executors.slurm.test_ready_stage import _profile


def _helper(program, *, timeout: float = 2):
    return SlurmContainmentHelper(
        "bounded-fixture", (sys.executable, "-c", program), timeout,
        process_policy="bounded-v1",
    )


def test_selected_policy_changes_only_selected_helper_identity():
    legacy = SlurmContainmentHelper("helper", ("/site/helper",))
    same = replace(legacy, process_policy=None)
    selected = replace(legacy, process_policy="bounded-v1")
    profile = _profile(FakeSlurmCommandRunner())
    assert replace(profile, containment_helper=legacy).configuration_fingerprint == replace(profile, containment_helper=same).configuration_fingerprint
    assert replace(profile, containment_helper=legacy).configuration_fingerprint != replace(profile, containment_helper=selected).configuration_fingerprint


@pytest.mark.parametrize("timeout", [True, 0, -1, "2", float("nan"), float("inf"), 3601, 10**400])
def test_selected_timeout_validation_precedes_execution(timeout, monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("started helper"))
    with pytest.raises(SlurmPlanningError, match="timeout"):
        _helper("pass", timeout=timeout)


def test_unknown_policy_and_oversize_request_do_not_start_helper(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("started helper"))
    with pytest.raises(SlurmPlanningError, match="policy"):
        SlurmContainmentHelper("helper", ("/site/helper",), process_policy="unknown")
    assert _helper("pass").resolve({"large": "x" * 16_384}) is None


def test_input_and_output_progress_concurrently_without_pipe_deadlock():
    program = (
        "import json,os,sys\n"
        "os.write(1, b' ' * 12000)\n"
        "request=json.load(sys.stdin)\n"
        "print(json.dumps({'received': len(request['value'])}))\n"
    )
    assert _helper(program).resolve({"value": "x" * 12000}) == {"received": 12000}


def test_nonreading_helper_has_one_deadline_including_input_delivery():
    started = time.monotonic()
    assert _helper("import time; time.sleep(60)", timeout=0.2).resolve({"value": "x" * 16000}) is None
    assert time.monotonic() - started < 5


@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-state evidence")
@pytest.mark.parametrize("failure", ["timeout", "stdout", "stderr"])
@pytest.mark.parametrize("parent_exits", [False, True])
def test_helper_failure_stops_its_wrapper_and_descendant(tmp_path, failure, parent_exits):
    pid_path = tmp_path / "child.pid"
    action = (
        "import time; time.sleep(60)" if failure == "timeout" else
        "import os\nwhile True: os.write(" + ("1" if failure == "stdout" else "2") + ", b'x' * 4096)"
    )
    child = (
        "import time\nfrom pathlib import Path\n"
        f"while not Path({str(pid_path)!r}).exists(): time.sleep(0.01)\n" + action
    )
    wrapper = (
        "import subprocess,sys\nfrom pathlib import Path\n"
        f"p=subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        f"Path({str(pid_path)!r}).write_text(str(p.pid))\n"
        + ("raise SystemExit(0)\n" if parent_exits else "p.wait()\n")
    )
    started = time.monotonic()
    assert _helper(wrapper, timeout=1).resolve({"request": "fixture"}) is None
    assert time.monotonic() - started < 5
    _assert_child_stopped(int(pid_path.read_text()))


@pytest.mark.parametrize("program", [
    "raise SystemExit(1)", "print('not JSON')", "print('[]')",
    "import os; os.write(1, b'\\xff')",
])
def test_failed_or_malformed_response_is_unavailable(program):
    assert _helper(program).resolve({"request": "fixture"}) is None


def test_binary_limit_is_bytes_and_accepts_an_exact_size_response():
    exact = "import os; os.write(1, b' ' * (16384 - 2) + b'{}')"
    assert _helper(exact).resolve({}) == {}
    oversized = "import os; os.write(1, b' ' * (16385 - 2) + b'{}')"
    assert _helper(oversized).resolve({}) is None


def test_selected_helper_retains_parent_scratch_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    result = _helper("import json,tempfile; print(json.dumps({'tmp': tempfile.gettempdir()}))").resolve({})
    assert result is not None and isinstance(result["tmp"], str)
    assert Path(result["tmp"]) == tmp_path

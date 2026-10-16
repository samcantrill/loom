"""Public parser/rendering and reporter lifecycle, without a second recovery matrix."""
import io
import json
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace

import pytest

from loom.cli.main import build_parser, main
from loom.fleet import upgrades


@pytest.fixture
def cli(monkeypatch, tmp_path):
    from loom.fleet import configuration
    from loom.fleet._host import atomic
    inventory = SimpleNamespace(path=tmp_path / "fleet.json")
    monkeypatch.setattr(configuration, "load_inventory", lambda path: inventory)
    (tmp_path / "operations/window").mkdir(parents=True)
    atomic(tmp_path / "operations/window/intent.json", {"kind": "runtime-upgrade"})
    return inventory


@pytest.mark.parametrize("format", ["json", "text"])
def test_cli_progress_is_explicit_stderr_and_final_result_unchanged(cli, monkeypatch, format):
    result = {"outcome": "waiting", "reason": "PRIVATE-result", "operation_id": "window"}
    def native(**options):
        observer = options["observation"]
        observer.kind = "runtime-upgrade"
        observer.enter("checking")
        observer.reason = "check_failed"
        return result
    monkeypatch.setattr(upgrades, "_upgrade", native)
    args = ["fleet", "operation", "resume", "window", "--fleet", str(cli.path), "--format", format]
    quiet, quiet_err = io.StringIO(), io.StringIO()
    assert main(args, stdout=quiet, stderr=quiet_err) == 2
    assert quiet_err.getvalue() == ""
    output, errors = io.StringIO(), io.StringIO()
    assert main([*args, "--progress", "json"], stdout=output, stderr=errors) == 2
    assert output.getvalue() == quiet.getvalue()
    if format == "json":
        assert json.loads(output.getvalue()) == result
    records = [json.loads(line) for line in errors.getvalue().splitlines()]
    assert records[-1]["state"] == "waiting"
    assert records[-1]["phase"] == "checking"
    assert records[-1]["reason_code"] == "check_failed"
    assert "PRIVATE" not in errors.getvalue() and "window" not in errors.getvalue()


def test_retry_control_routes_existing_ids_with_progress(cli, monkeypatch):
    calls = []
    def native(**options):
        calls.append(options)
        return {"outcome": "complete"}
    monkeypatch.setattr(upgrades, "_upgrade", native)
    out, err = io.StringIO(), io.StringIO()
    assert main(["fleet", "operation", "retry-control", "window", "--fleet", str(cli.path),
                 "--failed-control", "failed", "--operation-id", "successor", "--progress", "json", "--format", "json"],
                stdout=out, stderr=err) == 0
    assert (calls[0]["operation_id"], calls[0]["failed_control"], calls[0]["new_control"]) == ("window", "failed", "successor")
    assert json.loads(err.getvalue().splitlines()[-1])["action"] == "retry-control"


def test_progress_rejects_preview_and_nonupgrade_before_mutation(cli, monkeypatch):
    from loom.fleet._host import atomic
    from loom.fleet import ssh_operations
    monkeypatch.setattr(upgrades, "preview", lambda *a, **k: pytest.fail("preview executed"))
    monkeypatch.setattr(ssh_operations, "apply", lambda *a, **k: pytest.fail("setup mutated"))
    for args in [
        ["upgrade", "--runtime-release", "PRIVATE", "--plan"],
        ["operation", "resume", "window"],
    ]:
        atomic(cli.path.parent / "operations/window/intent.json", {"kind": "setup"})
        out, err = io.StringIO(), io.StringIO()
        assert main(["fleet", *args, "--fleet", str(cli.path), "--progress", "json"], stdout=out, stderr=err) != 0
    with pytest.raises(SystemExit):
        build_parser().parse_args(["fleet", "operation", "status", "window", "--fleet", "lab", "--progress", "json"])


@pytest.mark.parametrize("exception,state", [(ValueError("PRIVATE-exception"), "error"), (KeyboardInterrupt(), "interrupted")])
def test_reporter_stops_and_preserves_native_exception(monkeypatch, exception, state):
    observers, records = [], []
    def native(**options):
        observers.append(options["observation"])
        raise exception
    monkeypatch.setattr(upgrades, "_upgrade", native)
    with pytest.raises(type(exception)) as caught:
        upgrades.upgrade(object(), operation_id="window", progress=records.append)
    assert caught.value is exception
    assert observers[0].worker is not None and not observers[0].worker.is_alive()
    assert records[-1]["state"] == state
    assert "PRIVATE" not in json.dumps(records)


def test_heartbeat_advances_while_native_call_is_held_and_is_rate_bounded(monkeypatch):
    entered, release, heartbeat = threading.Event(), threading.Event(), threading.Event()
    records, times, outputs = [], [], []
    def sink(snapshot):
        records.append(snapshot)
        times.append(time.monotonic())
        if len([row for row in records if row["event"] == "heartbeat"]) == 2:
            heartbeat.set()
    def native(**options):
        options["observation"].enter("replacing")
        entered.set()
        assert release.wait(15)
        return {"outcome": "complete"}
    monkeypatch.setattr(upgrades, "_upgrade", native)
    worker = threading.Thread(target=lambda: outputs.append(upgrades.upgrade(object(), operation_id="window", progress=sink)))
    worker.start()
    try:
        assert entered.wait(2)
        assert heartbeat.wait(12)
        assert not outputs
        current = records[-1]
        assert current["phase"] == "replacing"
        assert current["elapsed_seconds"] >= 4.9
        beats = [instant for row, instant in zip(records, times) if row["event"] == "heartbeat"]
        assert len(beats) == 2
        assert beats[1] - beats[0] >= 4.9
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert outputs == [{"outcome": "complete"}]
    assert records[-1]["event"] == "result"
    assert not any(t.name == "loom-upgrade-progress" and t.is_alive() for t in threading.enumerate())


def test_broken_stderr_preserves_native_result_and_requests(cli, monkeypatch):
    calls = []
    def native(**options):
        calls.append(options["operation_id"])
        return {"outcome": "complete"}
    class Broken(io.StringIO):
        def write(self, value):
            raise BrokenPipeError("PRIVATE-sink")
    monkeypatch.setattr(upgrades, "_upgrade", native)
    out = io.StringIO()
    assert main(["fleet", "operation", "resume", "window", "--fleet", str(cli.path), "--progress", "json", "--format", "json"], stdout=out, stderr=Broken()) == 0
    assert calls == ["window"]
    assert json.loads(out.getvalue()) == {"outcome": "complete"}


@pytest.mark.parametrize("blocked", [False, True], ids=["healthy-pipe", "full-pipe"])
def test_descriptor_progress_preserves_successful_process_exit(tmp_path, blocked):
    script = textwrap.dedent('''
        import json
        import os
        from pathlib import Path
        import sys
        import threading
        from types import SimpleNamespace
        from loom.cli.main import main
        from loom.fleet import configuration, upgrades
        from loom.fleet._host import atomic

        root = Path(sys.argv[1])
        blocked = sys.argv[2] == "True"
        inventory = SimpleNamespace(path=root / "fleet.json")
        configuration.load_inventory = lambda path: inventory
        (root / "operations/window").mkdir(parents=True)
        atomic(root / "operations/window/intent.json", {"kind": "runtime-upgrade"})

        # Model an operator whose progress reader has stopped draining stderr.
        if blocked:
            os.set_blocking(2, False)
            try:
                while True:
                    os.write(2, b"x" * 4096)
            except BlockingIOError:
                pass
            os.set_blocking(2, True)

        entered, finished = threading.Event(), threading.Event()
        original = upgrades.upgrade
        def observed(*args, progress=None, **options):
            def sink(snapshot):
                entered.set()
                progress(snapshot)
                finished.set()
            return original(*args, progress=sink, **options)
        def native(**options):
            assert entered.wait(2), "reporter did not attempt progress"
            if blocked:
                assert not finished.wait(0.1), "stderr pipe unexpectedly drained"
            else:
                assert finished.wait(2), "healthy progress was not delivered"
            return {"outcome": "complete"}
        upgrades.upgrade = observed
        upgrades._upgrade = native
        raise SystemExit(main([
            "fleet", "operation", "resume", "window", "--fleet", str(inventory.path),
            "--progress", "json", "--format", "json",
        ]))
    ''')
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), str(blocked)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    timed_out = False
    try:
        # communicate() would drain stderr and conceal the shutdown failure.
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
    finally:
        output, errors = process.communicate(timeout=5)
    assert not timed_out, "successful native operation could not exit with a full stderr pipe"
    assert process.returncode == 0, errors[-1000:]
    assert json.loads(output) == {"outcome": "complete"}
    if not blocked:
        records = [json.loads(line) for line in errors.splitlines()]
        assert records[0]["event"] == "phase"
        assert records[-1]["event"] == "result"
        assert records[-1]["state"] == "complete"
        assert all(len(line.encode("utf-8")) + 1 <= 1024 for line in errors.splitlines())


@pytest.mark.parametrize("exception,code", [
    (upgrades.sshops.SshUnavailable("PRIVATE-host"), "host_unavailable"),
    (upgrades.CoordinatorClientError("unavailable", boundary="transport", operation="observe_status"), "coordinator_unavailable"),
    (upgrades.QueueConfigError("PRIVATE-path"), "input_invalid"),
    (upgrades.QueueConflictError("PRIVATE-owner"), "native_refusal"),
])
def test_preoperation_typed_failures_keep_safe_codes(monkeypatch, exception, code):
    records = []
    def native(**options):
        raise exception
    monkeypatch.setattr(upgrades, "_upgrade", native)
    with pytest.raises(type(exception)):
        upgrades.upgrade(object(), operation_id="PRIVATE-operation", progress=records.append)
    assert records[-1]["state"] == "error"
    assert records[-1]["reason_code"] == code
    assert "PRIVATE" not in json.dumps(records)

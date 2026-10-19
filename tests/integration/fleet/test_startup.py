"""A real delayed tmux launch publishes native process/boot ownership once."""
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

import pytest

from loom.fleet import _host, _startup
from loom.queue.operations import inspect_native_service
from tests.integration.fleet.test_service_lifecycle import configuration

pytestmark = pytest.mark.integration


def test_tmux_launch_ready_after_twenty_seconds_resumes_same_native_process(tmp_path, monkeypatch):
    config = configuration(tmp_path)
    root = config.agent_root
    assert root is not None
    root_id = inspect_native_service(root).owner
    release, ready = tmp_path / "release-start", tmp_path / "ready"
    executable = tmp_path / "delayed-service"
    executable.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\nimport time\n"
        "from loom.queue._service_lifetime import record_process\n"
        f"while not Path({str(release)!r}).exists(): time.sleep(0.05)\n"
        f"record_process(Path({str(root)!r}), stopped=False, coordinator_id='coordinator', session_id='session')\n"
        f"Path({str(ready)!r}).touch()\n"
        "time.sleep(120)\n"
    )
    executable.chmod(0o700)
    monkeypatch.setattr(_host, "sys", SimpleNamespace(executable=str(executable)))
    with tempfile.TemporaryDirectory(prefix="lf-start-") as temporary:
        admin = Path(temporary)
        request = {"name": "worker", "request_id": "delayed-native-start", "root": str(root),
                   "admin": str(admin), "config": str(tmp_path / "role.json"),
                   "expected_root_id": root_id, "coordinator_id": "coordinator",
                   "release": {"descriptor_sha256": "selected-runtime"}}
        pidfd = None
        try:
            started = time.monotonic()
            with pytest.raises(_startup.ServiceStarting):
                _host.start(request)
            assert time.monotonic() - started >= 20
            record = _host.read(_startup.startup_path(request))
            pidfd = os.pidfd_open(record["process"]["pid"])
            assert not select.select([pidfd], [], [], 0)[0]
            time.sleep(max(0, 21 - (time.monotonic() - started)))
            release.touch()
            deadline = time.monotonic() + 10
            while not ready.exists():
                assert time.monotonic() < deadline
                assert not select.select([pidfd], [], [], 0.05)[0]
            result = _host.start(dict(request))
            assert result["native_owner"]["value"]["ownership"] == "live"
            assert result["native_owner"]["value"]["expected_process"] == record["process"]["pid"]
            retained = _host.read(_startup.startup_path(request))
            assert retained["deadline"] == record["deadline"] and retained["ready"]
            assert retained["process"] == record["process"]
        finally:
            subprocess.run(["tmux", "-S", str(admin / "tmux.sock"), "kill-server"],
                           capture_output=True)
            if pidfd is not None:
                try:
                    assert select.select([pidfd], [], [], 10)[0]
                finally:
                    os.close(pidfd)

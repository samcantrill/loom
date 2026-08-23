"""E2E smoke coverage for deterministic queue CLI commands."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from loom.cli.main import main


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_queue_cli_preflight_and_start_smoke(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: gpu-pool
              mode: managed
              resources:
                gpu: 1
          queues:
            - queue_name: gpu
              pool_name: gpu-pool
        """,
        encoding="utf-8",
    )
    preflight_out = io.StringIO()
    preflight_err = io.StringIO()
    start_out = io.StringIO()
    start_err = io.StringIO()

    assert (
        main(
            ["queue", "preflight", str(config_path)],
            stdout=preflight_out,
            stderr=preflight_err,
        )
        == 0
    )
    assert (
        main(
            ["queue", "start", str(config_path)],
            stdout=start_out,
            stderr=start_err,
        )
        == 0
    )

    assert preflight_err.getvalue() == ""
    assert "queue preflight" in preflight_out.getvalue()
    assert start_err.getvalue() == ""
    assert "queue service: running" in start_out.getvalue()
    assert "scope: in_process_command" in start_out.getvalue()


def test_queue_cli_pool_status_uses_existing_v1_envelope(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    config_path = tmp_path / "queue.yaml"
    config_path.write_text(
        f"""
        queue:
          service:
            db_path: {tmp_path / "queue.sqlite"}
          pools:
            - pool_name: local-pool
              mode: managed
          queues:
            - queue_name: local
              pool_name: local-pool
        """,
        encoding="utf-8",
    )
    output = io.StringIO()

    assert (
        main(
            [
                "queue",
                "status",
                str(config_path),
                "--pool",
                "local-pool",
                "--format",
                "json",
            ],
            stdout=output,
            stderr=io.StringIO(),
        )
        == 0
    )

    envelope = json.loads(output.getvalue())
    assert envelope["schema_version"] == "loom.cli.queue.status.v1"
    assert set(envelope) == {"schema_version", "ok", "warnings", "result"}
    assert set(envelope["result"]["pool"]) == {
        "pool_name",
        "controller_max_active_items",
        "counts",
        "active_attempts",
    }


def test_managed_local_queue_example_is_rerunnable(tmp_path: Path) -> None:
    script = (
        REPO_ROOT
        / "examples"
        / "operations"
        / "managed-local-queue"
        / "run_managed_local_queue.py"
    )
    output_root = tmp_path / "managed-local-queue"
    env = dict(os.environ)
    env["LOOM_EXAMPLE_OUTPUT_ROOT"] = str(output_root)

    for _ in range(2):
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=script.parent,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"managed-local example failed with exit {result.returncode}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        assert "coordinator: coordinator-" in result.stdout
        assert "status: SUCCEEDED" in result.stdout
        assert "stages: produce,consume" in result.stdout
        assert "admissions: 1" in result.stdout

    run_roots = sorted(output_root.glob("run-*"))
    assert len(run_roots) == 2
    for run_root in run_roots:
        assert (run_root / "coordinator" / "control.sqlite").is_file()
        assert (run_root / "coordinator" / "execution.sqlite").is_file()
        assert (run_root / "agent" / "journal.sqlite").is_file()
        assert not (run_root / "coordinator" / "daemon.sock").exists()

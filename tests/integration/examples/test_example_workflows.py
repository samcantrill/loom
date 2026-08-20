"""Integration coverage for selected full example workflows."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]

REPO_ROOT = Path(__file__).resolve()
for candidate in REPO_ROOT.parents:
    if (candidate / "pyproject.toml").exists():
        REPO_ROOT = candidate
        break
else:
    raise RuntimeError("unable to locate repository root")
EXAMPLES_ROOT = REPO_ROOT / "examples"


def test_example_captured_logs_records_captured_output(
    tmp_path: Path,
) -> None:
    output = _run_example_script(
        script=EXAMPLES_ROOT / "operations" / "captured-logs" / "run_captured_logs.py",
        tmp_path=tmp_path / "captured-logs",
    )
    fields = _summary_fields(output)

    assert fields["run_status"] == "SUCCEEDED"
    assert fields["output_names"] == "data,report"
    assert fields["outputs_are_refs"] == "True"
    assert fields["stdout_tail"] == "stdout line two"
    assert fields["stderr_path_available"] == "True"
    run_uri_path = _run_uri_path(fields["run_uri"])
    assert run_uri_path.exists()
    assert (run_uri_path / "artifacts" / "noisy" / "report.txt").read_text(
        encoding="utf-8"
    ) == "registered report\n"
    assert (
        run_uri_path / "stages" / "noisy" / "workspace" / "notes" / "project.log"
    ).read_text(encoding="utf-8") == "project-owned workspace file\n"


def test_example_failing_run_reports_diagnostics_summary(
    tmp_path: Path,
) -> None:
    output = _run_example_script(
        script=EXAMPLES_ROOT / "operations" / "failing-run" / "run_failure_diagnostics.py",
        tmp_path=tmp_path / "failing-run",
    )
    fields = _summary_fields(output)

    assert fields["preflight_status"] == "PASS"
    assert fields["run_status"] == "FAILED"
    assert fields["failed_stages"] == "build"
    assert int(fields["artifact_count"]) == 0
    run_uri_path = _run_uri_path(fields["run_uri"])
    assert run_uri_path.exists()


def test_example_resource_preflight_reports_resource_warnings_and_strict_exit(
    tmp_path: Path,
) -> None:
    output = _run_example_script(
        script=EXAMPLES_ROOT
        / "operations"
        / "resource-preflight"
        / "run_resource_preflight.py",
        tmp_path=tmp_path / "resource-preflight",
    )
    fields = _summary_fields(output)

    assert fields["normal_status"] == "WARN"
    assert fields["strict_status"] == "WARN"
    assert "resource.ignored" in fields["diagnostic_codes"].split(",")


def test_example_resource_leases_coordinate_blocked_then_released_state(
    tmp_path: Path,
) -> None:
    output = _run_example_script(
        script=EXAMPLES_ROOT / "operations" / "resource-leases" / "run_resource_leases.py",
        tmp_path=tmp_path / "resource-leases",
    )
    fields = _summary_fields(output)

    assert fields["counter_name"] == "resource:gpu"
    assert fields["first_lease_kind"] == "resource"
    assert fields["blocked_category"] == "conflict"
    assert fields["released_state"] == "released"
    assert fields["reacquired_kind"] == "resource"


def test_example_offline_import_rejections_report_rejection_codes_and_acceptance(
    tmp_path: Path,
) -> None:
    output = _run_example_script(
        script=EXAMPLES_ROOT
        / "operations"
        / "offline-import-rejections"
        / "run_offline_import_rejections.py",
        tmp_path=tmp_path / "offline-import",
    )
    fields = _summary_fields(output)

    assert fields["incomplete_code"].startswith("authority_offline_import_")
    assert fields["conflict_code"].startswith("authority_offline_import_")
    assert fields["accepted_status"] not in {"", "FAILED"}
    assert fields["accepted_status"] != "FAIL"
    assert fields["conflict_code"] != fields["incomplete_code"]
    assert not fields["conflict_code"].startswith("authority_offline_import_incomplete")


def _run_example_script(*, script: Path, tmp_path: Path) -> str:
    output_root = tmp_path / "outputs"
    env = _example_environment(output_root=output_root)

    result = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(script.parent),
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{script} failed with exit {result.returncode}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )

    if not result.stdout:
        raise AssertionError(f"{script} produced no output")

    return result.stdout


def _summary_fields(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.strip().partition(": ")
        if separator:
            parsed[key] = value
    if not parsed:
        raise AssertionError("expected example output to include key-value summary lines")
    return parsed


def _example_environment(*, output_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    pythonpath: list[str] = []
    current_pythonpath = env.get("PYTHONPATH")
    if current_pythonpath:
        pythonpath.append(current_pythonpath)
    pythonpath.extend([str(REPO_ROOT), str(REPO_ROOT / "src")])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env["LOOM_EXAMPLE_OUTPUT_ROOT"] = str(output_root)
    env["LOOM_EXAMPLE_RUN_ROOT"] = str(output_root / "runs")
    env["PYTHONUNBUFFERED"] = "1"
    output_root.mkdir(parents=True, exist_ok=True)
    return env


def _run_uri_path(run_uri: str) -> Path:
    parsed = urlparse(run_uri)
    if parsed.scheme != "file":
        raise AssertionError(f"expected file URI run URI, got {run_uri!r}")
    return Path(parsed.path)

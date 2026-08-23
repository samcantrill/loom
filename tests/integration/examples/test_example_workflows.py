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


def test_example_run_catalog_and_bundles_compares_and_preserves_payload(
    tmp_path: Path,
) -> None:
    script = (
        EXAMPLES_ROOT
        / "operations"
        / "run-catalog-and-bundles"
        / "run_catalog_workflow.py"
    )
    for _ in range(2):
        fields = _summary_fields(
            _run_example_script(script=script, tmp_path=tmp_path / "run-catalog-and-bundles")
        )
        assert fields["indexed_run_count"] == "2"
        assert fields["listed_run_count"] == "2"
        assert int(fields["different_entries"]) > 0
        assert fields["exported_payload_count"] == "1"
        assert fields["inspected_payload_count"] == "1"
        assert fields["imported_payload_count"] == "1"
        assert fields["payload_bytes_equal"] == "True"
        imported_run = _run_uri_path(fields["imported_run_uri"])
        assert (imported_run / "imported_payloads").is_dir()


def test_example_local_pipeline_reuses_then_repairs_only_affected_branch(
    tmp_path: Path,
) -> None:
    script = EXAMPLES_ROOT / "execution" / "local" / "run_pipeline.py"
    fields = _summary_fields(_run_example_script(script=script, tmp_path=tmp_path))

    assert fields["first_status"] == "SUCCEEDED"
    assert fields["resume_status"] == "SUCCEEDED"
    assert fields["repair_status"] == "SUCCEEDED"
    assert fields["config_fingerprint"].startswith("sha256:")
    assert int(fields["pipeline_stage_fingerprint_count"]) > 0
    assert fields["resume_actions"] == (
        "left_seed=REUSE,left_summarize=REUSE,"
        "right_seed=REUSE,right_summarize=REUSE"
    )
    assert fields["repair_actions"] == (
        "left_seed=RUN,left_summarize=RUN,"
        "right_seed=REUSE,right_summarize=REUSE"
    )
    assert fields["repair_reason"] == "ARTIFACT_CHECKSUM_MISMATCH"


def test_example_fake_backend_and_local_materialization(tmp_path: Path) -> None:
    script = (
        EXAMPLES_ROOT
        / "storage"
        / "fake-backend-materialization"
        / "run_fake_backend_materialization.py"
    )
    for _ in range(2):
        fields = _summary_fields(_run_example_script(script=script, tmp_path=tmp_path))

        assert fields["registered_backend_kind"] == "example-backend"
        assert fields["materialize_capability"] == "unsupported"
        assert fields["backend_operation_support"] == "unsupported"
        assert fields["backend_operation"] == "materialize"
        assert fields["materialization_status"] == "succeeded"
        assert fields["materialization_operation"] == "artifact.materialize.local.copy"
        assert fields["checksum_verified"] == "True"
        assert fields["bytes_equal"] == "True"
        assert int(fields["bytes_copied"]) > 0


def test_example_deterministic_sweep_runs_two_trials_and_collects_artifacts(
    tmp_path: Path,
) -> None:
    script = (
        EXAMPLES_ROOT
        / "experiments"
        / "deterministic-sweep"
        / "run_sweep.py"
    )
    for _ in range(2):
        fields = _summary_fields(_run_example_script(script=script, tmp_path=tmp_path))

        assert fields["planned_trials"] == "2"
        assert fields["run_status"] == "succeeded"
        assert fields["succeeded_trials"] == "2"
        assert fields["collected_trials"] == "2"
        assert fields["artifact_count"] == "2"


def test_example_event_sink_observes_committed_events_and_isolates_failure(
    tmp_path: Path,
) -> None:
    script = EXAMPLES_ROOT / "extensions" / "event-sink" / "run_event_sink.py"
    fields = _summary_fields(_run_example_script(script=script, tmp_path=tmp_path))

    assert fields["run_status"] == "SUCCEEDED"
    assert {"run.started", "stage.completed", "run.completed"} <= set(
        fields["observed_events"].split(",")
    )
    assert fields["failure_count"] == "1"
    assert fields["failure_sink"] == "example.fail_completed"


def test_example_cleanup_and_gc_is_preview_first_and_candidate_only(
    tmp_path: Path,
) -> None:
    script = EXAMPLES_ROOT / "operations" / "cleanup-and-gc" / "run_cleanup_and_gc.py"
    for _ in range(2):
        fields = _summary_fields(
            _run_example_script(script=script, tmp_path=tmp_path / "cleanup-and-gc")
        )
        assert fields["clean_preview_selected"] == "1"
        assert fields["clean_deleted"] == "1"
        assert fields["gc_preview_selected"] == "1"
        assert fields["gc_deleted"] == "1"
        assert fields["candidate_paths_removed"] == "True"
        assert fields["preserved_paths"] == "True"
        assert _run_uri_path(fields["first_run_uri"]).is_dir()
        assert _run_uri_path(fields["second_run_uri"]).is_dir()


def test_example_nvidia_gpu_pool_uses_fake_discovery_and_planning(
    tmp_path: Path,
) -> None:
    output = _run_example_script(
        script=EXAMPLES_ROOT
        / "operations"
        / "nvidia-gpu-pool"
        / "run_nvidia_gpu_pool.py",
        tmp_path=tmp_path / "nvidia-gpu-pool",
    )
    fields = _summary_fields(output)

    assert fields == {
        "whole_capacity": "2",
        "shares_capacity": "4",
        "grouped_capacity": "1",
        "safe_summary_has_uuid": "False",
    }


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

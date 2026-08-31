"""Integration tests for ``loom run`` with real config composition."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.stores import (
    authority_config_to_cli_args,
    path_to_run_uri,
    run_uri_to_path,
)
from loom.pipeline.stores.service_authority import LocalAuthorityService


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@contextmanager
def _local_authority_args() -> Iterator[tuple[str, ...]]:
    with LocalAuthorityService.start() as service:
        yield authority_config_to_cli_args(service.config())


def _write_pipeline_config(
    path: Path,
    *,
    value: int = 1,
    counter_path: Path | None = None,
    failing: bool = False,
) -> None:
    if failing:
        build_target = "tests.support.pipeline_execution_stages.FailingStage"
        config_block = ""
    else:
        build_target = "tests.support.pipeline_execution_stages.JsonProducerStage"
        counter_line = (
            f"        counter_path: {counter_path}\n"
            if counter_path is not None
            else ""
        )
        config_block = f"      config:\n        value: {value}\n{counter_line}"

    path.write_text(
        "pipeline:\n"
        "  name: demo\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        f"        _target_: {build_target}\n"
        f"{config_block}"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.TextConsumerStage\n"
        "      depends_on: [build]\n"
        "      inputs:\n"
        "        data: build.data\n"
        "      outputs:\n"
        "        text:\n"
        "          artifact_type: text\n"
        "          codec_key: text.v1\n",
        encoding="utf-8",
    )


def test_run_default_uri_executes_under_store_default_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                ["run", str(config_path), *authority_args, "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

    payload = json.loads(stdout.getvalue())
    run_uri = payload["result"]["run_uri"]
    assert payload["schema_version"] == "loom.cli.run.v2"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "SUCCEEDED"
    assert payload["result"]["plan_summary"]["RUN"] == 2
    assert run_uri.startswith(path_to_run_uri(tmp_path / "runs").removesuffix("/"))
    assert run_uri_to_path(run_uri).is_dir()
    assert stderr.getvalue() == ""


def test_run_profile_root_persists_fresh_and_resume_state_in_selected_collection(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pipeline.yaml"
    root = tmp_path / "configured-runs"
    _write_pipeline_config(config_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "runtime_profiles:\n"
            "  storage:\n"
            "    run_store:\n"
            f"      root: {root}\n"
        )

    with _local_authority_args() as authority_args:
        fresh_stdout = io.StringIO()
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--profile",
                    "storage",
                    *authority_args,
                    "--format",
                    "json",
                ],
                stdout=fresh_stdout,
                stderr=io.StringIO(),
            )
            == 0
        )
        run_uri = json.loads(fresh_stdout.getvalue())["result"]["run_uri"]
        assert run_uri.startswith(path_to_run_uri(root).removesuffix("/"))

        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--profile",
                    "storage",
                    "--run-uri",
                    run_uri,
                    "--resume",
                    *authority_args,
                ],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            == 0
        )

    assert run_uri_to_path(run_uri).is_dir()


def test_run_offline_first_writes_non_authoritative_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "offline")
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                "--offline-first",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    evidence = payload["result"]["offline_evidence"]
    manifest_path = Path(evidence["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["result"]["status"] == "SUCCEEDED"
    assert evidence["state_source"]["authoritative"] is False
    assert evidence["state_source"]["label"] == "offline_evidence"
    assert evidence["manifest_status"] == "complete"
    assert manifest["kind"] == "loom.offline_evidence_manifest"
    assert manifest["state_source"]["authoritative"] is False
    assert [stage["stage_name"] for stage in manifest["stages"]] == [
        "build",
        "report",
    ]
    assert manifest["events"][-1]["event_type"] == "run.completed"
    assert stderr.getvalue() == ""


def test_run_explicit_uri_uses_exact_target_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "explicit"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--run-uri",
                    path_to_run_uri(run_path),
                    *authority_args,
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

    assert f"OK run {path_to_run_uri(run_path)}: SUCCEEDED" in stdout.getvalue()
    assert (run_path / "run.json").is_file()


def test_run_existing_uri_without_resume_fails_before_execution(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "existing"
    _write_pipeline_config(config_path)
    run_path.mkdir(parents=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--run-uri",
                    path_to_run_uri(run_path),
                    *authority_args,
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 4
        )

    assert stdout.getvalue() == ""
    assert "run URI already exists" in stderr.getvalue()
    assert not (run_path / "status.json").exists()


def test_run_resume_reuses_existing_state(tmp_path: Path) -> None:
    counter_path = tmp_path / "counter.txt"
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "resume")
    _write_pipeline_config(config_path, counter_path=counter_path)

    with _local_authority_args() as authority_args:
        assert (
            main(
                ["run", str(config_path), "--run-uri", run_uri, *authority_args],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
            == 0
        )
        assert counter_path.read_text(encoding="utf-8") == "1"

        stdout = io.StringIO()
        stderr = io.StringIO()
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--run-uri",
                    run_uri,
                    "--resume",
                    *authority_args,
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

    payload = json.loads(stdout.getvalue())
    actions = {
        stage["stage"]: stage["action"]
        for stage in payload["result"]["stage_summaries"]
    }
    assert actions == {"build": "REUSE", "report": "REUSE"}
    assert counter_path.read_text(encoding="utf-8") == "1"


def test_run_dry_run_delegates_to_plan_without_execution(tmp_path: Path) -> None:
    counter_path = tmp_path / "counter.txt"
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "dry"
    _write_pipeline_config(config_path, counter_path=counter_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                str(config_path),
                "--dry-run",
                "--run-uri",
                path_to_run_uri(run_path),
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.plan.v2"
    assert payload["result"]["run_uri"] == path_to_run_uri(run_path)
    assert not run_path.exists()
    assert not counter_path.exists()


def test_run_slurm_single_job_dry_run_persists_plan_prepared_run_and_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "slurm-single"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--executor",
                    "slurm-single-job",
                    "--dry-run",
                    "--run-uri",
                    path_to_run_uri(run_path),
                    *authority_args,
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

    payload = json.loads(stdout.getvalue())
    result = payload["result"]
    assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
    assert payload["ok"] is True
    assert result["mode"] == "slurm-single-job"
    assert result["dry_run"] is True
    assert result["job_count"] == 1
    assert result["script_count"] == 1
    assert result["manifest_path"].endswith("/manifest.json")
    assert Path(result["manifest_path"]).is_file()
    assert Path(result["plan_path"]).is_file()
    assert Path(result["script_paths"][0]["path"]).is_file()
    assert (run_path / "plan.json").is_file()
    assert (run_path / "prepared_run.json").is_file()
    assert "SECRET" not in (run_path / "prepared_run.json").read_text(encoding="utf-8")
    assert any(
        warning["code"] == "executor.slurm.sbatch" for warning in payload["warnings"]
    )
    assert stderr.getvalue() == ""


def test_run_slurm_afterok_dry_run_creates_stage_scripts(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "slurm-afterok"
    _write_pipeline_config(config_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "runtime:\n"
            "  adapter_options:\n"
            "    slurm:\n"
            "      schema_version: 1\n"
            "      partition: shared\n"
            "  stage_options:\n"
            "    report:\n"
            "      adapter_options:\n"
            "        slurm:\n"
            "          schema_version: 1\n"
            "          partition: report\n"
            "          launcher_argv: [uv, run, loom]\n"
        )
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--executor",
                    "slurm-afterok",
                    "--dry-run",
                    "--run-uri",
                    path_to_run_uri(run_path),
                    *authority_args,
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

    payload = json.loads(stdout.getvalue())
    result = payload["result"]
    assert result["mode"] == "slurm-afterok"
    assert result["job_count"] == 2
    assert result["script_count"] == 2
    assert result["dependency_count"] == 1
    script_paths = {
        item["logical_key"]: Path(item["path"]) for item in result["script_paths"]
    }
    assert set(script_paths) == {"stage:build", "stage:report"}
    assert all(path.is_file() for path in script_paths.values())
    build_script = script_paths["stage:build"].read_text(encoding="utf-8")
    report_script = script_paths["stage:report"].read_text(encoding="utf-8")
    assert "#SBATCH --partition=shared" in build_script
    assert "#SBATCH --partition=report" in report_script
    assert "uv run loom stage-job run" in report_script
    assert stderr.getvalue() == ""


def test_run_config_resolved_slurm_dry_run_uses_slurm_artifact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "configured-slurm"
    _write_pipeline_config(config_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write("runtime:\n  executor: slurm-single-job\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--dry-run",
                    "--run-uri",
                    path_to_run_uri(run_path),
                    *authority_args,
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

    payload = json.loads(stdout.getvalue())
    result = payload["result"]
    assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
    assert result["mode"] == "slurm-single-job"
    assert Path(result["manifest_path"]).is_file()
    assert (run_path / "prepared_run.json").is_file()
    assert stderr.getvalue() == ""


def test_run_profile_resolved_slurm_dry_run_uses_slurm_artifact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "profile-slurm"
    _write_pipeline_config(config_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "runtime_profiles:\n"
            "  cluster:\n"
            "    executor: slurm-afterok\n"
            "    slurm:\n"
            "      schema_version: 1\n"
            "      launcher_argv: [loom]\n"
        )
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--profile",
                    "cluster",
                    "--dry-run",
                    "--run-uri",
                    path_to_run_uri(run_path),
                    *authority_args,
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

    payload = json.loads(stdout.getvalue())
    result = payload["result"]
    assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
    assert result["mode"] == "slurm-afterok"
    assert result["dependency_count"] == 1
    assert Path(result["manifest_path"]).is_file()
    assert (run_path / "prepared_run.json").is_file()
    assert stderr.getvalue() == ""


def test_run_configured_slurm_without_dry_run_requires_live_authority(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write("runtime:\n  executor: slurm-afterok\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                ["run", str(config_path), *authority_args, "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
            == 7
        )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.run.slurm_live_authority_unsupported"
    admission = payload["error"]["details"]["authority_admission"]
    assert admission["supported"] is False
    assert any(error["required"] == "slurm_live_worker" for error in admission["errors"])
    assert stderr.getvalue() == ""


def test_run_failed_pipeline_returns_run_failed_exit_code(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "failed")
    _write_pipeline_config(config_path, failing=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with _local_authority_args() as authority_args:
        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--run-uri",
                    run_uri,
                    *authority_args,
                    "--format",
                    "json",
                ],
                stdout=stdout,
                stderr=stderr,
            )
            == 5
        )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["result"]["status"] == "FAILED"
    assert payload["result"]["failure_summary"]["stage"] == "build"
    assert (
        "stage failed intentionally" in payload["result"]["failure_summary"]["message"]
    )


def test_run_unsupported_executor_is_not_usage_error(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", str(config_path), "--executor", "slurm", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 7
    )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.run.unsupported_executor"
    assert stderr.getvalue() == ""

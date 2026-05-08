"""End-to-end SLURM dry-run generation through the public CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from loom.cli.main import main
from loom.pipeline.stores import path_to_run_uri

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

pytestmark = pytest.mark.e2e


def test_cli_slurm_dry_run_generates_artifacts_without_scheduler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "pipeline:\n"
        "  name: slurm-e2e\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.TextConsumerStage\n"
        "      inputs:\n"
        "        data: build.data\n"
        "      outputs:\n"
        "        text:\n"
        "          artifact_type: text\n"
        "          codec_key: text.v1\n",
        encoding="utf-8",
    )

    for mode in ("slurm-single-job", "slurm-afterok"):
        run_path = tmp_path / "runs" / mode
        stdout = io.StringIO()
        stderr = io.StringIO()

        assert (
            main(
                [
                    "run",
                    str(config_path),
                    "--executor",
                    mode,
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
        result = payload["result"]
        assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
        assert result["mode"] == mode
        assert Path(result["manifest_path"]).is_file()
        assert Path(result["plan_path"]).is_file()
        assert all(Path(item["path"]).is_file() for item in result["script_paths"])
        assert (run_path / "plan.json").is_file()
        assert (run_path / "prepared_run.json").is_file()
        assert any(warning["code"] == "executor.slurm.sbatch" for warning in payload["warnings"])
        assert stderr.getvalue() == ""


def test_cli_slurm_dry_run_artifacts_cover_diamond_and_secret_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import loom.diagnostics.preflight as preflight_module

    monkeypatch.setattr(preflight_module.shutil, "which", lambda _name: None)
    monkeypatch.setenv("LOOM_SLURM_E2E_SECRET_ROOT", "STAGE_SECRET_VALUE_SHOULD_NOT_PERSIST")
    config_path = tmp_path / "diamond.yaml"
    _write_diamond_config(config_path)

    single_run_path = tmp_path / "runs" / "single"
    single_payload = _run_slurm_dry_run(config_path, single_run_path, "slurm-single-job")
    single_result = single_payload["result"]
    single_manifest = _read_json(Path(single_result["manifest_path"]))
    single_plan = _read_json(Path(single_result["plan_path"]))
    single_script = Path(single_result["script_paths"][0]["path"]).read_text(encoding="utf-8")

    assert single_result["job_count"] == 1
    assert single_result["dependency_count"] == 0
    assert single_result["log_paths"] == [
        {
            "logical_key": "pipeline",
            "stdout_relative_path": f"slurm/submissions/{single_result['planning_id']}/logs/pipeline.stdout.log",
            "stderr_relative_path": f"slurm/submissions/{single_result['planning_id']}/logs/pipeline.stderr.log",
        }
    ]
    assert single_manifest["mode"] == "slurm-single-job"
    assert single_manifest["dry_run"] is True
    assert single_manifest["jobs"][0]["command"]["command_args"][:2] == [
        "prepared-run",
        "continue",
    ]
    assert "scheduler_job_id" not in single_manifest["jobs"][0]
    assert single_plan["kind"] == "loom.slurm_dry_run_plan"
    assert "oc.env:LOOM_SLURM_E2E_SECRET_ROOT" in (
        single_run_path / "plan.json"
    ).read_text(encoding="utf-8")
    assert "loom prepared-run continue" in single_script
    assert "loom stage-job run" not in single_script
    assert "loom stage run" not in single_script
    assert "#SBATCH --partition=shared" in single_script
    _assert_dry_run_secret_boundary(single_run_path)

    afterok_run_path = tmp_path / "runs" / "afterok"
    afterok_payload = _run_slurm_dry_run(config_path, afterok_run_path, "slurm-afterok")
    afterok_result = afterok_payload["result"]
    afterok_manifest = _read_json(Path(afterok_result["manifest_path"]))

    assert afterok_result["job_count"] == 4
    assert afterok_result["script_count"] == 4
    assert afterok_result["dependency_count"] == 3
    assert {
        dependency["job_key"]: dependency["upstream_job_keys"]
        for dependency in afterok_manifest["dependencies"]
    } == {
        "stage:features": ["stage:extract"],
        "stage:train": ["stage:extract"],
        "stage:report": ["stage:features", "stage:train"],
    }
    commands = {
        command["logical_key"]: command["argv"]
        for command in afterok_result["generated_commands"]
    }
    assert commands["stage:extract"][:2] == ["loom", "stage-job"]
    assert commands["stage:report"][:4] == ["uv", "run", "loom", "stage-job"]
    assert commands["stage:report"][4:6] == ["run", "--run-uri"]
    scripts = {
        item["logical_key"]: Path(item["path"]).read_text(encoding="utf-8")
        for item in afterok_result["script_paths"]
    }
    assert "#SBATCH --dependency=afterok:stage:features:stage:train" in scripts["stage:report"]
    assert "#SBATCH --dependency=afterok:stage:extract" in scripts["stage:features"]
    assert "#SBATCH --dependency=afterok:stage:extract" in scripts["stage:train"]
    assert "#SBATCH --partition=train" in scripts["stage:train"]
    assert "#SBATCH --partition=report" in scripts["stage:report"]
    assert "#SBATCH --cpus-per-task=2" in scripts["stage:train"]
    assert all("loom stage-job run" in script for script in scripts.values())
    assert all("loom stage run" not in script for script in scripts.values())
    assert all("prepared-run continue" not in script for script in scripts.values())
    assert all("scheduler_job_id" not in job for job in afterok_manifest["jobs"])
    _assert_dry_run_secret_boundary(afterok_run_path)

    repeated_payload = _run_slurm_dry_run(
        config_path,
        afterok_run_path,
        "slurm-afterok",
        resume=True,
    )
    repeated_result = repeated_payload["result"]

    assert repeated_result["planning_id"] != afterok_result["planning_id"]
    assert Path(afterok_result["manifest_path"]).is_file()
    assert Path(repeated_result["manifest_path"]).is_file()
    assert Path(afterok_result["manifest_path"]) != Path(repeated_result["manifest_path"])
    _assert_dry_run_secret_boundary(afterok_run_path)


def _write_diamond_config(path: Path) -> None:
    path.write_text(
        "metadata:\n"
        "  secret_root: ${oc.env:LOOM_SLURM_E2E_SECRET_ROOT}\n"
        "pipeline:\n"
        "  name: slurm-diamond-e2e\n"
        "  stages:\n"
        "    - name: extract\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      config:\n"
        "        value: ${oc.env:LOOM_SLURM_E2E_SECRET_ROOT}\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: features\n"
        "      depends_on: [extract]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: train\n"
        "      depends_on: [extract]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      depends_on: [features, train]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "runtime:\n"
        "  environment:\n"
        "    set_variables:\n"
        "      LOOM_E2E_RUNTIME_TOKEN: RUNTIME_ENV_VALUE_SHOULD_NOT_PERSIST\n"
        "    unset_variables: [LOOM_E2E_OLD_TOKEN]\n"
        "  adapter_options:\n"
        "    slurm:\n"
        "      schema_version: 1\n"
        "      partition: shared\n"
        "      launcher_argv: [loom]\n"
        "  stage_options:\n"
        "    train:\n"
        "      resources:\n"
        "        entries:\n"
        "          cpu:\n"
        "            kind: cpu\n"
        "            amount: 2\n"
        "      adapter_options:\n"
        "        slurm:\n"
        "          schema_version: 1\n"
        "          partition: train\n"
        "    report:\n"
        "      adapter_options:\n"
        "        slurm:\n"
        "          schema_version: 1\n"
        "          partition: report\n"
        "          launcher_argv: [uv, run, loom]\n",
        encoding="utf-8",
    )


def _run_slurm_dry_run(
    config_path: Path,
    run_path: Path,
    mode: str,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    args = [
        "run",
        str(config_path),
        "--executor",
        mode,
        "--dry-run",
        "--run-uri",
        path_to_run_uri(run_path),
        "--format",
        "json",
    ]
    if resume:
        args.append("--resume")

    assert main(args, stdout=stdout, stderr=stderr) == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.slurm_dry_run.v1"
    assert payload["ok"] is True
    assert payload["result"]["mode"] == mode
    assert any(warning["code"] == "executor.slurm.sbatch" for warning in payload["warnings"])
    return payload


def _assert_dry_run_secret_boundary(run_path: Path) -> None:
    forbidden = (
        "STAGE_SECRET_VALUE_SHOULD_NOT_PERSIST",
        "RUNTIME_ENV_VALUE_SHOULD_NOT_PERSIST",
        "LOOM_E2E_RUNTIME_TOKEN",
        "LOOM_E2E_OLD_TOKEN",
    )
    files = sorted(path for path in run_path.rglob("*") if path.is_file())
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        for value in forbidden:
            assert value not in text, f"{value!r} leaked into {path}"
    assert not list((run_path / "config").glob("*"))
    assert not [path for path in (run_path / "stages").rglob("*") if path.is_file()]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

"""Integration tests for ``loom run`` with real config composition."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.stores import path_to_run_uri, run_uri_to_path


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


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
        counter_line = f"        counter_path: {counter_path}\n" if counter_path is not None else ""
        config_block = (
            "      config:\n"
            f"        value: {value}\n"
            f"{counter_line}"
        )

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

    assert main(["run", str(config_path), "--format", "json"], stdout=stdout, stderr=stderr) == 0

    payload = json.loads(stdout.getvalue())
    run_uri = payload["result"]["run_uri"]
    assert payload["schema_version"] == "loom.cli.run.v2"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "SUCCEEDED"
    assert payload["result"]["plan_summary"]["RUN"] == 2
    assert run_uri.startswith(path_to_run_uri(tmp_path / "runs").removesuffix("/"))
    assert run_uri_to_path(run_uri).is_dir()
    assert stderr.getvalue() == ""


def test_run_explicit_uri_uses_exact_target_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "explicit"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", str(config_path), "--run-uri", path_to_run_uri(run_path)],
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

    assert (
        main(
            ["run", str(config_path), "--run-uri", path_to_run_uri(run_path)],
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

    assert main(["run", str(config_path), "--run-uri", run_uri], stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert counter_path.read_text(encoding="utf-8") == "1"

    stdout = io.StringIO()
    stderr = io.StringIO()
    assert (
        main(
            ["run", str(config_path), "--run-uri", run_uri, "--resume", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    actions = {stage["stage"]: stage["action"] for stage in payload["result"]["stage_summaries"]}
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


def test_run_failed_pipeline_returns_run_failed_exit_code(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "failed")
    _write_pipeline_config(config_path, failing=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", str(config_path), "--run-uri", run_uri, "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 5
    )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["result"]["status"] == "FAILED"
    assert payload["result"]["failure_summary"]["stage"] == "build"
    assert "stage failed intentionally" in payload["result"]["failure_summary"]["message"]


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

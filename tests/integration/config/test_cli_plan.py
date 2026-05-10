"""Integration tests for ``loom plan`` with real config composition."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.stores import path_to_run_uri
from loom.config import compose_config


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _write_pipeline_config(path: Path, *, value: int = 1) -> None:
    path.write_text(
        "pipeline:\n"
        "  name: demo\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages:JsonProducerStage\n"
        "      config:\n"
        f"        value: {value}\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages:TextConsumerStage\n"
        "      depends_on: [build]\n"
        "      inputs:\n"
        "        data: build.data\n"
        "      outputs:\n"
        "        text:\n"
        "          artifact_type: text\n"
        "          codec_key: text.v1\n",
        encoding="utf-8",
    )


def test_plan_fresh_without_run_uri_does_not_create_default_run_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["plan", str(config_path)], stdout=stdout, stderr=stderr) == 0

    assert "OK plan" in stdout.getvalue()
    assert "build: RUN [RESUME_DISABLED]" in stdout.getvalue()
    assert "report: RUN [UPSTREAM_WILL_RUN]" in stdout.getvalue()
    assert stderr.getvalue() == ""
    assert not (tmp_path / "runs").exists()


def test_plan_explicit_new_run_uri_is_read_only(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "planned"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["plan", str(config_path), "--run-uri", path_to_run_uri(run_path), "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.plan.v2"
    assert payload["result"]["run_uri"] == path_to_run_uri(run_path)
    assert payload["result"]["summary"]["RUN"] == 2
    assert not run_path.exists()


def test_plan_existing_run_uri_without_resume_fails(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_path = tmp_path / "runs" / "planned"
    _write_pipeline_config(config_path)
    run_path.mkdir(parents=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["plan", str(config_path), "--run-uri", path_to_run_uri(run_path)],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    assert stdout.getvalue() == ""
    assert "run URI already exists" in stderr.getvalue()


def test_plan_resume_reports_reuse_for_existing_valid_run(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_store = create_authority_backed_serial_run_store(tmp_path / "runs")
    run_uri = path_to_run_uri(tmp_path / "runs" / "run-1")
    _write_pipeline_config(config_path)
    composed = compose_config(config_path)
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=composed, run_uri=run_uri)
    )
    assert result.status.value == "SUCCEEDED"

    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["plan", str(config_path), "--run-uri", run_uri, "--resume", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    actions = {stage["stage"]: stage["action"] for stage in payload["result"]["stage_actions"]}
    assert actions == {"build": "REUSE", "report": "REUSE"}
    assert payload["result"]["summary"]["REUSE"] == 2


def test_plan_selectors_and_explain_are_reflected_in_output(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "plan",
                str(config_path),
                "--only-stage",
                "build",
                "--explain",
                "build",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["selectors"]["only_stages"] == ["build"]
    assert payload["result"]["explanation"]["stage"] == "build"
    assert payload["result"]["explanation"]["reason_codes"] == [
        "ONLY_STAGE_SELECTED",
        "RESUME_DISABLED",
    ]

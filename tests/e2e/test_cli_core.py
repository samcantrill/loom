"""End-to-end coverage for the v2 CLI core through ``main(argv)``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.cli.main import main
from loom.pipeline.stores import path_to_run_uri, run_uri_to_path
from tests.support.config_samples import construction_event_log, reset_instantiate_probe_state

pytestmark = pytest.mark.e2e


def _write_pipeline_config(
    path: Path,
    *,
    value: int = 1,
    counter_path: Path | None = None,
    failing: bool = False,
    include_generic_target: bool = False,
) -> None:
    service_block = ""
    if include_generic_target:
        service_block = (
            "service:\n"
            "  _target_: tests.support.config_samples:ConstructionProbeTarget\n"
            "  marker:\n"
            "    _target_: tests.support.config_samples:log_and_return\n"
            "    tag: service-child\n"
            "    value: ok\n"
        )

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
        service_block
        + "pipeline:\n"
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


def test_cli_validate_plan_and_json_outputs(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "planned")
    _write_pipeline_config(config_path)

    preflight_stdout = io.StringIO()
    preflight_stderr = io.StringIO()
    assert (
        main(
            ["preflight", str(config_path), "--format", "json"],
            stdout=preflight_stdout,
            stderr=preflight_stderr,
        )
        == 0
    )
    preflight_payload = json.loads(preflight_stdout.getvalue())
    assert preflight_payload["schema_version"] == "loom.cli.preflight.v3"
    assert preflight_payload["result"]["status"] == "PASS"
    assert preflight_stderr.getvalue() == ""

    validate_stdout = io.StringIO()
    validate_stderr = io.StringIO()
    assert main(["validate", str(config_path)], stdout=validate_stdout, stderr=validate_stderr) == 0
    assert validate_stdout.getvalue() == f"OK validate {config_path}: 2 stages\n"
    assert validate_stderr.getvalue() == ""

    plan_stdout = io.StringIO()
    plan_stderr = io.StringIO()
    assert (
        main(
            ["plan", str(config_path), "--run-uri", run_uri, "--explain", "build", "--format", "json"],
            stdout=plan_stdout,
            stderr=plan_stderr,
        )
        == 0
    )
    payload = json.loads(plan_stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.plan.v2"
    assert payload["result"]["run_uri"] == run_uri
    assert payload["result"]["explanation"]["stage"] == "build"
    assert not run_uri_to_path(run_uri).exists()


def test_cli_preflight_failed_config_returns_diagnostics_result(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["preflight", str(tmp_path / "missing.yaml"), "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.preflight.v3"
    assert payload["ok"] is False
    assert payload["result"]["status"] == "FAIL"
    assert stderr.getvalue() == ""


def test_cli_validate_check_targets_constructs_trusted_targets(tmp_path: Path) -> None:
    reset_instantiate_probe_state()
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path, include_generic_target=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["validate", str(config_path), "--check-targets", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["warnings"][0]["code"] == "validate.target_constructors_may_run"
    assert payload["result"]["target_count"] == 4
    assert stderr.getvalue() == ""
    assert construction_event_log == ["service-child", "parent"]


def test_cli_run_default_and_explicit_run_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)

    default_stdout = io.StringIO()
    default_stderr = io.StringIO()
    assert main(["run", str(config_path), "--format", "json"], stdout=default_stdout, stderr=default_stderr) == 0
    default_payload = json.loads(default_stdout.getvalue())
    default_run_uri = default_payload["result"]["run_uri"]
    assert default_payload["schema_version"] == "loom.cli.run.v2"
    assert default_payload["result"]["status"] == "SUCCEEDED"
    assert default_run_uri.startswith(path_to_run_uri(tmp_path / "runs").removesuffix("/"))
    assert run_uri_to_path(default_run_uri).is_dir()

    explicit_run_uri = path_to_run_uri(tmp_path / "runs" / "explicit")
    explicit_stdout = io.StringIO()
    explicit_stderr = io.StringIO()
    assert (
        main(
            ["run", str(config_path), "--run-uri", explicit_run_uri],
            stdout=explicit_stdout,
            stderr=explicit_stderr,
        )
        == 0
    )
    assert f"OK run {explicit_run_uri}: SUCCEEDED" in explicit_stdout.getvalue()
    assert run_uri_to_path(explicit_run_uri).is_dir()


def test_cli_run_dry_run_does_not_execute_or_allocate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    counter_path = tmp_path / "counter.txt"
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path, counter_path=counter_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["run", str(config_path), "--dry-run", "--format", "json"], stdout=stdout, stderr=stderr) == 0

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.plan.v2"
    assert payload["result"]["run_uri"] is None
    assert not counter_path.exists()
    assert not (tmp_path / "runs").exists()


def test_cli_run_resume_reuses_existing_state(tmp_path: Path) -> None:
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


def test_cli_failed_run_reports_failure_summary(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "failed")
    _write_pipeline_config(config_path, failing=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["run", str(config_path), "--run-uri", run_uri, "--format", "json"], stdout=stdout, stderr=stderr) == 5

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["result"]["status"] == "FAILED"
    assert payload["result"]["failure_summary"]["stage"] == "build"
    assert "stage failed intentionally" in payload["result"]["failure_summary"]["message"]


def test_cli_rejects_deferred_executor_and_plain_run_uri(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)

    executor_stdout = io.StringIO()
    executor_stderr = io.StringIO()
    assert (
        main(
            ["run", str(config_path), "--executor", "slurm", "--format", "json"],
            stdout=executor_stdout,
            stderr=executor_stderr,
        )
        == 7
    )
    assert json.loads(executor_stdout.getvalue())["error"]["code"] == "cli.run.unsupported_executor"

    uri_stdout = io.StringIO()
    uri_stderr = io.StringIO()
    assert (
        main(
            ["plan", str(config_path), "--run-uri", str(tmp_path / "runs" / "plain"), "--format", "json"],
            stdout=uri_stdout,
            stderr=uri_stderr,
        )
        == 4
    )
    assert json.loads(uri_stdout.getvalue())["error"]["type"] == "InvalidRunURIError"

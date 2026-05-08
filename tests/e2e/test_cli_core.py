"""End-to-end coverage for the v2 CLI core through ``main(argv)``."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import cast

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.cli.main import main
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import LocalRunStore, path_to_run_uri, run_uri_to_path
from loom.pipeline.submitted import SubmittedOperationRecord, SubmittedOperationState
from tests.support.config_samples import (
    construction_event_log,
    reset_instantiate_probe_state,
)

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
        counter_line = (
            f"        counter_path: {counter_path}\n"
            if counter_path is not None
            else ""
        )
        config_block = f"      config:\n        value: {value}\n{counter_line}"

    path.write_text(
        service_block + "pipeline:\n"
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
    assert (
        main(
            ["validate", str(config_path)],
            stdout=validate_stdout,
            stderr=validate_stderr,
        )
        == 0
    )
    assert validate_stdout.getvalue() == f"OK validate {config_path}: 2 stages\n"
    assert validate_stderr.getvalue() == ""

    plan_stdout = io.StringIO()
    plan_stderr = io.StringIO()
    assert (
        main(
            [
                "plan",
                str(config_path),
                "--run-uri",
                run_uri,
                "--explain",
                "build",
                "--format",
                "json",
            ],
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


def test_cli_continuation_commands_reject_recursive_executors_as_json() -> None:
    for argv, executor in (
        (
            [
                "prepared-run",
                "continue",
                "--run-uri",
                "file:///tmp/missing-run",
                "--executor",
                "slurm-single-job",
                "--format",
                "json",
            ],
            "slurm-single-job",
        ),
        (
            [
                "stage-job",
                "run",
                "--run-uri",
                "file:///tmp/missing-run",
                "--stage",
                "build",
                "--executor",
                "slurm-afterok",
                "--format",
                "json",
            ],
            "slurm-afterok",
        ),
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()

        assert main(argv, stdout=stdout, stderr=stderr) == 7
        payload = json.loads(stdout.getvalue())
        assert payload["ok"] is False
        assert payload["error"]["code"] == "execution.continuation.unsupported_executor"
        assert payload["error"]["context"]["executor"] == executor
        assert stderr.getvalue() == ""


def test_cli_preflight_strict_resource_warning_exits_pipeline_failure(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "runtime:\n"
            "  stage_options:\n"
            "    build:\n"
            "      resources:\n"
            "        entries:\n"
            "          memory:\n"
            "            kind: memory\n"
            "            amount: 1024\n"
            "            unit: MiB\n"
        )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "preflight",
                str(config_path),
                "--check",
                "resources",
                "--strict",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["result"]["status"] == "WARN"
    assert payload["result"]["checks"][0]["details"]["diagnostics"][0]["code"] == (
        "resource.ignored"
    )
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


def test_cli_run_default_and_explicit_run_uri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "pipeline.yaml"
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
    assert json.loads(preflight_stdout.getvalue())["result"]["status"] == "PASS"
    assert preflight_stderr.getvalue() == ""

    default_stdout = io.StringIO()
    default_stderr = io.StringIO()
    assert (
        main(
            ["run", str(config_path), "--format", "json"],
            stdout=default_stdout,
            stderr=default_stderr,
        )
        == 0
    )
    default_payload = json.loads(default_stdout.getvalue())
    default_run_uri = default_payload["result"]["run_uri"]
    assert default_payload["schema_version"] == "loom.cli.run.v2"
    assert default_payload["result"]["status"] == "SUCCEEDED"
    assert default_run_uri.startswith(
        path_to_run_uri(tmp_path / "runs").removesuffix("/")
    )
    assert run_uri_to_path(default_run_uri).is_dir()
    LocalRunStore().write_stage_log(
        default_run_uri, "build", "stdout", "hello\nworld\n"
    )

    status_stdout = io.StringIO()
    status_stderr = io.StringIO()
    assert (
        main(
            ["status", default_run_uri, "--format", "json"],
            stdout=status_stdout,
            stderr=status_stderr,
        )
        == 0
    )
    status_payload = json.loads(status_stdout.getvalue())
    assert status_payload["schema_version"] == "loom.cli.status.v3"
    assert status_payload["result"]["stages"][0]["stage_name"] == "build"

    logs_stdout = io.StringIO()
    logs_stderr = io.StringIO()
    assert (
        main(
            [
                "logs",
                default_run_uri,
                "build",
                "--stream",
                "stdout",
                "--tail",
                "1",
                "--format",
                "json",
            ],
            stdout=logs_stdout,
            stderr=logs_stderr,
        )
        == 0
    )
    logs_payload = json.loads(logs_stdout.getvalue())
    assert logs_payload["schema_version"] == "loom.cli.logs.v3"
    assert logs_payload["result"]["streams"][0]["content"] == "world\n"

    artifacts_stdout = io.StringIO()
    artifacts_stderr = io.StringIO()
    assert (
        main(
            ["artifacts", "list", default_run_uri, "--format", "json"],
            stdout=artifacts_stdout,
            stderr=artifacts_stderr,
        )
        == 0
    )
    artifacts_payload = json.loads(artifacts_stdout.getvalue())
    assert artifacts_payload["schema_version"] == "loom.cli.artifacts.list.v3"
    assert artifacts_payload["result"]["artifact_count"] == 2
    assert [
        artifact["artifact_id"] for artifact in artifacts_payload["result"]["artifacts"]
    ] == [
        "build/data",
        "report/text",
    ]
    assert artifacts_stderr.getvalue() == ""

    artifact_stdout = io.StringIO()
    artifact_stderr = io.StringIO()
    assert (
        main(
            ["artifacts", "show", default_run_uri, "build/data", "--format", "json"],
            stdout=artifact_stdout,
            stderr=artifact_stderr,
        )
        == 0
    )
    artifact_payload = json.loads(artifact_stdout.getvalue())
    assert artifact_payload["schema_version"] == "loom.cli.artifacts.show.v3"
    assert artifact_payload["result"]["artifact"]["key"] == "build.data"
    assert artifact_payload["result"]["stage_provenance"] is not None
    assert artifact_stderr.getvalue() == ""

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


def test_cli_status_submitted_state_smoke(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "runs" / "submitted")
    store = LocalRunStore(tmp_path / "runs")
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUBMITTED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUBMITTED,
            attempt=1,
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_submitted_operation(
        run_uri,
        SubmittedOperationRecord(
            run_uri=run_uri,
            submission_id="sub-1",
            backend="test-backend",
            mode="batch",
            created_at="2020-01-01T00:00:01Z",
            updated_at="2020-01-01T00:00:01Z",
            state=SubmittedOperationState.SUBMITTED,
            manifest_relative_path="submitted/sub-1/manifest.json",
            summary_counts={"submitted": 1},
        ),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(["status", run_uri, "--format", "json"], stdout=stdout, stderr=stderr) == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["status"] == "SUBMITTED"
    assert payload["result"]["stages"][0]["status"] == "SUBMITTED"
    assert payload["result"]["submitted_operations"][0]["submission_id"] == "sub-1"
    assert stderr.getvalue() == ""


def test_cli_run_subprocess_success_smoke(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "subprocess-success")
    _write_pipeline_config(config_path, value=55)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                "--executor",
                "subprocess",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is True
    assert payload["result"]["status"] == "SUCCEEDED"
    assert payload["result"]["artifact_count"] == 2
    assert stderr.getvalue() == ""
    store = LocalRunStore()
    assert store.read_stage_worker_result(run_uri, "build", attempt=1) is not None
    provenance = store.read_stage_provenance(run_uri, "build")
    assert provenance is not None
    executor_metadata = cast(dict[str, object], provenance["executor_metadata"])
    assert executor_metadata["executor"] == "subprocess"


def test_cli_run_subprocess_failure_smoke(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "subprocess-failed")
    _write_pipeline_config(config_path, failing=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "run",
                str(config_path),
                "--run-uri",
                run_uri,
                "--executor",
                "subprocess",
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
    failure_summary = payload["result"]["failure_summary"]
    assert failure_summary["stage"] == "build"
    assert failure_summary["attempt"] == 1
    assert failure_summary["executor"] == "subprocess"
    assert failure_summary["exit_code"] == 1
    assert failure_summary["signal"] is None
    assert "stage failed intentionally" in failure_summary["message"]
    assert failure_summary["failure_path"].endswith("/stages/build/failure.json")
    assert failure_summary["stdout_path"].endswith("/stages/build/logs/stdout.log")
    assert failure_summary["stderr_path"].endswith("/stages/build/logs/stderr.log")
    assert failure_summary["traceback_path"].endswith(
        "/stages/build/logs/traceback.txt"
    )
    assert stderr.getvalue() == ""
    worker_result = LocalRunStore().read_stage_worker_result(
        run_uri,
        "build",
        attempt=1,
    )
    assert worker_result is not None
    assert worker_result["status"] == "FAILED"

    text_run_uri = path_to_run_uri(tmp_path / "runs" / "subprocess-failed-text")
    text_stdout = io.StringIO()
    text_stderr = io.StringIO()
    assert (
        main(
            [
                "run",
                str(config_path),
                "--run-uri",
                text_run_uri,
                "--executor",
                "subprocess",
            ],
            stdout=text_stdout,
            stderr=text_stderr,
        )
        == 5
    )
    rendered = text_stdout.getvalue()
    assert f"FAILED run {text_run_uri}: FAILED" in rendered
    assert "failure build: stage failed intentionally" in rendered
    assert "  attempt: 1\n" in rendered
    assert "  executor: subprocess\n" in rendered
    assert "  exit_code: 1\n" in rendered
    assert "  failure_record:" in rendered
    assert "  stdout:" in rendered
    assert "  stderr:" in rendered
    assert "  traceback:" in rendered
    assert text_stderr.getvalue() == ""


def test_cli_run_dry_run_does_not_execute_or_allocate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    counter_path = tmp_path / "counter.txt"
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path, counter_path=counter_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", str(config_path), "--dry-run", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

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

    assert (
        main(
            ["run", str(config_path), "--run-uri", run_uri],
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


def test_cli_failed_run_reports_failure_summary(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "failed")
    _write_pipeline_config(config_path, failing=True)

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
    assert json.loads(preflight_stdout.getvalue())["result"]["status"] == "PASS"
    assert preflight_stderr.getvalue() == ""

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
    assert (
        "stage failed intentionally" in payload["result"]["failure_summary"]["message"]
    )

    LocalRunStore().write_stage_log(run_uri, "build", "stderr", "failed\n")

    status_stdout = io.StringIO()
    status_stderr = io.StringIO()
    assert (
        main(
            ["status", run_uri, "--format", "json"],
            stdout=status_stdout,
            stderr=status_stderr,
        )
        == 0
    )
    status_payload = json.loads(status_stdout.getvalue())
    assert status_payload["result"]["status"] == "FAILED"
    assert status_payload["result"]["stages"][0]["stage_name"] == "build"
    assert status_stderr.getvalue() == ""

    logs_stdout = io.StringIO()
    logs_stderr = io.StringIO()
    assert (
        main(
            ["logs", run_uri, "build", "--stream", "stderr", "--format", "json"],
            stdout=logs_stdout,
            stderr=logs_stderr,
        )
        == 0
    )
    assert (
        json.loads(logs_stdout.getvalue())["result"]["streams"][0]["content"]
        == "failed\n"
    )
    assert logs_stderr.getvalue() == ""

    artifacts_stdout = io.StringIO()
    artifacts_stderr = io.StringIO()
    assert (
        main(
            ["artifacts", "list", run_uri, "--format", "json"],
            stdout=artifacts_stdout,
            stderr=artifacts_stderr,
        )
        == 0
    )
    artifacts_payload = json.loads(artifacts_stdout.getvalue())
    assert artifacts_payload["schema_version"] == "loom.cli.artifacts.list.v3"
    assert artifacts_payload["result"]["artifact_count"] == 0
    assert artifacts_stderr.getvalue() == ""


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
    assert (
        json.loads(executor_stdout.getvalue())["error"]["code"]
        == "cli.run.unsupported_executor"
    )

    uri_stdout = io.StringIO()
    uri_stderr = io.StringIO()
    assert (
        main(
            [
                "plan",
                str(config_path),
                "--run-uri",
                str(tmp_path / "runs" / "plain"),
                "--format",
                "json",
            ],
            stdout=uri_stdout,
            stderr=uri_stderr,
        )
        == 4
    )
    assert json.loads(uri_stdout.getvalue())["error"]["type"] == "InvalidRunURIError"

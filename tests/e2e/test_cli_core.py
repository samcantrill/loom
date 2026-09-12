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
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import path_to_run_uri, run_uri_to_path
from loom.pipeline.stores import authority_config_to_cli_args
from loom.pipeline.stores.service_authority import LocalAuthorityService
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
    include_stage_owned_targets: bool = False,
    generic_target_path: str = "tests.support.config_samples:ConstructionProbeTarget",
    build_target_override: str | None = None,
) -> None:
    service_block = ""
    if include_generic_target:
        service_block = (
            "service:\n"
            f"  _target_: {generic_target_path}\n"
            "  marker:\n"
            "    _target_: tests.support.config_samples:log_and_return\n"
            "    tag: service-child\n"
            "    value: ok\n"
        )

    pipeline_metadata = ""
    factory_init = ""
    if include_stage_owned_targets:
        pipeline_metadata = (
            "  metadata:\n"
            "    marker:\n"
            "      _target_: tests.support.config_samples:log_and_return\n"
            "      tag: pipeline-metadata\n"
            "      value: inert\n"
        )
        factory_init = (
            "        init:\n"
            "          constructor_value:\n"
            "            _target_: tests.support.config_samples:log_and_return\n"
            "            tag: factory-init\n"
            "            value: inert\n"
        )

    if failing:
        build_target = "tests.support.pipeline_execution_stages.FailingStage"
        config_block = ""
    else:
        build_target = (
            "tests.support.pipeline_execution_stages.ConfiguredProducerStage"
            if include_stage_owned_targets
            else "tests.support.pipeline_execution_stages.JsonProducerStage"
        )
        counter_line = (
            f"        counter_path: {counter_path}\n"
            if counter_path is not None
            else ""
        )
        stage_marker = (
            "        marker:\n"
            "          _target_: tests.support.config_samples:log_and_return\n"
            "          tag: stage-config\n"
            "          value: inert\n"
            if include_stage_owned_targets
            else ""
        )
        config_block = (
            f"      config:\n        value: {value}\n{counter_line}{stage_marker}"
        )

    if build_target_override is not None:
        build_target = build_target_override

    path.write_text(
        service_block + "pipeline:\n"
        "  name: demo\n"
        f"{pipeline_metadata}"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        f"        _target_: {build_target}\n"
        f"{factory_init}"
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
        "resource.not_requested"
    )
    assert stderr.getvalue() == ""


def test_cli_validate_keeps_generic_project_targets_as_data(tmp_path: Path) -> None:
    reset_instantiate_probe_state()
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path, include_generic_target=True)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["validate", str(config_path), "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.validate.v3"
    assert payload["warnings"] == []
    assert set(payload["result"]) == {"config_path", "pipeline_name", "stage_count"}
    assert stderr.getvalue() == ""
    assert construction_event_log == []


def test_cli_validate_keeps_nested_project_targets_as_data(
    tmp_path: Path,
) -> None:
    reset_instantiate_probe_state()
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(
        config_path,
        include_generic_target=True,
        include_stage_owned_targets=True,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["validate", str(config_path), "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.validate.v3"
    assert payload["warnings"] == []
    assert construction_event_log == []
    assert stderr.getvalue() == ""


def test_cli_validate_defers_invalid_stage_factory_to_execution(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(
        config_path,
        build_target_override="tests.support.pipeline_execution_stages.NotAStage",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", str(config_path)], stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == f"OK validate {config_path}: 2 stages\n"
    assert stderr.getvalue() == ""

    run_uri = path_to_run_uri(tmp_path / "runs" / "invalid-stage")
    from tests.support.executed_run_fixture import execute_fixture
    with LocalAuthorityService.start() as service:
        result, _ = execute_fixture(config_path, run_uri, authority_config=service.config())
    assert result.status.value == "FAILED"
    assert result.failure is not None
    assert "did not construct a Stage-compatible object" in result.failure.message


def test_cli_validate_does_not_reject_invalid_generic_target(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(
        config_path,
        include_generic_target=True,
        generic_target_path="tests.support.config_samples:NON_CALLABLE_TARGET",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", str(config_path)], stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == f"OK validate {config_path}: 2 stages\n"
    assert stderr.getvalue() == ""




def test_cli_status_submitted_state_smoke(tmp_path: Path) -> None:
    run_uri = path_to_run_uri(tmp_path / "runs" / "submitted")
    with LocalAuthorityService.start() as service:
        authority_args = authority_config_to_cli_args(service.config())
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=service.config(),
        )
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
            main(
                ["status", run_uri, *authority_args, "--format", "json"],
                stdout=stdout,
                stderr=stderr,
            )
            == 0
        )

        payload = json.loads(stdout.getvalue())
        assert payload["result"]["status"] == "SUBMITTED"
        assert payload["result"]["stages"][0]["status"] == "SUBMITTED"
        assert payload["result"]["submitted_operations"][0]["submission_id"] == "sub-1"
        assert stderr.getvalue() == ""

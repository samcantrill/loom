"""Integration tests for ``loom preflight`` with real config composition."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("yaml")
pytest.importorskip("omegaconf")
pytest.importorskip("pydantic")

from loom.cli.main import main
from loom.pipeline.stores import path_to_run_uri


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _write_pipeline_config(path: Path) -> None:
    path.write_text(
        "pipeline:\n"
        "  name: demo\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      config:\n"
        "        value: 1\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )


def test_preflight_valid_config_json_includes_diagnostics_payload(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["preflight", str(config_path), "--format", "json"], stdout=stdout, stderr=stderr) == 0

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.preflight.v3"
    assert payload["ok"] is True
    assert payload["result"]["status"] == "PASS"
    assert "config" in payload["result"]["groups"]
    assert any(check["check_id"] == "config.load" for check in payload["result"]["checks"])
    assert stderr.getvalue() == ""


def test_preflight_selected_run_group_without_uri_skips(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["preflight", str(config_path), "--check", "run", "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["status"] == "SKIP"
    assert payload["result"]["groups"] == ["run"]
    assert payload["result"]["checks"][0]["status"] == "SKIP"
    assert stderr.getvalue() == ""


def test_preflight_explicit_run_uri_enables_path_checks(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    run_uri = path_to_run_uri(tmp_path / "runs" / "preflighted")
    _write_pipeline_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "preflight",
                str(config_path),
                "--run-uri",
                run_uri,
                "--check",
                "run",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["status"] == "PASS"
    assert payload["result"]["checks"][0]["check_id"] == "run_uri.resolve"
    assert payload["result"]["checks"][0]["details"]["run_uri"] == run_uri
    assert not (tmp_path / "runs" / "preflighted").exists()
    assert stderr.getvalue() == ""


def test_preflight_resource_warnings_and_strict_exit(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    _write_pipeline_config(config_path)
    with config_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "runtime:\n"
            "  stage_options:\n"
            "    build:\n"
            "      resources:\n"
            "        entries:\n"
            "          cpu:\n"
            "            kind: cpu\n"
            "            amount: 2\n"
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
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["result"]["status"] == "WARN"
    check = payload["result"]["checks"][0]
    assert check["check_id"] == "resources.capabilities"
    assert check["details"]["diagnostics"][0]["code"] == "resource.ignored"
    assert stderr.getvalue() == ""

    strict_stdout = io.StringIO()
    strict_stderr = io.StringIO()
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
            stdout=strict_stdout,
            stderr=strict_stderr,
        )
        == 4
    )
    strict_payload = json.loads(strict_stdout.getvalue())
    assert strict_payload["ok"] is False
    assert strict_payload["result"]["status"] == "WARN"
    assert strict_stderr.getvalue() == ""


def test_preflight_missing_config_returns_failed_result(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.yaml"
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["preflight", str(config_path), "--format", "json"], stdout=stdout, stderr=stderr) == 4

    payload = json.loads(stdout.getvalue())
    assert payload["ok"] is False
    assert payload["result"]["status"] == "FAIL"
    assert any(check["status"] == "FAIL" for check in payload["result"]["checks"])
    assert stderr.getvalue() == ""


def test_run_preflight_failure_exits_before_store_records(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.yaml"
    run_path = tmp_path / "runs" / "blocked"
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["run", str(config_path), "--run-uri", path_to_run_uri(run_path), "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 4
    )

    payload = json.loads(stdout.getvalue())
    assert payload["error"]["code"] == "cli.run.preflight_failed"
    assert payload["error"]["details"]["preflight"]["status"] == "FAIL"
    assert not run_path.exists()
    assert stderr.getvalue() == ""

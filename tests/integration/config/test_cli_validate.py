"""Integration tests for ``loom validate`` with real config composition."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from tests.support.config_samples import construction_event_log, reset_instantiate_probe_state


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _write_valid_config(path: Path) -> None:
    path.write_text(
        "service:\n"
        "  _target_: tests.support.config_samples:ConstructionProbeTarget\n"
        "  marker:\n"
        "    _target_: tests.support.config_samples:log_and_return\n"
        "    tag: service-child\n"
        "    value: ok\n"
        "pipeline:\n"
        "  name: demo\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages:ConfiguredProducerStage\n"
        "        init:\n"
        "          constructor_value: 7\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n",
        encoding="utf-8",
    )


def test_validate_static_default_does_not_construct_targets(tmp_path: Path) -> None:
    reset_instantiate_probe_state()
    config_path = tmp_path / "pipeline.yaml"
    _write_valid_config(config_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", str(config_path)], stdout=stdout, stderr=stderr) == 0

    assert stdout.getvalue() == f"OK validate {config_path}: 1 stage\n"
    assert stderr.getvalue() == ""
    assert construction_event_log == []


def test_validate_check_targets_constructs_stage_and_generic_targets(tmp_path: Path) -> None:
    reset_instantiate_probe_state()
    config_path = tmp_path / "pipeline.yaml"
    _write_valid_config(config_path)
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

    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.validate.v2"
    assert payload["warnings"][0]["code"] == "validate.target_constructors_may_run"
    assert payload["result"]["stage_count"] == 1
    assert payload["result"]["target_count"] == 3
    assert construction_event_log == ["service-child", "parent"]


def test_validate_invalid_pipeline_returns_pipeline_error(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "pipeline:\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages:JsonProducerStage\n",
        encoding="utf-8",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(["validate", str(config_path)], stdout=stdout, stderr=stderr) == 4

    assert stdout.getvalue() == ""
    assert "outputs" in stderr.getvalue()

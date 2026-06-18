"""End-to-end coverage for the deterministic sweep CLI."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.pipeline.stores import path_to_run_uri


pytestmark = pytest.mark.e2e


def test_sweep_cli_plan_run_status_collect_direct_workflow(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    config = _write_pipeline_config(tmp_path)
    sweep_dir = tmp_path / "sweep"

    plan_stdout = io.StringIO()
    assert (
        main(
            [
                "sweep",
                "plan",
                str(spec),
                "--sweep-dir",
                str(sweep_dir),
                "--format",
                "json",
            ],
            stdout=plan_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert json.loads(plan_stdout.getvalue())["result"]["trial_count"] == 1

    run_stdout = io.StringIO()
    assert (
        main(
            [
                "sweep",
                "run",
                str(spec),
                "--config",
                str(config),
                "--sweep-dir",
                str(sweep_dir),
                "--format",
                "json",
            ],
            stdout=run_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert json.loads(run_stdout.getvalue())["result"]["result"]["status"] == "succeeded"

    status_stdout = io.StringIO()
    assert (
        main(
            ["sweep", "status", str(sweep_dir), "--format", "json"],
            stdout=status_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    status = json.loads(status_stdout.getvalue())["result"]
    assert status["status"] == "succeeded"
    assert status["counts"]["succeeded"] == 1

    collect_stdout = io.StringIO()
    assert (
        main(
            [
                "sweep",
                "collect",
                str(sweep_dir),
                "--include-unsupported-extraction",
                "--format",
                "json",
            ],
            stdout=collect_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    collection = json.loads(collect_stdout.getvalue())["result"]
    assert collection["artifact_count"] == 1
    assert collection["trials"][0]["extraction_result"]["status"] == "unsupported"


def _write_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "sweep.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "manual",
                "sweep_id": "e2e-sweep",
                "run_uri_root": path_to_run_uri(tmp_path / "runs"),
                "trials": [{"overrides": {"pipeline.name": "e2e-sweep"}}],
            }
        ),
        encoding="utf-8",
    )
    return spec


def _write_pipeline_config(tmp_path: Path) -> Path:
    config = tmp_path / "pipeline.json"
    config.write_text(
        json.dumps(
            {
                "pipeline": {
                    "name": "demo",
                    "stages": [
                        {
                            "name": "build",
                            "factory": {
                                "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                            },
                            "config": {"value": 1},
                            "outputs": {
                                "data": {
                                    "artifact_type": "json",
                                    "codec_key": "json.v1",
                                }
                            },
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return config

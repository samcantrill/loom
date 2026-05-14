"""Unit tests for ``loom sweep`` CLI helpers."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.cli.main import main
from loom.pipeline.status import RunStatus, RunStatusRecord
from loom.pipeline.stores import LocalRunStore, path_to_run_uri


pytestmark = pytest.mark.unit


def test_sweep_plan_command_writes_manifests_and_json(tmp_path: Path) -> None:
    spec = _write_spec(tmp_path)
    sweep_dir = tmp_path / "sweep"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "sweep",
            "plan",
            str(spec),
            "--sweep-dir",
            str(sweep_dir),
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.sweep.plan.v1"
    assert payload["result"]["sweep_id"] == "cli-sweep"
    assert payload["result"]["trial_count"] == 2
    assert (sweep_dir / "sweep.json").exists()
    assert (sweep_dir / "trials.json").exists()


def test_sweep_status_and_collect_commands_read_existing_plan(
    tmp_path: Path,
) -> None:
    spec = _write_spec(tmp_path)
    sweep_dir = tmp_path / "sweep"
    assert main(["sweep", "plan", str(spec), "--sweep-dir", str(sweep_dir)]) == 0
    run_uri = path_to_run_uri(tmp_path / "runs" / "trial-0001")
    store = LocalRunStore(tmp_path / "runs")
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2026-05-14T00:00:00Z",
            updated_at="2026-05-14T00:00:01Z",
        ),
    )
    store.write_artifact_index(
        run_uri,
        {
            "build.out": ArtifactRef(
                artifact_id="build/out",
                uri=f"{run_uri}/artifacts/build/out.json",
                artifact_type="json",
            )
        },
    )

    status_stdout = io.StringIO()
    assert (
        main(
            ["sweep", "status", str(sweep_dir), "--format", "json"],
            stdout=status_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    status_payload = json.loads(status_stdout.getvalue())
    assert status_payload["result"]["counts"]["succeeded"] == 1
    assert status_payload["result"]["counts"]["pending"] == 1

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
    collect_payload = json.loads(collect_stdout.getvalue())
    assert collect_payload["schema_version"] == "loom.cli.sweep.collect.v1"
    assert collect_payload["result"]["artifact_count"] == 1
    assert collect_payload["result"]["trials"][0]["extraction_result"]["status"] == "unsupported"


def test_sweep_run_queue_command_enqueues_without_draining(
    tmp_path: Path,
) -> None:
    spec = _write_spec(tmp_path)
    config = _write_pipeline_config(tmp_path)
    queue_config = _write_queue_config(tmp_path)
    sweep_dir = tmp_path / "sweep"
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "sweep",
            "run",
            str(spec),
            "--config",
            str(config),
            "--sweep-dir",
            str(sweep_dir),
            "--queue-config",
            str(queue_config),
            "--queue-name",
            "local",
            "--format",
            "json",
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert stderr.getvalue() == ""
    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.sweep.run.v1"
    assert payload["result"]["mode"] == "queue"
    assert payload["result"]["result"]["submitted_count"] == 2

    status_stdout = io.StringIO()
    assert (
        main(
            [
                "sweep",
                "status",
                str(sweep_dir),
                "--queue-config",
                str(queue_config),
                "--format",
                "json",
            ],
            stdout=status_stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    status_payload = json.loads(status_stdout.getvalue())
    assert status_payload["result"]["counts"]["queued"] == 2


def _write_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "sweep.json"
    payload = {
        "schema_version": 1,
        "mode": "manual",
        "sweep_id": "cli-sweep",
        "run_uri_root": path_to_run_uri(tmp_path / "runs"),
        "trials": [
            {"overrides": {"pipeline.name": "demo-a"}},
            {"overrides": {"pipeline.name": "demo-b"}},
        ],
    }
    spec.write_text(json.dumps(payload), encoding="utf-8")
    return spec


def _write_pipeline_config(tmp_path: Path) -> Path:
    config = tmp_path / "pipeline.json"
    payload = {
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
    config.write_text(json.dumps(payload), encoding="utf-8")
    return config


def _write_queue_config(tmp_path: Path) -> Path:
    config = tmp_path / "queue.json"
    payload = {
        "service": {"db_path": str(tmp_path / "queue.sqlite")},
        "pools": [{"pool_name": "local-pool", "mode": "managed"}],
        "queues": [{"queue_name": "local", "pool_name": "local-pool"}],
    }
    config.write_text(json.dumps(payload), encoding="utf-8")
    return config

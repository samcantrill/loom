"""End-to-end coverage for ``loom runs`` commands through ``main(argv)``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.artifacts import ArtifactRef
from loom.cli.main import main
from loom.fingerprints import format_digest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import path_to_run_uri


pytestmark = pytest.mark.e2e


def test_cli_runs_index_list_and_diff(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    left_uri = _create_run(
        root,
        root / "left",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
        config_fingerprint="config-left",
    )
    right_uri = _create_run(
        root,
        root / "right",
        status=RunStatus.FAILED,
        tag_value="demo",
        config_fingerprint="config-right",
    )

    index_stdout = io.StringIO()
    index_stderr = io.StringIO()
    assert (
        main(
            ["runs", "index", str(root)],
            stdout=index_stdout,
            stderr=index_stderr,
        )
        == 0
    )
    assert f"runs index {root}: 2 indexed, 0 skipped" in index_stdout.getvalue()
    assert index_stderr.getvalue() == ""

    list_stdout = io.StringIO()
    list_stderr = io.StringIO()
    assert (
        main(
            [
                "runs",
                "list",
                str(root),
                "--status",
                "SUCCEEDED",
                "--tag",
                "project=demo",
            ],
            stdout=list_stdout,
            stderr=list_stderr,
        )
        == 0
    )
    list_output = list_stdout.getvalue()
    assert f"runs list {root}: 1 run" in list_output
    assert left_uri in list_output
    assert right_uri not in list_output
    assert list_stderr.getvalue() == ""

    diff_stdout = io.StringIO()
    diff_stderr = io.StringIO()
    assert (
        main(
            [
                "runs",
                "diff",
                str(root),
                left_uri,
                right_uri,
                "--format",
                "json",
            ],
            stdout=diff_stdout,
            stderr=diff_stderr,
        )
        == 0
    )
    payload = json.loads(diff_stdout.getvalue())
    assert payload["schema_version"] == "loom.cli.runs.diff.v1"
    assert payload["result"]["sections"][0]["entries"][0]["status"] == "different"
    assert diff_stderr.getvalue() == ""


def _create_run(
    root: Path,
    run_path: Path,
    *,
    status: RunStatus,
    tag_value: str,
    config_fingerprint: str,
) -> str:
    store = create_authority_backed_serial_run_store(root)
    run_uri = path_to_run_uri(run_path)
    store.create_run(run_uri, metadata={"tags": {"project": tag_value}})
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=status,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_composition_manifest(run_uri, {"fingerprint": config_fingerprint})
    store.write_plan(run_uri, {"pipeline_fingerprint": "pipeline-demo"})
    store.write_runtime_metadata(run_uri, {"executor": "local", "backend": "local"})
    store.write_stage_status(
        run_uri,
        "build",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="build",
            status=StageStatus.SUCCEEDED
            if status is RunStatus.SUCCEEDED
            else StageStatus.FAILED,
            attempt=1,
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_artifact_index(
        run_uri,
        {
            "build.out": ArtifactRef(
                artifact_id="build/out",
                uri="file:///tmp/out.json",
                artifact_type="json",
                codec_key="json.v1",
                checksum=format_digest("sha256", "a" * 64),
                producer_stage="build",
            )
        },
    )
    return run_uri

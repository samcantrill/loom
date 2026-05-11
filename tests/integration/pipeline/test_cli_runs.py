"""Integration coverage for ``loom runs`` commands over local stores."""

from __future__ import annotations

import io
import json
from pathlib import Path

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
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


def test_cli_runs_list_filters_current_catalog(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    match_uri = _create_run(
        root,
        root / "match",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
        checksum=format_digest("sha256", "1" * 64),
    )
    _create_run(
        root,
        root / "other",
        status=RunStatus.FAILED,
        tag_value="other",
        checksum=format_digest("sha256", "2" * 64),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "list",
                str(root),
                "--tag",
                "project=demo",
                "--artifact",
                "build.out=build/out",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert [summary["run_uri"] for summary in payload["result"]["summaries"]] == [
        match_uri
    ]
    assert payload["result"]["filters"] == [
        {"kind": "tag", "key": "project", "value": "demo"},
        {"kind": "artifact_identity", "key": "build.out", "value": "build/out"},
    ]
    assert stderr.getvalue() == ""


def test_cli_runs_diff_formats_metadata_comparison(tmp_path: Path) -> None:
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
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "diff", str(root), left_uri, right_uri],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    output = stdout.getvalue()
    assert f"runs diff {left_uri} {right_uri}:" in output
    assert "run.status: different left=SUCCEEDED right=FAILED" in output
    assert (
        "fingerprints.config: different left=config-left right=config-right"
        in output
    )
    assert stderr.getvalue() == ""


def test_cli_runs_list_reports_partial_run_warnings(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _create_run(
        root,
        root / "healthy",
        status=RunStatus.SUCCEEDED,
        tag_value="demo",
    )
    partial_path = root / "partial"
    partial_path.mkdir(parents=True)
    partial_uri = path_to_run_uri(partial_path)
    (partial_path / "run.json").write_text(
        (
            "{"
            '"schema_version": 1, '
            f'"run_uri": "{partial_uri}", '
            '"created_at": "2020-01-01T00:00:00Z", '
            '"metadata": {}'
            "}\n"
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "list", str(root), "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["warnings"][0]["code"] == "local_lifecycle_unsupported"
    assert payload["warnings"][0]["details"]["path"] == str(partial_path)
    assert payload["result"]["warnings"][0]["path"] == str(partial_path)
    assert stderr.getvalue() == ""


def _create_run(
    root: Path,
    run_path: Path,
    *,
    status: RunStatus,
    tag_value: str,
    config_fingerprint: str = "config-demo",
    checksum: str | None = None,
) -> str:
    store = create_authority_backed_serial_run_store(
        root,
        authority_store=SQLitePerRunAuthorityStore(),
    )
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
                checksum=checksum or format_digest("sha256", "a" * 64),
                producer_stage="build",
            )
        },
    )
    return run_uri

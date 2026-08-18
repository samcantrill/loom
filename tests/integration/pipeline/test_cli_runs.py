"""Integration coverage for ``loom runs`` commands over local stores."""

from __future__ import annotations

import io
import json
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.cli.main import main
from loom.fingerprints import format_digest
from loom.io.uris import path_to_file_uri, uri_to_path
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


def test_cli_runs_export_inspect_import_local_bundle(tmp_path: Path) -> None:
    run_uri = _create_completed_authority_run(tmp_path / "source-runs" / "run-1")
    bundle_path = tmp_path / "bundle.tar"
    target_collection = tmp_path / "target-runs"

    export_stdout = io.StringIO()
    export_stderr = io.StringIO()
    assert (
        main(
            ["runs", "export", run_uri, str(bundle_path), "--include-payloads"],
            stdout=export_stdout,
            stderr=export_stderr,
        )
        == 0
    )
    assert f"runs export {run_uri}: succeeded" in export_stdout.getvalue()
    assert "payloads=1" in export_stdout.getvalue()
    assert export_stderr.getvalue() == ""

    inspect_stdout = io.StringIO()
    inspect_stderr = io.StringIO()
    assert (
        main(
            ["runs", "inspect", str(bundle_path)],
            stdout=inspect_stdout,
            stderr=inspect_stderr,
        )
        == 0
    )
    assert f"runs inspect {bundle_path}: succeeded" in inspect_stdout.getvalue()
    assert "payloads=1" in inspect_stdout.getvalue()
    assert inspect_stderr.getvalue() == ""

    import_stdout = io.StringIO()
    import_stderr = io.StringIO()
    assert (
        main(
            ["runs", "import", str(bundle_path), str(target_collection)],
            stdout=import_stdout,
            stderr=import_stderr,
        )
        == 0
    )
    import_output = import_stdout.getvalue()
    assert f"runs import {bundle_path}: succeeded" in import_output
    assert "readiness: mode=historical_only blockers=1" in import_output
    assert import_stderr.getvalue() == ""
    assert (target_collection / "run-1").exists()


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
    if status is RunStatus.SUCCEEDED:
        store.write_run_status(
            run_uri,
            RunStatusRecord(
                run_uri=run_uri,
                status=RunStatus.RUNNING,
                created_at="2020-01-01T00:00:00Z",
                updated_at="2020-01-01T00:00:00Z",
            ),
        )
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
    if status is RunStatus.SUCCEEDED:
        store.write_stage_status(
            run_uri,
            "build",
            StageStatusRecord(
                run_uri=run_uri,
                stage_name="build",
                status=StageStatus.RUNNING,
                attempt=1,
                updated_at="2020-01-01T00:00:00Z",
            ),
        )
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


def _create_completed_authority_run(run_path: Path) -> str:
    run_uri = path_to_run_uri(run_path)
    payload = run_path / "artifacts" / "build" / "out.bin"
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(b"payload")
    store = SQLitePerRunAuthorityStore(run_uri)
    store.create_run(run_uri)
    allocation = store.allocate_stage_attempt(
        run_uri,
        "build",
        owner_id="worker-1",
        lease_ttl_seconds=30,
    )
    assert allocation.lease is not None
    store.record_output_commit(
        run_uri,
        "build",
        attempt_id=allocation.attempt.attempt_id,
        fencing_token=allocation.lease.fencing_token,
        outputs={
            "out": ArtifactRef(
                artifact_id="build/out",
                uri=path_to_file_uri(payload),
                artifact_type="bytes",
            )
        },
    )
    store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.RUNNING,
    )
    store.transition_run(
        run_uri,
        from_status=RunStatus.RUNNING,
        to_status=RunStatus.SUCCEEDED,
    )
    assert uri_to_path(run_uri) == run_path
    return run_uri

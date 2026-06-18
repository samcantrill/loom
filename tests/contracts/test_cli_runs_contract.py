"""Contract tests for ``loom runs`` JSON output."""

from __future__ import annotations

import io
import json
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.cli.main import main
from loom.cli.runs import (
    RUNS_DIFF_SCHEMA_VERSION,
    RUNS_EXPORT_SCHEMA_VERSION,
    RUNS_INDEX_SCHEMA_VERSION,
    RUNS_IMPORT_SCHEMA_VERSION,
    RUNS_INSPECT_SCHEMA_VERSION,
    RUNS_LIST_SCHEMA_VERSION,
)
from loom.fingerprints import format_digest
from loom.io.uris import path_to_file_uri
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.status import (
    RunStatus,
    RunStatusRecord,
    StageStatus,
    StageStatusRecord,
)
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore


def test_runs_index_json_contract(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _create_run(root, root / "a", status=RunStatus.SUCCEEDED)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            ["runs", "index", str(root), "--format", "json"],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == RUNS_INDEX_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["warnings"] == []
    assert payload["result"]["indexed_count"] == 1
    assert payload["result"]["skipped_count"] == 0
    assert stderr.getvalue() == ""


def test_runs_list_json_contract(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    _create_run(root, root / "a", status=RunStatus.SUCCEEDED)
    _create_run(root, root / "b", status=RunStatus.FAILED)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "runs",
                "list",
                str(root),
                "--status",
                "SUCCEEDED",
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == RUNS_LIST_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["warnings"] == []
    assert [summary["status"] for summary in payload["result"]["summaries"]] == [
        "SUCCEEDED"
    ]
    assert (
        payload["result"]["summaries"][0]["state_source"]["label"]
        == "materialized_local_state"
    )
    assert payload["result"]["filters"] == [
        {"kind": "run_status", "key": None, "value": "SUCCEEDED"}
    ]
    assert stderr.getvalue() == ""


def test_runs_diff_json_contract(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    left_uri = _create_run(root, root / "a", status=RunStatus.SUCCEEDED)
    right_uri = _create_run(root, root / "b", status=RunStatus.FAILED)
    stdout = io.StringIO()
    stderr = io.StringIO()

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
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    payload = json.loads(stdout.getvalue())
    assert payload["schema_version"] == RUNS_DIFF_SCHEMA_VERSION
    assert payload["ok"] is True
    assert payload["warnings"] == []
    assert payload["result"]["left_run_uri"] == left_uri
    assert payload["result"]["right_run_uri"] == right_uri
    assert payload["result"]["sections"][0]["entries"][0] == {
        "key": "run.status",
        "status": "different",
        "left": "SUCCEEDED",
        "right": "FAILED",
        "details": {},
    }
    assert stderr.getvalue() == ""


def test_runs_bundle_exchange_json_contract(tmp_path: Path) -> None:
    run_uri = _create_completed_authority_run(tmp_path / "source-runs" / "run-1")
    bundle_path = tmp_path / "bundle.tar"
    target_collection = tmp_path / "target-runs"

    export_stdout = io.StringIO()
    export_stderr = io.StringIO()
    assert (
        main(
            ["runs", "export", run_uri, str(bundle_path), "--format", "json"],
            stdout=export_stdout,
            stderr=export_stderr,
        )
        == 0
    )
    export_payload = json.loads(export_stdout.getvalue())
    assert export_payload["schema_version"] == RUNS_EXPORT_SCHEMA_VERSION
    assert export_payload["ok"] is True
    assert export_payload["warnings"] == []
    assert export_payload["result"]["status"] == "succeeded"
    assert export_payload["result"]["exported_payload_count"] == 0
    assert export_payload["result"]["manifest"]["payload_selection"] == {
        "include_artifacts": False,
        "include_logs": False,
        "include_other": False,
        "include_workspace": False,
        "extensions": {},
    }
    assert export_stderr.getvalue() == ""

    inspect_stdout = io.StringIO()
    inspect_stderr = io.StringIO()
    assert (
        main(
            ["runs", "inspect", str(bundle_path), "--format", "json"],
            stdout=inspect_stdout,
            stderr=inspect_stderr,
        )
        == 0
    )
    inspect_payload = json.loads(inspect_stdout.getvalue())
    assert inspect_payload["schema_version"] == RUNS_INSPECT_SCHEMA_VERSION
    assert inspect_payload["ok"] is True
    assert inspect_payload["result"]["status"] == "succeeded"
    assert inspect_payload["result"]["manifest"]["run_uri"] == run_uri
    assert inspect_payload["result"]["included_payload_count"] == 0
    assert inspect_stderr.getvalue() == ""

    import_stdout = io.StringIO()
    import_stderr = io.StringIO()
    assert (
        main(
            [
                "runs",
                "import",
                str(bundle_path),
                str(target_collection),
                "--format",
                "json",
            ],
            stdout=import_stdout,
            stderr=import_stderr,
        )
        == 0
    )
    import_payload = json.loads(import_stdout.getvalue())
    assert import_payload["schema_version"] == RUNS_IMPORT_SCHEMA_VERSION
    assert import_payload["ok"] is True
    assert import_payload["result"]["status"] == "succeeded"
    assert import_payload["result"]["target_run_uri"].endswith("/run-1")
    assert import_payload["result"]["readiness"]["mode"] == "historical_only"
    assert import_stderr.getvalue() == ""


def _create_run(
    root: Path,
    run_path: Path,
    *,
    status: RunStatus,
) -> str:
    store = create_authority_backed_serial_run_store(
        root,
        authority_store=SQLitePerRunAuthorityStore(),
    )
    run_uri = path_to_run_uri(run_path)
    store.create_run(run_uri, metadata={"tags": {"project": "contract"}})
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=status,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    store.write_composition_manifest(run_uri, {"fingerprint": "config-contract"})
    store.write_plan(run_uri, {"pipeline_fingerprint": "pipeline-contract"})
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
                checksum=format_digest("sha256", "a" * 64),
            )
        },
    )
    store.transition_run(
        run_uri,
        from_status=RunStatus.CREATED,
        to_status=RunStatus.SUCCEEDED,
    )
    return run_uri

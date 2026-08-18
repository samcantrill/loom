"""Integration coverage for local bundle import APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loom.artifacts import ArtifactRef
from loom.io.uris import path_to_file_uri, uri_to_path
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.runs import (
    RunBundleExportOptions,
    RunCatalog,
    RunExchangeOperationStatus,
    export_run_bundle,
    import_run_bundle,
)


@dataclass(slots=True)
class FrozenClock:
    value: str

    def __call__(self) -> str:
        return self.value


def test_import_completed_bundle_rebases_payloads_and_refreshes_catalog(
    tmp_path: Path,
) -> None:
    source = _export_completed_bundle(tmp_path)
    target_collection = tmp_path / "target-runs"

    result = import_run_bundle(source.bundle_path, target_collection)

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.target_run_uri is not None
    assert result.target_run_uri != source.run_uri
    assert result.imported_entry_count == 1
    assert result.imported_payload_count == 1
    target_run_dir = uri_to_path(result.target_run_uri)
    assert target_run_dir == target_collection / "run-1"
    store = LocalRunStore(target_collection)
    status = store.read_run_status(result.target_run_uri)
    assert status is not None
    assert status.status is RunStatus.SUCCEEDED
    artifacts = store.read_artifact_index(result.target_run_uri)
    assert set(artifacts) == {"build.out"}
    imported_ref = artifacts["build.out"]
    imported_payload = uri_to_path(imported_ref.uri)
    assert imported_payload.read_bytes() == b"payload"
    assert imported_payload.is_relative_to(target_run_dir / "imported_payloads")
    assert imported_ref.metadata["source_uri"] == path_to_file_uri(source.payload_path)
    listed = RunCatalog.open(target_collection).list()
    assert [summary.run_uri for summary in listed.summaries] == [result.target_run_uri]


@dataclass(frozen=True, slots=True)
class ExportedBundle:
    bundle_path: Path
    run_uri: str
    payload_path: Path


def _export_completed_bundle(tmp_path: Path) -> ExportedBundle:
    run_root = tmp_path / "source-runs" / "run-1"
    run_uri = path_to_run_uri(run_root)
    payload = run_root / "artifacts" / "build" / "out.bin"
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(b"payload")
    clock = FrozenClock("2020-01-01T00:00:00Z")
    store = SQLitePerRunAuthorityStore(run_uri, clock=clock)
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
    bundle_path = tmp_path / "bundle.tar"
    result = export_run_bundle(
        SQLitePerRunAuthorityStore(run_uri, clock=clock),
        run_uri,
        bundle_path,
        options=RunBundleExportOptions(include_payloads=True, verify_checksums=True),
    )
    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    return ExportedBundle(
        bundle_path=bundle_path,
        run_uri=run_uri,
        payload_path=payload,
    )

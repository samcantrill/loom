"""Integration coverage for local bundle import APIs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
    historical = cast(Any, store.read_runtime_metadata(result.target_run_uri))["historical_lineage"]
    assert historical["source_run_uri"] == source.run_uri
    assert historical["stages"][0]["attempts"][0]["run_uri"] == source.run_uri
    assert historical["stages"][0]["attempts"][0]["start_confirmed"] is True
    assert historical["stages"][0]["attempts"][0]["input_bindings"] is None
    assert not (target_run_dir / ".loom" / "authority.sqlite3").exists()
    listed = RunCatalog.open(target_collection).list()
    assert [summary.run_uri for summary in listed.summaries] == [result.target_run_uri]


@dataclass(frozen=True, slots=True)
class ExportedBundle:
    bundle_path: Path
    run_uri: str
    payload_path: Path


def test_import_preserves_nonempty_source_lineage_without_graph_stitching(tmp_path):
    from dataclasses import replace
    from types import SimpleNamespace
    from tests.integration.queue.test_lineage_queries import graph
    from loom.pipeline.stores import read_completed_run_bundle_metadata
    from loom.runs import export_completed_run_bundle, CollectionScope, LineageQuery
    from loom.queue._lineage import lineage_operation

    _, _, consumer, uri, locator = graph(tmp_path)
    consumer.transition_run(uri, from_status=RunStatus.RUNNING, to_status=RunStatus.SUCCEEDED)
    metadata = read_completed_run_bundle_metadata(consumer, uri)
    from loom.pipeline.stores import CompletedRunBundleMetadata
    projected = CompletedRunBundleMetadata.from_snapshot(consumer.snapshot(uri))
    assert projected.lineage_evidence is not None
    assert [s["attempts"] for s in cast(Any, projected.lineage_evidence)["stages"]] == [s["attempts"] for s in cast(Any, metadata.lineage_evidence)["stages"]]
    projected_bundle = tmp_path / "snapshot.tar"
    assert export_completed_run_bundle(projected, projected_bundle).status is RunExchangeOperationStatus.SUCCEEDED
    projected_import = import_run_bundle(projected_bundle, tmp_path / "snapshot-import")
    assert projected_import.target_run_uri is not None
    assert cast(Any, LocalRunStore(tmp_path / "snapshot-import").read_runtime_metadata(projected_import.target_run_uri))["historical_lineage"] == projected.lineage_evidence
    bundle = tmp_path / "lineage.tar"
    assert export_completed_run_bundle(metadata, bundle).status is RunExchangeOperationStatus.SUCCEEDED
    for root in (tmp_path / "first", tmp_path / "second"):
        imported = import_run_bundle(bundle, root)
        assert imported.status is RunExchangeOperationStatus.SUCCEEDED
        assert imported.target_run_uri is not None
        local = LocalRunStore(root)
        history = cast(Any, local.read_runtime_metadata(imported.target_run_uri))["historical_lineage"]
        assert history == metadata.lineage_evidence
        transforms = [s for s in history["stages"] if s["stage_name"] == "transform"]
        binding = transforms[0]["attempts"][0]["input_bindings"][0]
        assert binding["producer"] == locator.to_dict()
        assert transforms[0]["attempts"][0]["run_uri"] == uri != imported.target_run_uri
        daemon = SimpleNamespace(config=SimpleNamespace(run_store_root=root, coordinator_authority_factory=SQLitePerRunAuthorityStore), _require_started=lambda: "coordinator")
        page = lineage_operation(daemon, LineageQuery(start={"run_uri": imported.target_run_uri}, scope=CollectionScope()).checked())
        assert not page.items and not page.complete
        assert any(w["code"] == "authority_unavailable" for w in page.warnings)
    old_bundle = tmp_path / "old.tar"
    export_completed_run_bundle(replace(metadata, lineage_evidence=None), old_bundle)
    imported = import_run_bundle(old_bundle, tmp_path / "old")
    assert imported.target_run_uri is not None
    assert cast(Any, LocalRunStore(tmp_path / "old").read_runtime_metadata(imported.target_run_uri))["historical_lineage"] is None


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

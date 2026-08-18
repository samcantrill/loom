"""Integration tests for local bundle export and inspect APIs."""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from loom.artifacts import ArtifactRef
from loom.io.uris import path_to_file_uri
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.runs import (
    PortableRunSourceIdentity,
    PortableRunTargetIdentityPolicy,
    RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
    RunBundleExportOptions,
    RunBundleManifest,
    RunExchangeOperationStatus,
    RunTargetIdentityPolicyMode,
    export_run_bundle,
    inspect_run_bundle,
)
from loom.serialization import stable_json_bytes


@dataclass(slots=True)
class FrozenClock:
    value: str

    def __call__(self) -> str:
        return self.value


def test_export_and_inspect_completed_run_bundle(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
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

    result = export_run_bundle(
        SQLitePerRunAuthorityStore(run_uri, clock=clock),
        run_uri,
        tmp_path / "bundle.tar",
        options=RunBundleExportOptions(include_payloads=True, verify_checksums=True),
    )

    assert result.status is RunExchangeOperationStatus.SUCCEEDED
    assert result.exported_payload_count == 1
    inspection = inspect_run_bundle(tmp_path / "bundle.tar", verify_checksums=True)
    assert inspection.status is RunExchangeOperationStatus.SUCCEEDED
    assert inspection.manifest.run_uri == run_uri
    assert inspection.included_payload_count == 1
    completed_run = cast(dict[str, object], inspection.manifest.extensions["completed_run"])
    stages = cast(list[dict[str, object]], completed_run["stages"])
    assert stages[0]["stage_name"] == "build"


def test_inspect_reports_unsafe_member_without_extracting(tmp_path: Path) -> None:
    bundle_path = tmp_path / "unsafe.tar"
    manifest = RunBundleManifest(
        schema_version=RUN_BUNDLE_MANIFEST_SCHEMA_VERSION,
        run_uri="file:///runs/source/run-1",
        source_identity=PortableRunSourceIdentity(
            source_kind="test",
            run_uri="file:///runs/source/run-1",
        ),
        target_identity=PortableRunTargetIdentityPolicy(
            mode=RunTargetIdentityPolicyMode.TARGET_LOCAL,
        ),
    )
    with tarfile.open(bundle_path, "w") as archive:
        manifest_bytes = stable_json_bytes(manifest.to_dict())
        manifest_info = tarfile.TarInfo("manifest.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, io.BytesIO(manifest_bytes))
        unsafe_bytes = b"unsafe"
        unsafe_info = tarfile.TarInfo("../escape.txt")
        unsafe_info.size = len(unsafe_bytes)
        archive.addfile(unsafe_info, io.BytesIO(unsafe_bytes))

    inspection = inspect_run_bundle(bundle_path)

    assert inspection.status is RunExchangeOperationStatus.FAILED
    assert [diagnostic.code for diagnostic in inspection.diagnostics] == [
        "run_bundle_inspect.unsafe_member_path"
    ]
    assert not (tmp_path / "escape.txt").exists()

"""Package-level API tests for pipeline store modules."""

import inspect
import subprocess
import sys

import pytest


pytestmark = pytest.mark.package


def test_pipeline_store_public_exports() -> None:
    import loom.pipeline.stores as stores

    assert stores
    assert set(stores.__all__) == {
        "ArtifactStore",
        "LocalArtifactStore",
        "RunStore",
        "RunLifecycleStore",
        "RunDocumentStore",
        "RunEventStore",
        "RunInspectionStore",
        "RunLockStore",
        "RunStatusStore",
        "RunPlanStore",
        "RunPreparedRunStore",
        "RunArtifactIndexStore",
        "RunConfigStore",
        "RunProvenanceStore",
        "RunRuntimeMetadataStore",
        "StageStateStore",
        "StageLogStore",
        "StageWorkspaceStore",
        "LocalRunStorePaths",
        "LocalRunStore",
        "RunStageInspection",
        "RunStateInspection",
        "StoreError",
        "ArtifactStoreError",
        "RunStoreError",
        "RunLockError",
        "RunLockConflictError",
        "RunLockReleaseError",
        "UnsafeStorePathError",
        "InvalidRunURIError",
        "UnsupportedArtifactURIError",
        "ArtifactNotFoundError",
        "MissingArtifactCodecError",
        "ArtifactTypeMismatchError",
        "ArtifactChecksumMismatchError",
        "ArtifactChecksumUnsupportedError",
        "RunAlreadyExistsError",
        "RunNotFoundError",
        "MissingStoreDocumentError",
        "CorruptStoreDocumentError",
        "StageStateNotFoundError",
        "AtomicWriteError",
        "ensure_dir",
        "unique_temp_path",
        "atomic_write_bytes",
        "atomic_write_text",
        "atomic_write_json",
        "replace_file",
        "format_artifact_key",
        "parse_artifact_key",
        "artifact_index_to_dict",
        "artifact_index_from_dict",
        "merge_artifact_index",
        "LocalRunURI",
        "resolve_local_run_uri",
        "validate_run_uri",
        "run_uri_to_path",
        "path_to_run_uri",
        "allocate_local_run_uri",
    }
    assert "read_composition_manifest" in stores.RunConfigStore.__dict__
    assert "write_composition_manifest" in stores.RunConfigStore.__dict__
    assert "read_stage_worker_request" in stores.StageStateStore.__dict__
    assert "write_stage_worker_request" in stores.StageStateStore.__dict__
    assert "read_stage_worker_result" in stores.StageStateStore.__dict__
    assert "write_stage_worker_result" in stores.StageStateStore.__dict__
    assert "read_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "write_prepared_run" in stores.RunPreparedRunStore.__dict__
    assert "local_stage_worker_request_path" in stores.LocalRunStorePaths.__dict__
    assert "local_stage_worker_result_path" in stores.LocalRunStorePaths.__dict__
    assert "local_generated_artifact_path" in stores.LocalRunStorePaths.__dict__
    write_signature = inspect.signature(
        stores.RunConfigStore.write_composition_manifest
    )
    assert list(write_signature.parameters) == ["self", "run_uri", "manifest"]


@pytest.mark.parametrize(
    "forbidden",
    ["loom.config", "loom.cli"],
)
def test_pipeline_stores_import_does_not_import_forbidden_modules(
    forbidden: str,
) -> None:
    script = (
        "import sys\n"
        "import loom.pipeline.stores\n"
        f"if {forbidden!r} in sys.modules:\n"
        f"    raise SystemExit('{forbidden} was imported through loom.pipeline.stores')\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"

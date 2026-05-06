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
        "RunLockStore",
        "RunStatusStore",
        "RunPlanStore",
        "RunArtifactIndexStore",
        "RunConfigStore",
        "RunProvenanceStore",
        "StageStateStore",
        "StageLogStore",
        "StageWorkspaceStore",
        "LocalRunStorePaths",
        "LocalRunStore",
        "StoreError",
        "ArtifactStoreError",
        "RunStoreError",
        "RunLockError",
        "RunLockConflictError",
        "RunLockReleaseError",
        "UnsafeStorePathError",
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
    }
    assert "read_composition_manifest" in stores.RunConfigStore.__dict__
    assert "write_composition_manifest" in stores.RunConfigStore.__dict__
    write_signature = inspect.signature(
        stores.RunConfigStore.write_composition_manifest
    )
    assert list(write_signature.parameters) == ["self", "run_id", "manifest"]


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

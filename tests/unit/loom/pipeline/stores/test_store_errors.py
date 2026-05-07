"""Tests for store error exports and inheritance."""

import loom.pipeline.stores as stores


def test_store_error_inheritance() -> None:
    assert issubclass(stores.StoreError, Exception)
    assert issubclass(stores.ArtifactStoreError, stores.StoreError)
    assert issubclass(stores.RunStoreError, stores.StoreError)
    assert issubclass(stores.UnsafeStorePathError, stores.StoreError)
    assert issubclass(stores.InvalidRunURIError, stores.RunStoreError)
    assert issubclass(stores.UnsupportedArtifactURIError, stores.ArtifactStoreError)
    assert issubclass(stores.ArtifactNotFoundError, stores.ArtifactStoreError)
    assert issubclass(stores.MissingArtifactCodecError, stores.ArtifactStoreError)
    assert issubclass(stores.ArtifactTypeMismatchError, stores.ArtifactStoreError)
    assert issubclass(stores.ArtifactChecksumMismatchError, stores.ArtifactStoreError)
    assert issubclass(
        stores.ArtifactChecksumUnsupportedError, stores.ArtifactStoreError
    )
    assert issubclass(stores.AtomicWriteError, stores.StoreError)
    assert issubclass(stores.RunAlreadyExistsError, stores.RunStoreError)
    assert issubclass(stores.RunLockError, stores.RunStoreError)
    assert issubclass(stores.RunLockConflictError, stores.RunLockError)
    assert issubclass(stores.RunLockReleaseError, stores.RunLockError)
    assert issubclass(stores.RunNotFoundError, stores.RunStoreError)
    assert issubclass(stores.MissingStoreDocumentError, stores.RunStoreError)
    assert issubclass(stores.CorruptStoreDocumentError, stores.RunStoreError)
    assert issubclass(stores.StageStateNotFoundError, stores.RunStoreError)


def test_store_error_exports() -> None:
    assert stores.__all__ == [
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
    ]

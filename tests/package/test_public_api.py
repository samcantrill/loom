"""Package-level API tests."""

import pytest


pytestmark = pytest.mark.package


def test_public_root_symbols() -> None:
    from loom import ArtifactRef, Fingerprint, InMemoryManifest, ManifestView, Record, ResourceRef, __all__, __version__, hash_mapping

    assert __version__
    assert __all__
    assert ResourceRef
    assert ArtifactRef
    assert InMemoryManifest
    assert ManifestView
    assert Record
    assert Fingerprint
    assert callable(hash_mapping)


def test_package_modules_import_cleanly() -> None:
    import loom.fingerprints
    import loom.ids
    import loom.refs
    import loom.artifacts
    import loom.records
    import loom.serialization
    import loom.provenance
    import loom.protocols
    import loom.errors
    import loom.timestamps

    assert loom.ids
    assert loom.refs
    assert loom.artifacts
    assert loom.records
    assert loom.serialization
    assert loom.provenance
    assert loom.protocols
    assert loom.errors
    assert loom.timestamps


def test_public_import_paths() -> None:
    from loom.fingerprints import Fingerprint, hash_mapping
    from loom.ids import Checksum, Fingerprint as IdFingerprint, ResourceType
    from loom.refs import ResourceRef, ResourceRefError
    from loom.artifacts import ArtifactRef, ArtifactValidationError
    from loom.records import Record
    from loom.serialization import PlainData
    from loom.serialization import dataclass_to_dict
    from loom.provenance import capture_command_provenance, ProvenanceCaptureOptions, StageProvenance, RunProvenance

    assert Fingerprint
    assert hash_mapping
    assert Checksum
    assert IdFingerprint
    assert ResourceType
    assert ResourceRef
    assert ResourceRefError
    assert ArtifactRef
    assert ArtifactValidationError
    assert Record
    assert PlainData
    assert dataclass_to_dict
    assert ProvenanceCaptureOptions
    assert capture_command_provenance
    assert StageProvenance
    assert RunProvenance

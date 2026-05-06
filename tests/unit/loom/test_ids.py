"""Unit tests for loom identifiers."""

import loom.ids as ids


def test_id_aliases_are_string_types() -> None:
    assert ids.RecordID is str
    assert ids.ResourceKey is str
    assert ids.CodecKey is str
    assert ids.ResourceType is str
    assert ids.ArtifactID is str
    assert ids.ArtifactType is str
    assert ids.Checksum is str
    assert ids.Fingerprint is str
    assert ids.RunURI is str
    assert ids.StageID is str


def test_ids_are_usable_as_string_aliases() -> None:
    assert isinstance("records", ids.RecordID)
    assert isinstance("resources", ids.ResourceKey)
    assert isinstance("codecs", ids.CodecKey)
    assert isinstance("artifact", ids.ArtifactID)
    assert isinstance("dataset", ids.ArtifactType)
    assert isinstance("run", ids.RunURI)
    assert isinstance("stage", ids.StageID)
    assert isinstance("abc", ids.Checksum)
    assert isinstance("def", ids.Fingerprint)


def test_ids_export_surface() -> None:
    assert ids.__all__ == [
        "ResourceType",
        "RecordID",
        "ResourceKey",
        "CodecKey",
        "ArtifactID",
        "ArtifactType",
        "Checksum",
        "Fingerprint",
        "RunURI",
        "StageID",
    ]

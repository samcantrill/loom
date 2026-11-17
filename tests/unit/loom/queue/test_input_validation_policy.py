"""Explicit publisher trust replaces traversal, not root or version checks."""

import hashlib
import pytest

from loom.queue.errors import QueueServiceError
from loom.queue import shared_execution as shared


def inputs(tmp_path, *, trusted=True):
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "frame.bin").write_bytes(b"payload")
    manifest = b'{"version":"fixture-v1"}\n'
    (tmp_path / "version.json").write_bytes(manifest)
    roots = shared.root_bindings({"data": {
        "host_path": str(tmp_path), "container_path": "/loom/data", "access": "ro",
        "qualification": {"kind": "input_directory"},
        **({"input_validation": {
            "policy": "trusted_immutable_dataset", "version": "fixture-v1",
            "manifest": {"path": "version.json", "sha256": hashlib.sha256(manifest).hexdigest()},
            "entry_points": ["clips", "version.json"],
        }} if trusted else {}),
    }})
    location = {"kind": "loom.shared-location", "schema_version": 1, "root_id": "data", "path": "clips"}
    required = {"capability": shared.SHARED_EXECUTION_CAPABILITY,
                "roots": shared.qualifications(roots), "locations": [location]}
    return roots, shared.scope(required)


def test_trusted_root_checks_identity_and_entries_without_walking_payload(tmp_path, monkeypatch):
    roots, required = inputs(tmp_path)
    monkeypatch.setattr(shared.os, "walk", lambda *_args, **_kwargs: pytest.fail("trusted input was traversed"))
    shared.require_bindings(required, roots)
    # The explicit policy trusts publisher immutability. It does not pretend
    # the version manifest is a fresh digest of every payload file.
    (tmp_path / "clips" / "frame.bin").write_bytes(b"changed by publisher")
    shared.require_bindings(required, roots)
    assert shared.scope(required) == required
    assert required["roots"]["data"]["input_validation"]["entry_points"] == ["clips", "version.json"]


@pytest.mark.parametrize("change", ["manifest", "manifest_link", "missing_entry", "missing_selection", "version"])
def test_trusted_root_rejects_changed_identity_or_unavailable_entry(tmp_path, change):
    roots, required = inputs(tmp_path)
    if change == "manifest":
        (tmp_path / "version.json").write_bytes(b"other version")
    elif change == "manifest_link":
        (tmp_path / "version.json").rename(tmp_path / "version-old.json")
        (tmp_path / "version.json").symlink_to("version-old.json")
    elif change == "missing_entry":
        (tmp_path / "clips").rename(tmp_path / "clips-old")
    elif change == "missing_selection":
        required["locations"][0]["path"] = "clips/missing"
    else:
        roots["data"]["input_validation"]["version"] = "fixture-v2"
    with pytest.raises(QueueServiceError):
        shared.require_bindings(required, roots)


def test_default_recursive_policy_still_checks_descendants(tmp_path):
    roots, required = inputs(tmp_path, trusted=False)
    (tmp_path / "clips" / "link").symlink_to("frame.bin")
    with pytest.raises(QueueServiceError, match="regular files"):
        shared.require_bindings(required, roots)


def test_input_policy_requires_read_only_directory_binding(tmp_path):
    roots, _ = inputs(tmp_path)
    roots["data"]["access"] = "rw"
    with pytest.raises(QueueServiceError, match="read-only"):
        shared.root_bindings(roots)


def test_container_projection_retains_exact_policy(tmp_path):
    roots, required = inputs(tmp_path)
    # The same version facts must qualify a relocated host or container mount.
    other = tmp_path / "other"
    other.mkdir()
    (other / "clips").mkdir()
    (other / "version.json").write_bytes((tmp_path / "version.json").read_bytes())
    roots["data"]["host_path"] = str(other)
    shared.require_bindings(required, roots)
    (other / "version.json").write_bytes(b"another mount")
    with pytest.raises(QueueServiceError, match="manifest"):
        shared.require_bindings(required, roots)


def test_manifest_larger_than_one_chunk_keeps_exact_digest(tmp_path):
    roots, _ = inputs(tmp_path)
    content = b"versioned-manifest\n" * 100000
    (tmp_path / "version.json").write_bytes(content)
    roots["data"]["input_validation"]["manifest"]["sha256"] = hashlib.sha256(content).hexdigest()
    required = shared.scope({"capability": shared.SHARED_EXECUTION_CAPABILITY,
        "roots": shared.qualifications(roots), "locations": []})
    shared.require_bindings(required, roots)

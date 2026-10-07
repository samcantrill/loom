"""Immutable release inputs, read-only refusal and profile selection."""

from __future__ import annotations

import hashlib
import json

import pytest

from loom.fleet.releases import verify_release
from loom.queue.errors import QueueConfigError, QueueConflictError
from tests.integration.fleet.test_configuration import cli, inventory, snapshot

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(root, *, wheel_bytes=b"synthetic wheel", label="service-1"):
    root.mkdir(exist_ok=True)
    wheels = root / "wheels"
    wheels.mkdir()
    wheel = wheels / "loom-0.1.0-py3-none-any.whl"
    wheel.write_bytes(wheel_bytes)
    requirements = root / "requirements.txt"
    requirements.write_text(
        f"loom[fleet]==0.1.0 \\\n    --hash=sha256:{digest(wheel)}\n"
    )
    manifest = root / "wheels.sha256"
    manifest.write_text(f"{digest(wheel)}  {wheel.name}\n")
    descriptor = root / "release.yaml"
    descriptor.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "loom.service-release",
                "release_id": label,
                "python": "3.12",
                "requirements": {
                    "path": requirements.name,
                    "sha256": digest(requirements),
                },
                "wheelhouse": {
                    "path": "wheels",
                    "manifest": manifest.name,
                    "sha256": digest(manifest),
                },
            }
        )
    )
    return descriptor


def test_valid_bundle_verifies_bytes_without_installation(tmp_path):
    path = bundle(tmp_path)
    before = snapshot(tmp_path)
    result = verify_release(path)
    assert result["release_id"] == "service-1"
    assert result["descriptor_sha256"] == digest(path)
    assert result["installed"] is False and result["wheel_count"] == 1
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "case",
    [
        "requirements",
        "wheel",
        "manifest",
        "python",
        "escape",
        "missing_wheel",
        "extra_wheel",
        "unhashed",
        "editable",
        "mutable_url",
    ],
)
def test_invalid_bundle_refuses_without_changing_selected_bytes(tmp_path, case):
    path = bundle(tmp_path)
    descriptor = json.loads(path.read_text())
    wheel = next((tmp_path / "wheels").iterdir())
    if case == "requirements":
        (tmp_path / "requirements.txt").write_text("changed")
    elif case == "wheel":
        wheel.write_bytes(b"changed")
    elif case == "manifest":
        (tmp_path / "wheels.sha256").write_text("changed")
    elif case == "python":
        descriptor["python"] = "3.13"
    elif case == "escape":
        descriptor["requirements"]["path"] = "../outside.txt"
    elif case == "missing_wheel":
        wheel.unlink()
    elif case == "extra_wheel":
        (wheel.parent / "unselected.whl").write_text("extra")
    else:
        text = {
            "unhashed": "loom[fleet]==0.1.0",
            "editable": "-e .",
            "mutable_url": "loom[fleet] @ https://invalid/loom.whl",
        }[case]
        (tmp_path / "requirements.txt").write_text(text)
        descriptor["requirements"]["sha256"] = digest(tmp_path / "requirements.txt")
    path.write_text(json.dumps(descriptor))
    before = snapshot(tmp_path)
    with pytest.raises((QueueConfigError, OSError)):
        verify_release(path)
    assert snapshot(tmp_path) == before


def test_same_label_changed_bytes_conflict_and_new_label_is_explicit(tmp_path):
    old = bundle(tmp_path / "old")
    changed = bundle(tmp_path / "new", wheel_bytes=b"other valid selected bytes")
    before = snapshot(tmp_path)
    with pytest.raises(QueueConflictError):
        verify_release(changed, previous=old)
    assert snapshot(tmp_path) == before
    descriptor = json.loads(changed.read_text())
    descriptor["release_id"] = "service-2"
    changed.write_text(json.dumps(descriptor))
    assert verify_release(changed, previous=old)["release_id"] == "service-2"
    assert verify_release(old)["release_id"] == "service-1"


def test_preflight_valid_local_bundle_is_incomplete_not_remote_qualification(tmp_path):
    path = inventory(tmp_path)
    bundle(tmp_path)
    code, result = cli(
        "preflight", "--fleet", path, "--hosts", "gpu01", "--profile", "remote-profile"
    )
    assert code == 3 and result["outcome"] == "incomplete"
    assert result["release"]["outcome"] == "passed"
    assert result["release"]["installed"] is False
    assert result["hosts"]["gpu01"]["installation"]["availability"] == "unavailable"
    assert (
        cli("preflight", "--fleet", path, "--hosts", "gpu01", "--profile", "unknown")[0]
        == 2
    )

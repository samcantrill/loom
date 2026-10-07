"""Immutable byte checks precede native candidate qualification/publication."""
import hashlib
from pathlib import Path

import pytest

from loom.fleet import _workload_host as host
from loom.queue.errors import QueueConflictError


def test_candidate_digest_mismatch_never_qualifies_or_publishes(tmp_path, monkeypatch):
    image = tmp_path / "candidate.sif"
    image.write_bytes(b"changed-image")
    original = {"resident_profiles": [{"descriptor": {"profile_id": "selected", "revision": "v1"},
        "container": {"kind": "apptainer", "container": {"image": {"reference": "/old.sif"}}}}]}
    monkeypatch.setattr(host, "payload", lambda _: original)
    monkeypatch.setattr(host, "qualify", lambda *a: pytest.fail("must check image before native qualification"))
    with pytest.raises(QueueConflictError, match="digest mismatch"):
        host.probe({"name": "agent", "workload_profile": "selected", "image": str(image), "image_sha256": "0" * 64})
    assert original["resident_profiles"][0]["descriptor"]["revision"] == "v1"


def test_candidate_keeps_old_source_and_uses_native_target_qualification(tmp_path, monkeypatch):
    image = tmp_path / "candidate.sif"
    image.write_bytes(b"candidate")
    sha = hashlib.sha256(image.read_bytes()).hexdigest()
    original = {"resident_profiles": [{"descriptor": {"profile_id": "selected", "revision": "v1"},
        "container": {"kind": "apptainer", "container": {"image": {"reference": "/old.sif"}}}}]}
    monkeypatch.setattr(host, "payload", lambda _: original)
    monkeypatch.setattr(host, "owner", lambda _: {"owner": "original-root"})
    observed = []
    def qualify(request, declaration):
        observed.append(declaration)
        return {"observed": len(observed)}
    monkeypatch.setattr(host, "qualify", qualify)
    result = host.probe({"name": "agent", "workload_profile": "selected", "image": str(image), "image_sha256": sha})
    assert result["source"] == {"observed": 1}
    assert result["target"] == {"observed": 2}
    assert observed[0] == original
    assert result["declaration"]["resident_profiles"][0]["descriptor"]["revision"] == "image-" + sha[:24]
    assert Path(result["declaration"]["resident_profiles"][0]["container"]["container"]["image"]["reference"]) == image
    assert original["resident_profiles"][0]["descriptor"]["revision"] == "v1"

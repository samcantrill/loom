from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from loom.pipeline.status import StageStatus
from loom.queue._remote_stage_execution import (
    MAX_TRANSFER_BYTES,
    _RemoteExecutionReport,
    _RemoteOutputArtifact,
)
from loom.queue._slurm_result_transport import SharedSlurmResult
from loom.queue.errors import QueueConflictError, QueueServiceError
import loom.queue._slurm_result_transport as transport_module


def _fixture(tmp_path, data=b"result"):
    storage = {
        "agent_root": str(tmp_path),
        "compute_root": str(tmp_path),
        "retention_bytes": 65 * 1024 * 1024,
    }
    identity = {
        "coordinator_id": "coordinator",
        "assignment": {
            "assignment_id": "assignment-1",
            "agent_id": "agent",
            "agent_root_id": "agent-root",
            "attempt_id": "attempt",
            "operation_id": "operation",
        },
        "fence": "fence",
        "incarnation": "bootstrap",
    }
    artifact = _RemoteOutputArtifact(
        "output-1",
        "data",
        hashlib.sha256(data).hexdigest(),
        len(data),
        "artifact",
        "bytes",
        None,
        1,
        None,
        "stage",
        "2026-09-13T00:00:00+00:00",
        {},
    )
    report = _RemoteExecutionReport(
        "assignment-1",
        "stage",
        1,
        StageStatus.SUCCEEDED,
        "2026-09-13T00:00:00+00:00",
        "2026-09-13T00:00:01+00:00",
        "local",
        (artifact,),
        process_created=True,
        schema_version=3,
        executor_metadata={"container_runtime": "apptainer"},
    )
    owner = SharedSlurmResult(storage, "assignment-1")
    owner.reserve(identity["assignment"])

    def chunk(_transfer, offset):
        value = data[offset : offset + transport_module.TRANSFER_CHUNK_BYTES]
        return value, offset + len(value) == len(data)

    return owner, identity, report, chunk


def test_manifest_last_partial_copy_and_lost_ack_preserve_bytes(tmp_path, monkeypatch):
    owner, identity, report, chunk = _fixture(tmp_path)
    atomic = transport_module._atomic_regular_file

    def crash(path, data):
        if path.name == "manifest.json":
            raise OSError("compute stopped before manifest")
        atomic(path, data)

    monkeypatch.setattr(transport_module, "_atomic_regular_file", crash)
    with pytest.raises(OSError):
        owner.publish(identity, report, chunk)
    assert not owner.deliver(
        identity, lambda _: pytest.fail("partial result delivered")
    )
    assert (owner.path / "outputs/output-1").read_bytes() == b"result"
    monkeypatch.setattr(transport_module, "_atomic_regular_file", atomic)
    owner.publish(identity, report, chunk)
    committed = []

    def relay(value):
        if value["result_operation"] == "commit":
            committed.append(value["identity"])
            if len(committed) == 1:
                raise OSError("commit acknowledgement lost")
            return {"acknowledged": True}
        if value["result_operation"] == "output":
            return {"received": 6}
        assert (
            value["report"]["executor_metadata"]
            == report.to_dict()["executor_metadata"]
        )
        return {"accepted": True}

    with pytest.raises(OSError):
        owner.deliver(identity, relay)
    assert owner.path.exists()
    reopened = SharedSlurmResult(owner.storage, owner.assignment_id)
    assert reopened.deliver(identity, relay)
    assert committed == [identity, identity]
    assert not owner.path.exists()


@pytest.mark.parametrize(
    "damage",
    ["fence", "agent", "digest", "traversal", "symlink", "directory", "partial"],
)
def test_untrusted_shared_evidence_cannot_deliver_or_cleanup(tmp_path, damage):
    owner, identity, report, chunk = _fixture(tmp_path)
    owner.publish(identity, report, chunk)
    manifest_path = owner.path / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if damage == "fence":
        manifest["identity"]["fence"] = "old"
    elif damage == "agent":
        manifest["identity"]["assignment"]["agent_id"] = "foreign"
    elif damage == "digest":
        (owner.path / "outputs/output-1").write_bytes(b"corrupt")
    elif damage == "traversal":
        manifest["report"]["path"] = "../report.json"
    elif damage in {"symlink", "directory"}:
        target = owner.path / "outputs/output-1"
        target.unlink()
        if damage == "symlink":
            other = tmp_path / "foreign"
            other.write_bytes(b"result")
            target.symlink_to(other)
        else:
            target.mkdir()
    manifest_path.write_text("{" if damage == "partial" else json.dumps(manifest))
    with pytest.raises(QueueConflictError):
        owner.deliver(identity, lambda _: pytest.fail("invalid result delivered"))
    assert manifest_path.exists()
    assert (owner.path / "delivery-failure.json").exists()


def test_retention_quota_never_evicts_unacknowledged_attempt(tmp_path):
    owner, identity, report, chunk = _fixture(tmp_path)
    owner.publish(identity, report, chunk)
    other = SharedSlurmResult(owner.storage, "assignment-2")
    with pytest.raises(QueueServiceError, match="quota exhausted"):
        other.reserve({"assignment_id": "assignment-2"})
    assert owner.read(identity)[0] == report


def test_existing_aggregate_artifact_bound_at_and_over_limit(tmp_path):
    data = b"x" * MAX_TRANSFER_BYTES
    owner, identity, report, chunk = _fixture(tmp_path, data)
    owner.publish(identity, report, chunk)
    assert owner.read(identity)[1]["output-1"] == data
    extra = replace(
        report.outputs[0], transfer_id="output-2", logical_name="other", size_bytes=1
    )
    with pytest.raises(QueueServiceError):
        replace(report, outputs=(*report.outputs, extra))

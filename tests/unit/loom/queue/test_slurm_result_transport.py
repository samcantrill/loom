from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from loom.pipeline.status import StageStatus
from loom.serialization import freeze_plain_data, thaw_plain_data
from loom.queue._remote_stage_execution import (
    MAX_TRANSFER_BYTES,
    _RemoteExecutionReport,
    _RemoteOutputArtifact,
)
from loom.queue._slurm_result_transport import SharedSlurmResult, SlurmTransportPending
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
            "profile_descriptor": {"supported_data_versions": [1]},
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
        schema_version=6,
        executor_metadata={"container_runtime": "apptainer"},
    )
    owner = SharedSlurmResult(storage, "assignment-1")
    owner.reserve(identity["assignment"])

    def chunk(_transfer, offset):
        value = data[offset : offset + transport_module.TRANSFER_CHUNK_BYTES]
        return value, offset + len(value) == len(data)

    return owner, identity, report, chunk


def test_authenticated_frozen_identity_delivers_with_exact_plain_receipt(tmp_path):
    owner, identity, report, chunk = _fixture(tmp_path)
    owner.publish(identity, report, chunk)
    received = freeze_plain_data(identity)
    assert received != identity  # The real descriptor array becomes a tuple.
    assert owner.read(received)[0] == report
    operations = []

    def coordinator(value):
        # Exercise the real JSON encode/decode boundary before authenticated
        # decoding freezes the receiving coordinator's payload again.
        evidence = freeze_plain_data(json.loads(json.dumps(value, allow_nan=False)))
        transport_module.validate_identity(evidence["identity"], identity)
        operations.append(evidence["result_operation"])
        if evidence["result_operation"] == "output":
            return {"received": 6}
        return {"acknowledged": True}

    changed = thaw_plain_data(received)
    changed["assignment"]["profile_descriptor"]["supported_data_versions"] = [2]
    with pytest.raises(QueueConflictError, match="retained result is invalid"):
        owner.deliver(freeze_plain_data(changed), coordinator)
    assert not operations and owner.path.exists()
    assert owner.deliver(received, coordinator)
    assert operations == ["report", "output", "commit"]
    assert not owner.path.exists()
    # A restart may only retain the pending commit, after byte cleanup.
    assert owner.finish_delivery(received, coordinator)
    assert operations[-1] == "commit"


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
    with pytest.raises(SlurmTransportPending, match="result_transport_capacity"):
        other.reserve({"assignment_id": "assignment-2"})
    assert owner.read(identity)[0] == report
    assert transport_module.result_transport_capacity(other.storage) == {
        "capacity_bytes": 65 * 1024**2,
        "reservation_bytes_per_attempt": 65 * 1024**2,
        "maximum_outstanding_reservations": 1,
    }
    # Capacity deferral does not weaken exact replay checks.
    with pytest.raises(QueueConflictError, match="reservation conflicts"):
        owner.reserve({"assignment_id": "different"})
    owner.finish_delivery(identity, lambda _: {"acknowledged": True})
    other.reserve({"assignment_id": "assignment-2"})
    assert other.path.is_dir()


def test_contended_quota_lock_yields_and_preserves_existing_reservation(tmp_path):
    import fcntl

    owner, identity, report, chunk = _fixture(tmp_path)
    owner.publish(identity, report, chunk)
    with (tmp_path / ".retention.lock").open("rb") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with pytest.raises(SlurmTransportPending, match="result_quota_lock_busy"):
            owner.reserve(identity["assignment"])
        with pytest.raises(SlurmTransportPending, match="result_quota_lock_busy"):
            owner.finish_delivery(identity, lambda _: {"acknowledged": True})
        assert owner.read(identity)[0] == report
    assert owner.finish_delivery(identity, lambda _: {"acknowledged": True})


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


def test_pending_commit_preserves_transport_until_exact_replay(tmp_path):
    owner, identity, report, chunk = _fixture(tmp_path)
    owner.publish(identity, report, chunk)
    pending = {
        "assignment_id": owner.assignment_id,
        "identity": freeze_plain_data(identity),
        "result_operation": "commit",
        "disposition": "pending",
        "retry_after_seconds": 5,
    }
    with pytest.raises(transport_module.SlurmEffectPending):
        owner.finish_delivery(identity, lambda _: pending)
    assert owner.read(identity)[0] == report
    reopened = SharedSlurmResult(owner.storage, owner.assignment_id)
    assert reopened.finish_delivery(identity, lambda _: {
        "disposition": "applied", "acknowledged": True,
    })
    assert not owner.path.exists()


@pytest.mark.parametrize("change", [
    {"assignment_id": "different"},
    {"identity": {}},
    {"result_operation": "report"},
    {"acknowledged": True},
    {"retry_after_seconds": True},
    {"retry_after_seconds": float("nan")},
    {"disposition": "unknown"},
])
def test_conflicting_pending_commit_never_cleans_transport(tmp_path, change):
    owner, identity, report, chunk = _fixture(tmp_path)
    owner.publish(identity, report, chunk)
    response = {
        "assignment_id": owner.assignment_id,
        "identity": identity,
        "result_operation": "commit",
        "disposition": "pending",
        "retry_after_seconds": 5,
        **change,
    }
    with pytest.raises(QueueConflictError):
        owner.finish_delivery(identity, lambda _: response)
    assert owner.read(identity)[0] == report

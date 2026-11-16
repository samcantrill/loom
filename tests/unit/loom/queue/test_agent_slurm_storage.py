"""Filesystem stalls and reply loss must yield finite, replayable result turns."""

import base64
import hashlib
from threading import Event
from time import monotonic, sleep

import pytest

from loom.queue._agent_slurm_storage import SlurmStorageProgress
from loom.queue._slurm_result_transport import SlurmEffectPending, SlurmRequestUncertain
from tests.unit.loom.queue.test_slurm_result_transport import _fixture


def drive_until(action, complete, *, seconds=5):
    deadline = monotonic() + seconds
    while not complete():
        assert monotonic() < deadline, "result progress did not settle"
        try:
            action()
        except SlurmEffectPending:
            pass
        sleep(0.005)


def test_blocked_storage_is_deduplicated_and_capacity_remains_bounded():
    owner = SlurmStorageProgress(workers=1, outstanding=2, owners=2)
    entered, release = Event(), Event()
    calls = []

    def blocked():
        calls.append("read")
        entered.set()
        assert release.wait(5)
        return "result"

    try:
        with pytest.raises(SlurmEffectPending):
            owner.poll("A", "read", blocked)
        assert entered.wait(1)
        for _ in range(20):
            with pytest.raises(SlurmEffectPending):
                owner.poll("A", "read", blocked)
        with pytest.raises(SlurmEffectPending):
            owner.poll("B", "read", lambda: "peer")
        with pytest.raises(SlurmEffectPending):
            owner.poll("C", "read", lambda: pytest.fail("capacity was exceeded"))
        assert calls == ["read"]
        release.set()
        values = []
        drive_until(lambda: values.append(owner.poll("A", "read", blocked)), lambda: bool(values))
        assert values == ["result"]
    finally:
        release.set()
        owner.close()


@pytest.mark.parametrize("restart", [False, True])
def test_chunk_reply_loss_replays_exact_bytes_and_receiver_offset(tmp_path, restart):
    from loom.queue._remote_stage_execution import TRANSFER_CHUNK_BYTES

    data = b"x" * (TRANSFER_CHUNK_BYTES * 3 + 17)
    transport, identity, report, output = _fixture(tmp_path, data)
    transport.publish(identity, report, output)
    owner = SlurmStorageProgress()
    received = bytearray()
    lost = False
    requests = []
    committed = False

    def call(value):
        nonlocal lost, committed
        requests.append(value)
        if value["result_operation"] == "output":
            chunk = base64.b64decode(value["data"])
            assert len(chunk) <= TRANSFER_CHUNK_BYTES
            offset = value["offset"]
            if offset < len(received):
                assert received[offset:offset + len(chunk)] == chunk
            else:
                assert offset == len(received)
                received.extend(chunk)
            if not lost:
                lost = True
                raise SlurmRequestUncertain("reply lost after receiver persistence")
            return {"received": len(received)}
        if value["result_operation"] == "commit":
            assert hashlib.sha256(received).hexdigest() == report.outputs[0].digest
            committed = True
        return {"acknowledged": True}

    try:
        with pytest.raises(SlurmRequestUncertain):
            drive_until(lambda: owner.advance(transport, identity, call), lambda: lost)
        assert transport.path.exists() and not committed
        if restart:
            owner.close()
            owner = SlurmStorageProgress()

        def turn():
            before = len(requests)
            owner.advance(transport, identity, call)
            assert len(requests) - before <= 1

        drive_until(turn, lambda: not transport.path.exists())
        assert committed and bytes(received) == data
        outputs = [value for value in requests if value["result_operation"] == "output"]
        assert outputs[0] == outputs[1]
    finally:
        owner.close()


def test_cleanup_waits_for_commit_and_does_not_block_other_storage(tmp_path, monkeypatch):
    from loom.queue._slurm_result_transport import SharedSlurmResult

    transport, identity, report, output = _fixture(tmp_path)
    transport.publish(identity, report, output)
    owner = SlurmStorageProgress()
    entered, release = Event(), Event()
    cleanup = SharedSlurmResult.cleanup
    committed = False

    def slow_cleanup(value):
        assert committed
        entered.set()
        assert release.wait(5)
        cleanup(value)

    monkeypatch.setattr(SharedSlurmResult, "cleanup", slow_cleanup)

    def call(value):
        nonlocal committed
        if value["result_operation"] == "output":
            return {"received": 6}
        if value["result_operation"] == "commit":
            committed = True
        return {"acknowledged": True}

    try:
        drive_until(lambda: owner.advance(transport, identity, call), entered.is_set)
        assert transport.path.exists()
        results = []
        drive_until(lambda: results.append(owner.poll("peer", "read", lambda: "ready")), lambda: bool(results))
        assert results == ["ready"] and not release.is_set()
        release.set()
        drive_until(lambda: owner.advance(transport, identity, call), lambda: not transport.path.exists())
    finally:
        release.set()
        owner.close()

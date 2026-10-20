"""Append-only timing diagnostics preserve operation outcomes and isolation."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import json
from types import SimpleNamespace

import pytest

from loom.fleet import _timing
from loom.fleet import ssh_operations


def test_diagnostics_append_across_continuations_and_retain_outcomes(tmp_path, monkeypatch):
    now = [10.0]
    monkeypatch.setattr(_timing.time, "monotonic", lambda: now[0])
    for outcome in ("waiting", "complete"):
        with _timing.recording():
            _timing.bind_directory(tmp_path)
            with _timing.measure("upgrade_continuation") as timing:
                now[0] += 3
                timing["outcome"] = outcome
    records = [json.loads(row) for row in (tmp_path / "timings.jsonl").read_text().splitlines()]
    assert [r["outcome"] for r in records] == ["waiting", "complete"]
    assert [r["elapsed_seconds"] for r in records] == [3, 3]
    assert len({r["invocation"] for r in records}) == 2
    assert (tmp_path / "timings.jsonl").stat().st_mode & 0o077 == 0


def test_timing_write_failure_cannot_fail_successful_operation(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("diagnostics volume unavailable")
    monkeypatch.setattr(_timing.os, "open", unavailable)
    with _timing.recording():
        _timing.bind_directory(tmp_path)
        with _timing.measure("candidate_qualification"):
            result = "qualified"
    assert result == "qualified"


def test_failed_action_keeps_original_exception_and_records_elapsed(tmp_path):
    error = ValueError("real candidate failure")
    with pytest.raises(ValueError) as raised, _timing.recording():
        _timing.bind_directory(tmp_path)
        with _timing.measure("candidate_qualification"):
            raise error
    assert raised.value is error
    record = json.loads((tmp_path / "timings.jsonl").read_text())
    assert record["outcome"] == "error"
    assert "real candidate failure" not in json.dumps(record)


def test_worker_contexts_join_one_trace_and_remote_records_are_bounded(tmp_path):
    def work():
        with _timing.measure("check_observation"):
            pass
    with _timing.recording():
        _timing.bind_directory(tmp_path)
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(copy_context().run, work) for _ in range(9)]
            for future in futures:
                future.result()
        remote = {"action": "image_hash", "started_at": "2026-10-19T00:00:00+00:00",
                  "elapsed_seconds": 2.0, "outcome": "complete", "host": None}
        _timing.ingest([remote, {**remote, "secret": "not allowed"},
                        {**remote, "elapsed_seconds": float("nan")}], host="worker")
    rows = [json.loads(row) for row in (tmp_path / "timings.jsonl").read_text().splitlines()]
    assert len(rows) == 10
    assert len({r["invocation"] for r in rows}) == 1
    assert rows[-1]["host"] == "worker"


@pytest.mark.parametrize("failed", [False, True])
def test_rpc_keeps_aggregate_and_classifies_host_action_without_payload(monkeypatch, failed):
    def transport(*args, **kwargs):
        if failed:
            raise OSError("transport unavailable")
        return SimpleNamespace(returncode=0, stdout=b'{"ok": true, "result": {}}')

    monkeypatch.setattr(ssh_operations.subprocess, "run", transport)
    with _timing.recording() as trace:
        for host, action in (("host-a", "workload-probe"), ("host-b", "inspect")):
            request = {"action": action, "private_key": "never-record-this"}
            if failed:
                with pytest.raises(ssh_operations.SshUnavailable):
                    ssh_operations.ssh(host, request)
            else:
                assert ssh_operations.ssh(host, request) == {}
    assert [(r["host"], r["action"]) for r in trace.records] == [
        ("host-a", "rpc_workload-probe"), ("host-a", "host_rpc"),
        ("host-b", "rpc_inspect"), ("host-b", "host_rpc"),
    ]
    assert {r["outcome"] for r in trace.records} == {"error" if failed else "complete"}
    assert "never-record-this" not in json.dumps(trace.records)

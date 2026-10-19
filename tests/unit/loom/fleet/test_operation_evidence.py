"""Operator reports read native evidence without managing its private layout."""

import json

import pytest

from loom.fleet.configuration import Inventory
from loom.fleet.ssh_operations import operation_evidence, operation_status
from loom.queue.errors import QueueConfigError


def test_missing_operation_status_remains_strict_unless_requested(tmp_path):
    inventory = Inventory(
        tmp_path / "fleet.json", "lab", tmp_path / "release", "tmux", ()
    )
    assert operation_status(inventory, "new", missing_ok=True) is None
    with pytest.raises(QueueConfigError, match="unknown administrative"):
        operation_status(inventory, "new")
    with pytest.raises(QueueConfigError, match="simple identifier"):
        operation_status(inventory, "../outside", missing_ok=True)
    with pytest.raises(QueueConfigError, match="simple identifier"):
        operation_evidence(inventory, "../outside")
    assert not list(tmp_path.iterdir())


def test_evidence_keeps_partial_timings_and_all_check_attempts_without_writes(tmp_path):
    inventory = Inventory(
        tmp_path / "fleet.json", "lab", tmp_path / "release", "tmux", ()
    )
    root = tmp_path / "operations" / "upgrade"
    root.mkdir(parents=True)
    (root / "intent.json").write_text('{"kind":"runtime-upgrade"}')
    timing = {"action": "rpc_inspect", "host": "one", "elapsed_seconds": 2}
    (root / "timings.jsonl").write_text(json.dumps(timing) + '\n{"interrupted":')
    (root / "checks.json").write_text(
        json.dumps(
            {
                "one:cpu": [
                    {"operation_id": "failed"},
                    {"operation_id": "retry"},
                    {"operation_id": "pending"},
                ]
            }
        )
    )
    for identity, outcome in (("failed", "failed"), ("retry", "passed")):
        path = tmp_path / "checks" / identity / "result.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"outcome": outcome}))
    close = root / "steps" / "close" / "receipt.json"
    close.parent.mkdir(parents=True)
    close.write_text('{"applied_at":"2026-10-19T00:00:00Z"}')
    for path in tmp_path.rglob("*"):
        if path.is_file():
            path.chmod(0o600)
    before = {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    evidence = operation_evidence(inventory, "upgrade")
    assert evidence["timings"] == [timing]
    assert evidence["checks"] == {
        "failed": {"outcome": "failed"},
        "retry": {"outcome": "passed"},
    }
    assert evidence["maintenance"] == {"close": {"applied_at": "2026-10-19T00:00:00Z"}}
    assert evidence["issues"] == [
        {"source": str(root / "timings.jsonl"), "reason": "invalid_or_partial_line"}
    ]
    assert (
        operation_status(inventory, "upgrade", missing_ok=True)["outcome"] == "pending"
    )
    assert before == {
        p: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in tmp_path.rglob("*")
        if p.is_file()
    }

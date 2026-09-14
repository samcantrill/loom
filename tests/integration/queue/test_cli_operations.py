"""Integration coverage for queue CLI-backed operations."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from loom.cli.main import main
from loom.queue import (
    LocalDaemonSocketClient,
    ManagedRecoveryTarget,
    RecoverUnknownAssignment,
)


pytestmark = pytest.mark.optional_dependency


def test_guarded_recovery_cli_parses_the_exact_request_and_delegates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = RecoverUnknownAssignment(
        recovery_id="recover-from-cli",
        run_uri="file:///run",
        stage_name="train",
        attempt=1,
        stage_work_id="work-1",
        assignment_id="assignment-1",
        process_execution_id="process-1",
        execution_fence="fence-1",
        target=ManagedRecoveryTarget("agent-a", "session-a"),
        expected_state_version=7,
        requested_outcome="failed",
        consider_retry=True,
        reason="operator verified containment",
    )
    request_path = tmp_path / "recovery.json"
    request_path.write_text(json.dumps(request.to_dict()), encoding="utf-8")
    received: list[RecoverUnknownAssignment] = []

    def recover_unknown(
        _client: LocalDaemonSocketClient, candidate: RecoverUnknownAssignment
    ) -> dict[str, object]:
        received.append(candidate)
        return {
            "recovery_id": candidate.recovery_id,
            "state": "closed",
            "evidence": "TEST_CONTAINMENT",
        }

    monkeypatch.setattr(LocalDaemonSocketClient, "recover_unknown", recover_unknown)
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert (
        main(
            [
                "queue",
                "daemon-recover-unknown",
                "--endpoint",
                str(tmp_path / "daemon.sock"),
                "--request",
                str(request_path),
                "--format",
                "json",
            ],
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )

    assert stderr.getvalue() == ""
    assert received == [request]
    envelope = json.loads(stdout.getvalue())
    assert envelope["result"]["recovery_id"] == request.recovery_id
    assert envelope["result"]["state"] == "closed"

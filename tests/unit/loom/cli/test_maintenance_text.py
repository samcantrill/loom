"""Maintenance observations in the operator CLI."""

import json

import pytest

from loom.cli.main import main
from loom.coordinator import CoordinatorOperatorClient


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("state", "settled", "reasons"),
    [
        ("open", True, []),
        ("closed", True, []),
        (
            "closed",
            False,
            [
                "accepted_work_or_preparation",
                "assignment_publication_or_claim_release",
                "agent_control_settlement",
                "coordinator_reconciliation_unavailable",
                "additional_native_reason",
            ],
        ),
    ],
)
def test_maintenance_observation_text_and_json(
    monkeypatch, capsys, state, settled, reasons
):
    maintenance_id = "pos-runtime-upgrade" if state == "closed" else None
    gate = {
        "state": state,
        "settled": settled,
        "wait_reasons": reasons,
        "maintenance_id": maintenance_id,
        "intent_digest": "window-intent" if maintenance_id else None,
        "revision": 3,
        "checks": {},
        "coordinator_id": "native",
        "owner": "native",
        "observed_at": "2026-10-19T00:03:00Z",
        "freshness": "current",
        "availability": "available",
    }
    monkeypatch.setattr(
        CoordinatorOperatorClient, "observe_maintenance", lambda self: gate
    )
    monkeypatch.setenv("COLUMNS", "80")
    argv = ["queue", "daemon-maintenance", "--endpoint", "/unused/socket"]
    assert main(argv) == 0
    header, row, *waiting = capsys.readouterr().out.splitlines()
    assert header.split("  ") == ["ADMISSION", "SETTLED", "MAINTENANCE ID"]
    assert row.split() == [state, "yes" if settled else "no", maintenance_id or "—"]
    assert waiting == (
        []
        if settled
        else [
            "",
            "Waiting for:",
            "  • Accepted work or preparation to finish",
            "  • Assignment publication or claim release",
            "  • Agent controls to settle",
            "  • Coordinator reconciliation to become available",
            "  • additional_native_reason",
        ]
    )
    assert main([*argv, "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == gate

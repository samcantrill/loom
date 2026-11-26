"""Terminal views use the same coordinator read and preserve observation boundaries."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from loom.cli.main import main
from loom.coordinator import CoordinatorClient
from loom.queue.errors import QueueServiceError

pytestmark = pytest.mark.unit


def invoke(*argv):
    output, error = io.StringIO(), io.StringIO()
    code = main([*argv, "--endpoint", "/unused/socket"], stdout=output, stderr=error)
    return code, output.getvalue(), error.getvalue()


def test_queue_page_layout_does_not_change_selection(monkeypatch):
    when = "2026-06-05T12:00:00Z"
    item = "experiment-" + "p" * 75 + "-017"
    identity = "coordinator:admission:" + "a" * 80
    reason = (
        "the selected worker has no remaining capacity in the requested execution pool"
    )
    admission = dict(
        admission_id=identity,
        queue_item_id=item,
        admitted_by=None,
        state="CANCELLATION_REQUESTED",
        accepted_at=when,
        blocked_reason=reason,
        run_priority=0,
        enqueue_sequence=17,
    )
    page = dict(
        as_of="2026-06-05T12:18:42Z",
        next_cursor="page-after-017",
        admissions=[admission],
    )
    calls = []

    def read(client, **kwargs):
        calls.append(kwargs)
        return page

    monkeypatch.setattr(CoordinatorClient, "list_queue", read)
    monkeypatch.setenv("COLUMNS", "80")
    code, narrow, error = invoke("queue", "list", "--all", "--limit", "3")
    assert code == 0 and error == ""
    lines = narrow.splitlines()
    assert lines[0].split() == ["STATE", "AGE", "PRINCIPAL", "QUEUE", "ITEM", "REASON"]
    assert "CANCELLATION_REQUESTED" in lines[1] and "017" in lines[1]
    assert "18m42s" in lines[1] and "unknown" in lines[1]
    assert " ".join(" ".join(lines[2:-1]).split()) == f"Reason: {reason}"
    assert (
        lines[-1] == "Continue with --cursor page-after-017"
        and max(map(len, lines)) <= 80
    )
    assert identity not in narrow
    code, wide, error = invoke("queue", "list", "--all", "--limit", "3", "--wide")
    assert (
        code == 0
        and error == ""
        and identity in wide
        and when in wide
        and item in wide
        and reason in wide
    )
    code, raw, error = invoke(
        "queue", "list", "--all", "--limit", "3", "--format", "json"
    )
    assert code == 0 and error == "" and json.loads(raw)["result"] == page
    monkeypatch.setenv("COLUMNS", "32")
    code, small, error = invoke("queue", "list", "--all", "--limit", "3")
    assert code == 0 and error == "" and "STATE: CANCELLATION_REQUESTED" in small
    assert "QUEUE ITEM: experiment-" in small and "PRINCIPAL: unknown" in small
    monkeypatch.setenv("COLUMNS", "240")
    code, spacious, error = invoke("queue", "list", "--all", "--limit", "3")
    assert code == 0 and error == "" and item in spacious and reason in spacious
    assert all(call == calls[0] for call in calls)


def test_empty_queue_and_failed_queue_read_are_distinct(monkeypatch):
    monkeypatch.setattr(
        CoordinatorClient,
        "list_queue",
        lambda self, **kwargs: {
            "admissions": [],
            "next_cursor": None,
            "as_of": "2026-06-05T12:00:00Z",
        },
    )
    assert invoke("queue", "list") == (0, "No matching admissions.\n", "")

    def unavailable(self, **kwargs):
        raise QueueServiceError("observation deadline exceeded")

    monkeypatch.setattr(CoordinatorClient, "list_queue", unavailable)
    code, output, error = invoke("queue", "list")
    assert code and output == "" and "deadline exceeded" in error


def test_agent_capacity_uses_resource_observations(monkeypatch):
    resource = dict(
        resource_kind="gpu",
        local_capacity_key="device-0",
        available=False,
        reason_code="external_process_detected",
        observed_at="2026-06-05T12:00:00Z",
    )
    agent = dict(
        agent_id="machine",
        session_id="session-a",
        state="ACTIVE",
        available=True,
        pools=["resident"],
        resource_status=[resource],
    )
    monkeypatch.setattr(
        CoordinatorClient,
        "agents",
        lambda *a, **kw: SimpleNamespace(
            to_dict=lambda: {"agents": [agent], "next_cursor": None}
        ),
    )
    monkeypatch.setattr(
        CoordinatorClient, "agent", lambda *a, **kw: SimpleNamespace(to_dict=lambda: agent)
    )
    code, text, _ = invoke("queue", "daemon-agents")
    assert code == 0 and "CPU CAPACITY" in text and "GPU CAPACITY" in text
    assert text.splitlines()[1].split()[:6] == [
        "machine",
        "ACTIVE",
        "yes",
        "unknown",
        "occupied",
        "resident",
    ]
    code, detail, _ = invoke("queue", "daemon-agent", "machine")
    assert (
        code == 0
        and "device-0" in detail
        and "external_process_detected" in detail
        and "OBS AGE" in detail
    )
    resource["reason_code"] = "observation_stale"
    assert invoke("queue", "daemon-agents")[1].splitlines()[1].split()[4] == "unknown"


def test_job_search_preserves_unavailable_evidence_partial_coverage_and_cursor(
    monkeypatch,
):
    page = {
        "items": [
            {
                "identity": "admission-54",
                "native": {"queue_item_id": "item-54", "state": "ACTIVE"},
                "sources": {
                    "job_associations": {
                        "assignment": {
                            "availability": "available",
                            "assignments": [{"state": "delivered"}],
                        },
                        "execution": {"availability": "unavailable", "journal": []},
                        "slurm": {
                            "availability": "available",
                            "assignments": [
                                {"submission": {"scheduler_state": "PENDING"}}
                            ],
                        },
                    }
                },
            }
        ],
        "coverage": {"complete": False},
        "examined": 3,
        "warnings": [
            {"code": "job_observation_deadline", "admission_id": "admission-55"}
        ],
        "next_cursor": "continue-after-54",
    }
    monkeypatch.setattr(
        CoordinatorClient,
        "_native_call",
        lambda *a, **kw: SimpleNamespace(to_dict=lambda: page),
    )
    code, text, error = invoke("runs", "jobs")
    assert code == 0 and error == ""
    assert text.splitlines()[1].split() == [
        "admission-54",
        "item-54",
        "ACTIVE",
        "delivered",
        "unavailable",
        "PENDING",
    ]
    assert "Coverage incomplete (3 candidates examined)" in text
    assert "job_observation_deadline (admission_id=admission-55)" in text
    assert "--cursor continue-after-54" in text
    assert json.loads(invoke("runs", "jobs", "--format", "json")[1])["result"] == page
    page["items"] = []
    assert "No jobs returned on this page." in invoke("runs", "jobs")[1]


@pytest.mark.parametrize(
    ("action", "native", "identity", "expected"),
    [
        (
            "submissions",
            {
                "principal_id": "a",
                "accepted_at": "2026-05-07T00:00:00Z",
                "state": "applied",
            },
            "id-17",
            "id-17 a 2026-05-07T00:00:00Z applied",
        ),
        (
            "search",
            {
                "principal_id": "a",
                "status": "RUNNING",
                "created_at": "2026-05-07T00:00:00Z",
            },
            "file:///run",
            "file:///run RUNNING a 2026-05-07T00:00:00Z",
        ),
    ],
)
def test_discovery_identity_and_state(monkeypatch, action, native, identity, expected):
    page = {"items": [{"native": native, "identity": identity}]}
    monkeypatch.setattr(
        CoordinatorClient,
        "_native_call",
        lambda *a, **kw: SimpleNamespace(to_dict=lambda: page),
    )
    code, text, error = invoke("runs", action)
    assert code == 0 and error == ""
    assert " ".join(text.splitlines()[1].split()) == expected


def test_observed_coordinator_and_assignment_have_separate_reported_states(monkeypatch):
    from loom.coordinator import CoordinatorOperatorClient

    status = {
        "coordinator_id": "fleet",
        "service_health": "degraded",
        "scheduling_ready": False,
        "active_admissions": 2,
        "waiting_admissions": 11,
        "running_assignments": 1,
        "service_diagnostic": "owner_status_unavailable",
        "as_of": "2026-06-05T12:00:00Z",
    }
    monkeypatch.setattr(
        CoordinatorClient, "status", lambda *a: SimpleNamespace(to_dict=lambda: status)
    )
    code, text, error = invoke("queue", "daemon-status")
    assert code == 0 and not error
    assert text.splitlines()[1].split() == [
        "fleet",
        "degraded",
        "unready",
        "2",
        "11",
        "1",
    ]
    assert "owner_status_unavailable" in text and status["as_of"] in text
    result = dict(
        availability="available",
        freshness="current",
        observed_at=status["as_of"],
        value=dict(
            assignment_id="assignment-a",
            coordinator_state="settling",
            remote_state="TERMINAL",
            released=False,
            release_proof=None,
            result_progress={"worker_execution": "succeeded"},
        ),
    )
    monkeypatch.setattr(
        CoordinatorOperatorClient,
        "observe_assignment",
        lambda *a: SimpleNamespace(to_dict=lambda: result),
    )
    code, text, error = invoke("queue", "daemon-assignment", "assignment-a")
    assert code == 0 and not error
    assert text.startswith("Assignment assignment-a: settling")
    assert (
        "remote state: TERMINAL" in text
        and "released: no" in text
        and "worker execution: succeeded" in text
    )


def test_output_metadata_and_partial_lineage_edges(monkeypatch):
    run = "file:///run"
    start, end = ({"run_uri": run, "stage_name": stage} for stage in ("first", "next"))
    pages = {
        "trace_lineage": {
            "items": [
                {
                    "kind": "edge",
                    "source": start,
                    "target": end,
                    "relation": "declared_dependency",
                }
            ],
            "next_cursor": "line-1",
        },
        "select_outputs": {
            "items": [
                {
                    "outcome": "selected",
                    "matched_run_uri": run,
                    "matched_stage_name": "first",
                    "locator": {"output_name": "signal"},
                    "artifact": {"artifact_type": "json", "artifact_id": "out-1"},
                    "availability": "not_checked",
                }
            ]
        },
    }
    monkeypatch.setattr(
        CoordinatorClient,
        "_native_call",
        lambda self, op, *a, **kw: SimpleNamespace(to_dict=lambda: pages[op]),
    )
    code, text, error = invoke("runs", "outputs", "--run-uri", run, "--wide")
    assert code == 0 and not error
    assert text.splitlines()[1].split() == [
        "selected",
        run,
        "first",
        "signal",
        "json",
        "out-1",
        "not_checked",
    ]
    code, text, error = invoke("runs", "lineage", "--query", "{}")
    assert code == 0 and not error
    assert text.splitlines()[:2] == [
        f"{run} / first",
        f"  └─ declared_dependency → {run} / next",
    ]
    assert "line-1" in text


def test_wait_reports_changes_and_keeps_final_result_on_stdout(monkeypatch):
    from loom.queue.local_daemon import AdmissionWaitKind

    def observation(state):
        return SimpleNamespace(
            state=state,
            blocked_reason=None,
            revision=1,
            admission_id="admission-a",
            to_dict=lambda: dict(
                state=state, admission_id="admission-a", queue_item_id="item-a"
            ),
        )

    monkeypatch.setattr(
        CoordinatorClient, "_native_call", lambda *a, **kw: observation("WAITING")
    )
    updates = iter(
        (("CHANGED", "ACTIVE"), ("TIMEOUT", "ACTIVE"), ("TERMINAL", "SUCCEEDED"))
    )

    def wait(*a, **kw):
        kind, state = next(updates)
        return SimpleNamespace(
            kind=AdmissionWaitKind(kind), admission=observation(state)
        )

    monkeypatch.setattr(CoordinatorClient, "_wait_native", wait)
    code, text, error = invoke("queue", "daemon-wait", "item-a")
    assert code == 0 and len(text.splitlines()) == len(error.splitlines()) == 1
    assert text.split()[1:] == ["SUCCEEDED", "item-a", "admission-a"]
    assert error.split()[1:] == ["ACTIVE", "item-a", "admission-a"]
    assert error.split()[0].endswith("Z") and text.split()[0].endswith("Z")


def test_fleet_receipt_distinguishes_deferred_qualification_and_unknown_step():
    from loom.cli.fleet import _operation_receipt

    text = _operation_receipt(
        {
            "outcome": "waiting",
            "fleet": "research",
            "operation_id": "upgrade-a",
            "reason": "check pending",
            "qualification": {
                "state": "partial",
                "deferred_agents": ["b"],
                "reason": "offline",
            },
            "release": {"release_id": "release-1"},
            "steps": {"a-start": {"native_outcome": "unknown", "reason": "lost_reply"}},
            "checks": {"a": {"outcome": "waiting", "operation_id": "check-a"}},
        }
    )
    assert text.startswith(
        "Fleet research: waiting\noperation id: upgrade-a\nreason: check pending"
    )
    assert "state: partial" in text and "offline" in text
    assert (
        "Release: release-1" in text
        and "check-a" in text
        and "unknown (lost_reply)" in text
    )

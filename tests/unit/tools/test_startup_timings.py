import pytest

from tools.startup_timings import summarize


pytestmark = pytest.mark.unit


def _event(action, sec, *, op=None, pid=1, ns=0, **attrs):
    return {"diagnostic": "loom.phase_timings", "spans": [{
        "action": action, "started_at": f"2026-01-01T00:00:{sec:02d}+00:00",
        "operation_id": op, "attributes": {
            "host": "host", "process_id": pid, "process_origin_ns": 1,
            "monotonic_ns": ns, **attrs,
        },
    }]}


def test_reverse_order_replay_clock_domains_and_missing_coverage():
    records = [
        _event("submission_sent", 0, op="one", ns=123),
        _event("submission_acknowledged", 1, op="one", ns=100_000_123),
        _event("submission_acknowledged", 30, op="one", ns=30_000_000_000),
        _event("admission_committed", 2, op="one", admission_id="p", role="preparation"),
        _event("admission_committed", 3, op="one", admission_id="t", role="target"),
        _event("reservation_committed", 4, assignment_id="pre", admission_id="p"),
        _event("stage_run_entered", 5, assignment_id="pre", pid=2),
        _event("reservation_committed", 6, assignment_id="work", admission_id="t"),
        _event("attempt_scheduling_summary", 6, assignment_id="work", result="reserved",
               saw_eligible_offer=True, eligible_request_ready_ns=2_000_000_000),
        _event("stage_run_entered", 7, assignment_id="work", pid=3),
        _event("submission_acknowledged", 8, op="two"),
        _event("stage_run_entered", 9, assignment_id="orphan"),
    ]
    result = summarize(reversed(records), clock_error_ms=8)
    assert result["first_send_to_first_ack"]["p50"] == .1
    assert result["ack_to_first_target_entry"]["p95"] == 6
    assert result["utc_difference_uncertainty_seconds"] == .016
    assert result["stage_entries_without_reservation_link"] == 1
    assert result["acknowledgements_without_target_entry"] == 1
    roles = result["observed_request_ready_and_eligible_to_reservation"]
    assert roles["target"]["p95"] == 2
    assert roles["preparation"]["p95"] is None and roles["preparation"]["unknown"] == 1
    assert summarize(records)["utc_difference_uncertainty_seconds"] is None


def test_direct_submission_correlates_without_parent_operation():
    records = [
        _event("submission_acknowledged", 4, submit_method="submit", queue_item_id="q", admission_id="a"),
        _event("reservation_committed", 5, assignment_id="w", admission_id="a"),
        _event("stage_run_entered", 6, assignment_id="w", pid=2),
    ]
    assert summarize(records)["ack_to_first_target_entry"]["max"] == 2

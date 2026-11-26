import pytest

from tools.startup_timings import summarize


pytestmark = pytest.mark.unit


def _event(action, sec, *, op=None, pid=1, ns=0, work=None, **attrs):
    return {"diagnostic": "loom.phase_timings", "spans": [{
        "action": action, "started_at": f"2026-01-01T00:00:{sec:02d}+00:00",
        "operation_id": op, "attributes": {
            "host": "host", "process_id": pid, "process_origin_ns": 1,
            "monotonic_ns": ns, **(work or {}), **attrs,
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


def test_selected_timeline_links_the_publishing_child_and_both_clock_domains():
    work = dict(admission_id="target", stage_work_id="w", attempt_id="attempt")
    req = {**work, "request_queued_ns": 3_000_000_000}
    records = [
        _event("submission_sent", 0, op="operation"),
        _event("submission_acknowledged", 1, op="operation"),
        _event("admission_committed", 2, op="operation", role="preparation", admission_id="child"),
        _event("reservation_committed", 3, assignment_id="ca", admission_id="child"),
        _event("stage_run_returned", 7, assignment_id="ca", pid=7),
        _event("admission_succeeded", 9, pid=6, admission_id="child"),
        _event("admission_committed", 3, op="operation", role="preparation", admission_id="earlier-child"),
        _event("reservation_committed", 4, assignment_id="old", admission_id="earlier-child"),
        _event("stage_run_returned", 5, assignment_id="old", pid=8),
        _event("prepared_target_committed", 10, op="operation", child_admission_id="child", run_uri="uri"),
        _event("admission_committed", 11, ns=1_000_000_000, op="operation", role="target",
               admission_id="target", run_uri="uri"),
        _event("attempt_ready", 12, ns=2_000_000_000, projection_revision=3, work=work),
        _event("request_preparation_queued", 13, ns=3_000_000_000, work=req),
        _event("request_preparation_worker_started", 14, ns=4_000_000_000, work=req),
        _event("worker_request_available", 16, ns=6_000_000_000, request_available_ns=6_000_000_000, work=req),
        _event("reservation_committed", 20, ns=10_000_000_000, assignment_id="assigned",
               projection_revision=5, ready_projection_revision=3, request_available_ns=6_000_000_000, work=work),
        _event("attempt_scheduling_summary", 20, assignment_id="assigned", result="reserved",
               saw_eligible_offer=True, eligible_request_ready_ns=100_000_000,
               wait_ns={"assignment_slots_full": 2_000_000_000, "capacity_unknown": 5_000_000_000}, work=work),
        _event("assignment_received", 22, pid=2, assignment_id="assigned"),
        _event("supervisor_launch", 25, pid=3, assignment_id="assigned"),
        _event("stage_run_entered", 29, pid=4, assignment_id="assigned"),
    ]
    r = summarize(reversed(records + records[-2:]), operation="operation", clock_error_ms=3)
    report, = r["submissions"]
    attempt, = report["attempts"]["target"]
    assert (attempt["ready_projection_revision"], attempt["projection_revision"]) == (3, 5)
    assert attempt["wait_reason_seconds"] == {"assignment_slots_full": 2, "capacity_unknown": 5}
    assert attempt["confirmed_eligible_request_ready_seconds"] == .1
    assert {k: v["seconds"] for k, v in attempt["intervals"].items()} == {
        "admission_to_ready": 1, "ready_to_request_queued": 1, "request_worker_queue": 1, "request_worker_io": 2,
        "request_available_to_reservation": 4, "reservation_to_agent": 2, "agent_to_supervisor": 3,
        "supervisor_to_stage_run": 4,
    }
    assert attempt["intervals"]["reservation_to_agent"]["uncertainty_seconds"] == .006
    assert attempt["intervals"]["request_worker_io"]["clock"] == "monotonic"
    assert report["handoffs"] == [{
        "child_admission_id": "child", "target_admission_id": "target",
        "intervals": {"child_return_to_prepared_target_commit": {"seconds": 3, "clock": "utc", "uncertainty_seconds": .006},
                      "child_return_to_admission_succeeded": {"seconds": 2, "clock": "utc", "uncertainty_seconds": .006},
                      "child_admission_succeeded_to_prepared_target_commit": {"seconds": 1, "clock": "utc", "uncertainty_seconds": .006},
                      "prepared_target_commit_to_target_admission": {"seconds": 1, "clock": "monotonic", "uncertainty_seconds": 0}},
    }]
    assert r["phase_distributions"]["target"]["request_worker_io"]["samples"] == 1
    assert r["phase_distributions"]["preparation"]["request_worker_io"]["unknown"] == 2
    without_child_commit = [r for r in records if not (
        r["spans"][0]["action"] == "admission_committed" and r["spans"][0]["attributes"]["admission_id"] == "child"
    )]
    partial, = summarize(without_child_commit)["submissions"]
    assert partial["handoffs"][0]["intervals"]["child_return_to_prepared_target_commit"]["seconds"] == 3
    child = next(a for a in partial["attempts"]["preparation"] if a["admission_id"] == "child")
    assert child["assignment_id"] == "ca"
    assert child["intervals"]["admission_to_ready"] is None


def test_reopened_attempt_reuses_only_its_exact_request_and_missing_evidence_stays_unknown():
    key = dict(admission_id="a", stage_work_id="w", attempt_id="same")
    records = [_event("admission_committed", 1, op="r", role="target", admission_id="a")]
    for rev, queued, completed, assignment in [(1, 2, 4, "rejected"), (3, 9, 11, "accepted")]:
        records += [
            _event("attempt_ready", queued, ns=queued, projection_revision=rev, work=key),
            _event("request_preparation_queued", queued, ns=queued, request_queued_ns=queued, work=key),
            _event("worker_request_available", completed, ns=completed, request_available_ns=completed,
                   request_queued_ns=queued, work=key),
            _event("reservation_committed", completed + 2, ns=completed + 2, assignment_id=assignment,
                   ready_projection_revision=rev, projection_revision=rev, request_available_ns=completed, work=key),
        ]
    records += [
        _event("request_preparation_worker_started", 3, ns=3, request_queued_ns=2, work=key),
        _event("stage_run_entered", 14, assignment_id="accepted", pid=5),
        _event("attempt_ready", 16, ns=16, projection_revision=5, work=key),
        _event("reservation_committed", 18, ns=18, assignment_id="carried", ready_projection_revision=5,
               projection_revision=6, request_available_ns=11, work=key),
    ]
    r = summarize(records[::-1])
    report, = r["submissions"]
    a, b, c = report["attempts"]["target"]
    assert [x["assignment_id"] for x in (a, b, c)] == ["rejected", "accepted", "carried"]
    assert a["intervals"]["request_worker_io"]["seconds"] == 1e-9
    assert b["intervals"]["request_worker_io"] is None
    assert c["request_queued_before_this_ready"]
    assert c["intervals"]["ready_to_request_queued"] is None
    assert c["intervals"]["request_available_to_reservation"]["seconds"] == 7e-9
    assert all(v is None for v in report["handoffs"][0]["intervals"].values())

    # Exact build tokens survive a dropped queue marker. A reopened placement
    # can consume the built request, but it cannot contribute a second build.
    records.append(_event("request_preparation_worker_started", 10, ns=10, request_queued_ns=9, work=key))
    missing_queue = [e for e in records if not (e["spans"][0]["action"] == "request_preparation_queued"
                                                and e["spans"][0]["attributes"]["request_queued_ns"] == 9)]
    r = summarize(missing_queue)
    _, accepted, carried = r["submissions"][0]["attempts"]["target"]
    assert accepted["intervals"]["request_worker_io"]["seconds"] == 1e-9
    assert carried["request_queued_before_this_ready"]
    assert carried["intervals"]["request_worker_io"] is None
    assert r["phase_distributions"]["target"]["request_worker_io"]["samples"] == 2

    partial = [e for e in records if not (e["spans"][0]["action"] == "reservation_committed"
                                           and e["spans"][0]["attributes"]["assignment_id"] == "rejected")]
    partial.append(_event("attempt_scheduling_summary", 6, ns=6, assignment_id="rejected", work=key,
                          ready_projection_revision=1, projection_revision=2, request_available_ns=4,
                          result="reserved"))
    placements = summarize(reversed(partial))["submissions"][0]["attempts"]["target"]
    assert [a["assignment_id"] for a in placements] == ["rejected", "accepted", "carried"]
    assert placements[0]["intervals"]["request_worker_io"]["seconds"] == 1e-9
    assert placements[0]["intervals"]["reservation_to_agent"] is None


def test_ranking_and_lookup_include_incomplete_submissions_without_polluting_percentiles():
    records = []
    for op, end in [("fast", 5), ("slow", 35), ("missing", None)]:
        records.append(_event("submission_acknowledged", 1, op=op))
        records.append(_event("admission_committed", 2, op=op, role="target", admission_id=op))
        if end:
            records += [_event("reservation_committed", 3, assignment_id=op, admission_id=op),
                        _event("stage_run_entered", end, assignment_id=op, pid=2)]
    ranked = summarize(records, slowest=1)
    assert [r["operation_id"] for r in ranked["submissions"]] == ["slow"]
    assert ranked["ack_to_first_target_entry"] == {"samples": 2, "p50": 4, "p95": 34, "max": 34}
    missing, = summarize(records, operation="missing")["submissions"]
    assert missing["ack_to_first_target_entry"] is None
    assert all(v is None for v in missing["attempts"]["target"][0]["intervals"].values())
    assert summarize(records, operation="absent")["submissions"] == []


def test_missing_reservation_preserves_known_agent_intervals_and_discards_mismatched_worker_start():
    key = dict(admission_id="a", stage_work_id="work", attempt_id="attempt")
    records = [
        _event("admission_committed", 1, op="r", role="target", admission_id="a"),
        _event("attempt_ready", 2, ns=2, projection_revision=1, work=key),
        _event("request_preparation_queued", 3, ns=3, request_queued_ns=3, work=key),
        _event("request_preparation_worker_started", 8, ns=8, request_queued_ns=7, work=key),
        _event("assignment_received", 10, pid=2, assignment_id="assigned", work=key),
        _event("supervisor_launch", 11, pid=3, assignment_id="assigned", work=key),
        _event("stage_run_entered", 13, pid=4, assignment_id="assigned", work=key),
    ]
    row, = summarize(records)["submissions"][0]["attempts"]["target"]
    assert row["assignment_id"] == "assigned"
    assert row["intervals"]["request_worker_queue"] is None
    assert row["intervals"]["reservation_to_agent"] is None
    assert row["intervals"]["agent_to_supervisor"]["seconds"] == 1
    assert row["intervals"]["supervisor_to_stage_run"]["seconds"] == 2


def test_reserved_build_with_dropped_completion_does_not_claim_earlier_failed_build():
    key = dict(admission_id="a", stage_work_id="w", attempt_id="attempt")
    records = [
        _event("admission_committed", 1, op="r", role="target", admission_id="a"),
        _event("attempt_ready", 2, ns=2, projection_revision=1, work=key),
        _event("request_preparation_queued", 3, ns=3, request_queued_ns=3, work=key),
        _event("request_preparation_worker_started", 8, ns=8, request_queued_ns=3, work=key),
        _event("reservation_committed", 12, ns=12, request_available_ns=11, ready_projection_revision=1,
               assignment_id="successful", work=key),
    ]
    row, = summarize(records)["submissions"][0]["attempts"]["target"]
    assert row["assignment_id"] == "successful"
    assert row["intervals"]["ready_to_request_queued"] is None
    assert row["intervals"]["request_worker_queue"] is None


def test_prequeue_observations_belong_to_the_selected_build_and_bulk_keeps_retries():
    key = dict(admission_id="a", stage_work_id="w", attempt_id="attempt")
    records = [
        _event("admission_committed", 1, op="r", role="target", admission_id="a"),
        _event("attempt_ready", 2, ns=2, projection_revision=1, work=key),
        _event("worker_request_available", 5, ns=5, request_queued_ns=4, request_available_ns=5, work=key),
        _event("attempt_scheduling_summary", 7, ns=7, assignment_id="assigned", work=key, result="reserved",
               ready_projection_revision=1, projection_revision=1, request_available_ns=5, prequeue_status="observed",
               prequeue_ready_ns=2, prequeue_queued_ns=4, prequeue_wait_ns={"first_scan": 2}),
    ]
    def bulk(outcome, sec, child):
        return {"diagnostic": "loom.phase_timings", "operation_id": "r", "related": {"child_admission_id": child},
                "spans": [{"action": "bulk_capacity_wait", "elapsed_nanoseconds": 3_000_000_000},
                          {"action": "preparation_report_hydration", "operation_id": "r", "outcome": outcome,
                           "started_at": f"2026-01-01T00:00:{sec:02d}+00:00", "elapsed_nanoseconds": 250_000_000}]}
    failed, good = bulk("error", 1, "earlier"), bulk("complete", 9, "chosen")
    records.extend([good, failed, good])
    result = summarize(records)
    report, = result["submissions"]
    target, = report["attempts"]["target"]
    assert target["prequeue_wait_seconds"] == {"first_scan": 2e-9}
    assert result["prequeue_distributions"]["target"]["coverage"] == {"observed": 1}
    assert [(r["outcome"], r["child_admission_id"], r["capacity_wait_seconds"], r["worker_seconds"])
            for r in report["observed_preparation_work"]] == [("error", "earlier", 3, .25), ("complete", "chosen", 3, .25)]
    # A failed first build and a subsequent successful build share the same work ID.
    records[3]["spans"][0]["attributes"]["prequeue_queued_ns"] = 3
    changed, = summarize(records)["submissions"]
    assert changed["attempts"]["target"][0]["prequeue_status"] == "missing"
    assert changed["attempts"]["target"][0]["prequeue_wait_seconds"] is None

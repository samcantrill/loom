import json
import sys

import pytest

from tools.startup_timings import main, summarize


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
    assert {k: v["seconds"] for k, v in attempt["intervals"].items() if v is not None} == {
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
    # A dropped commit cannot hide the independently joined child return/success.
    no_commit = [r for r in records if r["spans"][0]["action"] != "prepared_target_committed"
                 and r["spans"][0]["attributes"].get("admission_id") != "earlier-child"]
    partial, = summarize(no_commit)["submissions"]
    assert partial["handoffs"][0]["intervals"]["child_return_to_admission_succeeded"]["seconds"] == 2
    assert partial["handoffs"][0]["intervals"]["child_admission_succeeded_to_prepared_target_commit"] is None


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
    assert target["intervals"]["ready_to_request_queued"]["seconds"] == 2e-9
    assert result["prequeue_distributions"]["target"]["coverage"] == {"observed": 1}
    assert [(r["outcome"], r["child_admission_id"], r["capacity_wait_seconds"], r["worker_seconds"])
            for r in report["observed_preparation_work"]] == [("error", "earlier", 3, .25), ("complete", "chosen", 3, .25)]
    # A failed first build and a subsequent successful build share the same work ID.
    records[3]["spans"][0]["attributes"]["prequeue_queued_ns"] = 3
    changed, = summarize(records)["submissions"]
    assert changed["attempts"]["target"][0]["prequeue_status"] == "missing"
    assert changed["attempts"]["target"][0]["prequeue_wait_seconds"] is None
    legacy = bulk("complete", 9, None)
    del legacy["related"]
    old, = summarize([legacy], operation="r")["submissions"]
    assert old["observed_preparation_work"][0]["child_admission_id"] is None
    assert old["observed_preparation_work"][0]["worker_seconds"] == .25


def test_unassigned_closures_keep_unknown_and_measured_placement_coverage():
    key = dict(admission_id="a", stage_work_id="w", attempt_id="attempt")
    rows = [
        _event("admission_committed", 1, op="r", role="target", admission_id="a"),
        _event("attempt_ready", 2, ns=6, projection_revision=1, work=key),
        _event("request_preparation_queued", 4, ns=12, request_queued_ns=9, work=key),
        _event("request_preparation_worker_started", 5, ns=14, request_queued_ns=9, work=key),
        _event("attempt_scheduling_summary", 6, ns=20, work=key, ready_projection_revision=1, result="left_ready",
               request_available_ns=None, prequeue_ready_ns=2, prequeue_queued_ns=9,
               prequeue_wait_ns={"context_unavailable": 7}, prequeue_status="observed"),
        _event("attempt_scheduling_summary", 7, ns=30, work=key, ready_projection_revision=3, result="left_ready",
               prequeue_status="inapplicable", prequeue_wait_ns=None),
    ]
    result = summarize(rows)
    observed, inapplicable = result["submissions"][0]["attempts"]["target"]
    assert observed["assignment_id"] is None and inapplicable["assignment_id"] is None
    assert observed["intervals"]["ready_to_request_queued"]["seconds"] == 7e-9
    assert observed["intervals"]["request_worker_queue"]["seconds"] == 2e-9
    assert result["prequeue_distributions"]["target"]["coverage"] == {"observed": 1, "inapplicable": 1}


def _context(action, stamp, request=1, **attrs):
    identity = {"admission_id": "a", "admission_revision": 2, "coordinator_epoch": "c", "scheduling_epoch": "s",
                "context_request_id": request, "source": "dispatch"}
    return _event(f"context_{action}", 0, ns=stamp * 1_000_000_000, **{**identity, **attrs})


def test_context_timeline_keeps_reloads_processes_epochs_and_dropped_endpoints_separate():
    records = [
        _context("requested", 1, wait_reason="workers_busy"),
        _context("loader_started", 2),
        _context("validation", 3, result="cold_load"),
        _context("available", 6),
        _context("consumer_advanced", 13, consumer="dispatch"),
        _context("discarded", 14, owner="retained", reason="revision_changed"),
        _context("cache_evicted", 20, reason="capacity"),
        _context("requested", 10, 2, wait_reason="dispatch_slot_busy"),
        _context("loader_started", 14, 2),
        _context("validation", 15, 2, result="dependencies_changed"),
        _context("discarded", 20, 2, owner="preparation", reason="loader_error"),
        _context("requested", 10, process_origin_ns=99, wait_reason="available"),
        _context("available", 31, process_origin_ns=99),
        _context("discarded", 42, process_origin_ns=99, owner="preparation", reason="revision_changed"),
        _context("requested", 0, scheduling_epoch="new", wait_reason="available"),
        _context("loader_started", 1, scheduling_epoch="new"),
        _context("available", 50, admission_revision=3),
        _context("consumer_advanced", 55, admission_revision=3, consumer="reconcile"),
    ]
    # A replayed log can contain the same milestone more than once in any order.
    copied = [_context("loader_started", 32, host=None, process_origin_ns=99), *records, *reversed(records)]
    result = summarize(copied)
    assert result["submissions"] == []
    report = result["context_loader"]
    assert report["observed_requests"] == 5
    assert report["unattributed_events"] == 1
    assert (report["admission_revisions"], report["repeated_requests"], report["observed_reloads"]) == (2, 3, 2)
    assert report["requests_per_revision"] == {1: 1, 4: 1}
    assert report["loader_starts_per_revision"] == {0: 1, 3: 1}
    assert report["validation_results"] == {"cold_load": 1, "dependencies_changed": 1}
    assert report["initial_wait_reasons"] == {"workers_busy": 1, "dispatch_slot_busy": 1, "available": 2}
    assert report["discard_reasons"] == {"retained": {"revision_changed": 1},
                                         "preparation": {"loader_error": 1, "revision_changed": 1}}
    assert report["cache_eviction_reasons"] == {"capacity": 1}
    queue = report["interval_seconds"]["request_to_loader_start"]
    assert queue == {"samples": 3, "unknown": 2, "p50": 1, "p95": 4, "p99": 4, "max": 4}
    worker = report["interval_seconds"]["loader_start_to_available"]
    assert (worker["samples"], worker["unknown"], worker["max"]) == (1, 4, 4)
    advance = report["interval_seconds"]["available_to_first_consumer"]
    assert (advance["samples"], advance["unknown"], advance["max"]) == (2, 3, 7)
    by_phase = {phase: row for row in report["slow_examples"] for phase in row["slowest_for"]}
    assert by_phase["request_to_loader_start"]["context_request_id"] == 2
    longest = by_phase["available_to_first_consumer"]
    assert longest["interval_seconds"]["available_to_first_consumer"] == 7
    assert (longest["admission_id"], longest["admission_revision"], longest["process_origin_ns"]) == ("a", 2, 1)
    assert longest["discards"] == [{"owner": "retained", "reason": "revision_changed"}]


def test_context_only_cli_reports_population_tails_and_scopes_examples_and_revision_counts(tmp_path, monkeypatch, capsys):
    records = []
    for request in range(1, 101):
        records += [_context("requested", 0, request, op="many", wait_reason="workers_busy"),
                    _context("loader_started", request, request, op="many")]
    records += [_event("admission_committed", 0, submit_method="submit", queue_item_id="direct", admission_id="other"),
                _context("requested", 1, admission_id="other", wait_reason="workers_busy"),
                _context("discarded", 2, admission_id="other", owner="request", reason="retained_reuse")]
    path = tmp_path / "coordinator.log"
    path.write_text("".join(f"INFO {json.dumps(r)}\n" for r in reversed(records)))
    monkeypatch.setattr(sys, "argv", ["startup_timings.py", str(path), "--operation", "direct"])
    main()
    direct = json.loads(capsys.readouterr().out)["context_loader"]
    assert direct["observed_requests"] == 101
    queue = direct["interval_seconds"]["request_to_loader_start"]
    assert (queue["samples"], queue["unknown"], queue["p95"], queue["p99"]) == (100, 1, 95, 99)
    assert direct["selected_revisions"] == [{"admission_id": "other", "admission_revision": 2, "requests": 1,
                                             "loader_starts": 0}]
    discarded, = direct["slow_examples"]
    assert discarded["discards"] == [{"owner": "request", "reason": "retained_reuse"}]
    assert all(value is None for value in discarded["interval_seconds"].values())
    assert discarded["slowest_for"] == ["discarded"]
    many = summarize(records, operation="many")["context_loader"]
    assert many["selected_revisions"] == [{"admission_id": "a", "admission_revision": 2, "requests": 100,
                                           "loader_starts": 100}]
    assert [row["context_request_id"] for row in many["slow_examples"]] == [100]
    assert summarize(records, operation="absent")["context_loader"]["slow_examples"] == []


def test_context_timeline_matches_installation_and_first_target_entry_per_admission():
    key = dict(admission_id="a", stage_work_id="w", attempt_id="attempt")
    identity = {"context_request_id": 1, "admission_revision": 2, "coordinator_epoch": "c", "scheduling_epoch": "s"}
    fields = dict(first_scan_ns=3, interest_ns=5, installed_ns=8, visit_ns=9, progress_ns=10,
                  demand_load=identity, used_load=identity, demand_ns=5, demand_installed_ns=8, demand_visit_ns=11, progress_installed_ns=8)
    records = [
        _event("admission_committed", 1, op="op", ns=1, role="target", admission_id="a"),
        _event("attempt_ready", 2, ns=2, projection_revision=1, work=key),
        _event("attempt_scheduling_summary", 11, ns=11, assignment_id="assignment", work=key, result="reserved",
               prequeue_ready_ns=2, ready_projection_revision=1, projection_revision=1, stage_context=fields),
        _event("stage_run_entered", 13, ns=13, pid=2, assignment_id="assignment"),
        _event("admission_committed", 2, op="peer", role="target", admission_id="b"),
    ]
    result = summarize(records)
    phases = result["phase_distributions"]["target"]
    assert [phases[k]["p50"] for k in ("ready_to_first_scan", "first_scan_to_context_interest", "context_demand_to_install",
                                       "context_install_to_stage_visit", "context_install_to_stage_progress")] == [1e-9, 2e-9, 3e-9, 1e-9, 2e-9]
    assert phases["demand_install_to_stage_revisit"]["p50"] == 3e-9
    assert result["target_admission_to_first_stage_entry"]["unknown"] == 1
    assert result["first_target_admission_to_last_first_entry"] is None
    fields.pop("demand_installed_ns")  # A superseding load supplied the first usable context.
    fields["used_load"] = {**identity, "context_request_id": 2}
    fields["progress_installed_ns"] = 1  # The progress used a context installed before this READY cycle.
    result = summarize(records[:-1])
    phases = result["phase_distributions"]["target"]
    assert phases["context_demand_to_install"]["samples"] == phases["context_install_to_stage_progress"]["samples"] == 0
    assert phases["demand_install_to_stage_revisit"]["unknown"] == 1
    assert result["target_admission_to_first_stage_entry"]["p50"] == 12
    assert result["first_target_admission_to_last_first_entry"]["seconds"] == 12

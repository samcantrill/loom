"""Summarize single-stage Loom submissions from combined client, coordinator and agent logs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import json
from math import ceil, isfinite
from pathlib import Path


def _distribution(values):
    values = sorted(values)
    if not values:
        return {"samples": 0, "p50": None, "p95": None, "max": None}
    return {"samples": len(values), "p50": values[ceil(.50 * len(values)) - 1],
            "p95": values[ceil(.95 * len(values)) - 1], "max": values[-1]}


# Measurements are computed on a single joined placement before aggregating.
_PHASES = {
    "admission_to_ready": ("admission_committed", "attempt_ready"),
    "ready_to_request_queued": ("attempt_ready", "request_preparation_queued"),
    "request_worker_queue": ("request_preparation_queued", "request_preparation_worker_started"),
    "request_worker_io": ("request_preparation_worker_started", "worker_request_available"),
    "request_available_to_reservation": ("worker_request_available", "reservation_committed"),
    "reservation_to_agent": ("reservation_committed", "assignment_received"),
    "agent_to_supervisor": ("assignment_received", "supervisor_launch"),
    "supervisor_to_stage_run": ("supervisor_launch", "stage_run_entered"),
}
_HANDOFF = {
    "child_return_to_prepared_target_commit": ("stage_run_returned", "prepared_target_committed"),
    "child_return_to_admission_succeeded": ("stage_run_returned", "admission_succeeded"),
    "child_admission_succeeded_to_prepared_target_commit": ("admission_succeeded", "prepared_target_committed"),
    "prepared_target_commit_to_target_admission": ("prepared_target_committed", "admission_committed"),
}
_REQUEST = ("request_preparation_queued", "request_preparation_worker_started", "worker_request_available")
_AGENT = ("assignment_received", "supervisor_launch", "stage_run_entered", "stage_run_returned")
_BULK_PHASES = {"preparation_report_hydration", "preparation_target_publication", "preparation_annotation_initialization"}
_ACTIONS = {"submission_sent", "submission_acknowledged", "admission_committed", "admission_succeeded", "prepared_target_committed",
            "attempt_ready", "attempt_scheduling_summary", "reservation_committed", *_REQUEST, *_AGENT}


@dataclass
class Event:
    action: str
    utc: datetime
    domain: tuple
    ns: int | None
    attrs: dict

    @classmethod
    def read(cls, span):
        a = span.get("attributes") or {}
        return cls(span["action"], datetime.fromisoformat(span["started_at"]),
                   (a.get("host"), a.get("process_id"), a.get("process_origin_ns")), a.get("monotonic_ns"), a)


def _interval(start, finish, error_ms):
    if start is None or finish is None:
        return None
    if (None not in start.domain and start.domain == finish.domain
        and start.ns is not None and finish.ns is not None):
        return {"seconds": (finish.ns - start.ns) / 1e9, "clock": "monotonic", "uncertainty_seconds": 0}
    return {"seconds": (finish.utc - start.utc).total_seconds(), "clock": "utc",
            "uncertainty_seconds": None if error_ms is None else 2 * error_ms / 1000}


def _first(events):
    return min(events, key=lambda e: e.utc, default=None)


def _unique(events):
    """Repeated copies of one observed event are safe; ambiguous associations stay unknown."""
    found = None
    for event in events:
        if found is not None and event != found:
            return None
        found = event
    return found


def _measure(events, phases, error_ms):
    return {name: _interval(events.get(start), events.get(end), error_ms) for name, (start, end) in phases.items()}


def _stats(intervals):
    intervals = list(intervals)
    return {**_distribution(v["seconds"] for v in intervals if v is not None), "unknown": intervals.count(None),
            "utc_samples": sum(v is not None and v["clock"] == "utc" for v in intervals)}


def _work(attrs):
    return attrs.get("admission_id"), attrs.get("stage_work_id"), attrs.get("attempt_id")


class Trace:
    """Indexes diagnostic events by their native owners, independently of file order."""

    def __init__(self, records):
        self.client = defaultdict(lambda: defaultdict(list))
        self.admissions = {}
        self.admitted = {}
        self.succeeded = defaultdict(list)
        self.bulk = defaultdict(dict)
        self.prepared = defaultdict(list)
        self.assignments = defaultdict(lambda: defaultdict(list))
        self.work = defaultdict(lambda: defaultdict(list))
        self.prepare_only = set()
        for record in records:
            if record.get("diagnostic") != "loom.phase_timings":
                continue
            # Only the worker's own record contains the FIFO capacity span and
            # the timed operation. Nested caller spans do not establish queue time.
            spans = record.get("spans", ())
            operation = record.get("operation_id")
            waits = [s for s in spans if s.get("action") == "bulk_capacity_wait"]
            for span in spans:
                if span.get("action") in _BULK_PHASES and operation and span.get("operation_id") == operation:
                    child = (record.get("related") or {}).get("child_admission_id")
                    if child:
                        self.admissions[child] = operation, "preparation"
                    wait = waits[0]["elapsed_nanoseconds"] / 1e9 if len(waits) == 1 else None
                    row = {"action": span["action"], "child_admission_id": child, "started_at": span["started_at"],
                           "worker_seconds": span["elapsed_nanoseconds"] / 1e9, "outcome": span["outcome"],
                           "capacity_wait_seconds": wait}
                    self.bulk[operation][tuple(row.values())] = row
            for span in spans:
                if span.get("action") not in _ACTIONS:
                    continue
                e = Event.read(span)
                a = e.attrs
                operation = span.get("operation_id") or record.get("operation_id")
                admission = a.get("admission_id")
                if e.action in ("submission_sent", "submission_acknowledged"):
                    if a.get("submit_method") == "submit":
                        identity = a.get("queue_item_id") or admission
                        if identity is None:
                            continue
                        operation = ("direct", identity)
                        if admission:
                            self.admissions[admission] = (operation, "target")
                    if operation is not None:
                        self.client[operation][e.action].append(e)
                        if a.get("submit_method") == "prepare_run":
                            self.prepare_only.add(operation)
                elif e.action == "admission_succeeded":
                    self.succeeded[admission].append(e)
                elif e.action == "admission_committed":
                    self.admitted[admission] = e
                    if operation:
                        self.admissions[admission] = operation, a["role"]
                    elif a.get("queue_item_id"):
                        self.admissions[admission] = ("direct", a["queue_item_id"]), "target"
                elif e.action == "prepared_target_committed":
                    self.prepared[operation].append(e)
                    child = a.get("child_admission_id")
                    if child and operation:
                        self.admissions[child] = operation, "preparation"
                elif a.get("assignment_id"):
                    self.assignments[a["assignment_id"]][e.action].append(e)
                elif all(_work(a)):
                    self.work[_work(a)][e.action].append(e)


def _request(events, reserved, single_cycle):
    """A rebuilt request and a request carried into a reopened reservation have distinct observations."""
    available = events.get("worker_request_available", [])
    if reserved and not reserved.attrs.get("assignment_id") and reserved.attrs.get("prequeue_queued_ns") is not None:
        token = reserved.attrs["prequeue_queued_ns"]
        return {action: _unique(e for e in events.get(action, ())
                                if e.domain == reserved.domain and e.attrs.get("request_queued_ns") == token)
                for action in _REQUEST}
    if reserved and "request_available_ns" in reserved.attrs:
        stamp = reserved.attrs["request_available_ns"]
        finished = _unique(e for e in available if stamp is not None and e.domain == reserved.domain
                           and e.attrs.get("request_available_ns") == stamp)
        if finished is None:
            # An earlier failed build can have queue and start events under the same attempt.
            return {}
    elif single_cycle and all(len({(e.utc, e.domain, e.ns) for e in events.get(action, ())}) <= 1
                              for action in _REQUEST):
        finished = _unique(available)
    else:
        return {}
    result = {"worker_request_available": finished}
    for action in _REQUEST[:2]:
        candidates = events.get(action, ())
        if finished and "request_queued_ns" in finished.attrs:
            candidates = [e for e in candidates if e.domain == finished.domain and
                          e.attrs.get("request_queued_ns") == finished.attrs["request_queued_ns"]]
        elif (not single_cycle or len({(e.utc, e.domain, e.ns) for e in available}) > 1
              or (reserved and available and finished is None)):
            continue
        result[action] = _unique(candidates)
    queued, started = (result.get(action) for action in _REQUEST[:2])
    if queued and started and "request_queued_ns" in queued.attrs and (
        queued.domain != started.domain or queued.attrs["request_queued_ns"] != started.attrs.get("request_queued_ns")
    ):
        # Dropped observations from two different builds cannot establish a worker queue interval.
        result["request_preparation_worker_started"] = None
    return result


def _attempt(trace, key, assignment, assigned, ready, single_cycle, error_ms):
    admission, work_id, attempt = key
    reserved = _first(assigned.get("reservation_committed", ()))
    summary = _first(assigned.get("attempt_scheduling_summary", ()))
    events = {action: _first(assigned.get(action, ())) for action in _AGENT}
    events.update(admission_committed=trace.admitted.get(admission), attempt_ready=ready,
                  reservation_committed=reserved)
    events.update(_request(trace.work.get(key, {}), reserved or summary, single_cycle))
    intervals = _measure(events, _PHASES, error_ms)
    build = next((e for action in reversed(_REQUEST) if (e := events.get(action)) is not None
                  and "request_queued_ns" in e.attrs), None)
    queued = build or events.get("request_preparation_queued")
    queued_ns = queued.attrs.get("request_queued_ns", queued.ns) if queued else None
    carried = bool(ready and queued and ready.domain == queued.domain and ready.ns is not None
                   and queued_ns is not None and queued_ns < ready.ns)
    if carried:
        intervals["ready_to_request_queued"] = None
        intervals["request_worker_queue"] = None
        intervals["request_worker_io"] = None
    s = summary.attrs if summary else {}
    r = reserved.attrs if reserved else {}
    waits = s.get("wait_ns")
    prequeue = s.get("prequeue_status", "missing")
    selected_queue_ns = s.get("prequeue_queued_ns")
    if prequeue == "observed" and (selected_queue_ns is None or (assignment is not None and (
            build is None or summary is None or build.domain != summary.domain or selected_queue_ns != queued_ns))):
        prequeue = "missing"
    prequeue_waits = s.get("prequeue_wait_ns") if prequeue == "observed" else None
    if prequeue_waits is not None and s.get("prequeue_ready_ns") is not None:
        # Use the two transition stamps also measured by the reason counters.
        # The separate log records can be emitted later after a thread pause.
        intervals["ready_to_request_queued"] = {"seconds": (selected_queue_ns - s["prequeue_ready_ns"]) / 1e9,
                                                "clock": "monotonic", "uncertainty_seconds": 0}
    return {
        "admission_id": admission, "stage_work_id": work_id, "attempt_id": attempt, "assignment_id": assignment,
        "stage_name": r.get("stage_name") or s.get("stage_name") or (ready.attrs.get("stage_name") if ready else None),
        "ready_projection_revision": (ready.attrs.get("projection_revision") if ready else
                                      r.get("ready_projection_revision", s.get("ready_projection_revision"))),
        "projection_revision": r.get("projection_revision", s.get("projection_revision")),
        "intervals": intervals, "request_queued_before_this_ready": carried,
        "prequeue_status": prequeue,
        "prequeue_wait_seconds": {k: v / 1e9 for k, v in prequeue_waits.items()} if prequeue_waits is not None else None,
        "wait_reason_seconds": {k: v / 1e9 for k, v in waits.items()} if waits is not None else None,
        "confirmed_eligible_request_ready_seconds": (
            s["eligible_request_ready_ns"] / 1e9 if s.get("saw_eligible_offer") else None),
    }


def _attempts(trace, error_ms):
    by_work = defaultdict(list)
    work_ids = {key[1:]: key for key in trace.work}
    for identity, assigned in trace.assignments.items():
        # Either coordinator event can identify the placement if the other was omitted.
        link = _first(assigned.get("reservation_committed", ())) or _first(assigned.get("attempt_scheduling_summary", ()))
        if link is not None:
            by_work[_work(link.attrs)].append((identity, assigned))
        else:
            # Agent/guest reports retain the immutable work and attempt IDs even
            # when both coordinator reservation diagnostics were dropped.
            keys = {work_ids[(e.attrs["stage_work_id"], e.attrs["attempt_id"])]
                    for action in _AGENT for e in assigned.get(action, ())
                    if (e.attrs.get("stage_work_id"), e.attrs.get("attempt_id")) in work_ids}
            if len(keys) == 1:
                by_work[keys.pop()].append((identity, assigned))
    for key in dict.fromkeys([*by_work, *trace.work]):
        placements = by_work[key]
        ready_events = trace.work.get(key, {}).get("attempt_ready", [])
        matched = []
        # Legacy emitters lack a reservation-to-READY link. Only use an unambiguous cycle.
        single_cycle = len(placements) <= 1 and (not ready_events or _unique(ready_events) is not None)
        for identity, assigned in placements:
            link = _first(assigned.get("reservation_committed", ())) or _first(assigned.get("attempt_scheduling_summary", ()))
            revision = link.attrs.get("ready_projection_revision") if link else None
            if link is not None and revision is not None:
                ready = _unique(e for e in ready_events if e.attrs.get("projection_revision") == revision
                                and e.domain == link.domain)
            else:
                ready = _unique(ready_events) if single_cycle else None
            if ready is not None:
                matched.append(ready)
            yield _attempt(trace, key, identity, assigned, ready, single_cycle, error_ms)
        closures = trace.work.get(key, {}).get("attempt_scheduling_summary", ())
        matched_closures = []
        for ready in ready_events:
            if ready not in matched:
                matched.append(ready)
                closed = _unique(e for e in closures
                                 if e.domain == ready.domain and
                                 e.attrs.get("ready_projection_revision") == ready.attrs.get("projection_revision"))
                if closed is not None:
                    matched_closures.append(closed)
                details = {"attempt_scheduling_summary": [closed]} if closed else {}
                yield _attempt(trace, key, None, details, ready, single_cycle, error_ms)
        for closed in closures:
            if closed not in matched_closures and closed.attrs.get("ready_projection_revision") is not None:
                matched_closures.append(closed)
                yield _attempt(trace, key, None, {"attempt_scheduling_summary": [closed]}, None, single_cycle, error_ms)
        if not placements and not ready_events and not matched_closures:
            yield _attempt(trace, key, None, {}, None, single_cycle, error_ms)


def _handoff(trace, op, attempts, targets, error_ms):
    rows = []
    commits = defaultdict(list)
    for event in trace.prepared.get(op, ()):
        commits[(event.attrs.get("child_admission_id"), event.attrs.get("run_uri"))].append(event)
    # Multiple verification children may belong to one operation. The durable
    # prepared-target observation identifies the child that produced this result.
    for (child, uri), observations in commits.items():
        commit = min(observations, key=lambda e: e.utc)
        returns = [e for a in attempts["preparation"] if a["admission_id"] == child
                   for e in trace.assignments.get(a["assignment_id"], {}).get("stage_run_returned", ())]
        admitted = _unique(trace.admitted[ad] for ad in targets if ad in trace.admitted
                           and trace.admitted[ad].attrs.get("run_uri") == uri)
        row = {"child_admission_id": child, "target_admission_id": admitted.attrs["admission_id"] if admitted else None,
               "intervals": _measure({"prepared_target_committed": commit, "stage_run_returned": _unique(returns),
                                      "admission_succeeded": _unique(trace.succeeded.get(child, ())),
                                      "admission_committed": admitted}, _HANDOFF, error_ms)}
        rows.append(row)
    if not rows and isinstance(op, str) and op not in trace.prepare_only:
        children = {a["admission_id"] for a in attempts["preparation"]}
        child = next(iter(children)) if len(children) == 1 else None
        returns = [e for a in attempts["preparation"] if a["admission_id"] == child
                   for e in trace.assignments.get(a["assignment_id"], {}).get("stage_run_returned", ())]
        row_events = {"stage_run_returned": _unique(returns), "admission_succeeded": _unique(trace.succeeded.get(child, ()))}
        rows.append({"child_admission_id": child,
                     "target_admission_id": targets[0] if len(targets) == 1 else None,
                     "intervals": _measure(row_events, _HANDOFF, error_ms)})
    return rows


def _seconds(interval):
    return None if interval is None else interval["seconds"]


def summarize(records, *, clock_error_ms=None, slowest=10, operation=None):
    """Join native identities, then compute nearest-rank quantiles across measured intervals."""
    trace = Trace(records)
    grouped = defaultdict(lambda: {"preparation": [], "target": []})
    targets = defaultdict(list)
    observed_admissions = set()
    for attempt in _attempts(trace, clock_error_ms):
        link = trace.admissions.get(attempt["admission_id"])
        if link is not None:
            op, role = link
            grouped[op][role].append(attempt)
            observed_admissions.add(attempt["admission_id"])
    for admission, (op, role) in trace.admissions.items():
        if role == "target":
            targets[op].append(admission)
        if admission not in observed_admissions:
            grouped[op][role].append(_attempt(trace, (admission, None, None), None, {}, None, True, clock_error_ms))
    operations = list(dict.fromkeys([*trace.client, *(op for op, _ in trace.admissions.values()), *trace.prepared, *trace.bulk]))
    durations, send_times, reports = [], [], []
    handoff_samples = []
    phase_samples = defaultdict(list)
    prequeue_samples = defaultdict(list)
    prequeue_counts = defaultdict(Counter)
    eligible = defaultdict(list)
    unknown = defaultdict(int)
    acked = ack_missing = without_target = prep_acks = 0
    for op in operations:
        client = trace.client.get(op, {})
        ack = _first(client.get("submission_acknowledged", ()))
        send = _first(client.get("submission_sent", ()))
        acked += int(ack is not None)
        ack_missing += int(send is not None and ack is None)
        send_time = _interval(send, ack, clock_error_ms)
        if send_time:
            send_times.append(send_time)
        roles = grouped[op]
        entry = _first(e for a in roles["target"] for e in
                       trace.assignments.get(a["assignment_id"], {}).get("stage_run_entered", ()))
        latency = _interval(ack, entry, clock_error_ms)
        if latency:
            durations.append(latency)
        elif ack and op not in trace.prepare_only:
            without_target += 1
        prep_acks += int(ack is not None and op in trace.prepare_only)
        handoffs = _handoff(trace, op, roles, targets[op], clock_error_ms)
        if isinstance(op, str) and op not in trace.prepare_only:
            handoff_samples.extend(h["intervals"] for h in handoffs)
        for role, attempts in roles.items():
            for a in attempts:
                phase_samples[role].append(a["intervals"])
                prequeue_counts[role][a["prequeue_status"]] += 1
                if a["prequeue_wait_seconds"] is not None:
                    prequeue_samples[role].append(a["prequeue_wait_seconds"])
                if a["assignment_id"]:
                    value = a["confirmed_eligible_request_ready_seconds"]
                    if value is not None:
                        eligible[role].append(value)
                    else:
                        unknown[role] += 1
            attempts.sort(key=lambda a: (a["admission_id"] or "", a["stage_work_id"] or "",
                                         a["ready_projection_revision"] or 0, a["assignment_id"] or ""))
        op_id = op[1] if isinstance(op, tuple) else op
        if operation is None or operation == op_id:
            reports.append({"operation_id": op_id, "direct_submission": isinstance(op, tuple),
                            "send_to_ack": send_time, "ack_to_first_target_entry": latency,
                            "observed_preparation_work": sorted(trace.bulk.get(op, {}).values(),
                                                                key=lambda row: (row["started_at"], row["action"])),
                            "attempts": roles, "handoffs": handoffs})
    reports.sort(key=lambda r: (r["ack_to_first_target_entry"] is None,
                                -(_seconds(r["ack_to_first_target_entry"]) or 0), r["operation_id"]))
    cross = sum(i["clock"] == "utc" for i in durations)
    any_cross = any(i["clock"] == "utc" for i in [*send_times, *durations])
    for samples in [*phase_samples.values(), handoff_samples]:
        any_cross |= any(i and i["clock"] == "utc" for s in samples for i in s.values())
    return {
        "unit": "seconds", "first_send_to_first_ack": _distribution(i["seconds"] for i in send_times),
        "ack_to_first_target_entry": _distribution(i["seconds"] for i in durations),
        "submissions_without_acknowledgement": ack_missing, "acknowledgements": acked,
        "acknowledgements_without_target_entry": without_target, "preparation_only_acknowledgements": prep_acks,
        "different_clock_samples": cross, "utc_difference_uncertainty_seconds": (
            0 if not any_cross else None if clock_error_ms is None else 2 * clock_error_ms / 1000),
        "observed_request_ready_and_eligible_to_reservation": {
            role: {**_distribution(eligible[role]), "unknown": unknown[role]} for role in ("preparation", "target")},
        "phase_distributions": {role: {name: _stats(s.get(name) for s in phase_samples[role]) for name in _PHASES}
                                for role in ("preparation", "target")},
        "prequeue_distributions": {
            role: {"coverage": dict(prequeue_counts[role]),
                   "reason_seconds": {reason: _distribution(row.get(reason, 0) for row in prequeue_samples[role])
                                      for reason in sorted({k for row in prequeue_samples[role] for k in row})}}
            for role in ("preparation", "target")
        },
        "handoff_distributions": {name: _stats(s.get(name) for s in handoff_samples) for name in _HANDOFF},
        "submissions": reports if operation is not None else reports[:slowest],
        "reservations_without_admission_link": sum(
            e.attrs.get("admission_id") not in trace.admissions for a in trace.assignments.values()
            for e in [_first(a.get("reservation_committed", ()))] if e is not None),
        "stage_entries_without_reservation_link": sum(
            "stage_run_entered" in a and "reservation_committed" not in a for a in trace.assignments.values()),
    }


def _records(paths):
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if '"loom.phase_timings"' in line:
                    try:
                        value = json.loads(line[line.index("{"):])
                    except ValueError:
                        continue
                    if isinstance(value, dict):
                        yield value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--clock-error-ms", type=float,
                        help="independently established maximum absolute UTC error per participating clock")
    parser.add_argument("--slowest", type=int, default=10, help="number of submission timelines to include")
    parser.add_argument("--operation", help="select one operation ID or direct-submission queue item for detail")
    args = parser.parse_args()
    if args.slowest < 0:
        parser.error("--slowest must be nonnegative")
    if args.clock_error_ms is not None and (not isfinite(args.clock_error_ms) or args.clock_error_ms < 0):
        parser.error("--clock-error-ms must be finite and nonnegative")
    print(json.dumps(summarize(_records(args.logs), clock_error_ms=args.clock_error_ms,
                               slowest=args.slowest, operation=args.operation), indent=2))


if __name__ == "__main__":
    main()

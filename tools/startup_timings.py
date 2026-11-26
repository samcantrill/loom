"""Summarize single-stage Loom submissions from combined client, coordinator and agent logs."""
from __future__ import annotations

import argparse
from collections import defaultdict
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


def _stamp(span):
    attrs = span["attributes"]
    domain = (attrs.get("host"), attrs.get("process_id"), attrs.get("process_origin_ns"))
    return datetime.fromisoformat(span["started_at"]), domain, attrs.get("monotonic_ns")


def _elapsed(start, finish):
    before, start_domain, start_ns = start
    after, end_domain, end_ns = finish
    if None not in start_domain and start_domain == end_domain and start_ns is not None and end_ns is not None:
        return (end_ns - start_ns) / 1e9, False
    return (after - before).total_seconds(), True


def summarize(records, *, clock_error_ms=None):
    """Use nearest-rank quantiles; expose missing evidence and offset uncertainty."""
    sent, acknowledgements, admissions, reservations, entries, summaries = {}, {}, {}, {}, {}, {}
    prepare_only = set()
    for record in records:
        if record.get("diagnostic") != "loom.phase_timings":
            continue
        for span in record.get("spans", ()):
            action = span.get("action")
            a = span.get("attributes") or {}
            operation = span.get("operation_id") or record.get("operation_id")
            if action in {"submission_sent", "submission_acknowledged"}:
                if a.get("submit_method") == "submit":
                    operation = ("direct", a.get("queue_item_id") or a.get("admission_id"))
                    if a.get("admission_id"):
                        admissions[a["admission_id"]] = operation, "target"
                if not operation:
                    continue
                if a.get("submit_method") == "prepare_run":
                    prepare_only.add(operation)
                table = sent if action == "submission_sent" else acknowledgements
                stamp = _stamp(span)
                if operation not in table or stamp[0] < table[operation][0]:
                    table[operation] = stamp
            elif action == "admission_committed" and operation:
                admissions[a["admission_id"]] = operation, a["role"]
            elif action == "reservation_committed":
                reservations[a["assignment_id"]] = a["admission_id"]
            elif action == "stage_run_entered" and a.get("assignment_id"):
                stamp = _stamp(span)
                if a["assignment_id"] not in entries or stamp[0] < entries[a["assignment_id"]][0]:
                    entries[a["assignment_id"]] = stamp
            elif action == "attempt_scheduling_summary" and a.get("result") == "reserved":
                summaries[a["assignment_id"]] = a

    latency = []
    by_role = defaultdict(list)
    unknown = defaultdict(int)
    target_entries = defaultdict(list)
    cross_clock = 0
    for assignment, admission in reservations.items():
        if admission not in admissions:
            continue
        operation, role = admissions[admission]
        summary = summaries.get(assignment)
        if summary and summary["saw_eligible_offer"]:
            by_role[role].append(summary["eligible_request_ready_ns"] / 1e9)
        else:
            unknown[role] += 1
        if role == "target" and assignment in entries and operation in acknowledgements:
            target_entries[operation].append(entries[assignment])
    for operation, stamps in target_entries.items():
        duration, different = _elapsed(acknowledgements[operation], min(stamps, key=lambda t: t[0]))
        latency.append(duration)
        cross_clock += int(different)

    ack_times = [_elapsed(sent[key], ack) for key, ack in acknowledgements.items() if key in sent]
    across = cross_clock + sum(int(different) for _, different in ack_times)

    return {
        "unit": "seconds", "first_send_to_first_ack": _distribution(value for value, _ in ack_times),
        "ack_to_first_target_entry": _distribution(latency),
        "submissions_without_acknowledgement": len(sent.keys() - acknowledgements.keys()),
        "acknowledgements": len(acknowledgements),
        "acknowledgements_without_target_entry": len(acknowledgements.keys() - target_entries.keys() - prepare_only),
        "preparation_only_acknowledgements": len(acknowledgements.keys() & prepare_only),
        "different_clock_samples": cross_clock,
        "utc_difference_uncertainty_seconds": (
            0 if across == 0 else None if clock_error_ms is None else 2 * clock_error_ms / 1000
        ),
        "observed_request_ready_and_eligible_to_reservation": {
            role: {**_distribution(by_role[role]), "unknown": unknown[role]}
            for role in ("preparation", "target")
        },
        "reservations_without_admission_link": sum(id_ not in admissions for id_ in reservations.values()),
        "stage_entries_without_reservation_link": sum(id_ not in reservations for id_ in entries),
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
    args = parser.parse_args()
    if args.clock_error_ms is not None and (not isfinite(args.clock_error_ms) or args.clock_error_ms < 0):
        parser.error("--clock-error-ms must be finite and nonnegative")
    print(json.dumps(summarize(_records(args.logs), clock_error_ms=args.clock_error_ms), indent=2))


if __name__ == "__main__":
    main()

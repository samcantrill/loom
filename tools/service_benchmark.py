"""Opt-in, isolated service measurements using the real TLS integration fixture.

Run with the locked dev environment from the repository root, for example:
``uv run --locked --group dev python -m tools.service_benchmark --seconds 10``.
Never attaches to, changes or cancels deployed services. Only fixture-owned work
is started and cleaned up. Counters are in memory and emitted once per window.
CPU covers the coordinator, agent and TLS threads in this process, not children.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from functools import wraps
import json
import sqlite3
from threading import Lock
import time

import pytest

from loom.queue import LocalDaemon, LocalDaemonAdmissionRequest, QueueServiceError
from loom.queue import agent_session_transport as transport
from loom.queue import deployment
from loom.queue.gpu.occupancy import NvidiaSmiGpuProcessObserver
from tests.integration.queue.test_concurrent_outbound_agent import (
    _eventually,
    _rows,
    _service,
    _submit,
)
from tests.integration.queue.test_agent_session_transport import _prepare_remote_sleep_run


class Counters:
    def __init__(self) -> None:
        self.lock = Lock()
        self.values: Counter[str] = Counter()

    def increment(self, name: str) -> None:
        with self.lock:
            self.values[name] += 1

    def snapshot(self) -> Counter[str]:
        with self.lock:
            return self.values.copy()

    def wrap(self, patch, owner, name, metric):
        original = getattr(owner, name)

        @wraps(original)
        def measured(*args, **kwargs):
            self.increment(metric)
            return original(*args, **kwargs)

        patch.setattr(owner, name, measured)


@contextmanager
def measured_calls(patch):
    counters = Counters()
    counters.wrap(patch, LocalDaemon, "reconcile_once", "reconciliation_cycles")
    counters.wrap(patch, transport, "https_connection", "tls_connections_created")
    counters.wrap(patch, NvidiaSmiGpuProcessObserver, "observe", "gpu_occupancy_queries")
    connect = sqlite3.connect

    def trace(statement):
        if statement.lstrip().upper().startswith("PRAGMA TABLE_INFO"):
            counters.increment("schema_table_checks")

    def counted_connect(*args, **kwargs):
        counters.increment("database_connections_opened")
        connection = connect(*args, **kwargs)
        connection.set_trace_callback(trace)
        return connection

    patch.setattr(sqlite3, "connect", counted_connect)
    exchange = transport._exchange_agent_request

    @wraps(exchange)
    def counted_exchange(config, operation, *args, **kwargs):
        if operation in {"control", "assignment_control", "wait_controls"}:
            counters.increment("control_requests")
        if operation == "renew":
            counters.increment("resource_renewals")
        return exchange(config, operation, *args, **kwargs)

    patch.setattr(transport, "_exchange_agent_request", counted_exchange)
    yield counters


def sample(counters, scenario, seconds):
    before = counters.snapshot()
    cpu = time.process_time()
    started = time.monotonic()
    time.sleep(seconds)
    elapsed = time.monotonic() - started
    cpu = time.process_time() - cpu
    print(json.dumps({
        "scenario": scenario,
        "wall_seconds": round(elapsed, 3),
        "process_cpu_seconds": round(cpu, 3),
        "one_core_cpu_percent": round(100 * cpu / elapsed, 2),
        "counters": dict(counters.snapshot() - before),
        "scope": "isolated coordinator+agent+TLS; child CPU excluded",
    }), flush=True)


def released(case):
    return not _rows(
        case.agent_root / "journal.sqlite",
        "SELECT assignment_id FROM assignments WHERE state != 'released'",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--history", type=int, default=4)
    parser.add_argument("--coordinator-interval", type=float, default=None)
    args = parser.parse_args()
    if not 0 < args.seconds <= 15 or not 1 <= args.history <= 100:
        parser.error("seconds must be in (0, 15]; history must be in [1, 100]")
    with pytest.MonkeyPatch.context() as patch, measured_calls(patch) as counters:
        with _service(patch) as case:
            # The fixture normally accelerates test polling; benchmark production
            # timing instead, allowing an already-pending test poll to finish.
            patch.setattr(deployment, "_OUTBOUND_POLL_WAIT_MS", 5000)
            if args.coordinator_interval is not None:
                case.daemon.config = replace(
                    case.daemon.config, poll_interval_seconds=args.coordinator_interval
                )
            time.sleep(1)
            sample(counters, "healthy_idle", args.seconds)

            uri, _ = _prepare_remote_sleep_run(
                case.store, run_name="benchmark-sleep", machine_id="agent-a"
            )
            case.client.submit(LocalDaemonAdmissionRequest("benchmark-sleep", uri))
            _eventually(lambda: _rows(
                case.agent_root / "journal.sqlite",
                "SELECT assignment_id FROM assignments WHERE state = 'process_started'",
            ), seconds=60)
            sample(counters, "running_without_output", args.seconds)
            case.client.wait("benchmark-sleep", timeout_seconds=90)
            _eventually(lambda: released(case))

            for index in range(args.history):
                name = f"benchmark-history-{index}"
                _submit(case, name)
                case.client.wait(name, timeout_seconds=90)
            _eventually(lambda: released(case))
            sample(counters, "retained_terminal_history", args.seconds)

            execution = case.daemon._execution
            assert execution is not None
            reconcile = execution.reconcile_admission

            def unavailable(admission):
                if admission.queue_item_id == "benchmark-recovery":
                    counters.increment("recovery_attempts")
                    raise QueueServiceError("benchmark recoverable owner outage")
                return reconcile(admission)

            with patch.context() as failure_patch:
                failure_patch.setattr(execution, "reconcile_admission", unavailable)
                _submit(case, "benchmark-recovery")
                sample(counters, "recoverable_error", args.seconds)
            case.daemon._wake.set()
            case.client.wait("benchmark-recovery", timeout_seconds=90)
            _eventually(lambda: released(case))


if __name__ == "__main__":
    main()

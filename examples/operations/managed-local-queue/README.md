# Managed Local Queue Operations

This dependency-free example is the recommended starting point for one
managed-local pool. It builds `ManagedLocalQueueRuntime.from_spec(...)` from a
schema-v2 spec with one config-owned controller owner, two generic accelerator
slots, queue-owned logs, and three short commands. The first command requests
both slots; the later one-slot commands demonstrate refill.

```sh
uv run python examples/operations/managed-local-queue/run_managed_local_queue.py
```

Each invocation writes a new `run-*` directory below `LOOM_EXAMPLE_OUTPUT_ROOT`
(or this directory's `output/`). Rerunning preserves earlier SQLite evidence
and separate stdout/stderr logs. The active output is deliberately redacted,
but proves that `item-1` owns two distinct slots and is
`source=same_session_live`.

## Public Python Surface

The runtime constructs and keeps alive the queue service, local adapter,
controller, and authored static-slot provider. Do not manually give those
objects different owners or copy a controller timing loop. A long-lived process
normally installs a signal handler that sets a `threading.Event` and lets
`serve()` own maintenance and shutdown:

```python
from threading import Event
import signal

from loom.queue.managed_local import ManagedLocalQueueRuntime

runtime = ManagedLocalQueueRuntime.from_spec(
    spec, workspace_id="project-workspace", coordination_store=store
)
stop = Event()
signal.signal(signal.SIGTERM, lambda *_args: stop.set())
signal.signal(signal.SIGINT, lambda *_args: stop.set())
runtime.serve(stop, shutdown_mode="drain", shutdown_timeout_seconds=120)
```

`runtime.start()` and `runtime.run_cycle()` remain useful narrow test and
advanced-control seams. `serve()` is the normal foreground operation. The
example's finite harness only sets its event after all work completes; it does
not implement its own maintenance loop.

## Ownership And Status Truth

One runtime is deployed for one pool. `controller.owner_id` is the only owner
value: it reaches claims, local-adapter evidence, and same-session status
matching. The runtime owns process-local object lifetime, wake timing, health,
recovery gating, and drain/cancel choice. The controller owns reconcile before
fill and its local active limit; the provider owns physical placement and
member leases; the coordination authority owns lease capacity, expiry, and
fencing. An external supervisor/operator owns containment of a prior process
tree after a crash.

`READY` means the current runtime can reconcile/fill. `DEGRADED` prevents
refill after a current-session problem; a healthy later reconciliation is
required before it becomes ready again. `RECOVERY_REQUIRED` blocks claiming
when selected-pool work belongs to a previous session. On normal stop,
`DRAINING` stops new claims but continues maintenance until current work is
terminal. `shutdown_mode="cancel"` enters `CANCELLING`; a timeout reports the
remaining work and never force-releases its leases. Successful shutdown ends in
`STOPPED`.

Pool status combines distinct scopes: queue facts and assignment/log evidence
are persisted, `same_session_live` is only an observation by this in-process
runtime, and hardware health plus current lease liveness are not observed. A
persisted expiry is never proof that a device is available.

## Recovery And Supervision

After a crash, contain the old process group with the external supervisor
first. Loom does not kill by PID, reattach, take over, renew, or release foreign
leases. Once an operator has confirmed containment, resolve exactly one foreign
item at a time as `UNKNOWN` with an explicit audit assertion:

```python
runtime.resolve_recovery_unknown(
    "item-17",
    previous_processes_confirmed_stopped=True,
    requested_by="queue-operator",
    reason="supervisor confirmed the prior control group stopped",
)
```

The boolean is an operator attestation, not automatic process verification.
For POSIX's built-in local runner, a small systemd unit can make containment
explicit:

```ini
[Service]
ExecStart=/path/to/project/.venv/bin/python -m project.queue_runtime
KillMode=control-group
TimeoutStopSec=120
```

This is an illustrative deployment pattern, not a Loom daemon or a required
Linux acceptance environment.

## Two Slots Or An Indivisible Bundle

For independent devices, use the standard generic request from this example:

```python
resources={"accelerator": 2}
```

The authored static assignment binds both values to
`LOOM_ASSIGNED_ACCELERATORS` (a project may instead use a conventional name
such as `CUDA_VISIBLE_DEVICES`). Loom does not discover, validate, or report
vendor hardware.

If two members must be allocated as one topology-specific placement, copy and
adapt [`paired_assignment_provider.py`](paired_assignment_provider.py). It is
project-owned placement code, not a stable Loom import. Its key rule is that
bundle acquisition leases `accelerator-slot-a` and `accelerator-slot-b` -- the
same physical coordination keys used by the individual static allocator -- and
rolls back any first member if the second cannot be acquired. It implements
acquire, renew, and release over every member and produces a two-value
environment binding. It never uses a synthetic bundle key or accesses queue
repositories/controller mutation.

The controller's active limit is local to this runtime, not a distributed item
quota. For broader candidate selection, generic scheduling, device health,
reattachment, or resource-use telemetry, retain the later Stage 25/26 design
boundaries rather than extending this example.

# Loom monitor

The repository-local read-only Textual monitor connects to an existing native
coordinator using its Unix socket or protected HTTPS client connection file:

```sh
uv run python -m tools.loom_monitor /path/to/coordinator-client.yaml
uv run python -m tools.loom_monitor /run/loom/coordinator.sock
uv run python -m tools.loom_monitor --demo
```

The monitor paginates native admissions and reads admission detail and authority
facts. Scheduler rows show the submit agent's retained observations; the monitor
does not contact SLURM or write scheduler snapshots. The coordinator grouping
is not a discovered resource pool, and unavailable capacity remains unknown.
Local logs are available only where the inspecting host can read the retained
path. Failed collectors keep their last successful value marked stale.

Admission, authority and scheduler statuses remain separate. No cancel, retry,
recovery or scheduler mutation bindings exist. Closing the monitor closes only
its client connection. Refresh is independent of the selected tab; Space pauses,
r refreshes, f changes the work filter and Escape returns to the work table.

The demo uses in-memory native-shaped observations. It creates no queue database,
starts no service and executes no stages. `--demo-speed` controls its display
clock and `--demo-scenario` labels the selected evidence mix. A retained demo
output directory is presentation scratch space, not execution evidence.

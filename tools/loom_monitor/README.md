# Loom monitor

`tools.loom_monitor` is a repository-local, read-only Textual interface for one
configured Loom queue. It answers three operational questions in order:

1. Is any work failed, uncertain, or recovery-required?
2. Which queue item, run, stage, process, or scheduler job is involved?
3. Which queue, authority, scheduler, or materialization evidence supports that
   conclusion?

Run it from the repository root with a trusted queue configuration:

```bash
uv run python -m tools.loom_monitor path/to/queue.yaml
```

To explore the interface without a running Loom service, open the isolated demo:

```bash
uv run python -m tools.loom_monitor --demo
```

The demo writes a real temporary SQLite queue and drives deterministic mock work
through queued, claimed, dispatched, successful, failed, cancelled, unknown, and
capacity-deferred states. Authority summaries, stage progress, scheduler jobs,
logs, timelines, and one deliberate lifecycle disagreement are simulated at
their external observation boundaries. The header includes `DEMO`; no process,
authority service, or scheduler is started.

Use a faster lifecycle or a focused evidence mix with:

```bash
uv run python -m tools.loom_monitor --demo --demo-speed 2
uv run python -m tools.loom_monitor --demo --demo-scenario failures
uv run python -m tools.loom_monitor --demo --demo-scenario scheduler
```

The generated workspace is removed on exit by default. Preserve its queue,
config, and any inspected logs beneath a newly created `demo-*` directory with:

```bash
uv run python -m tools.loom_monitor --demo --demo-output .loom/monitor-demos
```

`--demo-seed INTEGER` changes deterministic process and scheduler identities.
Pause refresh with `Space` when you want to inspect a snapshot. Press `f` to
cycle from the initial all-work view through the narrower work views.

Queue state, visible and selected runs, authority readiness, selected-item
evidence, selected delegated jobs, and selected-stage logs refresh
automatically at 1 Hz. Polling is independent of the open detail tab; `r`
requests an immediate refresh and `Space` pauses or resumes automatic polling.
Use `--help` to tune the independent cadences.

The interface uses blue (`#3BB9FF`) for its borders, bold labels, and
scrollbars, with a subdued grey (`#3A3A3A`) footer. Queue, run, stage, and
scheduler lifecycle states always remain visible as words.

The initial screen includes source readiness, pool summaries, a filterable work
table, queue/run/execution detail, finite stage and submitted-job progress,
bounded plain-text log following, a source-tagged timeline, and an evidence
ledger. Below 112 columns, selecting a work row opens its detail as a full-width
view and `Esc` returns to the list.

Important semantics:

- `Queue READABLE` means the durable queue repository was read. It does not mean
  a dispatcher is alive.
- A separate monitor reports `Runtime UNOBSERVED`; it does not infer `STOPPED`.
- Queue, authority, and scheduler lifecycle values remain separate. `DIVERGENT`
  calls attention to disagreement but does not synthesize a new true state.
- Failed collectors retain their last successful value and display it as stale.
- Scheduler and log inspection remain bounded to the selected delegated run and
  selected stage, respectively, but poll whether or not their tabs are active.
- There are no cancel, retry, recovery, or scheduler mutation bindings.

Here, read-only means that the monitor never requests a lifecycle or scheduler
action. Loom's existing live SLURM status inspection may persist its allowlisted
scheduler observation snapshot, just as `loom status --jobs` does.

The tool intentionally does not add a Loom runtime command or public schema.
Host telemetry, domain-specific progress, multiple workspaces, notifications,
and runtime ownership remain outside this prototype.

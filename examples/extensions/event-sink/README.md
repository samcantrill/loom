# Observe-Only Event Sink

This example uses direct `EventSinkRegistry` registration as the primary
integration path. The capture sink receives committed `PipelineEventRecord`
values for run start, stage completion, and run completion. A second sink fails
on `run.completed`; Loom records that observer failure while the pipeline still
succeeds.

## Public Python Surface

The entrypoint constructs `EventSinkRegistry`, registers two callables, and
supplies it in `RunRequest(event_sink_registry=...)`. Sinks are observe-only:
they do not control lifecycle state or retry the pipeline. A sink may subscribe
to an exact allowlist; unfiltered registrations continue to observe all events.

```python
registry.register(
    "notifications.completed",
    project_sink,
    subscription=EventSinkSubscription(event_types=("stage.completed", "run.failed")),
)
```

## Lifecycle Event Vocabulary

Subscriptions use these exact event names. The named owner dispatches only
after it has committed the corresponding lifecycle fact; a direct stage worker
does not construct sinks because its parent owns those commits.

| Event types | Lifecycle owner |
| --- | --- |
| `run.created`, `run.opened`, `run.planned`, `run.started`, `run.completed`, `run.cancelled`, `run.failed`, `run.preparation_failed` | `PipelineRunner`; `stage-job` also owns its self-finalizing `run.completed` and `run.failed` transitions. |
| `run.interrupted` | `PipelineRunner` recovery path. |
| `stage.planned`, `stage.stale`, `stage.blocked`, `stage.reused`, `stage.skipped` | `PipelineRunner`. |
| `stage.started`, `stage.completed`, `stage.failed`, `stage.cancelled` | `PipelineRunner`; `stage-job` owns the equivalent events when it commits that stage attempt. |
| `cleanup.report.recorded`, `cleanup.result.recorded` | Cleanup operation owner, after its report/result fact is recorded. |

## Discord Webhook Package

The [Discord webhook event sink](../discord-webhook/README.md) is a concrete
downstream package with an installed `loom.event_sinks:notifications.discord`
entry point. It uses an exact terminal-run subscription, a process-local
webhook secret, bounded content, mention suppression, and sanitized best-effort
failures. It is not a Loom notification API or delivery receipt.

## Why Hooks Are Separate

An event sink observes an already committed fact and its return value is
ignored. A hook that can reject, replace, retry, or otherwise alter execution
would need a decision owner, ordering, failure policy, validation, provenance,
and resume contract. Loom therefore adds no mutable hook bus here. A later
accepted use case should define one narrow immutable-input hook at its existing
decision owner.

## Plugin Packaging Snippet

For a separately distributed plugin, expose a callable through the installed
event-sink entry-point group and load it into a caller-provided registry. This
example intentionally does not install a package; direct registration is the
smallest runnable path.

```toml
[project.entry-points."loom.event_sinks"]
completed = "my_package.observers:completed_sink"
```

```python
def completed_sink():
    return EventSinkRegistration(
        sink=ProjectSlackSink.from_environment(),
        subscription=EventSinkSubscription(event_types=("stage.completed",)),
    )
```

## Run

```sh
uv run python examples/extensions/event-sink/run_event_sink.py
```

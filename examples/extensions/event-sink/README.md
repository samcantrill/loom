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

## Slack Or Discord Sink Recipe

Slack and Discord are ordinary downstream sink integrations, not Loom
notification APIs. A project factory can return an `EventSinkRegistration` with
an exact subscription, then map the received event reference to a small message
using its own HTTP client, timeout, credential source, response handling, and
provider format. Slack accepts a JSON `text` payload; Discord accepts `content`
and projects should disable unintended mentions with `allowed_mentions`.

Keep webhook URLs in the lifecycle-owning process environment or a deployment
secret provider. Do not place them in pipeline config, plugin activation
records, metadata, provenance, exceptions, or fixtures. Callback failures and
optional observer links are best-effort evidence, not delivery receipts;
retries, buffering, rate limits, and guaranteed delivery need a later outbox or
external relay design.

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

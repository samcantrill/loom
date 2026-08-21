# Observe-Only Event Sink

This example uses direct `EventSinkRegistry` registration as the primary
integration path. The capture sink receives committed `PipelineEventRecord`
values for run start, stage completion, and run completion. A second sink fails
on `run.completed`; Loom records that observer failure while the pipeline still
succeeds.

## Public Python Surface

The entrypoint constructs `EventSinkRegistry`, registers two callables, and
supplies it in `RunRequest(event_sink_registry=...)`. Sinks are observe-only:
they do not control lifecycle state or retry the pipeline.

## Plugin Packaging Snippet

For a separately distributed plugin, expose a callable through the installed
event-sink entry-point group and load it into a caller-provided registry. This
example intentionally does not install a package; direct registration is the
smallest runnable path.

```toml
[project.entry-points."loom.event_sinks"]
audit = "my_package.observers:audit_sink"
```

## Run

```sh
uv run python examples/extensions/event-sink/run_event_sink.py
```

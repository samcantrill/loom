# Observe-Only Event Sink

This example runs through the native coordinator/agent lifecycle. Its protected
coordinator configuration selects `event_observers.capture` and
`event_observers.fail_completed`, each returning `EventSinkRegistration`.
The capture callback receives committed events; the second intentionally fails
on completion. The scientific run still succeeds and retains its observer failure.

The helper configures an explicit fresh local deployment. Factories construct in
the coordinator after root guards, once per process startup. Selection is
coordinator-wide. Clients, preparation workers and stage workers do not load sinks.
A subscription on the returned registration can filter exact event names.

Callbacks run synchronously with coordinator privileges and must bound IO.
Events are committed before dispatch, but state commit/event append/callback are
separate steps: crashes can omit an event or delivery. Restart and same-ID replay
do not resend history. There is no durable delivery queue or notification retry.
Callback-record persistence failures are visibly diagnostic and do not fail runs.

```sh
uv run --extra config python examples/extensions/event-sink/run_event_sink.py
```

The [Discord example](../discord-webhook/README.md) supplies an installed downstream
factory using a protected environment secret. See [event and reliability behavior](../../../docs/features/reliability.md#event-hooks)
for event vocabulary, authority ownership and delivery limits.

## Public Python Surface

Installed factories return `EventSinkRegistration`. Native coordinator events are observed through the selected `EventSinkRegistry`.

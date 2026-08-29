# Extensions Examples

Extensions examples show narrow, explicit integrations built on public Loom
extension points.

## Public Python API Workflows

| Example | Demonstrates |
| --- | --- |
| `extensions.event-sink` | Direct instance-local event sink registration, committed lifecycle observation, and isolated observer failure facts. |
| `extensions.discord-webhook` | A manual downstream package with terminal-run webhook notifications and a same-host coordinator progress reporter. |

## Run

```sh
uv run python examples/extensions/event-sink/run_event_sink.py
```

The [Discord webhook package](discord-webhook/README.md) is manual because it
needs a user-managed credential and sends a real external request. Its
coordinator reporter also needs access to the same-user local daemon socket.

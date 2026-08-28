# Discord Webhook Event Sink and Coordinator Reporter

`loom-discord` is a small downstream package that turns selected committed Loom
events into Discord webhook messages, and includes a coordinator sidecar that
polls local managed-run status. Both are intentionally best effort: Discord
delivery never changes a Loom run result or delays coordinator scheduling.

## Setup

Create an [incoming webhook](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)
for the intended Discord channel, then provide its URL through the environment
of the process that owns lifecycle commits. Do not put the URL in a pipeline
config, `--plugin` argument, metadata, or a fixture.

```sh
export LOOM_DISCORD_WEBHOOK_URL="$(your-secret-command)"
uv pip install --editable examples/extensions/discord-webhook
```

The package installs `loom.event_sinks:notifications.discord`. Its default
subscription is exactly `run.cancelled`, `run.completed`, `run.failed`,
`run.interrupted`, and `run.preparation_failed`.

## Coordinator Progress Reporter

Run the reporter on the coordinator host as the same OS user that owns the
protected local daemon Unix socket. It reads that socket directly; it does not
open a remote status endpoint or control the coordinator.

After installing this package and setting `LOOM_DISCORD_WEBHOOK_URL`, send one
credential-free smoke-test request (the secret remains in the environment):

```sh
loom-discord-coordinator --endpoint /path/to/coordinator/daemon.sock --once
```

For continuous reporting, place the command in a service manager under that
same account. Choose modest positive finite polling and heartbeat intervals:

```sh
loom-discord-coordinator \
  --endpoint /path/to/coordinator/daemon.sock \
  --interval 60 \
  --heartbeat 900
```

The initial status sends once. Later polls send only after a meaningful health,
admission, authority run, or authority stage change; `--heartbeat` forces the
current summary after that interval passes without another report attempt. The
report labels its non-atomic `as_of`, service
health/diagnostic, exact admission and authority counts, plus bounded active
queue-item details: admission and authority state, successful stages over total,
and running/submitted stage names. It never includes a run URI, raw owner view,
assignment, process, agent, session, scheduler, control, revision, receipt,
log, config, or payload identifier.

One-shot status or delivery failure exits nonzero with a sanitized diagnostic.
In continuous mode the sidecar prints a sanitized local diagnostic and keeps
polling. There is no durable cursor, retry queue, outbox, delivery receipt, or
guarantee; restart intentionally sends a fresh initial summary. Automated tests
fake both the socket and Discord, so live availability remains a manual check.

For example, a service manager should run both processes as the socket-owning
account and inject the webhook URL from a protected environment file:

```ini
[Service]
User=loom
EnvironmentFile=/etc/loom/discord.env
ExecStart=/opt/loom/bin/loom-discord-coordinator --endpoint /srv/loom/coordinator/daemon.sock --interval 60 --heartbeat 900
Restart=on-failure
```

Keep the environment file owner-readable only and adapt the user, executable,
and socket paths to the deployment. The reporter is independent of the
coordinator service's success and restart policy.

## Public Python Surface

For a direct Python integration, construct the factory in the process that
creates the `RunRequest`, then register its returned subscription unchanged.

```python
from loom.pipeline.event_sinks import EventSinkRegistry
from loom_discord import discord_event_sink

registration = discord_event_sink()
registry = EventSinkRegistry()
registry.register(
    "notifications.discord",
    registration.sink,
    subscription=registration.subscription,
)
```

Run the included manual pipeline after the package is installed and the secret
is available:

```sh
uv run python examples/extensions/discord-webhook/run_discord_webhook.py
```

## CLI Selection

Select the installed entry point explicitly; the webhook URL remains only in
the lifecycle-owning process environment.

```sh
cd examples/extensions/discord-webhook
loom run pipeline.yaml --plugin loom.event_sinks:notifications.discord
```

For a prepared run or SLURM continuation, inject the secret only into the
parent, `stage-job`, or continuation process that commits the relevant terminal
event. Do not pass it in command arguments or authored configuration. Direct
stage workers do not own terminal run commits and do not construct event sinks.

## Delivery Boundary

Each selected event sends only its event type, run URI, occurrence time, and a
stage name when its primary resource is a stage. Content is clipped to Discord's
2,000-character limit and disables all mention parsing. The request uses
`wait=true` and a finite timeout, following Discord's
[execute-webhook contract](https://docs.discord.com/developers/resources/webhook#execute-webhook).

The manual runner prints `notification_status: accepted` only after Discord
returns a successful response. A failed notification remains recorded beside
the event and leaves `run_status: SUCCEEDED`, while the wrapper exits nonzero so
an operator does not mistake the report for delivered.

This example has no retry, rate-limit sleep, background queue, durable outbox,
message editing, attachment support, or delivery guarantee. Discord advises
clients to follow returned rate-limit headers rather than hard-code quotas; a
deployment that needs retry or buffering should use an external durable relay.
Automated tests use a fake HTTP transport; they do not prove Discord
availability.

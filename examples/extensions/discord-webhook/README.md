# Discord Webhook Event Sink and Coordinator Reporter

`loom-discord` is a small downstream package that turns selected committed Loom
events into Discord webhook messages, and includes a coordinator sidecar that
polls local managed-run status. Both are intentionally best effort: Discord
delivery never changes a Loom run result. Selected lifecycle callbacks run
synchronously and their bounded IO can delay coordinator scheduling. The separate
progress reporter has its own lifetime.

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

## Coordinator Selection

Add this fragment to the protected coordinator service configuration after
installing the package in that service's environment:

```json
{"event_sinks": [{"name": "notifications.discord", "factory": {
  "_target_": "loom_discord.discord_event_sink"
}}]}
```

The factory returns its terminal-event subscription unchanged. It constructs in
the coordinator, not the calling client. Inject `LOOM_DISCORD_WEBHOOK_URL` only
into that protected coordinator environment. Workers and agents do not need it.
The installed entry point remains package metadata; the native service selects
the explicit factory without discovery or a `--plugin` option.

The included example creates a configured fresh native local deployment:

```sh
uv run --extra config python examples/extensions/discord-webhook/run_discord_webhook.py
```

This command sends real notifications when explicitly run with a configured URL.
Automated validation uses fake HTTP responses only.

## Delivery Boundary

Each selected event sends only its event type, run URI, occurrence time, and a
stage name when its primary resource is a stage. Content is clipped to Discord's
2,000-character limit and disables all mention parsing. The request uses
`wait=true` and a finite timeout, following Discord's
[execute-webhook contract](https://docs.discord.com/developers/resources/webhook#execute-webhook).

The native example selects `loom_discord.discord_event_sink` in protected
coordinator `event_sinks` configuration; the URL stays in the coordinator environment.
It prints `notification_status: no_failure_recorded` when no failure evidence was
retained. This is not a delivery guarantee. A failed notification remains recorded beside
the event and leaves `run_status: SUCCEEDED`, while the example exits nonzero so
an operator does not mistake the report for delivered.

This example has no retry, rate-limit sleep, background queue, durable outbox,
message editing, attachment support, or delivery guarantee. Discord advises
clients to follow returned rate-limit headers rather than hard-code quotas; a
deployment that needs retry or buffering should use an external durable relay.
Automated tests use a fake HTTP transport; they do not prove Discord
availability.

Lifecycle callbacks construct once per coordinator startup, apply coordinator-wide,
and survive client detachment. A deliberate same-root restart loads the current
protected selection for future events. Commit, event append and callback are
separate steps; a crash can omit an event or delivery. Queries, restart and same-ID
run replay do not resend historical notifications. Observer-record persistence
failures are logged visibly and never change scientific status.

## Public Python Surface

Protected native coordinator factories return `EventSinkRegistration`; the installed extension implements `DiscordWebhookEventSink` and its coordinator reporter.

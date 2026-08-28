# Roadmap Stage 31 Planning: Discord Webhook Event Sink

Status: approved
Roadmap stage: 31
Evidence tree: `/home/can134/work/active/loom` at `e5ad16d`; relevant dirty paths: none
Planning route: lean; the external-service and secret boundaries reuse the locked Stage 20/28 observer contracts and the Stage 30 example harness
Current gate: passed; ready for implementation
Blockers: none

This file is current authoritative state. The maintainer accepted the concrete
Discord reporting implementation after reviewing the recommended event-sink
and webhook design on 2026-08-28.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Loom already emits committed lifecycle records, filters sinks by exact event name, loads explicitly selected `loom.event_sinks` entry points, and isolates callback failure. | None. | Reuse the existing path. |
| Functionality | Provide a copyable downstream Discord webhook package and live example for terminal run reporting. | None. | Implement one vertical phase. |
| Design | Keep provider code outside `src/loom`; use `httpx` only in the downstream example package; load the webhook URL only from process environment. | None. | Preserve core dependency and import boundaries. |
| Validation | Fake HTTP transport proves request projection, timeout, filtering, and secret-safe failures; live Discord remains opt-in. | None. | Add focused tests and run repository gates. |
| Detailed plan | One phase owns package, example, docs, and tests. | None. | Execute Phase 1. |
| Approval | The maintainer explicitly requested implementation of the recommended design. | None. | Begin implementation after the planning artifact lands. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `docs/features/plugins.md`, `docs/features/execution.md`, and `docs/features/reliability.md` | Service delivery belongs in downstream event-sink plugins; callbacks observe committed facts and cannot control execution. | Provider placement and failure behavior. | FR-1, FR-4, FR-7 |
| `src/loom/pipeline/event_sinks.py` and `src/loom/plugins/event_sinks.py` | `EventSinkRegistration`, exact subscriptions, instance-local dispatch, and no-argument plugin factories already exist. | Plugin factory and default event allowlist. | FR-1, FR-2 |
| `src/loom/pipeline/execution/eventing.py` and `RunRequest.event_sink_registry` | Durable append precedes sink dispatch; callback exceptions become event-adjacent failure facts and do not fail the run. | End-to-end integration and assertions. | FR-4, FR-6 |
| `examples/extensions/event-sink/` and Stage 30 tests | A runnable local example documents observer semantics, but Discord remains prose-only and no provider request is exercised. | Closest example and catalog conventions. | FR-1, FR-5, FR-6 |
| Official Discord execute-webhook contract | A webhook accepts JSON `content`, supports `allowed_mentions`, and `wait=true` requests the created message response. | HTTP projection. | FR-2, FR-3 |
| Current `pyproject.toml` | `httpx` is a development dependency but not a Loom runtime dependency. | Hermetic fake tests without widening core installation. | FR-5, FR-7 |

- User-visible outcome: a project can copy or install the example package,
  provide `LOOM_DISCORD_WEBHOOK_URL` through its deployment environment, select
  `loom.event_sinks:notifications.discord`, and receive bounded terminal run
  messages in a Discord channel.
- Existing end-to-end path: a lifecycle owner commits a run event, the runtime
  dispatcher applies `EventSinkSubscription`, and the selected callback
  performs one best-effort HTTP request. The sink return value is ignored.
- Included scope: a separately packaged example adapter, default terminal-event
  factory, direct Python construction, explicit entry-point metadata, live
  usage documentation, catalog routing, and fake-transport tests.
- Non-goals and deferrals: Discord bots, Gateway connections, interactions,
  inbound control, retries, rate-limit sleeping, queues/outboxes, guaranteed
  delivery, message editing, artifact upload, arbitrary event-payload copying,
  and a provider API in core Loom.
- Current consumer and boundary: the maintainer requested remote Discord
  reporting. The Discord webhook URL is a secret credential and the network is
  an external dependency; both remain owned by the downstream lifecycle process.
- Public or durable surfaces affected: no Loom public API or schema changes.
  The example package intentionally exposes `DiscordWebhookSink` and the
  `discord_event_sink` entry-point factory. Existing Loom failure facts record
  sanitized adapter failures.

## Minimum Useful Change

- Smallest useful behavior: send one Discord message for each selected terminal
  run event through the existing sink callback and prove the exact JSON request
  without contacting Discord during default validation.
- Closest existing capability and reuse decision: extend the Stage 30 extension
  examples with a real downstream package rather than adding a notifier
  protocol, notification schema, CLI option, or provider branch in Loom.
- Why a new surface is required: the existing generic sink callback cannot by
  itself construct Discord HTTP requests. A provider-specific downstream class
  and factory are the current concrete consumer.
- Explicitly deferred behavior: durable delivery needs an external relay or a
  later accepted outbox contract. `discord.py` and bot services are unnecessary
  for one-way reports and are not added.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Supply a separately packaged Discord event-sink example with an installed entry point named `loom.event_sinks:notifications.discord`. | No provider code under `src/loom`; no new Loom API. | Existing plugin loader and example layout. | Metadata and factory tests. | locked |
| FR-2 | The no-argument factory reads `LOOM_DISCORD_WEBHOOK_URL` and subscribes by default to `run.completed`, `run.failed`, `run.cancelled`, `run.interrupted`, and `run.preparation_failed`. | No authored-config credential and no implicit observe-all behavior. | `EventSinkRegistration` and `EventSinkSubscription`. | Exact subscription assertion. | locked |
| FR-3 | Each callback posts a bounded Discord JSON message with `allowed_mentions.parse=[]`, `wait=true`, and a finite timeout. | No arbitrary payload, logs, configuration, traceback, artifact contents, or mention activation. | Discord execute-webhook HTTP contract and `httpx`. | Captured request assertion including 2,000-character bound. | locked |
| FR-4 | HTTP, timeout, status, and invalid-URL failures surface as sanitized callback exceptions that never contain the webhook URL or token and never change run status. | No retry or fatal observer mode. | Existing sink failure isolation. | Failed fake response plus persisted failure record. | locked |
| FR-5 | Default tests perform no external network request and the live Discord journey is explicitly opt-in. | No Discord credential in tests or fixtures. | Fake/monkeypatched HTTP client. | Focused integration tests and example manifest. | locked |
| FR-6 | Documentation covers webhook creation, secret injection, direct Python use, CLI plugin selection, remote/SLURM process ownership, expected events, and best-effort reliability. | No delivery SLA claim. | Existing event ownership documentation. | Docs/catalog assertions and review. | locked |
| FR-7 | Core Loom imports and runtime dependencies remain unchanged. | The downstream package alone declares `httpx`. | Package boundary and root build. | Diff review, import tests, and `make validate-pr`. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1, FR-7 | Place the adapter in `examples/extensions/discord-webhook` as a nested downstream distribution. | Matches the documented dependency direction while making the package copyable and installable. | It is an example distribution, not a separately released artifact. | locked |
| FQ-2 | FR-2, FR-3 | Report terminal run outcomes by default. | Terminal events provide useful signal with low channel volume; exact subscription is already authoritative. | Stage progress requires explicit direct registration with a different subscription. | locked |
| FQ-3 | FR-4, FR-5 | Delivery stays synchronous, bounded, and best effort. | This is the current Loom callback contract; failures are already recorded without changing execution. | It cannot guarantee delivery during outages. | locked |
| FQ-4 | FR-6 | Demonstrate actual live configuration while validating through a fake transport. | External credentials and Discord availability cannot be default test prerequisites. | The default suite proves integration logic, not Discord uptime. | locked |

## Behavior Baseline

- Included and default behavior: the factory constructs one sink from the
  environment and selects five terminal run events. Each selected event sends
  the event name, run URI, occurrence time, and stage name only when the event
  primary resource is a stage. Direct callers may construct the class and
  choose a different exact Loom subscription.
- Failure and unsupported behavior: a missing environment variable fails
  explicit plugin activation before execution; a provider/request failure is
  converted to a generic status-bearing or transport failure message; the
  dispatcher records it and continues. Bots, inbound commands, and reliable
  queues are unsupported by this adapter.
- Reproducibility and durable behavior: no credential, HTTP object, or response
  is serialized into Loom state. Durable events and ordinary sink-failure facts
  retain their existing schemas and ordering.
- Explicit deferrals: external message IDs and observer-link records are not
  needed for one-way reporting; editing a single per-run message can justify
  that addition later.

## Minimum Design

- Modules and ownership: `examples/extensions/discord-webhook/src/loom_discord`
  owns provider projection and HTTP behavior. The nested `pyproject.toml` owns
  its dependency and entry point. Loom continues to own events, subscriptions,
  dispatch order, and failure isolation.
- Data and control flow: plugin selection loads `discord_event_sink`; the
  factory reads the secret and returns an exact registration; a committed event
  reaches `DiscordWebhookSink.__call__`; the sink builds a finite message and
  posts it; exceptions cross back through the existing callback-failure path.
- Fixed public, durable, trust-boundary, and cross-phase contracts: entry-point
  group/name, environment variable name, default event set, Discord mention
  suppression, 2,000-character maximum, finite timeout, and sanitized errors
  are fixed. No Loom durable shape changes.
- Private implementation discretion: message formatting helpers, text clipping,
  response helper factoring, test fakes, and README organization.
- Extension and compatibility seams: callers can instantiate the sink directly
  and register any valid exact subscription. A future separately released
  package can reuse the same module without changing Loom.
- Import and dependency direction: `loom_discord -> loom`; `loom` never imports
  `loom_discord`. Root runtime dependencies do not gain `httpx` or `discord.py`.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Downstream sink class | Concrete Discord consumer | Documentation-only pseudocode does not deliver messages. | keep |
| Nested package metadata and entry point | Explicit CLI plugin activation | Direct registration alone does not demonstrate installed activation. | keep |
| `httpx` downstream dependency | Bounded HTTPS and typed failure handling | Standard-library HTTP would reduce one dependency but weaken the accepted implementation recipe and test ergonomics. | keep downstream only |
| Message/severity abstraction | No second provider or shared consumer | Provider-local formatting is sufficient. | defer |
| Retry/outbox state | No delivery-guarantee requirement | Synchronous sleeping would block lifecycle owners and still be non-durable. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1, FR-7 | Provider package stays outside core source and root runtime dependency list. | Preserves repository ownership and cheap imports. | Users install/copy a second package. | locked |
| DQ-2 | FR-2, FR-3 | Factory owns fixed terminal defaults; class remains usable with caller-owned registration. | Avoids a new config schema while retaining Python flexibility. | CLI-selected defaults are intentionally narrow. | locked |
| DQ-3 | FR-3, FR-4 | Project only a finite event identity allowlist and replace HTTP errors with secret-free messages. | Loom persists callback error strings, so raw client exceptions are unsafe. | Detailed provider bodies are not retained. | locked |
| DQ-4 | FR-4, FR-5 | No automatic retry; document Discord rate-limit handling and external relays. | Matches current synchronous best-effort observer semantics. | A transient failure can lose a notification. | locked |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Installed entry point | Wrong group/name or factory target makes CLI activation fail. | Nested package metadata and Loom plugin loader. | Parse/build metadata and normalize factory registration. | ready |
| Discord request projection | Mentions, unbounded text, or arbitrary payload can leak or spam. | Provider sink at external HTTP boundary. | Capture JSON, params, and timeout; assert finite allowlist. | ready |
| Secret-safe failure | HTTP client exceptions can include the token-bearing URL. | Provider exception translation before Loom failure persistence. | Fake status/transport errors and assert secret absence. | ready |
| Observer isolation | Remote failure must not become pipeline failure. | Loom registry/dispatcher after provider exception. | Successful run plus one persisted sanitized sink failure. | ready |
| Live journey truthfulness | Fake coverage can be mistaken for live Discord proof. | Example README/manifest. | Manual prerequisites and explicit opt-in command. | ready |

Causal interactions requiring combined coverage:

- One integration test combines exact terminal filtering, a failed webhook
  response, successful run completion, and persisted secret-free failure
  evidence because those dimensions jointly prove the trust/failure boundary.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Discord webhook event sink | A downstream package can be installed or copied, selected as a Loom event sink, validated without network, and run against a real Discord webhook explicitly. | Example package/catalog/docs/tests; no `src/loom`, schema, root runtime dependency, bot, retry, or outbox changes. | Existing Stage 20/28 sink contracts and Stage 30 example harness. | Metadata/factory, request projection, secret failure isolation, docs inventory, and full gates pass. | ready |

One phase is proportionate because package, live example, documentation, and
fake validation form one user journey and share the same external boundary.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Explicit maintainer request plus FR/FQ/DQ tables. | pass |
| Minimum design justified | Reuses the complete event-sink path and adds only provider projection. | pass |
| Complexity delta proportionate | One downstream package and focused tests; no core machinery. | pass |
| Contracts and private discretion clear | Entry point, secret source, defaults, request safety, and failure behavior fixed. | pass |
| Invariant ownership and validation proportionate | External, secret, and callback boundaries each have focused fake evidence. | pass |
| Phases vertical and reviewable | One complete Discord reporting journey. | pass |
| No unresolved blocker | Live infrastructure is explicitly manual and not a default gate. | pass |

Gate result: passed; ready for implementation.
Accepted risks and revisit triggers: delivery remains best effort; revisit for a
durable outbox only after a required delivery SLA. Revisit message-ID observer
links if editing or deduplication becomes a current requirement. Revisit a
separately released integration repository only when distribution is requested.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Core notification API | Deferred. | One provider does not justify shared message/severity machinery. | Two concrete adapters demonstrate the same stable projection. |
| Discord bot/Gateway | Deferred. | One-way reporting needs only execute-webhook. | Inbound interaction or control is accepted. |
| Retry/outbox | Deferred. | Current sink semantics are synchronous and best effort. | Delivery guarantee or offline buffering is required. |
| Observer links | Deferred. | One-way posts do not need message mutation. | Edit/delete/deduplicate workflow needs external IDs. |
| Artifact upload | Deferred. | Reports should normally be stored remotely and linked after explicit project projection. | A bounded attachment consumer is accepted. |
| Release packaging | Nested copyable example only. | Satisfies current implementation without release-process machinery. | Maintainer requests an independently versioned distribution. |

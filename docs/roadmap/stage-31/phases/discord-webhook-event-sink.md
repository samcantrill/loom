# Phase 1 Execution Plan: Discord Webhook Event Sink

## Metadata

- Status: pr_open
- Roadmap stage and phase: Stage 31, Phase 1
- Manifest: `docs/roadmap/stage-31/implementation-plan.md`
- Branch: `agent/stage-31-p1-discord-webhook-event-sink`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; `/home/can134/work/active/loom-worktrees/stage-31-p1-discord-webhook-event-sink`
- Base revision: `f602ac5` (current `origin/develop` after approved Stage 31 planning)
- PR target: develop
- PR title: `Stage 31 phase 1: add Discord webhook event sink`
- Dependencies: approved Stage 31 planning; existing Stage 20 event-sink dispatch, Stage 28 explicit filtered activation, and Stage 30 extension-example harness
- Workflow path: fast; provider and secret boundaries reuse fixed downstream observer contracts
- Blockers: none

## Objective And Context

- Vertical outcome: a project can copy/install a small downstream package,
  select `loom.event_sinks:notifications.discord`, inject a Discord webhook URL
  only into the lifecycle-owning process, and receive bounded terminal run
  messages while Loom execution remains authoritative and independent of
  notification success.
- Earlier dependency: Loom already dispatches exact subscribed committed events,
  loads selected entry-point factories, records callback failures, and excludes
  sinks from processes that do not own lifecycle commits. The Stage 30 event
  example proves generic observation but has only a prose provider recipe.
- Later work explicitly out of scope: Discord bots, inbound interactions,
  message edits, external message-ID links, retries, rate-limit sleeping,
  background queues, durable outboxes, guaranteed delivery, attachments, and a
  shared Loom notification model.

## Current Source And Harness

- Relevant files and symbols: `pipeline/event_sinks.py` registration,
  subscription, context, and failure records; `plugins/event_sinks.py` factory
  normalization; `execution/eventing.py` append-before-dispatch; explicit CLI
  plugin activation; and `examples/extensions/event-sink/` catalog patterns.
- Existing tests and seams: event-sink unit/contract tests, local execution
  committed-event integration, CLI filtered-sink E2E, example manifest
  validation, and the Stage 30 example workflow test.
- Import, dependency, or harness constraints: provider code must not enter
  `src/loom`; the root runtime dependency list must not change; root development
  already supplies `httpx` for network-free fake tests; no test may require a
  webhook credential or external network.

## Scope

In scope:

- Add `examples/extensions/discord-webhook/` as a nested downstream
  `loom-discord` distribution with `src/loom_discord/` and a
  `loom.event_sinks` entry point named `notifications.discord`.
- Implement `DiscordWebhookSink` and a no-argument `discord_event_sink` factory.
- Read `LOOM_DISCORD_WEBHOOK_URL` at explicit factory construction and subscribe
  to the approved terminal run event tuple.
- Post JSON `content` no longer than 2,000 characters, suppress all mentions,
  pass `wait=true`, and use a finite default timeout.
- Project only event type, run URI, occurrence time, and optional stage identity;
  do not copy arbitrary payload/config/log/artifact/failure content.
- Translate client status/transport/invalid-URL failures to bounded messages
  that contain no webhook URL/token.
- Add an opt-in live runner using the existing small pipeline and authority
  example support, plus explicit installation/activation/remote process docs.
- Add fake request/failure integration coverage and update example catalogs and
  the generic event-sink recipe to route to the concrete adapter.

Out of scope:

- Changes to Loom event names, schemas, dispatch, plugin activation, CLI options,
  worker propagation, status, provenance, or failure policy.
- Adding `httpx`, `discord.py`, or any notification package to Loom runtime
  dependencies.
- Retrying 429 or transport failures, sleeping in a lifecycle callback,
  persisting delivery state, or claiming a delivery SLA.
- Sending raw exception messages, tracebacks, logs, environment, authored
  config, event payload mappings, artifact bodies, or credentials to Discord.
- Real Discord calls in automated tests.

Assumptions:

- The manually created webhook URL targets the intended Discord channel and is
  supplied by a deployment environment or secret manager.
- The selected plugin is installed and the secret is available in whichever
  local, prepared-run, or stage-job continuation process owns terminal commits.
- Terminal run event volume is low enough for one synchronous request per event;
  higher-volume stage reporting remains an explicit direct-registration choice.

## Fixed Contracts And Private Discretion

- Observable behavior: the factory fails clearly when the named environment
  variable is absent; otherwise it returns the named sink with the exact sorted
  terminal subscription. A selected event generates one bounded request. A
  failed request becomes one existing sink-failure fact and does not alter the
  run result.
- Public or durable shapes: the nested package exposes
  `DiscordWebhookSink` and `discord_event_sink`; package metadata exposes
  `notifications.discord`. No Loom public export, schema, or store layout changes.
- Trust and failure boundaries: the URL is held only in adapter memory and the
  HTTP request. Raw `httpx` exceptions must not cross into Loom because their
  text can include the token-bearing request URL. Mention parsing is explicitly
  disabled even when projected identifiers contain Discord syntax.
- Cross-phase contracts: exact event filtering remains solely
  `EventSinkSubscription`; only the lifecycle-owning process constructs the
  selected factory; callback results never mutate execution.
- Reproducibility and compatibility: default validation uses deterministic fake
  responses, retains no credentials, and leaves core imports/dependencies
  unchanged. The live example is manual because Discord is external.
- Private choices the executor may simplify: message line order, clipping
  helper, HTTP helper factoring, fake response implementation, and whether the
  live runner reuses or copies the Stage 30 sample pipeline files.

## Proportionality

- Existing seam reused: generic registration/factory normalization, exact
  subscription, committed event record/context, callback failure isolation,
  nested project metadata, and example catalog validation.
- Material additions and current justification: one provider class and package
  are necessary because the maintainer requested actual remote Discord
  reporting rather than a recipe. Focused fake tests are necessary because the
  webhook URL is both an external dependency and a durable-error leak risk.
- Optional hardening and future capability deferred: host allowlists, custom
  templates, severity/color models, client pooling/lifecycle, retries,
  deduplication, observer links, attachments, and independently versioned release.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Only exact terminal defaults dispatch from the factory | `EventSinkSubscription` returned by plugin factory | plugin construction | noisy or unintended messages | exact registration/factory assertion |
| Discord request cannot create mentions or exceed content limit | downstream projection helper | event identity to provider JSON | spam or rejected request | captured JSON/params/timeout test |
| Webhook credential never enters Loom failure evidence | adapter exception translation | `httpx` exception includes request URL | durable secret disclosure | failing response through runner plus secret-absence assertion |
| Notification failure cannot change run lifecycle | Loom registry/dispatcher | adapter raises | successful work falsely fails | successful result and one recorded failure |
| Default validation never contacts Discord | test fake and manual manifest | external network boundary | flaky tests or credential requirement | monkeypatched transport and manual prerequisites |
| Core dependency/import boundary remains unchanged | repository package layout/root `pyproject.toml` | provider implementation placement | domain-neutral core gains provider cost | diff/import/build review |

## Implementation Slices

1. Add nested package metadata and typed provider implementation with exact
   factory defaults, bounded projection, timeout, and sanitized errors.
2. Add fake-HTTP tests for metadata/factory normalization, successful request
   shape, terminal filtering, and non-fatal secret-safe failure persistence.
3. Add live pipeline entrypoint, example manifest, and README covering Discord
   setup, secret injection, direct Python and CLI selection, remote process
   placement, and delivery limitations.
4. Route the example from extension/root docs, replace the generic prose-only
   Discord recipe with a concrete link, and run targeted/catalog validation.
5. Run full local PR validation and exact-tree summary evidence.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required via final gate | Loom imports and distribution remain unchanged | Existing package/import suite; nested metadata inspection is focused integration coverage. |
| Unit | required via final gate | Existing event contracts remain compatible | Existing suite; provider is a downstream example and tested at its HTTP/lifecycle boundary. |
| Contract | required via final gate | Existing plugin normalization and observer isolation remain | Existing event-sink and plugin contract suites. |
| Integration | required | Provider metadata, request projection, filtering, and failure isolation | Fake `httpx` calls; successful run; one sanitized failure; no credential/network. |
| E2E / opt-in | manual live plus default catalog validation | Actual Discord service availability and credentials | README command and manual manifest; no live service in default gate. |

Targeted commands:

    uv run pytest tests/integration/examples/test_discord_webhook.py tests/integration/docs/test_v0_python_examples.py::test_examples_catalog_manifests_are_valid
    uv run ruff check examples/extensions/discord-webhook tests/integration/examples/test_discord_webhook.py
    uv run pyright examples/extensions/discord-webhook/src tests/integration/examples/test_discord_webhook.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: a raw client exception persists the secret URL; message projection
  permits mentions or copies arbitrary payloads; the nested package silently
  widens core dependencies; docs imply fake tests prove delivery; remote
  continuation guidance injects the secret through durable metadata or argv.
- Review focus: dependency direction, exact subscription, secret lifetime,
  exception text, content bound, mention suppression, timeout, fake/live
  distinction, and lifecycle-owner placement.
- Stop if: working delivery requires `src/loom` changes, a root runtime
  dependency, a new event/schema, credential serialization, background work,
  retries/outbox, or an external live gate. Those reopen planning.
- Accepted debt and revisit trigger: a nested example is not a separately
  released plugin; best-effort delivery can be lost. Revisit only for an
  independent release request or explicit delivery guarantee.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above, limited to the nested
  package/example, extension routing/docs, focused tests, and phase metadata.
- Decisions not to revisit: downstream-only provider, `httpx` nested dependency,
  exact terminal defaults, environment-only URL, bounded/sanitized best-effort
  behavior, no observer link/retry/outbox/core change.
- Conditions requiring manager action: any need for core/public/durable/root
  dependency changes, unclear Discord contract, secret exposure that cannot be
  removed locally, or inability to prove failure isolation without live network.

## Workflow State

- Manager preparation: passed; approved manifest and phase plan are consistent,
  `origin/develop` is `f602ac5`, and the dedicated branch/worktree are clean and
  isolated at the recorded paths.
- Expanded planning: not needed; fixed Stage 20/28 contracts remove novel
  public or durable decisions.
- Implementation: passed after preserving the executor's coherent uncommitted
  output from a lifecycle anomaly and completing one bounded manager correction;
  the downstream package, live example, catalogs, and fake HTTP/lifecycle tests
  are present, and all targeted commands plus the nested wheel build pass.
- Refiner: not needed.
- Pre-submit gate: passed on implementation revision `0246e3c`; targeted Discord
  and catalog tests passed 7 tests, focused Ruff and Pyright passed, the nested
  package built both distributions with the expected entry point,
  `make validate-pr` passed lint/typecheck, 2,578 default tests, 148 config-extra
  tests with 3 expected skips, and root package builds, and `make test-summary`
  produced a fresh all-pass receipt.
- Independent review: not needed; manager fast-path review found no remaining
  credential, dependency-direction, provider-projection, observer-isolation,
  fake/live truthfulness, scope, or proportionality blocker.
- Blocker corrections: 1/3 — after three full event waits the executor was no
  longer addressable and had left changes uncommitted. The manager preserved
  that work, suppressed raw HTTP exception chains, made the live wrapper report
  delivery failure truthfully, added provider failure-branch coverage, removed
  generated bytecode, and reran the targeted gate.
- PR and merge: [#251](https://github.com/samcantrill/loom/pull/251) is open,
  non-draft, mergeable, and verified with base `develop`, the exact phase head,
  and the approved title; remote merge is pending the final eligibility recheck.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Commit `0246e3c` adds the downstream `examples/extensions/discord-webhook/` distribution and live runner, routes extension/roadmap docs, and leaves `src/loom` plus root runtime dependencies unchanged. |
| Tests added or updated | Added fake provider request/failure/lifecycle coverage in `tests/integration/examples/test_discord_webhook.py` and cataloged the manual Python example. |
| Validated revision/tree state and evidence | `0246e3c`: targeted 7 passed; focused Ruff/Pyright passed; nested sdist/wheel built; `make validate-pr` passed 2,578 default and 148 config-extra tests with 3 expected skips plus builds; fresh summary passed package 118, unit 1,833, contract 296, integration 273, E2E 58, and config-extra 148. |
| Validation-relevant changes after evidence | None; this evidence record is phase metadata only. |
| PR, review, and merge | Manager fast-path review passed; [#251](https://github.com/samcantrill/loom/pull/251) is correctly targeted, non-draft, and mergeable; merge pending final recheck. |
| Residual risk and cleanup | Delivery remains synchronous and best effort; real Discord availability is intentionally manual. Worktree/branch cleanup follows remote merge. |

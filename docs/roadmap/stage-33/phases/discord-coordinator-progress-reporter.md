# Phase 1 Execution Plan: Discord Coordinator Progress Reporter

## Metadata

- Status: pr_open
- Roadmap stage and phase: Stage 33, Phase 1
- Manifest: `docs/roadmap/stage-33/implementation-plan.md`
- Branch: `agent/stage-33-p1-discord-coordinator-progress-reporter`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; `/home/can134/work/active/loom-worktrees/stage-33-p1-discord-coordinator-progress-reporter`
- Base revision: `c55892f5bd04691938da1a5a8ba76a4f4a0fabc9`
- PR target: develop
- PR title: `Stage 33 phase 1: add Discord coordinator progress reporter`
- Dependencies: merged Stage 29 joined status/socket behavior and merged Stage
  31 `loom-discord` downstream package
- Requirements and decisions: FR-1 through FR-8; FQ-1 through FQ-4; DQ-1
  through DQ-5
- Workflow path: fast; existing typed status and provider boundaries are fixed
  and no Loom public or durable contract changes
- Blockers: none

## Objective And Context

- Vertical outcome: after installing the nested package, an operator can run
  `loom-discord-coordinator --endpoint PATH --once` as a smoke test or leave it
  polling to receive useful Discord reports for coordinator health,
  queue/admission state, running/submitted stages, and stage completion progress.
- Earlier dependency: `LocalDaemonStatus` already provides the redacted joined
  read model, and the Stage 31 package already provides the secret-safe Discord
  webhook boundary. The runtime event sink remains correct for per-run terminal
  events but cannot represent cross-run coordinator status.
- Later work explicitly out of scope: Stage 32 deployment entrypoints, remote
  operator services, provider-neutral telemetry, metrics/history, bot control,
  message editing, durable retry/outbox, and core coordinator callbacks.

## Current Source And Harness

- Relevant files and symbols: `LocalDaemonStatus`,
  `LocalDaemonSocketClient.status()`, joined `runs` owner views,
  `DiscordWebhookSink`, `discord_event_sink`, nested package metadata/README,
  and `tests/integration/examples/test_discord_webhook.py`.
- Existing tests and seams: fake `httpx.post`, direct module import from the
  nested source tree, event filtering/failure isolation, example catalog
  validation, and nested wheel inspection.
- Import, dependency, or harness constraints: no `src/loom` edit or root
  dependency; `httpx` stays nested; the reporter uses only public `loom.queue`
  imports; tests never open an external connection or require a webhook secret.

## Scope

In scope:

- Refactor the provider-local webhook POST boundary only as needed so event and
  coordinator messages share content length, mention suppression, timeout,
  status handling, and sanitized exceptions without changing existing sink
  behavior.
- Add and intentionally export `DiscordCoordinatorReporter`. It accepts a
  webhook URL and finite timeout, consumes a typed `LocalDaemonStatus`, and
  returns whether one message was attempted/sent versus suppressed as unchanged.
- Derive a stable semantic projection from service health/diagnostic, exact
  admission states, exact authority run/stage states, and bounded active-run
  details. Active detail includes queue item ID, admission state, authority
  state/availability, successful stage count over total, and bounded
  running/submitted stage names.
- Exclude run URI, raw owner mappings, assignment/process/agent/session/
  scheduler/control/revision/receipt/log/config identifiers and all arbitrary
  payloads from remote content.
- Bound the message to Discord's existing 2,000-character maximum, suppress all
  mention parsing, sort/count deterministically, and count omitted active runs.
- Add an installed `loom-discord-coordinator` command using the existing
  environment variable and an explicit `--endpoint`. Support `--once`, positive
  finite polling, and positive finite heartbeat controls.
- In continuous mode, send on startup, semantic changes, and heartbeat. Ignore
  timestamp-only status changes. Keep status/HTTP failure outside the
  coordinator, print only sanitized local diagnostics, and continue polling.
  One-shot failures return nonzero.
- Update the nested README and manifest/catalog guidance with webhook creation,
  installation, same-OS-user socket requirement, smoke/continuous commands,
  service-manager placement, report fields, and best-effort limitations.
- Extend focused fake tests and inspect nested wheel console metadata.

Out of scope:

- Any change to `src/loom`, root `pyproject.toml`, Stage 29 status fields,
  transport authorization, public Loom imports, durable schemas, or Stage 32.
- A generic reporter protocol/registry, plugin group, coordinator event, or
  in-process callback/thread.
- Posting raw joined status or run URI; streaming logs/config/artifacts;
  percent-complete, ETA, utilization, historical charts, or inferred scheduler
  truth.
- Remote socket forwarding, Internet-facing control/status endpoints,
  certificate handling, bots, interactions, or inbound commands.
- Durable dedupe, message IDs/editing, immediate retry loops, provider rate-limit
  queues, delivery guarantees, or real Discord calls in tests.

Assumptions:

- The reporter runs on the coordinator host under the same OS account that owns
  the protected Unix socket, and outbound HTTPS to Discord is allowed.
- Queue item IDs and stage names are acceptable operational labels for the
  chosen channel; the projection omits broader identifiers by default.
- Polling the existing status endpoint at an operator-selected modest interval
  is acceptable for the current coordinator scale.

## Fixed Contracts And Private Discretion

- Observable behavior: first status sends once; equivalent semantics with new
  observation times do not send; admission/stage/health changes send; heartbeat
  forces the current summary. The report names its non-atomic `as_of`, service
  health, exact counts, and bounded active details without asserting an ETA.
- Public or durable shapes: the nested package exports
  `DiscordCoordinatorReporter` and installs `loom-discord-coordinator`. Its
  direct `report(status, force=False)` surface may return a boolean indicating
  delivery versus suppression. No Loom public/durable shape changes.
- Trust and failure boundaries: URL remains only in the environment and
  provider object; raw `httpx` or socket exceptions never enter Discord or
  sanitized reporter diagnostics. The reporter cannot mutate the coordinator.
- Cross-phase contracts: the existing event sink factory, entry-point name,
  subscription, message content, and run lifecycle isolation remain unchanged.
- Reproducibility and compatibility: semantic ordering and truncation are
  deterministic; process restart intentionally sends a fresh initial report;
  default validation is fake-backed and credential-free.
- Private choices the executor may simplify: provider-local module split,
  internal projection dataclass/mapping, exact default cadence, line wording,
  maximum active-run/stage-name display counts, CLI loop helper injection, and
  whether safe continuous failures use a fixed or bounded delayed cadence.

## Proportionality

- Existing seam reused: one typed status call, existing redacted owner join,
  existing downstream webhook dependency/request safety, package console
  metadata, and fake integration harness.
- Material additions and current justification: a semantic formatter is needed
  because raw status is neither safe nor bounded; a polling command is needed
  for ongoing progress without coordinator changes; process-local dedupe is
  needed to avoid one Discord message per poll.
- Optional hardening and future capability deferred: durable checkpoints,
  delivery receipts, several coordinators, asynchronous HTTP pooling, adaptive
  rate-limit handling, remote APIs, custom templates, metrics, and dashboards.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Reported lifecycle progress comes from authority/admission axes only | downstream projection over `LocalDaemonStatus` | joined plain-data owner views | scheduler evidence is misstated as lifecycle truth | multi-axis fixture with conflicting/non-authoritative details omitted |
| Poll timestamps do not create channel noise | semantic signature excluding observation fields | every socket status read | one message per poll | equivalent-status/different-time test |
| Useful changes and heartbeat do post | reporter state/caller cadence | stage transition or forced heartbeat | progress disappears indefinitely | changed-stage and force tests |
| Remote content is bounded and allowlisted | downstream formatter/shared webhook sender | long IDs/many active runs/stages | provider rejection or operational leakage | 2,000 bound, omitted count, field-absence and mention assertions |
| Credentials and raw provider errors stay local | shared sanitized HTTP boundary | token-bearing URL in `httpx` exception | secret persistence/output disclosure | invalid/status/transport failures with secret-absence assertions |
| Scheduling cannot be delayed or failed by Discord | adjacent process and read-only socket client | external outage | coordinator throughput/lifecycle corruption | architecture/diff review plus no daemon mutation in tests |
| Installed command is real and documented | nested project metadata and runner | wheel/build boundary | copyable instructions fail | entry-point metadata/help/one-shot seam tests |

## Implementation Slices

1. Extract or add one provider-local bounded content sender while preserving the
   existing event sink request and failure behavior.
2. Add the typed coordinator reporter, semantic projection, deterministic
   formatting, change suppression, force/heartbeat seam, and focused unit-like
   integration fixtures.
3. Add the installed command with option validation, one-shot behavior,
   continuous polling, and sanitized status/delivery diagnostics.
4. Update README/package metadata/example manifest and add setup, smoke,
   continuous, and service-manager guidance.
5. Inspect nested build metadata, run focused tests/lint/typecheck, then run the
   full repository gates.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required via final gate | Core imports/build remain independent | Existing package suite; no new Loom export. |
| Unit | required via final gate | Existing queue/status/event behavior remains | Existing suite; downstream logic stays in focused integration test. |
| Contract | required via final gate | Public status and event-sink contracts remain compatible | Existing queue Python API and event sink contracts. |
| Integration | required | Projection, dedupe/heartbeat, request safety, CLI seam, metadata | Fake typed statuses and HTTP/client calls; no network. |
| E2E / opt-in | manual live | Real owner-only socket plus Discord availability | README smoke and continuous commands; not a default gate. |

Targeted commands:

    uv run pytest tests/integration/examples/test_discord_webhook.py tests/integration/docs/test_v0_python_examples.py::test_examples_catalog_manifests_are_valid
    uv run ruff check examples/extensions/discord-webhook tests/integration/examples/test_discord_webhook.py
    uv run pyright examples/extensions/discord-webhook/src tests/integration/examples/test_discord_webhook.py
    uv build --project examples/extensions/discord-webhook

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: calling raw assignment/scheduler state lifecycle progress;
  timestamp-driven spam; exposing run paths or operational IDs; truncating away
  health/counts; changing Stage 31 event messages; retrying aggressively during
  provider outage; implying a globally atomic or guaranteed report.
- Review focus: status owner selection, field allowlist, stable signature,
  content priority under truncation, mention/secret safety, process separation,
  existing event-sink compatibility, real installed command, and fake/live
  wording.
- Stop if: useful reporting requires a new Loom status/schema, remote endpoint,
  coordinator mutation/callback, generic plugin registry, credential
  persistence, durable cursor/outbox, root dependency, Stage 32 edit, or live
  network gate. Reopen planning instead of widening the phase.
- Accepted debt and revisit trigger: same-host/process-local best-effort
  reporting; revisit after a remote gateway, delivery SLA, second provider, or
  historical telemetry becomes a current accepted consumer.

## Executor Handoff

- Read section range: `Objective And Context` through `Risks, Review, And Stops`.
- Safe implementation slices: the five slices above, confined to the existing
  nested Discord package, its README/manifest, directly related catalog/roadmap
  wording, focused tests, and phase metadata.
- Decisions not to revisit: adjacent same-user process; typed status socket;
  authority/admission-only progress; safe bounded projection; timestamp-free
  semantic suppression; environment-only secret; no core/schema/Stage 32
  changes; no durable delivery or live default tests.
- Conditions requiring manager action: any need for core/public/durable/root
  dependency changes, ambiguity about authority versus external status, raw
  secret/identifier exposure that cannot be removed locally, or inability to
  package/test the console command without network.

## Workflow State

- Manager preparation: passed; approved manifest and phase plan are consistent,
  the isolated branch/worktree starts from `c55892f`, and user-owned Stage 32
  paths remain isolated in the control checkout.
- Expanded planning: not needed; existing Stage 29 and Stage 31 contracts fix
  the public, durable, trust, and delivery boundaries.
- Implementation: complete; the downstream package now projects typed
  coordinator status through a shared sanitized webhook sender and installs the
  one-shot/continuous reporter command without changing Loom core or Stage 32.
- Refiner: not needed.
- Pre-submit gate: passed on `46383e9`; corrected targeted tests (13 passed),
  Ruff, Pyright, lazy-import check, nested build/wheel metadata,
  `make validate-pr`, and `make test-summary` all pass.
- Independent review: not needed; manager fast-path review found no remaining
  lifecycle-truth, credential, import-cost, cadence, compatibility, scope, or
  fake/live-evidence blocker.
- Blocker corrections: 1/3 — manager review found that alphabetical truncation
  could hide currently running work behind waiting admissions and that a
  progress report immediately before a heartbeat could be followed by a noisy
  duplicate. Active detail now prioritizes running/submitted stages, heartbeat
  time resets after each report attempt, and the existing event-sink import
  remains lazy with respect to coordinator code.
- PR and merge: [#252](https://github.com/samcantrill/loom/pull/252) targets
  `develop` from the exact phase branch, is non-draft and mergeable, and passed
  manager fast-path scope/body/evidence review; squash merge pending.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Added the downstream coordinator projection, CLI, shared bounded sender, package script, operator documentation/catalog wording, and Stage 33 implementation state; `src/loom`, root dependencies, schemas, and Stage 32 remain unchanged. |
| Tests added or updated | Extended `tests/integration/examples/test_discord_webhook.py` for safe allowlisted projection, timestamp suppression, heartbeat, bounded active-run omission, sanitized failures, one-shot CLI, continuous recovery, and package script metadata. |
| Validated revision/tree state and evidence | `46383e9`: targeted pytest 13 passed; Ruff, Pyright, lazy-import check, nested build/wheel metadata passed; `make validate-pr` passed 2,578 default and 154 config-extra tests with 3 expected skips plus root builds; fresh summary passed 2,732 tests with 0 failures/errors and 3 skips. |
| Validation-relevant changes after evidence | None; this evidence update is phase metadata only. |
| PR, review, and merge | [#252](https://github.com/samcantrill/loom/pull/252) is correctly targeted and manager review passed; merge pending. |
| Residual risk and cleanup | pending |

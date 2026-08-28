# Roadmap Stage 33 Planning: Discord Coordinator Progress Reporter

Status: approved
Roadmap stage: 33
Evidence tree: `/home/can134/work/active/loom` at `4ba8265`; relevant dirty paths: user-owned untracked `docs/roadmap/stage-32/`, preserved unchanged
Planning route: lean; the change consumes the existing redacted coordinator status and downstream Discord package without changing a public Loom or durable contract
Current gate: passed; ready for implementation
Blockers: none

This file is current authoritative state. The maintainer requested useful remote
reporting for coordinator-managed runs on 2026-08-28. The request approves the
smallest downstream design that keeps Discord delivery outside the scheduling
process and projects the coordinator's existing joined status.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | `LocalDaemonStatus` already exposes redacted coordinator health, admissions, authority run/stage status, scheduling, assignments, agent execution, SLURM, cancellation, controls, freshness, and a join `as_of`. | None. | Consume this status; add no second queue or progress owner. |
| Functionality | Add an installed Discord coordinator reporter with one-shot and continuous modes, meaningful-change suppression, and optional heartbeat reports. | None. | Extend the Stage 31 downstream package. |
| Design | Run the reporter beside the coordinator through its owner-only Unix socket so webhook latency or failure cannot delay scheduling. | None. | Reuse `LocalDaemonSocketClient.status()`. |
| Validation | Fake the webhook and coordinator client; prove the bounded allowlisted projection, progress-change behavior, and secret-safe failure handling. | None. | Keep live Discord manual. |
| Detailed plan | One vertical phase owns the package extension, command, documentation, and focused tests. | None. | Execute Phase 1. |
| Approval | The maintainer explicitly requested coordinator queue/running/progress reporting. | None. | Begin after this artifact lands. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `src/loom/queue/local_daemon.py` and `local_daemon_transport.py` | `LocalDaemonStatus` is a typed, socket-readable status join and the socket authenticates the same local OS owner. | Status source and process boundary. | FR-1, FR-3, FR-7 |
| `src/loom/queue/local_daemon_execution.py` | Owner views already join exact admission, authority stage, scheduling, managed assignment, SLURM, agent, cancellation, and service axes without claiming global atomicity. | Authoritative progress facts. | FR-2, FR-6 |
| `docs/features/queue.md`, `docs/GLOSSARY.md` | Joined managed status is explicitly non-atomic and preserves each owner's authority, revision, observation time, and freshness. | Truthful message wording. | FR-2, FR-6 |
| `examples/extensions/discord-webhook/` | The downstream package already owns the webhook secret, bounded HTTP request, mention suppression, finite timeout, sanitized errors, and manual live setup. | Provider delivery reuse. | FR-1, FR-4, FR-5 |
| Stage 31 plan and tests | Discord remains downstream and best effort; root runtime dependencies and core imports are unchanged. | Scope and validation baseline. | FR-4, FR-5, FR-7 |
| Untracked Stage 32 plan | A separate user-owned plan may later add first-party deployment entrypoints, but current Stage 29 status and socket APIs are sufficient now. | Independence and compatibility. | FR-3, FR-7 |

- User-visible outcome: an operator can install the existing example package,
  start `loom-discord-coordinator` under the coordinator's OS account, and
  receive a concise Discord message at startup, when managed progress changes,
  and at a configured heartbeat interval.
- Existing end-to-end path: the coordinator builds one owner-labelled
  `LocalDaemonStatus`; the owner-only socket returns it; a downstream process
  may already call `LocalDaemonSocketClient.status()`. The missing behavior is
  a safe Discord projection and a long-running invocation.
- Included scope: a downstream reporter class, semantic projection/formatting,
  installed console command, one-shot and polling modes, change suppression,
  heartbeat, safe error output, live setup documentation, and fake tests.
- Non-goals and deferrals: a core notification API, coordinator event schema,
  new status/database fields, Discord code under `src/loom`, a network operator
  gateway, bot interactions, durable outbox, guaranteed delivery, historical
  charts, metrics extraction, arbitrary message templates, or inbound control.
- Demonstrated failure: the Stage 31 sink observes events owned by one run. It
  cannot truthfully represent the cross-run queue, currently active stages, or
  coordinator health because every `PipelineEventRecord` requires one run URI.
- Public or durable surfaces affected: no Loom public API or persisted/wire
  schema. The nested downstream distribution adds a public reporter class and
  an installed console script. Its in-memory deduplication state is explicitly
  non-durable.

## Minimum Useful Change

- Smallest useful behavior: poll the existing coordinator status, derive one
  bounded operational summary, and post it only at startup, after a semantic
  status change, or when the operator-selected heartbeat expires.
- Closest existing capability and reuse decision: extend `loom-discord` and
  reuse its webhook request/error boundary. Do not adapt cross-run status into a
  fake run event or add a service-specific callback to `LocalDaemon`.
- Why a new surface is required: event sinks are deliberately run-scoped, while
  coordinator reporting is a cross-run read model. A sidecar console command is
  the current concrete consumer and isolates external I/O from reconciliation.
- Explicitly deferred behavior: reliable delivery needs a durable external
  relay; remote status access needs a separately authenticated operator
  gateway; dashboards and time series need a distinct metrics/telemetry design.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Extend the `loom-discord` example distribution with `DiscordCoordinatorReporter` and an installed `loom-discord-coordinator` command. | No Discord or reporter import from core Loom. | Existing nested package and webhook helper. | Public import and wheel script metadata. | locked |
| FR-2 | Project service health, exact admission-state counts, aggregate authority stage-state counts, and bounded active-run lines containing queue item, admission/authority state, successful-stage progress, and running/submitted stage names. | Do not copy raw owner views, run URIs, assignments, process IDs, agent/session IDs, scheduler handles, controls, revisions, receipts, logs, config, payloads, or secrets. | `LocalDaemonStatus` and its `runs` allowlist. | Representative healthy/degraded and multi-run fixtures. | locked |
| FR-3 | Read status through `LocalDaemonSocketClient` in one-shot or continuous polling mode under the socket owner's account. | No new remote endpoint and no coordinator lifecycle ownership. | Existing owner-only Unix transport. | Command/client seam tests and manual command. | locked |
| FR-4 | Post at startup, on semantic progress changes, and on a configurable heartbeat; changing observation timestamps alone must not post. | Deduplication is process-local and best effort; no durable cursor or outbox. | Stable provider-local semantic projection. | Same-status/new-time, changed-stage, and forced-heartbeat tests. | locked |
| FR-5 | Preserve the existing 2,000-character bound, disabled mention parsing, finite timeout, environment-only webhook secret, and sanitized HTTP errors. | No secret in argv, status, output, or exception text. | Existing Discord webhook request boundary. | Captured request, truncation, and failure-secret assertions. | locked |
| FR-6 | Report only facts present in the joined status and label unavailable/degraded status without upgrading scheduler or agent observations into lifecycle truth. | No invented percentage, ETA, throughput, or global-atomic claim. | Existing owner-labelled status contract. | Exact-count/progress assertions and docs review. | locked |
| FR-7 | Leave `src/loom`, root dependencies, Loom public imports, and all durable/wire schemas unchanged; preserve untracked Stage 32 work. | No coordinator hook or new plugin group. | Repository dependency direction. | Diff review and full repository gates. | locked |
| FR-8 | Document webhook creation, same-user socket access, smoke test, continuous use, heartbeat/poll controls, service-manager placement, expected message content, and failure/delivery limits. | Fake tests do not claim live Discord proof. | Existing README and official links. | Documentation assertions and manual manifest review. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1, FR-3, FR-7 | Use an adjacent reporter process, not an in-process coordinator callback. | External HTTPS cannot delay or fail the coordinator, and the current owner-only status client is sufficient. | Operators supervise one additional lightweight process. | locked |
| FQ-2 | FR-2, FR-6 | Send an allowlisted operational summary rather than raw JSON. | The joined view contains sensitive operational identifiers and more data than a Discord message can safely or usefully present. | Deep investigation still uses `daemon-status --format json`. | locked |
| FQ-3 | FR-4 | Suppress unchanged semantic summaries and allow a heartbeat. | Progress changes remain visible without posting every poll; a heartbeat proves the observer is alive. | Dedupe resets when the reporter restarts. | locked |
| FQ-4 | FR-5, FR-8 | Retain best-effort webhook behavior with observable sanitized local errors. | This matches the existing downstream boundary without promising delivery. | A transient failure can lose a particular progress update. | locked |

## Behavior Baseline

- Included and default behavior: the command reads one status immediately and
  posts it. Without `--once`, it polls at a positive finite interval, compares
  only semantic summary fields, posts changes, and forces a periodic heartbeat.
  Active-run detail is bounded and deterministic; omitted runs are counted.
- Failure and unsupported behavior: one-shot status or delivery failure exits
  nonzero with a safe message. Continuous mode records a safe stderr diagnostic
  and keeps polling; an unchanged failed report is not immediately replayed,
  but a later semantic change or heartbeat creates a new best-effort attempt.
  Socket authorization and endpoint availability retain their current errors.
- Reproducibility and durable behavior: no reporter cursor, webhook response,
  credential, or Discord message ID enters Loom state. Restart sends a fresh
  startup summary. Message ordering is observation order, not a durable event
  sequence or globally atomic history.
- Explicit deferrals: inbound Discord commands, per-stage log streaming,
  message editing, durable retry, several coordinator endpoints in one process,
  remote socket tunnelling guidance, and provider-neutral telemetry exporters.

## Minimum Design

- Modules and ownership: add a downstream coordinator module below
  `examples/extensions/discord-webhook/src/loom_discord`. It owns status
  projection, semantic fingerprinting, polling presentation, and Discord
  delivery reuse. `LocalDaemonStatus` remains the sole status source.
- Data and control flow: console command validates options, constructs
  `LocalDaemonSocketClient`, reads a typed status, builds an allowlisted semantic
  projection, renders bounded text, and uses the existing webhook POST helper.
  Continuous mode retains only the last attempted signature and heartbeat time.
- Fixed public and trust-boundary contracts: public reporter name, console
  command name, existing environment variable, one-shot/continuous modes,
  meaningful-change suppression, heartbeat, safe projection fields, content
  bound, mention suppression, finite timeout, and sanitized errors are fixed.
  No durable contract changes.
- Private implementation discretion: internal projection representation, line
  wrapping, exact default poll/heartbeat values, maximum displayed run/stage
  counts within the content bound, CLI helper decomposition, and fake clients.
- Extension and compatibility seams: direct Python callers may pass any typed
  `LocalDaemonStatus` to the reporter and force a heartbeat. The existing event
  sink entry point and terminal-run behavior remain unchanged.
- Import and dependency direction: `loom_discord -> loom.queue`; `loom` never
  imports the downstream package. `httpx` remains nested-package-only.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Downstream status reporter and formatter | Concrete coordinator reporting consumer | Raw JSON copied to Discord leaks detail and exceeds provider limits. | keep bounded |
| Installed polling command | Operators need ongoing progress without custom code | One-shot script plus cron would send duplicates and obscure change semantics. | keep minimal |
| In-memory semantic signature and heartbeat | Frequent polls otherwise spam the channel | Post on every poll. | keep process-local |
| Core reporter protocol/plugin registry | No second provider or core consumer | Would add public machinery without necessity. | defer |
| Durable cursor/outbox | No delivery guarantee requested | Requires new persistence and replay semantics. | defer |
| Remote operator API | Current same-host sidecar is sufficient | Broadens authentication and network trust. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1, FR-7 | Extend only the downstream distribution and its tests/docs. | The typed status client is already public and complete for this consumer. | Reporter deployment is separate from Loom core installation. | locked |
| DQ-2 | FR-2, FR-6 | Derive progress from exact authority stage states and exact admission states. | Authority owns lifecycle truth; assignment/scheduler observations are not substituted for it. | The summary deliberately omits low-level dispatch details. | locked |
| DQ-3 | FR-4 | Hash/compare a timestamp-free semantic projection; render the current `as_of` only when sending. | Coordinator observation times change on every read and must not cause noise. | Identical state after restart produces one new startup report. | locked |
| DQ-4 | FR-5 | Reuse one sanitized webhook content sender for event and coordinator messages. | One external boundary should own timeout, status, mention, and credential safety. | Small provider-local refactor touches the prior sink implementation. | locked |
| DQ-5 | FR-3, FR-8 | Continuous failures stay outside coordinator and are visible locally; one-shot fails clearly. | Operators can supervise the reporter independently without corrupting scheduling. | Continuous delivery remains best effort. | locked |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Useful progress projection | Counts or active names could be inferred from the wrong owner. | Authority/admission axes in `LocalDaemonStatus`. | Multi-run fixture with running, submitted, waiting, succeeded, failed, and unavailable facts. | ready |
| Noise suppression | Volatile `as_of` and observation times change every read. | Downstream semantic projection. | Two equivalent statuses with different times send once; a stage change sends again. | ready |
| Discord safety | Operational identifiers could mention users or overflow content. | Shared downstream webhook sender. | Captured `allowed_mentions`, timeout, and length assertions. | ready |
| Failure isolation | HTTP or socket failure must not affect coordinator work. | Separate reporter process. | Sanitized one-shot failure and continuous-loop seam; no daemon mutation. | ready |
| Installed journey | Metadata or docs may describe a command that is not packaged. | Nested `project.scripts` and README. | Wheel metadata plus parser-backed invocation/help test. | ready |

Causal interactions requiring combined coverage:

- One focused integration test combines a typed joined status, semantic change
  suppression, a captured webhook request, and a token-bearing fake failure
  because together they prove progress truth, channel volume, and secret safety.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Discord coordinator progress reporter | The installed downstream package can safely report current coordinator health, queue/admission state, running/submitted stages, and per-run stage progress once or continuously. | Nested package, README/catalog/roadmap routing, and focused tests only; no `src/loom`, root dependency, schema, remote gateway, bot, or durable delivery changes. | Existing Stage 29 joined status/socket and Stage 31 webhook package. | Projection, dedupe/heartbeat, request safety, CLI/metadata, docs, and full gates pass. | ready |

One phase is proportionate because projection, delivery, command, documentation,
and fake validation form one downstream operator journey with one external
boundary and no core contract change.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | Direct maintainer request plus FR/FQ/DQ tables. | pass |
| Minimum design justified | Reuses the complete joined status and webhook boundaries. | pass |
| Complexity delta proportionate | One downstream module/command and process-local state; no core machinery. | pass |
| Contracts and private discretion clear | Projection, cadence triggers, process boundary, secret handling, and failures are fixed. | pass |
| Invariant ownership and validation proportionate | Authority/admission facts, socket, and webhook boundaries have focused evidence. | pass |
| Phases vertical and reviewable | One install-to-live-reporting journey. | pass |
| No unresolved blocker | Stage 32 is independent and preserved; live Discord stays manual. | pass |

Gate result: passed; ready for implementation.
Accepted risks and revisit triggers: the reporter is same-host, process-local,
and best effort. Revisit a provider-neutral core observer only after a second
concrete coordinator-status consumer; revisit durable delivery for an explicit
SLA; revisit remote access only with an authenticated operator-gateway design.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| In-process coordinator callback | Deferred. | External HTTP must not share reconciliation latency/failure. | A bounded non-blocking coordinator observer contract has another current consumer. |
| Coordinator events in run event grammar | Rejected for this scope. | Cross-run status has no truthful single run URI. | A separately designed coordinator event/audit owner is accepted. |
| Raw joined-status delivery | Rejected. | It is verbose and contains operational identifiers beyond the message need. | Never for this Discord summary; use protected JSON inspection. |
| Durable delivery/outbox | Deferred. | No delivery SLA and no safe current persistence owner. | Required offline replay or guaranteed notification. |
| Remote status gateway | Deferred. | Same-host owner-only socket is the existing supported trust boundary. | Authenticated remote operator access is accepted. |
| Historical charts/ETA | Deferred. | Current status is a snapshot, not a metrics series. | A telemetry/time-series consumer and retention contract exist. |

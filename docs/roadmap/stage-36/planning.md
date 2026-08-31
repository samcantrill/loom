# Roadmap Stage 36 Planning: Standalone Managed-Local Starter

Status: approved
Roadmap stage: 36
Evidence tree: `/home/can134/work/active/loom` at
`3990d79906c89151649b32623b6d20ef42db60bc`; relevant dirty paths: none
Planning route: lean; the accepted change composes existing public planning,
deployment, authority, and daemon boundaries without a new durable schema or
trust boundary
Current gate: passed; the maintainer approved implementation on 2026-08-31
Blockers: none

This file is current authoritative state. The maintainer first requested a
copyable single-machine coordinator/daemon journey, reviewed the current
managed-local implementation and remaining gap, accepted the minimum design,
and explicitly requested implementation on 2026-08-31.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Stage 29 supplies durable embedded execution, protected service configuration, exact runtime records, CLI management, restart, and cleanup; Stage 34 supplies singular run inspection. The current example proves those pieces only through an in-process test-oriented composition. | None. | Reuse the merged owners. |
| Functionality | One protected local-only coordinator config and one authored pipeline can prepare, initialize, serve, submit, wait, inspect, read an artifact, restart, and replay preparation from a copied directory. | None. | Implement one vertical phase. |
| Design | Add one narrow public preparation facade and make `managed-local-basic` its standalone service consumer. Keep exact runtime preparation as the low-level owner. | None. | Preserve existing schemas and commands. |
| Validation | Public preparation identity/replay and the copied real-service lifecycle are the causal boundaries. | None. | Add unit/package and copied E2E coverage. |
| Detailed plan | One phase joins the public facade to its only current downstream-template consumer. | None. | Execute Phase 1. |
| Approval | The maintainer approved the explained behavior and requested implementation. | None. | Proceed on the fast path. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `loom.queue.local_daemon_runtime` | `prepare_managed_local_runtime_record` safely owns the exact executable intent but requires a prepared store, plan, pipeline, and per-stage requirements. | Retain the low-level invariant owner. | FR-1..FR-5 |
| `loom.queue.deployment` | Protected schema-v2 coordinator configuration already owns deployment/run roots, embedded launch identity, scheduling composition, authority adapter, remote profiles, and optional listeners. | Single source for paths and embedded execution identity. | FR-1..FR-4 |
| pipeline planning/runtime/store APIs and Weave composition | Public APIs can compose config, parse a pipeline, merge runtime options, persist config/plan/runtime records, and create local materialization. They are currently assembled manually in the example. | High-level preparation composition. | FR-1..FR-5 |
| `managed-local-basic` | The runnable journey uses fresh temporary roots, inline stages/config, a shared repository helper, and direct `LocalDaemon`/socket construction. It does not exercise `daemon-init` or `daemon-serve`. | Demonstrated downstream-copy failure. | FR-6..FR-8 |
| `managed-local-queue` and queue docs | The protected config/commands exist, but the example combines local execution with illustrative outbound TLS and repository-relative paths. | Reuse command/config shape while removing remote-only setup. | FR-6, FR-7 |
| Stage 34 `inspect-run` | The owner-only socket already exposes bounded metadata-only run inspection. | End-state observation without a new query surface. | FR-7 |

- User-visible outcome: copy the managed-local starter into an ordinary project,
  edit project stages and pipeline config, and run one experiment through a
  persistent coordinator with its embedded agent using documented commands.
- Existing end-to-end path: project code creates a local run and exact runtime
  record, constructs `LocalDaemon` in-process, submits through its socket, waits
  for success, stops, reopens, and checks retained admission state.
- Included scope: local-only protected configuration, authored config
  composition, prepared-run receipt, exact replay/conflict behavior, real
  `daemon-init`/`daemon-serve` subprocess use, submit/wait/inspect/artifact and
  restart proof, documentation, and copied-directory validation.
- Non-goals and deferrals: outbound agents, TLS/PKI, ready-stage SLURM, custom
  execution-requirement routing, plugin activation, dashboards, content relay,
  automatic retention/deletion, process-manager installation, and a new run or
  coordinator schema.
- Public or durable surfaces affected: one lazy `loom.queue` function and
  frozen receipt are public. Existing plan, config, runtime, authority, and
  daemon durable formats are reused unchanged.

## Minimum Useful Change

- Add `prepare_managed_local_run(coordinator_config, pipeline_config, run_name)`
  for the supported embedded-only starter profile. It derives the canonical run
  URI beneath the protected service run root, composes the authored config,
  validates the pipeline/runtime, persists normal resolved/composition/runtime
  evidence, prepares the exact runtime record, initializes embedded authority,
  and returns a typed receipt.
- Exact replay of a fully prepared matching run returns the same identities
  without mutation. An existing partial, corrupt, or changed preparation fails
  closed. Preparation never repairs or overwrites an existing run.
- Refactor `managed-local-basic` into a self-contained copied project that uses
  the facade and actual role commands. Preserve the low-level example only as
  an advanced reference where it still has a current consumer.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Public preparation accepts protected coordinator config path, authored pipeline config path, and one safe run name; it returns immutable run URI, plan digest, runtime digest, and ordered stage names. | No queue submission or daemon startup inside preparation. | Deployment loader, Weave, pipeline/store APIs. | Public import/signature and receipt tests. | locked |
| FR-2 | The coordinator config is the only owner of run-store root and embedded project/environment/executor identity. Runtime-authored run-store values must agree; requirements are derived rather than repeated. | No implicit environment override or alternate root. | Protected service config and resident descriptor. | Matching/mismatching root and fingerprint assertions. | locked |
| FR-3 | The convenience path supports only embedded authority and embedded local execution: no agent TLS listener, remote profiles/principals/agents, or ready-stage SLURM profiles. Unsupported composition fails before run creation. | Advanced callers retain the low-level record API. | Existing deployment model. | One rejection per unsupported owner family; no Cartesian expansion. | locked |
| FR-4 | Fresh preparation persists resolved and redacted config snapshots, composition and recipe manifests, config provenance, plan, safe runtime metadata, exact managed runtime record, and embedded authority using existing formats. | No new preparation manifest/schema. | LocalRunStore and current exact record. | Exact files/owner open and digest agreement. | locked |
| FR-5 | Exact replay of a complete matching preparation returns the same receipt without writes; changed config/profile/runtime, corrupt state, or partial state conflicts explicitly. | No automatic repair, deletion, or migration. | Existing atomic records and strict loaders. | Fresh/replay timestamps or freshness unchanged; conflict/partial tests. | locked |
| FR-6 | `managed-local-basic` contains its stages, pipeline, protected local-only config template/setup, preparation entrypoint, and lifecycle runner without imports outside the copied project and installed Loom/Weave packages. | Test harness code may remain local to that directory. | Existing example catalog. | Copy directory to randomized root and run with no examples/tests import. | locked |
| FR-7 | The copied journey uses real `daemon-init` and foreground `daemon-serve`, submits only queue item plus run URI, waits, invokes `inspect-run --endpoint`, verifies artifact content, stops, restarts the same roots, and observes stable coordinator/terminal admission with a rotated epoch. | No outbound agent or network service. | Stage 29 CLI and Stage 34 inspection. | Real subprocess E2E and exact process cleanup. | locked |
| FR-8 | README and catalog describe one-time initialization, service lifetime, preparation, submission, observation, restart, local artifact access, retained state, limitations, and advanced remote/SLURM links. Correct schema-version wording and current Stage 29 planning status are restored. | No production PKI or service-manager automation claim. | Feature/docs catalog. | Documentation assertions and manifest-to-invocation parity. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1..FR-5 | Use one additive preparation facade over current owners. | The current consumer otherwise repeats six ordered operations and three execution identities. | One new public helper/receipt. | locked; maintainer approved |
| FQ-2 | FR-3 | Keep the facade embedded-only and fail on advanced configured owners. | The requested journey is one machine; silently assigning embedded identity to remote/SLURM routes would overclaim. | Advanced configurations keep the existing lower-level API. | repo-resolved |
| FQ-3 | FR-5 | Exact complete replay succeeds; all nonmatching or incomplete existing state fails closed. | Supports response-loss retry without inventing repair/overwrite semantics. | A crashed partial preparation needs a new run name or explicit operator cleanup. | locked; maintainer approved |
| FQ-4 | FR-6, FR-7 | Replace the internals of `managed-local-basic` rather than add a fourth overlapping managed journey. | Its catalog role is already the basic local lifecycle. | Existing manifest/test expectations change to the real service surfaces. | repo-resolved |

## Behavior Baseline

- A fresh safe run name becomes one canonical `file:///` run URI directly under
  the service's configured run root. The facade performs preparation only and
  emits no daemon admission.
- A complete matching run is immutable replay. An existing different or
  incomplete run is a conflict; no file, authority row, or runtime record is
  overwritten to make it match.
- The standalone service is initialized once. Ordinary starts open the same
  deployment, rotate the process epoch, and preserve coordinator/admission
  identity. Terminal run data remains after service stop.
- `inspect-run` returns metadata/locations only. The local starter reads its
  known output file directly and makes no content-relay claim.

## Minimum Design

- `loom.queue.managed_local_preparation` owns the facade and receipt. It lazily
  calls the deployment loader, Weave composition, public pipeline planning and
  runtime helpers, the existing exact record writer/loader, and embedded
  authority initializer/opener. `loom.queue.__init__` exposes both names lazily.
- The helper validates local-only service composition and run name before any
  run write. It merges config runtime options with the derived run URI, rejects
  a non-local executor or conflicting configured run root, and passes the
  service scheduling composition into exact placement preparation.
- Existing LocalRunStore documents remain authoritative. Replay compares the
  canonical resolved/redacted snapshots, composition/recipe/config provenance,
  plan, runtime metadata, exact runtime digest, and embedded authority
  availability. Comparison code is private and adds no sidecar.
- The example owns domain-neutral toy stage behavior. A machine-local protected
  service config is rendered from a committed template using the current Python
  and copied project root, then used unchanged for init, serve, and preparation.
- Dependency direction remains project/example -> public Loom; queue may depend
  on pipeline/config composition, while pipeline and lower transports never
  import queue preparation.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Preparation receipt/function | Current copyable consumer otherwise owns ordering, root/profile agreement, and replay. | Keep the long example-local sequence. | keep |
| Exact replay comparison | Response loss or repeated project command otherwise becomes an unexplained existing-directory failure. | Fresh-only helper. | keep; no repair |
| Self-contained config renderer | Protected config needs an exact machine Python/project path and Git cannot preserve owner-only mode. | Commit repository-relative or placeholder paths. | keep |
| New durable preparation record, daemon command, remote agent, service manager | Existing owners already supply the behavior. | Add machinery. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1..FR-4 | Queue preparation composes existing public config/pipeline/store owners and retains `prepare_managed_local_runtime_record` as exact intent owner. | One high-level consumer boundary without duplicate schema. | Queue facade has a lazy Weave call. | repo-resolved |
| DQ-2 | FR-2, FR-3 | Validate local-only service composition before creating the run and derive every stage requirement from the protected embedded descriptor. | Prevents path/profile drift and false advanced support. | Advanced users call the lower seam. | repo-resolved |
| DQ-3 | FR-5 | Replay is read/compare/open only and returns the canonical existing digests. | No timestamp/freshness mutation and clear immutable identity. | Partial state is not repaired. | repo-resolved |
| DQ-4 | FR-6..FR-8 | The copied example, not a test fixture, is the actual CLI subprocess E2E input. | Tests the artifact users copy. | The runner contains bounded local process orchestration. | repo-resolved |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Fresh preparation | Ordered materialization and matching execution identity. | New facade over existing owners. | Unit/integration fresh receipt and exact persisted facts. | planned |
| Exact replay/conflict | Retry must not mutate or overwrite. | Facade comparison. | Matching replay plus changed and partial cases. | planned |
| Copied standalone journey | Repository paths/helpers could hide portability failure. | Copied example and installed CLI. | Randomized copy, real service, success/artifact/restart/no PIDs. | planned |
| Public import | Queue facade must remain cheap and intentional. | Lazy queue exports. | Package import expectations/build. | planned |

Causal interactions requiring combined coverage:

- Preparation root/profile identity and actual daemon execution interact, so
  the copied E2E must consume the exact generated protected config in both.
- Restart and supervisor cleanup interact with the real service process, so
  both are asserted in the same journey.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Standalone managed-local starter | A copied project prepares and completes one run through the persistent embedded service and survives restart. | Preparation facade, public export, existing basic example, docs/tests; no advanced routes or new schema. | Merged Stages 29 and 34. | Public/replay tests, copied real-process E2E, docs/package checks, full gates. | pending |

One phase is intentional: the public facade has no consumer without the starter,
and the starter is not safe to merge while it owns the current low-level
invariants itself.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR-1..FR-8 and explicit maintainer request | pass |
| Minimum design justified | Existing owners reused; one consumer-facing composition | pass |
| Complexity delta proportionate | Two public values, no schema/service/dependency | pass |
| Contracts and private discretion clear | Embedded-only, exact replay, copied subprocess journey fixed | pass |
| Invariant ownership and validation proportionate | Root/profile/replay owners and causal E2E identified | pass |
| Phases vertical and reviewable | One bounded end-to-end phase | pass |
| No unresolved blocker | Repository evidence resolves all choices | pass |

Gate result: approved and ready for implementation.
Accepted risks and revisit triggers: partial preparation is not repaired;
advanced remote/SLURM requirements remain low-level; add overlays, plugins, or
process-manager packaging only for a concrete downstream need.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Advanced execution requirements | Deferred to existing low-level API. | One-machine starter needs only embedded identity. | Copyable remote or ready-stage consumer. |
| Preparation repair/delete | Deferred. | Cross-owner repair/forget needs its own contract. | Repeated real partial-preparation incidents. |
| Artifact content through daemon | Deferred. | Stage 34 intentionally returns metadata/locations only. | Remote content-transfer requirement. |
| systemd installation | Example file/notes only, no installer. | Process manager is site-owned. | Maintained deployment packaging requirement. |

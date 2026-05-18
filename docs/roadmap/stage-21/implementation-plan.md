# Roadmap Stage 21 Implementation Plan: Cleanup And Retention

Status: complete
Roadmap stage: `v21`
Planning document: `docs/roadmap/stage-21/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: all phases merged
Blockers:

- None before phase execution planning.

## Summary

- Goal: implement conservative, explicit cleanup, retention metadata, and
  candidate-level run-collection GC without surprising deletion of user data.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-21/planning.md`; FR-1 through FR-8 are closed.
- Approved behavior: dry-run first; explicit delete intent for mutation;
  managed-root and ownership safety checks; bounded selectors such as
  `--older-than 7d`; append-only cleanup result records as correctness
  evidence; cleanup events as Stage 20 audit projections; event sinks
  observe-only; candidate-level GC only.
- Source behavior confirmation: complete in the planning artifact after user
  approval of capability triage, functionality, behavior, design agreement,
  design-safety review, examples, validation strategy, and phase shaping.
- Key design constraints: keep Loom domain-neutral, dependency-light,
  import-light, plain-data-compatible, fake/local-test friendly, explicit
  about destructive intent, and conservative about ownership proof.
- Source design-agreement gate: confirmed. Use `loom.pipeline.cleanup` for
  cleanup records, selectors, safety, planning, execution, event projection,
  and errors; keep CLI and diagnostics as wrappers/readers; keep default
  dry-run previews side-effect-free, allow only explicit recorded report
  facts, and persist mutating cleanup result facts through authority when
  deletion evidence is needed.
- Future-roadmap impact: remote deletion, provider retention enforcement,
  whole-run deletion, organization policy engines, cleanup-specific sink
  plugins, and automatic retention enforcement remain deferred and compatible
  with the proposed record/adapter boundaries.
- Reusable interface, adapter, or protocol assumptions: cleanup selectors,
  reports, safety decisions, delete intent, result records, retention helpers,
  and target adapters stay generic. Target adapters prove capability and
  ownership; they do not own selector policy, retention semantics, or delete
  intent.
- Examples covered: per-run dry-run, bounded selector cleanup, explicit
  deletion and result records, path-safety rejection, retention inspection,
  candidate-level collection GC, cleanup/retention preflight warnings, and
  cleanup audit event projection.
- Source phase shaping: five phases confirmed in the planning artifact.
- Source plan quality gate: passed after local manager-equivalent review on
  2026-05-18.
- Out of scope: whole-run deletion, automatic retention enforcement,
  aggressive artifact GC, global cache cleanup, arbitrary cleanup query
  language, arbitrary directory cleanup, cleanup-specific event sink plugins,
  remote provider deletion enforcement, and provider SDK dependencies.

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: completed 2026-05-18
- Refinement pass: completed 2026-05-18; clarified Phase 2/Phase 3 durable
  fact ownership
- Confirmation review: completed 2026-05-18
- Automatic merge mode: enabled after plan quality gate and phase PR gates
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-21/planning.md`
- Functionality and behavior baseline: complete. The notes lock dry-run-first
  cleanup, explicit delete intent, path safety, retention hints, bounded
  selectors, candidate-level GC, cleanup result records, cleanup event
  projection, preflight warnings, and explicit deferrals.
- Design agreement: complete. All DAQ-1 through DAQ-10 decisions are confirmed
  with no unresolved `blocked` or `needs discussion` items.
- Design-safety review: passed. The review added two hardening constraints:
  cleanup results append outcome facts instead of mutating/removing candidates,
  and managed roots come from trusted authority/store/config facts, not broad
  collection input paths.
- Examples and validation strategy: complete. Validation is layered across
  package/import, unit, contract, integration, CLI/e2e, opt-in unsupported
  behavior, and final suite evidence.
- Phase shaping: complete. Five phases are recorded below.
- Implementation readiness blockers from planning: none after the user
  instructed continuing to implementation-plan drafting on 2026-05-18.
- Accepted risks and revisit triggers:
  - Unrecorded dry-run previews are not persisted or emitted as events by
    default. Revisit if audit-heavy deployments require recorded preview
    reports.
  - Stage 21 first deletion adapter is local-filesystem only. Revisit when
    remote artifact-store deletion or provider retention enforcement enters
    scope.
  - Cleanup result persistence adds authority schema and compatibility work.
    Revisit if result records become too large or too slow for authority-backed
    storage without compaction or paging.
  - Whole-run deletion remains outside first GC. Revisit when terminal-state,
    active-lease, submitted-operation, dependency/reference, marker/provenance,
    and tombstone semantics are designed.

## Desired Outcome

When all phases are complete:

- Users can inspect per-run and collection-level cleanup candidates before any
  deletion happens.
- Programmatic cleanup deletion requires explicit `CleanupDeleteIntent` or an
  equivalent structured intent record.
- CLI cleanup commands present dry-run output by default and require
  confirmation or `--yes` for deletion.
- Cleanup selectors are bounded and explainable, including age/timestamp,
  metadata/tag, retention mode, candidate kind/reason, status/stage, and
  artifact fields.
- Cleanup deletes only approved Loom-owned local targets under trusted managed
  roots; symlinks, outside-root paths, missing ownership evidence, and
  unsupported remote/external refs are rejected visibly.
- Mutating cleanup appends cleanup result facts that reference candidate ids,
  target refs, revisions, and outcomes.
- Recorded cleanup report facts and mutating cleanup result facts project into
  compact Stage 20 event records after the cleanup fact exists; event sinks
  remain observe-only.
- Retention modes `keep`, `temporary`, `archive`, and `external` are typed,
  inspectable, serializable hints and do not trigger automatic deletion.
- Run-collection GC operates over selected cleanup candidates inside runs and
  never deletes whole run directories.
- Preflight warns about unsafe cleanup candidates, unsupported retention
  policies, unsupported remote/external deletion, and cleanup paths whose
  managed-root or ownership evidence cannot be proven.

## Non-Goals

- No automatic retention deletion, background TTL sweeps, cleanup daemon, or
  implicit cleanup on execution.
- No whole-run directory deletion or run tombstones.
- No remote/provider deletion enforcement, cloud SDK dependency, or provider
  credential probing.
- No arbitrary cleanup query language.
- No arbitrary directory cleanup, global cache GC, or directory guessing.
- No cleanup-specific event sink plugin loading or service-specific
  notification/tracking behavior.
- No event-sink authorization or veto of cleanup correctness.
- No domain-specific retention classes such as checkpoints, datasets, reports,
  metrics, or model artifacts.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep `loom.pipeline.cleanup.records` and retention helpers import-light.
  They must not import CLI, diagnostics, plugins, concrete executors, provider
  SDKs, or project packages.
- Cleanup planning/execution may import store protocols, authority read models,
  retention helpers, path helpers, and Stage 20 event projection helpers.
- CLI imports public cleanup APIs and owns argument parsing, presentation, and
  confirmation only.
- Diagnostics and preflight remain read-only.
- Stores persist cleanup facts but do not own deletion policy.
- Target adapters prove target support, capability, ownership, and deletion
  execution; they do not own selectors, retention semantics, or delete intent.
- Cleanup result facts are append-only relative to cleanup candidates.
- Managed roots come from trusted authority/store/config facts and local path
  helpers, not user-supplied collection directories.
- All tests stay domain-neutral, local by default, and network-free. Use
  temporary directories, fake sinks, fake unsupported refs, and fake/local
  authority stores.
- Every phase PR must run targeted validation. PR preparation must run
  `make validate-pr` and `make test-summary` unless unavailable and justified
  in the phase artifacts.

## Design Principles

- Preview before mutation. Dry-run is the default and unrecorded previews do
  not write authority facts or events.
- Explicit destructive intent. Mutation requires a structured delete-intent
  value or CLI confirmation/`--yes`.
- Authority facts over directory guessing. Cleanup candidates, result facts,
  retention hints, statuses, leases, and submitted operations come from
  authoritative records.
- Safety rejects instead of repairing. Missing ownership evidence, unsafe paths,
  symlinks, unsupported refs, and deletion failures are visible outcomes.
- Result facts before events. Cleanup events project recorded cleanup facts and
  never become the sole evidence source.
- Thin CLI. Command modules parse, confirm, call APIs, and format records.
- Generic records first. Retention and cleanup records stay plain-data and
  provider-neutral.
- Per-run semantics before collection GC. Collection behavior reuses per-run
  cleanup and does not create a second deletion engine.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Cleanup ownership | Add `loom.pipeline.cleanup` for records, selectors, safety, planning, execution, event projection, and errors | Centralizes cleanup policy and keeps CLI/diagnostics thin |
| Durable evidence | Keep default dry-run reports side-effect-free; persist explicit recorded report facts and mutating cleanup result facts through authority when durable evidence is needed | Store schemas and protocols grow, but preview safety and deletion evidence remain reviewable |
| Candidate compatibility | Preserve existing cleanup candidates and append result facts instead of mutating/removing candidates | Old records remain readable and future reconciliation can use candidate/result ids |
| Dry-run side effects | Unrecorded dry-run previews are side-effect-free by default | True previews are safe; optional recorded reports can be added later |
| Delete intent | Require structured delete intent in Python APIs and confirmation/`--yes` in CLI | Avoids accidental destructive behavior and avoids prompt logic in APIs |
| Safety model | Validate trusted managed roots, ownership evidence, and symlink rejection before deletion | Data-loss risk stays explicit and testable |
| Selector model | Use bounded plain-data selectors and no query language | Keeps matching explainable and serializable |
| Retention | Add typed `RetentionMode`/`RetentionPolicy` helpers over plain-data metadata | Retention is visible but not automatic deletion policy |
| Collection GC | Discover runs from input/catalogs but open each run authority for cleanup truth | Catalogs never authorize deletion |
| Events | Emit compact cleanup events for recorded report/result facts only | Event sinks can observe without becoming correctness dependencies |
| Remote/external refs | Report unsupported deletion unless a future store-owned adapter proves support and ownership | Keeps Stage 21 provider-neutral |

## Conflicts And Tradeoffs

| Tradeoff | Decision | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Authority persistence vs. simpler CLI output | Persist result facts through authority | Cleanup evidence must survive CLI/process boundaries and be inspectable | Result facts become too large or slow without paging/compaction |
| Side-effect-free dry-run vs. complete audit of previews | Dry-runs are not recorded by default | Users expect preview to avoid mutation | Audit-heavy deployments require recorded preview reports |
| Local-only deletion vs. early provider support | Implement only local filesystem deletion | Remote deletion has provider, credential, and capability risk | Remote deletion/provider retention enters roadmap scope |
| Bounded selectors vs. query expressiveness | Use bounded selector records | Safety, serialization, and explanation matter more than expressiveness | Users need compound boolean cleanup policy |
| Candidate-level GC vs. whole-run cleanup | Defer whole-run deletion | Whole-run deletion has higher blast radius and needs extra gates | Whole-run deletion enters roadmap scope |

## Maintainability Assessment

The plan keeps cleanup behavior in one policy layer and moves presentation,
diagnostics, authority persistence, and event projection behind explicit
boundaries. This is maintainable because destructive behavior is not spread
across CLI, run catalogs, stores, diagnostics, or event sinks.

The main cost is authority persistence for cleanup results. That is acceptable
because deletion needs durable, inspectable evidence. Phase ordering keeps that
cost reviewable before local deletion lands.

## Extensibility Assessment

The records/selectors/results design can grow deliberately:

- New bounded selectors can be added as fields with tests and docs.
- Future target adapters can prove store-owned deletion support without
  changing selector or result semantics.
- Future whole-run deletion can reuse selectors, safety decisions, results, and
  event projection while adding stronger gates and tombstones.
- Organization policy engines can compile policy into selectors and retention
  hints later without entering core Stage 21 behavior.
- Service-specific event sinks remain plugins over Stage 20 event contracts.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Cleanup report and result facts add authority schema surface. | Durable cleanup evidence is required for correctness and auditability. | Result facts become too large or slow without paging/compaction. |
| Unrecorded dry-run previews are not durable audit facts. | Preserves true preview behavior and avoids surprising writes. | Audit-heavy users require recorded preview reports by default. |
| First deletion adapter is local-filesystem only. | Keeps first destructive behavior deterministic, local, and testable. | Remote artifact-store deletion or provider retention enforcement enters scope. |
| CLI selector set starts bounded. | Avoids query-language complexity and unsafe implicit policy. | Users need compound boolean selector logic. |
| Whole-run deletion remains deferred. | User confirmed candidate-level GC first and stronger whole-run gates are needed. | Whole-run deletion is explicitly planned. |

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `cleanup-records-contracts` | merged | `codex/cleanup-records-contracts` | https://github.com/samcantrill/loom/pull/191 | `loom.pipeline.cleanup`, `loom.artifacts`, tests | Cleanup records, retention, selectors, and safety contracts | package, unit, contract | dry-run records, selectors, safety, retention |
| 2 | `cleanup-dry-run-authority` | merged | `codex/cleanup-dry-run-authority` | https://github.com/samcantrill/loom/pull/192 | authority/read models, dry-run planner, diagnostics inspection | Authority-backed dry-run reports, explicit recorded report facts, and compatible result-fact scaffolding | unit, contract, integration | per-run dry-run, retention inspection |
| 3 | `cleanup-delete-events` | merged | `codex/cleanup-delete-events` | https://github.com/samcantrill/loom/pull/193 | cleanup execution, local target adapter, event projection | Explicit local deletion and cleanup audit events | unit, contract, integration | explicit deletion, path rejection, audit event |
| 4 | `cleanup-collection-preflight` | merged | `codex/cleanup-collection-preflight` | https://github.com/samcantrill/loom/pull/194 | collection GC, run discovery boundary, preflight/diagnostics | Candidate-level collection GC and preflight warnings | unit, contract, integration | collection GC, preflight warnings |
| 5 | `cleanup-cli-docs` | merged | `codex/cleanup-cli-docs` | https://github.com/samcantrill/loom/pull/195 | CLI, formatting, docs, final validation | `loom clean`, `loom gc`, docs, and final evidence | package, unit, contract, integration, e2e, final gate | CLI clean/gc flows |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| None from implementation-plan quality gate | quality gate | No action required before phase execution planning. | resolved |

## Phase 1: Cleanup Records, Retention, Selectors, And Safety Contracts

Status: merged
Slug: `cleanup-records-contracts`
Branch: `codex/cleanup-records-contracts`
Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-records-contracts`
PR: https://github.com/samcantrill/loom/pull/191
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: add the import-light value records and normalization helpers needed for
  cleanup planning without store mutations or filesystem deletion.
- Files/modules owned:
  - `src/loom/pipeline/cleanup/`
  - `src/loom/artifacts.py`
  - Package/unit/contract tests for cleanup records, retention, selectors, and
    safety decisions.
- Behavior implemented:
  - Cleanup report/result, target, managed-root, selector, safety decision, and
    delete-intent records where they do not require persistence.
  - Bounded selector normalization/matching over plain-data candidate facts.
  - `RetentionMode`/`RetentionPolicy` helpers over existing plain-data
    retention metadata.
  - Path-safety decision helpers for trusted managed-root inputs.
- Decisions applied: DAQ-1, DAQ-3, DAQ-4, DAQ-5, DAQ-6, DAQ-9.
- Examples or docs covered: bounded selector cleanup, path-safety rejection,
  retention inspection record behavior.
- Out of scope: authority schema changes, deletion, events, collection GC, CLI.
- Dependencies: Stage 20 event records exist but are not used in this phase.

### Tasks

- Create the `loom.pipeline.cleanup` package and public exports.
- Define strict plain-data record types and errors.
- Add selector normalization/matching and explanation records.
- Add retention helpers while preserving current metadata compatibility.
- Add local path-safety decision helpers without deletion.
- Add package, unit, and contract tests.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/package` | Public import and package surface check | yes |
| `uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/test_artifacts.py` or phase-created equivalents | Cleanup record, selector, safety, and retention unit behavior | yes |
| `uv run pytest tests/contracts` with cleanup-specific paths where created | Plain-data public record compatibility | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Acceptance Evidence

- Behavior evidence: selector and safety helpers return deterministic reports
  and reason codes without deleting files.
- Design-decision evidence: cleanup policy vocabulary exists outside CLI and
  diagnostics.
- Future-roadmap compatibility evidence: no provider-specific deletion,
  retention, or query-language behavior lands.
- Interface, adapter, or protocol reuse evidence: records are plain-data and
  import-light.
- Documentation evidence: feature docs or API docs updated only where public
  names are introduced.
- Domain-neutrality evidence: tests use generic fake candidates and temporary
  paths only.

### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: used
- Implementation/refinement budget: not needed after validation passed
- PR review budget: completed by manager review
- Blocker-resolution budget: 1 of 3 used for sandbox-only service socket validation rerun
- Pre-submit blocker gate: do not start if plan quality gate is not passed
- Merge record: merged into `develop` on 2026-05-18 via PR #191; branch kept temporarily until Phase 2 was rebased away from it

### Risks And Stop Conditions

- Risks:
  - Record names may overfit implementation details.
  - Safety helpers may accidentally depend on local path layout assumptions.
- Stop conditions:
  - A selector requires arbitrary expression parsing.
  - Retention helpers require provider-specific semantics.
  - Safety validation needs store facts not available until Phase 2; defer
    those checks instead of inventing placeholders.
- Assumptions:
  - Existing serialization helpers are sufficient for plain-data records.

### Completion Summary

- Implementation: Added `loom.pipeline.cleanup` records, selectors, safety
  decisions, errors, and public exports; added generic retention helpers in
  `loom.artifacts`.
- Validation: Targeted cleanup package/unit/contract tests passed; targeted
  Ruff and Pyright passed; `make validate-pr` and `make test-summary` passed
  outside the sandbox after sandboxed service-authority socket tests were
  blocked by `PermissionError: [Errno 1] Operation not permitted`.
- PR: https://github.com/samcantrill/loom/pull/191 targeted `develop` from
  `codex/cleanup-records-contracts`; CI `checks` completed successfully.
- Merge: Squash-merged to `develop` on 2026-05-18 after target, CI,
  validation, scope, and manager review gates passed.
- Follow-up: Phase 2 was initially stacked on this branch, then rebased onto
  updated `develop`; Phase 1 branch/worktree can be cleaned once stack cleanup
  is complete.

## Phase 2: Authority-Backed Dry-Run Planning And Inspection

Status: merged
Slug: `cleanup-dry-run-authority`
Branch: `codex/cleanup-dry-run-authority`
Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-dry-run-authority`
PR: https://github.com/samcantrill/loom/pull/192
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: build side-effect-free cleanup dry-run planning over authoritative run
  facts and add cleanup report fact support plus cleanup result fact contract
  scaffolding where durable evidence paths require it.
- Files/modules owned:
  - `src/loom/pipeline/cleanup/planning.py` or equivalent
  - `src/loom/pipeline/stores/read_models.py`
  - `src/loom/pipeline/stores/authority.py`
  - Concrete authority/service authority protocol payloads as needed
  - `src/loom/diagnostics/backend.py` where read-only inspection is in scope
  - Store/authority/unit/contract/integration tests
- Behavior implemented:
  - Per-run `plan_cleanup(...)` dry-run reports.
  - Explicit recorded cleanup report fact records and append/list support where
    durable dry-run evidence is needed.
  - Cleanup result fact contract scaffolding only where it is required to keep
    later mutating result persistence compatible.
  - Existing cleanup candidate compatibility and bundle/import visibility.
  - Inspection of cleanup reports/results and retention hints where useful.
  - Proof that unrecorded dry-run previews do not write authority or events.
- Decisions applied: DAQ-1, DAQ-2, DAQ-3, DAQ-4, DAQ-6, DAQ-7.
- Examples or docs covered: per-run cleanup dry-run, retention inspection.
- Out of scope: deletion, mutating cleanup result production, events,
  collection GC, CLI.
- Dependencies: Phase 1 records and safety helpers.

### Tasks

- Extend read models and authority protocols with explicit recorded cleanup
  report fact records and any cleanup result fact contract scaffolding needed
  for Phase 3 compatibility.
- Implement concrete backend append/list behavior and serialization for
  explicit recorded report facts. Defer mutating cleanup result writes to
  Phase 3 unless a backend contract must be introduced here for compatibility.
- Implement dry-run planning over candidates, materialized refs, retention
  hints, statuses, leases, submitted operations, and trusted roots.
- Add diagnostics/backend inspection for cleanup/retention facts where useful.
- Add tests proving no writes happen during default dry-run previews.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/pipeline/stores tests/unit/loom/diagnostics` or phase-created equivalents | Planner, authority facts, and inspection unit behavior | yes |
| `uv run pytest tests/contracts` with authority cleanup paths | Protocol serialization and append/list compatibility | yes |
| `uv run pytest tests/integration` with cleanup-specific paths | Local/fake authority dry-run collaboration | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Acceptance Evidence

- Behavior evidence: dry-run reports selected, skipped, rejected candidates and
  stable reason codes without deleting or writing by default.
- Behavior evidence: default dry-run report generation does not append
  authority facts or events; any recorded report path is explicit.
- Design-decision evidence: cleanup facts are append-only relative to
  candidates.
- Future-roadmap compatibility evidence: facts reference candidate ids,
  targets, revisions, and outcomes for future reconciliation.
- Interface, adapter, or protocol reuse evidence: authority contracts expose
  append/list cleanup facts without leaking backend schemas.
- Documentation evidence: inspection/docs updated where new fields surface.
- Domain-neutrality evidence: tests use generic candidate kinds and temporary
  paths.

### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: used
- Implementation/refinement budget: used locally during validation
- PR review budget: completed by manager review
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 1 merged; PR targets `develop`
- Merge record: merged into `develop` on 2026-05-18 via PR #192; remote branch deletion required manual cleanup because the first local `gh pr merge --delete-branch` attempt merged but failed local branch cleanup

### Risks And Stop Conditions

- Risks:
  - Authority schema changes may be larger than expected.
  - Managed-root discovery may be too implicit.
- Stop conditions:
  - Dry-run implementation needs to mutate state to compute reports.
  - Existing cleanup candidates cannot be preserved without breaking
    compatibility.
  - Authority fact records need non-plain-data payloads.
- Assumptions:
  - Local/fake authority paths can support cleanup fact tests without network.

### Completion Summary

- Implementation: Added side-effect-free cleanup planning, explicit cleanup
  report recording, cleanup report/result facts, append/list authority
  contracts across backends/service/client/repository paths, and cleanup
  report/result diagnostics inspection.
- Validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 107
  passed / 1 skipped, unit 1378 passed / 7 skipped / 1 deselected, contract
  270 passed / 2 skipped, integration 166 passed / 8 skipped / 13 deselected,
  e2e 44 passed / 2 deselected, and config-extra 449 passed / 3 skipped / 1974
  deselected. GitHub CI `checks` completed successfully.
- PR: https://github.com/samcantrill/loom/pull/192 targets `develop` from
  `codex/cleanup-dry-run-authority`; target verified with
  `gh pr view 192 --json baseRefName,headRefName,state,url`.
- Merge: Squash-merged to `develop` on 2026-05-18 as
  `c9dd0a46986f2b9bf5bd80d4a2bbe21dc545d86d` after target, CI, validation,
  scope, and manager review gates passed.
- Follow-up: Phase 3 should branch from updated `develop`; no successor branch
  depends on `codex/cleanup-dry-run-authority`.

## Phase 3: Explicit Local Deletion And Cleanup Event Projection

Status: merged
Slug: `cleanup-delete-events`
Branch: `codex/cleanup-delete-events`
Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-delete-events`
PR: https://github.com/samcantrill/loom/pull/193
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: implement explicit local filesystem deletion for approved targets,
  complete mutating cleanup result persistence, and project recorded cleanup
  facts into Stage 20 cleanup audit events.
- Files/modules owned:
  - `src/loom/pipeline/cleanup/execution.py` or equivalent
  - `src/loom/pipeline/cleanup/events.py` or equivalent
  - Local deletion adapter/helper modules
  - Cleanup/event/unit/contract/integration tests
- Behavior implemented:
  - `execute_cleanup(...)` requiring structured delete intent.
  - Local filesystem deletion for approved Loom-owned targets.
  - Cleanup result persistence for deleted, skipped, rejected, and failed
    outcomes.
  - Cleanup result append/list backend behavior completed where Phase 2 only
    introduced contract scaffolding.
  - Cleanup event projection from recorded report/result facts.
  - Observe-only sink dispatch and sink-failure non-blocking behavior.
- Decisions applied: DAQ-2, DAQ-3, DAQ-4, DAQ-8, DAQ-9.
- Examples or docs covered: explicit deletion, path-safety rejection, cleanup
  audit event.
- Out of scope: remote/provider deletion, whole-run deletion, collection GC,
  CLI confirmation.
- Dependencies: Phases 1 and 2.

### Tasks

- Implement delete-intent-gated cleanup execution.
- Add local target deletion with strict safety checks and no symlink following.
- Persist cleanup results before event projection, including any backend write
  paths deferred from Phase 2 scaffolding.
- Add compact cleanup event payload projection and dispatch integration.
- Add unit, contract, and integration tests for destructive and event paths.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/pipeline/event_sinks` or phase-created equivalents | Delete intent, local outcomes, event projection, sink failure behavior | yes |
| `uv run pytest tests/contracts` with cleanup event paths | Cleanup event payload and fact-reference compatibility | yes |
| `uv run pytest tests/integration` with cleanup deletion/event paths | Temporary-directory deletion, result append, event append-before-dispatch | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Acceptance Evidence

- Behavior evidence: only explicitly intended cleanup deletes approved targets;
  unsafe targets are rejected visibly.
- Design-decision evidence: result facts append before event projection; event
  sinks do not alter cleanup correctness.
- Future-roadmap compatibility evidence: target adapter remains local and
  capability/ownership-focused.
- Interface, adapter, or protocol reuse evidence: event payloads reference
  durable facts and remain compact.
- Documentation evidence: safety/event docs updated if public behavior changes.
- Domain-neutrality evidence: no provider SDKs, no project artifacts, no domain
  semantics.

### Phase Workflow State

- Phase execution plan: complete
- Planning/refinement budget: used
- Implementation/refinement budget: used locally during validation
- PR review budget: completed by manager review
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 2 merged; PR targets `develop`
- Merge record: merged into `develop` on 2026-05-18 via PR #193; no successor branch depended on this branch

### Risks And Stop Conditions

- Risks:
  - Filesystem edge cases can be subtle across platforms.
  - Event projection could duplicate too much target detail.
- Stop conditions:
  - Deletion cannot reject symlink traversal reliably.
  - Delete API can be invoked with only a bare boolean.
  - Event sinks are required for cleanup success.
- Assumptions:
  - Tests can cover deletion behavior using temporary directories without
    external services.

### Completion Summary

- Implementation: Added `execute_cleanup`, local-only deletion with
  execution-time safety rechecks, cleanup result fact recording, compact
  cleanup report/result event projection, optional runtime event dispatcher
  support, and public cleanup exports.
- Validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 107
  passed / 1 skipped, unit 1384 passed / 7 skipped / 1 deselected, contract
  271 passed / 2 skipped, integration 167 passed / 8 skipped / 13 deselected,
  e2e 44 passed / 2 deselected, and config-extra 449 passed / 3 skipped / 1982
  deselected. GitHub CI `checks` completed successfully.
- PR: https://github.com/samcantrill/loom/pull/193 targets `develop` from
  `codex/cleanup-delete-events`; target verified with
  `gh pr view 193 --json baseRefName,headRefName,state,url`.
- Merge: Squash-merged to `develop` on 2026-05-18 as
  `a2126a817dc1bfe358124283b589ee9fcda14574` after target, CI, validation,
  scope, and manager review gates passed.
- Follow-up: Phase 4 should branch from updated `develop`; no successor branch
  depends on `codex/cleanup-delete-events`.

## Phase 4: Candidate-Level Run-Collection GC And Preflight Warnings

Status: merged
Slug: `cleanup-collection-preflight`
Branch: `codex/cleanup-collection-preflight`
Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-collection-preflight`
PR: https://github.com/samcantrill/loom/pull/194
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: add collection-level candidate cleanup and read-only cleanup/retention
  preflight warnings over stable per-run cleanup APIs.
- Files/modules owned:
  - `src/loom/pipeline/cleanup/collection.py` or equivalent
  - `src/loom/diagnostics/preflight.py`
  - `src/loom/diagnostics/models.py`
  - `src/loom/runs` call sites only for discovery/presentation if needed
  - Collection/preflight/unit/contract/integration tests
- Behavior implemented:
  - `plan_collection_gc(...)` and `execute_collection_gc(...)` or equivalent.
  - Candidate-level GC across run collections.
  - Run catalog and collection inputs used only for discovery.
  - Preflight warnings for unsafe cleanup candidates, unsupported retention
    policies, unsupported remote/external deletion, and missing ownership/root
    evidence.
- Decisions applied: DAQ-4, DAQ-5, DAQ-6, DAQ-7, DAQ-9, DAQ-10.
- Examples or docs covered: run-collection GC dry-run/delete and cleanup
  preflight warnings.
- Out of scope: CLI commands, whole-run deletion, automatic retention
  enforcement, remote provider deletion.
- Dependencies: Phases 1 through 3.

### Tasks

- Implement aggregate collection cleanup reports/results over per-run APIs.
- Add discovery boundaries so catalogs/collection paths never authorize
  deletion.
- Add read-only preflight warning checks and stable ids.
- Add diagnostics rendering where applicable.
- Add integration tests over multiple temporary runs.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/diagnostics` or phase-created equivalents | Collection aggregation and warning behavior | yes |
| `uv run pytest tests/contracts` with cleanup/preflight paths | Aggregate records and warning payload compatibility | yes |
| `uv run pytest tests/integration` with collection/preflight paths | Multiple-run GC and read-only diagnostics collaboration | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Acceptance Evidence

- Behavior evidence: collection reports/results aggregate per-run cleanup
  without deleting whole runs.
- Design-decision evidence: catalogs are discovery inputs only.
- Future-roadmap compatibility evidence: whole-run deletion remains deferred
  and separate.
- Interface, adapter, or protocol reuse evidence: collection APIs reuse per-run
  cleanup records/results.
- Documentation evidence: preflight warning ids and behavior documented where
  public.
- Domain-neutrality evidence: tests use generic temporary run directories and
  fake unsupported refs.

### Phase Workflow State

- Phase execution plan:
  `docs/roadmap/stage-21/phases/cleanup-collection-preflight.md`
- Planning/refinement budget: used locally for expanded-path phase planning
- Implementation/refinement budget: used locally during validation to fix a
  pytest module-name collision and diagnostics public export contract
- PR review budget: completed by manager review
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 3 must be merged or used as stack predecessor
- Merge record: merged into `develop` on 2026-05-18 via PR #194 after target,
  CI, validation, scope, and manager review gates passed.

### Risks And Stop Conditions

- Risks:
  - Collection iteration may need paging later.
  - Preflight may be tempted to run expensive validation.
- Stop conditions:
  - GC needs whole-run deletion to meet acceptance criteria.
  - Preflight mutates cleanup facts, dispatches events, or loads provider
    plugins.
  - Catalog rows are used as deletion authority.
- Assumptions:
  - Simple collection iteration is acceptable for Stage 21; paging can be a
    future improvement.

### Completion Summary

- Implementation: added collection cleanup aggregate records and
  `plan_collection_gc` / `execute_collection_gc` helpers over per-run cleanup
  planning/execution, plus optional cleanup preflight targets and stable cleanup
  warning ids.
- Validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 107
  passed / 1 skipped, unit 1389 passed / 7 skipped / 1 deselected, contract
  272 passed / 2 skipped, integration 168 passed / 8 skipped / 13 deselected,
  e2e 44 passed / 2 deselected, and config-extra 449 passed / 3 skipped /
  1989 deselected.
- PR: https://github.com/samcantrill/loom/pull/194 targets `develop` from
  `codex/cleanup-collection-preflight`; target verified with
  `gh pr view 194 --json baseRefName,headRefName,state,url`.
- Merge: Squash-merged to `develop` on 2026-05-18 as
  `e49751ce5d3976d603d147c2fc91bb426a7d7ecf` after target, CI, validation,
  scope, and manager review gates passed.
- Follow-up: Phase 5 should branch from updated `develop`; no successor branch
  depends on `codex/cleanup-collection-preflight`.

## Phase 5: CLI Commands, Documentation, And Final Validation

Status: merged
Slug: `cleanup-cli-docs`
Branch: `codex/cleanup-cli-docs`
Worktree: `/home/samcantrill/work/loom-worktrees/cleanup-cli-docs`
PR: https://github.com/samcantrill/loom/pull/195
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: expose cleanup and GC through thin CLI commands and update docs,
  examples, and final validation evidence.
- Files/modules owned:
  - `src/loom/cli/clean.py`
  - `src/loom/cli/gc.py` or a combined cleanup CLI module
  - `src/loom/cli/main.py`
  - CLI formatting/errors as needed
  - Feature docs and implementation-plan metadata
  - CLI/unit/integration/e2e tests
- Behavior implemented:
  - `loom clean RUN_URI` dry-run/default preview and explicit deletion.
  - `loom gc <collection>` candidate-level collection cleanup.
  - Bounded selector flags including representative `--older-than 7d`.
  - Confirmation/`--yes` behavior for mutating commands.
  - Text and JSON output from public cleanup records.
  - Final docs and validation evidence.
- Decisions applied: all DAQ decisions, especially DAQ-10.
- Examples or docs covered: all confirmed examples.
- Out of scope: CLI-owned deletion policy, whole-run deletion flags,
  provider deletion commands, cleanup-specific event sink loading.
- Dependencies: Phases 1 through 4.

### Tasks

- Add CLI command modules and parser registration.
- Add selector flag parsing into cleanup selector records.
- Add confirmation/`--yes`, text/JSON formatting, and error/exit mapping.
- Update docs for cleanup safety, retention, GC, preflight, and deferrals.
- Add CLI/e2e tests and final suite validation.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/cli` with cleanup paths | Parser, formatting, confirmation, and error mapping | yes |
| `uv run pytest tests/contracts` with CLI/API output paths | JSON/plain-data output compatibility | yes |
| `uv run pytest tests/integration` with CLI cleanup paths | CLI handlers over temporary runs/fake authority | yes |
| `make test-e2e` or narrower cleanup CLI e2e paths | User-visible dry-run/delete command behavior | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Final suite evidence for PR body | yes |

### Acceptance Evidence

- Behavior evidence: CLI dry-run/delete and collection GC flows match public
  cleanup APIs.
- Design-decision evidence: CLI does not implement deletion policy and does not
  treat collection paths as ownership proof.
- Future-roadmap compatibility evidence: whole-run/provider deletion remains
  documented as deferred.
- Interface, adapter, or protocol reuse evidence: JSON output is public
  plain-data cleanup records.
- Documentation evidence: feature docs and CLI docs describe safety, examples,
  validation, and deferrals.
- Domain-neutrality evidence: examples and tests use synthetic runs only.

### Phase Workflow State

- Phase execution plan: `docs/roadmap/stage-21/phases/cleanup-cli-docs.md`
- Planning/refinement budget: used locally for expanded-path phase planning.
- Implementation/refinement budget: used locally to preserve import-light CLI
  behavior and fix Pyright summary typing.
- PR review budget: completed by local manager review.
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 4 merged; PR targets `develop`.
- Merge record: merged into `develop` by squash merge after final target-branch
  verification, GitHub CI success, and mergeable state `CLEAN`; merge commit
  `af4ebec1a10cc8115aa7458e24465eb96430d410`.

### Risks And Stop Conditions

- Risks:
  - CLI flag naming may overfit the first implementation.
  - E2E setup may duplicate lower-level fixtures if not scoped carefully.
- Stop conditions:
  - CLI needs arbitrary query parsing.
  - CLI implements independent deletion rules.
  - CLI exposes whole-run deletion flags.
- Assumptions:
  - `argparse` remains the CLI framework.

### Completion Summary

- Implementation: added `loom clean` and `loom gc` CLI commands, bounded
  selector parsing, confirmation gates, delete intent propagation, JSON/text
  output, docs, and phase-scoped tests.
- Validation: `make validate-pr` passed with default harness `1963 passed, 26
  skipped, 21 deselected`, config-extra `449 passed, 3 skipped, 2001
  deselected`, Ruff, Pyright, and build success. `make test-summary` passed
  with package `108 passed, 1 skipped`; unit `1394 passed, 7 skipped, 1
  deselected`; contract `274 passed, 2 skipped`; integration `170 passed, 8
  skipped, 13 deselected`; e2e `46 passed, 2 deselected`; config-extra `449
  passed, 3 skipped, 2001 deselected`.
- PR: https://github.com/samcantrill/loom/pull/195 opened against `develop`;
  automated manager review found no blocking findings, target verification
  confirmed base `develop` and head `codex/cleanup-cli-docs`, and GitHub CI
  `checks` passed before merge.
- Merge: squash-merged into `develop` at
  `af4ebec1a10cc8115aa7458e24465eb96430d410` after final target-branch
  verification confirmed base `develop`, head `codex/cleanup-cli-docs`,
  mergeable state `CLEAN`, and GitHub CI `checks` success.
- Follow-up: Stage 21 is complete; no successor branch depends on
  `codex/cleanup-cli-docs`, and the phase worktree plus stale branch are
  eligible for cleanup.

## Cross-Phase Validation

- Full relevant test command: each phase runs targeted tests plus
  `make validate-pr` and `make test-summary` before PR preparation.
- Docs/template checks: update `docs/features/reliability.md`,
  `docs/features/artifacts.md`, `docs/features/cli.md`,
  `docs/features/preflight.md`, `docs/features/run-catalog.md`, and roadmap
  artifacts when behavior lands.
- Domain-neutrality checks: no provider SDKs, no project package imports, no
  domain-specific retention classes, and no real external services in default
  tests.
- Example/demo checks: phase plans must cite which confirmed examples they
  cover and which remain pending.
- Manual review focus: destructive path safety, explicit intent, authority
  append-only cleanup facts, event projection ordering, and catalog/preflight
  non-authority boundaries.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Phase 2 durable-fact scope blurred side-effect-free dry-run previews with mutating cleanup result evidence. | concern | Clarified that Phase 2 owns dry-run planning, explicit recorded report facts, and result-fact contract scaffolding only; Phase 3 owns mutating result production, result persistence, and event projection. | resolved |

Gate result:

- Status: passed
- Review evidence:
  - Local manager-equivalent implementation-plan quality review completed on
    2026-05-18 against `docs/roadmap/stage-21/planning.md`,
    `docs/roadmap.md`, repository structure/workflow guidance, and the drafted
    Stage 21 implementation plan.
  - Review covered planning readiness, functionality traceability,
    maintainability, extensibility, future-roadmap compatibility, design
    conflicts and tradeoffs, technical debt, test strategy, phase shaping, and
    reviewability.
  - One refinement pass was applied to clarify the Phase 2/Phase 3 durable fact
    boundary; confirmation review found no remaining blockers before phase
    execution planning.
- Accepted risks:
  - Local-filesystem deletion only in Stage 21.
  - Unrecorded dry-run previews are not durable audit facts.
  - Authority cleanup result facts add schema/persistence surface.
  - Whole-run deletion remains deferred.
- Revisit triggers:
  - Remote deletion/provider retention enforcement enters scope.
  - Whole-run deletion enters scope.
  - Audit-heavy deployments require recorded dry-run previews.
  - Cleanup result facts require paging or compaction.

## Final Approval

- Approval status: implementation complete; all five phases merged
- Approved scope: conservative cleanup, retention metadata, explicit local
  deletion, candidate-level GC, preflight warnings, cleanup event projection,
  and CLI wrappers as phased above
- Accepted risks:
  - Local-only deletion adapter.
  - Append-only cleanup facts add authority persistence work.
  - Bounded selector model defers arbitrary query language.
  - No persisted dry-run audit by default.
- Deferred items:
  - Whole-run deletion.
  - Automatic retention enforcement.
  - Remote provider deletion enforcement.
  - Cleanup-specific event sink plugins.
  - Arbitrary cleanup query language.
  - Arbitrary directory/global cache cleanup.

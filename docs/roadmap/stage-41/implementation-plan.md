# Roadmap Stage 41 Implementation Plan

Status: implementation in progress; approved nine-phase baseline
Roadmap stage: 41
Stage descriptor: Unified Run Lifecycle And Agent Execution
Workflow: .codex/workflows/roadmap-stage-implementation.md
Planning document: [planning.md](planning.md)
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: Phase 5, agent-slurm-jobs
Next phase: Phase 6, slurm-result-recovery, after Phase 5 merge and synchronization
Blockers: none; the reviewed packet is published and stage-worktree startup passed
Maintainer approval: behavior and nine-phase structure approved on 2026-09-10;
published-source refinements, startup review and whole-stage implementation
requested on 2026-09-12.

## Summary

- Goal: one configured CLI/Python run starts or reuses services, prepares,
  admits, executes through agents, observes and settles work across local,
  persistent, fleet and connected Slurm deployments.
- Agreed behavior: FR-41-01 through FR-41-15. Agents are services; stage workers
  execute attempts. Lifetime belongs to each service. Detach does not cancel.
  Slurm jobs/results survive observer loss. All old execution bypasses are removed.
- Design: DQ-41-01 through DQ-41-07. Reuse Stage 40's native client/preparation,
  existing role stores, authority, supervisor, ready-stage submission mechanics
  and result finalizer. The assigned agent is the sole Slurm external-call owner.
- Delivery: nine bounded implementation phases, one coherent behavior change
  and PR each. Local/fleet execution, Slurm recovery and consumer cutover remain
  the overall outcomes. Coexistence during development is not final compatibility.
  Remove replaced code in its owning phase; Phase 9 finishes shared removals.
- Deliberately excluded: a new scheduler framework, job database, global service
  discovery, compatibility adapters, remote provisioning, environment builders,
  offline starts, allocation acquisition, transparent requeue and HA.
- Validation/phase source: [planning behavior and validation](planning.md#examples-and-validation).
  Cards assign causal checks to their invariant owners and distinguish local
  gates from environment-dependent release qualification.

## Shared Constraints

- Dependency direction: high-level run/client composition above queue and
  diagnostics; native owners below CLI/MCP. Every accepted execution goes through
  coordinator assignment, agent backend and authority finalization. Workers never
  recursively invoke public run. Base imports remain cheap and optional extras inert.
- Stage 40 is published. The [published baseline and amendment ownership](planning.md#published-baseline-and-amendment-ownership)
  records the inspected source at `25d97f50d66f44273bf979a5488a312e7f1a15d2`,
  including subsequent publication/retry and worker-completion fixes. Reconcile
  later relevant drift before each phase; reuse unchanged owners and evidence.
  Stage 41 extends Stage 40's preparation family and replaces old execution APIs.
- P1 owns selected-authority/profile recovery and complete invocation propagation;
  P2 owns durable publication/admission/cancellation linkage; P3 owns current
  coordinator-authorized role retirement; P8 binds all tools to one deployment.
  Explicit failed-admission retry remains separate from same-ID run replay and
  retains its existing embedded-only authority capability. P4/P6 preserve verified
  native completion, exact output predecessor and report metadata. No larger
  artifact transfer or general source upload is introduced.
- Keep operation, run, admission, attempt, assignment and scheduler identities
  distinct. Same-ID retries reconcile unchanged accepted intent; changed intent
  conflicts. Restart reopens exact owners; unknown execution never authorizes a
  fresh submission. Configuration changes require a new prepared run.
- Preparation-only applies at publication; the continuation-bearing `run`
  operation applies at exact admission, after which waiting follows execution.
  Phase 2's `cancel_run_operation` owns suppression/admission races and returns
  its own native control operation. CLI/MCP delegate that behavior unchanged.
- Coordinator/application owns admission and service quiescence; agent owns
  execution/observation; authority owns current fences and commits. Agent result
  transport has no independent finalization power. Release needs the corresponding
  containment evidence, not merely a process exit or scheduler state.
- Role lifetime is persistent or run-owned and is retained across restart. Only
  configured local roles may autostart. Shared run-owned roles survive other runs,
  waiting work, results and client exit. Durable state is not removed on shutdown.
- Preserve graph/planner, artifacts, selectors, reuse, reliability, resource
  enforcement and provenance meaning. Unsupported in-process objects are rejected;
  no silent control dropping, recompilation or scientific substitution.
- Hard cutover has no public alias/migration requirement. Reject incompatible
  roots before mutation; old-version work must settle under that version before
  service replacement. Never reset roots or delete old outputs to implement this.
- Execution paths and coordination are recorded in Execution Context below.
  Every card keeps its phase branch/PR in the same persistent stage worktree.
  Start the successor only after remote predecessor merge, published metadata
  and synchronization. Preserve unrelated work and the original dirty checkout.

## Execution Context

- Execution worktree root: `/nas/home/can134/work/loom-worktrees`.
- Clean control checkout: `control-stage-40` under that root, on develop.
  The `control` checkout remains occupied by unrelated settings work; preserve it.
  Verify this selected checkout remains clean and fast-forwardable at startup.
- Persistent stage worktree: `stage-41` under that root; bootstrap before
  startup review or writes and retain through final synchronized closeout.
- Coordination branch: `agent/stage-41` for metadata and closeout.
- Shared Git gate: `.codex/prompts/phase-loop-management.md`.
- Execution-mechanics amendment: refined workflow adopted on 2026-09-10;
  phase scope/order, approvals, fixed contracts and validation remain unchanged.

## Phase Boundaries And Ordering

The maintainer approved nine independently acceptable phases. Publication,
durable admission, service
lifetime, process execution, scheduler ownership, result transport and separate
consumers have distinct implementation/review boundaries. Each card delivers a
working outcome with code, tests, documentation and local removal.

Implement in order 1 through 9, one phase branch/PR at a time in the stage
worktree on published develop; Phase 1 follows published Stage 40. This is
integration order, not a requirement to invent runtime dependencies between independent consumers.
Phases 2/3/5/6 keep these indivisible contracts together respectively:
acceptance/continuation/cancellation; startup/handoff/quiescence;
submission/uncertainty/cancellation/recovery; and result ingestion/finalizer
acknowledgement/retirement. Private implementation slices stay inside those PRs.

Phase 2 proves runs on existing services; Phase 3 adds configured autostart.
Phase 5 proves connected job control with current typed result relay; Phase 6
completes durable result recovery after compute exit during coordinator downtime.
Neither interim limitation is a final supported compatibility mode. Stage 41
completes only after all phases and required qualification/evidence disposition.

## Phase Index

Each card includes an **Implementation Walkthrough And Examples** section with
the core changes, interface sketches, ownership handoffs and failure/recovery
examples in plain language. The fixed contracts and validation owners below that
section remain authoritative. Code is planned target usage or explicitly marked
pseudocode; illustrative private helpers and configuration layouts do not add
public APIs or schema requirements. The [lifecycle overview](../../briefs/unified-execution-lifecycle.md)
links directly to all nine walkthroughs.

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | preparation-publication | merged | [Phase 1](phases/preparation-publication.md) | agent/stage-41-p1-preparation-publication | [308](https://github.com/samcantrill/loom/pull/308) | Managed preparation publisher and selected authority | Prepare exact invocation intent and publish a truthful, replayable target through the selected authority. |
| 2 | durable-run-operation | merged | [Phase 2](phases/durable-run-operation.md) | agent/stage-41-p2-durable-run-operation | [309](https://github.com/samcantrill/loom/pull/309) | Native run operation, coordinator continuation and cancellation | An accepted run reaches its exact admission after client loss and supports race-safe cancellation and observation against existing services. |
| 3 | service-startup-lifetime | merged | [Phase 3](phases/service-startup-lifetime.md) | agent/stage-41-p3-service-startup-lifetime | [310](https://github.com/samcantrill/loom/pull/310) | Deployment initializer, per-service lifetime and public run composition | The ordinary run command connects or safely starts configured services, then cleans only the roles whose lifetime permits it. |
| 4 | agent-worker-execution | merged | [Phase 4](phases/agent-worker-execution.md) | agent/stage-41-p4-agent-worker-execution | [311](https://github.com/samcantrill/loom/pull/311) | Agent resident execution, process supervisor and native/container executors | Native and configured container attempts use the same agent-owned worker and result boundary with correct resource and containment evidence. |
| 5 | agent-slurm-jobs | in_progress | [Phase 5](phases/agent-slurm-jobs.md) | agent/stage-41-p5-agent-slurm-jobs | pending | Agent Slurm operation journal, authorized placement and backend observation | One assigned agent submits, observes, cancels and recovers the exact Slurm job without duplicate submission or capacity accounting. |
| 6 | slurm-result-recovery | pending | [Phase 6](phases/slurm-result-recovery.md) | agent/stage-41-p6-slurm-result-recovery | pending | Bootstrap result publisher, submit-agent transport and existing coordinator finalizer | A job can finish and its compute process exit during coordinator downtime; the recovered submit agent delivers the same result for one authority commit. |
| 7 | unified-sweeps | pending | [Phase 7](phases/unified-sweeps.md) | agent/stage-41-p7-unified-sweeps | pending | Sweep expansion/dispatch state and native admission references | Sweep trials use the unified run lifecycle with unchanged experiment meaning and stable retry identities. |
| 8 | unified-mcp | pending | [Phase 8](phases/unified-mcp.md) | agent/stage-41-p8-unified-mcp | pending | Existing optional stdio MCP adapter and four operational skills | MCP runs, observes and cancels through the same native service/run owners, with updated skills and no private lifecycle. |
| 9 | execution-cutover | pending | [Phase 9](phases/execution-cutover.md) | agent/stage-41-p9-execution-cutover | pending | Remaining shared legacy owners, public exports/configuration and stage integration audit | All production execution entrypoints use the unified lifecycle and the remaining shared obsolete engines are removed. |

## Validation Ownership

| Obligation | Primary phase owner / distinct part |
| --- | --- |
| VAL-41-01 | P1 state/reuse; P2 persistent run; P3 cold run; P9 integration reuses fresh evidence |
| VAL-41-02 | P3 creation/open/concurrent startup |
| VAL-41-03 | P3 role/fleet lifetime; P4 authorized execution/resource binding |
| VAL-41-04 | P3 shared lifetime and acceptance/quiescence races |
| VAL-41-05 | P2 continuation/cancellation; P3 cleanup; P4 process containment |
| VAL-41-06 | P4 native/container workers and resource evidence |
| VAL-41-07 | P1 immutable preparation and selected-authority publication |
| VAL-41-08/09 | P5 Slurm job ownership, quota, grants, cancellation and restart |
| VAL-41-10/11 | P6 durable results and real-site qualification |
| VAL-41-12 | P7 sweeps; P8 MCP/skills; P9 final public/dynamic removal |

Each invariant has one implementation owner. These are distinct causal parts of
shared validation examples, not repeated full matrices. Every phase verifies its
changed import/public boundary. Reuse successful evidence until relevant changes
invalidate it; local fixtures never substitute for live qualification.

## Quality Gate

This is the grandfathered authoritative readiness receipt. Reuse the recorded
approval/review below under the current workflow; no new product-plan review is
claimed by the skill/title metadata update. Phase scope/order, fixed contracts,
and all approved validation commands remain binding.

- Functionality/design: agreed contracts retained; original independent design
  pass resolved service ownership, sole submitter and one finalizer.
- Independent plan review: completed before this decomposition; its run-operation
  terminal/cancel blocker was corrected. Phase 2 retains that complete correction;
  Phase 8 delegates it. That correction remains binding; the requested source
  amendment review is recorded separately below.
- Maintainer approval: behavior and the nine-phase split approved on 2026-09-10.
- Manager decomposition review: contract preservation, phase handoffs, invariant/
  validation/removal ownership and one-to-one manifest/card mapping checked.
- Original documentation checks: links/anchors, stale-reference audit, snippet
  syntax and diff checks passed. Current amendment checks are recorded below;
  neither receipt establishes runtime implementation or physical qualification.
- Original planning quality: pass; the approved behavior and nine-phase shape
  remain the baseline. The current published-source amendment is reviewed below.
- Execution readiness: amended packet passed independent review and is published;
  stage-worktree startup passed as recorded in Phase 1's Workflow State.
  Phase execution state and runtime evidence are owned by the phase index/cards.

### Published-source startup readiness review

- Status: pass on 2026-09-12; no required corrections or qualified blockers.
- Source assumptions: published develop `25d97f50d66f44273bf979a5488a312e7f1a15d2`;
  [baseline contract inventory](planning.md#published-baseline-and-amendment-ownership).
- Reviewed packet revision: `d2e36893a3e206933ad255b0306104d41045b5bc`;
  tree: `a379008512799b7042efb19176af2fbdb4bae409`.
  Paths: `docs/roadmap.md` Stage 41 entry,
  `docs/briefs/unified-execution-lifecycle.md`,
  `docs/roadmap/stage-41/{planning,implementation-plan}.md` and all nine cards
  indexed in Phase Index under `docs/roadmap/stage-41/phases/`.
- Scope: the maintainer-requested predecessor reconciliation; preserve unaffected
  original reviews, accepted outcomes, phase order and all required phase gates.
- Independent result: the amended packet accurately preserves published
  preparation/publication, explicit retry, verified completion/output replay,
  container/report, service-lifetime and MCP contracts. Phase ownership, merge
  boundaries, validation obligations and incremental removals are consistent.
  No findings required correction; unaffected original reviews were reused.
- Documentation validation: 13 documentation-only paths; 52 local links/anchors,
  nine Python snippets, 35 shell examples and 42 test-path references checked;
  nine pending phase identities/order/approval/full gates and FR/FQ/DQ tables
  preserved; `git diff --check` passed. No runtime tests or live qualification
  are claimed by this amendment review.
- Post-review changes: readiness/status and receipt updates only. No accepted
  contract, example, validation obligation or phase boundary changed.
- Landing/startup handoff: [plan PR 307](https://github.com/samcantrill/loom/pull/307).
  The reviewed packet is published; the exact merged base and completed startup
  verification are recorded in [Phase 1's Workflow State](phases/preparation-publication.md#workflow-state).
  The stage-worktree helper verified isolation before startup review and writes.
  No relevant source drift invalidated the independent review. Startup receipts
  join the Phase 1 PR. The subsequent whole-stage implementation request is
  recorded above; this readiness pass itself claimed no runtime implementation.

- Accepted risks: breaking APIs; original owner loss/accounting delay can leave
  work unresolved; live fleet/container/HPC/MCP qualification remains explicit.
- Revisit only for a changed predecessor contract, demonstrated supported-path
  blocker or explicitly requested deferred capability. Private choices remain open.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | [308](https://github.com/samcantrill/loom/pull/308), merge `c133d17` | Both required gates, manager acceptance and independent review passed; exact evidence in Phase 1 card | Physical qualification remains with later owners; no Phase 1 blocker | Replaced publication helper and consumers removed; metadata published/synchronized; exact remote/local phase branches retired |
| 2 | [309](https://github.com/samcantrill/loom/pull/309), merge `5a624d1` | Both required gates, manager acceptance and independent review passed; exact evidence in Phase 2 card | No implementation blocker; physical qualification remains with later owners | Preparation-only and explicit retry retained; evidence archived; metadata published/synchronized; exact remote/local phase branches retired |
| 3 | [310](https://github.com/samcantrill/loom/pull/310), merge `a4bedaa` | Both required gates, manager acceptance and independent review passed; exact evidence in Phase 3 card | No implementation blocker; physical qualification remains with later owners | Ordinary CLI cutover audited; retained consumers mapped to P4/P6/P9; evidence archived; no phase-owned processes remain; metadata published/synchronized; exact remote/local phase branches retired |
| 4 | [311](https://github.com/samcantrill/loom/pull/311), merge `243c86a` | Both fresh required gates, manager acceptance, same-reviewer confirmation and gated delivery passed; exact evidence in Phase 4 card | No implementation blocker; physical qualification unavailable and unclaimed | Examples/removals and evidence archive complete; no phase-owned processes remain; completion metadata published/synchronized; exact remote/local phase branches retired |
| 5 | pending | Prepared on published `86ed646`; implementation in progress | Required connected fake-scheduler evidence pending; completed-job durability/site qualification stays with Phase 6 | Pending sole agent submission owner and coordinator-path removal audit |
| 6 | pending | not started | Live site/container and durable shared-storage qualification pending | not started |
| 7 | pending | not started | Sweep semantic/replay evidence and shared-owner disposition pending | not started |
| 8 | pending | not started | Optional MCP/real-session qualification pending | not started |
| 9 | pending | not started | Final dynamic removal and qualified deployment evidence audit pending | not started |

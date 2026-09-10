# Roadmap Stage 41 Implementation Plan

Status: approved; nine-phase implementation baseline
Roadmap stage: 41
Stage descriptor: Unified Run Lifecycle And Agent Execution
Workflow: .codex/workflows/roadmap-stage-implementation.md
Planning document: [planning.md](planning.md)
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: none; implementation not started
Blockers: published Stage 40 required before execution
Maintainer approval: agreed behavior and nine-phase structure approved on 2026-09-10.

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
- Stage 40 is approved but unimplemented at this plan's evidence revision.
  Reconcile its published client, preparation, root version and MCP source before
  Phase 1. Its preserve/limited-preparation decisions end at its delivery boundary;
  Stage 41 explicitly extends or replaces them. Do not rewrite its phase gates.
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
- Clean control checkout: `control` under that root; verify or create a clean
  linked checkout on develop without repurposing unrelated work.
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
| 1 | preparation-publication | pending | [Phase 1](phases/preparation-publication.md) | agent/stage-41-p1-preparation-publication | pending | Managed preparation publisher and selected authority | Prepare exact invocation intent and publish a truthful, replayable target through the selected authority. |
| 2 | durable-run-operation | pending | [Phase 2](phases/durable-run-operation.md) | agent/stage-41-p2-durable-run-operation | pending | Native run operation, coordinator continuation and cancellation | An accepted run reaches its exact admission after client loss and supports race-safe cancellation and observation against existing services. |
| 3 | service-startup-lifetime | pending | [Phase 3](phases/service-startup-lifetime.md) | agent/stage-41-p3-service-startup-lifetime | pending | Deployment initializer, per-service lifetime and public run composition | The ordinary run command connects or safely starts configured services, then cleans only the roles whose lifetime permits it. |
| 4 | agent-worker-execution | pending | [Phase 4](phases/agent-worker-execution.md) | agent/stage-41-p4-agent-worker-execution | pending | Agent resident execution, process supervisor and native/container executors | Native and configured container attempts use the same agent-owned worker and result boundary with correct resource and containment evidence. |
| 5 | agent-slurm-jobs | pending | [Phase 5](phases/agent-slurm-jobs.md) | agent/stage-41-p5-agent-slurm-jobs | pending | Agent Slurm operation journal, authorized placement and backend observation | One assigned agent submits, observes, cancels and recovers the exact Slurm job without duplicate submission or capacity accounting. |
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
  Phase 8 delegates it. No additional review pass or budget reset is claimed.
- Maintainer approval: behavior and the nine-phase split approved on 2026-09-10.
- Manager decomposition review: contract preservation, phase handoffs, invariant/
  validation/removal ownership and one-to-one manifest/card mapping checked.
- Documentation checks: links/anchors, stale-reference audit and diff checks pass.
  All nine walkthroughs preserve the approved card text outside their explanatory
  additions; Python snippets pass syntax checks without execution. These checks
  are documentation evidence, not runtime implementation or another review pass.
- Planning quality: pass; no unresolved planning blocker.
- Execution readiness: approved baseline; Phase 1 awaits published Stage 40.
  All phase execution statuses remain pending. No runtime work started.
- Accepted risks: breaking APIs; original owner loss/accounting delay can leave
  work unresolved; live fleet/container/HPC/MCP qualification remains explicit.
- Revisit only for a changed predecessor contract, demonstrated supported-path
  blocker or explicitly requested deferred capability. Private choices remain open.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | not started | Published Stage 40 and authority integration evidence pending | not started |
| 2 | pending | not started | Persistent-service execution/cancellation evidence pending | not started |
| 3 | pending | not started | Live fleet qualification and mixed-role process evidence pending | not started |
| 4 | pending | not started | Real container/runtime qualification pending | not started |
| 5 | pending | not started | Completed-job result durability and site qualification delivered by Phase 6 | not started |
| 6 | pending | not started | Live site/container and durable shared-storage qualification pending | not started |
| 7 | pending | not started | Sweep semantic/replay evidence and shared-owner disposition pending | not started |
| 8 | pending | not started | Optional MCP/real-session qualification pending | not started |
| 9 | pending | not started | Final dynamic removal and qualified deployment evidence audit pending | not started |

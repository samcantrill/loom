# Phase 3 Execution Plan: Container Timeout Lifecycle

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 38, Phase 3
- Manifest: `docs/roadmap/stage-38/implementation-plan.md`
- Branch: `agent/stage-38-p3-container-timeout-lifecycle`
- Worktree/base: create from current develop after Phase 2 merge
- PR target: develop
- PR title: `feat(execution): supervise container timeout cleanup`
- Dependencies: prior merges; explicit expanded lifecycle design review
- Workflow path: expanded, cross-process ownership and cleanup proof
- Blockers: not ready for execution; lifecycle mechanism review required

## Objective And Context

FR-3 requires a truthful configured deadline and supported-process cleanup, not
just a timed-out launcher. A fresh real-process baseline probe proves the
existing Apptainer command runner can return while its ordinary child survives.
The local patch's timeout wiring is useful evidence but is not a supervision
implementation. FR-4 prohibits weakening managed resource release or existing
ordinary/no-timeout semantics.

## Current Source And Harness

Read direct Apptainer command/executor/result owners, ordinary subprocess
command construction, `cli/stage.py`, and execution `stage_worker.py` along with
`StageContext`. Ordinary worker reconstruction explicitly says STAGE; resident
agent and SLURM entries explicitly say OUTER_BOUNDARY. Stage-owned downstream
work may establish its own child groups. Merely adding a launcher process group
does not cover that supported behavior.

Read agent supervisor `contain` as a reference for positive observation/order,
not as a private helper to import. Also trace historical queue `local.py`
inspect/cancel: a new nested session can escape an existing enclosing group.
Direct, legacy whole-run managed, resident agent, and scheduler boundaries must
not be conflated. Existing Apptainer fake-runner tests need real-process
companions; reuse `tests/container_acceptance` for actual runtime evidence.

Independent audit confirmed A-10: the legacy adapter releases after its root
exits while a child can survive in the inherited group. The existing Stage 23
contract requires descendant cleanup. A bounded legacy process-group settlement
observation plus root-first-exit regression is a concrete necessary correction,
not optional hardening. Its integration/phase placement must be resolved in the
expanded lifecycle design; do not copy the resident daemon or silently redesign
the full queue to address it.

## Scope

Approved outcome: configured deadlines, bounded graceful termination and
escalation, observation and owned reaping, primary timeout plus cleanup context,
and no success admission or physical release based on an exited launcher alone.
Implementation shape is intentionally not approved until the design gate below.

Exclude a general supervisor framework, daemon imports into low-level commands,
arbitrary hostile/daemonizing-process containment, new scheduler or recovery
APIs, rphys changes, and silent expansion into every executor. Any new public
surface or materially broader process-ownership change needs a separate bounded
design decision rather than being hidden as private wiring.

## Fixed Contracts And Private Discretion

- Timeout is failure, never cancellation or successful output. A worker result
  written before the deadline cannot override timeout or cleanup uncertainty.
- Apply the deadline at the selected execution boundary; cleanup has a bounded
  additional grace/escalation budget and must be reported separately.
- Signal only processes/boundaries owned by this invocation. Observe exit and
  reap owned processes before claiming termination. No PID-only adoption.
- Stage and enclosing-owner obligations must agree with actual containment.
  Runtime namespace/group behavior requires evidence; a label or `killpg`
  call alone is not proof that supported descendants are gone.
- Preserve the primary explanation and secondary cleanup failures without
  leaking environment values. Failed/unknown containment cannot admit outputs.
- Managed capacity remains held until its actual owner has positive settlement
  evidence, not just a direct launcher result. Existing agent/scheduler owners
  remain authoritative on their routes.
- Keep ordinary success/failure and absent-timeout behavior compatible. Do not
  globally change worker owner facts to make one container test pass.
- Private helper/fixture names and intermediate data are open only after the
  public, durable, cross-owner, and lifecycle mechanism decisions are locked.

## Proportionality

First look for an existing owner with the required guarantees. Current immediate
worker-kill behavior is not such a guarantee. Reuse ideas without introducing
reverse dependency direction. A narrow runtime boundary is preferable to a new
framework only if it actually covers the accepted supported lifecycle.

## Invariant Ownership

| Invariant | Owner to establish in design | Reachable consequence | Evidence required |
| --- | --- | --- | --- |
| Deadline and cleanup budgets | Direct execution supervisor | Hanging supported work or unbounded cleanup | Real timed process fixtures |
| Correct child ownership | Launcher plus worker reconstruction | Stage detaches from a group the outer layer assumes covers it | Public owner propagation and real descendants |
| Outcome admission | Executor result gate | Late/stale success accepted despite timeout | Result-before-timeout fixture |
| Capacity settlement | Existing managed owner | Subsequent work overlaps surviving children | Relevant production release path and regression |

## Implementation Slices

1. Complete the expanded design investigation and record concrete mechanism,
   supported runtime/platforms, owner propagation, budgets, outcome evidence,
   resource-release composition, and exact affected owners in this card.
2. Obtain independent design review. If a materially broader redesign is
   required, stop and present it to the maintainer. Do not enable timeouts.
3. Only after that gate, implement the smallest accepted supervision and worker
   propagation change with truthful capability/failure reporting.
4. Add real-process fixtures and runtime acceptance, update docs, then validate
   and independently review the resulting implementation.

## Test And Validation Plan

Required real-process cases: normal timeout; cooperating child; root exits
before child; child ignores TERM; interruption; result written immediately
before deadline; cleanup uncertainty/failure; success without timeout. Fixtures
must own every process/group they signal and guarantee their own cleanup.

Required production evidence: selected container runtime with a suitable image,
actual child topology and cleanup behavior, correct worker containment-owner
fact, no success on timeout, and retained managed capacity until the owner proves
settlement. Mocks can cover rare cleanup errors but cannot prove child liveness.

Final commands:

    make validate-pr
    make test-summary

Exact targeted commands and affected integration cases must be locked during
expanded phase preparation. Missing runtime prerequisites remain visible gaps.

## Risks, Review, And Stops

Stop before product implementation if the selected mechanism cannot contain
supported children, if it escapes outer managed cancellation, if required
owner/public changes exceed the approved bounded phase, or if no maintainable
bounded cleanup proof exists. Present the smallest concrete proposal and its
tradeoffs; do not substitute launcher-only timeout support. Prior phases may
remain merged while this decision is resolved; the overall objective stays open.

## Executor Handoff

No executor is authorized from this initial card. A manager/expanded planner
must close slices 1-2 and update this card's fixed design and startup receipt.
The later executor must preserve all other work, implement only locked owners,
and return implementation/validation evidence without PR/merge or delegation.

## Workflow State

- Manager preparation: initial ownership evidence recorded
- Expanded planning/design review: required, pending
- Implementation: not started
- Pre-submit gate, independent implementation review, PR and merge: pending
- Blocker corrections: 0/3

## Completion Record

| Item | Result |
| --- | --- |
| Reviewed mechanism and approved boundaries | pending |
| Implementation and changed paths | not started |
| Real process/runtime tests and validated revision | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |

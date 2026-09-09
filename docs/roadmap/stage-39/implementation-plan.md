# Roadmap Stage 39 Implementation Plan

Status: blocked; approved Phase 1 has a local implementation checkpoint
Roadmap stage: 39
Planning document: docs/roadmap/stage-39/planning.md
Artifact layout: manifest-and-phase-plans-v1
Target branch: develop
Current phase: 1 — pipeline-resource-policy
Blockers: no-claim offer freshness, retained-worker comparison, and managed
control/failure transport and no-start completion; see Phase 1's remaining blockers

## Summary

- Goal: declare job demand once, choose independently what Loom accounts for
  and which additional controls it requests, and report the actual control owner.
- Approved behavior: FR-39-01 through FR-39-08 in planning.md; new invocations
  default to `account_for: all`, `enforce: []`. Timeout retains its separate
  reliability owner. The maintainer subsequently approved the complete two-phase
  plan and its documented compatibility cuts. Protected physical execution is
  still not authorized.
- Design: the existing runtime policy composes selectors; a single post-demand
  projection resolves concrete identifiers. EDR-39-01 fixes the managed handoff;
  EDR-39-02 uses the existing terminal lifecycle for incompatible queued work.
- Minimum useful change: Phase 1 delivers the complete configured pipeline path,
  including admission, local/remote workers and container/SLURM consumers. Phase 2
  extends the older opaque whole-run queue through its own public boundary.
- Phase shape: pipeline defaults, placement, worker replay and command controls
  must change atomically; a policy-only foundation would leave implicit controls
  active. The whole-run API has a distinct demand namespace and durable owner,
  so its complete migration is a second vertical phase, not prerequisite scaffolding.
- Excluded complexity: new schedulers, provider/mechanism registries, duplicate
  amounts, policy timers, lifecycle stores, live migrations and measured isolation.
- Validation source: planning.md's supported boundaries, invariant evidence and
  accepted design corrections; exact owners and causal comparisons are in each card.
- Out of scope: rphys scientific code, Stage 85 deployment/readiness ownership,
  host administration, physical/GPU runs and actual SLURM submission.

## Shared Constraints

- Keep imports cheap and Loom domain-neutral. Preserve upstream diagnostics and
  lifecycle work at source baseline `719e016c6fe5e1ec3e70994bca6b3716964fc200`;
  reconcile subsequent published changes before each phase starts.
- `loom.pipeline.runtime.ResourcePolicy` is the single public two-axis selector.
  `all`, explicit unique identifier lists and empty lists retain distinct meanings;
  omission inherits per axis, supplied lists replace, and authored null is invalid.
  Defaults resolve only for new invocations. Pipeline identifiers are semantic
  kinds; whole-run identifiers are existing logical demand keys. No implicit mapping.
- Full normalized demand remains the amount authority. Existing semantic owners
  still validate it. The post-demand projection owns the plain-data
  `resource_selection: {account_for: [...], enforce: [...]}`; saved consumers
  compare/use that projection, never expand `all` again with fresh defaults.
- Additional controls use existing mechanisms only. Unsupported selected present
  demand fails with preserved context and correction guidance. Absent/zero demand
  creates no claim or limit. Empty enforcement preserves authored/inherited
  environment, reservation ownership, cancellation, fences, cleanup and timeout.
- Existing metadata carries `resource_policy`, `resource_selection` and bounded
  `resource_controls`. Each control has exactly resource, owner, mechanism and
  disposition, sorted by resource/owner/mechanism with null for no mechanism.
  Dispositions are not_requested, not_applicable, requested, applied, delegated,
  unavailable and failed. Preparation reports requested; applied means the actual
  job received the control, not measured isolation. Known setup failure is failed;
  uncertain inner launch cannot be called applied. SLURM delegation and no extra
  inner control can coexist. Ordinary application failure retains launch evidence.
  Missing old metadata means unreported. No new store or raw binding/lease dump.
- Final approval covers the phase-specific executable cuts and narrow legacy
  inspection rule. Never upgrade old executable intent through new defaults,
  edit version fields, overwrite retained identities or automatically adopt live work.
- The planning tree and original dirty Loom checkout are not phase execution
  trees. Worktree root: `/nas/home/can134/work/loom-worktrees`; clean control:
  `stage-85-control` under that root. Preserve the original `/nas/home/can134/work/loom`.
- Follow the canonical Loom phase workflow: one executor and one PR per phase,
  current develop base, required expanded independent implementation review,
  `make validate-pr` and `make test-summary`, verified remote merge and exact cleanup.
  Hosted CI is disabled. Phase 2 starts after Phase 1 remotely merges.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | pipeline-resource-policy | blocked | [Phase 1](phases/pipeline-resource-policy.md) | agent/stage-39-p1-pipeline-resource-policy | pending | Runtime composition, placement/admission, stage handoffs, executors, diagnostics and consumers | Configured pipeline accounting and additional controls are independent end to end |
| 2 | queued-resource-policy | pending | [Phase 2](phases/queued-resource-policy.md) | agent/stage-39-p2-queued-resource-policy | pending | Whole-run contract, selection/controller, assignment bindings/providers and consumers | Opaque queued commands use the same policy semantics without losing replay or lifecycle safety |

## Quality Gate

- Planning gate: functionality and default approved; expanded design review
  passed after one bounded correction and targeted confirmation of EDR-39-01/02.
- Manager review: two coherent vertical phases; current producer/consumer and
  test seams identified; returned SLURM correction verified against the existing
  delivery decoder/workspace/worker join. Documentation diff, local links and
  explicit targeted-test paths checked; no runtime validation claimed.
- Independent plan review: passed after one qualified cross-machine replay finding.
- Plan correction: complete; Phase 1 now cuts the independently versioned
  `SlurmStageDelivery` and requires old-writer/current round-trip coverage.
- Original implementation approval: maintainer approved both phases and their
  concrete migration rules. Phase 1 starts on published develop `214f242c`;
  its preparation API addition preserves the same runtime owner and is included
  in the phase's regression obligations. That upstream addition did not require
  contract reopening; the subsequently discovered boundaries below do.
- Current gate: blocked at local checkpoint `6474206`. Three correction passes
  are conservatively consumed (including the separately returned refiner repair).
  A targeted amendment must resolve no-claim offer consumption and the closed
  remote report/launch and no-start boundaries, retain the outstanding replay
  comparison obligations, and pass independent startup review before more fixes.
  No PR, remote merge or Phase 2 start is authorized by a partial checkpoint.
- Accepted risks: no additional enforcement can expose more host resources than
  reservation bookkeeping suggests; excluded accounting permits oversubscription.
  No claim of isolation. Hard cuts require pinned old environments for old live work.
- Revisit triggers: overlapping upstream changes to these public/durable owners,
  inability to preserve a supported route or old inspection digest, or a required
  mechanism without current authoritative evidence. Ask about material contract
  changes; resolve private implementation mechanics locally.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | Local checkpoint `6474206`; targeted 214 unit/contract and 15 fake-SLURM integration tests pass; managed comparisons 5 pass/1 fails; Ruff/Pyright pass; full gates and review pending | No-claim sequential pipeline and remote replay/failure/control boundaries remain incomplete; no physical proof | Preserve phase worktree and ignored checkpoint logs |
| 2 | pending | not started | No live upgrade or automatic old-provider attribution | not applicable |

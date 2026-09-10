# Phase 9 Execution Plan: Complete Execution Cutover

## Metadata

- Status: pending
- Roadmap stage and phase: 41 / 9
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p9-execution-cutover
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: published develop after Phase 8 merges; record exact SHA at execution preparation
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 9: Complete Execution Cutover
- Dependencies: Phase 8 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: source predecessor pending; no unresolved planning blocker

## Objective And Context

All production execution entrypoints use the unified lifecycle and the remaining shared obsolete engines are removed.

Earlier phases remove the code they replace. This phase handles shared owners that could not be deleted until their last consumer moved, then audits complete stage behavior and current deployment claims. It is not a deferred bulk rewrite or docs-only phase.

Requirements: FR-41-01/13/14; final completion check for FR-41-01 through FR-41-15. Design: DQ-41-06.
Validation ownership: VAL-41-12 (final removal), VAL-41-01 (integrated journey); reuse VAL-41-02 through VAL-41-11 evidence unless changed.

## Current Source And Harness

- Predecessor phase completion/removal records and delivered public/native APIs.
- `src/loom/pipeline/execution/runner.py`, continuation/slurm_controller/offline_adapter, `queue/{client,service,controller,local,slurm}.py` and `cli/{prepared_run,stage_job}.py`: inspect actual remaining consumers.
- Root/pipeline/queue exports, configured _target_ paths, generated worker scripts, CLI options, recipes and examples; preserve restricted worker/bootstrap entrypoints.
- README, docs/GLOSSARY.md, docs/structure.md and current feature docs; historical evidence is not current support.
- Package/public API, CLI runtime/Slurm, sweep, MCP and unified-run tests; predecessors own numerical/resource/backend acceptance.

## Scope

Finish remaining shared removals and dynamic-reference audit, reconcile current terminology/deployment docs and prove stage integration. Do not postpone earlier consumer conversions here or introduce compatibility/data migration.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### Finish removal after the last consumer moves

Phases 1–8 remove their replaced code as they deliver each capability. This
phase finishes shared orchestration that could not be removed while an earlier
consumer still used it, then checks that every supported public execution
entrypoint reaches the same coordinator/agent lifecycle.

The intended migration looks like this illustrative diff:

```diff
- PipelineRunner(...).run(old_request)
+ loom.run(request, deployment="deployments/project.yaml")
```

`request` is the new native `RunRequest` described in Phase 2, not the old
runner's input passed through unchanged. The old public name is removed; it
does not become a compatibility alias. Pure configuration validation, graph
planning and read-only artifact inspection can remain useful without starting
execution. Restricted agent worker and Slurm bootstrap entrypoints also remain
because they execute coordinator-authorized attempts within the new lifecycle.

### Audit real producers before deleting shared code

For each remaining direct/offline/whole-run queue or Slurm continuation owner,
inspect its definition, current callers, tests and dynamic producers. Imports
alone are insufficient: configured `_target_` values, CLI flags, recipes and
generated Python or shell commands can still invoke a removed path. The
disposition table below is the deletion checklist, with each retained pure
planner, artifact or execution-only primitive tied to an actual consumer.

For example, a former whole-run runner may contain a graph helper still needed
by preparation. Preserve or extract that helper before deleting orchestration,
and move the meaningful assertions to its surviving consumer. A module name in
the removal table does not authorize deleting all of its behavior. Historical
roadmap evidence may retain old terminology, while current exports, commands
and user instructions must describe only supported execution.

### Prove the same lifecycle across entrypoints and deployments

The integrated synthetic journey runs through Python, CLI, sweep and MCP entry
surfaces and follows the same native acceptance, assignment, agent execution,
authority finalization and query/cancellation contracts. Reuse predecessor
backend and failure evidence unless this final removal changes a relevant
contract. VAL-41-12 owns the final removal audit; VAL-41-01 owns the integrated
journey. Neither an empty import search nor one working example proves that all
production bypasses have been removed.

Current documentation explains cold local startup, persistent attachment,
fleets, mixed role lifetimes and connected Slurm with the same role vocabulary.
Examples include shared run-owned services, detach/reconnect, explicit
cancellation, same-root service restart, missing scheduler accounting and a
Slurm job finishing during a coordinator outage. The
[lifecycle overview](../../../briefs/unified-execution-lifecycle.md) introduces
that model; final operator instructions must match delivered commands and
qualified environments. Site-specific account/partition/QoS, installed code,
resource mapping, grant reachability and result storage remain deployment
configuration. Allocation-native execution remains separately qualified or
deferred; a common command does not establish support for nested submission or
offline starts.

### Make the incompatible switch operationally clear

Before replacing an old deployment, stop new admission and settle its work
under that version. Preserve old records and outputs for inspection. Opening an
incompatible root must fail before mutation; this phase adds no root reset,
artifact deletion or live-work migration. Stage completion requires the
delivered unified entrypoints, owner-level evidence and explicit qualification
of live deployment claims, alongside the removal itself.

## Fixed Contracts And Private Discretion

### Removal contract

| Current surface | Required disposition |
| --- | --- |
| Public PipelineRunner/run_pipeline and direct ordinary run | Delete independent orchestration and exports after preserving needed pure graph/planner/execution-only primitives |
| Offline execution adapter/mode | Delete execution behavior; retain only independently needed read-only evidence primitives |
| Whole-run queue service/client/controller and local/Slurm adapters | Convert actual consumers to native operations and delete the obsolete orchestration surface |
| Whole-run Slurm/afterok/prepared-run/stage-job continuations | Remove service-less entrypoints and generated scripts; retain the restricted agent worker/Slurm bootstrap entrypoint |
| Former coordinator Slurm submission loop | Delete after agent ownership is live; keep one shared command/marker primitive where actually consumed |
| Sweep direct/queue selector and record plumbing | Replace with one admission/reference path; preserve expansion semantics |
| Old exports, dotted targets, configuration/recipe keys, CLI aliases and examples | Remove/rewrite to the delivered public contract; no fallback or compatibility shim |

Before deletion inspect definition, current static callers, exact imports,
configured `_target_` paths, generated shell/python entrypoints and tests. Search
absence alone is not proof when a dynamic producer exists. Record each candidate's
final disposition in this card's completion record, including the current consumer
for any retained primitive. Do not delete an entire module solely because its
filename appears here; extract/reuse the minimal actual dependency first.

No old public entrypoint may continue executing by calling a hidden second
engine. Removed names/flags fail explicitly; main execution docs use the new
contract. Historical roadmap/evidence records need not be rewritten, but must not
be presented as current supported workflows. No numerical/project behavior is
replaced merely to make a removal audit empty.

### Documentation and operator behavior

Document coordinator service, agent service, stage worker, backend, supervisor,
authority and client separately. Show one lifecycle and a deployment comparison
covering fresh local, persistent local, fleet, mixed service lifetimes and
connected Slurm: which roles start, what is borrowed, where stages run, what
survives client/service exit and how restart/cleanup behaves. Site profiles retain
account/partition/QoS, resource mapping, trusted environment, grant reachability
and shared result storage; interface consistency does not erase those differences.

Include concrete cold run, attach/detach/reconnect, explicit cancel, two shared
runs, service restart, Slurm missing-accounting and finish-during-outage examples.
Explain the ordinary command's current configured deployment requirement and
preparation source limits. State allocation-native operation as separately
qualified/deferred, without suggesting nested sbatch or offline starts work.

Cutover instructions stop new admission and settle all old-version work under
that version before replacement. New incompatible roots/records are rejected
before mutation. Retain existing artifacts and old records for read-only evidence;
this phase does not authorize deleting/resetting state or migrating live work.

### Delivery boundary

Stage 41 completes only when every production execution path satisfies the unified contract and required local gates pass, with live claims explicitly qualified. No phase is marked complete merely because old APIs remain unused by one example.

### Cross-phase handoff

Final completion records link predecessor evidence and each remaining primitive to an actual consumer. Operators settle old-version work before switching incompatible roots; no live migration, artifact deletion or root reset is authorized.

### Removal owned here

The disposition table is the final audit scope, not work deferred wholesale from earlier phases. Confirm completed removals, finish shared whole-run/queue/offline/afterok owners after their last caller moves, and delete leftover exports, aliases, dynamic targets and orphan dependencies. Keep current restricted worker/bootstrap entrypoints.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Mostly deletion and integration verification. Reuse predecessor tests/qualification while fresh. No new registry, alias layer, migration utility or entire duplicate topology/failure matrix.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| No production bypass remains | Public API/config/CLI and remaining shared owners | Old import, dotted target, flag or generated script | Independent lifecycle survives cutover | VAL-41-12 exact removal disposition and public checks |
| Scientific behavior retained | Existing planner/artifact/resource owners | Helper extraction or test removal during deletion | Lost selectors/reliability/resources/provenance | Retain meaningful assertions against new consumers |
| Current deployment claims are accurate | Docs/examples plus delivered contract | User follows cold/fleet/Slurm/restart example | Unsupported lifecycle or unsafe state reset | Executable synthetic examples and evidence audit |
| Cheap intentional package | Public imports/dependency metadata | Orphan export or extra after deletion | Heavy/missing import or hidden runtime | Package/import/optional dependency gates |

## Implementation Slices

1. Audit prior removal records and exact static/dynamic/generated consumers; identify only the remaining shared owners.
2. Delete those owners after preserving required pure primitives; update exports/config/recipes/tests and dependency metadata.
3. Complete lifecycle terminology, deployment comparison and operator cutover guidance from delivered behavior.
4. Run integrated synthetic CLI/Python/sweep/MCP journeys and final gates; record qualified live evidence and each retained primitive consumer.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/contract | Required | Intentional current public API, removed modes, cheap imports and preserved scientific/control semantics. |
| Integration/E2E | Required | Same synthetic pipeline through CLI/Python/sweep/MCP; inspect/cancel/reconnect and accurate cleanup. |
| Removal/doc audit | Required | No old production owner/export/dynamic entrypoint; examples match delivered commands; remaining primitives have consumers. |
| Live deployment | Reuse or requalify if changed | Record Phases 3/4/6/8 receipts and gaps; final docs cannot upgrade unsupported claims. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/package tests/contracts/test_runtime_profiles_contract.py tests/e2e/test_cli_runs_e2e.py tests/e2e/test_sweep_cli.py

Use the published isolated MCP lane for the integrated tool journey; reuse its fresh Phase 8 receipt when unchanged.

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop for a supported consumer whose accepted behavior disappears; make the smallest owner-level remedy without retaining a second engine. Obsolete input compatibility alone is not a blocker. Preserve historical records and outputs, and do not count unrun site qualification as success.

## Executor Handoff

Read planning.md Behavior Baseline, the requirement/design/validation IDs above,
this whole card and the actual published predecessor contracts. Implement the
listed slices within the stated ownership. Do not reopen agreed lifecycle,
grant-before-start, sole submission/finalization ownership or hard cutover.
Manager action is for a demonstrated public/durable or accepted-behavior conflict,
not private helper choices. You are not alone in the codebase; preserve others' edits.

## Workflow State

- Manager preparation: approved card; execution revision/worktree pending
- Planning review: original design review and corrected run/cancel contracts retained; nine-phase mapping checked locally
- Implementation: not started
- Refiner: not used
- Pre-submit gate: not run
- Independent implementation review: required for final hard public/dynamic removal and stage integration
- Blocker corrections: 0/3
- PR and merge: not started

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Not started |
| Tests added, updated or intentionally removed | None; planning only |
| Validated revision/tree and evidence | Pending implementation |
| Validation-relevant changes after evidence | None |
| Replaced-code removal / retained primitive consumers | Pending this phase's removal audit |
| PR, review and merge | Pending |
| Residual risk and cleanup | Final dynamic removal and qualified deployment evidence audit pending |

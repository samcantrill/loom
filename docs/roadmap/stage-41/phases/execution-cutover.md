# Phase 9 Execution Plan: Complete Execution Cutover

## Metadata

- Status: pr_open
- Roadmap stage and phase: 41 / 9
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p9-execution-cutover
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `d0e2dd33729cb465d5af313fe22379a6dad5c27d` (published Phase 8 completion metadata after PR 319)
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 9: Complete Execution Cutover
- Dependencies: Phase 8 remotely merged; approved Stage 41 plan
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: none; native observer amendment independently reviewed and explicitly approved on 2026-09-14

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

### Approved native observer bridge

The source audit found that deleting the old runner would remove committed
lifecycle notification behavior from current event-sink/webhook consumers.
[The approved native lifecycle observer amendment](../planning.md#phase-9-amendment-native-lifecycle-observers)
is the single owner of the new selection, authority, delivery/trust and validation
contracts. The maintainer explicitly approved it on 2026-09-14. Phase 9 owns that bridge and consumer migration atomically with removal; existing backend,
run identity and scientific behavior remain fixed. The native bridge is implemented; the Workflow State records owner-level corrections and validation.

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

Preserve native prepared-receipt submission and explicit failed-admission retry
while deleting the old whole-run queue surface. Same-ID run/sweep/MCP replay must
still observe a terminal failure rather than silently retry it; the current
embedded-only retry capability remains documented. Preserve the shared publication
lock, report-v3 evidence, native completion qualification and exact predecessor
commit/replay invariants when removing the final legacy consumers.

Audit every changed durable/wire owner against the baseline inventory and the
earlier cards' version/refusal decisions. Existing compatible report/root shapes
need no gratuitous replacement; incompatible roots/peers fail before mutation.
Keep retained outputs and evidence inspectable under their qualified version.
Do not turn hard cutover into an implicit root reset or erase preparation pins.

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

- Manager preparation: passed on the manifest stage worktree and canonical Phase 9 branch at the Base revision above. Phase 8 PR 319 merged as `928df2e42ec29b9f2c68a7cdb8bfff2c9d09d1b4`; completion metadata is published, synchronization verified matching stage/local/fetched/advertised develop, and exact predecessor local/remote branches are retired. All predecessor agents/processes are terminal; successor start and preflight passed.
- Source reconciliation: remaining runner/continuation/offline/whole-run queue and generated Slurm continuation owners are removed. Static imports, configured plugin targets, CLI parser registrations, generated command builders, examples and the repository monitor now use native operations or explicitly read-only primitives. The disposition and meaningful surviving assertion owners are recorded below. Historical roadmap records are retained.
- Validation selection: package/public/isolated imports, runtime profiles, native CLI/Python/sweep/MCP journeys, affected diagnostics/event/log/catalog examples, removed entrypoint refusal and source/dynamic/doc disposition. The card's named test paths remain present; use the locked isolated environments owned by tests/README.md. Both full make gates remain binding. Expand for changed shared execution/planner/artifact/resource boundaries, a failing supported consumer or a missing accepted assertion; reuse unchanged predecessor backend/race evidence.
- Qualification reconciliation: P3/P4/P6/P8 phase records own the actual local evidence and unavailable physical fleet/NAS/container/Slurm/live-assistant cases. Final docs must retain these limits; no external workload, provisioning, allocation acquisition or active project environment changes are required by this phase.
- Resolved contract gap: the event-sink/webhook consumers depended on old runner event emission and retained callback failures. The native request/coordinator authority lacked an observer selection/dispatch contract. The executor stopped before edits; manager authored the bounded amendment linked above. Independent plan review passed at `1ec0bc01a6a94d6f1a7340de1c645ace2e2bc51f`; the maintainer explicitly approved it on 2026-09-14, authorizing implementation. The amendment used no implementation correction; the two subsequent owner-level corrections are recorded below.
- Execution delegation: one executor is justified for the remaining cross-package orchestration removal, consumer/test migration and integrated operator documentation. It owns Phase 9 source/tests/current docs/examples and this card; manager owns the manifest, delivery and independent review. No children, extra branches or lifecycle sidecars.
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: observer bridge, failure-policy restoration, consumer migrations and remaining engine removal are committed; both required final gates passed. Default read-only status/backend/artifact/plan consumers select an existing embedded authority, explicit service selection remains authoritative, and bounded local log inspection follows retained native references with truthful unavailable cases. The manager confirmed these as accepted consumer migrations.
- Refiner: not used
- Pre-submit gate: manager acceptance passed for approved scope, source/dynamic removal, preserved consumer assertions, native observer authority/trust, failure/cancellation behavior and qualified operator docs. Both fresh `make validate-pr` and `make test-summary` passed on `42cc9957d43f85144fc6538aa610103e0df49f32`, tree `753d32979eae3793a49c16f53a5afd390bbbdf99`. Manager independently parsed all seven XML receipts (3,257 passed, 15 skipped, zero failures/errors), verified the archive hash and inspected the metadata-only delta. Later edits only record phase/manifest acceptance and delivery facts.
- Independent implementation review: pending on PR 321 for final hard public/dynamic removal and stage integration
- Blocker corrections: 2/3. Native runtime options already retained `continue_independent`, but admission finalization ignored it and failed before unrelated branches settled. Manager confirmed restoration within the accepted contract. Consume the existing serialized policy at native readiness/finalization, retain failed descendants and explicit retry semantics, and stop new work after a known failure under the default policy. No new durable policy schema is introduced. The discriminating failure and rechecks are archived under `/tmp/loom-stage41-p9-evidence/native-failure-policy*.log` and `native-policy-settlement.log`.
- Correction 2: manager reproduced failure plus independent early-stop remaining WAITING/RUNNING with both stage facts terminal. Historical authored parallel behavior gives cancellation precedence for a still-live run. Native cancellation now runs before independent-failure waiting; fresh dispatch refuses an observed cancelled stage. Terminal run guards and existing containment/release ownership remain intact. The regression retains failed/early-stop facts, original reason, cancellation outcome, and no managed binding for a further independent branch. Eleven focused failure/cancellation/late-terminal tests pass (`native-failure-cancellation-owner-recheck.log`).
- PR and merge: [PR 321](https://github.com/samcantrill/loom/pull/321) is open, non-draft and mergeable against develop with the canonical phase title and branch; independent review and gated delivery remain pending.

## Removal and coverage disposition

| Retired owner | Surviving behavior and current consumer |
| --- | --- |
| `execution/runner`, continuation, offline adapter and Slurm controller | `LocalDaemonExecution`, native preparation/publication/run operations. Native production/reconciled-run/failure-policy suites retain scientific artifacts, branch dependencies, explicit retry, output predecessor, cancellation, replay and restart assertions. |
| Whole-run queue client/service/controller/local/Slurm adapters and generated CLI commands | Native daemon/agent/client operations, current sweeps and MCP. Mixed native CLI/public-contract suites were retained; obsolete whole-run adapter/drive tests were removed. `test_execution_cutover_contract` checks removed imports and parser refusal. |
| Direct subprocess/container executor classes and unrestricted stage worker | Restricted `execute_resident_stage_worker_request`, native resident/container supervisor and Slurm bootstrap. Worker contract retains output payload/ref assertions without worker-owned authority finalization; containment, GPU, resource and native backend suites remain. |
| Generated whole-run Slurm planning/submission/cancel/status/script wrappers | Connected agent ready-stage owner and fixed restricted bootstrap. Pure directives, GPU allocation projection, command parsing, resource mapping and Apptainer wrapping remain used by `ready_stage.py`; historical manifest serializers/readers remain read-only evidence. |
| Runner-built diagnostic/import fixtures | Native execution for current CLI/log/invalid-factory consumers; explicit synthetic authority facts for read-only diagnostics; one frozen historical offline manifest shared by tests and import examples. Import rejection, checksums, artifact indexes and bundle payload equality remain asserted. |
| Repository monitor's old queue engine and scheduler queries | Existing native client admission pages/details, authority facts and retained scheduler observations. Demo is in-memory presentation data; missing capacity/input counts are unknown. Collector failure/staleness, refresh, bounded logs and native state assertions remain. |
| Legacy public runner/examples and dynamic plugin targets | Local/log/catalog/event/webhook/backend examples use native sessions. Local example checks unchanged reuse and corruption-local repair through the pure planner, without implicit reexecution. Whole-run queue examples point to native sweep/ready-stage journeys. Graph-only Slurm examples generate no commands. |

Retained pure storage/resource interfaces have current consumers:
`RuntimeServices` supplies installed executor registry factories and extension
inspection; its unused store compatibility facade is removed. The authority
adapter remains a pure authority-backed store used by planning, diagnostics,
read-only fixtures and store conformance. Queue record/config/repository models
support historical inspection; assignment/resource providers are used by native
agents. Prepared-run and Slurm manifest records retain read-only serialization
and import/inspection consumers. None executes a second run lifecycle.

The final deleted-suite inventory is archived as
`/tmp/loom-stage41-p9-evidence/retired-owner-test-inventory-final.json` (54 removed
files, 358 test functions at the audit snapshot). Mixed files retain native
assertions; deletion counts are not a coverage claim. Earlier phase completion
records remain the owners of backend qualification: P3
`service-startup-lifetime.md`, P4 `agent-worker-execution.md`, P5
`agent-slurm-jobs.md`, and P6 `slurm-result-recovery.md`. Their physical fleet,
container, shared-storage and Slurm gaps are unchanged. No physical workload,
webhook delivery, provisioning or live-site success is claimed here.

The broad diagnostic run recorded 2,957 passes and 13 failures while the worktree
was still changing. Retired-mode tests and stale import/schema expectations were
reconciled; native late cancellation exposed that failed run authority must not
wait for already-terminal provider release. The smallest correction retains
waiting for executable assignments while allowing terminal authority and
cleanup to remain distinct. The existing late-cancel/provider-release test,
native failure-policy test, and cancellation restart test own the recheck.
The old-projection test double now accepts the existing native policy keyword.
Explicit authority selections, including a default-valued service selection or
environment selection, now refuse missing service endpoints instead of silently
reading embedded authority. The focused consumer recheck passed 26 tests
(`explicit-authority-selection.log`). Full-gate evidence below must be fresh on
the stable candidate.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Native protected observers and committed selected-authority event/failure/link facts; authored failure-policy restoration; remaining execution engine removal; current diagnostics/monitor/examples/operator cutover conversions. |
| Tests added, updated or intentionally removed | Native observer identity/delivery/persistence diagnostics, failure-policy and descendants, restricted workers, read-only native diagnostics/log availability, historical import/bundle artifacts, hard command/import refusal, and retained native CLI/agent/Slurm suites. See disposition above. |
| Validated revision/tree and evidence | `42cc9957d43f85144fc6538aa610103e0df49f32`, tree `753d32979eae3793a49c16f53a5afd390bbbdf99`. Both final gates passed; complete gate logs, seven suite XML/coverage artifacts, report, skips and checksummed archive are under `/tmp/loom-stage41-p9-evidence/gates-final/`. |
| Validation-relevant changes after evidence | None. Subsequent edits only record current phase/manifest acceptance and delivery metadata; manager inspected the delta. |
| Replaced-code removal / retained primitive consumers | Implemented; explicit owner mapping above. |
| PR, review and merge | [PR 321](https://github.com/samcantrill/loom/pull/321) opened against develop; independent review and delivery pending. |
| Residual risk and cleanup | Approved synchronous best-effort observer delivery tradeoffs; no replay/outbox guarantee. Physical qualification remains with prior phase records. Owned process audit is empty; exact task orphan PID 1189812 was stopped after identity verification, and both private tmpfs scratch roots were removed. Unrelated processes/roots were preserved. |


Final `make validate-pr` passed Ruff, Pyright (zero errors), default tests
(2,937 passed, two optional-import skips, 320 deselected), config tests
(274 passed, 15 opt-in physical-container skips, 2,987 deselected), MCP tests
(44 passed, 3,215 deselected), and sdist/wheel builds. Final `make test-summary`
passed all seven rows: package 124, unit 2,060, contract 303, integration 429,
e2e 23, config 274, MCP 44; overall 3,257 passed, zero failures/errors, 15 skipped.
Per-suite coverage and actual skip reasons are in the archived report/XML.
The complete archive is `/tmp/loom-stage41-p9-evidence/evidence-archive.tar.gz`,
SHA256 `3627cd384602e3a2a9d1fa4ea9aba65e86d4a6adfee1c1aba71a80f42ee40660`.

Failed gates remain qualified evidence, never overwritten as success:
`gates-8a346be` found an explicit test import missing for Pyright;
`gates-b63af55` found one obsolete continuation CLI assertion;
`gates-81ee9dd` found a parsed integer example count asserted as a string.
Each was corrected before the final candidate. `gates-9fe3df9` preserves a
passing prior validation gate and failed coverage summary (one recovery wait,
two resident probe timeouts, two explicit disk-full errors). The local root
filesystem reached capacity. All five failed cases passed unchanged after
manager-approved private local tmpfs scratch, with executable fixtures and
cross-process SQLite locking verified; NAS storage was not substituted.
Manager's separate early-stop reproducer then required correction 2 above,
invalidating that earlier candidate for final delivery.

Final validation used private local `/dev/shm` scratch and cache. The first
corrected-candidate summary passed six rows but its long temporary-directory
prefix exceeded AF_UNIX path limits in the managed remote journey; its complete
artifacts remain under `gates-final/summary-long-tmpdir/`. Shortening only the
scratch root to `/dev/shm/l9` resolved this, and a fresh full summary passed.
The intermediate no-extra single-case probe skipped for absent dotenv and is
not passing journey evidence; the final e2e row executed and passed that journey.
`gates-final/scratch-environment.json` records exact environment differences.
Tmpfs receipts establish local POSIX lifecycle behavior, not power-loss,
physical-storage, container fleet or Slurm qualification. No source or test
assertion was weakened to address storage or temporary-path failures.

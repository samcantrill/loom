# Phase 1 Execution Plan: Pipeline Resource Accounting And Controls

## Metadata

- Status: blocked; recovery approved, independent startup review pending
- Roadmap stage and phase: Stage 39, Phase 1
- Manifest: `docs/roadmap/stage-39/implementation-plan.md`
- Branch: `agent/stage-39-p1-pipeline-resource-policy`
- Worktree: `stage-39-p1-pipeline-resource-policy` under the manifest's root
- Base revision: published develop `000f34f`, merged without conflicts in
  `b94b89d`; original approved planning packet imported from `6c1a0edc`
- PR target: develop
- PR title: `feat(runtime): separate pipeline resource accounting and enforcement`
- Dependencies: reviewed Stage 39 plan and concrete migration approval — satisfied
- Workflow path: expanded; public options, executable schemas and cross-machine ownership
- Blockers: no-claim offer freshness, authoritative retained-worker comparison,
  and managed control/failure transport and known-no-start completion (see below)

## Objective And Context

Deliver FR-39-01..08 for configured pipelines: GPU-only accounting can retain
CPU/RAM demand without claiming those resources or adding container cgroups.
Local and remote workers consume the exact prepared choice, and supported
additional controls and timeout can be selected independently. All pipeline
consumers ship together so the new default is truthful on the first merge.

Phase 2 owns the older whole-run `LaunchContract` and its flat assignment-provider
API. They retain existing behavior during this phase; docs must scope the new
default to the migrated pipeline API, not claim the whole-run migration is done.

## Current Source And Harness

- Composition and demand: `src/loom/pipeline/runtime/{options,profiles,metadata,
  placement,capabilities}.py`, `pipeline/resources.py`, and existing semantic
  planners/validators. Read `docs/features/runtime-resources.md` and `docs/structure.md`.
- Admission: `pipeline/execution/{runner,resource_admission}.py`,
  `queue/local_daemon_runtime.py`, `queue/managed_local_preparation.py` and
  `queue/local_daemon_execution.py`. Placement, not `resolve_run_runtime`, knows
  authored/default/planner-refined demand.
- Process boundaries: `pipeline/execution/models.py::StageWorkerRequest`,
  `queue/_managed_local.py`,
  `queue/_resident_stage_worker.py`, `queue/_remote_stage_execution.py` and
  `queue/agent_session_transport.py`. Managed claims already carry resource-kind
  identity; this is not Phase 2's `LaunchEnvironmentBindings` API.
- Controls and evidence: Apptainer/Docker command builders and executors,
  `pipeline/executors/slurm/{resources,planning,ready_stage,container}.py`,
  `diagnostics/preflight.py`, current runtime metadata and inspection renderers.
- Harness: Python 3.12, locked `uv` environment, existing test harness and final
  Make gates. Public imports must not acquire optional config/GPU dependencies.

Startup reconciliation: upstream PR #289 at `214f242c` adds
`prepare_managed_run` for trusted already-composed inputs and explicit execution
requirements; the embedded-local facade delegates to it. Preserve both entry
points, coordinator-only preparation, no recomposition or local-agent discovery,
exact requirement coverage and immutable replay. Both use the unchanged
`_runtime_for_service` and managed payload owner, so policy flows through that
shared path. Extend its existing preparation/public-import tests; do not fork
preparation or change the approved resource/durable contracts. Manager verified
the five-file upstream diff; no additional phase-planner pass is needed.

## Scope

In scope: policy and profile composition, one post-demand projection, serial and
managed admission, local/remote exact handoff, direct container and all existing
SLURM mapping routes, preflight/inspection, actionable errors, executable cuts,
and all maintained pipeline configs, examples, tests and feature documentation.

Out of scope: raw whole-run policy/record/provider migration, new controls or
providers, timer redesign, factory construction, scheduler/lifecycle redesign,
Stage 85 probe behavior, rphys source, images or physical execution.

Assumption: existing claims and providers remain the authority for managed
binding. Excluding accounting cannot create a secret reservation for enforcement.

## Fixed Contracts And Private Discretion

- Public keyword-only `ResourcePolicy(account_for=..., enforce=...)`, exposed at
  `loom.pipeline.runtime`, is carried by `RunOptions.resource_policy` and
  `StageRuntimeOptions.resource_policy`. Strict plain-data codec; immutable,
  detached canonical identifier lists. Each omitted axis inherits independently,
  supplied lists replace, empty mapping inherits, explicit null is invalid.
  New invocation defaults are all/empty; timeout is unchanged reliability policy.
- Resolve full semantic demand before selecting. `resolve_run_runtime` composes
  selectors only. `resolve_stage_placement` owns the managed concrete selection;
  default CPU and planner refinement precede it. Store full `resource_request`
  and sorted `resource_selection` with account_for/enforce lists in placement's
  fingerprint. Absent/zero demand contributes no selected identifier.
- Scheduling descriptors/requests cover accounted kinds without skipping full
  demand semantic validation. Serial admission uses the same projection before
  its existing positive-integer lease conversion; irrelevant excluded memory
  must not reach that adapter-specific representability check.
- Intent loading joins saved placement demand and selection into worker runtime.
  Stage preparation and retained request/bundle replay consume or compare that
  exact projection. Mismatch fails before launch; never refresh a retained worker
  file or expand `all` from runtime-only resources. Direct non-managed routes use
  the same projection at their existing effective-demand ingress, preserving
  runtime-over-container intent precedence and saving the result in their handoff.
- Public `build_apptainer_exec_command` and `build_docker_run_command` accept the
  effective policy/selection at their existing boundary. A standalone builder can
  resolve a new selection after demand; a prepared builder consumes/validates it.
  Filtering to no controls must not trigger fallback to the original full demand.
- Native serial adds no CPU/RAM/GPU mechanism. Managed routes select existing
  provider contributions by authoritative claim kind. Apptainer/Singularity use
  existing CPU/RAM flags and supported GPU binding; driver passthrough is separate
  from visibility restriction. Docker supports CPU/RAM only. Unsupported selected
  present controls fail with cause, requested kind, prerequisite and fix; unselected
  unsupported controls do not fail. No absent demand creates flags or a mask.
- SLURM maps full allocation demand regardless of inner accounting selection;
  preserve unsupported hard-request rejection, profile identity and request digest
  on ready-stage and existing planning routes. Preserve inherited allocation;
  do not duplicate scheduler-owned CPU/RAM limits inside the container.
- Empty enforcement preserves claims/renewal/fences/release, authored environment,
  suspension/reconnect, cancellation, containment, and control-plane/cleanup
  deadlines. Existing job timeout remains independent, including explicit disable.
- Runtime metadata keeps composed `resource_policy`; post-demand handoffs keep
  `resource_selection`. Existing command/attempt/launch metadata adds ordered
  `resource_controls`, each exactly `{resource, owner, mechanism, disposition}`.
  Mechanism can be null. Sort by resource/owner/mechanism. Dispositions:
  not_requested, not_applicable, requested, applied, delegated, unavailable, failed.
  Preflight/argv is requested, not applied; applied means a launched job received
  the flag/binding, not measured isolation. Known setup failure is failed; uncertain
  inner launch remains requested/failed. Ordinary application failure does not
  erase valid launch evidence. SLURM delegated and inner not_requested can coexist.
  Older metadata is unreported; no lease capability or raw binding values here.
- Executable cuts: RunOptions 1→2; placement 2→3; exact managed runtime 2→3;
  StageWorkerRequest 1→2; resident bundle 3→4; `SlurmStageDelivery` 3→4 at
  its existing codec. Preserve the delivery's enclosing store schema. Reject old
  explicit versions before input acceptance, resource/worker reconstruction or
  launch, preserve saved bytes and nested causes, and give guidance to finish/cancel
  in the pinned old environment and prepare a fresh identity. Existing
  `ExecutionFailure`/`StageWorkerResult` envelopes remain unchanged; the recovery
  below versions the closed remote report and retained supervisor launch while
  preserving legacy inspection/replay. Reconcile version constants with actual
  published owners at startup; material overlapping changes need review.
- Retire `cpu_memory_enforcement=runtime/scheduling_only` atomically with all its
  current pipeline consumers. Reject the removed key with replacement guidance;
  no silent alias/translation. Examples explicitly select intended controls.
- Cross-phase: Phase 2 reuses the public policy and projection semantics without
  importing heavyweight executor code. Private module/helper layout, wiring and
  fixture organization remain executor discretion; no second policy class/store.

## Proportionality

Extend current options, placement, leases, builders and metadata. Each executable
cut protects an actual retained/process boundary; control evidence has current
preflight and inspection consumers. Defer measured kernel enforcement, plugin
mechanisms, live upgrades, new scheduler kinds and a policy-by-backend Cartesian suite.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer / consequence | Coverage |
| --- | --- | --- | --- |
| Independent composition | Policy codec and runtime profiles | Stage override accidentally restores inherited controls | Per-axis inherit/clear and strict public codec |
| One effective selection | Post-demand projection; placement owns managed use | Default CPU/planner refinement lost or replay expands all again | Exact full demand/subset fingerprint and worker comparison |
| Only selected claims/bindings | Admission and actual managed launch owners | Excluded memory blocks serial job or unselected GPU mask is added | Actual leases plus local and remote process environment |
| Explicit supported controls | Existing backend mapping/capability boundary | Docker GPU or missing allocation silently downgrades | Selected failure versus unselected success; exact argv |
| Honest execution evidence | Existing launch/submission and metadata boundary | Preflight or failed container creation claims enforcement | Requested/failed/delegated and legacy-unreported assertions |
| Immutable retained meaning | Executable codecs and preparation/replay | Old request launches under new defaults | Old-writer fixtures and zero resource/launch side effects |

## Implementation Slices

1. Add the public policy and independent profile composition; thread selectors
   through runtime without prematurely resolving concrete demand. Cover codec,
   defaults and import boundaries with the first real consumers.
2. Resolve/select demand at placement and direct ingress, select actual admission,
   and migrate exact local/remote worker handoffs and executable readers together.
3. Apply selected controls in builders and managed launch; migrate the old switch,
   preserve timeout/lifecycle and full-demand SLURM allocation semantics.
4. Align capability/preflight, actual-launch evidence and maintained examples/docs;
   cover actionable failures without eager downstream factory construction.
5. Complete causal integration/replay cases, final stable-tree gates and independent
   correctness review. These are slices within one atomic phase, not separate PRs.

## Test And Validation Plan

| Suite | Required or deferred | Behavior/risk and minimum oracle |
| --- | --- | --- |
| Package | required | `tests/package/test_import_boundaries.py`, `test_public_api.py`: public policy cheap and intentional |
| Unit / contract | required | Runtime options/profile contracts and units: omission, empty, all, strict shape, independent override and round trip |
| Admission / placement | required | `pipeline/execution/test_resource_admission.py`, `pipeline/test_orchestration.py`, `queue/test_managed_resources.py`, `test_managed_local.py`: default CPU after refinement; GPU-only actual claims; retained full fractional-memory demand; absent/zero invents none |
| Worker / replay | required | Stage-worker contracts/units/integration, `queue/test_managed_local_preparation.py`, `test_resident_stage_worker.py`: old versions reject pre-effect; exact replay preserves bytes/timestamps; changed selection conflicts; saved placement/worker mismatch cannot launch |
| Managed integration | required | `test_local_daemon_production.py`, `test_agent_session_transport.py`, `pipeline/test_managed_local_execution.py`: actual local/remote environment differs with enforcement, no-binding reservation still renews/releases, retained launch uses exact policy |
| Container / SLURM | required | Apptainer/Docker command/executor tests, Docker command contract, SLURM resources/planner/container/scripts/ready-stage and queue ready-stage tests: default no flags, explicit exact CPU/RAM, unsupported selected vs unselected GPU, preserved intent precedence and driver access, full SBATCH demand with no duplicate cgroups; `tests/integration/queue/test_slurm_ready_stage.py` uses an old-writer schema-3 delivery to prove pre-input/pre-resource/pre-worker rejection and a current schema-4 round trip to preserve the exact selection |
| Diagnostics / examples | required | Runtime-capability integration, preflight unit/contract/integration and CLI contract: same execution choice, no false applied controls, setup/application failure distinction, old unreported metadata and removed-key guidance; composed maintained examples select intended behavior |
| Lifecycle regression | required | Existing timeout, cancellation, suspension/reconnect, containment and release cases in final gates; explicit enforcement-none does not disable timeout or lease ownership |
| Physical / live scheduler | deferred | No host configuration, GPU workload, SIF launch or SLURM submission is authorized by this plan; fake commands/CPU loopback do not prove physical isolation |

Targeted commands use the worktree's locked environment; select the named owners
as slices change, then let the final gates cover all maintained suites:

    uv run --locked --group dev pytest tests/contracts/test_runtime_options_contract.py tests/contracts/test_runtime_profiles_contract.py tests/unit/loom/pipeline/test_runtime_options.py tests/unit/loom/pipeline/test_runtime_profiles.py
    uv run --locked --group dev pytest tests/unit/loom/pipeline/execution/test_resource_admission.py tests/unit/loom/queue/test_managed_local_preparation.py tests/integration/queue/test_local_daemon_production.py tests/integration/queue/test_agent_session_transport.py

Final commands:

    make validate-pr
    make test-summary

Record revision/tree identity, required-case results and opt-in skips accurately;
refresh evidence only after validation-relevant changes. No runtime gate is
claimed by this planning-only packet.

## Risks, Review, And Stops

- Review upstream/current source assumptions and the complete implemented diff,
  especially post-demand ownership, retained local/remote comparison, standalone
  builder defaults, selected admission versus semantic validation, SLURM delegation
  and delivery replay, import direction and truthful failed-launch evidence.
- Plan review found one qualified replay gap: the retained flattened SLURM delivery
  could otherwise stamp a current worker schema around old runtime data. The added
  delivery codec cut and discriminating integration coverage resolve that finding;
  no other qualified plan blocker remains; final approval is recorded.
- Required expanded independent implementation review follows manager pre-submit
  checks. Use the canonical phase budget: one executor, at most one qualified
  refiner and three total scoped blocker corrections; no speculative hardening.
- Stop for an unsupported required mechanism, inability to preserve lifecycle or
  retained meaning, overlapping durable upstream changes, exhausted correction
  budget outside the approved recovery below, or any proposed physical run.
  Ask about material changes, not mechanics.
- Accepted risk: no binding is not isolation; accounting only reserves capacity.
  Host enforcement proof remains separate opt-in work on a compatible approved host.

## Executor Handoff

Read this complete card and the manifest's shared constraints, current Loom
AGENTS/workflow and source/tests above. Use slices 1–5 within this phase's owned
paths. You are not alone in the repository; preserve others' edits. Do not change
raw whole-run policy, Stage 85 or unrelated user work. Do not
reopen the approved default. Do not spawn children or broaden controls. Return
implementation, targeted evidence and concrete blockers to the manager; PR/full
gate/review/merge ownership follows the canonical phase workflow.

## Workflow State

- Manager preparation: approval recorded; isolated phase worktree created from
  published develop `214f242c`; upstream preparation addition reconciled
- Expanded planning: EDR-39-01 corrected and independently confirmed; packet review
  passed after the bounded `SlurmStageDelivery` replay correction; final plan approved
- Additional phase planning: not needed; current contracts and upstream join are explicit
- Implementation: initial executor delivery at `fce8016`; manager pre-submit found
  unmet fixed contracts below, so completion is not accepted
- Refiner: correction `1198c1a` and related repair `68a37ad` returned;
  manager verified the changes and added discriminating integration coverage
- Pre-submit: blocked by the remaining findings below; no PR opened or pushed
- Independent implementation review: not started
- Blocker corrections: conservatively counted as 3/3 consumed: refiner correction,
  its separately returned repair, and manager correction `6474206`. Do not reset
  the budget by relabelling further work. Resume through a reviewed targeted
  amendment with explicit recovery scope, not another unbounded correction.
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Checkpoint `6474206` adds full-intent container validation, saved-selection-aware builders, selection-aware capability/preflight, truthful direct-container launch receipts, native unsupported-control rejection, and direct handoff finalization after container/runtime precedence. Refiner commits preserve sparse axes and worker policy/selection, gate provider bindings, and begin empty-claim lifecycle support. This is not a complete Phase 1 implementation. |
| Targeted evidence | 214 policy/worker/container/capability/preflight unit and contract tests passed. Fake ready-stage SLURM integration passed 15 tests, including current delivery round trip and schema-3 writer-shaped delivery rejection before compute workspace/input acceptance. Managed local/remote comparisons: 5 passed, 1 failed. Passing cases include selected versus unselected GPU binding with retained claims/release, and two remote no-claim jobs. The remaining failure is the sequential local no-claim pipeline below. Ruff, Pyright and diff checks pass. |
| Evidence location | Worktree-local ignored `build/resource-policy-checkpoint/` retains unit, managed integration, SLURM replay and type-check logs. The failed managed log is required evidence, not a successful smoke receipt. |
| Full gates | Initial full receipts at `fce8016` are stale after implementation changes. Neither `make validate-pr` nor `make test-summary` is claimed for `6474206`; both must run on the final corrected stable tree. |
| PR, review, and merge | Blocked before submission. Required independent implementation review has not run. No PR, push or merge occurred. |
| Residual risk and cleanup | No physical GPU/container/SIF execution, live SLURM submission or host changes. CPU subprocesses, loopback transport and fake scheduler commands are not physical isolation proof. Preserve this phase worktree and evidence; Phase 2 and rphys Stage 81 physical continuation remain unstarted. |

### Manager Pre-Submit Corrections

These are missing approved Phase 1 contracts, not new design requirements.

| Finding | Evidence and material consequence | Smallest required correction and oracle | Owner |
| --- | --- | --- | --- |
| M1 — sparse policy changes at serialization | On `fce8016`, a run with GPU-only accounting and stage `{enforce: []}` resolves GPU-only before `RunOptions.to_dict/from_dict`, but resolves `account_for: all` afterwards. `ResourcePolicy(enforce=[])` also eagerly fills the omitted axis, and `StageRuntimeOptions.to_dict` loses axis presence. | Preserve omission inside the one policy value until new-invocation composition; exact typed and mapping save/load/profile paths must retain independent inheritance. Reject non-list plain-data selectors and explicit null. | Refiner |
| M2 — saved worker selection is optional and not authoritative | `StageWorkerRequest` checks optional `metadata.resource_selection` and returns early if absent; the approved location is required post-demand `resolved_runtime`. Managed replay checks only identity, not equality to saved placement. Worker execution reconstruction currently discards saved policy/demand. | Carry the saved full demand/policy/selection through the exact runtime mapping, validate at current worker/resident/SLURM codecs, compare retained local and SLURM requests to authoritative placement, and consume without fresh defaults. Add the required old-writer and mismatch integrations, not only version-constant edits. | Refiner |
| M3 — managed/no-resource execution does not consume policy | `_managed_local._worker_environment` and remote launch unconditionally merge every provider binding; native serial ignores unsupported selected controls; the resident bundle rejects empty claims although accounted demand can now be empty. | Select actual job bindings from admitted selection, preserve claims/renewal/release and separate readiness probes, fail unsupported selected controls before application, and support account-none without a hidden resource claim while retaining assignment/lifecycle ownership. Cover actual local/remote environment, empty-accounting lifecycle and unchanged probe behavior. | Refiner |
| M4 — direct control support/semantics still diverge | Public Docker capability validation rejects GPU demand even with `enforce: []`; Apptainer's public builder validates only selected CPU/RAM and ignores explicitly selected unsupported kinds/GPU applicability. Builders reselect rather than consume a prepared projection and omit policy/selection command evidence. | Use the composed policy and full effective demand at existing mapping owners, validate full canonical semantics independently of selected representability, honor saved selection, reject only selected unsupported controls, preserve driver access versus binding and all supported SLURM allocation/inner-control boundaries. Add public builder, capability/preflight and direct-route oracles. | Manager |
| M5 — control receipts overstate application | Container helpers infer controls by scanning all argv, call any non-null outer process result applied, and label `--nv` as GPU control. Known creation failure and payload arguments can therefore fabricate application; current SLURM/managed evidence is missing. | Produce the approved common shape from actual mapping/launch facts, keep setup failure failed or uncertain requested, never treat driver access as binding/isolation, report absent demand and delegated/inner-none honestly, and preserve existing structured failure context. Add fake setup/application failure and metadata/inspection comparisons. | Manager; refiner supplies managed binding facts |

The manager reproduced M1 and Docker's M4 through read-only public API calls and
verified M2/M3/M5 against the current reachable preparation/launch owners. All
18 summary skips were verified from JUnit as opt-in container acceptance. Both
final gates must cover the corrected stable implementation; earlier green
evidence remains an initial-delivery receipt only.

### Refiner Correction Receipt

The refiner correction preserves sparse policy axes through typed and mapping
round trips, rejects non-list authored selectors, carries the exact post-demand
policy, full demand and selection in `resolved_runtime`, and validates worker
replay. Managed local and remote worker environments apply provider bindings
only for selected enforcement kinds. Empty claim commands are now admitted by
the existing assignment, reservation, activation and resident-bundle paths;
their lifecycle evidence remains the same assignment/fence record rather than
a synthetic reservation. Focused policy, worker, journal and resident slices
returned 69 passing tests. Manager integration evidence and remaining blockers
below supersede the refiner's partial completion claim.

### Remaining Blockers And Proposed Targeted Amendment

1. **No-claim offer freshness is still incorrect.** The new sequential local
   test runs and releases `preprocess`, with retained `claims_json` exactly
   `{"commands":[]}`, then leaves `train` READY and the admission WAITING.
   The coordinator has one released assignment and a consumed current offer.
   `SQLiteCoordinatorAssignments.publish_offer` rejects another offer with the
   unchanged provider availability revision. Since no claim was acquired or
   released, the provider correctly did not change that revision. This is not
   unavailable hardware or an insufficient test timeout. Empty receipt guards
   have been removed, and remote single-stage account-none now passes; extending
   a timeout or inventing a CPU claim cannot fix sequential ownership.

   Required remedy: explicitly separate assignment/run-concurrency ownership
   from capacity-offer consumption for empty accounted demand. Reuse only current,
   unchanged validated capacity evidence where no capacity was consumed; preserve
   stale-offer rejection, fencing, unknown-work withholding, cancellation and
   ordinary resource-consuming reservations. Do not fabricate a provider revision
   or add a hidden resource claim. Lock the exact replay/CAS rule in the amendment
   before another implementation pass, retaining the failing two-stage test.

2. **Retained worker consistency is not yet authoritative.** New preparation
   joins placement demand/policy/selection, and worker codecs check their internal
   consistency. However, the retained-worker branches in local daemon `_execute`
   and `_dispatch_slurm_ready` still compare identity only. A saved worker can be
   self-consistent but disagree with authoritative placement. Compare saved full
   demand, concrete policy and selection to that placement before launch/delivery;
   preserve bytes and add actual retained-file mismatch tests for both routes.
   This remains an original M2 obligation, not a new acceptance criterion.

3. **Managed receipts and failure transport need an explicit carrier contract.**
   `_RemoteExecutionReport` has a closed schema-1 field set without executor
   metadata or a structured failure. `_ResidentAssignmentWorkspace.retain_outputs`
   replaces the underlying failure message with `resident stage execution failed`.
   Agent-local `resource_controls` alone cannot satisfy coordinator/client
   inspection or actionable selected-control failures. The retained supervisor
   launch also has a closed field set without a metadata slot. No speculative
   changes to those formats were retained in this checkpoint.

   Required amendment: name the existing structured-failure representation and
   bounded control-record carrier through launch, report, coordinator storage and
   inspection; explicitly review version/reader rules and old report digest/replay
   preservation. Old evidence remains unreported, never silently upgraded. Keep
   control records free of raw bindings/lease capabilities. Resolve how detailed
   failure context crosses the report's current path-free trust boundary; do not
   introduce an ad hoc resource-only exception-string escape hatch.

4. **Unavailable managed controls need truthful no-start completion.** The
   provider binding owner runs after activation/grant. It currently ignores a
   selected kind with no claim or an empty provider contribution. Simply raising
   there would leave ownership unsettled: ordinary resident result persistence
   requires STARTED, while its existing no-start path accepts cancellation only.
   Preserve the active-claim requirement of GPU binding; do not eagerly call
   providers before activation. Extend existing definitive no-start failure proof
   through local/remote terminal completion and release, preserving nested cause
   and remediation. Never call an indeterminate launch a known failure or invent
   a process-start event. This is the unresolved M3/M5 integration, not permission
   for a new scheduler or lifecycle store.

## Approved Recovery Amendment

The maintainer's 2026-09-09 implementation request approves the four remedies
above, this amendment, independent startup review, bounded implementation, fresh
full gates and independent implementation review before merge. This section owns
the concrete recovery contract. The original three correction passes remain
consumed, not reset. Recovery permits one scoped executor delivery and at most
one qualified correction. Stop with a concrete blocker if that allowance is
spent. No recovery implementation starts before a passing independent startup
receipt is recorded. Private helpers and slice order remain executor discretion.

Evidence: clean tree `b94b89d` joins checkpoint `6474206` to develop `000f34f`
(PR #290). That upstream delta adds managed-lifecycle examples/tests but changes
none of these scheduling/report/runtime owners. Preserve those journeys in final
validation and leave the original dirty checkout untouched.

### R1 — Canonical Offer Reuse

Keep the SQLite tables and unique `(agent_id, session_id, availability_revision)`
key. `publish_offer` returns the canonical offer ID. A different proposed ID may
reuse an existing availability revision only if its row is current, unconsumed,
and the entire normalized snapshot equals the proposed snapshot apart from
`offer_revision`. This includes session, inventory/snapshot revisions, provider
and planner descriptors, atoms and reflected claims. Reuse changes no stored
bytes, revision or consumption bit. Reject stale, consumed or conflicting evidence;
never revive a historical offer. The daemon uses the returned ID consistently in
assignment, decision receipt and delivery while retaining deterministic per-work/
attempt/projection identity; never rewrite a retained assignment to adopt an offer.

The existing reserve transaction still validates current offer, READY work,
receipt, single active assignment and run-wide parallel limit. Empty claims create
the same fenced assignment but do not consume the offer. Provider lifecycle receives
no synthetic command. Later resource-consuming work may consume that current offer
once; concurrent losers revalidate at the existing transaction. No new scheduler,
store or fabricated provider revision.

Proof: local and remote sequential account-none pipelines complete with real CPU
workers/loopback transport. Unit cases cover two no-claim assignments under a run
limit, a limit loser, exact replay, conflicting/stale snapshots and a consuming
claim after empty work followed by a consuming loser. Existing unknown-work
withholding, cancellation and release checks remain required.

### R2 — Authoritative Retained Worker Comparison

At local `_execute` and `_dispatch_slurm_ready`, compare decoded retained full
normalized demand, concrete policy axes and saved selection with
`_worker_runtime(intent, stage_name)` before input delivery or launch. Use canonical
plain data so tuple/list or immutable-map differences are not false conflicts.
Keep identity and internal codec checks. This is Loom handoff validation, never
downstream factory/dataset/model instantiation. Name the disagreement and advise
investigating retained input or preparing a fresh identity; do not overwrite it.

Proof uses actual retained files on both routes: an internally consistent resource
handoff mismatch is rejected before delivery/start without changing bytes or
timestamps, while exact replay succeeds. Codec-only mismatch tests are insufficient.

### R3 — Portable Failure And Control Evidence

Reuse `ExecutionFailure` and the `loom.diagnostic.v1` projector/renderer. Execution
exception capture stores native causes, implicit context and exception-group
children in `ExecutionFailure.details.diagnostic_failure`; where a traceback is
captured, retain formatted text including notes (without locals) in
`details.traceback`. Preserve other details and downstream nested context. Existing
cycle/node limits retain explicit truncation evidence. A worker-local filename is
provenance, not a dependency for another machine to inspect the cause. Cover common
local/subprocess/container worker capture/wrapping and managed no-start producers;
carry existing structured failures intact rather than recapturing their summaries.
Do not introduce a repository-wide exception base-class migration.

`_RemoteExecutionReport` schema 2 retains existing identity/status/output and scalar
summary fields and adds the following closed fields:

- `failure`: complete existing `ExecutionFailure` plain-data envelope for FAILED,
  otherwise null. Its worker-local run URI is source provenance until the
  coordinator rebinds identity to its authoritative run/attempt.
- `resource_controls`: ordered four-field records from the actual owner, or null
  for unreported evidence. Empty is distinct from unreported.
- `process_created`: true for confirmed launch, false only for owner-proven
  no-start, null for evidence that cannot establish it. Application-authored
  failure details are not proof of no-start.

New writers emit schema 2; readers accept exact schema-1 and schema-2 field sets.
Legacy decode/re-encode returns the original shape/canonical digest without new
fields, inferred controls or start proof. Current scalar summary and identity
must agree with nested failure. Remote-agent and SLURM report/store/commit paths
share this contract; enclosing database versions stay unchanged. Existing transport
bounds apply, with actionable failure rather than silent truncation on overflow.

The existing retained `ResidentWorkerLaunch` document gains explicit schema 2 and
`resource_controls`. Unversioned legacy documents preserve their old shape and
digest on decode/re-encode, with evidence unreported; new fields participate in
new launch identity/digest. Keep supervisor SQLite schema and continuity/fence
checks. Producer-built records, not arbitrary argv/environment scanning, establish
evidence. Preparation is requested; only confirmed launch makes controls applied.
Merge actual launch evidence into worker results at completion. No-start is
unavailable/failed, never applied; application failure retains applied controls.

At fenced local/remote/SLURM completion, persist the identity-rebound full failure
and control metadata at existing run-store result/attempt owners before terminal
admission is visible. Interrupted diagnostic persistence must be repairable through
commit replay without changing accepted report identity/bytes. Do not complete
commit/release while required persistence is absent. Existing admission run-result
views and CLI text/JSON expose the chain without reading worker-local files.
Successful control evidence must also be inspectable through existing result/
metadata owners. No new report store or API endpoint.

This intentionally relaxes the remote report's path-free diagnostic rule: useful
messages and diagnostic paths cross the existing authorized transport. Do not copy
ambient environments, locals, raw GPU bindings, credentials or lease capabilities
into control records/diagnostics, or serialize arbitrary exception attributes.

Proof: a real worker's nested failure reaches a coordinator with a different
run-store root and the text/JSON client, preserving original messages/details
without worker filesystem access. Cover serializer cause/context/group behavior,
current reports, writer-shaped legacy report/launch digest round trips, conflicting
replay, requested/applied/no-start/unreported controls and interrupted diagnostic
write retry. The fake-SLURM result route must consume the portable report too.

### R4 — Definitive No-Start Failure

The managed binding owner accounts for every selected present demand, including
kinds absent from claims. Use existing providers' actual contribution and exact
claim; no new capability registry. A missing claim or empty/unsupported contribution
cannot silently satisfy enforcement. Raise a typed actionable setup failure naming
kind, limitation/prerequisite and correction: remove the kind from `enforce`, use
`enforce: []`, or select a supporting existing execution owner. Absent/zero demand
remains not applicable; no hidden claim is created to enforce a resource.

GPU binding retains its exact ACTIVE-claim requirement after grant/activation.
Failure before any supervisor/process invocation is a proven no-start with nested
cause and unavailable/failed controls. Extend existing journal START_FAILED and
resident no-start persistence to FAILED alongside CANCELLED. The proof joins the
exact assignment/fence/grant and absence of supervisor/process start; do not trust
a worker's assertion. Persist proof so restart completes without another launch.

Local/remote outbox, coordinator terminal and release use existing owners. Accept
a proven no-start terminal event without inventing a confirmed-start event; then
record/acknowledge the result and release exact claims through existing proof.
Interrupted completion is idempotent. A potentially created process remains
START_UNKNOWN with claims withheld until existing containment/recovery resolves
it. Preserve cancellation, timeout and application suspension.

Proof: local/remote unsupported-selected CPU and missing selected binding fail
before application, expose the complete explanation, and release both agent and
coordinator ownership. Restart a durable no-start failure without launching.
An indeterminate launcher retains unknown ownership without releasing. Existing
enforce-none/supported GPU comparisons still pass with fake tokens only.

### Recovery Execution And Gates

One executor owns R1–R4 source, affected tests and feature/example documentation
within Phase 1; the manager owns planning artifacts, full gates and GitHub. Read
the original fixed contracts and this amendment; preserve others' work, do not
delegate, and return coherent commits with targeted evidence or concrete blockers.
Phase 2, rphys source, Stage 85 implementation and physical runs remain excluded.

The manager inspects test oracles and runs fresh `make validate-pr` and
`make test-summary` on the integrated stable tree. Independent implementation
review covers the entire Phase 1 diff against current develop, not only recovery.
No PR opens with known blockers. Merge after gates, record evidence and perform
exact workflow cleanup. This recovery request stops at Phase 1 completion rather
than implicitly starting Phase 2 or a physical Stage 81 experiment.

# Phase 1 Execution Plan: Pipeline Resource Accounting And Controls

## Metadata

- Status: in_progress; approved correction of the no-start persistence gap
- Roadmap stage and phase: Stage 39, Phase 1
- Manifest: `docs/roadmap/stage-39/implementation-plan.md`
- Branch: `agent/stage-39-p1-pipeline-resource-policy`
- Worktree: `stage-39-p1-pipeline-resource-policy` under the manifest's root
- Base revision: published develop `998b07c`, merged without conflicts in
  `2e4d0c9`; original approved planning packet imported from `6c1a0edc`
- PR target: develop
- PR: [#292](https://github.com/samcantrill/loom/pull/292)
- PR title: `feat(runtime): separate pipeline resource accounting and enforcement`
- Dependencies: reviewed Stage 39 plan and concrete migration approval — satisfied
- Workflow path: expanded; public options, executable schemas and cross-machine ownership
- Blockers: independent full-diff review at `f96eb105` found one verified R4
  journal/result atomicity gap. Follow-up below is approved on 2026-09-10;
  PR #292 must not merge until correction, fresh gates and review confirmation pass.

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
- Implementation: approved Phase 1 and recovery amendments implemented through
  `49799dc`; current full validation passes, independent review remains required
- Refiner: correction `1198c1a` and related repair `68a37ad` returned;
  manager verified the changes and added discriminating integration coverage
- Pre-submit: PASS on source `49799dc` against unchanged published develop
  `998b07c`; both full gates pass, no known blocker or future-phase implementation
- Independent implementation review: not started
- Blocker corrections: conservatively counted as 3/3 consumed: refiner correction,
  its separately returned repair, and manager correction `6474206`. Do not reset
  the budget by relabelling further work. Resume through a reviewed targeted
  amendment with explicit recovery scope, not another unbounded correction.
- PR and merge: #292 open, non-draft and mergeable; base develop and title verified;
  merge waits for the required independent review

## Completion Record

| Item | Result |
| --- | --- |
| Source | `49799dc5558c68520b1bd3285477989631ee14c9` against published develop `998b07c`; later lifecycle metadata edits do not invalidate this source receipt |
| Implementation | Independent pipeline accounting/enforcement; exact managed/worker handoffs; no-claim offer reuse; portable native/reported failures and truthful control/no-start evidence; bounded authenticated transport; immutable private delayed-SLURM resource preparation; dependency-neutral capture |
| Targeted evidence | Latest capture, executor, bounded report, delayed handoff, CLI and adjacent continuation selection: 115 passed (`capture-and-handoff-after.xml`) |
| Full gate | `make validate-pr` PASS: repository Ruff/Pyright, default 3,096 passed / 2 skipped / 156 deselected (1,004.93s), config-extra 162 passed / 18 skipped / 3,101 deselected (155.99s), sdist and wheel builds |
| Suite summary | `make test-summary` PASS: package 124, unit 2,179, contract 301, integration 424, e2e 70, config-extra 162; total 3,260 passed, no failures/errors, 18 opt-in skips (1,464.45s). Generated 2026-09-09T13:08:09Z |
| Evidence location | Ignored `build/resource-policy-checkpoint/{validate-pr-complete.log,test-summary-complete.log}`, `build/test-summary.md` and suite JUnit/coverage artifacts. Older failed/interrupted receipts are history, not current blockers or passing gates |
| PR, review, merge | PR #292 open to develop with approved title. Independent entire-diff review BLOCK at `f96eb105`: verified early no-start persistence gap below; no other blockers reported. No remote merge claimed |
| Residual risk / cleanup | No physical GPU/container/SIF execution, live SLURM or host changes. Eighteen opt-in skips cover container/build/resource/namespace acceptance; fake/CPU/loopback proof is not physical isolation or a scientific Stage 81 run. Preserve worktree and evidence until merge; Phase 2 and Stage 81 physical continuation excluded |

## Independent Implementation Review

Disposition: BLOCK at `f96eb105`, covering the entire Phase 1 diff against
published develop `998b07c`. The manager verified the sole product finding in
source and the existing restart oracle. No additional blockers were reported.
The passing source `49799dc` receipts remain accurate but do not prove this
earlier crash boundary. A private copy of `build/`, `.loom/` and `dist/` is retained
at `stage-39-p1-evidence-iPO6xw` under the manifest's worktree root.

R4 requires durable owner-proven no-start failure, complete nested explanation,
idempotent interrupted completion and exact release. The supported selected
resource-binding failure violates that requirement if the application stops
between these operations:

1. `SQLiteAgentJournal.start_once` catches `ManagedProcessStartError` and
   `_set_start_failed` commits START_FAILED and `start_failed = 1` alone.
2. The local dispatch or remote `execute_one` caller subsequently constructs the
   portable failed result, writes workspace evidence, and calls `record_result`.

The existing journal already has `result_json`, but the first transition does
not populate it. Local dispatch replay then raises `failed launch has no durable
diagnostic result`; remote `resume_retained_work` finds neither a supervisor launch
nor a retained result and keeps the assignment unresolved. Exact no-start proof
therefore exists while the nested failure is lost and agent/coordinator claims
remain held. The existing remote binding-failure restart test interrupts
`commit_result` only after workspace and journal result persistence, so it cannot
detect this window.

Approved targeted correction (2026-09-10):

- At the existing execution-journal owner, commit exact no-start proof and the
  portable failed-result evidence together in one transaction. Reuse its current
  result payload/codec and preserve assignment, grant/fence and process identity;
  no new store, public report schema or fabricated started event is needed.
- Make local and remote replay consume that authoritative result to repair
  workspace persistence and finish the existing terminal/acknowledgement/release
  sequence. Preserve local/coordinator result identity mapping and exact replay.
  Never synthesize a lost nested cause or relax unknown-launch containment.
- Add local and remote crash oracles immediately after the atomic no-start commit
  and before workspace-result persistence. Reopen the journal/application, forbid
  supervisor launch, and assert preserved nested cause, terminal completion,
  idempotent replay and exact agent/coordinator claim release. Keep the supported
  control, cancellation and indeterminate-launch comparisons.
- Perform manager-local correction, fresh required full gates and directly
  related confirmation by the existing full-diff reviewer. The maintainer
  explicitly approved as many necessary in-scope correctness corrections as
  required, overriding the spent count allowance. No new executor/refiner or
  full-review pass is needed for this finding. Reopen broader design only if
  evidence requires a materially different durable/public contract.

Do not merge, start Phase 2 or resume physical Stage 81 work while this finding
remains. After verified merge and cleanup, return to the approved rphys Stage 81
workflow; do not implicitly execute Loom Phase 2. Current evidence is preserved.

Correction evidence: the new local and TLS-remote post-no-start-commit crash
oracles fail on the preceding source (2 failures in `no-start-atomic-before.xml`).
The execution journal now requires the caller's failed-result projector, validates
its assignment/process identity, and commits `result_json` with START_FAILED in
one transaction. All current launch callers supply that projector. Local capture
retains worker-local diagnostic paths while mapping the result to coordinator
identity; replay maps it back only for workspace persistence. Remote replay uses
the same authoritative journal payload. No schema or table was added.

The affected journal/local saga and complete remote restart selection passes
42 tests (`no-start-atomic-after.xml`). After strengthening typed assertions,
three exact crash cases pass (`no-start-atomic-crash-after.xml`), including the
local supervisor's definitive no-root error after its launch intent is retained.
Those cases prove original nested details, no application launch on replay,
exact result identity/bytes by value, terminal completion and exact claim release.
Type checking passes (`no-start-atomic-pyright-final.log`); changed-file Ruff and
diff checks pass. Required fresh full gates and existing-reviewer confirmation
remain pending; the preceding full receipts do not validate this correction.

## Approved Recovery Amendment

The maintainer's 2026-09-09 implementation request approves the four remedies
above, this amendment, independent startup review, bounded implementation, fresh
full gates and independent implementation review before merge. This section owns
the concrete recovery contract. The original three correction passes remain
consumed, not reset. Recovery permits one scoped executor delivery and at most
one qualified correction. Stop with a concrete blocker if that allowance is
spent. No recovery implementation starts before a passing independent startup
receipt is recorded. Private helpers and slice order remain executor discretion.

Independent startup receipt: PASS at clean `5bb294908b23ce88782be0632935a38fce66aeaf`.
The single finding at `a07e290a` was the omitted local restart comparison; the
bounded correction and targeted independent confirmation resolve it through R2's
shared owner and actual restart mismatch/exact-replay oracle. No runtime validation
was claimed by this review. Recovery executor delivery is now admitted; its one
qualified implementation-correction allowance is now in progress, manager-owned.

Recovery audit at `c38994e`: the executor delivered R1 scheduling and R2 comparison
code plus a partial R3 report/R4 no-start path. Completion is not accepted. The
single scoped correction completes already-approved R2 retained-file integration
oracles, R3 portable capture/launch carrier/persistence/inspection and legacy
replay tests, and R4 actual binding-error wrapping plus local/remote restart and
terminal/release ordering. In particular, remote restart still skips a no-launch
workspace, provider exceptions can bypass definitive no-start capture, the remote
event path still distinguishes cancellation only, and no new portable capture or
client rendering is present. These are unmet R2–R4 contracts, not new scope. The
executor-reported journey results are not full gates; final evidence must name
the exact tests and preserved receipts, including a genuine remote sequential
account-none pipeline. No further executor/refiner pass is admitted by this record.

Evidence: clean tree `b94b89d` joins checkpoint `6474206` to develop `000f34f`
(PR #290). That upstream delta adds managed-lifecycle examples/tests but changes
none of these scheduling/report/runtime owners. Preserve those journeys in final
validation and leave the original dirty checkout untouched.

Current manager correction checkpoint (still one continuous correction): native
capture now preserves portable causes/tracebacks while masking credential-shaped
assignments; explicit downstream reported failures retain their opaque boundary.
Launch schema 2 carries producer-owned control records, with writer-shaped legacy
launch serialization/digest coverage. Confirmed launch controls join resident
results, including application failure, and reach coordinator attempt storage and
admission inspection. Local/remote selected-control errors preserve their cause;
exact journal/fence proof admits no-start completion and remote restart, while an
unknown launch retains ownership. Existing stores, protocol events and release
owners are reused; no new lifecycle store or provider registry was added. Local
restart wraps retained-state rejection with its native cause. The ready-stage
SLURM bootstrap now emits the same schema-2 portable report and producer-owned
SBATCH delegation evidence; legacy report replay remains unchanged.

Verified evidence before full gates: the retained `recovery-core.xml` checkpoint
contains 190 passing selected tests. Subsequent R2 local dispatch exact/conflict
cases passed (2), local restart exact/resource/policy cases passed (3), and the
complete fake-SLURM integration/assignment-unit selection passed (19), including
retained-file comparison and a native failure through report/commit/replay. Remote
interrupted diagnostic persistence now has a passing restart test that asserts
retained report bytes, held claims, nonterminal admission and repaired client
inspection. Both actual local/remote GPU environment comparisons assert persisted
applied versus not-requested control evidence (2 passed). Selected enforcement
without accounting has a passing no-claim/no-start remote restart case. The prior
20-second test timeout was corrected by interrupting at the failed-write boundary,
without changing the production 60-second indeterminate-operation retry window.
Fresh full validation and independent full-diff review are still required. These
focused results do not admit PR submission or phase completion.

### Approved Transport Amendment

Read-only public-data reproduction on `2e4d0c9` (runtime equals committed recovery
`4a81fcf` plus upstream #291) establishes a remaining R3 producer/transport gap:
`_capture_exception_details` and `_RemoteExecutionReport(schema_version=2)` accept
a three-node native cause chain, but `agent_session_transport._decode` rejects
the resulting 1,742-byte report as too deeply nested. A valid `ExecutionFailure`
detail `{"threshold": 0.5}` produces an 846-byte report rejected as an invalid JSON
value. Both are reachable current failure producers, not forged internal state.
The HTTP request handler runs this generic decoder before the report codec; its
depth-8/int-only policy prevents complete failure delivery despite the new carrier.
The passing short-chain socket-client test does not establish deeper HTTP report
delivery followed by coordinator persistence and client inspection.

The maintainer approved the targeted amendment: accept existing failure plain-data
types (including finite floats and string keys) and bounded causal/nested structure
only within declared failure payloads. One transport failure-payload validator owns
depth 512 (relative to that payload root) and collection size 256. The existing
128-node diagnostic graph can require roughly three JSON levels per causal link.
Keep the 64-KiB agent body and 1-MiB HTTP inspection-response caps, strict surrounding
envelopes, exact report schemas, authentication, legacy replay/digests and explicit
overflow errors. Generic requests retain depth 8, collection size 64 and their
existing scalar/key rules; ordinary inspection JSON retains collection size 256.
Do not flatten, stringify or silently drop failures to fit these bounds.

Current route inventory: authenticated `agent/output_manifest` and
`slurm_bootstrap/report` carry `_RemoteExecutionReport` schema 2 at `report`, with
the declared subtree at `report.failure`. Choose the exception using the exact
authenticated operation and current report version, never by finding arbitrary
keys named `failure`. Existing report and operation codecs retain semantic and
exact-field ownership. Malformed JSON, duplicate keys and non-finite values,
including numeric overflow, remain rejected with an explicit transport error.

Detailed admission inspection currently returns existing
`owners.run_result.failures` and `diagnostic_failure` through the daemon socket;
that decoder already accepts nested plain data. The separate HTTP query
`RunInspectionResult` is a closed status/location schema with no detailed-failure
field. Its shared depth checker does not justify adding a hypothetical field or
widening arbitrary response data: retain its schema and limits unchanged. Prove
the supported complete path with a real CPU worker producing at least three native
causal nodes and structured finite-float details, actual TLS HTTP report delivery,
coordinator persistence under a different root, and text/JSON admission inspection
with worker-file access forbidden. Existing HTTP query bounds/authorization tests
must still pass. If evidence identifies another existing declared failure subtree,
apply the same failure validator there; do not introduce an endpoint/schema.

Boundary checks must show accepted finite floats, string keys and near-limit
nested/collection data only within the declared subtree; genuine depth, collection
and byte overflow fail explicitly. Preserve ordinary-depth/float/key rejection,
duplicate/non-finite rejection, exact envelopes and legacy report replay. Cover
both authenticated report operations without requiring live SLURM.

The independent startup finding establishes a current producer below the limit:
`ExecutionFailure.details` with a 495-level nested mapping can be constructed and
serialized into a small valid schema-2 report, but report decoding raises
`RecursionError` inside plain-data normalization. The bounded correction therefore
includes stack-safe traversal at the existing serialization/plain.py owner for
the report/persistence freeze, thaw and plain-normalization paths. Preserve the
existing accepted scalar/container types, finite-number/key validation, immutable
copies and canonical JSON/digest behavior; do not change the interpreter recursion
limit, add a second failure serializer, or loosen unrelated protocol bounds.
Test accepted near-limit data through actual report normalization and both report
operations, not merely the JSON checker. Cover adjacent serialization behavior
and the full phase gate because this helper has multiple existing consumers.

Use the same report-bound validator on supported clients' serialized outbound
report bodies so structural/byte overflow has an actionable local explanation
before sending. The server independently validates the serialization boundary;
its fixed authentication/error envelopes remain unchanged.

Targeted independent startup review PASS at `93488a6004bd67dfded10d5786c31038156dc651`
after one bounded normalization correction. This admits completion in the manager's
existing recovery correction, not a new executor/refiner pass. Fresh full validation
and independent review of the entire Phase 1 diff remain required before PR/merge.

Implementation evidence: both exact authenticated report operations select the
failure-only validator, reused before outbound submission. Ordinary response and
query limits remain unchanged. Plain-data normalization now traverses explicitly
without consuming one Python call stack per nested level, retaining scalar/key
validation, frozen/mutable copies and canonical replay bytes. The deep conversion
test fails before the change (`plain-depth-before.xml`) and passes afterward;
the complete serialization/report/diagnostic selection passes 61 tests
(`plain-depth-after.xml`). The transport selection passes 22 tests
(`transport-amendment-after.xml`): both actual TLS report routes at depth 512,
finite/string-key/collection boundaries, rejected overflow and misplaced data,
unchanged query behavior, actual three-node native failure and worker-generated
float domain payload, retained-result/repaired-diagnostic replay, and socket text/
JSON inspection with worker files forbidden. Fake-SLURM native failure and adjacent
reported-worker handling pass two checks (`transport-producers.xml`). Type checks,
changed-file Ruff and diff checks pass. Float evidence is generated by the worker,
not placed in ordinary assignment configuration; that protocol remains unchanged.
These results admit fresh full validation, not phase completion or physical proof.

The subsequent complete default gate at `cba8d4d` reached 3,083 passes and five
failures without a stall (`validate-pr-transport.log`). Within the same open
manager correction, preserve the existing safe display projection and use one
private full-demand worker projection for preparation, retained comparison and
remote semantic checks. This fixes actual resource-attribute disclosure without
weakening replay comparison. Restore the previous top-level non-finite error
wording and give the old worker test fixture its required concrete handoff. The
105-check selection passes (`full-gate-corrections-after.xml`), including execution
models, safe-versus-private metadata, serialization, worker/report consumers and
actual retained local/SLURM exact/conflict paths. Ruff, type and diff checks pass.
The now-stale summary run was stopped gracefully before these edits; no process
remains in its group. Both final gates must be fresh after this checkpoint.

### Approved Delayed Submission Handoff Amendment

The complete default gate at `29292c8` finishes without a stall: 3,088 passed,
one failed, two skipped and 156 deselected (`validate-pr-final.log`). The supported
failure is `test_live_afterok_submitted_stage_job_materializes_worker_request_at_start[selected]`.
The selected CPU/memory request is written by `build_runtime_metadata(...).to_dict()`
as display-safe resource records. At delayed start, continuation.py's
`_stage_runtime_metadata` passes those records to `ResourceRequest.from_dict`,
which correctly rejects `attribute_count` as an execution-resource field.

This is a lossy-owner mismatch, not just a renamed field. Two current GPU requests
with different `fabric_group` values produce different private worker handoffs but
identical safe summaries. Replacing every count with empty attributes would erase
accepted demand. Reverting the safe projection would expose values through the
existing public display API. The immediate/local/managed preparation and retained
comparison routes now use the private full projection correctly; delayed afterok
preparation has no saved worker yet and only reads `runtime.json`'s safe summary.
The existing prepared-run record is also an artifact-safe summary/ref contract,
not an authoritative complete invocation; whole-run continuation already reports
insufficient prepared state. Neither current defaults, recomposed configuration
nor the outer SLURM allocation can safely stand in for the missing inner intent.

Maintainer approval admits this targeted amendment and one independent startup
review, followed by manager-local implementation after a pass. It does not reset
the executor/refiner budget or authorize Phase 2/physical execution.

The existing SLURM generated-artifact directory owns one private preparation
document, `slurm/submissions/<planning_id>/execution-resources.json`. Neither
`runtime.json`, the artifact-safe `PreparedRunRecord`, nor public planning/live
manifest summaries gain raw resource attributes. This document is execution
input, not a lifecycle store or another complete invocation format. Its lifetime
is that of the existing submission directory; it contains only resource intent,
not environment, adapter payloads, credentials, or new lifecycle state.

- Producer: `plan_afterok_slurm_dry_run` accepts optional keyword-only
  `stage_runtime: Mapping[str, ResolvedStageRuntimeOptions]`. CLI dry-run and live
  afterok paths pass the actual resolved runtime options (including programmatic
  overrides), before reducing them to display metadata. Resolve concrete selection
  once with the existing direct effective-demand owner. Save exactly the RUN job
  stages; require their complete coverage and matching stage identities. Outer
  `stage_resources` remains the separately mapped SLURM allocation authority.
- Durable schema version 1 has exactly `schema_version`, `run_uri`,
  `manifest_relative_path`, and `stages`. Each stage value has exactly `resources`
  (full normalized request), `resource_policy` (both resolved axes), and
  `resource_selection` (both exact sorted lists). The run URI, existing immutable
  manifest path/planning ID and stage name bind its execution identity. Existing
  resource codecs and selection comparison own semantic validation; no downstream
  target imports, factories or configuration instantiation are added.
- Publication precedes script/manifest publication and any scheduler call. Use
  atomic create-if-absent at the existing store-owned generated-artifact path;
  retain exact bytes on identical preparation, reject changed content for the
  same identity before overwriting anything. Existing live preparations missing
  this file must not be silently retrofitted. New files are owner-readable/writable;
  private means excluded from public summary projection, not a new security service.
- Consumer: `_materialize_submitted_worker_request_if_needed` uses the already
  validated submitted-operation manifest path to read this document, verifies
  schema/run/path/stage identity, and copies the saved three fields over the
  existing safe non-resource stage metadata. It never reconstructs resources from
  display counts, outer allocation, a recomposed config or new defaults. Existing
  stage-spec/input reconstruction is unchanged; complete whole-run continuation
  remains unsupported. Once a worker request exists, its current exact replay
  path remains authoritative and does not rewrite or require a new preparation.
- Missing, malformed, incompatible or conflicting handoff fails before worker
  materialization/launch, with a preserved cause and guidance to finish in the
  pinned original runtime or prepare a fresh execution identity. Legacy summaries
  and manifests remain inspectable with unchanged schemas and bytes. Omitting the
  new optional argument still permits dry-run inspection/submission planning,
  but cannot establish executable delayed reconstruction; document this limit.

Private helpers and module layout are implementation discretion. Reuse existing
local generated-artifact path and atomic-write utilities; no new public store
method, registry, generic snapshot API, public manifest schema, or implicit upgrade.

Independent targeted startup review PASS at clean `c5b23a7a72e05babb812a8cc7035500db8013605`.
No qualified finding or plan correction; manager-local implementation admitted.

Implementation receipt: one private execution helper owns version/identity,
semantic reading and atomic create-if-absent publication at the existing generated
artifact path. Afterok planning supplies exact RUN-stage runtime; both CLI branches
pass resolved invocation options. Delayed continuation reads the validated registry
reference before materialization and preserves original causes on refusal. Saved
workers bypass new preparation entirely. No display schema or other store changed.
Targeted afterok, dry-run, stage-job/prepared-run continuation and CLI selection:
37 passing checks in `delayed-handoff-after.xml`; its remaining CLI fixture setup
failure was corrected and that exact check passes separately (1 passed, 1.15s).
The CLI test uses an in-process authority with admission/readiness bypassed and
fake sbatch; it proves preparation/override wiring, not multi-host authority support.
Type checking passes (`delayed-handoff-pyright.log`). New evidence includes full GPU
attributes with CPU-only accounting, distinct outer CPU allocation, interrupted
first preparation followed by byte-identical worker replay with handoff rereads
forbidden, safe summaries, invalid version/identity/selection, missing legacy,
no retrofit, exact private bytes/timestamp, incomplete coverage and conflict refusal.
The earlier failed full receipts are superseded only when fresh full gates pass.

Required proof for that amendment: actual delayed start with nonempty resource
attributes and runtime overrides preserves exact resources/policy/selection;
safe summaries omit attribute values; exact replay preserves bytes/identity;
missing or incompatible private state fails actionably before launch. Include
different outer allocation, retained same-identity conflict, and CLI preparation
coverage so the test cannot pass with a test-only producer. Reuse the
existing afterok, preparation and retained-worker harnesses, then fresh full gates
and the still-required full Phase 1 independent review. The transport amendment's
startup pass does not review this new durable-owner decision. Runtime edits wait
for the now-approved targeted startup review; full Phase 1 review remains separate.

The completed separate summary corroborates this finding. At `29292c8`, package
(123), unit (2,179), contract (301) and e2e (69) suites pass; integration has 418
passes/one failure, and config-extra has 160 passes/two failures/18 opt-in skips.
The two optional failures are stale `resource.ignored` assertions in the existing
CLI preflight and resource-preflight example tests, not different runtime defects.
They now assert the accepted empty-enforcement `resource.not_requested` code while
retaining WARN and strict-exit checks; both pass (`optional-policy-expectations.xml`,
3.78 seconds). `test-summary-final.log` and `build/test-summary.md` retain the full
failed-gate evidence. Source remains `29292c8`; only those test expectations and
current phase status change afterward. The phase worktree and logs are retained;
no PR, full-diff review, merge, physical execution or cleanup was attempted.

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

At local `_execute`, `_dispatch_slurm_ready` and restart
`_reconcile_retained_local_assignment`, compare decoded retained full normalized
demand, concrete policy axes and saved selection with
`_worker_runtime(intent, stage_name)` before input delivery or launch. Use canonical
plain data so tuple/list or immutable-map differences are not false conflicts.
Use one comparison owner shared by these entry points; `resume_retained_local_work`
must not bypass it by going directly to reconciliation.
Keep identity and internal codec checks. This is Loom handoff validation, never
downstream factory/dataset/model instantiation. Name the disagreement and advise
investigating retained input or preparing a fresh identity; do not overwrite it.

Proof uses actual retained files on local scheduling, ready-stage SLURM and local
application-restart routes: an internally consistent resource handoff mismatch is
rejected before delivery/supervisor invocation without changing bytes or timestamps,
while exact replay (including restart) succeeds. Codec-only mismatch tests are
insufficient.

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

Manager pre-submit correction: the first capture implementation imported the
higher-level diagnostics package from five execution owners, contrary to
`docs/structure.md`. The new package-boundary check reproduces that violation
(`capture-boundary-before.xml`). Move the existing projector/capture functions
without algorithm changes into private `serialization._diagnostic_capture`;
keep the diagnostic facade, renderer, public error identity and v1 bytes intact.
This resolves implementation layering within R3, not a new format/behavior choice
or exception hierarchy. Both running full gates at `ecfeb46` were stopped before
source edits and their exact process groups exited; their interrupted receipts
are not validation passes. Fresh capture/renderer, executor, both bounded TLS
report operations, delayed afterok, CLI and adjacent continuation selection passes
all 115 tests (`capture-and-handoff-after.xml`, 18.33s), including the new import
boundary. Changed-file Ruff and diff checks pass. Fresh full gates remain required.

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
share this contract; enclosing database versions stay unchanged. Existing byte and
ordinary-envelope bounds apply; the Approved Transport Amendment owns recognized
failure-subtree structural rules. Overflow is actionable, never silently truncated.

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

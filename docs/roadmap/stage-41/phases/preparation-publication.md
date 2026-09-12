# Phase 1 Execution Plan: Preparation And Publication

## Metadata

- Status: merged
- Roadmap stage and phase: 41 / 1
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: agent/stage-41-p1-preparation-publication
- Stage worktree and coordination branch: from the manifest Execution Context;
  all phases share that stage worktree through synchronized closeout.
- Base revision: `ae1470149e84f679933ee3ec9765888556f78e67` (published develop with Stage 40 and plan PR 307)
- PR target: develop
- PR title: Stage 41 Unified Run Lifecycle And Agent Execution - Phase 1: Preparation And Publication
- Dependencies: Published Stage 40; Stage 41 plan and nine-phase split approved on 2026-09-10
- Plan approval: maintained behavior and nine-phase structure approved on 2026-09-10
- Workflow path: expanded for this card's public/durable/ownership boundary; retain the reviewed contracts
- Blockers: none; reviewed packet published and stage-worktree startup verified

## Objective And Context

Prepare exact invocation intent and publish a truthful, replayable target through the selected authority.

Stage 40 supplies assigned preparation in an installed environment. This phase extends that existing publication journey, proving preparation-to-prepared-receipt through both supported authority families. Phase 2 adds automatic admission; Phase 3 adds service startup.

Requirements: FR-41-07/08; supporting FR-41-01/09/13. Design: DQ-41-04.
Validation ownership: VAL-41-01 (state/reuse), VAL-41-07.

## Current Source And Harness

- Published `queue/preparation.py::{PrepareRunRequest,PreparationChildInput}`, `loom/preparation.py::{PreparationStage,CoordinatorPreparation}` and `queue/_preparation_operations.py::{CoordinatorPreparations,_configuration}`: strict invocation/report boundaries and retained selection.
- `src/loom/queue/managed_local_preparation.py`, `local_daemon_runtime.py`: exact composed publication, runtime requirements and current Slurm/authority exclusions.
- `src/loom/pipeline/stores/coordinator_authority.py`, `src/loom/queue/coordinator_authority.py`, authority repositories/routes: creation, transitions and authenticated access.
- `src/loom/pipeline/runtime/options.py`, `pipeline/status.py`, scheduler/readiness consumers and `cli/options.py`: invocation semantics and lifecycle transitions.
- Existing managed preparation, runtime options, coordinator authority and all-reuse/planner tests; source/report limits remain authoritative. Published #305 adds the same-URI publication lock and explicit admission retry; preserve its supported behavior and update retry pre-start status with this phase.

## Scope

Own immutable overlays/overrides/run options, selected-authority creation/publication, Slurm-profile preparation validation and correct pre-execution status. Change the transition/readiness consumers with their publication owner. Service startup, automatic run admission and backend execution changes belong to later phases.

Assume the predecessor's accepted contracts and existing qualified installations.
Each phase includes its code, owner-level tests, current docs and replaced-code
removal. Preserve unrelated work and current scientific/resource meaning.

## Implementation Walkthrough And Examples

### What changes and why

Preparation answers: which exact experiment will Loom execute? The existing
publisher accepts checked composition, but currently rejects configured Slurm
profiles/non-embedded authority and initializes an embedded target as RUNNING.
This phase extends that publisher and its authority boundary, rather than adding
another preparation engine. A prepared target must describe the work faithfully
before any of its pipeline stages execute.

The following Python-shaped example shows the planned request fields, including
the Stage 41 extensions. It is an illustrative target API example, not executable
against the current checkout; profile/root aliases require protected deployment
configuration. Constructors and internal helpers are not newly fixed by examples.

```python
from loom.coordinator import PrepareRunRequest

preparation = PrepareRunRequest.from_dict({
    "operation_id": "run-demo-001",
    "run_name": "demo-001",
    "source": {
        "mode": "shared",
        "root": "projects",
        "path": "demo",
        "include": ["configs"],
    },
    "config_path": "configs/experiment.yaml",
    "preparation_profile": "project-python",
    "overlays": ["configs/site.yaml"],
    "overrides": ["model.width=64"],
    "run_options": {
        "selectors": {"force_stages": ["train"]},
        "tags": {"experiment": "demo"},
    },
})
```

This only constructs intent. It does not call prepare-only and then reuse that
accepted operation as a different kind. Phase 2 can submit this request as part
of a run; a separate prepare-only invocation uses its own operation identity.

### Preparation-to-publication handoff

An eligible agent composes/checks the captured inputs in an existing installed
environment. It returns the exact checked composition and execution requirements.
The coordinator publisher persists those values and their provenance without
composing them again. Source capture provides preparation inputs; it does not
install the project or deliver arbitrary target-stage code/data.

Publication creates/transitions the target through its selected authority.
Embedded storage and authenticated authority are two implementations of that
boundary. Runtime coordinator logic must not construct a convenient replacement
database when the configured authority is unavailable.

```text
CREATED
   | checked target published
   v
PLANNED
   | first confirmed pipeline-stage execution
   v
RUNNING
   | execution and accepted results resolve
   v
terminal outcome
```

This is the target run's state, separate from the preparation operation and its
managed child. A reuse/skip-only target can terminalize without RUNNING. Changing
only a CLI label would leave readiness and transition consumers inconsistent;
update those owners together.

### Contracts illustrated

If publication succeeded but its response was lost, replay returns the same
prepared target. It must not recompose modified files or allocate another run.
Changed accepted intent conflicts. The VAL-41-01/07 checks below prove this
publication behavior, truthful state, authority-family support and preservation
of invocation controls. Preparation stops at its receipt in this phase; automatic
admission belongs to the [durable run operation](durable-run-operation.md).

## Fixed Contracts And Private Discretion

Extend Stage 40 preparation with ordered `overlays` (captured relative files),
ordered `overrides` (existing config strings), and sparse serializable
`run_options` using the current RunOptions composition/precedence rules. Persist
them in accepted intent and provenance. Preserve selectors, reuse, reliability,
timeouts, resources, tags/notes and plugin identity at their existing validators.
Reject obsolete executor/adapter inputs explicitly; never silently drop controls.
RunOptions validator registries/live closures are not serialized runtime inputs.

One publisher consumes the checked composition once. Add the required create/
publish operation to the selected embedded or authenticated authority boundary;
keep backend database construction out of runtime coordinator adapters. Prove
replay after publication/authority partial failure. Preserve Stage 40 source,
installed-code and report limits; this does not deploy the project's code/data.

Create the target run as CREATED, publish it as PLANNED, and move to RUNNING on
first confirmed executing-stage evidence. Queued/admitted is not RUNNING. A
reuse/skip-only plan can reach terminal status without a worker. Update authority
transition/readiness consumers together, preserving expected revisions/fences.

### Invocation and retained publication bindings

Extend the native request and `PreparationChildInput` together. Keep ordered
overlays relative to the selected captured project and require every overlay and
composition dependency inside the explicit source closure. Overrides keep their
order; sparse run options retain omission versus explicit values through durable
encoding. Use the existing config/runtime merge precedence in the qualified
preparation environment before preflight. The report and publisher consume that
same effective intent and its provenance; a coordinator-side merge after checks
must not change the checked experiment. Update exact-field decoders and version
decisions at the affected boundaries, including shared and staged inputs.

Preparation-profile runtime options govern only the internal child. Target
resource/reliability/selectors/tags/notes come from the target's effective options.
Keep the current single qualified preparation installation contract; target
execution profiles must satisfy its checked software requirements. Selecting a
Slurm target route does not move the preparation child into Slurm. Capture fixes
file bytes when `input_receipt` is recorded; acceptance alone is not an atomic
snapshot of a mutable directory. Captured inputs do not deploy code or datasets.

Retain selected authority identity and target profile descriptors/revisions with
accepted preparation alongside the existing source/profile/scheduling snapshot.
Resolve protected implementations with matching identities on replay; never store
live factories or credentials in public results. Replace `_configuration`'s forced
embedded authority and empty Slurm profiles. Route both child and target creation,
report lookup, fresh publication and replay through the selected authority.
Unavailable or changed owners leave explicit retained uncertainty/conflict; they
cannot substitute embedded storage or current mutable profile settings.

Preserve the publisher's existing per-run POSIX lock, retained lock inode and
partial/corrupt-target conflict behavior. Qualified storage must support that
cross-process advisory lock. Add idempotent selected-authority creation/publication
at its narrow coordinator interface, including exact lost-response replay. A
partially written local target remains an inspectable conflict; an unknown reply
from an idempotent authority operation is reconciled with the original identity.

The pre-start status rule also covers #305 explicit failed-admission continuation:
return released failed work to PLANNED under the existing RESUME intent and move
it to RUNNING only on confirmed new execution. Update the lifecycle transition
owner with the embedded retry authority. Preserve the exact failed-revision guard,
attempt history, cancellation/fence checks and retry receipt; ordinary replay
does not authorize retry. Authenticated-authority retry remains unsupported.

### Delivery boundary

A prepared receipt is the complete outcome here. Preparation-only remains terminal at publication. Slurm-targeted plans can be validated/published, but this phase does not enable a new dispatch route or claim the later agent-owned Slurm journey. Unsupported source/environment combinations still fail explicitly.

### Cross-phase handoff

Phase 2 consumes the exact prepared receipt and immutable invocation intent; Phase 5 consumes the checked Slurm profile requirements. Keep the existing prepare-only operation kind and projection bounds unchanged. Reconnecting reconciles unchanged intent; changed experiment configuration is a new run, and checkpoint recovery remains project-owned.

### Removal owned here

Remove the superseded unconditional embedded/RUNNING initialization and family rejection branches only when their replacements are covered. Delete abandoned publisher helpers with no remaining consumer; preserve pure composition/planner primitives.

Private helper names, local wiring and intermediate representations remain
implementation discretion. Public behavior, durable identity, trust, failure and
cross-phase meanings above are fixed. No compatibility aliases or state resets.

## Proportionality

Extend one publisher and selected-authority boundary. Reuse Stage 40 capture/composition/report schemas and current RunOptions validation. No extra preparation store, environment installer, recomposition path or scientific substitution.

## Invariant Ownership

| Invariant | Owner | Reachable boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Exact preparation intent | Preparation request/composition owner | Overlay/override or same-ID retry changed | Different experiment under one identity | VAL-41-07 immutable provenance/conflict |
| One selected-authority publication | Publisher and authority create/transition boundary | Transport loss or partial publication | Duplicate/partial target or wrong store | VAL-41-07 embedded/authenticated replay |
| Truthful pre-start state | Authority transitions and readiness consumers | Preadmission publication or reuse-only plan | False running state or stalled completion | VAL-41-01 CREATED/PLANNED/start/all-reuse |

## Implementation Slices

1. Reconcile Stage 40 publication source and extend immutable invocation controls with existing validators and provenance.
2. Route create/publication through the selected authority; cover partial failure and same-ID replay through both supported families.
3. Change lifecycle/readiness transitions together, cover all-reuse and queued cases, and enable checked Slurm-profile preparation without new dispatch.
4. Remove replaced publication helpers/rejections and update preparation/API documentation with the delivered family and state semantics.

## Test And Validation Plan

| Suite | Obligation | Minimal evidence |
| --- | --- | --- |
| Package/contract | Required | Optional imports stay inert; preparation controls, provenance and native receipt shape preserved. |
| Unit | Required | Changed intent conflicts; exact option precedence; CREATED/PLANNED/RUNNING and reuse-only transitions. |
| Integration | Required | Embedded/authenticated publication, partial failure/replay, Slurm-profile preparation, one target receipt. |
| Live deployment | Deferred to owner | No new real scheduler/container claim; later execution phases own qualification. |

Target existing source-mirrored tests and add focused assertions where the new
contract requires them. Resolve predecessor-renamed test paths at preparation.
Run optional-runtime commands only with their qualified environment. A local
fixture is not live-site evidence; record missing qualification explicitly.

    uv run --extra config pytest tests/unit/loom/queue/test_managed_local_preparation.py tests/contracts/test_runtime_options_contract.py tests/contracts/test_local_daemon_authority_contract.py tests/integration/authority/test_coordinator_authority_api.py

Extend the existing preparation operation/shared/staged fixtures with these
discriminating cases: ordered overlay/override and sparse-option precedence reaches
both preflight and the published target; child resource settings do not replace
target settings; restart preserves authenticated-authority and Slurm profile
bindings; identical concurrent publication produces one receipt; changed/partial
targets still conflict; queued and explicitly retried work remains PLANNED until
confirmed execution. Reuse existing child, report-bound and installation checks.

    uv run --extra config pytest tests/integration/queue/test_preparation_operations.py tests/integration/queue/test_staged_preparation_lifecycle.py tests/integration/queue/test_preparation_child.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py

Final implementation gate; reuse a fresh receipt only while relevant code,
tests, dependency/build and validation configuration remain unchanged:

    make validate-pr
    make test-summary

Do not repeat complete backend/fault matrices in consumer phases. Expand tests
only for changed shared contracts, new failures or a remaining accepted concern.

## Risks, Review, And Stops

Stop for a published Stage 40 conflict or an accepted invocation control that cannot survive the process/publication boundary. A root reset or silent control drop is not a remedy. Missing installed environments remain explicit readiness failures.

## Executor Handoff

Read planning.md Behavior Baseline, the requirement/design/validation IDs above,
this whole card and the actual published predecessor contracts. Implement the
listed slices within the stated ownership. Do not reopen agreed lifecycle,
grant-before-start, sole submission/finalization ownership or hard cutover.
Manager action is for a demonstrated public/durable or accepted-behavior conflict,
not private helper choices. You are not alone in the codebase; preserve others' edits.

## Workflow State

- Manager preparation: startup passed on 2026-09-12 in the manifest's persistent
  stage worktree, on this card's phase branch. Phase 1 is in progress.
- Publication: plan PR 307 merged as the Base revision above; its tree
  `ecc307c1af9fccb471dcedacd203d7278926f271` exactly matches the validated packet.
  Stage 40 implementation and closeout are present in that published base.
- Startup checks: `tools/phase_workflow.py setup` and `preflight` passed before
  review/writes. The phase, coordination, local develop and origin/develop refs
  matched the published base, with a clean stage worktree. All nine cards are
  published and pending; no relevant source or workflow drift from the reviewed
  evidence base. The manifest's independent pass is reusable.
- Named refinement: none needed. Scope, contracts, source/test references,
  merge boundary, private discretion and required validation remain current.
- Startup evidence: documentation and Git checks only; subsequent changes only
  record these startup facts. Keep this receipt with the future Phase 1 PR.
- Planning review: original accepted contracts retained; 2026-09-12 published-source amendments and current readiness receipt are owned by the manifest Quality Gate
- Implementation: complete and merged under the 2026-09-12 whole-stage execution request
- Refiner: not used
- Coverage selection: invocation request/capture/child/report/publication, selected
  authority identity and principal binding, retained Slurm profiles, native readiness,
  first confirmed execution and explicit failed-admission retry. Existing
  managed publisher/authority/preparation suites are selected, with added shared
  and staged sparse-intent cases, exact option precedence/resource separation,
  authenticated lost-response/partial-publication cases, owner/profile restart
  refusal and recovery, and worker-free skip/reuse completion. Changed shared
  lifecycle/authority contracts retain both required full gates. Expand only for
  relevant failures or remaining accepted evidence gaps.
- Format decision: child input/report version 2 and `preparation-input-v2`;
  coordinator root 14 rejects old preparation intent before mutation. Shared/staged
  input receipts, result projection and worker-root formats remain unchanged.
- Executor validation: complete; both required commands exited 0. Independent
  phase review and remote delivery also passed.
- Validated implementation: `767a139f47b5c181ba92c761b9e49b07fb6f45ce`, tree
  `5481f01c1efc95701bc4f7836a12627dae0ebb82`. Subsequent changes record workflow
  evidence and PR identity only.
- Required `make validate-pr`: final run exited 0; Ruff and Pyright passed;
  baseline 3333 passed, 2 skipped, 253 deselected; config-extra 223 passed,
  18 skipped, 3374 deselected; MCP-extra 36 passed, 3552 deselected; wheel and
  sdist built. Log: `/tmp/loom-stage41-p1-validate-pr-final.log`.
  It started at `f3a4c1703a4501b077cb0f8fe7bb4bc3dab1c900` (tree
  `7c4cb1d8a962c6e9bd234bc7e7fe25f9113c1711`). Later commits were rollout
  prose (`c8b50ae`) and the normalized-default MCP assertion (`767a139`),
  both present before their affected test collection. The changed assertion
  passed focused Ruff and all 21 MCP contract tests, then the full MCP gate.
  Runtime source and executable example stayed unchanged throughout this run.
- Required `make test-summary`: exited 0; 3594 passed, 18 skipped, no failures or
  errors across package 127, unit 2329, contract 301, integration 508, e2e 70,
  config-extra 223 and MCP-extra 36. Report: `build/test-summary.md`; JUnit and
  coverage: `build/test-summary/`; log: `/tmp/loom-stage41-p1-test-summary.log`.
  The summary and seven JUnit reports were preserved before successor validation
  at `/tmp/loom-stage41-p1-summary-evidence/`; later phases reuse the build paths.
  Started after `d8be797` (tree `fb55c78626fd340438243620e13e4a6531093300`):
  package collection 07:56:30+10 followed that commit at 07:56:27; the corrected
  example at 08:10 preceded e2e collection at 08:22:38; rollout prose at 08:13
  preceded config-extra collection at 08:26:52; the MCP assertion at 08:25
  preceded MCP-extra collection at 08:38:39 (all 2026-09-12). Thus later changes
  were covered by the affected summary suites; no summary restart was needed.
- Earlier evidence is qualified: initial `make validate-pr` started at `6ec24c3`
  (tree `231c4b3ed8a09498bfc492f73dec4aa99ebb8189`) and overlapped the embedded
  interruption correction, so it is not a corrected-revision receipt. It exited
  2 with one stale example-import failure, 3330 passes, 2 skips and 253
  deselections (`/tmp/loom-stage41-p1-validate-pr.log`). The supplemental remaining
  components passed config-extra but failed the stale MCP expected payload;
  that command did not replace the required full command. Both failures were
  corrected before their passing final selections.
- Focused correction checks: managed-local publisher plus authority API suites
  passed 24 tests; both missing-authority and CREATED-only local interruption
  variants passed with bytes/mtime/ctime unchanged on retry; the isolated
  Slurm-example e2e passed; MCP contracts passed 21 tests. Post-correction
  Pyright reported zero errors; affected Ruff and `git diff --check` passed.
- Pre-submit gate: passed. Manager reviewed accepted scope, invocation and
  publication/lifecycle boundaries, affected tests, current consumers, removal,
  validation logs and summary/JUnit timing. Required results reconcile to
  `767a139`; subsequent changes only record workflow evidence. No outstanding
  product blocker or future-phase implementation was found.
- Independent implementation review: passed on PR 308 at
  `4983595b79c103ee38c568d6847d1b5a778b4b24`, with no product blockers, localized
  corrections or workflow issues. The reviewer verified actual PR identity,
  accepted contracts, affected assertions, logs/JUnit timing and metadata-only
  deltas. The PR body retains the reviewed-head receipt; local validation was
  reconciled to that same head.
- Blocker corrections: 1/3. Manager regression reproduced interrupted embedded
  authority publication repairing a partial local target. Embedded replay now
  opens only completed publication; missing or CREATED-only authority remains a
  non-mutating conflict. Authenticated lost-response reconciliation is retained.
  Both local fault variants and selected-authority publisher coverage pass.
- Full-gate correction: the baseline found the executable fake-Slurm example
  still importing the removed initializer. Its script and invocation manifest now
  use selected embedded PLANNED publication; the isolated e2e passes. The initial
  `make validate-pr` failed (3330 passed, 2 skipped, 253 deselected, one failure).
  The fresh required command passed on the corrected tree as qualified above.
- PR: [308](https://github.com/samcantrill/loom/pull/308), squash-merged to
  `develop` as `c133d1798a73d3a4e8903527aa813a70b7659091` on 2026-09-12.
  Delivery verified the canonical title/base/head, required local gates and
  independent review before merge, then confirmed the remote outcome and
  retired the remote branch at the reviewed SHA.
- Post-merge transition: all phase agents and validation processes finished;
  the shared gate entered `agent/stage-41` and synchronized stage/control/live
  develop to the verified merge. Completion metadata was published from
  coordination as `383e9d473f479516db892f135693dd282100d526`; final synchronization
  verified stage/control/fetched/advertised equality before Phase 2 startup.
  The exact reviewed local phase branch was then retired, with the persistent
  stage worktree retained. No unknown or unrelated ref was removed.

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Implemented invocation request/child/report propagation; selected-authority publication/principal binding and retained profile recovery; truthful lifecycle/retry transitions; current preparation/operations docs. Source and related tests are in this phase branch. |
| Tests added, updated or intentionally removed | Added ordered/sparse immutable invocation and closure checks, checked/published resource separation, embedded/authenticated state and lost-response/partial-authority replay, authenticated Slurm-profile restart recovery, and worker-free skip/reuse completion. Updated existing metadata, format and retry assertions. |
| Validated revision/tree and evidence | `767a139f47b5c181ba92c761b9e49b07fb6f45ce`, tree `5481f01c1efc95701bc4f7836a12627dae0ebb82`; both required full commands exited 0 with exact timing and totals above. |
| Validation-relevant changes after evidence | Workflow evidence and PR identity only; runtime/example, MCP assertion and rollout prose are covered as qualified above. |
| Replaced-code removal / retained primitive consumers | Removed forced embedded/empty-Slurm recovery and unconditional RUNNING initializer; managed publication uses selected authority. Replay retains its original persisted plan; pure composition and planning remain fresh-publication owners. Embedded-local facade restrictions remain its explicit supported scope. |
| PR, review and merge | [PR 308](https://github.com/samcantrill/loom/pull/308); independent pass at `4983595`; merged as `c133d1798a73d3a4e8903527aa813a70b7659091`. |
| Residual risk and cleanup | Physical fleet/NAS/Slurm and container qualification remain unavailable locally; fake-Slurm and local authenticated/shared/staged fixtures are not physical qualification. The 18 opt-in skips comprise 13 Apptainer timeout/namespace cases and 5 Docker/Apptainer smoke/build/resource cases. Existing monitor tests emitted unawaited-coroutine warnings without failures. No external workload or sidecar was launched. Build/report artifacts remain ignored. Exact remote/local phase branches retired after verified merge and metadata synchronization; stage worktree retained for Phase 2. |

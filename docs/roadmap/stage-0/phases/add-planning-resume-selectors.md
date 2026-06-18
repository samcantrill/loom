# Phase 8 Execution Plan: Planning, Resume, And Selectors

## Metadata

- Status: pr_open metadata recorded in phase branch; manager mirror pending in control checkout
- Branch: `codex/add-planning-resume-selectors`
- PR: https://github.com/samcantrill/loom/pull/12
- PR title: `Phase 8: Planning, Resume, And Selectors`
- PR body artifact: `docs/roadmap/stage-0/phases/add-planning-resume-selectors-pr-body.md`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-planning-resume-selectors`
- Phase execution plan path: `docs/roadmap/stage-0/phases/add-planning-resume-selectors.md`
- Full plan: `docs/roadmap/stage-0/implementation-plan.md`
- Source phase: `Phase 8 - Planning, Resume, And Selectors`
- Stack predecessor: none; Phase 7 has landed in `develop`.
- Base branch: `develop` at `bafe79261f8b6a7303a36ba8d3a9b5039a9d4728`
- Target branch: `develop`
- Merge eligibility: root phase PR after stack maintenance; PR #12 targets `develop` and the recorded Phase 8 `from_stage` PR review blocker has been fixed with validation rerun. Merge only after human approval and current checks; do not delete the branch while Phase 9 PR #13 depends on it.
- Successor dependency notes: Phase 9 PR #13, branch `codex/add-local-execution`, depends on this branch. Keep this branch until Phase 9 is retargeted or rebased away from it.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no blocking findings remain in the canonical v0 plan.
- Plan quality gate loop budget: initial review used, automated plan refinement pass used, confirmation review used. Do not rerun or consume the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time.
- Refine pass: completed by `loom_phase_planner` on 2026-05-04 local time.
- PR body draft pass: completed by `loom_pr_preparer` in commit `0f9c581`.
- PR body refine/open pass: completed by `loom_pr_preparer` on 2026-05-04 local time.
- PR verification: initial stacked verification was `{"baseRefName":"codex/add-local-stores-run-layout","headRefName":"codex/add-planning-resume-selectors","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/12"}`; after Phase 7 landed, stack maintenance retargeted PR #12 to `develop` with head `codex/add-planning-resume-selectors`.
- PR validation evidence: after the user-authorized post-review blocker fix, `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed with Ruff, Pyright, default pytest `333 passed`, and build succeeded; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with package 24, unit 278, contract 15, and integration 16 passed and e2e not present. GitHub CI check `checks` completed with conclusion `SUCCESS` after the blocker-fix push.
- Setup limitations: `gh auth status` initially reported an invalid token inside the sandbox, then succeeded with approved network access. `gh auth setup-git` and `git fetch origin` completed with approved access. The first sandboxed `git worktree add` could not create the branch ref under the control checkout `.git` directory and was rerun with approved filesystem access. No validation commands were run in the planning passes.
- Blockers: none.

## Objective

Implement deterministic execution planning without invoking stage targets. This phase creates the planning surface that computes stage fingerprints, binds current inputs, applies selectors, inspects same-run-directory state through the Phase 7 stores, decides `RUN`, `REUSE`, `SKIP`, `STALE`, or `BLOCKED`, explains those decisions, propagates downstream invalidation, and persists computed plans through `RunStore.write_plan`.

The phase must stay conservative: reuse requires a prior `SUCCEEDED` stage with a matching fingerprint, valid `outputs.json`, required artifacts that exist, and checksum verification when local readable checksums are present. Interrupted, corrupt, stale, failed, partial, or unverifiable state must not be treated as reusable.

## Full-Plan Context

Phases 1 through 6 are merged and provide the typed package skeleton, primitives, serialization, I/O/codecs, trusted config composition, recipes/instantiation, static pipeline specs, graph helpers, stage context, status records, and strict `stage.output` bindings.

Phase 7 is open as PR https://github.com/samcantrill/loom/pull/11 and provides the local artifact/run stores and inspectable run layout. This Phase 8 branch stacks on that Phase 7 branch so it can use `ArtifactStore`, `RunStore`, `LocalArtifactStore`, `LocalRunStore`, artifact indexes, status files, `plan.json`, stage inputs, outputs, and fingerprints.

Phase 8 is the pure planning and resume policy layer between persistence and execution. Phase 9 will later invoke targets, validate returned outputs, drive lifecycle status writes, and use the planner's output. Phase 10 will harden errors, interrupted-run behavior, docs, and extension contracts after the local runner exists.

Future-phase work that must remain out of scope includes actual stage execution, `PipelineRunner`, `LocalExecutor`, lifecycle transitions, target instantiation, CLI parsing or command behavior, subprocess/SLURM/distributed executors, remote stores, run catalogs, cross-run cache reuse, conditionals, rich runtime option models, and domain-specific checkpoint resume.

## Stack Context

- Root or stacked phase: stacked phase.
- Current predecessor branch or PR: none. Phase 7 PR #11 has landed in `develop`.
- Why this base branch is correct: Phase 8 depends on the Phase 7 run/artifact store contracts, and those contracts are now present in `develop` after the Phase 7 squash merge.
- Retarget/rebase plan after predecessor merge: completed on 2026-05-04 local time. This branch was rebased onto `origin/develop` at `bafe79261f8b6a7303a36ba8d3a9b5039a9d4728`, pushed with `--force-with-lease`, and PR #12 was retargeted to `develop` with the GitHub REST API after `gh pr edit --base develop` hit the known Projects Classic deprecation GraphQL error.
- Branch cleanup constraints: do not delete this branch until successor stack state is recorded or confirmed clear.

## PR Preparation And Open Metadata

- PR preparation/open pass: completed on 2026-05-04 local time from worktree `/home/samcantrill/work/loom-worktrees/add-planning-resume-selectors`.
- Branch/head: `codex/add-planning-resume-selectors`.
- Initial target/base: `codex/add-local-stores-run-layout`.
- Current target/base after stack maintenance: `develop`.
- Stack predecessor: none after Phase 7 landed.
- Predecessor verification: Phase 7 PR #11 was verified as `OPEN` with base `develop` and head `codex/add-local-stores-run-layout` before opening this PR.
- Branch push: `git push -u origin codex/add-planning-resume-selectors` succeeded.
- PR URL: https://github.com/samcantrill/loom/pull/12
- PR metadata verification: initial stacked verification was `{"baseRefName":"codex/add-local-stores-run-layout","headRefName":"codex/add-planning-resume-selectors","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/12"}`; after stack maintenance, PR #12 targets `develop`.
- Live PR body: `gh pr edit --body-file docs/roadmap/stage-0/phases/add-planning-resume-selectors-pr-body.md` failed with the known GitHub Projects Classic deprecation GraphQL error; the body was updated with `gh api --method PATCH repos/samcantrill/loom/pulls/12 -F body=@docs/roadmap/stage-0/phases/add-planning-resume-selectors-pr-body.md`.
- Validation evidence: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed after the post-review blocker fix with Ruff, Pyright, default pytest `333 passed`, and build succeeded.
- Suite evidence: `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed after the post-review blocker fix; package 24, unit 278, contract 15, and integration 16 passed, and e2e is not present.
- GitHub checks: PR #12 is not draft, mergeStateStatus is `CLEAN`, and CI check `checks` completed with conclusion `SUCCESS`.
- Assumptions and risks: same-run-directory resume remains the only v0 reuse mode; Phase 9 owns execution and final lifecycle writes; this stacked PR must be rebased or replayed and retargeted to `develop` after Phase 7 lands before it is merge-eligible.
- PR review budget: used. The reviewer found the blocking `from_stage` selector issue; this user-authorized post-review fix addresses it. Do not consume a second automated PR review without explicit user instruction.
- Blockers: none.

## Source Phase Summary

- Goal: implement deterministic execution planning, selectors, stage fingerprints, conservative same-run-directory resume checks, and downstream invalidation without executing stages.
- Required scope:
  - Add stage fingerprint calculation.
  - Add execution plan and stage plan models with stable plain-data serialization.
  - Add plan explanation/reason data.
  - Add selector models for `force_stages`, `from_stage`, `only_stages`, and `skip_stages`.
  - Bind stage inputs from upstream outputs and existing run-store state.
  - Reuse Phase 7 stores for prior status, inputs, outputs, fingerprints, artifact indexes, and artifact validation.
  - Persist computed plans through the run store.
- Required checkpoints:
  - Fingerprints include deterministic semantic inputs: stage name, target path, stage config, declared outputs, bound inputs, Python version, `loom` version, relevant git state, configured dependency versions, and configured extra fields.
  - Fingerprints exclude noisy values such as timestamps, logs, temp paths, random run IDs, and `StageSpec.resources` by default.
  - Selectors are structured Python-safe planner inputs. CLI aliases remain deferred.
  - Planner emits ordered decisions, bound input refs, fingerprint data, skip/run/reuse/block reasons, invalidation reasons, and dry-run-friendly explanations.
  - `REUSE` is returned only with positive evidence from prior succeeded state, matching fingerprints, valid output refs, existing artifacts, and checksum verification where supported.
  - Downstream invalidation propagates when an upstream stage is forced, changed, stale, skipped, blocked, or expected to produce new artifacts.
- Acceptance criteria:
  - Planner computes bound inputs and topological stage plans.
  - Selectors `force_stages`, `from_stage`, `only_stages`, and `skip_stages` affect plan decisions deterministically and record explanations.
  - Resume returns `REUSE` only for valid succeeded stages with matching fingerprints, existing outputs, existing artifacts, and valid checksums.
  - Interrupted, corrupt, stale, failed, or partial state is never reusable.
  - Downstream invalidation propagates for changed config, target, output specs, selector decisions, or upstream artifacts.
  - Plan files can be persisted and read through the run store.
- Source references: `docs/roadmap/stage-0/implementation-plan.md` Phase 8; `docs/structure.md` sections "Pipeline Model and Planning", "Stores and State", "Provenance and Resume", "Runtime Dependency Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 9, 10, and 11; `docs/features/pipeline.md`, `docs/features/run-store.md`, `docs/features/pipeline-graph.md`, `docs/features/runtime-resources.md`, `docs/features/state.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, and `docs/features/testing.md`.

## Current Source And Harness Findings

- `src/loom/pipeline/planning/__init__.py` is still an import-safe skeleton with an empty public surface. Phase 8 should make this package the public planner API.
- `src/loom/pipeline/specs.py` already provides frozen `PipelineSpec`, `StageSpec`, and `OutputSpec` models with strict stage/output names, `target_path`, `stage_config`, input refs, output specs, and opaque `resources`.
- `src/loom/pipeline/graph` already provides strict `stage.output` parsing, resolved input bindings, graph construction, direct/transitive upstream and downstream queries, and deterministic topological sort.
- `src/loom/pipeline/status.py` already provides `RunStatus`, `StageStatus`, `RunStatusRecord`, and `StageStatusRecord`. `REUSE` and `BLOCKED` should remain plan actions, not persisted success statuses.
- `src/loom/fingerprints.py` already provides deterministic digest helpers and validation. Stage fingerprint policy belongs under planning and should reuse these helpers instead of adding another hashing layer.
- `src/loom/artifacts.py` already provides `ArtifactRef` with checksum, fingerprint, producer stage, and plain-data serialization.
- Phase 7 store APIs in `src/loom/pipeline/stores` provide `RunStore`, `ArtifactStore`, `LocalRunStore`, `LocalArtifactStore`, plan persistence, stage status/input/output/fingerprint readers, artifact indexes, and checksum/existence validation. Planning should use store protocols and avoid local path assumptions where possible.
- `LocalRunStore.read_stage_*` methods return `None` for missing optional state and raise store errors for corrupt state. Planning should convert missing state into rerun/stale reasons and treat corrupt state as a planning error, not silently ignore it.
- `LocalArtifactStore.validate()` verifies local existence and checksums when present; it raises store errors for missing paths, type mismatches, unsupported checksum cases, and checksum mismatches.
- Package import-boundary tests currently keep root `loom` cheap and keep stores out of config/CLI imports. Phase 8 should add planning-specific import tests without exporting planner behavior from root `loom`.
- Test harness suites are `package`, `unit`, `contract`, `integration`, `e2e`, and opt-in markers such as `slow`, `network`, `slurm`, and `optional_dependency`. There is no e2e test directory in the predecessor branch.

## In-Scope Work

- Add planning errors under `loom.pipeline.planning`.
- Add public planning models for plan actions, plan reasons, selector inputs, resume policy, stage fingerprint records or payloads, stage reuse results, stage plans, and execution plans.
- Add deterministic plain-data serialization for plan and fingerprint records so `RunStore.write_plan()` can persist and `RunStore.read_plan()` can round-trip planner output.
- Add stage fingerprint payload construction and hashing using existing `loom.fingerprints.hash_mapping`.
- Add configurable explicit fingerprint inputs for relevant git state, dependency versions, and extra plain-data fields, while keeping automatic environment scanning out of scope.
- Add planner input binding that resolves `StageSpec.inputs` to current `ArtifactRef` inputs from already planned upstream outputs or prior reusable run-store outputs.
- Add resume checks using `RunStore` state and `ArtifactStore.validate()`.
- Add selector validation and deterministic selector application for `force_stages`, `from_stage`, `only_stages`, and `skip_stages`.
- Add downstream invalidation across linear, branching, diamond, and fan-in DAGs.
- Add a `plan_pipeline()` API that returns an `ExecutionPlan` and optionally persists it through `RunStore.write_plan()`.
- Export the Phase 8 public planning API from `loom.pipeline.planning` only.
- Add focused package, unit, and integration tests for planner imports, models, fingerprints, selectors, resume, invalidation, store collaboration, and plan persistence. Defer the contract suite because Phase 8 must not add a new public structural protocol.

## Out-of-Scope Work

- No actual stage execution, `PipelineRunner`, executor protocol, `LocalExecutor`, lifecycle helpers, or target invocation.
- No stage target instantiation policy or constructor behavior.
- No runner output validation or status transitions beyond reading existing status records for planning.
- No functional CLI behavior, CLI aliases, terminal tables, or command parsing.
- No subprocess, SLURM, distributed, container, or remote execution behavior.
- No remote stores, global run discovery, cross-run cache reuse, content-addressed cache, or repair commands.
- No dynamic DAG mutation, conditional execution, runtime profiles, typed resource requests, or scheduler-specific resource mapping.
- No stage-internal checkpoint loading or domain-specific partial resume.
- No broad refactors outside `loom.pipeline.planning`, planning package exports, and tightly related tests.

## Assumptions

- The planner works against one run ID and one same-run directory. Cross-run lookup is deferred.
- A missing prior state file means no reusable state unless the file is explicitly optional for the current check.
- Corrupt store documents fail planning with a clear planning/store error because v0 should not silently repair or ignore corrupt state.
- Normal v0 reuse validates local artifacts and verifies checksums when an `ArtifactRef` has a checksum and the artifact store can read the URI.
- Remote or unsupported artifact URI validation must not produce `REUSE` unless a store implementation can positively validate it.
- `StageSpec.resources` are preserved in plans for inspection but excluded from the default semantic fingerprint policy.
- Git and dependency facts included in fingerprints are explicit planner inputs or lightweight capture results provided by callers; planning should not perform broad package/environment scans by default.
- `only_stages` requires upstream inputs to be reusable or otherwise already available in prior state; it must not implicitly run unselected upstream stages.
- `skip_stages` produces `SKIP` for selected stages and `BLOCKED` for downstream stages that require skipped outputs.
- Plan persistence uses the Phase 7 `plan.json` wrapper and stores one current plan, not historical attempts.

## Decision-Complete Contract

### Module Boundaries And Public Exports

Implement the public planning API under `src/loom/pipeline/planning/` with these files and ownership:

- `__init__.py`: public re-export surface only. It must not export through root `loom` or `loom.pipeline` in this phase.
- `models.py`: frozen dataclasses, `StrEnum` values, constants, and plain-data `to_dict()` / `from_dict()` helpers.
- `errors.py`: planning-specific exception hierarchy.
- `fingerprints.py`: deterministic stage fingerprint payload construction and hashing.
- `selectors.py`: selector normalization, validation, eligibility, and conflict checks.
- `resume.py`: prior-state loading and direct same-run reuse checks over `RunStore`/`ArtifactStore`.
- `planner.py`: `plan_pipeline(...)`, topological planning flow, downstream invalidation, and optional plan persistence.

`loom.pipeline.planning` public `__all__` must be exactly:

```python
[
    "DEFAULT_FINGERPRINT_ALGORITHM",
    "PLAN_SCHEMA_VERSION",
    "STAGE_FINGERPRINT_POLICY_NAME",
    "STAGE_FINGERPRINT_POLICY_VERSION",
    "STAGE_FINGERPRINT_SCHEMA_VERSION",
    "BoundInput",
    "ExecutionPlan",
    "FingerprintContext",
    "FingerprintStatus",
    "PendingInput",
    "PlanAction",
    "PlanPersistenceError",
    "PlanReason",
    "PlanReasonCode",
    "PlanSerializationError",
    "PlanSelectors",
    "PlanningError",
    "PlanningValidationError",
    "ResumeCheck",
    "ResumeOptions",
    "ResumeStateError",
    "SelectorValidationError",
    "StageFingerprintError",
    "StageFingerprintPayload",
    "StageFingerprintRecord",
    "StagePlan",
    "build_stage_fingerprint",
    "plan_pipeline",
]
```

Planning modules may import `PipelineSpec`, `StageSpec`, `OutputSpec`, graph helpers, `StageStatus`, `ArtifactRef`, direct store protocol modules `loom.pipeline.stores.run_store` and `loom.pipeline.stores.artifact_store`, store error classes, `loom.fingerprints`, `loom.serialization`, `loom.timestamps`, and cheap package metadata. They must not import config composition, CLI, executors, stage target instantiation, runner/lifecycle code, local store implementations from the planning public surface, project packages, or remote-store code.

### Constants, Actions, Reasons, And Errors

Define these constants:

```python
PLAN_SCHEMA_VERSION = 1
STAGE_FINGERPRINT_SCHEMA_VERSION = 1
STAGE_FINGERPRINT_POLICY_NAME = "loom.stage.v1"
STAGE_FINGERPRINT_POLICY_VERSION = 1
DEFAULT_FINGERPRINT_ALGORITHM = "sha256"
```

Use `StrEnum` for public action/status-like planning values:

```python
class PlanAction(StrEnum):
    RUN = "RUN"
    REUSE = "REUSE"
    SKIP = "SKIP"
    STALE = "STALE"
    BLOCKED = "BLOCKED"

class FingerprintStatus(StrEnum):
    COMPUTED = "COMPUTED"
    PENDING_INPUTS = "PENDING_INPUTS"
```

Use `PlanReasonCode(StrEnum)` with these v0 values. Tests may assert these literal values:

```python
RESUME_DISABLED = "RESUME_DISABLED"
NO_PRIOR_STATUS = "NO_PRIOR_STATUS"
PRIOR_STATUS_NOT_SUCCEEDED = "PRIOR_STATUS_NOT_SUCCEEDED"
PRIOR_STATUS_RUNNING = "PRIOR_STATUS_RUNNING"
MISSING_FINGERPRINT = "MISSING_FINGERPRINT"
MISSING_INPUTS = "MISSING_INPUTS"
MISSING_OUTPUTS = "MISSING_OUTPUTS"
MISSING_OUTPUT_REF = "MISSING_OUTPUT_REF"
OUTPUT_SPEC_MISMATCH = "OUTPUT_SPEC_MISMATCH"
FINGERPRINT_MATCH = "FINGERPRINT_MATCH"
FINGERPRINT_CHANGED = "FINGERPRINT_CHANGED"
FINGERPRINT_POLICY_CHANGED = "FINGERPRINT_POLICY_CHANGED"
ARTIFACT_VALIDATED = "ARTIFACT_VALIDATED"
ARTIFACT_MISSING = "ARTIFACT_MISSING"
ARTIFACT_CHECKSUM_MISMATCH = "ARTIFACT_CHECKSUM_MISMATCH"
ARTIFACT_VALIDATION_FAILED = "ARTIFACT_VALIDATION_FAILED"
ARTIFACT_INDEX_CONFLICT = "ARTIFACT_INDEX_CONFLICT"
FORCED_BY_SELECTOR = "FORCED_BY_SELECTOR"
FROM_STAGE_SELECTED = "FROM_STAGE_SELECTED"
ONLY_STAGE_SELECTED = "ONLY_STAGE_SELECTED"
OUTSIDE_ONLY_SELECTION = "OUTSIDE_ONLY_SELECTION"
SKIPPED_BY_SELECTOR = "SKIPPED_BY_SELECTOR"
BLOCKED_BY_UPSTREAM = "BLOCKED_BY_UPSTREAM"
UPSTREAM_WILL_RUN = "UPSTREAM_WILL_RUN"
UPSTREAM_SKIPPED = "UPSTREAM_SKIPPED"
UPSTREAM_BLOCKED = "UPSTREAM_BLOCKED"
UPSTREAM_STALE = "UPSTREAM_STALE"
UNAVAILABLE_UPSTREAM_INPUT = "UNAVAILABLE_UPSTREAM_INPUT"
PENDING_UPSTREAM_INPUT = "PENDING_UPSTREAM_INPUT"
```

Use this error hierarchy:

```python
class PlanningError(PipelineError): ...
class PlanningValidationError(PlanningError, ValidationError): ...
class SelectorValidationError(PlanningValidationError): ...
class PlanSerializationError(PlanningValidationError): ...
class StageFingerprintError(PlanningValidationError): ...
class ResumeStateError(PlanningError): ...
class PlanPersistenceError(PlanningError): ...
```

Selector errors, invalid public dataclass fields, unsupported plan/fingerprint schema versions, and malformed planner-owned plain data raise `PlanningValidationError` subclasses. Corrupt or internally inconsistent prior run state that cannot safely be degraded to a rerun raises `ResumeStateError`. A `RunStore.write_plan()` or `RunStore.read_plan()` failure while persisting or verifying plan persistence raises `PlanPersistenceError` with the original store error as `__cause__`.

### Public Dataclass Shapes

All public dataclasses are frozen and slot-based. Mapping fields must be copied to plain `dict` objects in `__post_init__`; sequence fields must be normalized to tuples in deterministic pipeline order where a `PipelineSpec` is available.

`PlanReason`:

```python
@dataclass(frozen=True, slots=True)
class PlanReason:
    code: PlanReasonCode
    message: str
    stage_name: str | None = None
    upstream_stage: str | None = None
    input_name: str | None = None
    output_name: str | None = None
    details: Mapping[str, PlainData] = field(default_factory=dict)
```

`PlanSelectors`:

```python
@dataclass(frozen=True, slots=True)
class PlanSelectors:
    force_stages: tuple[str, ...] = ()
    from_stage: str | None = None
    only_stages: tuple[str, ...] = ()
    skip_stages: tuple[str, ...] = ()
```

`ResumeOptions`:

```python
@dataclass(frozen=True, slots=True)
class ResumeOptions:
    enabled: bool = True
```

Keep additional strict/lenient modes out of scope. V0 normal mode always validates artifacts through the provided `ArtifactStore.validate()` before `REUSE`.

`FingerprintContext`:

```python
@dataclass(frozen=True, slots=True)
class FingerprintContext:
    python_version: str | None = None
    loom_version: str | None = None
    git: Mapping[str, PlainData] = field(default_factory=dict)
    dependencies: Mapping[str, str] = field(default_factory=dict)
    extra: Mapping[str, PlainData] = field(default_factory=dict)
    algorithm: str = DEFAULT_FINGERPRINT_ALGORITHM
    policy_name: str = STAGE_FINGERPRINT_POLICY_NAME
    policy_version: int = STAGE_FINGERPRINT_POLICY_VERSION
```

`python_version` and `loom_version` default to the current interpreter and `loom.__version__` during fingerprint payload construction. `git`, `dependencies`, and `extra` are included only when callers provide them; planning must not scan git, installed packages, or environment variables by default.

`BoundInput` and `PendingInput`:

```python
@dataclass(frozen=True, slots=True)
class BoundInput:
    input_name: str
    source_stage: str
    source_output: str
    artifact_ref: ArtifactRef

@dataclass(frozen=True, slots=True)
class PendingInput:
    input_name: str
    source_stage: str
    source_output: str
    reason: PlanReason
```

`StageFingerprintPayload` contains the canonical inputs that are hashed:

```python
@dataclass(frozen=True, slots=True)
class StageFingerprintPayload:
    schema_version: int
    policy_name: str
    policy_version: int
    stage_name: str
    target_path: str
    stage_config: Mapping[str, PlainData]
    declared_inputs: Mapping[str, str]
    bound_inputs: Mapping[str, Mapping[str, PlainData]]
    declared_outputs: Mapping[str, Mapping[str, PlainData]]
    python_version: str
    loom_version: str
    git: Mapping[str, PlainData]
    dependencies: Mapping[str, str]
    extra: Mapping[str, PlainData]
```

`StageFingerprintRecord`:

```python
@dataclass(frozen=True, slots=True)
class StageFingerprintRecord:
    schema_version: int
    algorithm: str
    policy_name: str
    policy_version: int
    fingerprint: str
    payload: StageFingerprintPayload
    inputs_summary: Mapping[str, PlainData]
```

`ResumeCheck` records direct same-stage reuse before selector and downstream invalidation:

```python
@dataclass(frozen=True, slots=True)
class ResumeCheck:
    stage_name: str
    action: PlanAction
    status: str | None
    attempt: int | None
    prior_fingerprint: StageFingerprintRecord | None
    current_fingerprint: StageFingerprintRecord | None
    inputs: Mapping[str, ArtifactRef]
    outputs: Mapping[str, ArtifactRef]
    reasons: tuple[PlanReason, ...]
```

`StagePlan`:

```python
@dataclass(frozen=True, slots=True)
class StagePlan:
    stage_name: str
    action: PlanAction
    base_action: PlanAction
    fingerprint_status: FingerprintStatus
    fingerprint: StageFingerprintRecord | None
    resume_check: ResumeCheck | None
    reasons: tuple[PlanReason, ...]
    bound_inputs: Mapping[str, BoundInput]
    pending_inputs: tuple[PendingInput, ...]
    reusable_outputs: Mapping[str, ArtifactRef]
    declared_outputs: Mapping[str, Mapping[str, PlainData]]
    upstream_stages: tuple[str, ...]
    downstream_stages: tuple[str, ...]
    selected_by: tuple[PlanReasonCode, ...]
    invalidated_by: tuple[PlanReason, ...]
```

`ExecutionPlan`:

```python
@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    schema_version: int
    run_id: str
    pipeline_name: str | None
    selectors: PlanSelectors
    resume: ResumeOptions
    fingerprint_context: FingerprintContext
    stage_order: tuple[str, ...]
    stage_plans: tuple[StagePlan, ...]
    reasons: tuple[PlanReason, ...]
    summary: Mapping[str, int]
```

`ExecutionPlan.stage_plans` must be in graph topological order. `summary` maps each `PlanAction.value` to its count. `ExecutionPlan.to_dict()` returns the inner plain-data document passed to `RunStore.write_plan()`. `ExecutionPlan.from_dict()` parses the inner mapping returned by `RunStore.read_plan()`.

### Public Function Signatures

The planner entrypoint signature is:

```python
def plan_pipeline(
    spec: PipelineSpec,
    *,
    run_id: str,
    run_store: RunStore,
    artifact_store: ArtifactStore,
    selectors: PlanSelectors | None = None,
    resume: ResumeOptions | None = None,
    fingerprint_context: FingerprintContext | None = None,
    persist: bool = False,
) -> ExecutionPlan: ...
```

`selectors`, `resume`, and `fingerprint_context` default to empty selectors, enabled resume, and default fingerprint context. `persist=True` writes `execution_plan.to_dict()` through `run_store.write_plan(run_id, ...)`; it must not write run status, stage status, stage inputs, stage outputs, or stage fingerprints.

The public fingerprint helper signature is:

```python
def build_stage_fingerprint(
    stage: StageSpec,
    *,
    bound_inputs: Mapping[str, ArtifactRef],
    fingerprint_context: FingerprintContext | None = None,
) -> StageFingerprintRecord: ...
```

This helper requires all declared inputs to be present in `bound_inputs`. If any input is pending because an upstream stage will run, the helper raises `StageFingerprintError`; `plan_pipeline()` records `fingerprint_status=PENDING_INPUTS` and `fingerprint=None` for that stage instead of calling the helper.

### Fingerprint Payload Inputs And Exclusions

`StageFingerprintPayload.to_hash_input()` must be the only mapping passed to `loom.fingerprints.hash_mapping()`. Include:

- stage name;
- target import path;
- `StageSpec.stage_config`;
- authored `StageSpec.inputs` as `declared_inputs`;
- bound input identity for each input;
- output declarations for every output;
- Python version;
- `loom` version;
- caller-provided git facts;
- caller-provided dependency versions;
- caller-provided extra plain-data fields;
- policy name/version and schema version.

Bound input identity must be normalized as:

```python
{
    "source_stage": source_stage,
    "source_output": source_output,
    "artifact_id": ref.artifact_id,
    "artifact_type": ref.artifact_type,
    "codec_key": ref.codec_key,
    "schema_version": ref.schema_version,
    "checksum": ref.checksum,
    "fingerprint": ref.fingerprint,
    "producer_stage": ref.producer_stage,
    "metadata": dict(ref.metadata),
}
```

Output declarations must be normalized as:

```python
{
    output_name: {
        "artifact_type": output_spec.artifact_type,
        "codec_key": output_spec.codec_key,
        "schema_version": output_spec.schema_version,
        "metadata": dict(output_spec.metadata),
    }
}
```

Exclude these values from the default fingerprint payload: `StageSpec.resources`, wall-clock timestamps, run ID, run directory, stage directory, artifact URI/path, log paths, temp paths, host/user/process data, random IDs, `ArtifactRef.created_at`, and any git/dependency/environment facts not explicitly supplied in `FingerprintContext`.

### Persisted Fingerprint Shape

`StageFingerprintRecord.to_dict()` is the inner mapping passed to Phase 7:

```python
run_store.write_stage_fingerprint(
    run_id,
    stage_name,
    stage_fingerprint_record.to_dict(),
    attempt=attempt,
)
```

Phase 7 wraps that mapping as `{"schema_version", "run_id", "stage_name", "attempt", "created_at", "fingerprint"}`. The inner `fingerprint` mapping must be:

```json
{
  "schema_version": 1,
  "algorithm": "sha256",
  "policy_name": "loom.stage.v1",
  "policy_version": 1,
  "fingerprint": "sha256:<hex>",
  "payload": { "...": "canonical hash input" },
  "inputs_summary": {
    "stage_name": "train",
    "target_path": "project.stages.Train",
    "input_names": ["dataset"],
    "output_names": ["model"],
    "input_artifacts": {
      "dataset": {
        "source": "build.dataset",
        "artifact_id": "build/dataset",
        "checksum": "sha256:<hex-or-null>",
        "fingerprint": "sha256:<hex-or-null>"
      }
    },
    "python_version": "3.12.x",
    "loom_version": "0.1.0",
    "git": {},
    "dependency_names": [],
    "extra_keys": []
  }
}
```

`payload` is allowed to contain stage config and metadata because it is stage-local plan state. `inputs_summary` must stay compact and assertion-friendly. `created_at` remains the Phase 7 store wrapper timestamp and is never part of the hash input.

### Persisted Plan Shape

`ExecutionPlan.to_dict()` is the inner mapping passed to Phase 7:

```python
run_store.write_plan(run_id, execution_plan.to_dict())
```

Phase 7 wraps it as `{"schema_version", "run_id", "updated_at", "plan"}` and `read_plan(run_id)` returns only the inner `plan` mapping. The inner plan mapping must be:

```json
{
  "schema_version": 1,
  "kind": "loom.execution_plan",
  "run_id": "run-1",
  "pipeline_name": "pipeline-name-or-null",
  "selectors": {
    "force_stages": [],
    "from_stage": null,
    "only_stages": [],
    "skip_stages": []
  },
  "resume": {
    "enabled": true
  },
  "fingerprint_context": {
    "python_version": "3.12.x",
    "loom_version": "0.1.0",
    "git": {},
    "dependencies": {},
    "extra": {},
    "algorithm": "sha256",
    "policy_name": "loom.stage.v1",
    "policy_version": 1
  },
  "stage_order": ["build", "train"],
  "stage_plans": [
    {
      "stage_name": "build",
      "action": "REUSE",
      "base_action": "REUSE",
      "fingerprint_status": "COMPUTED",
      "fingerprint": { "...": "StageFingerprintRecord" },
      "resume_check": { "...": "ResumeCheck" },
      "reasons": [{ "...": "PlanReason" }],
      "bound_inputs": {},
      "pending_inputs": [],
      "reusable_outputs": { "dataset": { "...": "ArtifactRef" } },
      "declared_outputs": { "dataset": { "...": "OutputSpec plain data" } },
      "upstream_stages": [],
      "downstream_stages": ["train"],
      "selected_by": [],
      "invalidated_by": []
    }
  ],
  "reasons": [],
  "summary": {
    "RUN": 0,
    "REUSE": 1,
    "SKIP": 0,
    "STALE": 0,
    "BLOCKED": 0
  }
}
```

Round-trip tests must assert `ExecutionPlan.from_dict(plan.to_dict()).to_dict() == plan.to_dict()` and that `LocalRunStore.write_plan()` / `read_plan()` preserves the same inner mapping.

### Selector Semantics And Conflict Rules

Selector validation runs before any store reads. Unknown stage names raise `SelectorValidationError` naming the selector field and stage. Duplicate names inside a selector field collapse to one stage and then normalize to pipeline topological order.

Default selector behavior:

- With no selectors, every stage is eligible to run. Stages directly reusable become `REUSE`; non-reusable stages become `RUN`; downstream consumers of any stage that will `RUN` become `RUN` with `UPSTREAM_WILL_RUN` and pending inputs until execution produces artifacts.
- `force_stages` forces listed stages to `RUN` even if direct reuse is valid, records `FORCED_BY_SELECTOR`, and invalidates all transitive downstream stages.
- `from_stage` forces that stage to `RUN`, marks it with `FROM_STAGE_SELECTED`, makes the selected stage and all downstream stages eligible to run, and treats upstream stages as reuse providers only. If an upstream required by the `from_stage` closure is not directly reusable, that upstream becomes `BLOCKED` and the selected closure becomes `BLOCKED` with `UNAVAILABLE_UPSTREAM_INPUT`.
- `only_stages` makes only the named stages eligible to run. Transitive upstream stages are reuse providers only: reusable upstreams are `REUSE`; unavailable upstreams are `BLOCKED`, and selected consumers are `BLOCKED`. Downstream stages outside `only_stages` become `SKIP` with `OUTSIDE_ONLY_SELECTION`.
- `skip_stages` makes listed stages `SKIP` with `SKIPPED_BY_SELECTOR`. Direct and transitive downstream stages that depend on skipped stages by data or control edge become `BLOCKED` with `UPSTREAM_SKIPPED` unless they were already skipped. V0 has no alternate input satisfaction rule.

Combined selector rules:

- `skip_stages` intersecting `force_stages`, `only_stages`, or `from_stage` is a `SelectorValidationError`.
- `from_stage` and `only_stages` are mutually exclusive in v0; combining them raises `SelectorValidationError`. This avoids ambiguous "closure versus exact set" semantics until CLI UX is designed.
- `force_stages` may combine with `from_stage` only when every forced stage is in the `from_stage` transitive downstream closure, including the selected `from_stage` itself.
- `force_stages` may combine with `only_stages` only when every forced stage is also listed in `only_stages`.
- `skip_stages` may skip downstream branches of a `from_stage` plan or unrelated stages in an `only_stages` plan as long as it does not intersect selected/forced stages; skipped dependencies still block their dependents.
- Selector validation happens before store reads, so selector conflicts are reported deterministically even if the run directory is corrupt.

### Store Error Handling, Direct Reuse, And Invalidation

Direct reuse checks call `RunStore.read_stage_status()`, `read_stage_inputs()`, `read_stage_fingerprint()`, `read_stage_outputs()`, and `read_artifact_index()` only. Planning never writes stage state. Missing optional documents represented by `None` become plan reasons, not exceptions.

Direct reuse results:

- `ResumeOptions(enabled=False)`: eligible stages return `RUN` with `RESUME_DISABLED`; reuse-provider-only stages return `BLOCKED` if their outputs are needed because reuse is disabled.
- Missing prior status: eligible stage returns `RUN` with `NO_PRIOR_STATUS`; reuse-provider-only stage returns `BLOCKED`.
- Prior status other than `SUCCEEDED`: eligible stage returns `RUN` with `PRIOR_STATUS_NOT_SUCCEEDED`, except `RUNNING` uses `PRIOR_STATUS_RUNNING`; reuse-provider-only stage returns `BLOCKED`.
- Prior `SUCCEEDED` with missing inputs, missing fingerprint, or missing outputs: base action is `STALE`; final action is `RUN` if the stage is eligible, otherwise `BLOCKED`.
- Prior fingerprint policy/schema/algorithm mismatch or fingerprint digest mismatch: base action is `STALE`; final action is `RUN` if eligible, otherwise `BLOCKED`.
- Missing required output ref, output name mismatch, artifact type mismatch, or declared codec mismatch: base action is `STALE`; final action is `RUN` if eligible, otherwise `BLOCKED`.
- `ArtifactStore.validate()` success for every required output plus matching fingerprint/status produces `REUSE`.
- `ArtifactStore.validate()` failures for missing artifacts, checksum mismatches, unsupported URI validation, or artifact type errors do not produce `REUSE`; eligible stages become `RUN`, reuse-provider-only stages become `BLOCKED`, and reasons preserve the validation error class/message in `details`.

Raise `ResumeStateError` instead of returning `RUN`/`STALE`/`BLOCKED` when:

- a run-store read raises `CorruptStoreDocumentError`;
- a prior fingerprint document cannot parse as `StageFingerprintRecord`;
- store output data contains invalid `ArtifactRef` payloads;
- the run-level artifact index conflicts with stage outputs for the same logical key (`stage.output`) by pointing at a different `ArtifactRef`;
- a store method raises a non-validation `StoreError` indicating the planner cannot know whether state is safe.

Do not automatically repair missing or stale `artifacts.json`; if the index is missing, direct reuse may still rely on valid stage `outputs.json` and artifact validation. If the index is present and conflicts with stage outputs, raise `ResumeStateError`.

Downstream invalidation:

- A stage with final action `RUN`, `STALE`, `SKIP`, or `BLOCKED` invalidates direct and transitive consumers.
- A consumer with any upstream `RUN` records `UPSTREAM_WILL_RUN`, gets final action `RUN` when otherwise eligible, and records affected inputs in `pending_inputs`; it cannot compute a final fingerprint until execution produces upstream artifacts.
- A consumer with any upstream `SKIP` or `BLOCKED` becomes `BLOCKED`.
- A consumer with an upstream base action `STALE` but final action `RUN` is invalidated as `UPSTREAM_STALE`.
- Fan-in stages record one reason per invalidating upstream up to all direct invalidating inputs; tests should assert exact reasons for two-input diamonds rather than relying on a summary string.

This phase must not implement runner behavior for rebinding pending inputs during execution. Phase 9 will consume `pending_inputs` and recompute/write fingerprints when upstream outputs exist.

## Design Impact

- Maintainability: keeps planning as a pure policy layer over already validated specs, graph helpers, and store protocols, avoiding runner shortcuts that would duplicate resume logic later.
- Extensibility: structured selectors, actions, reasons, fingerprints, and plan records leave room for future CLI display, remote stores, alternate executors, and stricter policies without changing stage specs.
- Domain neutrality: planner decisions are based on generic configs, artifact refs, fingerprints, checksums, and graph relationships. It does not inspect domain files, checkpoints, metrics, datasets, or models.
- Source-tree boundaries: implementation should stay under `src/loom/pipeline/planning` and related tests. It may import pipeline specs/graph/status, direct store protocol modules, store errors, artifacts, fingerprints, serialization, timestamps, ids, and cheap package metadata. It must not import config composition, CLI, executors, runner behavior, target instantiation, local store implementations through the planning public surface, or downstream project modules.

## Future Compatibility

- The plan model should be suitable for future `loom plan` and `loom run` APIs to share one planner.
- Selector models should use Python-safe field names now and leave CLI aliases such as `--from-stage`, `--only-stage`, `--force-stage`, and `--skip-stage` to the CLI phase.
- Fingerprint records should include policy/version metadata so future policy changes invalidate old records explicitly instead of comparing incompatible hashes.
- Plan reasons should be structured enough for future verbose explanations and PR/test assertions without relying only on free-form strings.
- Store interactions should use protocols so remote stores can later implement positive existence/checksum validation without rewriting planner policy.
- Same-run-directory resume should remain the only v0 reuse mode; cross-run cache indexes can be added later by extending state loading rather than weakening current reuse checks.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement selectors inside the future runner only | Dry-run planning and execution would diverge, and Phase 8 requires deterministic selector explanations before execution exists. |
| Reuse based on output file existence alone | The v0 plan and resume docs require prior `SUCCEEDED` status, matching fingerprint, output refs, artifact existence, and checksum validation where supported. |
| Include `StageSpec.resources` in default fingerprints | The v0 plan explicitly excludes resources from semantic fingerprints by default because resources are opaque operational metadata in v0. |
| Treat corrupt prior state as rerunnable missing state | Silent corruption handling can hide data loss or unsafe reuse. V0 should fail planning clearly for malformed store documents. |
| Add CLI aliases or command behavior now | Phase 8 supports Python-safe selector models only; CLI behavior belongs to later work. |
| Add cross-run cache reuse | The v0 plan intentionally limits resume to the same run directory. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Same-run-directory reuse only | This is an explicit v0 tradeoff to make local resume semantics correct before cache discovery exists. | After Phase 9/10 local execution and invalidation tests are stable and a new plan defines cross-run cache behavior. |
| Plan persistence stores only the current computed plan | Phase 7 run store exposes one `plan.json` document; attempt history is not part of v0. | If users need audit history or concurrent planning attempts. |
| Downstream fingerprints with pending upstream outputs are deferred until execution | Phase 8 cannot know artifact refs/checksums for stages that have not run, and inventing placeholders would make unsafe reuse easier. | Phase 9 runner binds produced upstream outputs before invoking downstream stages and writes the final stage fingerprint. |
| Detailed fingerprint diff rendering deferred | Phase 8 needs structured reasons and summaries, not CLI-grade verbose diff output. | When a CLI/status phase needs `loom plan --explain`-style output. |

## Reviewability

- Expected PR size and shape: one planning-focused PR adding models, fingerprint/resume/selector logic, planning exports, and focused tests. It should not include executor, runner, CLI, or broad store refactors.
- Files and areas to inspect:
  - `src/loom/pipeline/planning/`
  - `src/loom/pipeline/planning/__init__.py`
  - package API/import-boundary tests for planning
  - `tests/unit/loom/pipeline/planning/`
  - existing store/stage contract suites only to confirm no new planning protocol was introduced
  - `tests/integration/pipeline/` for planner plus Phase 7 store behavior
- Scope-control checks:
  - no root `loom.__init__` planning exports;
  - no functional CLI additions;
  - no stage target instantiation or execution;
  - no new runtime dependencies;
  - no remote/cross-run cache behavior;
  - planner imports stay away from `loom.config`, `loom.cli`, executors, and project code unless a refine-pass decision explicitly justifies a narrow exception.

## Implementation Steps

1. Add `errors.py` and `models.py` with the exact constants, enums, dataclasses, normalization, and plain-data serialization/deserialization named in the decision-complete contract.
2. Add `fingerprints.py` with `build_stage_fingerprint(...)`, canonical bound-input/output-spec normalization, exclusions for resources/paths/timestamps, and hashing via `loom.fingerprints.hash_mapping`.
3. Add `selectors.py` with `PlanSelectors` normalization against `PipelineSpec.stage_names`, deterministic topological ordering, and the conflict/combination rules for `force_stages`, `from_stage`, `only_stages`, and `skip_stages`.
4. Add `resume.py` with direct reuse checks over `RunStore`/`ArtifactStore`, including `REUSE` positive evidence, `RUN`/`STALE`/`BLOCKED` degradation for incomplete or unverifiable reusable state, and `ResumeStateError` for corrupt/inconsistent state.
5. Add `planner.py` with `plan_pipeline(...)`: build the stage graph, compute topological order, resolve input bindings, compute fingerprints when all inputs are bound, preserve pending inputs when upstreams will run, apply selectors, propagate downstream invalidation/blocking, and build an ordered `ExecutionPlan`.
6. Implement optional `persist=True` by calling only `RunStore.write_plan(run_id, execution_plan.to_dict())`; do not write stage status, inputs, outputs, fingerprints, failures, lifecycle state, or runner-owned files.
7. Export exactly the planned public API from `loom.pipeline.planning.__init__`; keep `loom.__init__` and `loom.pipeline.__init__` unchanged unless an import-boundary test needs a narrow negative assertion.
8. Add package, unit, and integration tests named below. Do not add a new public protocol or contract suite unless implementation discovers an unavoidable structural protocol, in which case stop and record the scope change for the manager.
9. Run targeted test commands for changed slices during implementation. Leave final `make validate-pr` and `make test-summary` to PR preparation after implementation/refinement.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_pipeline_planning_api.py`
  - update `tests/package/test_import_boundaries.py` if needed.
- Required assertions or deferral reason:
  - `loom.pipeline.planning.__all__` exactly matches the public export list in this plan.
  - Importing `loom` remains cheap and does not import planning.
  - Importing `loom.pipeline.planning` does not import `loom.cli`, `loom.config`, `loom.pipeline.execution`, `loom.pipeline.executors`, or downstream project modules.
  - Planning exports are available only from `loom.pipeline.planning`; root `loom.__all__` and `loom.pipeline.__all__` do not grow planning names in this phase.

### Unit Suite

- Status: required.
- Expected paths:
  - `tests/unit/loom/pipeline/planning/test_models.py`
  - `tests/unit/loom/pipeline/planning/test_fingerprints.py`
  - `tests/unit/loom/pipeline/planning/test_selectors.py`
  - `tests/unit/loom/pipeline/planning/test_resume.py`
  - `tests/unit/loom/pipeline/planning/test_planner.py`
  - `tests/unit/loom/pipeline/planning/test_errors.py`
- Required assertions or deferral reason:
  - `test_models.py`: `PlanReason`, `PlanSelectors`, `ResumeOptions`, `FingerprintContext`, `BoundInput`, `PendingInput`, `StageFingerprintRecord`, `ResumeCheck`, `StagePlan`, and `ExecutionPlan` reject unknown enum values, unsupported schema versions, non-plain details, and round-trip exactly through `to_dict()`/`from_dict()`.
  - `test_fingerprints.py`: mapping order does not affect fingerprints, list order does, and changes to stage name, target path, stage config, declared inputs, bound input checksum/fingerprint, output spec, Python version, `loom` version, git facts, dependency versions, and `extra` fields change fingerprints.
  - `test_fingerprints.py`: `StageSpec.resources`, run ID, artifact URI/path, `ArtifactRef.created_at`, timestamps, log paths, temp paths, and omitted git/dependency/environment data are excluded from the default payload.
  - `test_selectors.py`: unknown stages and conflicts raise `SelectorValidationError`; duplicates normalize once in topological order; allowed `force_stages` combinations behave as recorded; `from_stage` plus `only_stages` raises; `skip_stages` blocks downstream dependencies.
  - `test_resume.py`: missing status, failed/cancelled/running statuses, missing inputs, missing outputs, missing fingerprints, fingerprint policy mismatch, fingerprint digest mismatch, missing output refs, output spec mismatch, artifact validation failure, checksum mismatch, and artifact index conflicts never produce `REUSE`.
  - `test_resume.py`: corrupt run-store documents and malformed prior fingerprint records raise `ResumeStateError`, while missing optional state files become structured plan reasons.
  - `test_planner.py`: linear, branching, diamond, and fan-in DAGs produce deterministic topological `StagePlan`s, bound reusable inputs, pending inputs for upstream `RUN`, and exact invalidation/blocking reasons.
  - `test_errors.py`: `PlanPersistenceError` wraps `write_plan`/`read_plan` store failures when `persist=True`.

### Contract Suite

- Status: deferred for this phase.
- Expected paths: none.
- Required assertions or deferral reason:
  - Phase 8 must not introduce a new public structural protocol. Existing `tests/contracts/test_store_contract.py` and `tests/contracts/test_stage_contract.py` cover the protocols the planner consumes. If implementation proves a planning protocol is unavoidable, stop for the manager instead of adding a contract surface during executor work.

### Integration Suite

- Status: required.
- Expected paths:
  - `tests/integration/pipeline/test_planning_resume.py`
  - `tests/integration/pipeline/test_plan_persistence.py`
- Required assertions or deferral reason:
  - `test_planning_resume.py`: planner collaborates with `LocalRunStore` and `LocalArtifactStore` over temporary run directories without direct local-path assumptions in planning code.
  - `test_planning_resume.py`: valid prior `SUCCEEDED` state with matching `StageFingerprintRecord`, required `outputs.json`, matching output specs, and valid artifacts produces `REUSE`.
  - `test_planning_resume.py`: missing artifact files, checksum mismatches, unsupported validation, and changed fingerprints produce rerun/block reasons but no reuse.
  - `test_planning_resume.py`: corrupt store JSON and artifact index conflicts raise `ResumeStateError`.
  - `test_planning_resume.py`: `from_stage`, `only_stages`, `force_stages`, and `skip_stages` behave with stored upstream outputs and blocked downstream stages.
  - `test_plan_persistence.py`: `persist=True` writes only `plan.json`, `LocalRunStore.read_plan()` returns the inner plan mapping, and `ExecutionPlan.from_dict()` reconstructs an equivalent plan.

### E2E Suite

- Status: deferred for this phase.
- Expected paths: none.
- Required assertions or deferral reason: Phase 8 has no runner, target instantiation, local executor, CLI, or full user workflow. End-to-end synthetic pipeline execution belongs to Phase 9 after stages can actually run.

### Opt-In Suites

- Status: deferred.
- Markers affected: `slow`, `network`, `slurm`, `optional_dependency`.
- Required assertions or deferral reason: Phase 8 should be local, deterministic, standard-library plus existing dependencies, and should not require network services, SLURM, remote stores, optional dependencies, or slow acceptance tests.

## Risks

- Selector semantics can still be misimplemented if code drifts from this plan's conflict matrix. Tests must cover every allowed and rejected selector combination listed above.
- Fingerprint payloads can accidentally include noisy data or omit meaningful inputs. Tests should assert both included and excluded fields.
- Planning may be tempted to repair stale artifact indexes or corrupt state. V0 should fail or rerun conservatively rather than silently repair.
- `only_stages` can be unsafe if upstream inputs are neither runnable nor reusable. The planner must block clearly instead of implicitly widening scope.
- Artifact checksum validation may surface store errors that need wrapping for plan explanations without hiding useful file/URI context.
- Stacked Phase 8 work may need rebase/retarget maintenance after Phase 7 lands.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-integration
uv run pytest tests/unit/loom/pipeline/planning tests/integration/pipeline -q
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - planning models/errors/serialization;
  - stage fingerprint payloads and record hashing;
  - selector validation and graph selection helpers;
  - direct resume checks against store protocols;
  - topological planner and downstream invalidation;
  - plan persistence and public planning exports;
  - focused tests for each slice.
- Tests to run with each slice:
  - model/fingerprint changes: `uv run pytest tests/unit/loom/pipeline/planning/test_models.py tests/unit/loom/pipeline/planning/test_planning_fingerprints.py -q`;
  - selector/planner changes: `uv run pytest tests/unit/loom/pipeline/planning/test_selectors.py tests/unit/loom/pipeline/planning/test_planner.py -q`;
  - resume/error changes: `uv run pytest tests/unit/loom/pipeline/planning/test_resume.py tests/unit/loom/pipeline/planning/test_planning_errors.py -q`;
  - store collaboration: `uv run pytest tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py -q`;
  - exports/import boundaries: `make test-package`.
- Decisions the executor must not revisit:
  - use the exact public export names, dataclass fields, constants, reason codes, and function signatures in this plan;
  - `from_stage` and `only_stages` are mutually exclusive in v0;
  - `force_stages` cannot widen `from_stage` or `only_stages` eligibility;
  - corrupt or conflicting persisted state raises `ResumeStateError` instead of silently becoming rerunnable state;
  - pending upstream outputs produce `FingerprintStatus.PENDING_INPUTS`; Phase 8 does not invent artifact refs for stages that have not executed;
  - no execution, runner, executor, CLI, target instantiation, remote store, or cross-run cache behavior;
  - same-run-directory resume only;
  - `StageSpec.resources` excluded from default semantic fingerprints;
  - corrupt store state is not silently ignored;
  - `REUSE` requires positive evidence.
- Conditions that require stopping for the manager:
  - Phase 7 store APIs prove insufficient and would require changing the predecessor branch contract;
  - an acceptance criterion cannot be met without implementing Phase 9 runner/executor behavior;
  - implementation discovers a contradiction in the selector conflict matrix recorded here;
  - broad product or workflow files outside the Phase 8 planning scope would need edits.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-04 local time by this bounded
  `loom_phase_refiner` pass. Do not run another automated implementation
  refinement for Phase 8 without explicit user instruction.
- PR review: used. The reviewer found the blocking `from_stage` selector issue; this user-authorized post-review fix addresses it. Do not consume a second automated PR review without explicit user instruction.

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in this branch.
- Final phase execution plan: refined and decision-complete for implementation on 2026-05-04 local time.
- Implementation summary: completed locally after executor handoff attempts hit context-window tool failures before committing. Added the `loom.pipeline.planning` models, errors, fingerprinting, selector normalization, direct resume checks, topological planner, plan persistence, and exact planning exports. Added Phase 8-scoped package, unit, and integration coverage without runner/executor, CLI, remote store, or future-phase behavior.
- Implementation validation: `UV_CACHE_DIR=/tmp/uv-cache uv run python -m compileall src/loom/pipeline/planning` passed; focused Phase 8 pytest scope passed with 23 tests; `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/planning tests/package/test_pipeline_planning_api.py tests/unit/loom/pipeline/planning tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py` passed; `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` passed with 0 errors; `UV_CACHE_DIR=/tmp/uv-cache make test-package` passed with 24 tests; `UV_CACHE_DIR=/tmp/uv-cache make test-unit` passed with 271 tests; `UV_CACHE_DIR=/tmp/uv-cache make test-integration` passed with 15 tests.
- Refinement summary: completed one bounded implementation/test refinement pass.
  Fixed control-dependency invalidation so skipped or blocked upstream control
  dependencies block downstream consumers; added the planned
  `UNAVAILABLE_UPSTREAM_INPUT` reason for selected stages whose reuse-provider
  inputs are unavailable; removed duplicate selector reasons for skipped,
  outside-only, and forced stages; and added explicit `source_stage` and
  `source_output` fields to bound-input fingerprint payloads while rejecting
  undeclared bound inputs. Added focused unit/integration coverage for these
  cases.
- Refinement validation: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning/test_planning_fingerprints.py tests/unit/loom/pipeline/planning/test_planner.py tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py -q` passed with 10 tests; `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/planning tests/unit/loom/pipeline/planning tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py tests/package/test_pipeline_planning_api.py` passed; `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning tests/integration/pipeline -q` passed with 22 tests; `UV_CACHE_DIR=/tmp/uv-cache uv run pyright` passed with 0 errors; `UV_CACHE_DIR=/tmp/uv-cache make test-package` passed with 24 tests; `UV_CACHE_DIR=/tmp/uv-cache make test-unit` passed with 273 tests; `UV_CACHE_DIR=/tmp/uv-cache make test-integration` passed with 15 tests.
- PR preparation: completed on 2026-05-04 local time. The PR body artifact was refined, the branch was pushed, PR https://github.com/samcantrill/loom/pull/12 was opened against `codex/add-local-stores-run-layout`, and the initial verified PR metadata was `{"baseRefName":"codex/add-local-stores-run-layout","headRefName":"codex/add-planning-resume-selectors","state":"OPEN","url":"https://github.com/samcantrill/loom/pull/12"}`. Live PR body update used the direct GitHub API fallback after `gh pr edit --body-file` hit the GitHub Projects Classic deprecation GraphQL error.
- Stack maintenance: completed on 2026-05-04 local time after Phase 7 landed in `develop`.
  - Resolved Phase 8 rebase conflicts by preserving the merged Phase 7 store files, store tests, phase plan, and PR body artifacts from `develop`; the resulting diff against `origin/develop` contains only Phase 8 planning/resume/selector work and Phase 8 artifacts.
  - Rebased `codex/add-planning-resume-selectors` onto `origin/develop` at `bafe79261f8b6a7303a36ba8d3a9b5039a9d4728`; cleanup commit `07f8a8f` removed accidental conflict-marker text from the Phase 7 phase artifact.
  - Pushed the rebased branch with `git push --force-with-lease origin codex/add-planning-resume-selectors`.
  - Retargeted PR #12 to `develop` with `gh api --method PATCH repos/samcantrill/loom/pulls/12 -f base=develop` after `gh pr edit 12 --base develop` hit the known Projects Classic deprecation GraphQL error.
  - Rebase validation passed:
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py tests/package/test_pipeline_planning_api.py -q` — passed, 25 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` — passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 331 tests, and build succeeded.
    - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` — passed; package passed with 24 tests, unit passed with 277 tests, contract passed with 15 tests, integration passed with 15 tests, e2e not present.
- Post-review blocker fix: completed on 2026-05-04 local time after explicit user authorization.
  - Fixed the blocking `from_stage` selector review finding by forcing the selected stage to `RUN` even when direct resume found reusable prior state. The selected stage retains `REUSE` as `base_action`, records `FROM_STAGE_SELECTED`, clears `reusable_outputs`, and invalidates downstream consumers through pending upstream-output reasons.
  - Added unit and integration regressions for a reusable selected `from_stage` stage and downstream invalidation.
  - Validation after the blocker fix passed:
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning/test_planner.py tests/integration/pipeline/test_planning_resume.py -q` — passed, 8 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/planning tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py tests/package/test_pipeline_planning_api.py -q` — passed, 27 passed.
    - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` — passed; Ruff passed, Pyright reported 0 errors, default pytest passed with 333 tests, and build succeeded.
    - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` — passed; package passed with 24 tests, unit passed with 278 tests, contract passed with 15 tests, integration passed with 16 tests, e2e not present.
- Remaining blockers: none for the recorded `from_stage` PR review blocker. A separate unsupported schema-version strictness review note remains non-blocking future hardening unless explicitly pulled into this phase.

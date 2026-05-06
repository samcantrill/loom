# `loom.pipeline.planning.resume` Specification

## 1. Purpose

Resume is the policy layer that decides whether existing stage results can be
reused or must be rerun.

It exists because research pipelines are frequently interrupted, partially
completed, rerun after small config changes, or resumed after failed long-running
stages. `loom` should make those cases explicit, inspectable, and conservative.

Resume should answer:

```text
which prior stage results exist?
which results are valid for this resolved pipeline?
which stages can be reused?
which stages must rerun?
which downstream stages become stale?
which stages are blocked?
why did the planner choose each action?
```

The resume layer should not execute stages, load domain-specific checkpoints, or
repair ambiguous state silently. It should produce a deterministic execution plan
that the runner can execute and that the CLI can explain.

---

## 2. Core Position

Use this architecture:

```text
RunStore:
  persisted run state, stage status, inputs, outputs, fingerprints, artifact index

ArtifactStore:
  artifact existence and checksum verification when supported

Resume planner:
  reuse, rerun, stale, skip, and blocked decisions

Pipeline runner:
  executes the plan and records new state

Stage implementation:
  optional stage-internal resume, such as checkpoint loading
```

The central boundary is:

```text
loom pipeline resume:
  skip or rerun whole stages

stage-internal resume:
  continue work inside a stage from project-specific state
```

For example, `loom` may decide that the `train` stage must run. The training
stage may then decide to resume from `latest.ckpt` inside its stage directory.
`loom` should not implement model-specific checkpoint loading.

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) calls for fingerprints and resume logic, but v0 intentionally
keeps reuse conservative. This document refines that into same-run-directory
stage reuse decisions based on persisted state, fingerprints, and artifact
validity, leaving stage-internal checkpoint behavior to project code.

---

## 3. Package Boundary

### 3.1 `loom.pipeline.planning`

Owns execution planning.

Responsibilities:

```text
build stage plans
apply resume policy
apply selectors
compute actions and reasons
compute dependency effects
produce dry-run output data
```

### 3.2 `loom.pipeline.planning.resume`

Owns resume-specific decisions.

Responsibilities:

```text
load prior stage state summaries
compare fingerprints
check required output refs
check local artifact existence when supported
decide REUSE versus RUN versus STALE
propagate downstream invalidation
explain reuse and rerun reasons
```

### 3.3 `loom.pipeline.planning.invalidation`

Owns graph propagation rules.

Responsibilities:

```text
mark downstream stages stale when upstream outputs change
propagate blocked states
explain invalidation chains
```

Implemented as a dedicated module by Phase 5, this module keeps traversal
reason extraction typed and separate from resume I/O.

### 3.4 `loom.pipeline.stores.run_store`

Owns persisted state access.

Responsibilities:

```text
read stage status
read stage inputs
read stage outputs
read stage fingerprints
read artifact index
report corrupt or missing state files
```

The run store reports state. It should not decide semantic reuse.

### 3.5 `loom.pipeline.stores.artifact_store`

Owns artifact verification.

Responsibilities:

```text
check artifact existence
verify checksums by default when present and locally readable
resolve local paths
report unsupported URI schemes
```

### 3.6 `loom.config`

Owns config composition and artifact-safe comparison records.

Responsibilities:

```text
return in-memory resolved config to Python callers
return artifact-safe manifest/provenance/source/fingerprint records
record overlays and Python API override strings
redact secrets from public views
```

V1 config composition does not persist snapshots or write run-store state.
Resume policy should use pipeline-owned fingerprints and, where useful, the
artifact-safe config comparison records returned by `loom.config`. Those records
compare authored composition equivalence; they do not prove exact runtime
resolver-value replay.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
stage fingerprint computation
fingerprint comparison
reuse of prior successful stages
rerun of missing, failed, stale, or incomplete stages
artifact existence validation for local artifacts
stage output ref validation
downstream invalidation
resume entire pipeline
force-stage selector
from-stage selector
only-stage selector
skip-stage selector
dry-run plan explanations
conservative handling of old RUNNING stages
path-aware resume errors
```

The v0 planner should be able to explain every stage action:

```text
build_manifest  REUSE    fingerprint match
train           RUN      forced by selector
evaluate        RUN      upstream changed: train.best_checkpoint
report          BLOCKED  missing input: evaluate.metrics
```

`ExecutionPlan` remains the persisted contract used by execution. Explanatory view
models are derived in `loom.pipeline.planning.explanations` so CLI and
preflight consumers can report action and invalidation reasons without parsing
private planner internals or replaying store reads.

### 4.2 Should Not Support in v0

```text
domain-specific checkpoint loading
partial stage reuse
runtime DAG mutation
automatic repair of ambiguous state
distributed cache lookup
cross-run artifact reuse by default
remote artifact checksum validation
content-addressed global cache
advanced stale-output history
multi-writer resume coordination
```

Resume should first be correct for one local run directory. More ambitious cache
behavior can be added after local semantics are stable.

---

## 5. Terminology

### 5.1 Fresh Run

A run with no prior state used for stage reuse.

Fresh runs may still create a new run directory and write all normal state files.

### 5.2 Resumed Run

A run attempt that opens existing run state and tries to reuse valid prior stage
results.

### 5.3 Reusable Stage

A prior stage result that is safe to use for the current plan.

Required conditions:

```text
prior status is SUCCEEDED
fingerprint matches current expected fingerprint
required outputs are present
required artifacts exist when checkable
checksums verify by default when present and the store can read the URI
```

### 5.4 Stale Stage

A stage with prior results that cannot be reused.

Common reasons:

```text
fingerprint changed
upstream artifact changed
declared outputs changed
artifact missing
forced rerun
old RUNNING status
corrupt state
```

### 5.5 Blocked Stage

A stage that cannot run because a required upstream artifact is unavailable or an
upstream dependency failed or was skipped.

### 5.6 Fingerprint

A stable hash of the inputs that define a stage's output identity.

Fingerprints answer:

```text
would this stage invocation produce semantically equivalent outputs?
```

### 5.7 Checksum

A hash of stored artifact bytes.

Checksums answer:

```text
are these bytes the same bytes recorded earlier?
```

### 5.8 Selector

A user-requested stage selection policy, such as `force-stage`, `from-stage`,
`only-stage`, or `skip-stage`.

Selectors modify the plan. They should not mutate prior run state by themselves.

### 5.9 Resume Reason

A short, structured explanation for a stage action.

Examples:

```text
fingerprint match
missing prior status
prior status FAILED
fingerprint changed
missing artifact train.best_checkpoint
forced by selector
blocked by skipped upstream stage
```

---

## 6. Guiding Design Principles

### 6.1 Conservative by Default

When state is missing, corrupt, ambiguous, or unsupported, prefer rerun or fail
over unsafe reuse.

Default rule:

```text
reuse requires positive evidence
rerun handles uncertainty
fail handles impossible inputs
```

### 6.2 File Existence Is Not Enough

A stage should not be reused simply because output files exist.

Reuse requires a succeeded status and matching fingerprint. File existence is an
additional validation step, not the core policy.

### 6.3 Fingerprints Define Semantic Reuse

Fingerprints should include enough information to decide whether old outputs are
still valid for the current pipeline.

They should avoid noisy values that cause unnecessary reruns.

### 6.4 Checksums Validate Stored Bytes

Checksums should be used for artifact integrity, not as the only production
identity.

An artifact can have:

```text
same fingerprint, different checksum:
  serialization or metadata changed

same checksum, different fingerprint:
  same bytes but different production context
```

The planner should keep those concepts separate.

### 6.5 Plans Must Explain Themselves

Every action should have a reason suitable for:

```text
loom plan
logs
tests
debugging failed resumes
```

Opaque skip/rerun behavior will make users distrust resume.

### 6.6 Stage Internals Remain Project-Owned

`loom` resumes whole stages. Project code resumes inside stages.

Do not add core assumptions about:

```text
training checkpoints
optimizer state
partial dataset preprocessing
external tool restart files
```

### 6.7 Selectors Are Planning Inputs

Selectors should be applied during planning and reflected in the plan output.

Avoid implementing selectors as ad hoc runner shortcuts. The same selector should
behave the same way in `loom plan` and `loom run`.

---

## 7. Fingerprint Policy

### 7.1 Required Inputs

Recommended stage fingerprint inputs:

```text
stage name
stage target import path
stage config
declared inputs
bound input ArtifactRefs
input artifact fingerprints when available
input artifact checksums when available
declared outputs
selected resolved config subtree
explicit future opt-in runtime/resource fields that affect outputs
loom version or pipeline contract version
user-provided extra fingerprint fields
```

V0 excludes `StageSpec.resources` from semantic fingerprints by default.

### 7.2 Optional Inputs

Optional inputs can include:

```text
git commit
git dirty state
dependency versions
container image/digest
executor mode when it affects outputs
selected environment variables
```

These should be policy-driven because including too much environment data can
cause noisy reruns.

### 7.3 Values to Avoid

Do not include values that do not affect outputs:

```text
wall-clock timestamp
run directory path
temporary directory path
log path
random run ID
hostname, unless explicitly output-affecting
process ID
```

### 7.4 Stable Serialization

Fingerprint input data should be converted to plain structured data and hashed
deterministically.

Recommended behavior:

```text
sort mapping keys
preserve list order
normalize paths/URIs where documented
normalize ArtifactRefs through their serialized shape
include fingerprint algorithm version
```

### 7.5 Fingerprint Versioning

Persist:

```text
algorithm
algorithm_version
fingerprint
inputs_summary
created_at
loom_version
```

If the algorithm changes, old fingerprints should not silently compare equal
under the new algorithm. The planner should explain reruns caused by fingerprint
version changes.

---

## 8. Reuse Requirements

### 8.1 Required Prior State

To reuse a stage, the prior run state must have:

```text
stage status file
stage status SUCCEEDED
stage outputs file
stage fingerprint file
all required declared outputs
matching artifact index entries, when used
```

Missing optional files may be tolerated only if they are not needed for the
current policy.

### 8.2 Required Current State

The current plan must be able to compute:

```text
expected fingerprint
expected output declarations
expected input bindings
selected stage set
upstream actions
```

If the current pipeline spec cannot be validated, resume should not proceed.

### 8.3 Artifact Validation

For every required output:

```text
ArtifactRef exists in outputs.json
ArtifactRef artifact_type matches OutputSpec
ArtifactRef codec_key matches OutputSpec when declared
local artifact exists when URI is file://
checksum verifies when present and the store can read the URI
```

Strict validation modes are post-v0 policy extensions for additional checks
such as remote checksum verification, directory checksums, or fail-vs-rerun
behavior. They must not weaken the v0 default that readable local artifacts with
checksums are verified before reuse.

Unsupported remote URI validation should be explicit. Do not pretend a remote
artifact is valid if the current store cannot check it.

### 8.4 Artifact Index Consistency

The run-level artifact index should agree with stage outputs.

Recommended policy:

```text
if outputs.json is valid but artifacts.json is missing or stale, planner may rebuild or request repair
if artifacts.json points to an output not present in outputs.json, do not reuse without repair
if both exist and conflict, treat as corrupt or stale
```

V0 can avoid automatic repair and fail with a clear message for conflicts.

---

## 9. Stage Actions

### 9.1 Action Vocabulary

Use the same action vocabulary as pipeline planning:

```text
RUN
REUSE
SKIP
STALE
BLOCKED
```

### 9.2 `RUN`

The stage should be invoked.

Common reasons:

```text
no prior state
prior status FAILED
prior status CANCELLED
prior status RUNNING from old process
fingerprint changed
artifact missing
forced by selector
upstream changed
```

### 9.3 `REUSE`

The previous successful stage output should be used.

Required reason:

```text
fingerprint match
```

Additional details may include:

```text
all required artifacts exist
checksums verified
```

### 9.4 `STALE`

The previous result exists but cannot be reused.

`STALE` is useful in plan output. During execution, a stale stage usually becomes
`RUN` if rerun is allowed.

### 9.5 `SKIP`

The stage is intentionally excluded.

Common reasons:

```text
skip-stage selector
condition false, later
outside selected only-stage set
```

Skipping a stage may block downstream stages if their inputs cannot be satisfied.

### 9.6 `BLOCKED`

The stage cannot run now.

Common reasons:

```text
required upstream stage failed
required upstream stage skipped
required input artifact missing
only-stage selected without reusable inputs
```

Blocked should be a planning result, not a persisted successful state.

---

## 10. Downstream Invalidation

### 10.1 Invalidation Trigger

Downstream invalidation should happen when an upstream output identity changes or
is expected to change.

Triggers:

```text
upstream stage will RUN instead of REUSE
upstream stage is forced
upstream stage fingerprint changed
upstream output ArtifactRef changed
upstream artifact checksum changed under strict policy
upstream declared output set changed
```

### 10.2 Propagation

If stage `A` changes, all downstream stages that consume `A` outputs should be
replanned.

Recommended behavior:

```text
direct consumers become RUN or STALE
their downstream consumers are evaluated after updated input fingerprints are known
if a required upstream is BLOCKED, downstream becomes BLOCKED
```

### 10.3 Conservative Approximation

Before execution, the planner may not know the new artifact checksum an upstream
stage will produce.

V0 policy:

```text
if upstream will RUN, assume dependent downstream stages must RUN unless explicitly selected otherwise
```

This avoids using outputs that were generated from old upstream artifacts.

### 10.4 Explanation

Plans should name the invalidating upstream artifact when possible:

```text
evaluate  RUN  upstream changed: train.best_checkpoint
```

For fan-in stages, include all relevant changed inputs or a summarized count.

---

## 11. Selectors

### 11.1 `from_stage`

Command shape:

```bash
loom run experiment.yaml --from-stage train
```

Behavior:

```text
selected stage and all downstream stages are eligible to run
upstream stages are reused if valid
if required upstream inputs are not reusable, planning fails or upstreams must be explicitly included
```

Use case:

```text
rerun training and all evaluations after changing train config
```

### 11.2 `only_stages`

Command shape:

```bash
loom run experiment.yaml --only-stage evaluate
```

Behavior:

```text
only selected stage is eligible to run
required upstream artifacts must already be reusable
downstream stages are not run
```

Use case:

```text
debug one stage with existing inputs
```

### 11.3 `force_stages`

Command shape:

```bash
loom run experiment.yaml --force-stage train
```

Behavior:

```text
selected stage runs even if reusable
downstream consumers are invalidated
upstream stages are reused if valid
```

Use case:

```text
rerun a flaky stage or regenerate outputs
```

### 11.4 `skip_stages`

Command shape:

```bash
loom run experiment.yaml --skip-stage analyze
```

Behavior:

```text
selected stage is excluded
downstream stages that require its outputs become BLOCKED unless their inputs are otherwise satisfied
```

Use case:

```text
omit optional analysis branch
```

V0 should keep skip behavior simple. Conditional optional branches can be added
later.

### 11.5 Multiple Selectors

Multiple selectors should be validated for conflicts.

Examples:

```text
same stage in force_stages and skip_stages:
  error

only_stages evaluate and from_stage train:
  error unless explicitly defined

force_stages train and from_stage train:
  allowed, train and downstream run
```

Conflict errors should be raised before any stage executes.

---

## 12. Planning Algorithm

### 12.1 Inputs

The resume planner should receive:

```text
validated PipelineSpec
topological order
current resolved config or config fingerprint view
run store state snapshot
artifact store
resume enabled flag
selectors
fingerprint policy
```

The config input may be a pipeline-owned selected resolved view or a v1
artifact-safe config fingerprint/manifest comparison. Resume remains
pipeline-owned and must not require `loom.config` artifacts to exist.

### 12.2 High-Level Flow

Recommended flow:

```text
1. Validate selector conflicts.
2. Load prior run state snapshot.
3. Compute current expected fingerprints in topological order.
4. Evaluate direct reuse eligibility for each stage.
5. Apply selectors.
6. Propagate upstream changes and blocked states.
7. Recompute final actions and reasons.
8. Return ExecutionPlan.
```

### 12.3 Direct Reuse Check

For each stage:

```text
if resume disabled:
  action = RUN
elif prior state missing:
  action = RUN, reason = no prior state
elif prior status != SUCCEEDED:
  action = RUN or STALE, reason = prior status
elif fingerprint mismatch:
  action = RUN or STALE, reason = fingerprint changed
elif outputs invalid:
  action = RUN or STALE, reason = invalid outputs
elif artifacts missing:
  action = RUN or STALE, reason = missing artifact
else:
  action = REUSE, reason = fingerprint match
```

### 12.4 Selector Application

Selectors should be applied after basic reuse eligibility is known, because some
selectors depend on whether upstream inputs are reusable.

Example:

```text
only-stage evaluate:
  build_manifest and train are not run
  their outputs must be reusable for evaluate to run
```

### 12.5 Final Action Resolution

A stale stage usually resolves to `RUN` in an executable plan.

The plan may preserve both:

```text
base_action: STALE
action: RUN
reason: fingerprint changed
```

This keeps CLI explanations clear while giving the runner a direct action.

---

## 13. Interrupted and Corrupt State

### 13.1 Old `RUNNING` Stages

A stage left in `RUNNING` from an old process should not be reused.

Recommended behavior:

```text
if owner process is clearly live, block conflicting resume
if owner is gone or unknown, mark stage stale/incomplete
rerun if selected and inputs are available
```

### 13.2 Missing Files

Policy:

```text
missing status:
  no reusable state

missing outputs for SUCCEEDED stage:
  stale or corrupt, not reusable

missing fingerprint for SUCCEEDED stage:
  stale, not reusable

missing artifact index:
  stale or repairable, depending on outputs.json
```

### 13.3 Corrupt Files

Invalid JSON or invalid serialized refs should be treated as corrupt run state.

Default behavior:

```text
fail planning with clear error
```

Optional future behavior:

```text
--ignore-corrupt-state to rerun affected stages
repair commands for safe cases
```

Do not silently ignore corrupt state in v0.

---

## 14. Strictness Policy

V0 discusses normal and strict checks as separate policies. For v2 CLI-core,
resume behavior should be strict by default and there should be no `--strict`
CLI flag. Corrupt, ambiguous, unsupported, or unsafe prior state should fail
loudly; missing or stale reusable stage state may produce rerun decisions only
when the planner can do so safely.

### 14.1 Required Checks

Resume mode should check:

```text
status
fingerprint
declared outputs
artifact ref shape
local artifact existence when checkable
checksums for artifacts that have checksums
artifact index consistency
possibly selected environment/code provenance
```

Command shape for v2:

```bash
loom plan experiment.yaml --run-uri file:///abs/project/runs/example --resume
loom run experiment.yaml --run-uri file:///abs/project/runs/example --resume
```

### 14.2 Future Lenient Mode

A future lenient mode could allow:

```text
reuse when checksum is unsupported
rerun affected stages instead of failing on some corrupt state
```

Do not add lenient mode until strict and normal behavior are well tested.

---

## 15. Stage-Internal Resume

### 15.1 Boundary

`loom` should document, not own, stage-internal resume.

Examples:

```text
training stage loads checkpoint
preprocessing stage continues partial shard processing
external tool resumes from its own temp directory
```

### 15.2 Context Support

`StageContext` should provide stable paths that make internal resume possible:

```text
stage_dir
artifact_dir
temporary directory helper
stage_config
run metadata
```

### 15.3 Fingerprint Implications

Stage-internal resume must still produce outputs compatible with the current
stage fingerprint.

If a stage resumes from a checkpoint that was created under a different semantic
configuration, the stage implementation must reject it or handle it safely.

Core cannot validate domain-specific checkpoint compatibility.

---

## 16. Public API

Recommended API:

```python
from loom.pipeline.planning import (
    ResumePolicy,
    StageSelector,
    plan_pipeline,
)

from loom.pipeline.planning.resume import (
    compute_stage_fingerprint,
    evaluate_stage_reuse,
)
```

### 16.1 ResumePolicy

Recommended fields:

```python
@dataclass(frozen=True, slots=True)
class ResumePolicy:
    enabled: bool = False
    strict_checksums: bool = False
    verify_artifact_existence: bool = True
    treat_corrupt_state_as_error: bool = True
```

### 16.2 StageSelector

Recommended fields:

```python
@dataclass(frozen=True, slots=True)
class StageSelector:
    from_stage: str | None = None
    only_stages: frozenset[str] = frozenset()
    force_stages: frozenset[str] = frozenset()
    skip_stages: frozenset[str] = frozenset()
```

Use structured selector objects internally. CLI parsing should happen outside the
planner.

### 16.3 Reuse Result

Recommended structure:

```python
@dataclass(frozen=True, slots=True)
class StageReuseResult:
    reusable: bool
    reason: str
    expected_fingerprint: str
    prior_fingerprint: str | None
    missing_artifacts: tuple[str, ...] = ()
```

The exact fields can evolve, but tests should assert explicit reasons.

---

## 17. Future CLI Integration

Functional resume CLI behavior is not part of v1 config composition. The
examples in this section describe future CLI UX for pipeline-owned resume
planning.

### 17.1 `loom plan --resume`

Should:

```text
load or receive current pipeline config
load prior run state
compute fingerprints
evaluate reuse
show actions and reasons
not execute stages
```

Example:

```text
stage           action  reason
build_manifest  REUSE   fingerprint match
train           RUN     fingerprint changed
evaluate        RUN     upstream changed: train.best_checkpoint
report          RUN     upstream changed: evaluate.metrics
```

### 17.2 `loom run --resume`

Should use the same plan as `loom plan --resume`, then execute runnable stages.

The runner should persist the plan before execution starts.

### 17.3 Selector Commands

Supported shapes:

```bash
loom run experiment.yaml --resume --from-stage train
loom run experiment.yaml --resume --only-stage evaluate
loom run experiment.yaml --resume --force-stage train
loom run experiment.yaml --resume --skip-stage analyze
```

Multiple `--force-stage` and `--skip-stage` values may be useful. V0 can start
with one value and expand later.

### 17.4 Explanation Detail

Add a verbose mode later:

```bash
loom plan experiment.yaml --resume --explain train
```

It can show:

```text
fingerprint input diff
prior outputs
missing artifacts
upstream invalidation chain
```

Do not block v0 on detailed diff rendering.

---

## 18. Error Model

Recommended hierarchy:

```python
class ResumeError(PipelineError): ...
class FingerprintError(ResumeError): ...
class ResumeStateError(ResumeError): ...
class ResumeSelectorError(ResumeError): ...
class ResumeArtifactError(ResumeError): ...
class ResumeBlockedError(ResumeError): ...
```

### 18.1 Fingerprint Error Example

```text
Could not compute stage fingerprint.

Stage:
  train

Reason:
  stage config contains a non-serializable value at config.optimizer
```

### 18.2 Selector Error Example

```text
Conflicting stage selectors.

Stage:
  train

Reason:
  stage appears in both force-stage and skip-stage
```

### 18.3 Missing Artifact Example

```text
Cannot reuse stage.

Stage:
  train

Output:
  best_checkpoint

Reason:
  artifact is missing

URI:
  file:///runs/example/artifacts/train/best.ckpt
```

### 18.4 Blocked Stage Example

```text
Stage is blocked.

Stage:
  evaluate

Input:
  checkpoint

Reason:
  upstream stage train was skipped and no reusable artifact is available
```

---

## 19. Testing Strategy

### 19.1 Fingerprint Tests

Test:

```text
deterministic hash for same input
mapping key order does not affect hash
list order affects hash
stage config changes hash
input ArtifactRef changes hash
declared output changes hash
noisy values are excluded
algorithm version mismatch causes rerun
```

### 19.2 Reuse Tests

Test:

```text
no prior state -> RUN
SUCCEEDED with matching fingerprint -> REUSE
FAILED -> RUN
RUNNING from old process -> RUN or blocked lock error
missing outputs -> RUN/STALE
missing fingerprint -> RUN/STALE
missing artifact -> RUN/STALE
checksum mismatch when locally readable -> RUN/STALE or error
corrupt state -> error
```

### 19.3 Invalidation Tests

Use synthetic DAGs:

```text
linear
branching
diamond
fan-in
```

Test:

```text
upstream forced rerun invalidates downstream
upstream fingerprint change invalidates downstream
one branch reruns without invalidating unrelated branch
fan-in stage reruns when either input changes
blocked upstream blocks downstream
```

### 19.4 Selector Tests

Test:

```text
from-stage selects downstream
only-stage requires reusable upstream inputs
force-stage reruns selected stage and downstream
skip-stage blocks required downstream
selector conflict errors
unknown selector stage errors
```

### 19.5 CLI-Plan Tests

When functional CLI behavior exists, test the API that backs CLI output:

```text
plan reasons are stable enough for assertions
dry-run does not mutate state
run uses same planned actions as plan
```

---

## 20. Initial Implementation Plan

Build in this order:

1. Define `ResumePolicy`, `StageSelector`, and reuse result data structures.
2. Implement deterministic fingerprint input serialization and hashing.
3. Implement prior stage state loading from `RunStore`.
4. Implement direct reuse checks for one stage.
5. Add artifact existence validation through `ArtifactStore`.
6. Add default checksum validation for readable artifacts when checksums exist.
7. Integrate reuse checks into `plan_pipeline`.
8. Implement downstream invalidation for linear and branching DAGs.
9. Implement `force-stage`.
10. Implement `from-stage`.
11. Implement `only-stage`.
12. Implement `skip-stage`.
13. Add future plan reason formatting for CLI.
14. Add tests for interrupted and corrupt state.
15. Add optional verbose explanation helpers later.

Each step should include focused tests before the runner depends on it.

---

## 21. Summary

Resume should be a conservative planning policy for whole pipeline stages.

It should support:

```text
stage fingerprints
prior state inspection
safe stage reuse
rerun of stale or incomplete stages
artifact existence validation
checksum validation for readable artifacts with checksums
downstream invalidation
stage selectors
dry-run explanations
interrupted-run handling
path-aware errors
```

It should avoid:

```text
domain-specific checkpoint loading
partial stage reuse in core
file-existence-only reuse
silent repair of corrupt state
global distributed caches in v0
opaque selector behavior
```

This keeps long-running research pipelines resumable without making `loom` own
the internals of project-specific work.

# Phase 8 Execution Plan: Planning, Resume, And Selectors

## Metadata

- Status: draft phase execution plan
- Branch: `codex/add-planning-resume-selectors`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-planning-resume-selectors`
- Phase execution plan path: `docs/phases/add-planning-resume-selectors.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`
- Source phase: `Phase 8 - Planning, Resume, And Selectors`
- Stack predecessor: `codex/add-local-stores-run-layout`
- Base branch: `codex/add-local-stores-run-layout` at `889a55d58a0d47f7f26b1ae05b071178bba6ecfc`
- Target branch: `codex/add-local-stores-run-layout`
- Merge eligibility: stacked PR; reviewable against `codex/add-local-stores-run-layout`; not merge-eligible until Phase 7 lands and this branch is retargeted or rebased onto `develop`.
- Successor dependency notes: no successor branch is recorded yet. Keep this branch until the managing agent records any successor stack state or confirms it can be cleaned after merge.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no blocking findings remain in the canonical v0 plan.
- Plan quality gate loop budget: initial review used, automated plan refinement pass used, confirmation review used. Do not rerun or consume the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner` on 2026-05-04 local time.
- Refine pass: pending.
- Setup limitations: `gh auth status` initially reported an invalid token inside the sandbox, then succeeded with approved network access. `gh auth setup-git` and `git fetch origin` completed with approved access. The first sandboxed `git worktree add` could not create the branch ref under the control checkout `.git` directory and was rerun with approved filesystem access. No validation commands were run in this draft pass.
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
- Current predecessor branch or PR: `codex/add-local-stores-run-layout`, GitHub PR #11, recorded by the manager as `pr_open` with base `develop`, head `codex/add-local-stores-run-layout`, state `OPEN`.
- Why this base branch is correct: Phase 7 remains unmerged and Phase 8 depends on the Phase 7 run/artifact store contracts. The manager assignment explicitly makes the product stack base `codex/add-local-stores-run-layout` at `889a55d58a0d47f7f26b1ae05b071178bba6ecfc`.
- Retarget/rebase plan after predecessor merge: once Phase 7 lands, replay or rebase this branch onto updated `develop`, retarget the Phase 8 PR to `develop`, rerun validation, and record stack maintenance in this artifact and the PR body.
- Branch cleanup constraints: do not delete the Phase 7 predecessor branch while this branch still depends on it. Do not delete this branch until any successor branch has been retargeted or rebased away from it.

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
- Source references: `docs/implementation-plans/implementation-plan-v0.md` Phase 8; `docs/structure.md` sections "Pipeline Model and Planning", "Stores and State", "Provenance and Resume", "Runtime Dependency Policy", "Test Layout", and "Review Checklist"; `docs/loom.md` sections 9, 10, and 11; `docs/features/pipeline.md`, `docs/features/run-store.md`, `docs/features/pipeline-graph.md`, `docs/features/runtime-resources.md`, `docs/features/state.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, and `docs/features/testing.md`.

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
- Add focused package, unit, contract, and integration tests for planner imports, models, fingerprints, selectors, resume, invalidation, store collaboration, and plan persistence.

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

This draft identifies the intended contract but leaves exact dataclass names, field order, and module splits for the refine pass. The refine pass must make those decisions concrete before implementation begins.

The public behavior should be:

- `plan_pipeline(...)` accepts a validated `PipelineSpec`, a `RunStore`, an `ArtifactStore`, a run ID, selector inputs, resume policy, and explicit fingerprint context.
- It returns an `ExecutionPlan` with one `StagePlan` per stage in topological order.
- Each stage plan records stage name, action, base reuse outcome when useful, reason codes/messages, bound input `ArtifactRef`s, declared outputs, expected fingerprint record, upstream/downstream dependencies, and selector/invalidation explanation details.
- Actions use the vocabulary `RUN`, `REUSE`, `SKIP`, `STALE`, and `BLOCKED`.
- Plan actions are separate from persisted `StageStatus` values.
- The planner never imports config composition, CLI, executors, or user target-loading code.
- A persisted plan is plain-data-compatible and can be round-tripped through `RunStore.write_plan()` and `RunStore.read_plan()`.

## Design Impact

- Maintainability: keeps planning as a pure policy layer over already validated specs, graph helpers, and store protocols, avoiding runner shortcuts that would duplicate resume logic later.
- Extensibility: structured selectors, actions, reasons, fingerprints, and plan records leave room for future CLI display, remote stores, alternate executors, and stricter policies without changing stage specs.
- Domain neutrality: planner decisions are based on generic configs, artifact refs, fingerprints, checksums, and graph relationships. It does not inspect domain files, checkpoints, metrics, datasets, or models.
- Source-tree boundaries: implementation should stay under `src/loom/pipeline/planning` and related tests. It may import pipeline specs/graph/status, stores protocols, artifacts, fingerprints, provenance capture models/helpers, serialization, timestamps, and ids. It must not import CLI, executors, runner behavior, or downstream project modules.

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
| Detailed fingerprint diff rendering deferred | Phase 8 needs structured reasons and summaries, not CLI-grade verbose diff output. | When a CLI/status phase needs `loom plan --explain`-style output. |

## Reviewability

- Expected PR size and shape: one planning-focused PR adding models, fingerprint/resume/selector logic, planning exports, and focused tests. It should not include executor, runner, CLI, or broad store refactors.
- Files and areas to inspect:
  - `src/loom/pipeline/planning/`
  - `src/loom/pipeline/planning/__init__.py`
  - package API/import-boundary tests for planning
  - `tests/unit/loom/pipeline/planning/`
  - `tests/contracts/` if a planning or policy protocol is added
  - `tests/integration/pipeline/` for planner plus Phase 7 store behavior
- Scope-control checks:
  - no root `loom.__init__` planning exports;
  - no functional CLI additions;
  - no stage target instantiation or execution;
  - no new runtime dependencies;
  - no remote/cross-run cache behavior;
  - planner imports stay away from `loom.config`, `loom.cli`, executors, and project code unless a refine-pass decision explicitly justifies a narrow exception.

## Implementation Steps

1. Define planning error types, action/reason enums or constants, selector/resume policy models, fingerprint record/payload models, reuse result models, `StagePlan`, and `ExecutionPlan`.
2. Implement plain-data serialization and deserialization for plan and fingerprint records, including validation of action values, selector fields, and fingerprint metadata.
3. Implement selector validation against `PipelineSpec.stage_names`, including conflicts between `skip_stages`, `force_stages`, `from_stage`, and `only_stages`.
4. Implement stage fingerprint payload construction from deterministic stage/spec/input/context fields, then hash with existing `hash_mapping`.
5. Implement prior stage state loading through `RunStore`, with explicit missing, incomplete, corrupt, failed, stale, and succeeded summaries.
6. Implement direct reuse checks for one stage using prior status, prior/current fingerprint comparison, prior outputs, output specs, artifact index consistency as appropriate, and `ArtifactStore.validate()`.
7. Implement topological `plan_pipeline()` flow: build graph, resolve bindings, compute or load upstream input refs, evaluate reuse, apply selectors, propagate downstream invalidation/blocking, and produce ordered plans.
8. Persist the computed execution plan through `RunStore.write_plan()` when requested and verify `RunStore.read_plan()` returns a plain-data equivalent.
9. Export the public planning API from `loom.pipeline.planning` and add import-boundary/package tests.
10. Add targeted unit, contract as needed, and integration tests before PR preparation runs the full validation gate.

## Test Plan

### Package Suite

- Status: required.
- Expected paths:
  - `tests/package/test_pipeline_planning_api.py`
  - update `tests/package/test_import_boundaries.py` if needed.
- Required assertions or deferral reason:
  - `loom.pipeline.planning` exports only the Phase 8 public planning API.
  - Importing `loom` remains cheap and does not import planning.
  - Importing `loom.pipeline.planning` does not import CLI, executors, config composition, or project modules.

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
  - plan/fingerprint serialization round-trips through plain data;
  - mapping order does not affect fingerprints, list order does, and stage config/target/output/input changes affect fingerprints;
  - noisy values and `StageSpec.resources` are excluded from default fingerprints;
  - selector conflict and unknown-stage errors are path/stage aware;
  - prior missing, failed, running, missing outputs, missing fingerprints, checksum mismatch, and missing artifact states do not produce `REUSE`;
  - linear, branching, diamond, and fan-in invalidation decisions are deterministic.

### Contract Suite

- Status: required if Phase 8 introduces a public structural protocol; otherwise deferred.
- Expected paths:
  - `tests/contracts/test_planning_contract.py` if a public planning/fingerprint policy protocol is added.
- Required assertions or deferral reason:
  - If no protocol is added, existing store and stage contract suites cover the extension points Phase 8 consumes. The phase should document this deferral in the PR body.

### Integration Suite

- Status: required.
- Expected paths:
  - `tests/integration/pipeline/test_planning_resume.py`
  - `tests/integration/pipeline/test_plan_persistence.py`
- Required assertions or deferral reason:
  - planner collaborates with `LocalRunStore` and `LocalArtifactStore` over temporary run directories;
  - valid prior succeeded state with matching fingerprints and valid artifacts produces `REUSE`;
  - corrupt store JSON raises a planning/store error;
  - plan files persist and read through `LocalRunStore`;
  - selectors behave with stored upstream outputs and blocked downstream stages.

### E2E Suite

- Status: deferred for this phase.
- Expected paths: none.
- Required assertions or deferral reason: Phase 8 has no runner, target instantiation, local executor, CLI, or full user workflow. End-to-end synthetic pipeline execution belongs to Phase 9 after stages can actually run.

### Opt-In Suites

- Status: deferred.
- Markers affected: `slow`, `network`, `slurm`, `optional_dependency`.
- Required assertions or deferral reason: Phase 8 should be local, deterministic, standard-library plus existing dependencies, and should not require network services, SLURM, remote stores, optional dependencies, or slow acceptance tests.

## Risks

- Selector semantics can become ambiguous when multiple selectors combine. The refine pass must lock conflict rules before implementation.
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
make test-contract
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
  - model/fingerprint changes: `uv run pytest tests/unit/loom/pipeline/planning/test_models.py tests/unit/loom/pipeline/planning/test_fingerprints.py -q`;
  - selector/planner changes: `uv run pytest tests/unit/loom/pipeline/planning/test_selectors.py tests/unit/loom/pipeline/planning/test_planner.py -q`;
  - store collaboration: `uv run pytest tests/integration/pipeline/test_planning_resume.py tests/integration/pipeline/test_plan_persistence.py -q`;
  - exports/import boundaries: `make test-package`.
- Decisions the executor must not revisit:
  - no execution, runner, executor, CLI, target instantiation, remote store, or cross-run cache behavior;
  - same-run-directory resume only;
  - `StageSpec.resources` excluded from default semantic fingerprints;
  - corrupt store state is not silently ignored;
  - `REUSE` requires positive evidence.
- Conditions that require stopping for the manager:
  - Phase 7 store APIs prove insufficient and would require changing the predecessor branch contract;
  - an acceptance criterion cannot be met without implementing Phase 9 runner/executor behavior;
  - selector conflict semantics remain ambiguous after the refine pass;
  - broad product or workflow files outside the Phase 8 planning scope would need edits.

## Refinement And Review Budget Status

- Phase implementation refinement: unused.
- PR review: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner` in this branch.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- PR preparation: pending.
- Stack maintenance: pending Phase 7 merge/rebase or retarget decision.
- Remaining blockers: none.

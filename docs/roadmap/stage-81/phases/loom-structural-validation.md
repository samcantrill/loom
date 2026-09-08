# Phase 11 Execution Plan: Loom Structural Validation Ownership

## Metadata

- Status: approved
- Roadmap stage and phase: rphys 81, Loom owner phase 11
- Manifest: [implementation-plan.md](../implementation-plan.md)
- Branch: `agent/stage-81-p11-loom-structural-validation`
- Worktree: `/nas/home/can134/work/loom-worktrees/stage-81-p11-loom-structural-validation`
- Base revision: published Loom `cf9e2850476e4526c4884e34412c26e38de08b6e`
- PR target: `develop` in `samcantrill/loom`
- PR title: `Stage 81 Causal Failure Propagation And Deferred Retained Smoke - Phase 11: Loom Structural Validation Ownership`
- Dependencies: approved rphys diagnostic amendment; serialized after merged
  rphys P13. No semantic dependency on Stage 85 deployment adoption.
- Workflow path: ordinary implementation; independent review explicitly required
  by the approved public-removal contract. No further startup planning pass.
- Blockers: none; bounded fresh-import and constructor-cause test correction
  completed at `e4150d13e65ef8e4ed38b5a9d38fac9c0f459ab1`

## Objective And Context

`loom validate` must validate the graph and Loom-owned runtime/resource settings,
without an option that imports or constructs configured project factories merely
to check them. Downstream owners construct and validate their project objects.
Execution still performs real stage construction and checks the returned stage
interface. This removal is independently useful and must not require the later
diagnostic endpoint or reference dependency pin.

Canonical fixed contract:
[DD-81-23 and FR-81-29](https://github.com/samcantrill/rphys/blob/71970865ca5356335f3edc7108e3adf7369841e2/docs/roadmap/stage-81/planning/diagnostic-failures.md#structural-validation-ownership--dd-81-23).
The manager has verified this section; consult it for an actual contract question,
not an unrelated planning history or a new phase-design exercise.

## Current Source And Harness

At the base, `pipeline/validation.py` defines the static `PipelineValidationResult`
and `validate_pipeline_config`, plus the construction-only
`PipelineTargetCheckResult` and `check_pipeline_stage_targets`. The latter calls
`stage_factory.construct_stage` and discards the result. Pipeline public exports
expose both checker symbols.

`cli/validate.py` registers `--check-targets`, emits `TARGET_CHECK_WARNING`, and
calls pipeline and Weave target checkers. It creates a non-pipeline view for
generic checks. `ValidateCliOptions` in `cli/options.py` exists solely for this
flag. `ValidationCliResult` in `cli/results.py` includes `check_targets` and
`target_count`. The validation schema is currently `loom.cli.validate.v2`.
Remove exclusive eager-check helpers/imports/exports with their last consumer;
do not leave empty option scaffolding. Static factory-path facts are plain
structural data, not eager checking; do not widen the public removal merely
because their names mention targets. Unrelated diagnostics `target_count` fields
count preflight targets and retain their own contract.

Known tests: `tests/unit/loom/cli/test_validate.py`, `test_options.py`,
`tests/unit/loom/pipeline/test_pipeline_validation.py`, `test_stage_factory.py`,
`tests/package/test_pipeline_api.py`, `tests/integration/config/test_cli_validate.py`
and `tests/e2e/test_cli_core.py`. The real config integration tests have the
optional-dependency marker and must execute in the config-extra gate. Existing
construction fixtures include side-effect probes; reuse them where appropriate.
README and `docs/features/cli.md` currently advertise the option.

`make validate-pr` runs Ruff, Pyright with config extras, isolated default and
config-extra tests, then distribution builds. `make test-summary` runs/report
groups separately with JUnit/coverage. Both are required by Loom; do not treat
one as a substitute for the other or modify the harness to simplify this phase.

## Scope And Fixed Contracts

1. Remove `--check-targets`, the two eager pipeline checker symbols, their public
   exports, exclusive CLI helpers/option record, construction warning and removed
   result/count fields. Search exact names and dotted/dynamic references across
   source, tests, maintained config/examples and docs before deleting symbols.
2. Cut the validation JSON schema to `loom.cli.validate.v3`, with no removed
   fields or no-op compatibility option. Preserve unrelated envelope/error
   conventions and static success text. Removed-flag use fails visibly as
   unsupported usage; help explains that project owners perform construction
   and readiness checks.
3. Keep Weave composition and its public APIs, explicit plugin activation,
   pipeline parsing, graph validation, Loom resource/runtime option checks and
   actual `construct_stage`/runner/worker interface checks. Config composition
   is trusted code; do not promise that explicit plugins import nothing.
4. Nested target-shaped project values stay data at Loom's static boundary.
   A missing or failing target module/constructor is not a static validation
   failure merely because execution would later fail.
5. Preserve useful actual-construction coverage by locating it at the execution
   owner. Do not retain a constructor checker just to make its old tests pass.
   Downstream reference tests/pins migrate in rphys P8, not in this Loom phase.

Out of scope: new validation abstractions, Weave changes, resource-policy changes,
Loom inspection diagnostics, Stage 85, rphys edits, process/lifecycle redesign,
public safety redaction changes, physical data/GPU/container/SLURM runs or hosted CI.

## Proportionality And Invariant Ownership

This phase removes machinery and adds no schema beyond the approved CLI result
hard cut, loader, registry or durable state. Public parsing/graph/resource owners
continue to validate their own invariants; execution owns construction. Private
helper deletion, imports and test fixture layout are discretionary. Preserve
completed roadmap history; update maintained operational instructions in place.

| Invariant | Boundary and consequence | Required coverage |
| --- | --- | --- |
| Static validation does not eagerly import/construct project targets | CLI/public static validation would otherwise run arbitrary project initialization | A side-effecting/failing target remains untouched under static validation |
| Actual execution still constructs and fails informatively | Removing too much would break real execution or hide constructor causes | Existing execution factory/runner assertion plus the static-versus-execution regression |
| Graph/resource checks remain authoritative | Static acceptance of malformed Loom structure would fail later incorrectly | Existing malformed graph and runtime/resource rejection cases |
| CLI/public hard cut is complete | Old flag/export/count output could preserve a misleading supported checker | Removed usage/export tests and exact v3 JSON/text assertions |

## Implementation Slices And Validation

1. Remove the eager pipeline/public and CLI implementation together.
2. Migrate API/CLI assertions and retain actual construction behavior at its owner.
3. Add the discriminating static-versus-execution case and refresh user help/docs.
4. Finish scoped changes, run targeted tests while developing, then both final
   gates on a stable revision; inspect skips and exact outcomes.

Select the known unit/package owners above and the config-backed integration/e2e
owners in their existing environments. Include import and constructor side
effects, nested target-shaped data, invalid Loom graph/resource input, unknown
removed option, exact result shape and real execution cause preservation. Avoid
an unsupported cross-product of backends or factory shapes.

Final commands:

```sh
make validate-pr
make test-summary
```

Record full commands, revision/tree, reports, raw JUnit/logs, outcomes and all
skipped/unavailable tests. No physical gate is required. Optional skips must not
stand in for the required config-extra behavior. Expand only for a real affected
consumer; do not remove coverage or pin a different dependency to obtain a pass.

## Risks, Review And Executor Handoff

The deliberate public/API removal requires downstream migration when P8 adopts
the published Loom revision. No compatibility flag or shadow result is desired.
Independent review must inspect removal completeness, unchanged structural and
execution ownership, optional config coverage and the actual PR head. Stop only
for a concrete conflict in approved behavior, a missing dependency/contract,
failed required validation, or overlap with another owner's work.

Read this plan from Current Source And Harness through this handoff, plus the
manifest's shared constraints. Own only the named implementation, current
consumers, tests/docs and this plan's completion record. You are not alone;
preserve others' edits. Do not edit the manifest, rphys, Stage 39 resource draft,
Stage 85, workflows, dependencies, or other worktrees. No subagents, PR creation,
merge or physical runs. Return coherent commits, a clean tree and terminal
revision-bound validation evidence. Manager owns PR/review/delivery and metadata.

## Workflow State And Completion

- Manager preparation: complete at published base; canonical readiness reused.
- Expanded planning: not needed; no affected contract drift.
- Implementation: complete at `badf364a02f2d2cdaf2f8d657763708ad44ebe18`,
  with the required boundary-test correction at
  `e4150d13e65ef8e4ed38b5a9d38fac9c0f459ab1`.
- Refiner: unused; blocker correction 1/3 completed by the executor's one
  directly related repair.
- Independent review: passed with no findings on actual PR #287 head
  `d222e7b9186bb3954e4f2da10798344512a3aae7`, base `cf9e285`.
- PR: [#287](https://github.com/samcantrill/loom/pull/287), open, non-draft,
  mergeable, exact approved title and target `develop`; merge and cleanup pending.

Manager pre-submit verification: the corrected source/test revision is
`e4150d13e65ef8e4ed38b5a9d38fac9c0f459ab1`, tree
`3ce81dcb2413cb3982dda46c65bc472712cef3b4`. The delta to executor completion
`646224d2580b349b75e376b704fe2c15a52c8303` is this card only. Manager parsed the
six raw JUnit reports: 3,172 passes, no failures/errors, the same 18 opt-in
physical/container skips, and both new fresh-target cases executed successfully.
The correction closes the named acceptance gap without runtime changes. Current
Loom `origin/develop` remains `cf9e285`; no dependency/build or other source drift
invalidates the gates. Scope and removal search passed; independent PR review
is the remaining pre-merge gate. These receipt edits are validation-irrelevant.

Independent review completed read-only under the configured Loom phase reviewer:
no findings, merge eligible. It verified removal completeness, exact v3 output,
unchanged structural/runtime validation and actual construction, fresh-target
coverage, both gate receipts and the actual PR body/head. The manager verified
the result; the only residual risk is deliberate downstream CLI/API adoption.
The reviewer requested no correction or confirmation. This review/status receipt
changes only the two local owner documents; source/tests are identical to the
reviewed head and the corrected validated tree, so both receipts carry forward.

Retained evidence copy, verified byte-for-byte before worktree cleanup:
`/nas/home/can134/work/loom-worktrees/stage-85-control/build/stage81-p11-e4150d1/`.
It contains `test-summary.md`, all six JUnit/coverage groups under `test-summary/`,
and built distributions under `dist/`. The original report's command paths name
the execution worktree; this copy preserves that evidence without rewriting it.

### Manager Pre-submit Correction

The initial static tests observe constructors in modules already imported by the
test process. The actual-run regression uses `NotAStage` and checks its interface
error; existing `test_stage_factory.py` does not assert an import side effect or
an original constructor cause. This leaves the approved static-versus-execution
oracle incomplete: eager import could execute project initialization undetected,
and loss of a constructor's cause would not fail these tests.

Smallest correction: add a fresh project-target regression through real CLI
composition/static validation and the actual construction owner. Prove static
validation does not import or construct it, execution does, and the original
constructor cause survives. Keep existing interface and nested-data tests.
Own only the required test fixture/assertions and this completion record; no
runtime change or broader validation API is needed unless the regression fails.
Run the focused config/constructor selection, then refresh both required Loom
gates on the stable corrected test tree. Preserve prior evidence as historical.

Manager inspected all initial JUnit skips: 13 opt-in Apptainer namespace timeout
cases and five opt-in Docker/Apptainer smoke/build/resource cases. They are not
P11 requirements. Required config-backed validation and the actual-run interface
test executed and passed. No physical acceptance is inferred from these results.
The correction completed without a runtime change; its fresh focused and final
gate evidence follows.

## Executor Completion Record

| Item | Evidence |
| --- | --- |
| Implementation and changed paths | `badf364a02f2d2cdaf2f8d657763708ad44ebe18` removes `--check-targets`, the eager pipeline checker and exports, its exclusive CLI option/warning/helpers, and removed validation-result fields. `loom validate` now emits `loom.cli.validate.v3`, preserves composition, graph and resource/runtime validation, and directs construction/readiness to project execution. `e4150d13e65ef8e4ed38b5a9d38fac9c0f459ab1` adds the admitted test-only repair in `tests/integration/config/test_cli_validate.py` and `tests/unit/loom/pipeline/test_stage_factory.py`; no runtime source changed. |
| Boundary coverage | Historical focused selections passed: `65 passed` for validate/options/pipeline API and execution owners, and `19 passed` for config-backed validate/CLI e2e. The correction-focused selection passed: `8 passed` for the stage factory owner and `3 passed` for real config-backed CLI validation. The fresh static target remains absent from `sys.modules` and produces no import/constructor marker; the fresh construction target records import plus construction and preserves its original `ProjectConstructorError` cause. Existing nested-data and interface cases remain in place. |
| Final gates and validated tree | Historical `badf364a02f2d2cdaf2f8d657763708ad44ebe18` receipt is superseded for validation by clean corrected revision `e4150d13e65ef8e4ed38b5a9d38fac9c0f459ab1`. On that revision, `make validate-pr` passed Ruff, Pyright (0 errors), default harness (`3,011 passed`, `155 deselected`), config-extra harness (`161 passed`, `18 skipped`, `3,014 deselected`), and `uv build`, producing `dist/loom-0.1.0.tar.gz` and `dist/loom-0.1.0-py3-none-any.whl`. `make test-summary` passed: 3,172 passed, 0 failed, 0 errors, 18 skipped, and 3,148 deselected (3,190 total). No physical, container, GPU, or SLURM acceptance gate was run or required. |
| Raw reports and logs | Summary: `build/test-summary.md`. JUnit: `build/test-summary/package/junit.xml`, `build/test-summary/unit/junit.xml`, `build/test-summary/contract/junit.xml`, `build/test-summary/integration/junit.xml`, `build/test-summary/e2e/junit.xml`, and `build/test-summary/config-extra/junit.xml`. Coverage JSON: `build/test-summary/package/coverage.json`, `build/test-summary/unit/coverage.json`, `build/test-summary/contract/coverage.json`, `build/test-summary/integration/coverage.json`, `build/test-summary/e2e/coverage.json`, and `build/test-summary/config-extra/coverage.json`; raw coverage data is in the matching six `.coverage` paths. `make validate-pr` has no persistent raw-log artifact; its build outputs above are retained as ignored local evidence. |
| Validation-relevant changes after evidence | `e4150d13e65ef8e4ed38b5a9d38fac9c0f459ab1` adds only the approved fresh-target test oracle. All final evidence above was refreshed after that change; this completion-record update is documentation-only. |
| Residual risk and blocker | No implementation blocker. The deliberate incompatible CLI/API removal requires separate downstream adoption; independent review remains required before manager PR delivery. |

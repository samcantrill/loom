# Phase 11 Execution Plan: Loom Structural Validation Ownership

## Metadata

- Status: in_progress
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
- Blockers: none

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
- Implementation: complete at `badf364a02f2d2cdaf2f8d657763708ad44ebe18`.
- Refiner: unused; blocker corrections 0/3.
- Independent review: required after implementation and local gates.
- PR, merge and cleanup: pending; no runtime validation claimed yet.

## Executor Completion Record

| Item | Evidence |
| --- | --- |
| Implementation and changed paths | `badf364a02f2d2cdaf2f8d657763708ad44ebe18` removes `--check-targets`, the eager pipeline checker and exports, its exclusive CLI option/warning/helpers, and removed validation-result fields. `loom validate` now emits `loom.cli.validate.v3`, preserves composition, graph and resource/runtime validation, and directs construction/readiness to project execution. Updated paths are `src/loom/{cli/{options.py,results.py,validate.py},pipeline/{__init__.py,validation.py}}`, their affected unit/package/integration/e2e tests, `README.md`, and `docs/features/cli.md`. |
| Boundary coverage | Focused default selection passed: `65 passed` across validate/options/pipeline API and execution construction owners. Focused config-extra selection passed: `19 passed` across config-backed validate and CLI e2e owners. The added boundary cases prove static validation leaves generic and nested target-shaped values untouched, an invalid project target remains statically valid, and real execution retains the informative stage-interface failure. |
| Final gates and validated tree | On clean implementation revision `badf364a02f2d2cdaf2f8d657763708ad44ebe18`, `make validate-pr` passed Ruff, Pyright, default/config-extra harnesses, and `uv build`; it produced `dist/loom-0.1.0.tar.gz` and `dist/loom-0.1.0-py3-none-any.whl`. `make test-summary` passed: 3,170 passed, 0 failed, 0 errors, 18 skipped, and 3,147 deselected (3,188 total). No physical, container, GPU, or SLURM acceptance gate was run or required. |
| Raw reports and logs | Summary: `build/test-summary.md`. JUnit: `build/test-summary/package/junit.xml`, `build/test-summary/unit/junit.xml`, `build/test-summary/contract/junit.xml`, `build/test-summary/integration/junit.xml`, `build/test-summary/e2e/junit.xml`, and `build/test-summary/config-extra/junit.xml`. Coverage JSON: `build/test-summary/package/coverage.json`, `build/test-summary/unit/coverage.json`, `build/test-summary/contract/coverage.json`, `build/test-summary/integration/coverage.json`, `build/test-summary/e2e/coverage.json`, and `build/test-summary/config-extra/coverage.json`; raw coverage data is in the matching six `.coverage` paths. `make validate-pr` has no persistent raw-log artifact; its build outputs above are retained as ignored local evidence. |
| Validation-relevant changes after evidence | None. This completion-record update is documentation-only and does not alter the validated source/test/dependency/build configuration tree. |
| Residual risk and blocker | No implementation blocker. The deliberate incompatible CLI/API removal requires separate downstream adoption; independent review remains required before manager PR delivery. |

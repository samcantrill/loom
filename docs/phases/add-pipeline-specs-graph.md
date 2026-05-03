# Phase 6 Execution Plan: Pipeline Specs And Graph

## Metadata

- Status: draft phase execution plan
- Branch: `codex/add-pipeline-specs-graph`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-pipeline-specs-graph`
- Phase execution plan path: `docs/phases/add-pipeline-specs-graph.md`
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`
- Source phase: `Phase 6 - Pipeline Specs And Graph`
- Stack predecessor: `codex/add-recipes-instantiation`
- Base branch: `codex/add-recipes-instantiation` at `7ede758210f75c8a448b922af4c6034e7619bddb`
- Target branch: `codex/add-recipes-instantiation`
- Merge eligibility: stacked PR is reviewable against `codex/add-recipes-instantiation`; not merge-eligible until Phase 5 lands and Phase 6 is retargeted or rebased onto `develop`.
- Successor dependency notes: no known successor branch depends on Phase 6 yet. Keep the Phase 6 branch until any later stacked successor has been retargeted or rebased away from it.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers are recorded in the canonical v0 plan.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not rerun the plan-quality gate for this phase.
- Draft pass: completed by `loom_phase_planner` for this artifact.
- Refine pass: pending.
- Setup limitations: `gh auth status` reports the configured `samcantrill` token is invalid, so remote synchronization was unavailable in this draft pass. The worktree was created from the local recorded predecessor branch, not from `develop`. The first sandboxed worktree creation attempt could not create the nested `codex/add-pipeline-specs-graph` ref because git metadata was exposed read-only; the approved rerun created the branch and worktree successfully.
- Blockers: none for local phase planning.

## Objective

Implement the static pipeline model before any persistent state or execution side effects exist. This phase defines frozen pipeline, stage, and output specs; the structural stage contract and minimal stage context; stage/run status values and serializable status records; strict `stage.output` input binding helpers; and pure graph validation/traversal helpers.

The phase must turn resolved config pipeline shapes into validated static specs while keeping target instantiation, stage execution, artifact path allocation, run stores, resume planning, CLI behavior, and runner semantics out of scope.

## Full-Plan Context

Phases 1 through 5 established the import-safe package skeleton, primitives, serialization, I/O, config composition, recipes, and trusted `_target_` instantiation helpers. Phase 6 consumes resolved config data but does not instantiate stage targets and does not write run state.

Later phases depend on this static contract:

- Phase 7 adds local run/artifact stores and persisted run layout.
- Phase 8 adds planning and same-run-directory resume decisions.
- Phase 9 wires local in-process execution, stage target construction, context helpers, status writes, and output validation.
- Phase 10 hardens error messages across subsystems.

Future-phase work that must remain out of scope includes persistent stores, stage target construction, runner lifecycle, selectors, resume decisions, artifact save/register helpers, output path allocation, config persistence, CLI commands, remote stores, subprocess/SLURM execution, runtime profiles, retry policies, conditional `when` logic, and any domain-specific stage behavior.

## Stack Context

- Root or stacked phase: stacked phase.
- Current predecessor branch or PR: `codex/add-recipes-instantiation`, recorded locally as Phase 5 `pr_open` with PR https://github.com/samcantrill/loom/pull/8.
- Why this base branch is correct: Phase 5 is the nearest earlier unmerged phase and includes the committed config recipe/instantiation work that Phase 6 should build on.
- Retarget/rebase plan after predecessor merge: once Phase 5 lands, rebase or replay `codex/add-pipeline-specs-graph` onto updated `develop`, retarget the Phase 6 PR to `develop`, rerun validation, and record the stack maintenance in this artifact or PR body.
- Branch cleanup constraints: do not delete `codex/add-recipes-instantiation` until Phase 6 is rebased or retargeted away from it; do not delete `codex/add-pipeline-specs-graph` while any later successor branch depends on it.

## Source Phase Summary

- Goal: implement the static pipeline model, stage contract, status types, and pure graph validation before persistent stores and execution.
- Required scope:
  - Add `OutputSpec`, `StageSpec`, and `PipelineSpec` frozen dataclasses.
  - Add the `Stage` structural protocol and minimal `StageContext`.
  - Add stage/run status values and serializable status records.
  - Parse documented pipeline, stage, and output shapes from resolved config.
  - Support strict `stage.output` input references.
  - Distinguish data dependencies from control-only `depends_on`.
  - Build graph helpers for dependencies, cycle detection, upstream/downstream sets, and topological sorting.
  - Reject unknown and deferred orchestration fields with clear errors.
- Required checkpoints:
  - Preserve authored stage order in specs while validating execution order through graph helpers.
  - Store stage `_target_` as `target_path`; store authored `config` as `stage_config`.
  - Keep `StageContext` minimal: IDs, paths, resolved config, stage config, provenance, and metadata.
  - Keep resources as opaque plain-data-compatible metadata.
  - Keep status modeling serializable and minimal until store and runner phases prove more states are needed.
- Acceptance criteria:
  - Documented inline stage YAML shape parses correctly.
  - Unknown stage-level orchestration keys are rejected.
  - Deferred fields such as stage `runtime`, `retry`, `when`, stage metadata, and output `path` fail clearly.
  - Duplicate stages, missing outputs, bad output specs, bad refs, unknown stages, unknown outputs, cycles, and self-dependencies fail clearly.
  - Topological sort works for linear, branching, and diamond DAGs.
  - Dummy stages satisfy the stage protocol without inheritance.

## Current Source And Harness Findings

- `src/loom/pipeline/__init__.py`, `src/loom/pipeline/graph/__init__.py`, `src/loom/pipeline/planning/__init__.py`, `src/loom/pipeline/execution/__init__.py`, `src/loom/pipeline/executors/__init__.py`, and `src/loom/pipeline/stores/__init__.py` are import-safe skeletons.
- `src/loom/errors.py` already exposes broad `PipelineError`; Phase 6 should add pipeline-specific errors without breaking the broad root error hierarchy.
- `src/loom/artifacts.py` provides `ArtifactRef`, which the stage protocol can reference without pulling in stores or execution.
- `src/loom/serialization/plain.py` provides `PlainData` and `ensure_plain_data`; Phase 6 should reuse this for spec/status metadata and resources instead of inventing another plain-data checker.
- `src/loom/protocols.py` contains only package-wide generic protocols. The `Stage` protocol belongs under `loom.pipeline.stage`, not in `loom.protocols`.
- Package import-boundary tests assert that `import loom` does not import `loom.pipeline`, `loom.config`, or `loom.cli`. Phase 6 must preserve that root import behavior.
- Existing tests have package, unit, contract, and integration suites. There is no `tests/e2e` directory yet, and opt-in external suites are not part of the current harness.

## In-Scope Work

- Add pipeline-specific errors for validation, graph cycles, artifact binding, and stage contract checks, all inheriting from `PipelineError`.
- Add `OutputSpec`, `StageSpec`, and `PipelineSpec` as frozen dataclasses with validation and `from_dict`/`from_config` style construction from plain resolved config mappings.
- Add the public `Stage` protocol under `loom.pipeline.stage`, using `run(context: StageContext, inputs: Mapping[str, ArtifactRef]) -> Mapping[str, ArtifactRef]`.
- Add minimal `StageContext` under `loom.pipeline.context` with run/stage IDs, run/stage paths, resolved config, stage config, provenance, and metadata.
- Add `RunStatus`, `StageStatus`, `RunStatusRecord`, `StageStatusRecord`, and serialization helpers under `loom.pipeline.status`.
- Add binding helpers for strict `stage.output` references and resolved input bindings.
- Add pure graph helpers under `loom.pipeline.graph` for graph construction, direct and transitive dependency queries, cycle detection, and deterministic topological sorting.
- Add public pipeline package exports for Phase 6 API symbols while keeping `loom.__init__` unchanged.
- Add package, unit, contract, and integration coverage for the static pipeline model and graph behavior.

## Out-of-Scope Work

- No persistent stores, run directory layout implementation, config persistence, status file I/O, or artifact path allocation.
- No resume planning, stale/reuse decisions, selector handling, or same-run-directory cache behavior.
- No stage target import/instantiation policy for pipelines, no target constructor calls, and no use of Phase 5 generic `instantiate()` to build stages.
- No stage execution, runner behavior, executor behavior, preflight command, CLI behavior, or PR body creation.
- No store-backed `StageContext` helpers such as `artifact_store`, `run_store`, `output_path`, `artifact_path`, `save_artifact`, or `register_artifact`.
- No runtime profiles, retry behavior, conditional `when`, stage-level metadata, output paths, optional outputs, external input specs, literal pipeline inputs, dynamic DAG mutation, graph visualization, or domain-specific stages.
- No changes to top-level `loom.__init__` public exports.

## Assumptions

- The local predecessor branch at `7ede758210f75c8a448b922af4c6034e7619bddb` is the correct Phase 6 base because remote synchronization is unavailable and the manager supplied that stack state.
- Resolved config is trusted plain project config, but Phase 6 still validates the pipeline schema strictly so future execution phases receive a stable contract.
- `PipelineSpec.from_config()` or equivalent parser receives the `pipeline` mapping from the already resolved config, not a file path and not raw YAML text.
- Stage and output names should not contain dots in v0 so `stage.output` references are unambiguous.
- `depends_on` creates control edges only; input bindings create data edges and resolved artifact binding records.
- Stage `resources`, pipeline metadata, output metadata, status metadata, owner metadata, and context metadata must be plain-data-compatible when stored in Phase 6 model objects.
- Status transition helpers are optional for this phase unless they remain small and purely in-memory; runner-owned transition policy can wait for execution phases.

## Decision-Complete Contract

Phase 6 owns the public static pipeline contract exposed through `loom.pipeline` and `loom.pipeline.graph`. The executor must not redesign these boundaries into runtime behavior.

Expected module boundaries:

- `loom.pipeline.specs`: `OutputSpec`, `StageSpec`, `PipelineSpec`, parsing and validation helpers.
- `loom.pipeline.stage`: `Stage` structural protocol.
- `loom.pipeline.context`: minimal `StageContext`.
- `loom.pipeline.status`: run/stage status values, status records, and plain serialization helpers.
- `loom.pipeline.errors`: pipeline-specific errors that inherit from `loom.errors.PipelineError`.
- `loom.pipeline.graph.bindings`: artifact reference parsing and input binding resolution.
- `loom.pipeline.graph.dag`: graph dataclasses and dependency query helpers.
- `loom.pipeline.graph.topology`: cycle detection and deterministic topological sort.

Config parsing contract:

- Pipeline mapping supports only `stages`, optional `name`, optional `description`, optional `metadata`, and optional `schema_version` defaulting to `None`.
- Authored `pipeline.defaults` and unknown pipeline-level orchestration keys fail clearly.
- Stage mappings support only `name`, `_target_`, `config`, `depends_on`, `inputs`, `outputs`, and `resources`.
- Unknown stage-level keys fail clearly.
- Deferred stage fields `runtime`, `retry`, `when`, and `metadata` fail with explicit deferred-field messages.
- `StageSpec` stores `_target_` as `target_path`, `config` as `stage_config`, `depends_on` as `dependencies`, plus `inputs`, `outputs`, and `resources`.
- `OutputSpec` supports only required `artifact_type`, optional `codec_key`, optional `schema_version` defaulting to `None`, and optional `metadata`.
- Authored output `path`, unknown output-level keys, missing `artifact_type`, or malformed output specs fail clearly.

Graph and binding contract:

- Input values are strict strings in exactly `stage.output` form.
- Parsing is syntactic; semantic checks for unknown stages or outputs happen when resolving bindings against a `PipelineSpec`.
- Data dependencies from inputs and control dependencies from `depends_on` both contribute graph edges, but resolved input bindings preserve which input consumes which upstream output.
- Duplicate stages, unknown `depends_on` stages, self-dependencies, cycles, unknown input stages, and unknown input outputs all raise pipeline validation errors with useful stage/input/reference context.
- Topological sort must include every stage once, place upstream stages before downstream stages, and use authored order as the deterministic tie-breaker when possible.

Status contract:

- `StageStatus` includes `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`, `STALE`, and `CANCELLED`.
- `RunStatus` should cover minimal run-level states needed by later stores and runners without adding scheduler-specific states.
- `RunStatusRecord` and `StageStatusRecord` are frozen serializable records with schema version, IDs, status, timestamps, message, and plain-data metadata; stage records include attempt and owner metadata.
- Status helpers must not read/write files in this phase.

## Design Impact

- Maintainability: isolates static validation and graph behavior before store and runner code exists, so future execution phases can consume one stable model instead of duplicating ad hoc parsing.
- Extensibility: keeps resources and metadata opaque plain data, keeps graph helpers pure, and leaves room for future richer input specs, runtime profiles, optional outputs, selectors, and visualization without changing the v0 static core.
- Domain neutrality: stages are structural project-code objects; `loom` validates generic names, bindings, artifacts, and statuses but defines no domain stage subclasses or domain artifact types.
- Source-tree boundaries: pipeline model code stays under `src/loom/pipeline`, graph mechanics stay under `src/loom/pipeline/graph`, and root `loom.__init__` remains cheap and free of pipeline imports.

## Future Compatibility

- The parser should fail on deferred fields instead of silently preserving them so future phases can introduce `runtime`, `retry`, `when`, stage metadata, output paths, optional outputs, and pipeline defaults deliberately.
- Stage resources should be preserved as plain data but not interpreted or included in semantic fingerprints by default; future runtime/resource phases can add typed normalization and explicit fingerprint policy.
- `StageContext` should remain small in Phase 6 and be extendable by Phase 7 and Phase 9 with store-backed helpers without breaking the structural `Stage.run()` signature.
- Graph helpers should be reusable by planning, resume, preflight, CLI inspection, and future visualization without importing those subsystems.
- Status records should be serializable now but avoid persistence assumptions until run-store behavior lands.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Parse pipeline specs inside `loom.config.compose_config()` | Config composition should remain a generic resolved-config step; Phase 6 should expose an explicit parser so callers decide when to validate pipeline semantics. |
| Instantiate stage `_target_` values during spec parsing | Stage construction belongs to later runner phases and would mix static graph validation with runtime imports and side effects. |
| Treat authored stage order as execution order | The plan requires explicit DAG validation; authored order is only a deterministic tie-breaker for otherwise-ready stages. |
| Preserve unknown/deferred stage fields as metadata | Silent preservation would make future semantics ambiguous. V0 must reject deferred orchestration keys clearly. |
| Put `Stage` in `loom.protocols` | The stage contract depends on pipeline context, artifacts, and lifecycle semantics, so it belongs in `loom.pipeline.stage`. |
| Add store-backed context helpers now | Artifact paths, stores, save/register helpers, and run state belong to Phase 7 and Phase 9, not the static model phase. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Status model remains minimal and file-I/O-free. | Store and runner phases have not proven the exact persistence and transition helper needs yet. | Revisit in Phase 7 and Phase 9 when run-store writes and runner lifecycle use the records. |
| Only compact `stage.output` input references are supported. | V0 needs a strict, reviewable binding contract before richer input specs exist. | Revisit after local execution if literal inputs, external artifacts, or expanded input specs are needed. |
| Stage/output names reject dots to keep reference parsing simple. | The compact reference syntax would otherwise be ambiguous. | Revisit before release if downstream stage naming conventions require dots. |

## Reviewability

- Expected PR size and shape: moderate, with new pure pipeline modules plus focused tests. The PR should be reviewable without following store, runner, CLI, or domain logic.
- Files and areas to inspect:
  - `src/loom/pipeline/__init__.py`
  - `src/loom/pipeline/errors.py`
  - `src/loom/pipeline/specs.py`
  - `src/loom/pipeline/stage.py`
  - `src/loom/pipeline/context.py`
  - `src/loom/pipeline/status.py`
  - `src/loom/pipeline/graph/__init__.py`
  - `src/loom/pipeline/graph/bindings.py`
  - `src/loom/pipeline/graph/dag.py`
  - `src/loom/pipeline/graph/topology.py`
  - package, unit, contract, and integration tests under `tests/`
- Scope-control checks: confirm the diff has no store implementations, runner behavior, stage target imports, CLI behavior, config persistence, broad refactors, domain-specific fixtures, or root `loom.__init__` pipeline exports.

## Implementation Steps

1. Add pipeline-specific errors and export them from `loom.pipeline.errors` and `loom.pipeline`.
2. Add frozen `OutputSpec`, `StageSpec`, and `PipelineSpec` dataclasses with strict construction from plain mappings and validation for names, targets, outputs, resources, and deferred/unknown fields.
3. Add `StageContext` as a minimal frozen value type and add the structural `Stage` protocol without requiring inheritance.
4. Add status values, status records, and to/from plain dict helpers without filesystem behavior.
5. Add binding helpers for parsing strict `stage.output` references and resolving per-stage input bindings against a `PipelineSpec`.
6. Add graph representation and helpers that combine data and control edges, detect cycles/self-dependencies, compute upstream/downstream sets, and perform deterministic topological sorting.
7. Wire explicit public exports through `loom.pipeline` and `loom.pipeline.graph` while preserving root import boundaries.
8. Add phase-scoped tests across required suites, then run targeted suites during implementation.
9. Before PR preparation, run `make validate-pr` and `make test-summary` and record evidence in the PR body.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_public_api.py`, `tests/package/test_import_boundaries.py`, and possibly `tests/package/test_pipeline_api.py`.
- Required assertions: `import loom` still does not import `loom.pipeline`; `import loom.pipeline` and `import loom.pipeline.graph` expose the Phase 6 API; package modules import cleanly; top-level `loom.__init__` remains limited to cheap primitive exports.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/test_specs.py`, `tests/unit/loom/pipeline/test_context.py`, `tests/unit/loom/pipeline/test_stage.py`, `tests/unit/loom/pipeline/test_status.py`, `tests/unit/loom/pipeline/test_errors.py`, `tests/unit/loom/pipeline/graph/test_bindings.py`, `tests/unit/loom/pipeline/graph/test_dag.py`, and `tests/unit/loom/pipeline/graph/test_topology.py`.
- Required assertions: valid inline pipeline/stage/output shapes parse; unknown and deferred fields fail clearly; duplicate stages, bad names, missing targets, missing outputs, missing `artifact_type`, bad output specs, bad refs, unknown stages, unknown outputs, self-dependencies, and cycles fail clearly; resources and metadata require plain data; status records serialize/deserialize; topological sort works for single, linear, branching, and diamond DAGs; upstream/downstream helpers return direct and transitive sets.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_stage_contract.py`.
- Required assertions: dummy project stage objects satisfy `Stage` structurally without inheritance; protocol checks or typing-oriented runtime checks do not require subclassing; the required `run(context, inputs)` shape returns a mapping keyed by declared output names. Stage execution and output validation remain out of scope.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/pipeline/test_pipeline_config.py` or equivalent.
- Required assertions: a domain-neutral YAML config composed through `compose_config()` can feed the Phase 6 pipeline parser; recipe-expanded or override-adjusted resolved config can still produce a static `PipelineSpec`; parsing does not instantiate stage targets, import project stage modules, write files, or invoke stores/runners.

### E2E Suite

- Status: deferred.
- Expected paths: none in this phase; no `tests/e2e` directory exists yet.
- Required assertions or deferral reason: Phase 6 has no runnable user workflow, CLI command, runner, or run directory behavior. End-to-end coverage should begin after local execution and status persistence exist.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected for `slow`, `network`, `slurm`, or `optional_dependency`.
- Required assertions or deferral reason: this phase is pure in-memory validation and graph logic with no network, scheduler, optional dependency, or slow external behavior.

## Risks

- Strict parsing could accidentally reject future fields without a useful message; tests should assert deferred fields mention the field and that it is unsupported in v0.
- If graph construction loses authored order, topological sort may become nondeterministic and make later planning/fingerprint explanations noisy.
- Mixing input data edges and `depends_on` control edges without preserving the reason could make later artifact binding and resume explanations unclear.
- Adding public imports through `loom.__init__` would violate the import-boundary policy and should be rejected during review.
- Overbuilding status transitions or context helpers now could drag Phase 7/Phase 9 execution semantics into the static model PR.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
uv run pytest tests/unit/loom/pipeline tests/unit/loom/pipeline/graph
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

This draft pass intentionally did not run validation because no product implementation was performed and the manager requested planning only.

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: errors/spec parsing first; stage protocol/context second; status records third; bindings/graph/topology fourth; public exports and tests alongside each slice.
- Tests to run with each slice: run the matching direct `uv run pytest` path for new unit tests, then broaden to `make test-unit`, `make test-package`, `make test-contract`, and `make test-integration` before PR prep.
- Decisions the executor must not revisit: no target instantiation, no runner/store/CLI behavior, no root `loom.__init__` pipeline exports, no deferred fields accepted silently, no broad refactors outside `loom.pipeline` and phase-scoped tests.
- Conditions that require stopping for the manager: inability to preserve the recorded stack base, discovery that Phase 6 needs an unplanned public API outside `loom.pipeline`, or a conflict with Phase 5 branch contents that cannot be resolved without changing Phase 5 behavior.

## Handoff Notes For Phase Execution Plan Refinement

- Refine the exact dataclass field defaults, validation helper names, and serialization helper names before implementation.
- Decide whether status values should use `StrEnum` or string constants, and document the reason.
- Decide the exact graph edge representation and how edge reasons distinguish data inputs from control-only `depends_on`.
- Confirm whether `PipelineSpec.from_config()` or a standalone parser is the public construction API.
- Tighten expected test names and direct targeted commands based on the refined module layout.

## Refinement And Review Budget Status

- Phase implementation refinement: unused.
- PR review: unused.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed with message `plan: add phase execution plan`.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending implementation pass.
- Implementation validation: pending implementation and PR-preparation passes.
- Refinement summary: pending implementation refinement pass; budget unused.
- PR preparation: pending.
- Stack maintenance: pending predecessor merge and retarget/rebase handling.
- Remaining blockers: none recorded for local planning.

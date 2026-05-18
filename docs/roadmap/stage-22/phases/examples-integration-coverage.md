# Phase 2 Execution Plan: Robust Examples And Integration Behavior

## Metadata

- Status: final phase execution plan
- Feature focus: Examples And Validation
- PR title: `Examples And Validation - Phase 2: Integration Coverage`
- Branch: `codex/examples-integration-coverage`
- Worktree: `/home/samcantrill/work/loom-worktrees/examples-integration-coverage`
- Phase execution plan path: `docs/roadmap/stage-22/phases/examples-integration-coverage.md`
- Full plan: `docs/roadmap/stage-22/implementation-plan.md`
- Source phase: Phase 2, "Robust Examples And Integration Behavior"
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR; merge-eligible after automated review, required validation, CI, and target-branch checks pass against `develop`
- Workflow path: fast path
- Successor dependency notes: Phase 3 should branch from updated `develop` after this phase merges, or from `codex/examples-integration-coverage` only if this phase is validated and open but not yet mergeable.
- Plan quality gate: passed on 2026-05-18 in `docs/roadmap/stage-22/implementation-plan.md`
- Plan quality gate loop budget: already consumed and passed before this phase plan; no further plan-review pass requested
- Draft pass: completed in this artifact
- Refine pass: not needed on fast path; scope is examples/docs/tests-only and no expanded-path trigger is present
- Setup limitations: worktree was created from local `origin/develop` at `385c02f` (`docs: record stage 22 phase 1 merge`); no fetch, product validation, or broad checks were run in this planning-only pass
- Blockers: none

## Objective

Make the current authoring, execution, and operations examples reliably runnable and backed by targeted integration evidence, especially examples currently classified as `full`, while preserving the Stage 22 rule that missing behavior, real external systems, or daemon/cluster requirements become manual or no-example documentation rather than runtime implementation.

## Full-Plan Context

Stage 22 is a docs, examples, integration, e2e, and documentation-confidence stage over implemented Loom behavior. Phase 1 has merged and supplies the manifest/status/validation contract that this phase must use. Phase 2 strengthens runnable examples and integration behavior. Phase 3 owns representative end-to-end CLI/Python journeys and must remain out of scope. Phase 4 owns final docs audit, completion metadata, and broad final alignment and must also remain out of scope.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 1 merged into `develop` through PR #196, merge commit `b02304bad363ccd4a6103f3385d5b11188693230`, and merge metadata is present on `origin/develop` at `385c02f`; the Phase 1 dependency is satisfied.
- Retarget/rebase plan after predecessor merge: none for this phase because it targets `develop` directly.
- Branch cleanup constraints: do not delete this branch until any Phase 3 successor is rebased or retargeted away from it if stacked continuation becomes necessary.

## Source Phase Summary

- Goal: make implemented feature families discoverable through robust runnable examples backed by integration tests.
- Required scope: `examples/authoring/`, `examples/execution/`, `examples/operations/`, focused `docs/features/*-example-coverage.md`, and integration tests for example workflows.
- Required checkpoints: runnable examples use public APIs or CLI, temporary output/run roots, fake/local backends, named validation paths, and stable assertions over persisted records, diagnostics, generated artifacts, or public command/API results.
- Acceptance criteria: smoke examples keep executing through the manifest harness; `full` runnable examples gain concrete integration evidence; README and focused coverage docs name truthful validation paths; manual/illustrative examples remain manual with rationale; no runtime behavior is added.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - Phase 1 normalized 26 `examples/**/example.yaml` manifests with `id`, `status`, `validation`, `surface`, `public_surfaces`, `owner_docs`, `owner_stages`, and `validation_path`.
  - `examples/README.md` defines `smoke`, `full`, and `manual` validation tiers plus manifest metadata expectations.
  - Group READMEs in `examples/authoring/`, `examples/execution/`, and `examples/operations/` list primary CLI/Python workflows and keep `internal_demo` entries separate.
  - Focused coverage docs currently exist for config, SLURM, authority, and containers: `docs/features/config-example-coverage.md`, `docs/features/slurm-example-coverage.md`, `docs/features/authority-example-coverage.md`, and `docs/features/container-example-coverage.md`.
- Existing tests or harness behavior:
  - `tests/integration/docs/test_v0_python_examples.py` validates manifest/catalog consistency and executes `smoke` Python entrypoints with `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT` redirected to `tmp_path`.
  - Several `full` examples currently point to docs-only validation paths rather than per-example integration evidence: `operations.captured-logs`, `operations.failing-run`, `operations.resource-preflight`, `operations.resource-leases`, and `operations.offline-import-rejections`.
  - Existing integration suites already cover many lower-level behaviors under `tests/integration/config/`, `tests/integration/pipeline/`, `tests/integration/diagnostics/`, and `tests/integration/authority/`; Phase 2 should add example-workflow integration assertions, not duplicate those option matrices.
- Import-boundary or dependency constraints:
  - Core runtime modules must not import examples or docs validation tooling.
  - Examples must stay domain-neutral and synthetic.
  - Default validation must remain local/fake-backed and must not require Docker daemons, SLURM clusters, provider SDKs, network access, or credentials.

## In-Scope Work

- Add or update targeted integration tests that run `full` runnable example entrypoints through their public CLI or Python surfaces with temporary roots and assert stable behavior beyond process success.
- Keep the existing smoke-example harness working and add focused smoke assertions only where needed to make current validation paths meaningful without turning Phase 2 into e2e coverage.
- Update `validation_path` and, where appropriate, `validation_command` metadata for examples whose evidence moves from docs-only references to named integration test paths.
- Update example READMEs and focused example-coverage docs so runnable claims name the relevant validation path and manual boundaries remain explicit.
- Add no-example rationale or manual/illustrative classification when an implemented area cannot be demonstrated without new runtime behavior or external systems.
- Keep validation helpers test-owned; small shared helper code may live under tests or the existing docs integration harness if it avoids runtime imports.

## Out-of-Scope Work

- Runtime behavior, CLI behavior, executor/store/authority/plugin behavior, cleanup/retention behavior, or public API changes.
- New Phase 3 e2e journeys, broad command walkthrough tests, or end-to-end user journey selection.
- Phase 4 final documentation audit, final implementation-plan metadata, or broad stale-text cleanup outside the examples and focused coverage docs touched by Phase 2 evidence.
- Real Docker, Apptainer, SLURM, network, cloud, hosted authority, provider SDK, or credential-backed default validation.
- Domain-specific tutorial projects or examples that depend on downstream project code.

## Assumptions

- Existing example scripts are the preferred runnable artifacts; replacing them with a separate runner framework is unnecessary.
- `full` means runnable and integration-testable, but not necessarily part of the fastest smoke node.
- Existing lower-level integration tests can remain in place; Phase 2 should assert that example workflows compose public surfaces and produce reviewable outputs.
- If an example cannot support `LOOM_EXAMPLE_OUTPUT_ROOT` or `LOOM_EXAMPLE_RUN_ROOT` without runtime changes, it should be documented as manual, illustrative, or deferred instead of forcing product code changes.

## Scope Contract

No runtime public contract changes are in scope. The public behavior this phase may affect is limited to example artifacts and docs/test validation:

- User-facing examples must use public Python APIs or supported CLI commands.
- Runnable example scripts must isolate generated output through `LOOM_EXAMPLE_OUTPUT_ROOT` and run data through `LOOM_EXAMPLE_RUN_ROOT` when they write runs.
- Integration tests must assert stable public evidence such as status payloads, artifact/log records, rejection codes, resource lease outcomes, generated dry-run files, or documented stdout summaries.
- Manifest validation tiers remain `smoke`, `full`, and `manual`; statuses remain `runnable`, `illustrative`, and `deferred`.
- Manual external-system examples must keep `validation: manual`, prerequisites, and rationale.
- Validation failures should be test failures with actionable example IDs and paths, not new runtime exceptions or schema imports.

## Design Impact

- Maintainability: example-workflow integration tests make validation paths reviewable and reduce drift between manifests, README claims, and runnable scripts.
- Extensibility: keeping helper code test-owned leaves room for later example groups without making example metadata a runtime schema.
- Domain neutrality: examples continue to use synthetic pipelines, local stores, fake executors, and generic resources rather than domain datasets or project-specific packages.
- Source-tree boundaries: expected changes stay in `examples/`, focused `docs/features/*-example-coverage.md`, and `tests/integration/`; `src/loom` should remain untouched.

## Future Compatibility

Phase 2 should leave Phase 3 a clear set of already-runnable building blocks for representative e2e journeys. Validation paths should be specific enough to prove each example but not so tightly coupled to incidental stdout formatting that Phase 4 cannot polish docs without test churn. If example validation begins to need generated inventories or typed metadata, defer that to a future docs-tooling stage rather than adding a runtime abstraction here.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Convert every example into the smoke harness | Would make the fastest docs/example path slower and blur the existing `smoke`/`full` tier distinction. |
| Add e2e tests for the same workflows now | Phase 3 owns representative end-to-end journeys; Phase 2 should prove integration behavior and example robustness. |
| Require real Docker or SLURM for stronger confidence | Violates default-local validation and external-system boundaries. Fake/local evidence plus manual live guidance is the accepted Stage 22 shape. |
| Add runtime support solely to make a demo work | Stage 22 demonstrates implemented behavior; missing behavior should become manual or no-example rationale. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Some robust examples may remain `full` instead of `smoke` | Keeps the default docs/example smoke path fast while still adding named integration evidence | Users rely on those examples as primary onboarding paths and smoke coverage no longer catches common breakage. |
| Integration assertions may validate stable summaries rather than full golden output | Reduces brittleness while still proving persisted records and diagnostics | Regressions escape because summaries are too weak to catch user-visible drift. |
| Manual live external-system examples remain unexecuted by default | Real daemons and clusters are not deterministic local dependencies | A deterministic fake or hosted validation fixture becomes available and is approved for default checks. |

## Reviewability

- Expected PR size and shape: a focused examples/docs/tests PR, with new or updated integration tests, small example script hardening, manifest validation-path updates, and targeted coverage-doc edits.
- Files and areas to inspect: `examples/authoring/`, `examples/execution/`, `examples/operations/`, `examples/**/example.yaml`, group READMEs, focused `docs/features/*-example-coverage.md`, `tests/integration/docs/test_v0_python_examples.py`, and any new `tests/integration/examples/` module.
- Scope-control checks: no `src/loom` changes, no new runtime dependencies, no e2e test additions, no real external-system requirements, and no broad documentation audit outside Phase 2 evidence.

## Implementation Steps

1. Inventory current `full` and docs-only validation examples, then choose the smallest set of example-workflow integration tests that gives each runnable example a named evidence path.
2. Add or extend integration tests that run the selected example entrypoints with temporary output/run roots and assert stable public evidence.
3. Harden example scripts or README instructions only where needed for hermetic temporary roots, fake/local backends, and stable output.
4. Update manifests, group READMEs, and focused coverage docs to name the new validation paths and preserve manual boundaries.
5. Run targeted docs/example and integration checks before leaving final PR-gate commands for PR preparation.

## Test Plan

### Package Suite

- Status: required as final regression gate; no new package tests expected
- Expected paths: existing `tests/package/` through `make validate-pr`
- Required assertions or deferral reason: public import/API surfaces used by examples must remain intact. Adding new package tests or touching package exports should be treated as a stop condition unless needed only to fix an uncovered existing packaging regression.

### Unit Suite

- Status: deferred for new coverage; existing unit suite required through final gate
- Expected paths: none unless a reusable test-owned helper is introduced, then `tests/unit/tools/` or the nearest existing test-helper location
- Required assertions or deferral reason: Phase 2 should not add runtime units. If helper logic becomes reusable outside one integration module, add small unit coverage for parsing/error reporting without importing `src/loom` from docs tooling.

### Contract Suite

- Status: deferred for new coverage; existing contract suite required through final gate
- Expected paths: none
- Required assertions or deferral reason: this phase does not define runtime extension-point contracts. New `tests/contracts` coverage would indicate scope drift unless an existing contract test needs a small assertion update to preserve current behavior.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/docs/test_v0_python_examples.py` plus a focused new or existing example-workflow integration module such as `tests/integration/examples/test_example_workflows.py`
- Required assertions or deferral reason: execute runnable example entrypoints with temporary roots; assert stable evidence for `full` examples including captured logs, failure diagnostics, resource preflight warnings/errors, resource lease outcomes, and offline import rejection codes; preserve manifest/catalog validation and smoke entrypoint execution.

### E2E Suite

- Status: deferred for new coverage; existing e2e evidence may be reported by final summary
- Expected paths: none for new Phase 2 tests
- Required assertions or deferral reason: Phase 3 owns representative end-to-end journeys and CLI/Python workflow tests. Do not add `tests/e2e` coverage in this phase unless the manager explicitly reassigns scope.

### Opt-In Suites

- Status: deferred
- Markers affected: `slow`, `optional_dependency`, `slurm`, container and SLURM acceptance hooks remain manual
- Required assertions or deferral reason: real Docker, Apptainer, SLURM, network, and provider-backed validation remain outside default Stage 22 Phase 2. Fake/local behavior may be integration-tested in the default suite.

## Risks

- Integration tests can become a broad retest of lower-level config, executor, or authority behavior rather than proving example workflows.
- Running many example scripts can slow default validation if `full` coverage is not kept focused.
- Example stdout assertions can become brittle if they overfit incidental formatting.
- Hardening an example can tempt runtime changes when the correct answer is manual or no-example documentation.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/integration/docs/test_v0_python_examples.py
uv run pytest tests/integration/examples/test_example_workflows.py
make test-integration
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: `full` example inventory and test selection; example-workflow integration tests; small script/root-output hardening; manifest and README validation-path updates; focused coverage-doc updates.
- Tests to run with each slice: run the new example-workflow integration test after adding each example group; run `tests/integration/docs/test_v0_python_examples.py` after manifest or README changes; run `make test-integration` before PR preparation.
- Decisions the executor must not revisit: no runtime behavior, no e2e additions, no new external dependencies, no real daemon/cluster default checks, no public schema for manifest metadata, and no broad final docs audit.
- Conditions that require stopping for the manager: making an example runnable requires `src/loom` changes, default validation needs real external systems or network access, a `full` example cannot be isolated in temporary roots, or implementation would require adding Phase 3/4 work.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on fast path in this artifact
- Final phase execution plan: completed on fast path; refine pass not needed
- Implementation summary: Added focused integration coverage for the five `full` operation examples (`captured-logs`, `failing-run`, `resource-preflight`, `resource-leases`, `offline-import-rejections`) through a new module `tests/integration/examples/test_example_workflows.py`, updated their `validation_path` entries to point to this evidence, and documented explicit evidence locations in operations and authority coverage docs.
- Implementation validation: partial due environment constraints; required commands were executed and captured in command notes.
- Refinement summary: none needed on fast path.
- Blocker-resolution summary: two blockers remain local to this environment:
  - `PermissionError: [Errno 1] Operation not permitted` when example entrypoints attempt local authority socket startup in `examples/operations.resource-leases` and `operations.offline-import-rejections`.
  - Missing optional dependencies (`yaml`/`omegaconf`) required by example preflight/runtime command paths in this environment.
- PR preparation: pending. Focus remains on local edits + targeted pytest execution and phase-plan closure notes.
- Stack maintenance: none required for this phase-local worktree yet.
- Remaining blockers: local authority socket bind permissions and missing optional example dependencies (`yaml`/`omegaconf`) prevent full evidence execution in this sandbox.

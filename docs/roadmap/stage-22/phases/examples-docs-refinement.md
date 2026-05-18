# Phase 4 Execution Plan: Documentation Refinement And Final Validation

## Metadata

- Status: final phase execution plan
- Feature focus: Examples And Validation
- PR title: `Examples And Validation - Phase 4: Docs Refinement`
- Branch: `codex/examples-docs-refinement`
- Worktree: `/home/samcantrill/work/loom-worktrees/examples-docs-refinement`
- Phase execution plan path: `docs/roadmap/stage-22/phases/examples-docs-refinement.md`
- Full plan: `docs/roadmap/stage-22/implementation-plan.md`
- Source phase: Phase 4, "Documentation Refinement And Final Validation"
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR; merge-eligible after automated review, required validation, CI, target-branch checks, and final Stage 22 metadata pass against `develop`
- Workflow path: fast path
- Successor dependency notes: this is the final Stage 22 phase; no successor phase should branch from it unless the manager explicitly opens a follow-up blocker-resolution or metadata-only continuation.
- Plan quality gate: passed on 2026-05-18 in `docs/roadmap/stage-22/implementation-plan.md`
- Plan quality gate loop budget: already consumed and passed before this phase plan; no further plan-review pass requested
- Draft pass: completed in this artifact
- Refine pass: not needed on fast path; Phase 4 is docs/examples/tests evidence alignment and final metadata, with no new public API, persistence, schema, dependency, or runtime contract design
- Setup limitations: worktree was created from local `origin/develop` at `61c275d` (`docs: record stage 22 phase 3 merge`); the control checkout has unrelated dirty files and a behind local `develop`, so this phase uses the isolated worktree as the source of truth
- Blockers: none

## Objective

Complete the Stage 22 documentation and evidence alignment pass by auditing README, examples, focused coverage docs, validation-path claims, and implementation-plan completion metadata so the final stage record accurately describes which examples are smoke, full, manual, illustrative, or `internal_demo`, and which checks prove the runnable workflows.

## Full-Plan Context

Stage 22 has already merged the manifest/catalog contract, focused integration evidence, and representative e2e workflows through Phases 1 to 3. Phase 4 closes the stage by making docs and final metadata match that evidence. It must not add runtime behavior, invent future-roadmap scope, broaden example coverage beyond small audit corrections, or require real external systems.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none
- Why this base branch is correct: Phase 3 merged into `develop` through PR #198, merge commit `eabae1cb99678ef31ceadb8620fe0a595ae16bdc`, and Phase 3 merge metadata is present on `origin/develop` at `61c275d`; Phase 4 has no unmerged predecessor.
- Retarget/rebase plan after predecessor merge: none for this phase because it targets `develop` directly.
- Branch cleanup constraints: after PR merge and metadata recording, the branch and worktree can be cleaned up when no explicit successor or blocker-resolution branch depends on them.

## Source Phase Summary

- Goal: finish stale-text cleanup, example-output alignment, final catalog polish, final suite evidence, and Stage 22 completion metadata.
- Required scope: `README.md`, `examples/README.md`, example group READMEs, targeted feature docs, `docs/roadmap/stage-22/implementation-plan.md`, and the Phase 4 PR body artifact during PR preparation.
- Required checkpoints: README and feature-doc claims name validation tiers or manual prerequisites; final `make validate-pr` and `make test-summary` evidence is recorded; completion metadata identifies manual, full-only, `internal_demo`, and intentionally absent examples; no product behavior is changed.
- Acceptance criteria: final docs are internally consistent with manifests and named test paths; example output references are current and not overfit to incidental formatting; Stage 22 implementation-plan metadata records final completion facts and accepted follow-ups; default validation remains local/fake-backed.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase:
  - `examples/README.md` defines the catalog groups, validation tiers, and manifest inventory fields.
  - `examples/authoring/README.md`, `examples/execution/README.md`, and `examples/operations/README.md` list user-facing CLI and Python workflows, representative e2e evidence, full integration evidence, and internal demos.
  - Focused coverage docs currently track configuration, authority, container, and SLURM evidence in `docs/features/*-example-coverage.md`.
  - `docs/roadmap.md`, `docs/roadmap/stage-22/planning.md`, and `docs/roadmap/stage-22/implementation-plan.md` define Stage 22 exit criteria and must remain consistent with the final phase record.
- Existing tests or harness behavior:
  - `tests/integration/docs/test_v0_python_examples.py` validates manifests, owner docs, validation paths, README catalog sections, CLI/Python README sections, manual rationale, internal-demo exclusions, and smoke example execution.
  - `tests/integration/examples/test_example_workflows.py` validates selected `validation: full` operations examples.
  - `tests/e2e/test_example_journeys.py` validates representative local execution/resume, authority lifecycle, SLURM dry-run, and Docker workflow evidence.
- Import-boundary or dependency constraints:
  - Core runtime modules must not import examples or docs validation tooling.
  - Default checks must not require real Docker, Apptainer, SLURM, network, provider SDKs, hosted services, credentials, clusters, daemons, or persistent generated state.
  - Example and docs metadata remain docs/test-owned plain data rather than a runtime schema.

## In-Scope Work

- Audit top-level and example READMEs for stale future-tense claims, missing validation tiers, missing manual prerequisites, stale example output references, and links that no longer reflect Phase 1 to 3 evidence.
- Audit focused example coverage docs and nearby feature docs only where they make example, integration, e2e, manual, or validation-tier claims.
- Update manifests, README prose, or focused coverage docs only for small corrections needed to align existing evidence; do not create broad new examples.
- Record final Stage 22 completion metadata in `docs/roadmap/stage-22/implementation-plan.md`, including final validation evidence, accepted manual/full-only/internal-demo status, and accepted follow-ups.
- Leave the Phase 4 PR body artifact for PR preparation, using `make validate-pr` and `make test-summary` evidence gathered by implementation/PR-preparation stages.

## Out-of-Scope Work

- Any runtime behavior, CLI behavior, executor/store/authority/plugin behavior, cleanup/retention behavior, public API changes, or persistence/schema changes.
- New domain-specific tutorial projects, new provider integrations, hosted docs publishing, generated-doc tooling, notebooks, or website work.
- Real external-system validation in default checks, including Docker daemons, Apptainer, SLURM clusters, cloud services, network, provider SDKs, or credentials.
- Broad future-feature planning or roadmap cleanup outside the Stage 22 completion record.
- Adding new integration or e2e coverage except where a tiny targeted test/doc correction is required to keep an already claimed validation path true.

## Assumptions

- Phase 1 to 3 evidence is accepted as the primary source for final documentation claims.
- Some examples will intentionally remain manual, full-only, or `internal_demo`; Phase 4 should document that status rather than force broader default validation.
- Existing docs/example validation paths are durable enough for final metadata, but may need small wording or link cleanup.
- If a final audit finds broad stale-doc drift outside Stage 22 example evidence, that becomes an accepted follow-up or blocker, not hidden Phase 4 scope expansion.

## Scope Contract

No runtime public contract changes are in scope. Phase 4 may only change documentation, examples metadata/prose, test-owned validation references, and Stage 22 completion metadata:

- Runnable example claims must point to existing smoke, integration, or e2e validation paths.
- Manual or illustrative examples must name the external capability that keeps them out of default validation.
- `internal_demo` entries must remain excluded from primary user-facing catalogs.
- README and feature-doc examples must remain domain-neutral and describe public CLI or Python surfaces only.
- Any need to modify `src/loom`, add dependencies, or require real external systems is a stop condition.

## Design Impact

- Maintainability: final evidence alignment reduces drift between manifests, READMEs, focused coverage docs, and roadmap completion metadata.
- Extensibility: recording accepted manual and full-only boundaries gives future example groups a clear place to add evidence without changing runtime contracts.
- Domain neutrality: the audit keeps examples synthetic and generic rather than promoting downstream package workflows.
- Source-tree boundaries: expected changes stay in docs, examples metadata/prose, test evidence references, and the Stage 22 implementation-plan artifact; `src/loom` should remain untouched.

## Future Compatibility

Phase 4 should leave a clear final record for future roadmap stages: what Stage 22 proved, which examples remain intentionally manual or full-only, and what revisit triggers would justify more validation. Do not turn the completion metadata into a future-roadmap plan. If users later need hosted docs, generated indexes, or real external-system validation, those should be separate roadmap stages with their own design review.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Expand the final audit into runtime fixes for stale docs | Stage 22 is docs/examples/tests-only; stale docs should be corrected or marked manual rather than made true by product changes. |
| Require all examples to become smoke or e2e validated | This would slow default validation and conflict with accepted smoke/full/manual tiering. |
| Validate live Docker, Apptainer, SLURM, or hosted authority behavior before closing the stage | Real daemons, clusters, services, and credentials are outside the deterministic default suite. |
| Turn final metadata into broad future-feature planning | The stage may record accepted follow-ups, but future planning belongs to a later roadmap workflow. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Final docs may still point some runnable examples at smoke or integration evidence rather than e2e evidence | Stage 22 uses tiered validation, and exhaustive e2e coverage is intentionally out of scope | Users rely on a smoke/integration-only example as a primary workflow and regressions escape default validation. |
| Manual external-system examples remain unexecuted by default | Real clusters, daemons, networks, and provider credentials are not deterministic local dependencies | A fake-backed or hosted deterministic fixture becomes available and is approved for default checks. |
| Completion metadata is maintained manually in the implementation plan | Avoids adding generated-doc tooling during a final refinement phase | Metadata drift recurs or more stages need generated evidence rollups. |

## Reviewability

- Expected PR size and shape: a focused docs/examples/metadata PR with small README or coverage-doc edits, Stage 22 implementation-plan completion updates, and a PR body artifact prepared later.
- Files and areas to inspect: `README.md`, `examples/README.md`, example group READMEs, `docs/features/*-example-coverage.md`, `docs/roadmap/stage-22/implementation-plan.md`, and any touched `examples/**/example.yaml`.
- Scope-control checks: no `src/loom` changes, no new runtime dependencies, no real external-system default checks, no broad roadmap rewrite, no new domain-specific examples, and no unchecked validation claims.

## Implementation Steps

1. Audit final README, group README, manifest, focused coverage-doc, and roadmap text against the Phase 1 to 3 validation paths and manual/internal-demo boundaries.
2. Apply only small docs or metadata corrections needed to align claims with current examples and named validation evidence.
3. Update `docs/roadmap/stage-22/implementation-plan.md` with Phase 4 completion metadata placeholders/facts, accepted follow-ups, and final stage status once validation evidence is available.
4. Run targeted docs/example, integration, and e2e checks for touched evidence paths, then leave final `make validate-pr` and `make test-summary` evidence for PR preparation.
5. Prepare the Phase 4 PR body artifact with final validation summaries and any accepted manual or follow-up notes.

## Test Plan

### Package Suite

- Status: required as final regression gate; no new package tests expected
- Expected paths: existing `tests/package/` through `make validate-pr`
- Required assertions or deferral reason: public package imports used by examples and docs snippets must remain intact. Adding package tests or touching package metadata is out of scope unless needed to explain an existing validation failure.

### Unit Suite

- Status: deferred for new coverage; existing unit suite required through final gate
- Expected paths: none
- Required assertions or deferral reason: Phase 4 should not introduce runtime units or reusable docs tooling. If a tiny test-owned helper is unexpectedly added, cover it in the nearest existing test-helper unit location without runtime imports.

### Contract Suite

- Status: deferred for new coverage; existing contract suite required through final gate
- Expected paths: none
- Required assertions or deferral reason: this phase does not define extension-point contracts, schemas, or persistence behavior. New contract tests would indicate scope drift.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/docs/test_v0_python_examples.py` and `tests/integration/examples/test_example_workflows.py`
- Required assertions or deferral reason: manifest/catalog consistency, README sections, owner docs, validation-path references, manual rationale, internal-demo exclusions, smoke script execution, and full example evidence must remain true after docs or metadata edits.

### E2E Suite

- Status: required for touched e2e evidence and final gate
- Expected paths: `tests/e2e/test_example_journeys.py` plus `make test-e2e` if e2e validation paths or README claims are touched
- Required assertions or deferral reason: representative local execution/resume, authority lifecycle, SLURM dry-run, and Docker fake-backed workflows must stay aligned with documented validation paths. Do not add live external-system e2e checks.

### Opt-In Suites

- Status: deferred
- Markers affected: real Docker, Apptainer, SLURM, network, provider, hosted-service, and live acceptance checks remain manual or opt-in
- Required assertions or deferral reason: Phase 4 may document manual prerequisites but must not require opt-in suites for default Stage 22 completion. If an opt-in result is mentioned, it must be clearly labeled as supplemental and not part of `make validate-pr`.

## Risks

- The final audit could expand into unrelated roadmap cleanup instead of Stage 22 example evidence alignment.
- Example output snippets could overfit incidental formatting if docs try to mirror exact command output too closely.
- Completion metadata could accidentally overstate what fake/local validation proves for live external systems.
- Small docs fixes could mask a missing validation path; such a gap should become a blocker or accepted follow-up, not an unsupported claim.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/integration/docs/test_v0_python_examples.py
uv run pytest tests/integration/examples/test_example_workflows.py
uv run pytest tests/e2e/test_example_journeys.py
make test-e2e
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: final docs/README audit; small manifest or validation-path cleanup; focused feature coverage-doc alignment; Stage 22 implementation-plan completion metadata; PR body artifact preparation later in the workflow.
- Tests to run with each slice: run docs/example integration after manifest or README edits; run example-workflow integration after full-example evidence edits; run affected e2e modules after e2e validation-path edits; run final PR gates during PR preparation.
- Decisions the executor must not revisit: no runtime behavior, no new public schema, no new external dependencies, no real external-system default validation, no domain-specific examples, no broad future-roadmap planning, and no exhaustive e2e expansion.
- Conditions that require stopping for the manager: docs cannot be made truthful without `src/loom` changes, a validation claim needs real external systems, final evidence contradicts Phase 1 to 3 completion records, or broad stale-doc drift requires a separate roadmap planning pass.

## Refinement And Review Budget Status

- Phase implementation refinement: unused; reserved for later workflow stages only if targeted validation fails, suite coverage is missing, or a concrete implementation blocker appears
- PR review: unused; reserved for the phase PR review gate after implementation and PR preparation
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed on fast path in this artifact
- Final phase execution plan: completed on fast path; refine pass not needed
- Implementation summary: completed final docs alignment for the top-level
  README, example catalog tier guidance, execution/operations catalog placement
  prose, focused configuration and authority example coverage docs, and Stage
  22 implementation-plan metadata. No runtime, CLI, executor, store, authority,
  plugin, dependency, or external-system behavior changed.
- Implementation validation:
  - Targeted docs/example, focused integration, and representative e2e paths:
    `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py tests/e2e/test_example_journeys.py -q`
    passed with `44 passed`.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-e2e` passed with `46 passed,
    6 deselected`.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed: Ruff passed,
    Pyright reported 0 errors, default harness passed with `1963 passed,
    26 skipped, 30 deselected`, config-extra harness passed with
    `460 passed, 3 skipped, 2001 deselected`, and `uv build` succeeded.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote
    `build/test-summary.md` with package `108 passed, 1 skipped`; unit
    `1394 passed, 7 skipped, 1 deselected`; contract `274 passed, 2 skipped`;
    integration `170 passed, 8 skipped, 18 deselected`; e2e `46 passed,
    6 deselected`; config-extra `460 passed, 3 skipped, 2001 deselected`.
- Refinement summary: not used
- Blocker-resolution summary: none used
- PR preparation: PR body prepared in
  `docs/roadmap/stage-22/phases/examples-docs-refinement-pr-body.md`; PR
  opened against `develop` as
  [#199](https://github.com/samcantrill/loom/pull/199)
- Stack maintenance: no predecessor or successor maintenance needed for the planning pass
- Remaining blockers: none known

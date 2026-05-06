# Phase 7 Execution Plan: Final Hardening, Documentation, And Evidence

## Metadata

- Status: refined phase execution plan; ready for implementation
- Feature focus: V1 Post Configuration
- PR title: `V1 Post Configuration - Phase 7: Final Hardening Documentation And Evidence`
- Branch: `codex/v1-post-final-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-final-hardening`
- Phase execution plan path: `docs/phases/v1-post-final-hardening.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1-post.md`
- Source phase: Phase 7. Final Hardening, Documentation, And Evidence
- Stack predecessor: none; Phases 1-6 have merged into `develop`.
- Base branch: `develop` / `origin/develop` at `7a0cc9d` (`docs: record v1-post phase 6 merged (#56)`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after review and checks because the target is `develop`.
- Workflow path: expanded planning path
- Successor dependency notes: this is the final v1-post phase. No successor phase may be started from this branch unless a later implementation plan explicitly adds one.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v1-post.md`; no blocking plan-review findings remain.
- Plan quality gate loop budget: initial review used, automated refinement used, confirmation review used.
- Draft pass: completed by `loom_phase_planner` in this commit.
- Refine pass: completed by `loom_phase_planner` in this commit; expanded planning was selected because the phase spans documentation, evidence, and consistency checks across config, provenance, fingerprints, resume, pipeline, and implementation-plan contracts.
- Setup limitations: `git worktree add` needed approved Git metadata access after the sandbox could not create the nested `refs/heads/codex/...` directory. No product-code setup blocker remains.
- Blockers: none for implementation.

## Objective

Confirm the repaired v1-post behavior is internally consistent, documented as Python-API-only, and backed by representative public-Python evidence before v2 planning begins.

## Full-Plan Context

V1-post has merged the source boundary cleanup, strict authoring semantics, structured source diagnostics, artifact-safe provenance/fingerprint ordering, pipeline/run-store composition manifest persistence, and recipe residual-risk coverage. Phase 7 is the final sweep. It should repair stale documentation and evidence drift left by those phase changes, add or tighten representative public-Python e2e coverage for the artifact-safe run path, update implementation-plan completion metadata, and run the final validation gates.

This phase must not reopen the accepted v1 decisions or broaden v1 into deferred roadmap work.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: the manager selected `develop`; Phases 1-6 are merged and the control checkout is clean at `7a0cc9d`.
- Retarget/rebase plan after predecessor merge: none needed because there is no predecessor.
- Branch cleanup constraints: this branch may be deleted after merge when the PR is merged because no successor branch should depend on it.

## Source Phase Summary

- Goal: confirm repaired v1-post behavior is consistent and ready to hand off to v2 planning.
- Required scope: audit `docs/features/config.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, `docs/features/pipeline.md`, `docs/loom.md`, and implementation-plan docs for stale resolved-persistence, `_copy_`, CLI, manifest, provenance, and security wording; add or update representative public-Python e2e coverage for the repaired artifact-safe path; update implementation-plan phase statuses and accepted debt ledger after phases have landed; run `make validate-pr` and `make test-summary`.
- Required checkpoints: docs consistently say v1 is Python-API-only; `loom.config` returns artifact-safe records but does not persist them; `loom.pipeline` can persist plain composition manifests without importing `loom.config`; default artifacts do not persist resolver outputs, raw source bytes, or full resolved config snapshots for composed configs; `_copy_`, plugin/remote resolvers, sweeps, remote stores, and v2 CLI behavior remain deferred.

## Current Source And Harness Findings

- `docs/features/config.md` already states several accepted decisions, but still contains historical/future examples and ordering prose that mention `config/resolved.yaml`, `config/resolved.redacted.yaml`, legacy phase labels, or provenance after final resolution. The executor should make those examples unambiguously future/legacy or update them to the current v1-post artifact-safe order.
- `docs/features/pipeline.md` and `docs/loom.md` still show v0-style run-layout snippets with only `config/resolved.yaml` or with `resolved.redacted.yaml`. These should not describe current composed-config default persistence after Phase 5.
- `docs/features/provenance.md` contains a run config snippet with `redacted_config: config/resolved.redacted.yaml` and many future CLI references. Future CLI sections can remain if they are clearly labeled as future/non-v1, but current v1-post provenance and run-store examples must use composition manifest/provenance language that avoids resolved snapshots.
- `docs/features/fingerprints.md` and `docs/features/resume.md` already distinguish pipeline-owned resolved views from v1 artifact-safe config fingerprints in key sections. The audit should still check for any wording that implies v1 config fingerprints are runtime-replay digests or that resume requires `loom.config` artifacts.
- Existing e2e coverage includes public composed-config runner coverage in `tests/e2e/test_local_pipeline_run.py`, including a case that persists `config/composition_manifest.json` and omits `config/resolved.yaml` and `config/resolved.redacted.yaml`. Existing config public API e2e coverage in `tests/e2e/test_config_composition_public_api.py` checks resolver-expression preservation and opt-in raw source snapshots. Phase 7 should extend or consolidate these if they do not together prove the repaired artifact-safe path from compose through runner persistence and resume-facing records.
- Package coverage already guards Python-API-only packaging through `tests/package/test_import.py`; final package obligations should rerun and extend only if the docs audit exposes a metadata gap.

## In-Scope Work

- Audit and update the specified docs so current v1-post wording consistently preserves these accepted decisions:
  - `loom.config` remains persistence-free.
  - `loom.pipeline` must not depend on `loom.config` or config manifest/provenance classes.
  - `_copy_` is unsupported in v1.
  - Default artifacts are security-first and artifact-safe.
  - Resolver outputs and raw source bytes are not persisted by default.
  - V1 is Python-API-only and exposes no functional CLI commands.
- Keep future CLI, remote-store, sweep, and `_copy_` discussions only where clearly marked as future roadmap guidance, not current v1 behavior.
- Update stale current-behavior run-layout examples so composed-config defaults are described as `config/composition_manifest.json`, `config/recipe_manifest.json`, and artifact-safe provenance metadata, without default `config/resolved.yaml` or `config/resolved.redacted.yaml` for composed configs.
- Clarify the distinction between in-memory resolved config for Python callers, pipeline-owned selected resolved views for stage fingerprints, and artifact-safe v1 config fingerprints/manifests for persistence and comparison.
- Update `docs/implementation-plans/implementation-plan-v1-post.md` after implementation to record Phase 7 completion, final validation evidence, any accepted debt ledger adjustments, and v2 handoff notes. Do not change earlier phase history except to correct stale or inconsistent completion metadata discovered by the audit.
- Add or update representative public-Python e2e coverage for the repaired artifact-safe path. Prefer extending existing public e2e tests over adding duplicate fixtures.
- Add a narrow behavior test only when the documentation audit discovers a real behavior/documentation mismatch that is not already covered by package, unit, contract, integration, or e2e suites.
- Run final validation gates: `make validate-pr` and `make test-summary`.

## Out-of-Scope Work

- New v2 CLI behavior, functional commands, parser changes, or console script entry points.
- `_copy_` implementation or authoring syntax beyond explicit unsupported-directive wording.
- Plugin resolvers, remote resolvers, global include search, sweeps, remote stores, bundles, or catalogs.
- New product semantics beyond final documentation/evidence hardening unless a doc-discovered behavior gap requires a narrow regression test or narrow fix.
- Default raw source persistence, default resolver-output persistence, default full resolved-config snapshot persistence for composed configs, or exact resolved-runtime replay guarantees.
- Public API redesigns, schema migrations, new heavyweight dependencies, or source-tree boundary changes.

## Accepted Decisions To Preserve

- `loom.config` remains persistence-free.
- `loom.pipeline` must not depend on `loom.config` or manifests.
- `_copy_` is unsupported in v1.
- Default artifacts are security-first and artifact-safe.
- Resolver outputs and raw source bytes are not persisted by default.
- V1 is Python-API-only; no CLI commands are added.
- Plain mapping configs are caller-provided runtime data, not v1 composed-config artifacts.
- Runtime object fingerprinting remains explicit pipeline policy, not automatic config behavior.
- Opaque trusted-Python recipe branching on unresolved resolver text remains accepted debt.

## Assumptions

- Most Phase 7 changes should be docs, tests, and implementation-plan metadata. Product-code edits should be rare and justified by a concrete testable mismatch.
- Current composed-config runner persistence from Phase 5 is the accepted behavior. If docs imply otherwise, fix docs unless tests show implementation drift.
- Current recipe residual-risk debt from Phase 6 is accepted. Do not attempt to certify arbitrary recipe internals.
- Future CLI sections may remain in feature docs as roadmap notes if they cannot be mistaken for current v1 behavior.
- The final implementation-plan status update should be completed by the executor or PR-preparation workflow after implementation evidence exists, not by this planning-only commit.

## Scope Contract

Phase 7 is a hardening and evidence phase. It may change current-behavior documentation, docs examples, phase metadata, and tests that exercise already-accepted behavior. It may add a narrow fix only when a stale doc claim exposes an actual behavior gap in the repaired artifact-safe path.

The public-Python artifact-safe path to prove is:

```text
compose_config(...) or compose_config_with_catalog(...)
returns in-memory resolved config plus artifact-safe manifest/provenance/fingerprints
PipelineRunner.run(RunRequest(config=composed, ...))
persists plain composition manifest and recipe manifest through run-store APIs
does not persist default resolved config snapshots for composed configs
keeps resolver outputs and raw source bytes out of default persisted artifacts
```

The phase must preserve the source-tree boundary: config code owns composition artifact objects; pipeline and stores own persistence as plain data; docs should describe that boundary in the same terms.

## Design Impact

- Maintainability: removes stale cross-document contradictions so future v2 planning starts from a coherent v1-post baseline.
- Extensibility: keeps deferred CLI, remote-store, sweep, resolver, and `_copy_` work clearly future-scoped instead of implied by v1 docs.
- Security: reinforces artifact-safe defaults, explicit raw-source opt-in, and no default resolver-output or resolved-config persistence.
- Source-tree boundaries: makes docs and evidence align with the `loom.config`/`loom.pipeline` separation that earlier phases implemented.
- Public contract impact: no new public API or persistence contract is intended; the phase documents and tests the current accepted contract.

## Future Compatibility

- V2 CLI planning can wrap the public Python APIs and read persisted plain-data artifacts without inheriting stale v1 docs that promise current CLI behavior.
- Future remote stores or bundles can build on the `config/composition_manifest.json` plain-data contract without requiring `loom.pipeline` to import config classes.
- Future `_copy_`, resolver, sweep, and exact replay policies can be added behind explicit design decisions and security warnings rather than as accidental v1 implications.
- Future runtime fingerprint policy remains pipeline-owned and explicit; config fingerprints remain artifact-safe authored-composition records.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Leave stale resolved-snapshot examples as historical context without edits | Current-behavior docs would continue to contradict Phase 5 artifact-safe persistence and mislead v2 planning. |
| Remove every CLI mention from feature docs | Future CLI roadmap guidance is useful when clearly labeled; the problem is current-behavior ambiguity, not future sections. |
| Add new CLI commands or package entry points to satisfy docs | V1-post is Python-API-only and Phase 6 explicitly guards that no console script exists. |
| Reintroduce default resolved/redacted config snapshots for composed configs | Conflicts with the accepted artifact-safe default and Phase 5 persistence contract. |
| Broaden the phase into remote stores, sweeps, `_copy_`, or resolver support | Those are deferred roadmap decisions with separate security and contract implications. |
| Treat documentation drift as a reason for broad product refactors | Phase 7 should prefer docs/test corrections and stop on broad behavior changes. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Feature docs may retain future CLI examples while v1 remains Python-API-only. | Future roadmap context is useful, and removing it wholesale would reduce planning continuity. | Readers or tests continue confusing future CLI examples with current v1 behavior. |
| Plain mapping config snapshot behavior may still use legacy resolved names. | It is caller-provided runtime data, not composed-config artifact persistence, and changing it is a broader v2 snapshot policy decision. | A neutral all-config snapshot policy is designed for v2 or users need consistent naming across config input types. |
| The final e2e path remains representative, not exhaustive across every resolver/recipe/include combination. | Exhaustive coverage already belongs to focused unit/integration/config-extra suites; e2e should prove the full public path without duplicating the matrix. | A regression escapes focused suites because the public compose-to-runner path is underrepresented. |

## Reviewability

- Expected PR size and shape: mostly docs and tests, with implementation-plan metadata updates and final evidence. Product-code changes should be absent or narrowly tied to a test-discovered mismatch.
- Files and areas to inspect: `docs/features/config.md`, `docs/features/provenance.md`, `docs/features/fingerprints.md`, `docs/features/resume.md`, `docs/features/pipeline.md`, `docs/loom.md`, `docs/implementation-plans/implementation-plan-v1-post.md`, `docs/implementation-plans/implementation-plan-v1.md`, `docs/implementation-plans/roadmap-v1-planning-notes.md`, `tests/e2e/test_local_pipeline_run.py`, `tests/e2e/test_config_composition_public_api.py`, `tests/package/test_import.py`, and targeted config/pipeline integration tests only as needed.
- Scope-control checks: no functional CLI, no console script entry point, no `_copy_`, no resolver allow-list expansion, no raw-source or resolver-output default persistence, no remote stores, no sweeps, no pipeline import of config classes, no config persistence helpers, and no broad product refactor.
- PR body expectations: summarize docs audited, e2e/coverage changes, final validation tables from `make test-summary`, accepted debt, assumptions, and any intentionally deferred suite areas.

## Implementation Steps

1. Audit the named docs and implementation-plan docs for stale current-behavior claims around resolved persistence, `_copy_`, CLI, manifests, provenance, resume, fingerprints, and security defaults.
2. Update stale current-behavior wording so it matches the accepted v1-post contract while keeping future roadmap sections clearly labeled as future.
3. Add or update representative public-Python e2e coverage for the artifact-safe compose-to-runner path, including absence of default resolved snapshots and preservation of artifact-safe manifest/provenance/fingerprint facts.
4. Add narrow targeted tests only for any concrete behavior gap found during the doc audit.
5. Update `docs/implementation-plans/implementation-plan-v1-post.md` with Phase 7 completion metadata, final validation evidence, accepted debt ledger adjustments if needed, and v2 handoff notes after tests pass.
6. Run targeted docs/e2e/package checks during implementation, then run `make validate-pr` and `make test-summary` for PR evidence.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`, and public API package tests touched by docs-discovered gaps.
- Required assertions or deferral reason: v1-post still exposes no console script entry points or functional CLI commands; pipeline/store package surfaces remain importable without `loom.config`; store API still exposes composition manifest methods; public config/pipeline APIs remain available. If no package files change, rerun the existing package suite through `make validate-pr` and record it.

### Unit Suite

- Status: conditional.
- Expected paths: focused `tests/unit/loom/config/*`, `tests/unit/loom/pipeline/*`, or docs helper tests only if a doc-discovered behavior gap is narrow enough for unit coverage.
- Required assertions or deferral reason: defer when Phase 7 only updates docs/e2e/metadata and existing unit suites already cover the behavior. Add unit tests if stale docs expose a mismatch in artifact-safe serialization, local-store wrapper validation, resolver-output filtering, or import-boundary helpers.

### Contract Suite

- Status: required final evidence; new tests conditional.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_store_contract.py`, and recipe contract tests only if touched.
- Required assertions or deferral reason: final validation must show config provenance/schema-version-2, artifact fingerprint, composition manifest, and run-store composition manifest contracts still pass. Add contract tests only if Phase 7 changes a public schema or protocol, which should be unusual and must remain narrow.

### Integration Suite

- Status: required final evidence; targeted additions conditional.
- Expected paths: `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_fingerprints.py`, `tests/integration/config/test_compose_source_snapshots.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_local_stores.py`, and docs integration tests if docs examples are executable.
- Required assertions or deferral reason: final evidence must cover artifact-safe records, resolver-expression preservation, raw source snapshot opt-in, recipe artifact safety, pipeline composition manifest persistence, and absence of config imports from pipeline. Add integration coverage only if the final docs audit identifies an untested contract gap.

### E2E Suite

- Status: required.
- Expected paths: `tests/e2e/test_local_pipeline_run.py` and/or `tests/e2e/test_config_composition_public_api.py`.
- Required assertions or deferral reason: at least one public Python v1-post workflow must compose a config with artifact-safe records, run it through `PipelineRunner`, persist `config/composition_manifest.json` and `config/recipe_manifest.json`, omit default `config/resolved.yaml` and `config/resolved.redacted.yaml`, and avoid persisting resolver outputs/raw source bytes by default. If existing e2e tests already satisfy part of this, extend them rather than duplicating setup, and document exactly which e2e test is the representative path.

### Opt-In Suites

- Status: required for config-extra evidence.
- Markers affected: config optional dependency markers and any docs/example checks that require config extras.
- Required assertions or deferral reason: final `make test-summary` evidence must include config-extra rows that cover compose/provenance/fingerprint/source snapshot behavior. If config extras are unavailable in the environment, stop before PR preparation unless the manager explicitly accepts narrower evidence.

## Risks

- Docs may accidentally describe future CLI or remote-store behavior as current v1 functionality. Keep future sections explicitly labeled and avoid command examples that look runnable today.
- Updating run-layout snippets can obscure the difference between composed-config defaults and plain mapping caller-provided snapshots. Preserve that distinction.
- E2E coverage can become too broad and slow if it duplicates integration matrices. Keep one representative public path and leave exhaustive combinations to focused suites.
- Implementation-plan metadata could be updated before final checks exist. Record final status and evidence only after validation commands have run.
- A doc audit could uncover a real behavior gap that is larger than a narrow regression. Stop for the manager rather than implementing new product semantics.

## Stop Conditions

- Satisfying the docs or e2e acceptance criteria appears to require adding functional CLI behavior, console scripts, `_copy_`, plugin/remote resolvers, sweeps, remote stores, or new persistence contracts.
- A fix would require `loom.pipeline` or store modules to import `loom.config` classes or manifests.
- A fix would make `loom.config` write run-store artifacts or otherwise become persistence-aware.
- A fix would persist resolver outputs, raw source bytes, or full resolved composed-config snapshots by default.
- A final validation gate cannot run, config extras are unavailable, or tests fail for reasons outside a narrow Phase 7 docs/evidence fix.
- The implementation-plan quality gate status is found to be invalid or earlier phase metadata contradicts merged history in a way that cannot be corrected locally.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/e2e/test_local_pipeline_run.py tests/e2e/test_config_composition_public_api.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_fingerprints.py tests/integration/config/test_compose_source_snapshots.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_stores.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: docs audit and wording cleanup first; e2e/public coverage second; narrow behavior-gap tests or fixes only if discovered; implementation-plan completion metadata after validation evidence exists.
- Decisions the executor must not revisit: no config persistence helpers, no pipeline import of config classes, no default resolved or resolved-redacted snapshot for composed configs, no raw source or resolver output default persistence, no CLI, no console script, no `_copy_`, no plugin/remote resolver, no remote stores, no sweeps, and no automatic runtime-object fingerprinting.
- Conditions that require stopping for the manager: any stop condition above, or any implementation that needs a new public contract instead of docs/evidence hardening.
- Expanded-path refinement notes: complete. The refined boundary pins the final sweep to documentation consistency, representative public-Python evidence, implementation-plan metadata, and final validation gates.

## Refinement And Review Budget Status

- Plan draft: completed by `loom_phase_planner` in this commit.
- Plan refinement: completed by `loom_phase_planner` in this commit because expanded planning is active.
- Phase implementation refinement: unused; reserved for the later implementation workflow because expanded path is active or if validation/coverage obligations are missed.
- PR review: unused.
- PR body draft/refine: unused; reserved for `loom_pr_preparer`.

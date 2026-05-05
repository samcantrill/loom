# Phase 14 Execution Plan: Artifact-Safe Fingerprints And Resume Comparison

## Metadata

- Status: pr_open
- Feature focus: Configuration
- PR title: `Configuration - Phase 14: Artifact-Safe Fingerprints And Resume Comparison`
- PR: https://github.com/samcantrill/loom/pull/41
- Branch: `codex/config-artifact-fingerprints`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-artifact-fingerprints`
- Phase execution plan path: `docs/phases/config-artifact-fingerprints.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 14 - Artifact-Safe Fingerprints And Resume Comparison
- Stack predecessor: none; Phases 1-13 are merged.
- Base branch: `develop`
- Base commit: `50e89647fc37b6dd223e95e3a50aa831c5f83296`
- Target branch: `develop`
- Merge eligibility: root phase; PR targets `develop` and is merge-eligible only after passing review/CI against `develop`.
- Workflow path: expanded path
- Workflow path rationale: this phase defines durable artifact-safe fingerprint and authored-composition resume comparison semantics from Phase 13 records, affects public-ish artifact contracts, and must preserve resolver-output exclusion and path portability.
- Successor dependency notes: Phase 15 may add raw source snapshot opt-in and source hardening without changing Phase 14 default artifact-safe fingerprint semantics. Phase 16 may document limitations and broaden e2e coverage.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: completed by `loom_phase_planner`; refine budget used.
- Phase implementation refinement budget: used for the 2026-05-06 default validation blocker pass; no further automated implementation refinement pass remains.
- Pre-submit blocker gate budget: used on 2026-05-06 by a full diff/body/evidence review before PR submission. The gate found the comparison-helper outcome blocker.
- User-authorized blocker-resolution budget: used on 2026-05-06 for the exact comparison-helper outcome blocker; no further automated blocker pass remains.
- PR body draft pass: completed in this artifact; durable draft at `docs/phases/config-artifact-fingerprints-pr-body.md`.
- PR body refine pass: completed in this artifact; PR opened and verified.
- PR review budget: consumed by the full pre-submit blocker gate. Because the submitted diff changed after blocker resolution, only a bounded confirmation gate focused on that blocker and evidence drift remains before PR submission.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. Approved `gh auth setup-git` and `git fetch origin` succeeded. Local `develop` and `origin/develop` matched the assigned base commit. Initial sandboxed `git worktree add` could not create the nested `codex/...` branch ref because `.git/refs/heads/codex` directory creation was blocked by sandbox filesystem policy; approved `git worktree add` created the branch and worktree successfully.
- Blockers: none known.

## Objective

Compute the default config fingerprint from artifact-safe authored-composition inputs before resolver execution, using Phase 13 source artifact records and unresolved/redacted composition facts, and add narrow config-layer comparison helpers that tell whether two config artifact records match as authored composition without claiming exact runtime-value replay.

## Full-Plan Context

Phases 1-13 established config/pipeline boundaries, artifact skeletons, strict load/merge/include/override behavior, resolver security, recipe expansion, scoped validation, public composition inspection, and populated provenance, manifest, source metadata/hash records, and redacted unresolved artifacts. Phase 14 turns those Phase 13 records into the default artifact-safe fingerprint contract and the first authored-composition resume comparison surface.

Future work remains out of scope: Phase 15 raw source snapshot opt-in and hardening, Phase 16 documentation/e2e hardening, run-store persistence, CLI presentation, exact runtime resolver replay, secret-aware opt-in fingerprints, plugin/remote/global include resolvers, and pipeline resume integration. This phase must preserve accepted v1 decisions: `loom.config` remains persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` is unsupported in v1; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 is Python-API-only; and no plugin/remote/global search include resolvers are added.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-13 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, the v1 plan records Phase 13 as merged, and local/remote `develop` both resolve to the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 14 PR is merged and no successor branch depends on `codex/config-artifact-fingerprints`.

## Source Phase Summary

- Goal: compute artifact-safe fingerprints and compare authored composition for resume checks.
- Required scope: fingerprints before resolver execution; source hashes from Phase 13 source artifact records; stable composition context; unresolved expanded config; resolver expressions as authored text; redacted or allowed override facts; authored-composition resume comparison helpers if kept in v1 scope.
- Required checkpoints: replace runtime-resolved default config fingerprint semantics with an artifact-safe canonical payload; keep `ConfigFingerprintRecord` and manifest fingerprint references in sync with `ComposedConfig.fingerprint`; preserve resolver-output exclusion and path portability; expose authored-composition comparison without run-store or pipeline coupling.
- Acceptance criteria: fingerprints change for meaningful authored composition changes; fingerprints do not change solely because machine-local absolute path context changes; resolver outputs are excluded by default; resume comparison distinguishes authored-composition match from runtime-value replay.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/compose.py` owns staged composition and currently computes `resolved_fingerprint = build_resolved_fingerprint(validated)`, `unresolved_fingerprint = build_resolved_fingerprint(unresolved)`, one `ConfigFingerprintRecord(label="unresolved")`, and the public `fingerprint` through `build_config_fingerprint(resolved=validated, ...)`, which still includes runtime-resolved values. `_build_source_artifacts(...)`, `_build_provenance_metadata(...)`, and manifest population in the same module expose Phase 13 source records and artifact-safe facts. `src/loom/config/artifacts.py` owns `CompositionManifest`, `SourceArtifactRecord`, and `ConfigFingerprintRecord`. `src/loom/config/provenance.py` owns the old resolved-oriented `build_config_fingerprint(...)` helper. `src/loom/fingerprints.py` owns stable plain-data hashing and digest validation. `src/loom/config/api.py` owns public `ComposedConfig` and `ConfigCompositionInspection` fields.
- Existing tests or harness behavior: artifact contract tests live in `tests/contracts/test_config_artifact_contract.py`; inspection contract tests live in `tests/contracts/test_config_composition_inspection_contract.py`; Phase 13 integration coverage lives in `tests/integration/config/test_compose_provenance.py`; compose orchestration assertions live in `tests/unit/loom/config/test_compose.py`; artifact record unit coverage lives in `tests/unit/loom/config/test_config_artifacts.py`; digest helper coverage lives in `tests/unit/loom/test_fingerprints.py`; import-boundary coverage lives in `tests/package/test_import_boundaries.py`.
- Import-boundary or dependency constraints: production changes should stay in `loom.config` plus shared `loom.fingerprints` helpers only if a generic helper is needed. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project code, or add runtime dependencies. Do not make `loom.pipeline` depend on `ComposedConfig`, manifests, or fingerprint records.

## In-Scope Work

- Define the default config fingerprint as a stable canonical artifact-safe payload computed before resolver execution.
- Populate `ComposedConfig.fingerprint`, `ConfigCompositionInspection.fingerprint`, `ConfigFingerprintRecord`, and `CompositionManifest.fingerprint_records` from the same artifact-safe digest source.
- Include source artifact roles/order/content digests, stable source-artifact references, include site paths and authored include targets, replacement/customization facts, recipe manifest facts, resolver expressions as authored text, redacted or allowed override facts, redacted/unresolved config content, schema/policy version metadata, and other Phase 13 artifact-safe composition facts needed for authored-composition equivalence.
- Exclude resolved resolver outputs, resolved environment variables, runtime objects, raw source bytes, and machine-local absolute path identity from semantic fingerprint inputs.
- Normalize path-bearing fingerprint inputs so content and authored composition remain comparable across different checkout/tmp roots. Absolute paths may remain in provenance/manifest metadata, but fingerprint semantics must use portable references where available, such as source role/order, include site path, authored target, content digest, target kind, explicit escape flag, and relative or URI-authored path facts.
- Add the retained v1 authored-composition comparison helpers in `loom.config`. They must compare current/prior config fingerprint records or manifests and return plain-data-friendly outcomes for match, mismatch, incompatible policy/schema, or insufficient data, while explicitly stating that runtime resolver values were not replayed.
- Keep comparison helpers independent from run-store reads/writes, CLI output, pipeline planning, and exact runtime-value replay.

## Out-of-Scope Work

- Exact replay or equality of runtime resolver outputs, environment variables, runtime objects, or fully resolved config artifacts.
- Secret-aware opt-in fingerprints, keyed hashes, HMAC policies, or resolved-value persistence.
- Run-store persistence, store file layouts, stage resume integration, or pipeline planning behavior.
- CLI commands, CLI presentation, or future PR/status output.
- Raw source bytes by default, raw snapshot opt-in, raw payload dedupe behavior, or rebuild-from-missing-source policy.
- Plugin, remote, global-search, or custom include resolvers.
- `_copy_` support, Hydra defaults-list compatibility, or broader composition semantics.
- Pipeline ownership changes or manifest-as-pipeline-API behavior.

## Assumptions

- Phase 13 source artifact records and manifest/provenance metadata are the primary inputs; the executor should avoid rereading source files solely to build fingerprints.
- The existing `fingerprint` stage name can remain stable while its payload changes from resolved-oriented to artifact-safe summary facts, with contract tests updated for the deliberate semantic change.
- The old `ConfigProvenance.resolved_fingerprint` field may remain as compatibility metadata, but the public `ComposedConfig.fingerprint` becomes the artifact-safe default by this phase. If preserving `resolved_fingerprint` requires a clearer metadata note, keep it additive and do not use it for the default public fingerprint or comparison helper.
- Absolute paths are allowed in Phase 13 provenance and source artifact metadata, but Phase 14 fingerprint equality must not depend on local checkout or temp directory prefixes when source content and authored composition are otherwise identical.
- Redacted secret override facts are acceptable fingerprint inputs; raw secret-like override values are not.
- Authored-composition comparison belongs in `loom.config` only as plain artifact comparison. Pipeline/stage resume policy remains owned by `loom.pipeline` and later run-store/CLI work.

## Scope Contract

The default config fingerprint is an artifact-safe authored-composition fingerprint. It must be computed from plain data before runtime interpolation output is used as a fingerprint input. The canonical payload must be deterministic, policy-labeled, schema-versioned, and reviewable in tests. It must not include resolved resolver outputs, environment-derived values, runtime objects, raw source bytes, or resolved absolute path prefixes as semantic identity.

The default `ConfigFingerprintRecord` label is `artifact_safe_config`. Its metadata must use stable plain-data names including:

- `fingerprint_policy`: `artifact_safe_authored_composition_v1`.
- `payload_schema_version`: `1`.
- `artifact_schema_version`: the current config artifact schema version.
- `semantic_scope`: `authored_composition`.
- `runtime_values_included`: `false`.
- `resolver_outputs_included`: `false`.
- `raw_source_bytes_included`: `false`.
- `runtime_value_replay`: `unavailable`.
- concise counts or summaries such as `source_artifact_count`, `resolver_expression_count`, `include_record_count`, `override_count`, and `recipe_manifest_count`.

`ComposedConfig.fingerprint`, `ConfigCompositionInspection.fingerprint`, the `fingerprint` composition stage payload, `CompositionManifest.fingerprint_records`, `ComposedConfig.fingerprint_records`, and `ConfigCompositionInspection.fingerprint_records` must all derive from the same default record: the public fingerprint equals the default record digest, the manifest contains that record, and inspection/composed views expose the same record tuple. Do not keep the current `label="unresolved"` as the default public record. If an additional unresolved-content digest is retained, it must use a non-default label and must not be confused with the public artifact-safe default.

Source artifact digests are semantic fingerprint inputs. Path strings from `SourceArtifactRecord.path`, `ConfigSource.path`, `IncludeSiteRecord.source_path`, and `IncludeSiteRecord.resolved_path` are provenance context unless normalized into a portable authored fact. For local files under different temporary roots, identical source content, role/order, authored include targets, include-site paths, overrides, recipe facts, and unresolved/redacted composition should produce the same default fingerprint. For base and overlay source records, use role/order/content digest/size and omit resolved absolute path identity from the semantic payload. For include records, use include-site path, source role/order/content digest, authored target, target kind, explicit escape flag, included content digest/size, replacement marker facts, and source include-site path. For explicit absolute paths or `file://` authoring, preserve the authored target string, `target_kind`, and `explicit_escape` as authored intent; do not replace that authored intent with the machine-local resolved path, and do not promise portability when the authored absolute/file URI text itself changes.

Resolver expressions are authored text in fingerprint inputs. The fingerprint may include resolver token, resolver name, expression text, and config path from resolver scan records. It must not include the runtime value produced by `${oc.env:...}` or any other resolver.

Override facts are fingerprint inputs only after applying the Phase 13 artifact safety rules. Secret-like override values must be redacted before fingerprinting. Allowed non-secret override values, override paths, operation kinds, and order are in scope.

Authored-composition comparison is retained in v1 with this narrow surface:

- Location: a new `loom.config` module such as `src/loom/config/fingerprints.py`; lazy public export through `loom.config.api` and `loom.config.__init__` is allowed only if package import-boundary tests remain clean.
- Inputs: `ConfigFingerprintRecord`, `CompositionManifest`, or their plain mapping forms. The helper must extract the single default `artifact_safe_config` record from each side and must not accept or require `ComposedConfig`, run IDs, store paths, pipeline objects, or CLI arguments.
- Output: an immutable plain-data-friendly result such as `ConfigFingerprintComparison` with `status` in `match`, `mismatch`, `incompatible_policy`, or `insufficient_data`; left/right digests; policy/schema labels when available; a concise reason; and `runtime_values_replayed` fixed to `False`.
- Function names should say config artifact/authored composition rather than resume safety, for example `compare_config_artifact_fingerprints(...)` or `compare_authored_config_fingerprints(...)`.

The helper must compare artifact records, not recompose configs and not read run stores. A `match` means the default artifact-safe authored-composition records match under the same policy/schema; it must not mean exact runtime resolver values matched. `incompatible_policy` covers schema/policy/label/algorithm mismatches. `insufficient_data` covers missing default records or invalid plain mapping shapes. `mismatch` covers valid comparable records with different digests.

## Design Impact

- Maintainability: move default fingerprint semantics to a single artifact-safe payload builder instead of mixing resolved and unresolved hash paths in composition orchestration.
- Extensibility: policy-labeled fingerprint records and plain comparison outcomes leave room for Phase 15 raw snapshots and later secret-aware/runtime-value opt-ins without changing the default security-first behavior.
- Domain neutrality: fingerprint inputs describe generic config composition facts, not project model/dataset/stage semantics.
- Source-tree boundaries: production work stays in `loom.config` and low-level `loom.fingerprints`; no pipeline, store, CLI, plugin, remote, or project-code dependency is introduced.

## Future Compatibility

- Phase 15 can add raw snapshot opt-in records without changing the default artifact-safe fingerprint policy.
- Future run-store or CLI code can persist and compare returned manifest/fingerprint records without importing `loom.config` into `loom.pipeline`.
- Future secret-aware fingerprints can add opt-in records or policy labels while default records continue to exclude resolver outputs and raw source bytes.
- Future docs/e2e hardening can explain that authored-composition matches are not exact runtime-value replay.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep the public default fingerprint based on `resolved` config | Violates Phase 14 acceptance because resolver outputs and machine-local runtime values can affect the default fingerprint. |
| Fingerprint raw source bytes directly | Raw source bytes are not persisted by default and Phase 15 owns raw snapshot opt-in policy. |
| Treat absolute resolved file paths as semantic identity | Would make otherwise identical authored composition differ across machines or temporary directories. |
| Compare only opaque digest strings with no policy/schema metadata | Cannot distinguish real mismatches from incompatible fingerprint policies or old records. |
| Put resume comparison in `loom.pipeline` or run stores now | Phase 14 is a config artifact contract phase; pipeline/store integration is out of scope and would violate the config/pipeline boundary. |
| Persist or hash resolved resolver values as an opt-in shortcut | Secret-aware/runtime-value policies are explicitly deferred and need a separate security model. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Authored-composition comparison cannot prove exact runtime resolver equality | Default artifacts intentionally exclude resolver outputs and environment values for security. | A later opt-in runtime-value or secret-aware fingerprint policy is designed. |
| Path portability may rely on Phase 13 metadata and portable references rather than a dedicated source-root model | Keeps Phase 14 scoped to default fingerprints without inventing global source roots. | A future remote/plugin/source-root phase needs cross-machine path rendering beyond current local/file URI facts. |
| Comparison helper outcomes may be minimal in v1 | The phase needs a durable semantic distinction, not full CLI diff rendering. | Future CLI/run-store resume work needs human-readable mismatch diffs. |

## Reviewability

- Expected PR size and shape: focused config artifact/fingerprint semantics, small comparison helper surface in `loom.config`, and targeted package/unit/contract/integration tests. No run-store, pipeline, CLI, raw snapshot, or docs/e2e broadening beyond narrow comments or test names needed to explain the contract.
- Files and areas to inspect: `src/loom/config/compose.py`; `src/loom/config/artifacts.py`; `src/loom/config/provenance.py` if the old resolved-oriented helper is replaced or renamed; `src/loom/config/api.py` and `src/loom/config/__init__.py` if exports or public dataclasses change; new narrow `src/loom/config/fingerprints.py` for policy and comparison; `src/loom/fingerprints.py` only for generic digest helpers. Test areas: `tests/unit/loom/config/test_config_artifacts.py`, `tests/unit/loom/config/test_compose.py`, new or existing config fingerprint/comparison unit tests, `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`, `tests/integration/config/test_compose_provenance.py`, and focused config integration tests for resolver/path cases.
- Scope-control checks: no resolved resolver outputs in `fingerprint`, `fingerprint_records`, manifest fingerprint metadata, or comparison payloads; no raw source bytes; no absolute-path-only semantic equality; no run-store writes; no CLI behavior; no pipeline imports; no `_copy_`; no plugin/remote/global resolvers.

## Implementation Steps

1. Define the artifact-safe fingerprint payload policy and isolate its builder so compose, records, and tests use one source of truth.
2. Wire the staged compose path to use the artifact-safe digest for `ComposedConfig.fingerprint`, inspection fingerprint, `ConfigFingerprintRecord`, manifest records, and the `fingerprint` stage payload.
3. Normalize/portable-map source artifact and manifest inputs so source content and authored composition affect the digest while machine-local absolute path prefixes do not.
4. Add the narrow authored-composition comparison helper in `loom.config.fingerprints`, including plain outcome data and runtime-replay limitation metadata.
5. Add focused unit and contract tests for fingerprint record shape, policy metadata, path portability, resolver-output exclusion, redacted override handling, and comparison outcomes.
6. Add integration cases through public `compose_config(...)` for base/overlay/include/override/recipe/resolver combinations that prove meaningful changes alter fingerprints and portable path changes alone do not.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: public config exports remain intentional; any new comparison helper export is cheap and optional-dependency-safe; `loom.config` does not import pipeline/store/CLI modules; `loom.pipeline` remains independent from `loom.config`, `ComposedConfig`, manifests, and fingerprint records.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_config_artifacts.py`, `tests/unit/loom/config/test_compose.py`, new or existing focused tests such as `tests/unit/loom/config/test_config_fingerprints.py` and `tests/unit/loom/config/test_config_fingerprint_comparison.py`; `tests/unit/loom/test_fingerprints.py` only if generic digest helpers change.
- Required assertions or deferral reason: artifact-safe payloads are deterministic; source artifact content digests, role/order, include site paths, authored targets, target kind, explicit escape flag, recipe facts, resolver authored expressions, unresolved/redacted config, and redacted/allowed override facts affect the default fingerprint as specified; resolved resolver values do not; raw source bytes are absent; secret-like override values are redacted before fingerprinting; `ComposedConfig.fingerprint`, inspection fingerprint, manifest fingerprint records, and `fingerprint_records` agree; comparison outcomes distinguish match, mismatch, incompatible policy/schema/label/algorithm, insufficient data, and runtime-value replay unavailable.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`.
- Required assertions or deferral reason: `ConfigFingerprintRecord` round-trips with `label="artifact_safe_config"` and the required policy metadata; `CompositionManifest.fingerprint_records` references the same default digest returned by compose/inspection; populated records and comparison results remain plain data, reject invalid or unknown fields according to existing conventions, and include no resolved resolver outputs, raw source bytes, runtime objects, or absolute-path-only semantic identity. Inspection stage names/order should remain stable unless the diff deliberately updates the contract.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_provenance.py`, `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_includes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_recipes.py`, and `tests/integration/config/test_compose_resolvers.py` or a focused new integration file such as `tests/integration/config/test_compose_fingerprints.py`.
- Required assertions or deferral reason: public `compose_config(...)` changes the default fingerprint when included file content, overlay content/order, authored include target, target kind/explicit escape intent, replacement marker, ordinary override value, recipe output, or unresolved expanded config changes; it does not change solely because equivalent files live under different temporary roots; resolver environment value changes do not affect the default fingerprint while authored resolver expression changes do; secret-like override values are redacted in fingerprint inputs while ordinary non-secret override values remain meaningful; comparison helpers report authored-composition match/mismatch/incompatible policy/insufficient data without claiming runtime replay.

### E2E Suite

- Status: deferred.
- Expected paths: none for Phase 14.
- Required assertions or deferral reason: current e2e coverage is runner/pipeline oriented and this phase must not add run-store, runner, CLI, or pipeline behavior. Public config behavior is covered by required integration tests. Broader end-to-end artifact persistence and documentation coverage remains Phase 16 or later run-store/CLI work.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshot opt-in, secret-aware/runtime-value fingerprints, plugin/remote resolvers, network behavior, CLI inspection, store persistence, and pipeline resume integration are out of scope.

## Risks

- Resolved runtime values can leak into fingerprints if the executor reuses the existing `build_config_fingerprint(resolved=validated, ...)` path instead of replacing it for the default public fingerprint.
- Path portability can regress if tests compare only one temp directory or if the payload uses `SourceArtifactRecord.path` as semantic identity without normalization.
- Redacted override handling can either leak secret-like values or make allowed non-secret values indistinguishable. Tests need both secret and non-secret override cases.
- Comparison helpers can overclaim resume safety. Their names, metadata, and tests must say authored-composition match is not exact runtime-value replay.
- Manifest/fingerprint records can drift if compose builds digest, records, and stage payloads through separate payloads. Use one builder where practical.
- Adding exports or modules can accidentally import optional config dependencies or pipeline modules at package import time. Package/import-boundary tests must cover this.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_config_fingerprints.py tests/unit/loom/config/test_config_resume_comparison.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_fingerprints.py tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_resolvers.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: first isolate the `artifact_safe_authored_composition_v1` payload builder and default record constants; then wire compose records/stage payloads to the one default record; then add path portability, resolver-output exclusion, and redacted-override tests; then add the `loom.config.fingerprints` comparison helper and outcome tests; finally add focused integration matrix coverage through public compose APIs.
- Tests to run with each slice: run focused unit tests for payload/record changes first, then contract tests after record metadata changes, then comparison unit tests, then integration tests for public compose behavior and path/resolver/override cases.
- Decisions the executor must not revisit: default record label is `artifact_safe_config`; default policy is `artifact_safe_authored_composition_v1`; default fingerprints are artifact-safe and pre-runtime; resolver outputs and raw source bytes are excluded; resolved absolute paths are provenance context, not semantic identity; explicit absolute/file URI authored target text remains authored intent; `loom.config` writes nothing; `loom.pipeline` must not depend on config or manifests; `_copy_` remains unsupported; v1 has no CLI; plugin/remote/global include resolvers remain out of scope.
- Conditions that require stopping for the manager: satisfying acceptance appears to require run-store or pipeline integration, exact resolver replay, secret-aware runtime fingerprints, raw source persistence, changing Phase 13 source artifact contracts incompatibly, making path portability depend on a new global source-root model, accepting `ComposedConfig`/run IDs/store paths in the comparison helper, importing pipeline/stores/CLI from config, or reopening the already-used v1 plan quality gate.
- Stop before implementation if current source proves the default record cannot be made to agree across `ComposedConfig.fingerprint`, inspection fingerprint, manifest records, and stage payload without widening Phase 14 scope.
- Expanded-path refinement notes: completed. This pass fixed the comparison helper surface, default label/metadata naming, and path-portability semantics from Phase 13 source artifact metadata.

## Refinement And Review Budget Status

- Phase execution plan draft: used.
- Phase execution plan refine: used.
- Phase implementation refinement: used for the 2026-05-06 default validation blocker pass.
- Pre-submit blocker gate: used.
- User-authorized blocker-resolution pass: used for the comparison-helper outcome blocker.
- Focused confirmation gate: completed.
- PR body draft: used.
- PR body refine: completed.
- PR review: consumed by the full pre-submit blocker gate; no separate general PR review remains unless the submitted diff changes after confirmation.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner`; ready for `loom_phase_executor`.
- Implementation summary: implemented `artifact_safe_config`-labeled, artifact-safe composed-config fingerprints across composed config, inspection, and manifest records; introduced `src/loom/config/fingerprints.py` with default payload/record builders and `compare_config_artifact_fingerprints`; updated `src/loom/config/compose.py` to use authored-composition facts only for public defaults; added/updated imports in API package surface; added unit, contract, integration coverage for agreement, path portability, resolver expression identity, secret redaction, and comparison outcomes.
- Implementation validation: targeted phase commands were executed in the dedicated phase worktree.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py`
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_compose.py tests/unit/loom/config/test_config_fingerprints.py`
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py`
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_fingerprints.py tests/integration/config/test_compose_provenance.py tests/integration/config/test_compose_resolvers.py`
- Suite run/deferred:
    - Run: package, unit, contract, integration required by this phase.
    - Deferred: e2e and opt-in suites.
    - Note: command in the plan references `tests/unit/loom/config/test_config_resume_comparison.py`; this file is not present in this phase worktree, so the equivalent new comparison coverage is covered in `tests/unit/loom/config/test_config_fingerprints.py` and `tests/integration/config/test_compose_fingerprints.py`.
- Assumptions/risks:
    - `ConfigFingerprintComparison` and `compare_config_artifact_fingerprints` are plain-data artifacts and do not claim resolver runtime replay; `runtime_values_replayed` is fixed to `False`.
    - Legacy `ConfigProvenance.resolved_fingerprint` remains present for compatibility and is not used as the public default fingerprint.
    - Secret-like override and config values are redacted before inclusion in artifact-safe fingerprint payloads; full resolver/runtime persistence remains deferred.
- Refinement summary: resolved the default no-extra validation blocker by removing runtime imports of optional config dependency modules from `src/loom/config/fingerprints.py`; `IncludeSiteRecord` and `ResolverExpressionRecord` are now imported only for type checking, preserving explicit `loom[config]` execution coverage while allowing default artifact contract collection without `yaml`/`omegaconf`.
- Refinement validation:
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --isolated --locked --group dev pytest tests/contracts/test_config_artifact_contract.py` passed: 7 passed.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py` passed: 8 passed.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed: Ruff, Pyright, default isolated suite, config-extra isolated suite, and build.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed and wrote `build/test-summary.md`: package 36 passed/1 skipped; unit 354 passed/1 skipped; contract 29 passed/2 skipped; integration 9 passed/5 skipped; e2e 5 passed; config-extra 286 passed/433 deselected.
- PR preparation: expanded-path draft PR body created at `docs/phases/config-artifact-fingerprints-pr-body.md`; draft pass complete and refine pass pending. PR opening intentionally deferred to the later `pr-body-refine` pass.
- PR facts: PR #41 opened with title `Configuration - Phase 14: Artifact-Safe Fingerprints And Resume Comparison`; head branch `codex/config-artifact-fingerprints`; target branch `develop`; stack predecessor none/root phase; merge eligibility root phase targeting `develop` after review and CI.
- Scope confirmation: final branch diff is limited to Phase 14 config artifact-safe fingerprint/comparison implementation, config API exports, focused tests, and phase artifacts. It does not include Phase 15 raw snapshot/source hardening, Phase 16 documentation/e2e hardening, run-store persistence, CLI behavior, pipeline resume integration, secret-aware runtime fingerprints, plugin/remote/global include resolvers, `_copy_`, or raw source-byte default artifacts.
- Validation evidence for draft PR body: `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed after refinement; `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed and wrote `build/test-summary.md` with package 36 passed/1 skipped, unit 354 passed/1 skipped, contract 29 passed/2 skipped, integration 9 passed/5 skipped, e2e 5 passed, and config-extra 288 passed/433 deselected. Targeted default contract check passed with 7 passed; targeted config-extra contract check passed with 8 passed.
- User-authorized pre-submit blocker resolution: fixed `compare_config_artifact_fingerprints` so valid `ConfigFingerprintRecord` inputs and record-shaped mappings with non-default labels reach the policy checks and return `incompatible_policy`, while malformed plain mappings are caught and returned as `insufficient_data` without escaping plain-data validation errors. Added focused unit coverage for wrong-label record/mapping inputs and malformed mapping inputs.
- Blocker-resolution validation:
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_fingerprints.py` passed: 5 passed.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py` passed: 8 passed.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed: Ruff, Pyright, default isolated suite, config-extra isolated suite, and build.
    - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed and wrote `build/test-summary.md`: package 36 passed/1 skipped; unit 354 passed/1 skipped; contract 29 passed/2 skipped; integration 9 passed/5 skipped; e2e 5 passed; config-extra 288 passed/433 deselected.
- Focused confirmation gate: passed on current branch after the user-authorized blocker-resolution commit `b5f9070`; no remaining blockers. The focused comparison-helper unit check passed with 5 tests, the config-extra artifact/inspection contract check passed with 8 tests, `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed, and `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with config-extra 288 passed/433 deselected.
- Expanded-path PR body refine: completed. The public PR body at `docs/phases/config-artifact-fingerprints-pr-body.md` matches the phase plan, final diff, focused confirmation gate, validation evidence, scope boundaries, assumptions, and risks; it keeps workflow internals and budget details in this phase artifact. `@samcantrill` remains near the top of the body.
- PR submission: opened https://github.com/samcantrill/loom/pull/41 with explicit base `develop`, head `codex/config-artifact-fingerprints`, and title `Configuration - Phase 14: Artifact-Safe Fingerprints And Resume Comparison`. Immediate verification via `gh pr view 41 --json baseRefName,headRefName,state,url` returned base `develop`, head `codex/config-artifact-fingerprints`, state `OPEN`, url `https://github.com/samcantrill/loom/pull/41`. This is a root phase PR with no stack predecessor and no retarget/rebase work required.
- Stack maintenance: none; root phase targeting `develop`.
- Remaining blockers: none known.

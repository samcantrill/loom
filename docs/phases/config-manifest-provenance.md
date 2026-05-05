# Phase 13 Execution Plan: Provenance, Manifest, Source Records, And Redaction Population

## Metadata

- Status: implemented; implementation refinement completed; pre-submit blocker gate completed; user-authorized blocker-resolution pass completed; PR body draft completed; focused confirmation gate passed; expanded-path PR body refine completed
- Feature focus: Configuration
- PR title: `Configuration - Phase 13: Provenance, Manifest, Source Records, And Redaction Population`
- Branch: `codex/config-manifest-provenance`
- Worktree: `/home/samcantrill/work/loom-worktrees/config-manifest-provenance`
- Phase execution plan path: `docs/phases/config-manifest-provenance.md`
- Full plan: `docs/implementation-plans/implementation-plan-v1.md`
- Planning notes: `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Source phase: Phase 13 - Provenance, Manifest, Source Records, And Redaction Population
- Stack predecessor: none; Phases 1-12 are merged.
- Base branch: `develop`
- Base commit: `2f18ec1a031d8168dba3adaf56068474719e1da4`
- Target branch: `develop`
- Merge eligibility: root phase; eligible to merge into `develop` only after implementation, phase-scoped validation, pre-submit blocker gate, PR preparation/submission, and passing review/CI against `develop`.
- Workflow path: expanded path
- Workflow path rationale: schema/artifact population, redaction/security behavior, and future resume/CLI compatibility affect durable public-ish artifact contracts.
- Successor dependency notes: Phase 14 depends on this phase's artifact-safe source records and manifest references for default fingerprints and resume comparison. Phase 15 may add raw snapshot opt-in without changing the default metadata/hash-only source records. Phase 16 may align feature docs and broaden final e2e coverage.
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no blocking findings remain.
- Plan quality gate loop budget: fully used by the v1 implementation plan; do not reopen.
- Draft pass: completed by `loom_phase_planner` in this artifact; draft budget used.
- Refine pass: completed by `loom_phase_planner` in this artifact; refine budget used.
- Phase implementation refinement budget: used.
- Pre-submit blocker gate budget: used on 2026-05-06 by a full diff/body/evidence review before PR submission. The gate found stale user include source artifact records and nested plaintext secret override serialization leaks.
- User-authorized blocker-resolution budget: used on 2026-05-06 for the exact pre-submit blockers. Do not start another automated blocker/refinement pass without explicit user instruction.
- PR review budget: consumed by the full pre-submit blocker gate. Because the submitted diff changed after blocker resolution, only a bounded confirmation gate focused on those blockers and evidence drift remains before PR submission.
- PR body draft pass: completed in expanded-path draft pass; refine pass completed in expanded-path refine/open pass.
- Setup limitations: sandboxed `gh auth status` reported the stored token as invalid; approved outside-sandbox `gh auth status` succeeded. Approved `gh auth setup-git` succeeded. Sandboxed `git fetch origin` failed when writing `.git/FETCH_HEAD`; approved `git fetch origin` succeeded. Local `develop` resolved to the assigned base commit. Initial sandboxed `git worktree add` could not create the branch ref; approved `git worktree add` created the branch and worktree successfully.
- Blockers: none known after the user-authorized pre-submit blocker pass.

## Objective

Populate the v1 configuration artifact records that Phase 12 exposed as placeholders: artifact-safe provenance, metadata/hash-only source artifact records, a versioned composition manifest with source references, and the default unresolved/redacted config artifact, while ensuring default artifacts contain no raw source bytes or resolved runtime values.

## Full-Plan Context

Phases 1-12 established config/pipeline boundaries, artifact skeletons, strict loading, merge/override/include behavior, resolver scanning and runtime-only resolver execution, recipe expansion, validation, instantiation, and the public compose/inspection shape. Phase 13 replaces placeholder artifact population with real artifact-safe records. It must preserve accepted v1 decisions: `loom.config` is persistence-free; `loom.pipeline` must not depend on `loom.config` or manifests; `_copy_` stays unsupported; default artifacts are security-first and artifact-safe; resolver outputs and raw source bytes are not persisted by default; v1 remains Python-API-only; and there are no CLI commands or plugin, remote, or global-search include resolvers.

Future phases remain out of scope: Phase 14 computes artifact-safe fingerprints and resume comparison; Phase 15 handles raw source snapshot opt-in and dedupe policy; Phase 16 broadens final docs/e2e hardening. This phase may prepare records those phases will consume, but it must not implement their algorithms.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phases 1-12 are merged into `develop`.
- Why this base branch is correct: the manager selected `develop`, Phase 12 merge metadata is recorded in the v1 implementation plan, and local `develop` matches the assigned base commit.
- Retarget/rebase plan after predecessor merge: none for this root phase. The PR should target `develop`.
- Branch cleanup constraints: safe to delete only after the Phase 13 PR is merged and no successor branch depends on `codex/config-manifest-provenance`.

## Source Phase Summary

- Goal: populate artifact-safe provenance, default source metadata/hash records, manifest, and redacted artifact records.
- Required scope: source/order/include/override/recipe/resolver/security facts; default source metadata and content-hash records for base configs, overlays, includes, and recipe source references where available; versioned composition manifest; manifest references to source artifact records; default unresolved/redacted config artifact; plaintext-secret override warnings/docs.
- Required checkpoints: replace Phase 12 `artifact_placeholders` semantics with populated records; keep `source_artifacts`, `manifest`, and `provenance` mutually consistent; build redacted artifacts from unresolved artifact-safe data plus resolver metadata; document plaintext secret override risk.
- Acceptance criteria: manifest records all artifact-safe composition decisions needed for later resume and CLI inspection; manifest references the default source metadata/hash records it depends on; default artifact records contain no resolved runtime values; redaction applies before serializing sensitive authored paths.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/config/compose.py` owns the shared public staged orchestration and currently emits `artifact_placeholders` with empty `source_artifacts` and `fingerprint_records`; preserve the Phase 12 stage names and order unless the executor deliberately updates the public inspection contract tests in the same diff. `src/loom/config/api.py` owns `ComposedConfig` and `ConfigCompositionInspection`; `src/loom/config/artifacts.py` owns `CompositionManifest`, `SourceArtifactRecord`, and `ConfigFingerprintRecord`; `src/loom/config/provenance.py` owns `ConfigProvenance`, `ConfigSource`, and `ParsedOverride`; `src/loom/config/source_maps.py` owns value-to-source maps; `src/loom/config/includes.py` exposes include-site, local-customization, and recomposition records; `src/loom/config/interpolation.py` exposes resolver scan records; `src/loom/config/recipes/manifest.py` emits recipe manifest records; `src/loom/config/redaction.py` owns the current simple key-pattern redaction policy.
- Existing tests or harness behavior: contract tests for artifact records live in `tests/contracts/test_config_artifact_contract.py`; inspection shape tests live in `tests/contracts/test_config_composition_inspection_contract.py`; unit coverage exists in `tests/unit/loom/config/test_config_artifacts.py`, `test_config_provenance.py`, `test_redaction.py`, and `test_compose.py`; integration coverage exists in `tests/integration/config/test_compose_config.py`, `test_compose_includes.py`, `test_compose_overrides.py`, `test_compose_recipes.py`, `test_compose_resolvers.py`, and `test_source_map_integration.py`.
- Import-boundary or dependency constraints: production changes should stay under `loom.config` and docs. Do not import `loom.pipeline`, stores, CLI modules, plugin discovery, project code, network clients, or add runtime dependencies. Artifact modules should remain plain-data friendly and cheap relative to the existing config optional-dependency boundary.

## In-Scope Work

- Populate `ComposedConfig.source_artifacts` and `inspection.source_artifacts` with default metadata/hash `SourceArtifactRecord` values for base config, overlays, included files, and recipe source references where the current recipe manifest exposes stable metadata.
- Populate `CompositionManifest` from the staged composition outputs with source roles/order, include sites, replacement markers, user composition overrides, ordinary overrides, recipe manifest records, resolver-expression metadata, redaction/security policy facts, source artifact references, and `loom` version where locally available.
- Extend existing artifact/provenance record shapes additively only when the current fields are insufficient to represent required Phase 13 facts. Keep `schema_version` validation, `to_dict()`/`from_dict()` round trips, plain-data normalization, and unknown-field behavior coherent with existing tests.
- Enrich `ConfigProvenance` with artifact-safe composition facts needed for human/debug inspection: source/order, include authored/resolved metadata, local customizations, override operation kinds, recipe count/records or references, resolver-expression paths, source hashes, redaction policy, and security decisions.
- Change default `redacted` artifact population to redact the unresolved expanded artifact-safe config rather than the runtime-resolved config. Resolver expressions should remain authored strings in default artifacts; resolved resolver values must remain only in memory through `resolved`.
- Add redaction coverage for sensitive authored paths before artifact serialization, including secret-like keys introduced by files, includes, recipes, and overrides.
- Add warnings/docs snippets for plaintext secrets in override strings, recommending environment/runtime secret mechanisms and supported resolver references instead of literal `+auth.token=...` style values. This phase may surface a warning or security-note fact, but it must not reject plaintext overrides.
- Keep `compose_config(...)` and `inspect_config_composition(...)` using the same staged path. Preserve the existing stage names and order by default; change the `artifact_placeholders` payload from placeholder counts to populated-artifact summary facts only if the contract tests document the deliberate new semantics.

## Out-of-Scope Work

- Artifact-safe fingerprint comparison, default fingerprint algorithm changes, or resume comparison logic.
- Raw source bytes by default, raw source snapshot opt-in, raw payload dedupe behavior, or rebuild-from-missing-source policy.
- Resolved config persistence, run-store writes, store paths, or any file persistence from `loom.config`.
- CLI commands, CLI output formatting, or CLI inspection behavior.
- Pipeline ownership changes, `loom.pipeline` dependence on config artifacts, or manifest-as-pipeline API behavior.
- Plugin, remote, global-search, or custom include resolvers.
- `_copy_` support or Hydra defaults-list compatibility.
- Broad feature-doc alignment beyond the narrow plaintext-secret override snippet required by this phase.

## Assumptions

- Existing Phase 12 stage outputs are the preferred data source for artifact population; the executor should avoid recomposing or reading files a second time unless current staged data lacks a required source record.
- Source artifact records may include absolute paths as provenance context, but semantic references must use stable source role/order, content digest, config path or include site path, and a deterministic artifact reference such as `kind:order` or an equivalent manifest-local identifier. Absolute paths must not be the only semantic identity used by the manifest.
- `ConfigSource` remains base/overlay-only. Do not widen it just to represent includes or recipes; assemble `include` and `recipe` `SourceArtifactRecord` values from include-site/recomposition records and recipe manifest metadata.
- Include files currently travel through include records and loader `ConfigSource` metadata; the source artifact layer may label them as `include` even if lower-level loading reused base/overlay-style source facts internally.
- Recipe source records are best-effort in this phase: record stable recipe name/target/expanded hash/expanded path metadata already present in recipe manifests, and add a `recipe` source artifact only when it can be represented without introspecting raw project source bytes or adding project-code dependencies.
- Plaintext override warnings are documentation and inspectable/security metadata only; this phase does not block plaintext secret overrides or add a strict secret policy.
- Compatibility fingerprint fields may remain existing behavior until Phase 14 unless updating them is strictly required to remove resolved runtime values from artifact records. Any final fingerprint decision belongs to Phase 14.

## Scope Contract

Default artifacts are artifact-safe records, not persistence side effects. `loom.config` may return `CompositionManifest`, `SourceArtifactRecord`, `ConfigProvenance`, redacted unresolved config data, and inspection stage payloads, but it must not write them to disk, choose run-store locations, or expose CLI behavior.

`source_artifacts` must contain one default metadata/hash record for each loaded base and overlay source, one record for each included local/file source discovered during file-authored or user-composition include expansion, and metadata-only recipe records only when existing recipe manifest facts provide a stable reference. Valid `SourceArtifactRecord.kind` values stay `base`, `overlay`, `include`, and `recipe`. Each record must include `schema_version`, `kind`, `path`, `order`, `content_digest`, `size_bytes`, and plain-data metadata. For base/overlay records, use existing `ConfigSource` facts. For include records, use `IncludeSiteRecord` and recomposition context facts, including authored target, include site path, resolved path, target kind, explicit escape flag, source role/order, and source digest/size. For recipe records, use `RecipeManifestRecord` facts such as recipe name, target, expanded hash, expanded path, and `loom_version`; do not inspect callable source bytes.

Record identity and digest expectations: `content_digest` must be a stable digest of the source artifact content or safe artifact payload already available from existing loaders/manifests. For local YAML sources this is the loader/source digest. For recipe records without raw source ownership, use the recipe manifest's artifact-safe expansion hash or omit the recipe `SourceArtifactRecord` and keep the recipe facts in the manifest/provenance. `order` must be deterministic within a composed config and unique enough with `kind` to serve as a manifest reference. Manifest references must point back to records by deterministic plain-data identifiers and must not rely solely on absolute paths.

The manifest must be the machine-readable receipt for artifact-safe composition decisions. It must include or reference: base path and overlay order; source artifact references for base/overlay/include/recipe dependencies; include sites with authored target, resolved target metadata, target kind, explicit escape flag, replacement marker presence, and local customization paths; user composition include overrides separately from ordinary overrides, with override path, operation kind, order, and redacted value when sensitive; recipe manifest records; resolver scan records containing only config path, token, resolver name, and authored expression; redaction policy metadata naming the current key-pattern policy and redaction marker; artifact-safety/security facts stating that raw source bytes and resolved resolver outputs are excluded by default; and `loom`/schema version facts where available. It must not duplicate the fully resolved config.

`redacted` must be produced from the unresolved expanded artifact-safe config after includes, recipes, and overrides but before runtime interpolation output is serialized. Resolver expressions such as `${oc.env:SECRET}` remain authored strings in `unresolved` and `redacted`; resolved environment values remain only in `resolved`. Redaction must reuse `src/loom/config/redaction.py` and the current simple key-pattern policy as the default artifact boundary. Do not introduce a second redaction engine or a configurable secret-classification system in this phase.

`provenance` is the human/debug record and may carry broader plain-data metadata than the manifest, but it must use the same artifact-safe facts and references. It should include source/order, include authored/resolved metadata, local customizations, override operation kinds, recipe counts or records, resolver-expression paths, source hashes, redaction policy, and plaintext-secret override warning facts. It must not persist resolved resolver outputs, raw source bytes, constructed runtime objects, or the fully resolved runtime config.

Inspection payloads must remain stage-oriented diagnostics. Preserve existing stage names and order unless contract tests explicitly change them. Populate stage payloads additively with counts, references, and artifact-safety summaries; do not make inspection payloads the only place where a manifest/source/provenance fact exists.

`ComposedConfig.resolved` remains the in-memory runtime-resolved value for Python callers. `ComposedConfig.unresolved`, `ComposedConfig.redacted`, `manifest`, `source_artifacts`, `fingerprint_records`, `provenance`, and inspection artifact payloads must not persist resolved runtime values by default. Redaction must happen before any sensitive authored value is serialized into default artifact records.

The manifest is a narrow versioned artifact contract for future run-store, resume, and CLI inspection work. It may be represented by additive fields on `CompositionManifest` and plain-data `metadata`, but it must remain independent from `loom.pipeline` and must not become a pipeline construction input.

## Design Impact

- Maintainability: centralize artifact population near the existing staged composition output so provenance, manifest, source records, and redaction do not drift across duplicate composition paths.
- Extensibility: additive plain-data manifest/source/provenance records leave room for Phase 14 fingerprint comparison, Phase 15 raw snapshot opt-in, and future CLI inspection without changing pipeline behavior.
- Domain neutrality: records describe config composition facts generically; tests and docs should avoid project-specific model, dataset, experiment, or stage assumptions.
- Source-tree boundaries: production work stays in `loom.config`; pipeline, stores, CLI, plugin discovery, and project packages remain independent.

## Future Compatibility

- Phase 14 can compute artifact-safe fingerprints from the populated source artifacts, unresolved/redacted config, resolver-expression metadata, and manifest references without backfilling Phase 13 records.
- Phase 15 can add raw snapshot opt-in fields or records while preserving the default security-first metadata/hash behavior from this phase.
- Future CLI inspection can render manifest/provenance/source records without executing resolvers or requiring runtime values.
- Future run-store code can persist returned records as caller-owned data, but `loom.config` remains persistence-free.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep Phase 12 placeholder artifact records | Phase 13 acceptance requires populated manifest, provenance, source records, and redacted artifact data. |
| Build artifacts from the resolved runtime config | Would persist resolver outputs and violate the accepted security-first default. |
| Persist raw source bytes by default | Conflicts with the v1 default source-artifact policy; raw snapshots are Phase 15 opt-in or run-store policy. |
| Add a separate manifest format beside `CompositionManifest` | Increases contract drift after Phase 1 established the stable artifact skeleton name. |
| Widen `ConfigSource` to include include/recipe roles | Include and recipe facts already exist in include/recipe records; widening a base/overlay provenance helper would expand a lower-level contract without need. |
| Add a second redaction engine for artifacts | The accepted default boundary is the existing key-pattern redaction policy; a second policy would create drift and belongs to a future security policy phase. |
| Treat the manifest as a pipeline API | Violates the config/pipeline boundary and would couple runtime construction to config artifacts. |
| Block plaintext secret overrides in this phase | The assigned scope calls for warnings/docs, not a new strict secret policy. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Recipe source artifact records may be metadata-only or omitted when no stable source reference exists | Recipe implementations can be callables/classes without safe source-byte ownership; this phase must avoid project-code introspection and raw source persistence. | A future recipe/source provenance phase defines stable recipe source identity beyond target strings and manifest records. |
| Manifest references may use additive metadata rather than a richer dedicated reference model if the current contract can represent them safely | Keeps this phase small and avoids speculative schema design before Phase 14/15 consume the records. | Phase 14 fingerprint or Phase 15 raw snapshot implementation cannot consume references without ambiguous lookup. |
| Plaintext secret override handling is warning/documentation-only | The phase requires user guidance without changing override acceptance semantics. | A future security policy phase introduces strict secret classification or configurable redaction rules. |

## Reviewability

- Expected PR size and shape: contract-heavy config artifact population under `loom.config`, targeted docs snippet for secret overrides, and package/unit/contract/integration tests. No pipeline, store, CLI, raw snapshot, resume comparison, e2e runner behavior, or final fingerprint algorithm diff.
- Files and areas to inspect: `src/loom/config/compose.py`, `src/loom/config/api.py` if stage/output shape changes, `src/loom/config/artifacts.py`, `src/loom/config/provenance.py`, `src/loom/config/redaction.py`, `src/loom/config/includes.py` only for record plumbing, `src/loom/config/interpolation.py` only for resolver metadata reuse, `src/loom/config/recipes/manifest.py` only for safe recipe metadata, `docs/features/config.md` or a narrower docs location for secret handling. Test areas: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`, `tests/unit/loom/config/test_config_artifacts.py`, `test_config_provenance.py`, `test_redaction.py`, `test_compose.py`, and config integration tests.
- Scope-control checks: no raw source bytes; no resolved runtime values in default artifacts; no run-store writes; no CLI behavior; no pipeline imports; no `_copy_`; no plugin/remote/global include resolvers; no final fingerprint comparison; no resolved config persistence.

## Implementation Steps

1. Extend or normalize the artifact/provenance data contracts needed for Phase 13 population, keeping changes additive, plain-data serializable, and covered by contract tests before wiring compose.
2. Add source artifact population from existing source/load/include/recipe metadata, with stable source role/order and content digest records for base, overlays, includes, and safe recipe references. Do not widen `ConfigSource`; derive include/recipe records from their existing records.
3. Build manifest population from the existing staged composition facts, including source artifact references, include/replacement/customization records, override operation records, recipe manifest records, resolver scan records, redaction/security policy facts, and artifact-safe version metadata.
4. Update redacted artifact population so default redaction applies to unresolved artifact-safe config before artifact serialization, with resolver expressions preserved and sensitive authored paths redacted by the existing key-pattern redaction policy.
5. Enrich provenance and inspection stage payloads additively so compose and inspection expose consistent artifact-safe records without duplicate composition and without changing stage names/order unless contract tests are intentionally updated.
6. Add the plaintext-secret override docs/warning snippet and run focused package, unit, contract, and integration suites before PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_config_api.py`, `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: public config exports remain source-compatible; any additive artifact/provenance exports are intentional and cheap; importing `loom.config` does not import pipeline/store/CLI modules; `loom.pipeline` remains independent from `loom.config`, `ComposedConfig`, and manifests. This suite is not optional for Phase 13.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/config/test_config_artifacts.py`, `tests/unit/loom/config/test_config_provenance.py`, `tests/unit/loom/config/test_redaction.py`, `tests/unit/loom/config/test_compose.py`. Add focused helper tests near include/recipe/interpolation modules only when the implementation changes those helpers' behavior.
- Required assertions or deferral reason: source artifact records are populated for base/overlay/include sources with metadata/hash-only payloads; recipe source records are populated only when safe recipe manifest facts support them; manifest source references match populated source artifacts; provenance records include artifact-safe include/override/recipe/resolver/security facts; redaction handles secret-like keys and paths in unresolved data without mutating inputs; compose returns no placeholder-only manifest/source state; resolver scan records are reused for artifact-safe facts; resolved runtime values remain out of artifact fields; plaintext secret overrides are warned/documented but not rejected. This suite is not optional for Phase 13.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_config_artifact_contract.py`, `tests/contracts/test_config_composition_inspection_contract.py`.
- Required assertions or deferral reason: `CompositionManifest`, `SourceArtifactRecord`, and `ConfigProvenance` serialize and round-trip populated Phase 13 records; manifest references point to source artifact records it depends on by deterministic plain-data IDs rather than absolute-path-only identity; populated records reject non-plain data and unknown malformed fields according to local conventions; inspection stage records remain stable/additive and artifact-safe; stage names/order are preserved unless the contract test documents the deliberate replacement; contract tests explicitly assert no raw source bytes, resolved resolver outputs, constructed runtime objects, or fully resolved config payloads appear in default artifact records. This suite is not optional for Phase 13.

### Integration Suite

- Status: required.
- Expected paths: `tests/integration/config/test_compose_config.py`, `tests/integration/config/test_compose_includes.py`, `tests/integration/config/test_compose_overrides.py`, `tests/integration/config/test_compose_recipes.py`, `tests/integration/config/test_compose_resolvers.py`, and a focused `tests/integration/config/test_compose_provenance.py` for cross-feature artifact population cases.
- Required assertions or deferral reason: public `compose_config(...)` with base, overlays, recursive includes, user include replacement, recipes, ordinary overrides, and resolver expressions returns populated manifest/provenance/source records; source artifact references cover base/overlay/include roles and safe recipe references where available; redacted/unresolved artifacts contain no resolved `oc.env` values; resolver expressions are preserved in artifact-safe records; plaintext secret override docs/warnings are covered without changing override acceptance; inspection and composed config agree on artifact records. This suite is not optional for Phase 13.

### E2E Suite

- Status: deferred.
- Expected paths: none for Phase 13.
- Required assertions or deferral reason: the current e2e suite is runner/pipeline-oriented (`tests/e2e/test_local_pipeline_run.py`) and Phase 13 must not add CLI, store, runner, or pipeline behavior. Public `compose_config(...)` coverage for populated artifact records belongs in the required integration suite above. Broader e2e artifact persistence remains deferred to Phase 16.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected.
- Required assertions or deferral reason: raw source snapshot opt-in, raw payload dedupe, plugin/remote resolvers, network behavior, CLI inspection, store persistence, and runtime-value artifact policies are out of scope.

## Risks

- Manifest/source/provenance contracts can drift if Phase 13 adds parallel record shapes instead of extending the existing `CompositionManifest`, `SourceArtifactRecord`, and `ConfigProvenance` contracts.
- Redaction can accidentally run after runtime interpolation and leak resolved environment values. Tests must compare `resolved`, `unresolved`, `redacted`, manifest, and provenance on configs with `oc.env`.
- Include source metadata can be incomplete if only base/overlay `ConfigSource` records are considered. Include-site records and recomposition contexts must be included in the population source.
- Recipe source references may tempt unsafe project-code introspection. Keep recipe source records limited to safe manifest/catalog metadata unless the existing implementation exposes a stable source reference.
- Adding manifest references can over-specify Phase 14 fingerprint inputs. Keep this phase focused on artifact-safe facts and source dependencies, not comparison semantics.
- Pre-submit review may find scope drift, unresolved runtime-value leakage, or insufficient suite evidence. Known blockers must be resolved before PR submission or the phase must be marked blocked.
- A warning implementation for plaintext secret overrides can drift into policy enforcement. Tests and docs must confirm plaintext secret overrides remain accepted while artifact records surface the warning/security-note fact.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_config_provenance.py tests/unit/loom/config/test_redaction.py tests/unit/loom/config/test_compose.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py
UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/integration/config/test_compose_config.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_resolvers.py tests/integration/config/test_compose_provenance.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr
UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with contract/unit tests for populated artifact shapes; add source artifact population from `ConfigSource`, include records, and recipe manifest facts; add manifest population with deterministic source references; switch redacted artifact population to unresolved/redacted-safe data using the existing redaction policy; enrich provenance/inspection payloads; add integration coverage and the secret override docs/warning snippet.
- Tests to run with each slice: contract/unit artifact tests after model changes; redaction/unit compose tests after redacted artifact changes; integration include/override/recipe/resolver tests after compose wiring; package/import-boundary tests after export/import edits.
- Decisions the executor must not revisit: `loom.config` remains persistence-free; `loom.pipeline` must not depend on config or manifests; `_copy_` stays unsupported; `ConfigSource` remains base/overlay-only; include/recipe source artifacts are assembled from existing include/recipe metadata; default artifacts do not contain raw source bytes or resolved runtime values; resolver scan records are reused without persisting resolver outputs; redaction uses the existing key-pattern policy; plaintext secret overrides are warned/documented but accepted; v1 has no CLI; no plugin/remote/global include resolvers; no final fingerprint comparison or resume algorithm; no raw source snapshot opt-in or dedupe; no resolved config persistence.
- Conditions that require stopping for the manager: satisfying the phase appears to require persistence, raw snapshots, final fingerprint comparison, CLI/store behavior, pipeline ownership changes, resolved runtime value artifacts, raw source bytes in default records, public resolver/include policy changes, a second redaction engine, plaintext-secret rejection, or reopening the already-used plan quality gate.
- Expanded-path refinement notes: complete. Artifact reference shape, redaction serialization boundary, recipe-source fallback, plaintext-secret warning scope, suite decisions, and pre-submit blocker gate expectations are recorded above.

## Refinement And Review Budget Status

- Phase implementation refinement: used.
- Pre-submit blocker gate: used.
- User-authorized blocker-resolution pass: used.
- Focused confirmation gate: passed.
- PR review: consumed by the full pre-submit blocker gate; no separate general PR review remains unless the submitted diff changes after confirmation.

## Completion Notes

- Draft plan: completed by `loom_phase_planner`; committed as `plan: add phase execution plan`.
- Final phase execution plan: completed by `loom_phase_planner`; ready for implementation after commit `plan: refine phase execution plan`.
- Implementation summary:
- Composed `ComposedConfig`, `ConfigCompositionInspection`, and `CompositionManifest` with populated artifact-safe `source_artifacts` for base, overlays, includes, and safe recipe expansions, plus an unresolved artifact-safe `fingerprint_records` entry for future Phase 14 consumption.
- Added provenance metadata population for include/recomposition/customization records, override records (including redacted secret-like overrides), resolver scan records, recipe manifest facts, source-artifact references, and redaction/security policy facts.
- Moved redaction to operate on artifact-safe unresolved composition prior to interpolation while preserving resolver expressions in unresolved/redacted artifacts; runtime values remain in `resolved` only.
- Added plaintext-secret override warning snippet in `docs/features/config.md`.
- Refinement summary: expanded-path refinement made artifact population semantics, source record identity/digest expectations, redaction boundaries, plaintext-secret warning scope, suite decisions, and blocker-gate expectations explicit.
- Implementation refinement pass, 2026-05-06:
  - Validation output reviewed: phase diff against `develop`, implementation baseline `1234e24`, phase-scoped tests, `make validate-pr`, and `make test-summary`.
  - Blocking issues caused by this phase:
    - `fingerprint_records` included a `resolved` record derived from runtime-resolved config; narrowed default fingerprint records to the unresolved artifact-safe digest only.
    - Secret-like override artifact metadata and plaintext-secret warning facts retained raw override strings containing plaintext values; redacted those raw strings while preserving override acceptance.
  - Issues confirmed out of scope: no Phase 14 fingerprint comparison/resume behavior, persistence, CLI/store behavior, raw snapshots, plugin/remote/global include resolvers, `_copy_`, or pipeline import-boundary changes were introduced.
  - Fix evidence: targeted package/unit/contract/integration tests, `make validate-pr`, and `make test-summary` all passed after refinement.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/loom_uv_cache uv run --extra config pytest tests/package/test_config_api.py tests/package/test_import_boundaries.py tests/contracts/test_config_artifact_contract.py tests/contracts/test_config_composition_inspection_contract.py tests/unit/loom/config/test_config_artifacts.py tests/unit/loom/config/test_config_provenance.py tests/unit/loom/config/test_redaction.py tests/unit/loom/config/test_compose.py tests/integration/config/test_compose_config.py tests/integration/config/test_compose_includes.py tests/integration/config/test_compose_overrides.py tests/integration/config/test_compose_recipes.py tests/integration/config/test_compose_resolvers.py tests/integration/config/test_compose_provenance.py` passed: 100 passed.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed: Ruff passed, Pyright reported 0 errors, default suite passed with 427 passed/10 skipped, config-extra passed with 279 passed/432 deselected, and build succeeded.
  - `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed and wrote `build/test-summary.md`: package 36 passed/1 skipped; unit 354 passed/1 skipped; contract 28 passed/2 skipped; integration 9 passed/5 skipped; e2e 5 passed; config-extra 279 passed/432 deselected.
- E2E/opt-in status:
  - E2E: phase-scoped e2e coverage remains deferred per plan; existing harness e2e passed during `make test-summary`.
  - Opt-in suites: deferred per plan.
- PR preparation:
  - Expanded-path draft PR body completed at `docs/phases/config-manifest-provenance-pr-body.md`.
  - Confirmed worktree `/home/samcantrill/work/loom-worktrees/config-manifest-provenance`, branch `codex/config-manifest-provenance`, root target branch `develop`, and stack predecessor `none` match this phase plan.
  - Confirmed PR title remains `Configuration - Phase 13: Provenance, Manifest, Source Records, And Redaction Population`.
  - Reviewed final diff vs `develop`, this phase plan, implementation plan Phase 13 scope, validation evidence in `build/test-summary.md`, `.github/PULL_REQUEST_TEMPLATE.md`, and `.codex/templates/phase-pr-body.md`.
  - PR was not opened because Phase 13 is on the expanded path; `.codex/prompts/pr-body-refine.md` remains pending before PR submission.
  - PR preparation preserved workflow budgets at draft time: implementation refinement used; the later full pre-submit blocker gate consumed PR review budget, and the user-authorized blocker-resolution pass consumed the one scoped blocker-resolution allowance.
- User-authorized pre-submit blocker pass, 2026-05-06:
  - The pre-submit blocker gate found two blockers: stale user include source artifact records and nested/plaintext secret override serialization leaks.
  - The user-authorized blocker-resolution pass fixed both blockers in commit `a98f468`.
  - Fixed stale include source artifact records after user composition overrides. User include replacements now remove the replaced file-authored include record and add an artifact-safe record/reference for the replacement include file; brand-new user include additions now add a source artifact and manifest reference.
  - Fixed artifact-facing plaintext secret override serialization. `ConfigProvenance.to_dict()`, manifest metadata, provenance metadata, ordinary override records, and warning facts now redact raw override strings and nested secret-like JSON values with the default redaction policy while preserving plaintext override acceptance.
  - Added integration coverage for include replacement source artifact references, brand-new include addition references, and nested JSON secret override redaction across serialized provenance, manifest metadata, provenance metadata, and redacted artifacts.
  - Fix evidence: targeted Phase 13 suite, `make validate-pr`, and `make test-summary` all passed after this blocker-resolution pass.
- Focused confirmation gate, 2026-05-06:
  - Passed after the blocker-resolution pass and confirmed no remaining known blockers before PR submission.
  - Validation evidence after blocker pass: targeted Phase 13 suite passed with 100 passed; `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed; `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall 711 passed / 9 skipped / 432 deselected.
- Expanded-path PR body refine/open pass, 2026-05-06:
  - Confirmed worktree `/home/samcantrill/work/loom-worktrees/config-manifest-provenance`, branch `codex/config-manifest-provenance`, target branch `develop`, stack predecessor `none/root phase`, and PR title `Configuration - Phase 13: Provenance, Manifest, Source Records, And Redaction Population`.
  - Refined `docs/phases/config-manifest-provenance-pr-body.md` to keep workflow details in phase notes and make the GitHub checks row accurate for PR submission.
  - Confirmed `@samcantrill` remains near the top of the PR body.
  - Re-ran PR-preparation validation: `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed and `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall 711 passed / 9 skipped / 432 deselected.
  - GitHub auth and remote access were available after approved network-backed checks; branch `codex/config-manifest-provenance` was pushed to `origin`.
  - Opened PR #40: https://github.com/samcantrill/loom/pull/40
  - Verified PR #40 with `gh pr view 40 --json baseRefName,headRefName,state,url`: base `develop`, head `codex/config-manifest-provenance`, state `OPEN`.
- Stack maintenance:
  - None required (root phase branch). PR #40 targets `develop` directly and is merge-eligible only after human review/CI; no predecessor retargeting or rebase is needed.
- Remaining blockers:
  - None known after the user-authorized pre-submit blocker pass, focused confirmation gate, validation, and expanded-path PR body refine.

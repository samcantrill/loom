# V1 Post-Implementation Contract Audit And Remediation Plan

## Metadata

- Status: draft
- Related implementation plan:
  `docs/implementation-plans/implementation-plan-v1.md`
- Related planning notes:
  `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Related phase closeout:
  `docs/phases/harden-config-composition-v1.md`
- Trigger: D01-D36 validation after v1 Phase 16 merge
- Workflow: phase-based workflow after plan quality gate
- Plan quality gate: passed
- Blockers: none after plan-quality confirmation review; v1 contract gaps are
  assigned to phases below

## Goal

Close the remaining v1 contract gaps discovered by the D01-D36 validation pass
without expanding v1 into v2 CLI, plugin/remote resolver, sweep, `_copy_`, or
default raw/resolved persistence work.

This document is the post-v1 audit, decision record, and implementation plan for
bringing the merged v1 configuration surface into alignment with its accepted
design decisions. Individual phase execution plans should expand only one phase
at a time.

## Context

V1 implemented strict local/file config composition, source-aware includes,
user include replacement, recipes, runtime resolver handling, artifact-safe
records, raw source snapshot opt-in, public Python APIs, and final hardening
coverage.

The post-v1 validation found that many decisions are implemented, but several
security, boundary, provenance, and documentation details remain incomplete.
The most important gaps are:

- runtime interpolation occurs before artifact/provenance/fingerprint
  construction, even though those records are intended to be artifact-safe;
- `ConfigProvenance` still writes a legacy `resolved_fingerprint` derived from
  resolved runtime values;
- pipeline execution still persists full resolved config snapshots by default;
- structured config errors are not applied consistently to merge, ordinary
  override, recipe, instantiation, and artifact/provenance failures;
- some accepted v1 behavior is implemented but not clearly documented or
  regression-tested.

## Validation Ledger

| ID | Validation result | Post-v1 disposition |
| --- | --- | --- |
| D01 | Partial | Remove source-level pipeline-to-config import and add full-run boundary coverage. |
| D02 | Partial | Document untrusted configs as unsupported; consider error/help wording where relevant. |
| D03 | Implemented with docs gap | Add public `inspect_config_composition` docs and clarify it is not for pipeline construction. |
| D04 | Implemented | No post-v1 remediation. |
| D05 | Implemented | No post-v1 remediation. |
| D06 | Partial | Carry authorship through ordinary overrides and runtime interpolation diagnostics. |
| D07 | Implemented | No post-v1 remediation. |
| D08 | Implemented | No post-v1 remediation. |
| D09 | Implemented with coverage/docs gaps | Add literal-dot/no-escape docs and tests. |
| D10 | Partial | Implement JSON-quoted scalar literal override parsing and docs. |
| D11 | Partial | Reorder artifact-safe record generation before runtime interpolation. |
| D12 | Partial | Reject duplicate YAML keys, including duplicate `_include_`. |
| D13 | Implemented | No post-v1 remediation. |
| D14 | Implemented | No post-v1 remediation. |
| D15 | Implemented with coverage gaps | Add public compose/provenance coverage for explicit `../` include escapes. |
| D16 | Implemented | No post-v1 remediation. |
| D17 | Partial by strict reading | Record existing-site user include swaps as explicit replacement operations. |
| D18 | Implemented with coverage gap | Assert exact public provenance/manifest local-customization payloads. |
| D19 | Partial | Add remediation/include-stack context consistently to composition errors. |
| D20 | Partial docs | Remove or clearly supersede stale `_copy_` v1 scope in older roadmap docs; add overlay/include compose tests. |
| D21 | Partial | Preserve resolver expressions in all default artifacts; remove default resolved-runtime fingerprint emission. |
| D22 | Partial with accepted residual risk | Keep current guards; record opaque recipe branching on resolver text as accepted debt. |
| D23 | Implemented | Clean stale `change-needed` metadata where still misleading. |
| D24 | Implemented with docs/strictness caveat | Add product-facing dotted/colon/no-nested-lookup docs; decide whitespace policy. |
| D25 | Partial | Define pipeline-owned runtime object fingerprint policy; keep config fingerprints runtime-free. |
| D26 | Implemented | No post-v1 remediation. |
| D27 | Implemented | No post-v1 remediation. |
| D28 | Partial | Convert remaining v1 config errors to structured context-bearing errors where useful. |
| D29 | Partial | Stop default resolved config persistence and enforce artifact-before-resolver ordering. |
| D30 | Partial | Make provenance artifact-safe by default and add plaintext override warning example. |
| D31 | Partial | Remove default runtime-derived fingerprint-like provenance artifact. |
| D32 | Partial | Persist full composition manifests through run-store/pipeline without pipeline depending on config. |
| D33 | Implemented | No post-v1 remediation. |
| D34 | Implemented | No post-v1 remediation. |
| D35 | Implemented | Optional metadata test only. |
| D36 | Implemented | No post-v1 remediation. |

## Conflicts And Resolution Decisions

### D16 Versus D17 User Include Replacement

D16 intentionally allows existing-site bare user include replacement without a
YAML `_replace_` marker because override strings cannot naturally carry sibling
mapping markers. D17 says `_replace_: true` is required whenever an authored
`_include_` replaces accumulated mapping content.

Selected resolution:

- Preserve D16's existing public override syntax.
- Treat an existing-site user include override as an explicit replacement
  operation by definition.
- Record that replacement intent in manifest/provenance with an operation kind
  such as `user_include_replacement`.
- Do not require users to spell `_replace_` in override strings for existing
  file-defined include sites.

### Artifact-Safe Defaults Versus Legacy Resolved Fingerprint

D29-D31 require default records to avoid resolved runtime values and exact
runtime-value fingerprints. `ConfigProvenance.resolved_fingerprint` conflicts
with that if it is emitted by default.

Selected resolution:

- New provenance writes use `schema_version: 2` and omit top-level
  `resolved_fingerprint`.
- New provenance writes include top-level `artifact_fingerprint`, equal to the
  artifact-safe `ComposedConfig.fingerprint`, plus artifact-safe fingerprint
  facts in `metadata.fingerprint`.
- `ConfigProvenance.from_dict(...)` must continue to accept legacy
  `schema_version: 1` documents that contain top-level `resolved_fingerprint`.
  Legacy reads may expose that value through an explicitly named compatibility
  field or metadata key such as `metadata.legacy_resolved_fingerprint`; new
  writes must not re-emit it.
- `schema_version: 2` readers remain strict about unknown top-level fields.
- Any future resolved-runtime fingerprint must be explicit opt-in with security
  warnings and a distinct policy label.

### Manifest Additivity Versus Strict Unknown-Field Rejection

D32 describes an additive public-ish manifest contract. Current readers reject
unknown top-level fields.

Selected resolution:

- Preserve strict unknown-field rejection for `schema_version == 1` readers.
- Treat additivity as schema-versioned or `metadata`-scoped extension in v1-post.
- Do not silently tolerate arbitrary unknown top-level fields until a later
  bundle/catalog compatibility policy requires forward-tolerant readers.

### Built-In Resolver Scope

D21 mentions built-in OmegaConf resolvers, while implementation supports only
the explicitly allowed runtime resolver surface such as `oc.env`.

Selected resolution:

- Keep the allow-list security-first in v1-post.
- Document that `oc.env` is supported and other built-in resolver names remain
  deferred unless explicitly added with artifact-safety tests.
- Do not broaden resolver execution while fixing artifact ordering.

### Opaque Recipe Shape Dependency

D22 asks recipes that depend on executing resolver values for output shape to
fail explicitly. Loom can reject resolver-shaped recipe output keys, but cannot
generally prove that arbitrary trusted Python branched on unresolved resolver
text.

Selected resolution:

- Keep current explicit guards for resolver-shaped output keys and authored
  resolver expression preservation.
- Record opaque internal recipe branching on unresolved resolver text as
  accepted debt.
- Revisit only if users need deterministic recipe shape certification beyond
  trusted Python conventions.

### Run-Store Composition Manifest Contract

D32 requires pipeline persistence to retain full composition manifests without
making `loom.pipeline` depend on `loom.config` classes.

Selected resolution:

- Add a plain-data run-store protocol surface:
  `read_composition_manifest(run_id) -> dict[str, PlainData] | None` and
  `write_composition_manifest(run_id, manifest: Mapping[str, PlainData])`.
- Store the manifest in local runs at
  `config/composition_manifest.json`.
- Use a wrapper with exactly these top-level fields for schema version 1:
  `schema_version`, `run_id`, `created_at`, and `composition_manifest`.
- The wrapped `composition_manifest` payload is the plain serialized
  composition manifest produced by `loom.config`; store and pipeline code must
  treat it as plain data and must not import `loom.config` or manifest classes.
- `PipelineRunner` must not write `config/resolved.yaml` or
  `config/resolved.redacted.yaml` by default when the input is a composed config
  object. It should write artifact-safe config data and the composition manifest
  only when those plain/duck-typed fields are available.
- Plain mapping configs are still caller-provided data, not v1 composed-config
  artifacts. Existing snapshot behavior for plain mappings may remain
  conservative, but it must not be described as resolved-config replay.

## Suite Evidence Expectations

Every phase execution plan must translate this section into phase-scoped
package, unit, contract, integration, e2e, and opt-in suite obligations. A suite
may be explicitly deferred only when the phase does not touch behavior covered
by that suite. PR preparation should run `make validate-pr` and
`make test-summary` before opening or preparing a PR, or record why a narrower
validation set is the maximum available evidence.

## Phase Strategy

### Phase 1. Contract And Documentation Cleanup

Status: merged

Goal:

- Align source boundaries and user-facing docs with the accepted v1 decisions.

Scope:

- Remove the source-level `TYPE_CHECKING` import from `loom.pipeline` to
  `loom.config`.
- Add a full `PipelineRunner.run(...)` boundary test proving a direct
  `PipelineSpec` run does not import `loom.config`.
- Document untrusted configs as unsupported trusted project code.
- Document `inspect_config_composition` in the public config feature docs and
  explicitly say it is for inspection/debugging/tests, not pipeline
  construction.
- Document dot-path override no-escape behavior and strict `_target_` dotted or
  colon syntax.
- Clean stale `_copy_` v1-scope language in older roadmap docs or clearly mark
  those docs as superseded by `implementation-plan-v1.md`.
- Correct stale `change-needed` roadmap metadata where implementation and tests
  already resolved the decision.

Out of scope:

- Runtime behavior changes except the import-boundary cleanup.
- CLI commands, `_copy_`, plugin/remote resolvers, and persistence changes.

Required evidence:

- Package: import-boundary tests for direct Python pipeline use without config
  extras imported.
- Unit: focused test for the removed source-level type import if unit coverage
  is practical.
- Contract: deferred; no extension protocol contract changes.
- Integration: `PipelineRunner.run(...)` with direct `PipelineSpec` and no
  `loom.config` import.
- E2E: deferred; no user workflow behavior changes beyond documentation.
- Opt-in/config-extra: docs/example checks when touched.

Phase metadata:

- Branch: `codex/v1-post-contract-docs`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-contract-docs`
- Stack predecessor: none
- PR target: `develop`
- PR: https://github.com/samcantrill/loom/pull/44
- Merge: squash-merged into `develop` on 2026-05-06 after review approval and
  passing GitHub CI `checks`.
- Implementation summary: removed the source-level pipeline-to-config type
  import, added direct `PipelineRunner.run(...)` import-boundary regression
  coverage, and updated Phase 1 docs/roadmap metadata.
- Test results summary: `make validate-pr` passed; `make test-summary` passed
  with 755 passed and 9 skipped across package, unit, contract, integration,
  e2e, and config-extra rows. GitHub CI `checks` passed before merge.
- Follow-up notes: later phases still own strict authoring semantics,
  artifact-safe provenance/fingerprint ordering, run-store manifest
  persistence, structured errors, and recipe/resolver hardening. No successor
  branch depended on the Phase 1 branch at merge time.

### Phase 2. Strict Authoring And Override Semantics

Status: merged

Goal:

- Close strict authoring gaps that can otherwise hide user mistakes.

Scope:

- Add JSON scalar override parsing for quoted strings such as `"true"`,
  `"false"`, `"null"`, and numeric-looking values so they become literal
  strings without quote characters.
- Keep existing parsing for booleans, `null`, finite numbers, arrays, and
  objects.
- Add duplicate-key rejection during YAML loading. This should reject duplicate
  keys globally, not only duplicate `_include_`, because duplicate YAML keys are
  ambiguous before composition sees them.
- Add tests showing attempted literal-dot override escaping is not supported and
  mapping keys containing literal dots are not addressable by v1 override
  strings.
- Add public compose tests for `_copy_` rejection in overlays and included
  files.

Out of scope:

- Literal-dot escape syntax.
- List patching, deletion, or splice semantics.
- YAML schema authoring or project schema registries.

Required evidence:

- Package: deferred; no package surface changes.
- Unit: loader tests for duplicate YAML keys and override parser tests for typed
  and JSON-quoted scalar values.
- Contract: deferred; no extension protocol contract changes.
- Integration: public compose regression tests for duplicate keys,
  literal-dot/no-escape behavior, and overlay/include unsupported directives.
- E2E: deferred; compose public API coverage is sufficient.
- Opt-in/config-extra: config-marked suite rows must include the new loader and
  compose cases.

Phase metadata:

- Branch: `codex/v1-post-strict-authoring`
- Worktree: `/home/samcantrill/work/loom-worktrees/v1-post-strict-authoring`
- Stack predecessor: none
- PR target: `develop`
- PR: https://github.com/samcantrill/loom/pull/46
- Merge: squash-merged into `develop` on 2026-05-06 after phase review and
  passing GitHub CI `checks`.
- Implementation summary: added JSON double-quoted scalar override parsing,
  loader-local duplicate YAML key rejection, and public compose regressions for
  duplicate keys, literal-dot/no-escape override behavior, and `_copy_`
  rejection in overlays and includes.
- Test results summary: `make validate-pr` passed; `make test-summary` passed
  with 779 passed and 9 skipped across package, unit, contract, integration,
  e2e, and config-extra rows. GitHub CI `checks` passed before merge.
- Follow-up notes: duplicate-key config paths remain best effort from YAML
  nodes as accepted in the phase plan; Phase 3 still owns broader structured
  error/source-authorship completion. No successor branch depended on the Phase
  2 branch at merge time.

### Phase 3. Source Authorship And Structured Error Completion

Status: pending

Goal:

- Make strict composition errors consistently source-aware, path-aware, and
  machine-readable without leaking secret values.

Scope:

- Carry source/authorship metadata through ordinary value overrides.
- Attribute interpolation and unsupported resolver errors to the source of the
  authored value when available, including overlay- and override-authored
  values.
- Expose final-value authorship metadata in provenance or manifest metadata at
  a path/fact level that does not persist sensitive values.
- Convert merge and ordinary override failures to context-bearing
  `ConfigError` subclasses or add equivalent structured context to existing
  subclasses.
- Add remediation guidance to include/composition errors where an actionable
  fix exists.
- Include active include-stack context for nested include failures, not only
  cycles.
- Extend structured coverage to recipe expansion, target import/instantiation,
  interpolation, provenance, and artifact serialization failures when the
  context would help callers.

Out of scope:

- New public error class hierarchy churn beyond what is needed for structured
  context.
- Persisting raw secret values in error details.

Required evidence:

- Package: public error exports stay stable or receive package import coverage
  when touched.
- Unit: tests for authorship propagation and structured error construction.
- Contract: tests for error `to_dict()` shape and round-trip behavior.
- Integration: merge, override, include, resolver, recipe, target, and
  artifact/provenance failure cases through public composition APIs.
- E2E: deferred unless the phase changes public runner behavior.
- Opt-in/config-extra: redaction tests proving secret-like override values are
  not exposed.

### Phase 4. Artifact-Safe Ordering And Provenance

Status: pending

Goal:

- Make default config artifacts, provenance, manifests, and fingerprints
  artifact-safe by construction and by execution order.

Scope:

- Build source artifacts, redacted/unresolved artifact config, fingerprint
  records, provenance metadata, and composition manifest before runtime
  interpolation executes.
- Preserve resolver expressions and resolver paths in artifact-safe records.
- Write new `ConfigProvenance` documents as `schema_version: 2` with
  top-level `artifact_fingerprint` and no top-level `resolved_fingerprint`.
- Keep a legacy `schema_version: 1` reader for old provenance documents that
  contain `resolved_fingerprint`, without re-emitting that field on new writes.
- Store artifact-safe fingerprint facts in `metadata.fingerprint` or manifest
  records instead of a resolved-runtime digest.
- Keep public `ComposedConfig.fingerprint` as the artifact-safe digest.
- Add docs warning not to pass plaintext secrets through overrides, including a
  concrete example such as `+auth.token=...`; recommend environment resolvers
  for secrets.

Out of scope:

- Secret-aware opt-in runtime fingerprints.
- Default resolved config persistence.
- Broadening the runtime resolver allow-list.

Required evidence:

- Package: public config API compatibility coverage if `ConfigProvenance`
  exports or construction signatures change.
- Unit: tests proving environment value changes do not affect any default
  fingerprint or provenance-emitted digest.
- Contract: provenance/manifest contract tests for schema-version-2 writes and
  legacy schema-version-1 reads.
- Integration: public compose tests proving artifact-safe records are produced
  before resolver execution and preserve resolver expressions.
- E2E: deferred unless runner behavior is touched.
- Opt-in/config-extra: docs tests or example checks for secret warning wording.

### Phase 5. Pipeline Persistence And Runtime Fingerprints

Status: pending

Goal:

- Align pipeline/run-store persistence with v1 artifact-safe config boundaries
  without making `loom.pipeline` depend on `loom.config`.

Scope:

- Stop `PipelineRunner` from writing full resolved config snapshots by default
  for `ComposedConfig`.
- Persist artifact-safe/redacted config records and the full composition
  manifest through run-store APIs.
- Add the run-store protocol methods
  `read_composition_manifest(run_id)` and
  `write_composition_manifest(run_id, manifest)`.
- Add the local-store file `config/composition_manifest.json` with wrapper
  fields `schema_version`, `run_id`, `created_at`, and
  `composition_manifest`.
- Keep plain mapping config snapshot behavior conservative: if a plain mapping
  is persisted, it must be treated as caller-provided config data and not as a
  v1 resolved-config artifact.
- Ensure pipeline construction and execution remain usable without importing
  `loom.config`; use duck-typing or plain-data conversion at the boundary.
- Define runtime object fingerprinting outside `loom.config`. The accepted v1
  mechanism is explicit pipeline/runtime fingerprint input, using existing
  `StageSpec.fingerprint_fields`, `FingerprintContext.extra`, or the
  `Fingerprintable` protocol where appropriate.
- Add tests proving an output-affecting injected runtime object can change a
  stage fingerprint when explicitly accounted for, while config fingerprints
  remain runtime-free.

Out of scope:

- Automatic fingerprinting of arbitrary runtime objects.
- Remote stores, bundles, catalogs, or CLI inspection commands.
- Resolved-runtime replay guarantees.

Required evidence:

- Package: import-boundary tests proving pipeline/store modules do not import
  config.
- Unit: local-store tests for the `config/composition_manifest.json` wrapper and
  path validation.
- Contract: store protocol tests for composition manifest read/write using
  plain mappings.
- Integration: runner tests proving no default full resolved config snapshot is
  written for composed configs and that plain mappings keep conservative
  caller-provided behavior.
- E2E: public Python runner coverage for manifest persistence if practical.
- Opt-in/config-extra: planning/fingerprint tests for explicit runtime-object
  fingerprint inputs when config extras participate.

### Phase 6. Recipe Residual Risk And Coverage Hardening

Status: pending

Goal:

- Make recipe artifact-safety limits explicit and close coverage gaps that do
  not require new recipe semantics.

Scope:

- Record opaque Python recipe branching on unresolved resolver text as accepted
  debt.
- Keep current recipe output-key guard for resolver-shaped keys.
- Add tests around recipe manifest artifact-safe args and output hashes where
  gaps remain.
- Add public compose/provenance coverage for explicit relative include escapes
  such as `../shared/foo.yaml`.
- Add public provenance/manifest assertions for exact include sibling
  local-customization path/kind/value payloads.
- Add optional package metadata guard that v1-post still has no console script
  entry point.

Out of scope:

- Recipe sandboxing.
- Recipe argument override syntax.
- Proving arbitrary trusted recipe internals did not branch on unresolved
  resolver text.

Required evidence:

- Package: optional package metadata guard that no console script exists.
- Unit: recipe manifest artifact-safe args/output hash tests where gaps remain.
- Contract: deferred; recipe protocol shape is unchanged.
- Integration: public compose/provenance tests for relative escapes and include
  local customizations.
- E2E: deferred; no full workflow behavior changes.
- Opt-in/config-extra: config-marked rows must include the new recipe and
  compose coverage.

### Phase 7. Final Hardening, Documentation, And Evidence

Status: pending

Goal:

- Confirm the repaired v1-post behavior is internally consistent and ready to
  hand off to v2 planning.

Scope:

- Audit `docs/features/config.md`, `docs/features/provenance.md`,
  `docs/features/fingerprints.md`, `docs/features/resume.md`,
  `docs/features/pipeline.md`, `docs/loom.md`, and implementation-plan docs for
  stale resolved-persistence, `_copy_`, CLI, manifest, provenance, and security
  wording.
- Add or update representative public-Python e2e coverage for the repaired
  artifact-safe path.
- Update this plan's phase statuses and accepted debt ledger after each phase
  lands.
- Run final validation gates.

Out of scope:

- New v2 CLI behavior.
- `_copy_`, plugin/remote resolvers, sweeps, and remote stores.

Required evidence:

```sh
make validate-pr
make test-summary
```

Suite obligations:

- Package: final import and metadata guard sweep.
- Unit: targeted hardening tests for any final doc-discovered behavior gap.
- Contract: final config/provenance/store contract rows must pass.
- Integration: representative public Python artifact-safe compose and runner
  workflow coverage.
- E2E: at least one public Python v1-post workflow proving the repaired
  artifact-safe path end to end, unless already covered by integration and
  explicitly justified in the phase plan.
- Opt-in/config-extra: final `make test-summary` evidence must show config
  extras coverage or explain why unavailable.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Opaque recipe branching on unresolved resolver text cannot be proven generally. | Recipes are trusted Python code and can branch internally in arbitrary ways. | Users need certified deterministic recipe shapes beyond trust and current output guards. |
| Manifest top-level unknown fields remain rejected for schema version 1. | Strict readers preserve inspectability and catch misspelled artifact fields. | Bundle/catalog/remote inspection requires forward-tolerant partial readers. |
| Non-`oc.env` OmegaConf built-in resolvers remain deferred. | Artifact-safe resolver policy should grow by explicit allow-list and tests, not by broad enablement. | A concrete supported built-in resolver is requested and can be proven artifact-safe. |
| Runtime object fingerprinting is explicit pipeline policy, not automatic config behavior. | Arbitrary object hashing is domain-specific and can be unsafe or unstable. | Pipeline/runtime design adds declared fingerprint interfaces for runtime resources. |
| Existing global recipe registration remains Python convenience. | Explicit `RecipeCatalog` is the reproducible path, but the global helper supports notebooks and scripts. | Process-global recipe state causes reproducibility or test isolation failures despite explicit catalog docs. |

## Plan Quality Gate

Status: passed.

Before phase implementation starts, this plan must pass review for:

- whether the seven-phase sequence is reviewable;
- whether artifact-safe ordering is compatible with current public
  `ComposedConfig` behavior;
- whether provenance compatibility handles legacy `resolved_fingerprint`
  artifacts without continuing to emit runtime-derived digests by default;
- whether run-store manifest persistence preserves pipeline/config boundaries;
- whether duplicate YAML key rejection is acceptable as a strict authoring
  change;
- whether structured-error expansion is scoped enough to avoid broad exception
  churn; and
- whether accepted recipe and resolver debts are explicit enough for v2 CLI
  planning.

Gate budget status:

- Initial `loom_plan_reviewer` review: used; blocking findings were provenance
  schema transition and run-store persistence contract, with a high-severity
  suite-obligation gap.
- Automated plan refinement pass: used; this revision chose the provenance
  schema-version-2 contract, the run-store composition manifest API/path/wrapper,
  and per-suite evidence obligations.
- Confirmation review: used; no blocking findings remained and the plan was
  judged ready for phase implementation.

Refinement summary for confirmation reviewer:

- Resolved the provenance blocker by specifying new `ConfigProvenance`
  `schema_version: 2` writes with `artifact_fingerprint`, no top-level
  `resolved_fingerprint`, and legacy schema-version-1 read compatibility.
- Resolved the run-store blocker by specifying plain-data
  `read_composition_manifest` and `write_composition_manifest` methods, local
  file path `config/composition_manifest.json`, wrapper fields, and composed
  versus plain mapping runner behavior.
- Resolved the suite-obligation gap by adding a plan-level suite evidence rule
  and per-phase package/unit/contract/integration/e2e/opt-in expectations.

## Assumptions And Defaults

- The selected implementation plan for this work is this document after its
  plan quality gate passes.
- The workflow should use the default stacked phase workflow unless the user
  selects serial human-merge-gate mode.
- V1-post remains Python-API-only.
- `_copy_`, plugin/remote include resolvers, global include search, sweeps,
  resolved-runtime replay, default raw source persistence, and default resolved
  config persistence remain out of scope.
- Authored configs remain trusted project code; untrusted configs are
  unsupported.
- `loom.config` remains persistence-free.
- `loom.pipeline` must not depend on `loom.config` imports, manifests, or
  composition artifact classes.

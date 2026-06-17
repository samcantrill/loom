# Roadmap Stage 24 Implementation Plan: Weave Argv Config Shorthand

Status: reviewed; implementation-plan quality gate passed
Roadmap stage: `v24`
Planning document: `docs/roadmap/stage-24/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: Phase 2 pr_open
Blockers:

- Phase 2 PR #207 is open against `develop`; GitHub CI and automated review are
  the remaining merge gates.

## Summary

- Goal: add optional `weave` helpers that parse project CLI argv fragments into
  config value overrides and trailing-slash scoped overlays, then compose config
  through existing `weave` machinery.
- Source functionality-agreement gate:
  `docs/roadmap/stage-24/planning.md`; FR-1 through FR-6 are confirmed.
- Approved behavior: parse `<command> <base-config> ...`; treat no-slash LHS
  tokens as value overrides; treat trailing-slash LHS tokens as scoped overlays;
  resolve scoped overlay RHS files through scope-directory then base-directory
  lookup; apply scoped overlays before recipe expansion and value overrides
  after recipe expansion.
- Source behavior confirmation: user confirmed the planning artifact after
  design-safety review on 2026-06-17.
- Key design constraints: keep `weave` independent from Loom, add no first-party
  `weave` executable, add no broad `loom.cli` parser work, keep warnings on the
  argv helper result, and preserve existing `compose_config(...)` behavior.
- Source design-agreement gate: completed in the planning artifact; DAQ-1,
  DAQ-2, DAQ-4, and DAQ-5 were upheld; DAQ-3 was upheld with scoped-overlay
  provenance and artifact-safe fingerprint revisions.
- Future-roadmap impact: Stage 24 stays in optional config frontend behavior and
  does not alter execution, stores, scheduling, queues, resources, downstream
  operations, or future Hydra bridge scope.
- Reusable interface, adapter, or protocol assumptions: the helper is an
  argv-to-config adapter only. It introduces no backend, executor, store,
  scheduler, operation, event, notification, or pipeline protocol.
- Examples covered: `data.keyC=newValueC`, `keyD=newValueD`,
  `output_dir=results/model_B.yaml`, `data/=data_A`, `model/=model_B`,
  `model/pipeline/=pipeline_A`, absolute scoped overlay RHS paths, missing
  overlay diagnostics, `+runtime/=local`, and rejected `/=root`.
- Source phase shaping: three reviewable phases covering parser/records,
  scoped overlay composition, and public API/inspection/diagnostics/docs.
- Source plan quality gate: passed; non-blocking note addressed after
  `loom_plan_reviewer` review, one refinement pass, and confirmation review.
- Out of scope: first-party `weave` CLI executable, broad Loom CLI rewrite,
  Hydra/defaults/config-group behavior, escaped dot-path grammar, advanced list
  patching, untrusted config sandboxing, runtime execution, pipeline planning,
  and run-store writes.

## Implementation Workflow State

- Implementation-plan quality gate: passed; non-blocking note addressed
- Review pass: completed; initial blocker found
- Refinement pass: used; scoped-overlay inspection contract named
- Confirmation review: completed; no blocking findings remain
- Automatic merge mode: enabled after plan quality gate and phase PR gates
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-24/planning.md`
- Roadmap framing: confirmed by user on 2026-06-17.
- Functionality and behavior baseline: confirmed.
- Design agreement: resolved, with no unresolved `needs discussion` or blocked
  decisions.
- Design-safety review: passed on 2026-06-17.
- Design-safety revisions carried forward:
  - Keep top-level public exports narrow.
  - Keep argv warnings helper-local.
  - Represent scoped overlays as overlay-family source artifacts with explicit
    metadata by default.
  - Do not add a new `SourceArtifactRecord.kind` unless implementation planning
    records a schema-versioned compatibility decision.
  - Ensure scoped overlay values participate in source artifact metadata, value
    authorship, manifest metadata, and artifact-safe fingerprint payloads.
- Examples and validation strategy: confirmed in planning.
- Phase shaping: provisional three-phase shape accepted for drafting.
- Implementation-plan drafting approval: user explicitly approved drafting on
  2026-06-17.
- Implementation readiness blockers:
  - None for phase execution planning.
  - Phase implementation must wait for a scope-complete phase execution plan.

## Desired Outcome

When all phases are complete:

- `weave.compose_config_from_argv(...)` is available as the discoverable public
  helper for project-specific CLIs.
- `inspect_config_from_argv(...)` is available through `weave.api` as the
  inspection companion for debugging and audit workflows.
- Detailed result and record types are importable from `weave.api`; top-level
  exports remain narrow unless plan review accepts a broader public surface.
- The helper parses argv-like input with caller-provided command choices and an
  `allow_unparsed` option for command-specific arguments.
- Tokens starting with `-` are unparsed command args, not config shorthand.
- No-slash LHS tokens lower to existing value override parsing, including root
  keys, dotted paths, `+` add mode, booleans, null, numbers, JSON arrays and
  objects, JSON-quoted strings, and raw strings.
- Trailing-slash LHS tokens lower to scoped overlays with slash-separated scope
  paths and optional `+scope/=` add-only semantics.
- Scoped overlay RHS resolution tries scope-directory candidates first, then
  base-directory candidates, probes `.yaml` before `.yml` for relative stems,
  uses exact absolute paths, does not expand `~`, and records normalized
  relative escapes.
- Scoped overlays use normal recursive merge behavior, including `_replace_:
  true`, before recipe expansion.
- Value overrides apply after recipe expansion and win over scoped overlay
  content.
- `inspect_config_from_argv(...)` reports scoped overlay application through an
  argv-only inspection stage named `argv_scoped_overlays`, placed after
  `file_include_expansion` and before recipe interpolation/expansion, while
  `inspect_config_composition(...)` keeps its existing stage names and order for
  non-argv callers.
- Structured config errors cover malformed argv, unknown commands, missing base
  config path, unsupported root overlay, missing overlay files, non-mapping
  overlay sources, invalid target shapes, and disallowed unparsed args.
- Result-level warnings cover likely overlay mistakes without mutating
  `ComposedConfig` or persisted run artifacts.
- Inspection and artifact records make scoped overlays auditable through source
  artifact metadata, value authorship, manifest metadata, raw source snapshot
  references where applicable, and artifact-safe fingerprint facts.
- Existing direct `compose_config(...)` and `inspect_config_composition(...)`
  callers see no behavior change.

## What This Means In Practice

The implementation should extend `weave` in place rather than add a separate CLI
or parser package. The first phase defines the argv grammar and record shapes in
package-local code. The second phase teaches composition how to apply scoped
overlays at the confirmed insertion point while preserving source/provenance and
fingerprint contracts. The final phase exposes the public helpers, connects
warnings and inspection, updates docs, and proves end-to-end behavior.

The plan deliberately avoids generated wrapper YAML files. A scoped overlay is
recorded as an overlay-family authored source with metadata such as the authored
token, scope path, add/update mode, candidate paths, resolved path, and
insertion stage. Adding a new persisted source artifact kind is not part of the
default plan because design safety identified that as a schema compatibility
choice.

## Non-Goals

- No first-party `weave` executable or console script.
- No broad `loom.cli` integration or command parser rewrite.
- No Hydra bridge, defaults lists, config groups, or RHS inference.
- No escaped dot-path grammar or advanced list patching.
- No untrusted config sandboxing.
- No changes to runtime execution, pipeline planning, run stores, event systems,
  downstream operations, or scheduling.
- No behavior changes for existing direct `compose_config(...)`, explicit
  overlay paths, or explicit override-string callers.

## Constraints

- Follow `docs/structure.md` and `docs/GLOSSARY.md`.
- Keep Loom domain-neutral.
- Treat authored configs as trusted project code.
- Do not introduce heavyweight runtime dependencies.
- `weave` must not import `loom`.
- Keep config composition semantics in `weave`; Loom CLI remains presentation
  over public APIs.
- Keep warnings helper-local unless a future persisted argv audit artifact is
  explicitly requested.
- Keep public API names minimal and contract-tested.
- Preserve existing artifact-safe composition behavior unless an implementation
  decision records an explicit schema-versioned compatibility change.

## Design Principles

- Preserve existing composition semantics for callers that do not opt into the
  argv helper.
- Keep syntax explicit: trailing slash means scoped overlay; no slash means
  value override.
- Reuse existing parsers and merge/load/provenance machinery where possible.
- Keep project CLI concerns at the adapter boundary: parse argv tokens, return
  structured records, and let callers own display and process exits.
- Make scoped overlay auditability first-class through source/provenance and
  fingerprint records.
- Keep phases reviewable, with parser behavior separated from composition and
  public helper integration.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Helper ownership | Implement in `packages/weave`, not `loom.cli`. | Config shorthand semantics stay with config composition. |
| Public helper surface | Top-level export `compose_config_from_argv`; expose inspection helper and records through `weave.api`. | Keeps discoverability without over-expanding top-level public API. |
| Parser input shape | Parse `<command> <base-config> ...` and validate command against caller choices. | `weave` stays command-name agnostic. |
| Unparsed args | Tokens starting with `-` are unparsed command args; `allow_unparsed=False` fails. | Project CLIs can parse command-specific args explicitly. |
| Value syntax | No-slash LHS always lowers to existing override parser. | Path-like RHS values remain values and no RHS inference is added. |
| Overlay syntax | Trailing slash on LHS only; slash-separated scope path. | Overlay behavior is unambiguous and distinct from dot-path values. |
| Add semantics | `+path=value` and `+scope/=` use add-only semantics. | Missing-path creation is explicit. |
| Root overlay | `/=...` is rejected. | The helper avoids a second way to replace the whole base config. |
| RHS lookup | Scope-directory then base-directory lookup; `.yaml` before `.yml`; exact absolute paths. | Predictable shorthand over common config trees. |
| Composition order | Scoped overlays before recipe expansion; value overrides after recipe expansion. | Component swaps feed recipes, and final values still win. |
| Inspection contract | Define argv-only `argv_scoped_overlays` stage contract internally during scoped-overlay composition; expose it through `inspect_config_from_argv(...)` in Phase 3; leave non-argv `inspect_config_composition(...)` stage tuple unchanged. | Scoped overlays are debuggable without breaking existing inspection consumers while public API exposure remains phase-owned. |
| Source artifact kind | Treat scoped overlays as overlay-family source artifacts with metadata by default. | Avoids a persisted schema change unless later explicitly justified. |
| Warnings | Return helper-local warning records. | `ComposedConfig` and normal composition artifacts remain argv-agnostic. |
| Errors | Use config-owned structured errors. | Project CLIs can choose how to display or exit. |

## Conflicts And Tradeoffs

| Conflict or tradeoff | Resolution | Residual risk |
| --- | --- | --- |
| Convenience versus ambiguity | Require trailing slash for overlays and never infer overlay from RHS. | Users may forget the slash; warnings mitigate common mistakes. |
| Public API discoverability versus lock-in | Export only the main compose helper at top level by default. | Callers may ask for more top-level names later. |
| Provenance clarity versus schema churn | Store scoped overlay facts as metadata on overlay-family artifacts. | A future manifest schema revision may still be needed if metadata becomes too broad. |
| Phase granularity versus integration cost | Keep three phases: parser, composition, public API/audit. | If Phase 2 shows provenance requires a schema change, split or block before implementation. |
| CLI UX versus package boundary | Return structured data and warnings; do not print or exit. | Project CLIs must format diagnostics themselves. |

## Maintainability Assessment

The plan is maintainable because it keeps the new grammar in one package-local
module, reuses existing override parsing, and avoids broad CLI framework code.
Composition changes are limited to a scoped overlay insertion point and artifact
record integration. The most delicate area is source/provenance/fingerprint
participation; that is isolated in Phase 2 with explicit tests and stop
conditions.

## Extensibility Assessment

The helper remains a narrow argv-to-config adapter. Future Loom CLI adapters can
call it without inheriting a CLI framework. Future Hydra bridge work can remain
separate because this plan does not add defaults lists, global config groups, or
RHS inference. Future artifact-schema work can add a dedicated source kind only
with a schema-versioned compatibility decision.

## Technical Debt Ledger

| Debt or accepted risk | Why accepted | Revisit trigger | Owner phase |
| --- | --- | --- | --- |
| Detailed result/warning record fields become public through `weave.api`. | The helper needs typed records for project CLI callers and tests. | Plan review or user feedback shows fields are too broad or unstable. | Phase 1 / Phase 3 |
| Scoped overlays use overlay-kind artifacts with metadata rather than a new kind. | Avoids schema churn while preserving auditability. | Metadata becomes ambiguous, or downstream consumers need a first-class scoped kind. | Phase 2 |
| Warnings are not persisted outside the helper result. | Keeps argv UX out of normal composition artifacts. | A future persisted argv audit artifact is requested. | Phase 3 |
| No escaped dot-path grammar. | Existing override parser behavior is preserved. | A future path grammar stage adds escaped segments. | Deferred |
| No first-party CLI executable. | Stage 24 targets project-specific CLI authors. | A future roadmap stage explicitly adds a `weave` CLI. | Deferred |

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `weave-argv-parser-records` | merged | `codex/weave-argv-parser-records` | [#206](https://github.com/samcantrill/loom/pull/206) | `packages/weave` argv parsing and records | Define argv classification, RHS lookup, record shapes, and parser diagnostics. | Unit/API tests for parser and records. | Value tokens, scoped overlay tokens, candidate paths, unparsed args, root overlay rejection. |
| 2 | `weave-scoped-overlay-composition` | pr_open | `codex/weave-scoped-overlay-composition` | [#207](https://github.com/samcantrill/loom/pull/207) | `packages/weave` composition/provenance/fingerprints | Apply scoped overlays at the confirmed composition point with audit records. | Integration/contract tests for merge order, source artifacts, authorship, fingerprints. | `data/=data_A`, `model/=model_B`, `model/pipeline/=pipeline_A`, `_replace_`. |
| 3 | `weave-argv-api-inspection` | pending | `codex/weave-argv-api-inspection` | pending | Public API, inspection, warnings, docs | Expose public helpers and finish diagnostics, docs, and end-to-end validation. | Contract/API/docs tests plus `make validate-pr` and `make test-summary`. | End-to-end argv helper examples and warning/error cases. |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Implementation-plan quality gate initially blocked on unnamed scoped-overlay inspection contract. | Repository phase workflow | Ran `loom_plan_reviewer`, applied one refinement pass, and completed confirmation review. | passed; non-blocking note addressed |
| Remaining phase execution plans do not exist. | Phase workflow | Create a scope-complete phase execution plan before each remaining phase begins. | pending for Phase 2 and Phase 3 |

## Phase 1: Argv Parser And Records

Status: merged
Slug: `weave-argv-parser-records`
Branch: `codex/weave-argv-parser-records`
Worktree: `/nas/home/can134/work/loom-worktrees/weave-argv-parser-records`
PR: [#206](https://github.com/samcantrill/loom/pull/206)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: define the argv shorthand grammar, record shapes, RHS candidate
  resolver, and structured parser diagnostics without changing config
  composition behavior.
- Files/modules owned:
  - New argv/shorthand module under `packages/weave/src/weave/`.
  - `packages/weave/src/weave/api.py` only for record exports if needed by the
    chosen public type boundary.
  - `packages/weave/src/weave/errors.py` only for config-owned error contexts if
    existing errors are insufficient.
  - `packages/weave/tests/unit/config/` parser and record tests.
  - `packages/weave/tests/test_import.py` if API imports are introduced.
- Behavior implemented:
  - Parse argv-like input into command, base config path, value override tokens,
    scoped overlay requests, and unparsed args.
  - Validate command against caller-provided command choices without hard-coded
    command names.
  - Treat tokens starting with `-` as unparsed command args.
  - Enforce `allow_unparsed=False` failure behavior.
  - Classify no-slash LHS tokens as value override strings.
  - Recognize trailing-slash scoped overlay LHS tokens, including `+scope/=`.
  - Reject root overlay syntax such as `/=root`.
  - Resolve scoped overlay RHS candidate paths according to scope-directory then
    base-directory lookup, suffix rules, exact absolute paths, no `~` expansion,
    and normalized relative escapes.
- Decisions applied: DD-1, DD-2, DD-3, DAQ-1, DAQ-5.
- Examples or docs covered: parser-level examples from the planning artifact;
  no user-facing feature-doc status change yet.
- Out of scope:
  - Loading scoped overlay YAML sources.
  - Merging scoped overlays into composed config.
  - Source artifacts, provenance, fingerprints, or public compose helper.
- Dependencies: existing `overrides.py` parser for value override validation
  where practical.

### Tasks

- Add internal argv record dataclasses with plain-data-safe fields.
- Add token classification and command/base path parsing.
- Add scoped overlay LHS parsing with add/update mode and slash-segment
  validation.
- Add RHS candidate resolution with deterministic candidate ordering.
- Add structured parser errors with token, scope, RHS, command, and candidate
  context where relevant.
- Add unit tests for every documented parser edge case.
- Add API/import tests for any record types intentionally exposed in Phase 1.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest packages/weave/tests/unit/config/test_argv.py` | Parser, resolver, and record unit coverage. | yes |
| `uv run pytest packages/weave/tests/test_import.py` | Public import coverage if Phase 1 exposes records. | yes if exports change |
| `uv run pytest packages/weave/tests/unit/config/test_overrides.py` | Confirm value override parser behavior remains stable. | yes |

### Acceptance Evidence

- Behavior evidence: parser tests cover command choices, base config path,
  no-slash values, trailing-slash overlays, `+scope/=`, absolute and relative
  RHS paths, suffix probing, no `~`, unparsed args, and root overlay rejection.
- Design-decision evidence: tests prove no RHS inference and no dot-path overlay
  grammar.
- Future-roadmap compatibility evidence: no Loom CLI or Hydra concepts are
  introduced.
- Interface, adapter, or protocol reuse evidence: records are argv/config
  adapter records only.
- Documentation evidence: docstrings or test names map to feature-doc examples.
- Domain-neutrality evidence: no project/domain-specific commands, config keys,
  or schemas are hard-coded.

### Phase Workflow State

- Phase execution plan: completed
- Planning/refinement budget: used
- Implementation/refinement budget: used
- PR review budget: used
- Blocker-resolution budget: unused
- Pre-submit blocker gate: passed
- Merge record: PR #206 merged into `develop` with squash merge commit
  `6b649e090e96d666a0e4aaa665248ab1173efe9c` on 2026-06-17.

### Risks And Stop Conditions

- Risks: exposing too many public record fields too early.
- Stop conditions:
  - Parser implementation needs a broader CLI framework.
  - Existing override parser cannot be reused without changing its public
    semantics.
  - Candidate resolution requires global search paths or config groups.
- Assumptions: record names and module names may be refined in phase planning as
  long as the public API remains narrow and contract-tested.

### Completion Summary

- Implementation: added private `weave._argv` parser records and
  `parse_config_argv(...)` for command/base parsing, no-slash value override
  lowering, trailing-slash scoped overlay request parsing, RHS candidate
  resolution, unparsed arg handling, and structured argv diagnostics.
- Validation: `make validate-pr` passed; `make test-summary` passed with
  `2513 passed, 0 failed, 0 errors, 3 skipped, 2087 deselected`; GitHub CI
  `checks` passed.
- PR: [#206](https://github.com/samcantrill/loom/pull/206), targeting
  `develop` from `codex/weave-argv-parser-records`.
- Merge: merged into `develop` on 2026-06-17 with squash merge commit
  `6b649e090e96d666a0e4aaa665248ab1173efe9c`.
- Follow-up: Phase 2 should consume the private parser records for scoped
  overlay composition and must still create a scope-complete execution plan
  before implementation.

## Phase 2: Scoped Overlay Composition

Status: pr_open
Slug: `weave-scoped-overlay-composition`
Branch: `codex/weave-scoped-overlay-composition`
Worktree: `/nas/home/can134/work/loom-worktrees/weave-scoped-overlay-composition`
PR: [#207](https://github.com/samcantrill/loom/pull/207)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path

### Scope

- Goal: integrate scoped overlay requests into config composition at the
  confirmed insertion point while preserving authorship, source artifacts,
  manifests, raw snapshot references where applicable, and artifact-safe
  fingerprints.
- Files/modules owned:
  - `packages/weave/src/weave/compose.py`
  - `packages/weave/src/weave/load.py`
  - `packages/weave/src/weave/merge.py`
  - `packages/weave/src/weave/source_maps.py`
  - `packages/weave/src/weave/provenance.py`
  - `packages/weave/src/weave/artifacts.py`
  - `packages/weave/src/weave/fingerprints.py`
  - Parser module introduced in Phase 1, as needed for composition records.
  - Package-local unit, integration, and contract tests.
- Behavior implemented:
  - Load scoped overlay sources as mappings and fail for missing or non-mapping
    sources.
  - Apply scoped overlays after base config, explicit overlays, and file-authored
    includes are composed, and before recipe expansion.
  - Apply normal recursive merge semantics at the scoped target, including
    `_replace_: true`.
  - Enforce `scope/=` requires an existing target while allowing leaf-to-mapping
    replacement, and `+scope/=` creates only missing scopes.
  - Keep value overrides after recipe expansion unchanged.
  - Define the internal argv inspection stage contract `argv_scoped_overlays`,
    placed after `file_include_expansion` and before recipe
    interpolation/expansion, without exporting `inspect_config_from_argv(...)`
    in this phase.
  - Preserve the existing non-argv `inspect_config_composition(...)` stage names
    and order.
  - Represent scoped overlays as overlay-family source artifacts with metadata,
    not a new source kind by default.
  - Ensure scoped overlay values contribute to value authorship, manifest
    metadata, raw snapshot references where applicable, and artifact-safe
    fingerprint facts.
- Decisions applied: DAQ-3, DAQ-4, DD-5.
- Examples or docs covered: config-tree examples for `data/=data_A`,
  `model/=model_B`, `model/pipeline/=pipeline_A`, and `_replace_` behavior.
- Out of scope:
  - Public `compose_config_from_argv(...)` helper.
  - Public `inspect_config_from_argv(...)` helper or `weave.api` export.
  - Warning UX for likely overlay mistakes.
  - First-party CLI integration.
  - New persisted `SourceArtifactRecord.kind` unless phase planning records and
    justifies a schema-versioned compatibility decision before implementation.
- Dependencies: Phase 1 parser/record output.

### Tasks

- Add internal composition input for scoped overlay records without changing the
  public `compose_config(...)` signature.
- Load scoped overlay YAML through existing load/source mechanisms where
  possible.
- Add scoped target merge helper and target existence/add-mode validation.
- Add or extend source map/provenance authorship so scoped overlay values report
  their source accurately.
- Add source artifact metadata fields for scoped overlay source path, authored
  token, scope path, candidate paths, add/update mode, and insertion stage.
- Add artifact-safe fingerprint facts for scoped overlay source artifacts and
  changed authored values.
- Add internal inspection plumbing for the `argv_scoped_overlays` stage contract
  and contract tests proving non-argv inspection output remains unchanged.
- Add integration and contract tests for merge order, provenance, manifests,
  raw snapshot references where applicable, and fingerprint changes.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest packages/weave/tests/integration/config/test_compose_argv_scoped_overlays.py` | End-to-end scoped overlay composition behavior. | yes |
| `uv run pytest packages/weave/tests/unit/config/test_config_provenance.py packages/weave/tests/unit/config/test_config_fingerprints.py` | Authorship and fingerprint invariants. | yes |
| `uv run pytest packages/weave/tests/contracts/test_config_artifact_contract.py packages/weave/tests/contracts/test_config_composition_inspection_contract.py` | Artifact and inspection contract coverage. | yes |
| `uv run pytest packages/weave/tests/integration/config/test_compose_recipes.py packages/weave/tests/integration/config/test_compose_overrides.py` | Recipe/order and existing override behavior remain stable. | yes |

### Acceptance Evidence

- Behavior evidence: scoped overlays merge at target scope with correct add/update
  behavior and ordering relative to recipes and value overrides.
- Design-decision evidence: tests prove no new source artifact kind is required
  unless explicitly accepted.
- Inspection-contract evidence: internal argv inspection plumbing produces the
  `argv_scoped_overlays` stage in the scoped-overlay insertion position, public
  export remains deferred to Phase 3, and non-argv
  `inspect_config_composition(...)` keeps its existing stage tuple.
- Future-roadmap compatibility evidence: no execution, store, scheduler, or
  downstream operation contracts are touched.
- Interface, adapter, or protocol reuse evidence: composition accepts scoped
  overlay inputs as config composition inputs, not CLI framework state.
- Documentation evidence: inspection payload names and metadata fields are
  clear enough for Phase 3 docs.
- Domain-neutrality evidence: test fixtures use generic config trees and avoid
  domain-specific pipeline semantics.

### Phase Workflow State

- Phase execution plan: completed
- Planning/refinement budget: used
- Implementation/refinement budget: used
- PR review budget: unused
- Blocker-resolution budget: 1/3 used
- Pre-submit blocker gate: passed
- PR open record: PR #207 opened from `codex/weave-scoped-overlay-composition`
  to `develop` and verified with `gh pr view`.
- Merge record: pending; GitHub CI was in progress when PR-open metadata was
  recorded.

### Risks And Stop Conditions

- Risks: provenance/fingerprint changes may be broader than expected.
- Stop conditions:
  - A new source artifact kind appears necessary.
  - Scoped overlay facts cannot be represented artifact-safely without changing
    manifest schema.
  - Existing non-argv composition inspection contracts would change.
- Assumptions: if a schema-versioned source kind or manifest change is needed,
  Phase 2 must stop for plan refinement before implementation continues.

### Completion Summary

- Implementation: added private scoped-overlay composition plumbing, source-map
  target merge helpers, overlay-family artifact metadata, scoped overlay
  authorship/provenance/fingerprint facts, internal argv-only
  `argv_scoped_overlays` inspection stage support, and package-local tests.
- Validation: `make validate-pr` passed after one scoped blocker-resolution fix;
  `make test-summary` passed with `2522 passed, 0 failed, 0 errors, 3 skipped,
  2087 deselected`.
- PR: [#207](https://github.com/samcantrill/loom/pull/207), targeting
  `develop` from `codex/weave-scoped-overlay-composition`.
- Merge: pending
- Follow-up: automated phase review and GitHub CI must pass before merge; Phase
  3 should branch from updated `develop` after Phase 2 merges unless a GitHub
  blocker requires stacked continuation.

## Phase 3: Public Argv API, Inspection, Diagnostics, And Docs

Status: pending
Slug: `weave-argv-api-inspection`
Branch: `codex/weave-argv-api-inspection`
Worktree: `/home/samcantrill/work/loom-worktrees/weave-argv-api-inspection`
PR: pending
Base branch: `develop` after Phase 2 merges; otherwise stack on
`codex/weave-scoped-overlay-composition`
Target branch: `develop` for root PR, or predecessor branch while stacked
Workflow path: expanded path

### Scope

- Goal: expose the public argv helpers, finish result/warning diagnostics,
  update docs, and prove the full project-CLI adapter behavior end to end.
- Files/modules owned:
  - `packages/weave/src/weave/api.py`
  - `packages/weave/src/weave/__init__.py`
  - Parser/composition modules from Phases 1 and 2
  - `docs/features/config.md`
  - Package-local contract, integration, import, and docs/example tests
- Behavior implemented:
  - Add `compose_config_from_argv(...)` with default `argv=None` support for
    `sys.argv[1:]`-style input.
  - Add `inspect_config_from_argv(...)` through `weave.api`.
  - Top-level export only `compose_config_from_argv` unless plan review accepts
    more.
  - Return command, base config path, composed config or inspection, unparsed
    args, value override records, scoped overlay records, and warnings.
  - Keep warnings on argv helper result only.
  - Emit non-fatal warnings for likely overlay mistakes, including no-slash
    mapping replacement when RHS looks overlay-like.
  - Preserve existing public `compose_config(...)` and
    `inspect_config_composition(...)` behavior and stage contracts for non-argv
    callers.
  - Update feature docs from proposal language to implemented behavior as
    appropriate.
- Decisions applied: DAQ-1, DAQ-2, DAQ-5, DD-4.
- Examples or docs covered: all planning examples plus warning and structured
  error examples.
- Out of scope:
  - First-party CLI executable.
  - Loom CLI adapter work.
  - Persisting argv warnings outside helper result.
- Dependencies: Phases 1 and 2.

### Tasks

- Add public helper wrappers and parameter validation.
- Add result records and warning records to the public API boundary.
- Add top-level export for `compose_config_from_argv` and contract tests proving
  the intended import surface.
- Add helper-local warning generation after composition has enough target-shape
  context.
- Add end-to-end integration tests for composed config output and inspection.
- Add structured error tests for malformed argv, unknown commands, missing base
  config, missing overlay, non-mapping overlay, invalid target shape, root
  overlay, and unparsed args.
- Add public-helper inspection tests proving `inspect_config_from_argv(...)`
  exposes `argv_scoped_overlays` and legacy `inspect_config_composition(...)`
  remains unchanged.
- Update feature docs and examples to reflect implemented behavior.
- Run final validation gates and prepare suite-level evidence for PR body.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest packages/weave/tests/test_import.py packages/weave/tests/contracts/test_config_error_contract.py` | Public API and structured error contract coverage. | yes |
| `uv run pytest packages/weave/tests/integration/config/test_compose_argv_from_cli.py` | End-to-end public helper behavior. | yes |
| `uv run pytest packages/weave/tests/contracts/test_config_composition_inspection_contract.py packages/weave/tests/contracts/test_config_artifact_contract.py` | Inspection/artifact contracts after public helper integration. | yes |
| `make validate-pr` | Required PR validation gate. | yes |
| `make test-summary` | Suite-level evidence for PR preparation. | yes |

### Acceptance Evidence

- Behavior evidence: public helpers compose and inspect documented argv examples
  and return structured result records.
- Design-decision evidence: import tests prove top-level export breadth and
  `weave.api` record access.
- Future-roadmap compatibility evidence: no first-party CLI, Loom CLI, runtime,
  store, scheduler, or downstream operation behavior is introduced.
- Interface, adapter, or protocol reuse evidence: helper result is a config
  adapter result, not a command framework.
- Documentation evidence: `docs/features/config.md` reflects the implemented
  helper behavior and deferrals.
- Domain-neutrality evidence: examples stay generic and config-focused.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: unused
- Pre-submit blocker gate: not run
- Merge record: pending

### Risks And Stop Conditions

- Risks: public helper result may expose too many fields; warning heuristics may
  be too broad.
- Stop conditions:
  - Public API shape needs a larger design decision than recorded here.
  - Warning behavior requires mutation of `ComposedConfig` or persisted artifacts.
  - End-to-end helpers require Loom CLI imports.
- Assumptions: warning heuristics stay conservative and non-fatal.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Cross-Phase Validation

- Full relevant test command: `make validate-pr`
- Suite evidence command: `make test-summary`
- Package-local focus: parser unit tests, scoped overlay integration tests,
  artifact/provenance/fingerprint contract tests, public API/import tests, and
  docs/example tests.
- Docs/template checks: `docs/features/config.md` must describe implemented
  behavior and deferrals without promising a first-party CLI.
- Domain-neutrality checks: no project-specific commands, model names beyond
  generic examples, pipeline semantics, stores, schedulers, or executor-specific
  behavior in implementation code.
- Example/demo checks: documented examples should have matching tests or
  package-local fixtures.
- Inspection contract checks: argv inspection includes `argv_scoped_overlays`
  after file include expansion and before recipe interpolation/expansion;
  non-argv inspection stage names and order remain unchanged.
- Manual review focus: public API breadth, warning/result field stability,
  source artifact metadata, value authorship, fingerprint payload changes, and
  preservation of non-argv composition behavior.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Initial implementation-plan review found unnamed scoped-overlay inspection stage/payload. | blocker | Named argv-only `argv_scoped_overlays` stage for `inspect_config_from_argv(...)`, placed after `file_include_expansion` and before recipe interpolation/expansion; non-argv `inspect_config_composition(...)` stage tuple must remain unchanged and contract-tested. | resolved; confirmation review passed |
| Confirmation review noted Phase 2 / Phase 3 boundary for `inspect_config_from_argv(...)` export timing. | non-blocking | Refined Phase 2 to own internal `argv_scoped_overlays` inspection plumbing only and defer public `inspect_config_from_argv(...)` helper/export to Phase 3. | resolved; Phase 2 plan must preserve boundary |

Gate result:

- Status: passed; non-blocking note addressed
- Review evidence: initial `loom_plan_reviewer` review blocked on the unnamed
  scoped-overlay inspection contract; plan refined to name the contract.
- Confirmation evidence: follow-up `loom_plan_reviewer` confirmation review found
  no blocking findings and recommended pass with non-blocking notes; the note has since been addressed in this plan.
- Accepted risks:
  - Result/warning record fields become public through `weave.api`; mitigate
    with narrow fields and contract tests.
  - Scoped overlays are represented as overlay-family source artifacts with
    metadata; revisit if this becomes ambiguous or requires a schema revision.
- Revisit triggers:
  - Future users consistently miss trailing slash.
  - Future manifest/source compatibility requires a schema revision.
  - Future need to persist argv warnings outside helper results.
  - Future Hydra bridge needs a broader path/group grammar.

## Final Approval

- Approval status: implementation-plan quality gate passed; non-blocking
  note addressed
- Approved scope: Stage 24 phase execution planning may begin; phase
  implementation still requires a scope-complete phase execution plan.
- Accepted risks: see Implementation Plan Review.
- Deferred items: first-party `weave` CLI, Loom CLI integration, Hydra bridge,
  escaped dot-path grammar, advanced list patching, untrusted config sandboxing,
  runtime execution, pipeline planning, stores, and downstream operations.

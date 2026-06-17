# Roadmap Stage 24 Planning: Weave Argv Config Shorthand

## Metadata

- Roadmap stage: `v24`
- Source roadmap: `docs/roadmap.md`
- Previous version status: Stage 23 implementation plan records complete; all
  phases merged and `weave` exists as the standalone config package.
- Planning artifact status: confirmed; implementation-plan quality gate passed
- Current discussion stage: phase execution planning ready
- Stage gates:
  - Roadmap framing: confirmed by user on 2026-06-17
  - Intent discovery: completed from roadmap, feature docs, and user answers
  - Capability triage and candidate functional requirements: completed
  - Functionality agreement review: completed; no unresolved high-impact
    requirement questions remain
  - Functionality and behavior confirmation: completed from prior user behavior
    selections and 2026-06-17 framing confirmation
  - Context compaction/reset checkpoint: completed in this artifact
  - Design agreement review: completed; design-safety reviewer challenged and
    upheld the recorded recommendations with revisions
  - Design safety review: completed in this artifact on 2026-06-17
  - Examples and validation strategy: completed for planning purposes
  - Phase shaping: completed as provisional three-phase shape
  - Implementation readiness: implementation plan quality gate passed
  - Handoff: Phase 1 execution planning is the next workflow step
- Related implementation plan: `docs/roadmap/stage-24/implementation-plan.md`
  (quality gate passed; non-blocking note addressed)
- Related feature docs:
  - `docs/features/config.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/structure.md`
  - `docs/loom.md`
- Blockers:
  - Phase implementation must not start until the selected phase has a
    scope-complete phase execution plan.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | Defines `v24 - Weave argv config shorthand` after standalone package extraction. | Roadmap scope and sequencing | Stage 24 is a `weave` ergonomics implementation stage, not a Loom runtime or CLI-command stage. |
| `docs/features/config.md` | Drafts `compose_config_from_argv(...)`, `inspect_config_from_argv(...)`, value override syntax, trailing-slash overlay syntax, lookup rules, ordering, diagnostics, provenance, and deferrals. | Behavior source | Primary behavior specification for planning. |
| `docs/features/cli.md` | CLI is presentation over public APIs and must not duplicate config composition semantics. | Boundary guard | This stage provides a helper for project CLIs but does not add broad `loom.cli` behavior. |
| `docs/structure.md` | `weave` owns config composition and `cli` owns presentation over Python APIs. | Import and ownership boundaries | `weave` must not import Loom runtime or CLI modules. |
| `packages/weave/src/weave/api.py` | Current public API exposes `compose_config`, `inspect_config_composition`, `compose_config_with_catalog`, `instantiate`, and lazy top-level exports. | Current API shape | Stage 24 should add helper APIs without changing `compose_config(...)`. |
| `packages/weave/src/weave/compose.py` | Current composition order loads base/overlays, expands includes, handles include overrides, expands recipes, then applies ordinary overrides. | Data-flow planning | Stage 24 must insert argv scoped overlays before recipe expansion and value overrides after recipe expansion. |
| `packages/weave/src/weave/overrides.py` | Current value override parser handles strict update, `+` add, dot paths, typed values, JSON strings, arrays, objects, and structured errors. | Value override reuse | No-slash argv values should lower into this existing parser. |
| `packages/weave/src/weave/artifacts.py` and `packages/weave/src/weave/fingerprints.py` | Source artifact kinds are currently `base`, `overlay`, `include`, and `recipe`; artifact-safe fingerprints include source artifacts, include facts, and override facts. | Provenance and compatibility challenge | Scoped overlay sources should participate in source artifacts/fingerprints without inventing a new source kind unless a schema revision is explicitly justified. |
| `packages/weave/tests/unit/config/test_overrides.py` and `packages/weave/tests/integration/config/test_compose_overrides.py` | Existing coverage for override parsing/application and include-composition override behavior. | Test planning | Stage 24 should add package-local tests beside these behaviors. |
| `docs/roadmap/stage-23/implementation-plan.md` | Records completed standalone extraction and package-local config tests/examples. | Prerequisite status | Stage 24 can target `packages/weave` directly. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and architecture docs | `docs/roadmap.md`, `docs/structure.md`, `docs/loom.md` | Stage 24 is new and follows completed Stage 23. Ownership remains `weave` for config and CLI as wrapper/presentation. | No remaining design-safety gap. |
| Feature docs | `docs/features/config.md`, `docs/features/cli.md`, `docs/features/testing.md` | Feature doc records trailing-slash overlay behavior and helper shape. CLI doc keeps first-party CLI integration out of scope. | Warning and record shapes need implementation-plan precision, not user discussion. |
| Source and tests | `packages/weave/src/weave/api.py`, `compose.py`, `overrides.py`, `artifacts.py`, `fingerprints.py`, config tests | Existing composition has reusable pieces for value overrides and include/load/merge behavior; artifact/fingerprint contracts require explicit scoped-overlay representation. | Implementation plan must decide exact internal module/file split and contract field names. |
| Prior or adjacent plans | Stage 23 implementation plan, Stage 25 roadmap item | Stage 23 extraction is complete; downstream operations design is now Stage 25. | Stage 24 should not constrain Stage 25 or future Hydra bridge candidates. |

## Roadmap Extraction

Baseline roadmap outcome:

- Implement `weave` helpers that parse project CLI argv into config value
  overrides and trailing-slash scoped overlays while preserving existing
  `compose_config(...)` semantics.

Prerequisites:

- Stage 23 standalone `weave` package extraction is complete.
- Existing `weave` config composition, includes, recipes, target
  instantiation, redaction, provenance, manifests, source artifacts,
  fingerprints, and structured config errors are available in package-local
  modules and tests.

Primary feature docs:

- `config.md`
- `cli.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- No first-party `weave` CLI executable or console script.
- No broad `loom.cli` parser rewrite in this stage.
- No Hydra compatibility, defaults lists, config groups, escaped dot-path
  grammar, advanced list patching, or untrusted-config sandboxing.
- No behavior change for existing `compose_config(...)`, explicit overlay paths,
  or explicit override-string callers.

Future-roadmap touchpoints:

- Future project CLIs may use this helper without duplicating config merge,
  include, recipe, interpolation, provenance, or override logic.
- Future Loom-owned CLI phases may optionally adapt this helper, but Stage 24
  should not require Loom runtime or CLI modules to depend on config internals.
- Future Hydra bridge candidates remain separate; Stage 24 should keep argv
  shorthand narrow and not become a config-group/defaults implementation.
- Stage 25 downstream operations design should remain unaffected because this
  stage is config authoring/frontend behavior only.

Compatibility obligations:

- Preserve `compose_config(...)`, `inspect_config_composition(...)`, explicit
  `overlays=...`, and explicit `overrides=...` behavior.
- Preserve existing dot-path override value parsing and strict update/add
  behavior by reusing the current override parser.
- Keep `weave` import-safe and independent from Loom modules.
- Keep the new helper optional for callers; existing direct Python config APIs
  remain the primary stable composition surface.

## Stage Briefing

What this stage is:

- Stage 24 is a focused `weave` API ergonomics stage. It adds public helpers
  for project-specific CLIs that want to accept compact argv shorthand and then
  compose config through existing `weave` machinery.

Why this stage exists:

- Project CLIs often need to express both simple leaf value overrides and
  component overlays from a config directory. Without a helper, each project is
  likely to reimplement error-prone parsing, path lookup, and overlay lowering.
  Centralizing this in `weave` keeps config semantics with the config package.

Impacted or linked work:

- Directly impacts `packages/weave` public API, config composition internals,
  source/provenance records for scoped overlays, and package-local tests.
- Indirectly relates to `loom.cli`, but this stage should not add a new Loom
  command or make Loom CLI own config parsing semantics.

Likely public surfaces and durable artifacts:

- New public helper: `compose_config_from_argv(...)`.
- New inspection helper: `inspect_config_from_argv(...)`.
- New result/record types importable from `weave.api`.
- New warning records on the argv helper result.
- Composition manifests, source artifacts, provenance, and inspection stages
  should represent scoped overlays without requiring generated wrapper files.

Structure rationale:

- This should be a standalone post-extraction stage because `weave` now owns the
  full config implementation and package-local tests. It should be smaller and
  safer than bundling the helper with Loom CLI work or downstream operations
  design.

Visible assumptions, risks, and constraints:

- The helper should parse full argv shape: `<command> <base-config> ...`.
- No-slash tokens are value overrides, even when the RHS looks like YAML.
- Trailing slash on the LHS is required for overlays.
- Slash, not dot, separates nested overlay scope segments.
- Overlay lookup is scope directory first, then base config directory, with
  `.yaml` before `.yml` when no suffix is supplied.
- Absolute RHS values are exact file paths; no suffix probing.
- `~` expansion is not supported.
- Relative escapes are allowed and recorded normalized.
- Scoped overlays run before recipe expansion; value overrides run after recipe
  expansion.
- Existing `compose_config(...)` behavior must not change.
- Main risks are public API lock-in, confusing warnings/errors, provenance gaps,
  and accidentally broadening the config language into Hydra-like groups.

User clarification questions and resolved answers:

- User requested stronger overlay distinction with trailing `/`, for example
  `model/=...`; this supersedes the older ambiguous `model=...` overlay draft.
- User wanted no-slash tokens to remain value overrides so values can be set to
  path-like strings such as output directories or YAML filenames.
- User accepted warning records for no-slash mapping replacement or overlay-like
  mistakes, surfaced on the argv helper result rather than `ComposedConfig`.
- User selected slash-separated nested overlay paths, for example
  `model/pipeline/=pipeline_A`.
- User selected `+scope/=` as add-only overlay syntax for missing scopes.
- User selected recursive merge by default and honoring `_replace_: true`.
- User selected scope-directory then base-directory lookup, suffix probing for
  relative stems, exact absolute file paths, allowed `../`, and no `~`.
- User confirmed on 2026-06-17 that Stage 24 targets project-specific CLI
  authors using `weave` and should optimize for unambiguous config semantics,
  provenance, and structured diagnostics over maximum shorthand convenience.

## User Intent

Target audience:

- Authors of project-specific CLIs or scripts that want to delegate config
  composition shorthand to `weave`.

User-visible outcome:

- Callers can pass argv fragments such as
  `<command> configs/base.yaml model/=model_B data.keyC=newValueC` and receive a
  composed config plus structured records, warnings, and diagnostics.

Success criteria:

- Value overrides, scoped overlays, lookup, ordering, warnings, and errors
  behave as documented in `docs/features/config.md`.
- Existing direct Python composition behavior remains unchanged.
- Diagnostics are usable by project CLIs without forcing process exits or
  argparse ownership into `weave`.

Non-goals:

- No first-party `weave` executable, no broad `loom.cli` rewrite, no Hydra
  bridge, no untrusted-config sandbox, and no new dot-path grammar.

Constraints:

- Keep `weave` independent from Loom.
- Keep helpers domain-neutral.
- Treat authored configs as trusted project code.

## Workflow Stage Readback

Roadmap framing locked decisions:

- Stage scope is `weave` argv helper implementation after Stage 23.
- Target audience is project-specific CLI authors using `weave`.
- Stage priority is unambiguous config semantics, provenance, and diagnostics
  over maximum shorthand convenience.
- No first-party `weave` executable or new Loom CLI command is in scope.

Intent discovery locked decisions:

- The user wants a reusable implementation roadmap item, not immediate direct
  edits in the control checkout.
- The stage should convert previously agreed CLI shorthand behavior into an
  implementation-ready roadmap stage.

Capability triage and candidate-functional-requirement readback:

- Include full argv helper, no-slash value overrides, trailing-slash scoped
  overlays, lookup, diagnostics, warnings, inspection, and audit records.
- Defer first-party CLI, Loom CLI integration, Hydra-like features, escaped dot
  grammar, list patching, and untrusted sandboxing.

Functionality-agreement readback:

- The requirement queue is resolved from prior user answers, feature docs, and
  repository boundaries. No remaining high-impact requirement question needs
  user input before design safety.

Functionality and behavior confirmation readback:

- Behavior baseline is locked for design safety: no-slash tokens are value
  overrides; trailing-slash LHS tokens are overlays; slash paths denote nested
  overlay scopes; scoped overlays apply before recipes; value overrides apply
  after recipes.

Design-agreement follow-up:

- Public API, warning placement, provenance, composition order, and error
  taxonomy were challenged during design safety. Recommendations were upheld
  with scoped-overlay provenance/fingerprint revisions.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | `weave` argv helper stage; project-specific CLI authors; no first-party executable or Loom CLI command. | Favor clear semantics, provenance, diagnostics. | None. | Completed. |
| Intent discovery | Reusable helper for project CLIs; optional API, not mandatory command behavior. | Keep behavior domain-neutral and package-local. | None. | Completed. |
| Capability triage and candidate functional requirements | Include argv helper, value overrides, overlays, lookup, warnings, inspection. | Reuse existing override parser and composition machinery. | None. | Completed. |
| Functionality agreement review | FRQ-1 through FRQ-3 resolved. | Feature-doc behavior is binding for design pass. | None. | Completed. |
| Functionality and behavior confirmation | Behavior baseline locked for design safety. | Structured API errors; result warnings. | None. | Completed. |
| Context compaction/reset checkpoint | This artifact is the checkpoint and resume source. | Reload workflow and feature docs before later passes. | None. | Completed. |
| Design agreement review | DAQ-1 through DAQ-5 challenged and classified. | Keep helper narrow and config-owned. | None. | Completed. |
| Design safety review | Completed 2026-06-17. | Upheld Stage 24 as `weave`-owned argv adapter work with provenance/fingerprint revisions. | None. | Completed. |
| Examples and validation strategy | Scenario and suite obligations recorded, including scoped-overlay provenance/fingerprint tests. | Package-local tests first. | None. | Completed. |
| Phase shaping | Three-phase shape carried into the implementation plan. | Split provenance if it requires a schema-versioned source artifact or manifest change. | Phase execution plans must preserve reviewability. | Phase 1 execution planning. |
| Implementation readiness | Implementation-plan quality gate passed; non-blocking note addressed. | Phase implementation still waits for a scope-complete phase execution plan. | None for phase planning. | Phase 1 execution planning. |
| Handoff | Final planning confirmation received on 2026-06-17 and implementation-plan quality gate passed. | No phase implementation worktree yet. | None for phase planning. | Phase 1 execution planning. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Full argv parsing with caller-provided command choices | include | Roadmap and feature doc name full argv helper. | Scope is Python API, not console script. |
| No-slash dot/root value overrides | include | User explicitly requested root and dotted value override behavior. | Reuse existing override parser. |
| Trailing-slash scoped overlays | include | User requested clearer overlay marker. | Slash path grammar is part of confirmed behavior. |
| Scoped overlay source lookup | include | Core value of helper. | Scope-dir/base-dir order recorded. |
| Warning records | include | User selected result-level warnings. | Keep warnings outside normal `ComposedConfig`. |
| Inspection helper | include | User selected inspection companion. | Public export shape is a recorded recommendation. |
| First-party `weave` CLI executable | defer | Roadmap defers console script. | Keep out of scope unless a future stage adds it. |
| Broad `loom.cli` rewrite | out of scope | Would violate CLI/config boundary and expand stage. | Later Loom-owned phase can adapt helper. |
| Hydra/defaults/config-group compatibility | out of scope | Explicitly deferred by feature docs and roadmap. | Keep helper narrow. |
| Escaped dot-path grammar | out of scope | Current override parser intentionally lacks escaped-dot support. | Revisit only in future path grammar stage. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Confirm target audience and optimization priority. | none | 1 | Project-specific CLI authors; optimize for unambiguous config semantics and provenance. | Sets product framing and prevents drift into first-party CLI executable work. | User owns product priority and confirmed on 2026-06-17. | confirmed |
| FRQ-2 | Confirm included capabilities and explicit deferrals. | FRQ-1 | 2 | Include full argv helper, inspection helper, value overrides, trailing-slash overlays, warnings, structured errors; defer first-party CLI, Loom CLI rewrite, Hydra features. | Defines what Stage 24 must implement and what it must not implement. | Prior user behavior selections plus repo boundaries resolve this. | confirmed |
| FRQ-3 | Confirm failure/warning expectations as user-visible behavior. | FRQ-2 | 3 | Structured errors for malformed/missing overlays; result-level warnings for likely overlay mistakes. | Drives public API and tests. | User selected warning surface; feature docs now record behavior. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Full argv helper | none | Parse `<command> <base-config> ...` and compose config. | Gives project CLIs a reusable frontend. | `weave` API only. | Caller receives command, config, records, warnings, unparsed args when allowed. | Validates command against caller choices. | Project CLI delegation. | Unit/API tests. | confirmed |
| FR-2 | Value override shorthand | FR-1 | Reuse existing dot-path/root override parser for no-slash tokens. | Avoids duplicate parser semantics. | No new path grammar. | `data.key=x` and `key=x` are value overrides. | Lowers to existing parsed overrides. | Leaf/root config changes. | Existing parser regressions plus argv tests. | confirmed |
| FR-3 | Scoped overlay shorthand | FR-1 | Require trailing slash and slash-separated scope paths. | Unambiguous overlay syntax. | Config mapping overlays only. | `model/=model_B`, `model/pipeline/=pipeline_A`. | Loads mapping and merges at scope. | Component swaps from config directory. | Integration tests with config tree. | confirmed |
| FR-4 | Overlay lookup and merge | FR-3 | Scope-dir then base-dir lookup, suffix probing, exact absolute paths, recursive merge, `_replace_`. | Predictable shorthand over config file layout. | Local YAML files only. | Missing files fail with attempted candidates. | Uses existing load/merge/source behavior where possible. | Reviewable overlays. | Unit/integration tests. | confirmed |
| FR-5 | Diagnostics and warnings | FR-1 | Structured errors and result warnings. | Keeps CLI users debuggable without process exits. | Config-owned errors, result-level warnings. | Clear errors and non-fatal warnings. | Context includes scope, RHS, candidates. | Safer UX. | Contract/error tests. | confirmed |
| FR-6 | Inspection and artifact records | FR-3 | Inspection helper and provenance/source records for scoped overlays. | Maintains auditability. | No generated wrapper files. | Inspection exposes stages/records. | Manifest/source metadata identify actual source and target scope. | Debugging and reproducibility. | Inspection/provenance tests. | confirmed |

## Behavior Baseline

Included functionality:

- Full argv compose helper and inspection helper.
- No-slash value overrides through existing override parser.
- Trailing-slash scoped overlays with slash path scopes.
- Scoped overlay lookup, merge, structured errors, warnings, and audit records.

User-visible behavior:

- Project CLI code can call one helper and avoid duplicating config semantics.
- The helper returns structured records rather than printing or exiting.
- Values that look like paths or YAML filenames remain value overrides unless
  the LHS uses trailing slash overlay syntax.

Default behavior:

- `allow_unparsed=False` means unparsed command args fail.
- No-slash tokens are values; trailing slash is required for overlays.
- Overlay RHS stem lookup probes `.yaml` before `.yml` for relative stems.
- Absolute overlay RHS uses the exact file path and does not do suffix probing.
- `~` is not expanded.
- Relative escapes such as `../` are allowed and recorded normalized.
- Scoped overlays apply before recipe expansion.
- Value overrides apply after recipe expansion.

Failure behavior and diagnostics:

- Malformed argv, unknown commands, missing base config path, unsupported root
  overlay, missing overlay file, non-mapping overlay source, invalid target
  shape, and unparsed args fail with config-owned structured errors.
- Missing overlay errors report attempted candidates.
- Result-level warnings cover likely overlay mistakes such as replacing an
  existing mapping through no-slash value syntax when the RHS looks overlay-like.

Explicit deferrals:

- First-party `weave` CLI executable.
- Broad Loom CLI integration.
- Hydra/config-group/defaults behavior.
- Escaped dot-path grammar.
- Advanced list patching.
- Untrusted config sandboxing.

Out-of-scope behavior:

- Runtime execution, pipeline planning, run-store writes, first-party CLI
  presentation, untrusted config sandboxing, and domain-specific config
  semantics.

Context compaction/reset checkpoint:

- Checkpoint status: completed
- Notes path: `docs/roadmap/stage-24/planning.md`
- Resume instruction: reload this planning artifact,
  `.codex/workflows/roadmap-stage-planning.md`, the design-safety prompt, and
  the Stage 24 feature docs before continuing.
- Functionality and behavior reopened after checkpoint: none

## Proposed Implementation Shape

Likely modules or packages:

- `packages/weave/src/weave/api.py`
- A new internal argv/shorthand module under `packages/weave/src/weave/`
- Existing `compose.py`, `load.py`, `merge.py`, `overrides.py`,
  `source_maps.py`, `artifacts.py`, and `provenance.py` as needed.

Likely public classes, functions, or protocols:

- `compose_config_from_argv(...)`
- `inspect_config_from_argv(...)`
- Result, scoped overlay record, value override record, warning record, and
  structured error types or context codes.

Likely internal helpers:

- Argv token classifier.
- Overlay LHS parser for trailing slash and slash path scopes.
- Overlay RHS candidate resolver.
- Scoped overlay lowering/merge helper.
- Warning builder.

Data flow:

- Parse command/base path/tokens.
- Classify value override tokens and scoped overlay tokens.
- Resolve scoped overlay sources relative to base config and scope path.
- Load base and explicit composition inputs.
- Apply scoped overlays before recipe expansion.
- Expand recipes.
- Apply value overrides after recipes.
- Produce composed config/inspection plus argv result records.

Dependency direction:

- `weave` owns all helper behavior and imports no Loom modules.
- Loom CLI may later call the helper but is not part of this stage.

Extension points and flexibility boundaries:

- Caller-provided command choices are the command extension point.
- `allow_unparsed=True` lets project CLIs retain command-specific parsing.
- Overlay behavior remains local YAML only; no plugin/global resolver/search path.

Generic interface, adapter, or protocol shape:

- The helper is a small adapter from argv tokens to existing config composition,
  not a broad CLI framework.
- No backend, executor, store, scheduler, or operation protocol is introduced.

Future-roadmap impact:

- Should reduce duplicate project CLI parsing while preserving future room for
  Loom CLI or Hydra bridge work as separate stages.
- Should not constrain Stage 25 because it does not alter execution, stores,
  operation routing, or downstream behavior.

Compatibility constraints:

- Do not change `compose_config(...)` or existing config artifacts for callers
  that do not use the argv helper.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Public API/export surface for helper and result records. | FR-1 | 1 | recorded recommendation | Export `compose_config_from_argv` top-level; expose inspection helper and record types through `weave.api`; only top-level export additional records if implementation-plan review finds a discoverability reason. | Avoids over-expanding top-level API while making the primary helper discoverable. | Repo evidence supports this; no user input needed. | reviewed and upheld |
| DAQ-2 | Warning schema and placement. | FR-5 | 2 | recorded recommendation | Return argv warning records on helper result only, not `ComposedConfig`. | Keeps argv-specific UX out of normal composition artifacts. | User already selected this direction. | reviewed and upheld |
| DAQ-3 | Scoped overlay provenance representation. | FR-6 | 3 | recorded recommendation | Record actual source path, attempted candidates when relevant, scope path, add/update mode, resolved insertion stage, and artifact-safe fingerprint participation without generated wrapper files. | Affects manifest/source artifact compatibility and audit shape. | Design-safety review revised this recommendation to require source artifact metadata, value authorship, and artifact-safe fingerprint facts while avoiding a new source kind by default. | reviewed and revised |
| DAQ-4 | Composition insertion point. | FR-3 | 4 | recorded recommendation | Apply scoped overlays before recipes and value overrides after recipes. | Aligns with feature-doc behavior and current composition flow. | User selected recipe ordering. | reviewed and upheld |
| DAQ-5 | Error taxonomy. | FR-5 | 5 | recorded recommendation | Use config-owned structured errors with context codes rather than argparse exits. | Keeps helper API-friendly and testable. | Repo error patterns support recommendation. | reviewed and upheld |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DD-1 | Overlay marker | Trailing slash on LHS only. | User requested clearer distinction and gave `model/=...`. | Infer by RHS; explicit CLI flags. | Avoids RHS inference ambiguity while keeping shorthand compact. | Low; parser decision is narrow and testable. | Keeps future syntaxes possible because no-slash remains value-only. | Avoids Hydra-like inference creep. | Public argv grammar only. | Document examples and malformed-token errors. | Revisit if users consistently miss the trailing slash. | confirmed |
| DD-2 | Nested overlay path grammar | Slash-separated scopes. | User selected `model/pipeline/=pipeline_A`. | Dot path overlays; accept both. | Keeps overlay path grammar distinct from dot-path value overrides. | Low to medium; one grammar to validate. | Leaves dot grammar stable for values and can coexist with future explicit adapters. | Does not constrain downstream operation stages. | Public argv grammar only. | Unit tests for nested paths and invalid segments. | Revisit if future standard path grammar demands convergence. | confirmed |
| DD-3 | No-slash path-like RHS | Always value override. | User wanted `output_dir=...` and YAML-like strings to remain values. | YAML lookup inference. | Supports setting path-like values without ambiguity. | Low; delegates to existing override parser. | Preserves extension room for overlay-only markers. | Avoids config-group inference behavior. | Public argv grammar only. | Tests for path-like strings and warning records. | Revisit if warnings show frequent accidental value overrides. | confirmed |
| DD-4 | Warning placement | Store argv warnings on helper result, not `ComposedConfig`. | User selected result-level warnings. | Mutate `ComposedConfig`; print warnings; raise for all suspicious cases. | Keeps normal composition artifacts free from argv-specific UX. | Low; warning records are limited to new helper API. | Future CLIs can decide how to display warnings. | Does not affect existing config composition. | New result record shape. | Contract tests for warning shape and no-warning normal cases. | Revisit if warnings need persistence in run artifacts. | recorded recommendation |
| DD-5 | Scoped overlay provenance | Record actual source, target scope, source artifact metadata, value authorship, and artifact-safe fingerprint facts directly. | User emphasized provenance and clear errors. | Generate temporary wrapper overlay files; hide scoped overlay in normal overlay list. | Direct records are clearer and avoid synthetic file lifecycle concerns. | Medium; needs careful integration with source/provenance records. | Leaves future manifest formats able to distinguish explicit overlays from argv scoped overlays. | Should not constrain Stage 25; design-safety review upheld with provenance/fingerprint revisions. | New composition/inspection record shape. | Integration tests for inspection, source records, value authorship, and fingerprint payloads. | Revisit if source artifact compatibility needs a broader manifest change. | recorded recommendation |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Top-level API expansion could create public lock-in. | FR-1, FR-6 | Upheld: top-level export only the primary helper by default; keep inspection helper and record types in `weave.api` unless implementation-plan review records a discoverability reason. | upheld |
| DAQ-2 | recorded recommendation | Warnings might need durable provenance later. | FR-5 | Upheld: keep warnings on the argv helper result; do not mutate `ComposedConfig` or persisted run artifacts in this stage. | upheld |
| DAQ-3 | recorded recommendation | Scoped overlay records touch manifest/source artifacts and fingerprint compatibility. | FR-3, FR-6 | Upheld with revision: require source artifact metadata, value authorship, and artifact-safe fingerprint facts for scoped overlays; avoid a new source artifact kind unless implementation planning explicitly justifies a schema revision. | revised recommendation |
| DAQ-4 | recorded recommendation | Recipe ordering could surprise users if overlays depend on recipe expansion. | FR-3, FR-4 | Upheld: ordering is traceable to confirmed behavior and current compose flow; validate with recipe interaction tests. | upheld |
| DAQ-5 | recorded recommendation | Error codes must not leak CLI-specific terminology into core config too broadly. | FR-5 | Upheld: use config-owned structured errors with argv-specific codes scoped to the new helper module. | upheld |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| Public API export breadth should stay narrow. | DAQ-1, FR-1, FR-6 | Top-level record exports would lock in more public names than the roadmap requires. | Result and record types remain reusable through `weave.api`; top-level discoverability is limited to the main compose helper unless review records a reason. | Keep top-level export narrow; implementation plan must list every new public symbol and contract-test imports. | upheld |
| Argv warnings should remain helper-local. | DAQ-2, FR-5 | Persisting suspicious-argv warnings in normal composition artifacts would couple CLI ergonomics to direct Python composition and future run records. | Project CLIs can display, ignore, or escalate warnings from the wrapper result without changing `ComposedConfig`. | Keep warning records on argv helper result only; revisit only if a future persisted argv audit artifact is explicitly requested. | upheld |
| Scoped overlay provenance must not imply a new artifact source kind by default. | DAQ-3, DD-5, FR-6 | Current `SourceArtifactRecord.kind` and raw snapshot references accept only `base`, `overlay`, `include`, and `recipe`; adding `scoped_overlay` would be a persisted contract/schema decision. | A scoped overlay can be represented as an overlay source with metadata for `composition_input`, `scope_path`, authored token, add/update mode, candidate list, and insertion stage. | Treat scoped overlays as overlay-family source artifacts with explicit metadata and fingerprint facts unless the implementation plan records a schema-versioned kind change. | revised recommendation |
| Scoped overlay values must participate in authorship and artifact-safe fingerprints. | DAQ-3, DAQ-4, FR-6 | If the merge changes config values without value authorship/fingerprint facts, rebuild and resume comparisons could under-report why a config changed. | Existing provenance/fingerprint machinery can be extended with scoped overlay facts without introducing executor, store, or scheduler protocols. | Implementation plan must require tests proving scoped overlay source artifacts, value authorship, manifest metadata, and artifact-safe fingerprint payloads change when scoped overlay inputs change. | revised recommendation |
| Composition insertion point is compatible but needs stage records. | DAQ-4, FR-3, FR-4 | Hidden insertion would make inspection brittle and future config debugging harder. | A dedicated inspection stage or explicit stage payload preserves reusable inspection without exposing CLI internals. | Implementation plan must name the inspection stage/payload for scoped overlays and prove existing `inspect_config_composition(...)` stage contracts remain unchanged for non-argv callers. | upheld |
| Error taxonomy can remain config-owned. | DAQ-5, FR-5 | `argparse` exits or Loom CLI error roots would make helper reuse harder and violate package boundaries. | Config-owned structured errors with helper-scoped context codes are generic enough for project CLIs. | Keep errors in `weave`; include token, scope, RHS, target shape, and candidate-path context in tests. | upheld |

Gate result:

- Status: passed for implementation-plan drafting after final planning confirmation
- Reviewer: `loom_design_safety_reviewer` design-safety pass completed on 2026-06-17
- Blockers: no design-safety blockers remain; final planning confirmation was received and the implementation-plan quality gate has now passed; its non-blocking note has been addressed.
- Recorded recommendations: DAQ-1, DAQ-2, DAQ-4, and DAQ-5 upheld; DAQ-3 upheld with revisions for source artifact metadata, value authorship, and artifact-safe fingerprint participation.
- Future-roadmap impact summary: Stage 24 remains compatible with Stage 25 because it adds only optional `weave` config frontend helpers and does not alter execution, stores, scheduling, queues, resources, or downstream operations. It also keeps future Hydra bridge candidates separate by avoiding defaults lists, global config groups, or RHS inference.
- Generic interface, adapter, and protocol assessment: the helper remains an argv-to-config adapter only. It introduces no backend, executor, store, scheduler, operation, event, notification, or pipeline protocol. Caller-provided command choices and `allow_unparsed` are enough extension surface for this stage.
- Planning revisions required: implementation planning must preserve the scoped-overlay provenance/fingerprint obligations recorded above and must not invent a new source artifact kind without an explicit schema-versioned compatibility decision.
- Accepted risks: warning record shape and detailed result-record fields become new public API once exported through `weave.api`; mitigate with narrow fields and contract tests.
- Revisit triggers: future users consistently miss trailing slash, future manifest/source compatibility requires a schema revision, future need to persist argv warnings outside helper results, or a future Hydra bridge needs a broader path/group grammar.

## Practical Design Notes

Public Python API surface:

- Add `compose_config_from_argv(...)` as the discoverable helper.
- Add `inspect_config_from_argv(...)` as the audit/debug companion.
- Keep detailed records importable through `weave.api`; expand top-level exports
  only if implementation-plan review finds that important for ergonomics.

CLI surface:

- No first-party CLI executable is added.
- `weave` should not own printing, process exits, shell completion, argparse
  formatting, or command-specific help in this stage.

Persisted records and file layout:

- Prefer direct source/provenance records for argv scoped overlays over
  generated wrapper files. Represent them as overlay-family source artifacts with
  scoped-overlay metadata unless implementation planning explicitly accepts a
  schema-versioned new source kind.
- Missing overlay diagnostics should include attempted candidate paths.

Import boundaries and dependencies:

- `weave` must not import Loom runtime or CLI modules.
- No new heavyweight runtime dependency is expected.

Failure modes and diagnostics:

- Use config-owned structured errors with context, not `argparse` exits.
- Include token, scope, RHS, candidate paths, and target-shape context where
  applicable.

Extension points and flexibility boundaries:

- Caller-provided command choices and `allow_unparsed` are sufficient extension
  points for this stage.
- Do not add global search paths, plugin resolvers, or config groups.

Generic interfaces, adapters, and protocols:

- The helper is an adapter, not a protocol for execution or operations.
- No backend, executor, store, scheduler, or integration contract is introduced.

## Examples And Validation Strategy

Example scenarios to include in planning:

- `data.keyC=newValueC` updates a leaf value.
- `keyD=newValueD` updates a root value.
- `output_dir=results/model_B.yaml` remains a value string.
- `data/=data_A` resolves `configs/data/data_A.yaml` before base-dir fallback.
- `model/=model_B` resolves `configs/model/model_B.yaml`.
- `model/pipeline/=pipeline_A` resolves
  `configs/model/pipeline/pipeline_A.yaml`.
- Absolute overlay RHS uses exact file path.
- Missing overlay RHS reports attempted paths.
- `+runtime/=local` creates a missing scope.
- `/=root` is rejected.

Validation ideas:

- Package/API import tests for new exports.
- Unit tests for argv token parsing, classification, candidate resolution,
  warning creation, and structured errors.
- Integration tests for composition order, recipe interaction, overlay merge,
  `_replace_`, source/provenance records, and inspection stages.
- Contract tests for result/warning/error plain-data shape if those records are
  public or serialized.
- Contract/integration tests proving scoped overlays appear in source artifacts,
  value authorship, manifest metadata, raw snapshot references where applicable,
  and artifact-safe fingerprint payloads.
- No root Loom CLI/e2e tests unless a later Loom adapter phase uses the helper.

Suite obligations for the later implementation plan:

- Unit: parser/classifier/resolver/error/warning helpers.
- Integration: composed config behavior across representative config trees.
- Contract/API: imports, stable record fields, and scoped-overlay artifact/fingerprint fields.
- Docs/examples: feature doc examples and any API docstrings.
- PR gate: `make validate-pr` and `make test-summary` before PR preparation.

## Phase Shaping

Provisional phase shape:

1. Public argv records and parser classification.
2. Scoped overlay resolution/lowering and composition ordering.
3. Inspection, provenance/source records, warnings/errors, docs, and final
   validation.

Phase-shaping rationale:

- Parser and record shape are separable from composition changes.
- Scoped overlay composition is the riskiest behavioral change and deserves its
  own implementation focus.
- Inspection/provenance/warnings and docs are cross-cutting enough to finish as
  a focused validation and auditability phase.

Phase-shaping risks:

- If scoped overlay provenance requires a new persisted source artifact kind or
  manifest schema version, split records into a separate phase or record the
  compatibility decision in the implementation plan before implementation.
- If design safety finds the implementation is smaller and cohesive, the
  implementation plan may collapse phases while preserving reviewability and
  suite obligations.

## Implementation Readiness

Status: implementation plan drafted; quality gate passed and non-blocking note addressed.

Readiness blockers:

- None for phase execution planning.
- Phase implementation remains blocked until the selected phase has a
  scope-complete phase execution plan.

No longer blocked by:

- Roadmap framing.
- Intent discovery.
- Capability triage.
- Functionality agreement.
- Behavior baseline.
- Design agreement queue.
- Design-safety review.
- Examples and validation strategy.
- Provisional phase shaping.

Required next steps:

1. Select Phase 1 and create its scope-complete phase execution plan through the phase workflow.
2. Carry forward the implementation-plan confirmation review note about the Phase 2 / Phase 3 inspection export boundary.
3. Do not begin implementation until the selected phase execution plan exists.

## Open Questions

| ID | Question | Why it matters | Recommended answer | Status |
| --- | --- | --- | --- | --- |
| OQ-1 | Is the target audience project-specific CLI authors using `weave`, not end users of a first-party `weave` CLI? | Determines public surface and docs tone. | Yes. | confirmed 2026-06-17 |
| OQ-2 | Should the stage optimize for unambiguous config semantics/provenance over maximum shorthand convenience? | Confirms warning/error strictness and deferrals. | Yes. | confirmed 2026-06-17 |
| OQ-3 | Should implementation planning preserve the draft three-phase shape or collapse if design safety finds the diff small? | Affects phase plan size. | Let design safety and implementation-plan review decide. | recorded recommendation |
| OQ-4 | May this session run the required `loom_design_safety_reviewer` pass to satisfy the repository workflow? | Required by repo workflow before implementation-plan drafting. | Yes; authorized by the 2026-06-17 user request. | confirmed 2026-06-17 |

## Handoff

Current handoff state:

- Planning artifact is updated at `docs/roadmap/stage-24/planning.md`.
- Design-safety review is complete and recorded in this artifact.
- Final planning confirmation was given by the user on 2026-06-17.
- Implementation plan drafted at `docs/roadmap/stage-24/implementation-plan.md`; quality gate passed and non-blocking note addressed.
- Next action is Phase 1 execution planning; implementation still waits for the selected phase execution plan.

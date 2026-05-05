# Roadmap v1 Planning Notes: Rebuildable Config Composition

## Metadata

- Roadmap version: v1
- Source roadmap: `docs/implementation-plans/implementation-roadmap.md`
- Previous version status: v0-post hardening is recorded as merged in
  `docs/implementation-plans/implementation-plan-v0-post.md`.
- Planning notes status: draft
- Current discussion stage: Practical design refinement - config decision review
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Feature brainstorming: confirmed
  - Practical design refinement: open
  - Phase shaping: pending
  - Handoff: pending
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v0-post.md`
  - `docs/implementation-plans/implementation-plan-v1.md`
  - `docs/implementation-plans/implementation-plan-v2.md`
- Related feature docs:
  - `docs/features/config.md`
  - `docs/features/serialization.md`
  - `docs/features/io.md`
  - `docs/features/fingerprints.md`
  - `docs/features/provenance.md`
  - `docs/features/errors.md`
  - `docs/features/testing.md`
- Blockers:
  - No confirmed product blocker yet.
  - `docs/implementation-plans/implementation-plan-v1.md` still has plan
    quality gate status `pending`.

## Roadmap Extraction

Baseline roadmap outcome:

- Add explicit recursive config composition so large project configs can be
  factored into nested files, whole components can be swapped for experiments,
  repeated stage configs can reuse templates, and runs can preserve enough
  authored inputs to rebuild the composition process.
- Discussion narrowed v1 to nested includes, safe swaps, strict overrides, and
  rebuildable source artifacts. `_copy_` template reuse is deferred out of v1.
- Keep the feature narrower than Hydra: no defaults lists, launchers, sweepers,
  global search paths, arbitrary YAML expression language, custom interpolation
  resolvers, automatic schema inference, untrusted-config sandboxing, or
  plugin-discovered composition extensions.

Prerequisites:

- v0 config composition, merge, provenance, redaction, fingerprints, recipe
  expansion, and v0-post hardening closeout are expected to be complete.
- v0-post is recorded as merged, and its follow-up notes say v1 may proceed on
  the corrected v0-post contract set.

Primary feature docs:

- `config.md`
- `serialization.md`
- `io.md`
- `fingerprints.md`
- `provenance.md`
- `errors.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Hydra-compatible defaults lists, config groups, launchers, sweepers, advanced
  list patching, broad registry aliases, arbitrary YAML expression languages,
  automatic target schema inference, YAML `_schema_` directives, untrusted
  config sandboxing, automatic plugin-discovered composition extensions, custom
  include resolvers, custom OmegaConf-style interpolation resolvers, remote
  include sources, and public CLI behavior.

Compatibility obligations:

- Preserve the v0 `compose_config` public entrypoint.
- Integrate composition behavior into `compose_config` so v2 CLI and v10 sweeps
  get the behavior through the same API.
- Keep authored configs trusted project code.
- Keep `loom` domain-neutral and avoid importing project code from runtime
  composition helpers.
- Preserve v0 merge, interpolation, recipe, redaction, provenance, and
  fingerprint behavior except where v1 explicitly adds `_replace_` and
  strict/add override semantics.

## User Intent

Target audience:

- Primary: config authors using the Python API.
- Secondary: internal maintainers and reviewers.
- Tertiary: future CLI users.

User-visible outcome:

- Config authors can split large configs into nested component files.
- Config authors can safely swap model, dataset, and stage components without
  stale or accidental lower-precedence values surviving silently.
- Old run config inputs can be rebuilt from saved composition artifacts where
  possible.
- `_copy_`-based stage/component reuse is excluded from v1.

Success criteria:

- The author must explicitly make composition decisions that could change
  meaning.
- Ambiguous, implicit, silent, or ordinary-looking behavior should fail during
  loading/composition instead of guessing.
- Resolution and composition are strict enough to surface potentially unintended
  design decisions throughout the process.
- Error messages are informative enough to identify the config path, authored
  source, resolved target where relevant, and the explicit action required.
- The plan explicitly maps ambiguity points in the composition decision tree so
  v1 can fail closed now and consider softening behavior later.

Non-goals:

- Permissive compatibility shortcuts that silently preserve or create values.
- Implicit/global lookup behavior that hides where a component came from.
- Ordinary overrides that create paths without an explicit add marker.
- Convenience syntax that weakens provenance, rebuildability, or future-roadmap
  compatibility.
- `_copy_` subtree reuse in v1.

Constraints:

- Prioritize correctness, rebuildability, and future-roadmap compatibility over
  shortcut ergonomics or implementation speed.
- Prefer explicit authoring and load-time failures for now. More ergonomic
  shortcuts can be revisited later only after the strict model is reliable.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | V1 prioritizes correctness/rebuildability and future-roadmap compatibility. Primary audience is Python API config authors, then maintainers/reviewers, then future CLI users. | Authoring ergonomics can improve only where it does not weaken explicitness, provenance, or future compatibility. | None. | Intent discovery: workflows, success criteria, non-goals, constraints, and operational realities. |
| Intent discovery | Priority workflows are splitting large configs into nested components, safe model/dataset/stage swaps, and rebuilding old run config inputs from saved artifacts where possible. `_copy_` is useful but lower priority. V1 should aggressively surface unintended design decisions with strict resolution/composition and informative errors. | Prefer explicit authoring and load-time failures; revisit ergonomics later. | None. | Feature brainstorming: classify the planned capabilities into include, defer, maybe, and out of scope. |
| Feature brainstorming | Include `_include_`, `_replace_`, strict/add overrides, composition artifacts, local/file URI resolution, strict source-aware errors, and an explicit ambiguity decision tree. Exclude `_copy_` from v1. | Fail closed on uncertain include resolution, extension probing ambiguity, path normalization surprises, duplicate candidate files, and CLI-authored bare includes without a clear root. | None. | Practical design refinement: map the strict decision tree, API behavior, persisted artifacts, boundaries, and accepted debt. |
| Practical design refinement | Accepted strict include defaults: explicit paths require exact filenames; bare names append exactly `.yaml`; no `.yml` or extension probing; paths that normalize outside the including config tree fail unless explicitly authored as relative/absolute path or `file://`; CLI-authored bare includes fail unless root config path and destination config path provide one clear base. Composition manifest and source artifact schemas should be designed early as stable model scaffolding. The current broad integration phase should be split. | Ambiguity decision tree belongs in a plan-level section plus phase-specific acceptance criteria. | Config decision review queue is open. | Review each config design decision and record hardening/refactor guidance. |
| Phase shaping |  | Replace the earlier broad Phase 4 and six-phase sketch with an expanded PR-sized strategy that separates contracts, strict primitives, includes, user composition, resolver security, recipes, validation, instantiation, compose orchestration, provenance/manifest/redaction, fingerprints/resume, source artifacts, and hardening. | Does the expanded phase split create reviewable PR-sized units without excessive process overhead? | Confirm phase breakdown for implementation-plan refinement after design decision review. |
| Handoff |  |  |  |  |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| `_include_` inside mappings | default include | Core v1 roadmap capability. | Bare names resolve by including-file directory plus mapping key path. |
| `_replace_` whole-section replacement | default include | Prevents stale lower-precedence keys during component swaps. | Required when an include swaps over existing mapping content. |
| `_copy_` subtree reuse | out of scope for v1 | Useful, but lower priority than nested includes, safe swaps, strictness, and rebuildability. | Revisit after the strict include/replacement model is reliable. |
| Strict update overrides and explicit `+` add overrides | default include | Catches typos while preserving intentional additions and CLI replacement markers. | User composition overrides can replace include choices before recipes; ordinary value overrides target the expanded concrete config. |
| Composition manifest and source artifacts | default include | Makes authored composition inputs comparable and, when raw source snapshots are explicitly enabled, rebuildable after project files change. | Persistence remains runner/run-store owned; raw source bytes are opt-in because authored YAML/overrides may contain secrets. |
| Local path and `file://` include resolution | default include | Needed for deterministic local composition. | Other URI schemes deferred. |
| Explicit ambiguity decision tree | include | Every potentially unintended design decision should be visible and reviewed. | The implementation plan should enumerate fail-closed cases and exact author remedies. |
| Custom include resolvers or plugin extensions | default defer | Later v11-v13 work may introduce extensions with clearer contracts. | Do not define extension API in v1. |
| Hydra defaults lists, launchers, sweepers, global search paths | default out of scope | Keeps v1 narrow and domain-neutral. | Sweeps build later on `compose_config`. |

## Design Decisions

| Decision | Selected approach | Alternatives rejected | Rationale | Revisit trigger |
| --- | --- | --- | --- | --- |
| Planning priority | Prioritize correctness/rebuildability and future-roadmap compatibility. | Optimizing first for shorter syntax, permissive merging, or fastest implementation. | V1 becomes a foundation for CLI, sweeps, plugins, and remote config behavior, so ambiguous composition and incomplete provenance would create lasting debt. | Revisit only if the resulting authoring experience blocks ordinary Python API config authors after docs and examples exist. |
| Target audience | Primary audience is config authors using the Python API; maintainers/reviewers are secondary; future CLI users are tertiary. | Designing first for future CLI syntax. | V1 has no public CLI behavior, but must leave v2 CLI a clean path through `compose_config`. | Revisit when v2 CLI planning begins. |
| Strict authoring model | Fail on ambiguous, implicit, silent, or ordinary-looking composition behavior; require explicit markers for potentially meaning-changing decisions. | Permissive compatibility shortcuts, silent merges, implicit lookup, and ordinary overrides that create new paths. | The main product value is trusted, rebuildable composition where users can see and review every design decision. | Revisit only after the strict model is reliable and concrete user workflows show a repeated friction point. |
| Public entrypoint | Preserve `compose_config`; directive expansion is part of normal composition. | Separate public include expansion step. | Keeps v2 CLI and v10 sweeps on one composition path. | Revisit only if downstream callers need inspectable partial composition as public API. |
| Include resolution | Bare names resolve from including file and mapping key path; explicit relative paths resolve from including file directory; absolute paths and `file://` are supported. | Implicit global search path, registry aliases, plugin resolvers. | Deterministic and provenance-friendly. | Revisit when plugin or remote-store roadmap phases define extension contracts. |
| Include extension policy | Explicit paths require exact filenames. Bare names append exactly `.yaml`. V1 does not probe `.yml`, extension variants, or multiple candidates. | Extension probing and fallback candidates. | Probing creates ambiguous authored intent and makes provenance harder to review. | Revisit only if strict `.yaml` causes repeated real-world friction and the softening preserves deterministic provenance. |
| Include path normalization | Reject include paths that normalize outside the including config tree unless the author used an explicit relative path, absolute path, or `file://` URI. | Silent normalization outside the config tree. | Escaping the local config tree should be a visible author decision. | Revisit only with a documented source-root model or plugin/remote resolver contract. |
| CLI-authored bare includes | Fail unless the root config path and destination config path provide a single clear resolution base. | Treat all CLI bare includes as root-relative by default. | CLI overrides have weaker file-source context than authored YAML, so ambiguous bare component selection should fail closed. | Revisit during v2 CLI planning if explicit CLI syntax can make the base unambiguous. |
| Component replacement | `_include_` over existing mapping content requires same-site `_replace_: true`. | Silent recursive merge for component swaps. | Avoids stale key leakage. | Revisit only if real authoring workflows prove the requirement too noisy. |
| `_copy_` deferral | Exclude `_copy_` from v1. | Including copy expansion in the first strict composition release. | Nested components, safe swaps, and rebuildable source artifacts are higher priority and easier to make strict/reviewable. | Revisit after v1 include/replacement/source-artifact behavior is implemented and reviewed. |
| Ambiguity policy | Fail closed on uncertain include resolution, extension probing ambiguity, path normalization surprises, duplicate candidates, and CLI-authored bare includes without a clear root. | Guessing, choosing first match, normalizing silently, or treating missing context as root-relative without evidence. | Strict v1 behavior should expose every potentially unintended decision; later versions can soften behavior with explicit compatibility notes. | Revisit only after error telemetry or user workflows show a specific ambiguity that can be safely softened. |
| Manifest and source artifact schema timing | Design composition manifest and source artifact schema scaffolding in Phase 1, then populate and integrate it in later phases. | Waiting until full `compose_config` integration to design the schema. | Early schemas keep provenance, fingerprint, and rebuildability decisions coherent across phases. | Revisit only if Phase 1 discovers that existing provenance models already provide an equivalent stable schema. |
| Integration phase sizing | Split the current broad integration phase into smaller PR-sized phases. | One large phase for `compose_config`, provenance, source artifacts, fingerprints, recipes/interpolation integration, and e2e flows. | Smaller phases make strictness, provenance, rebuildability, and docs independently reviewable. | Revisit only if implementation proves the split creates artificial seams without review value. |
| Validation boundary | Explicitly support separate Loom pipeline config and project experiment/stage config files. Validate only Loom-owned envelopes and stable Loom contracts; project-owned mappings pass through as plain data. | Coupling pipeline config and experiment/stage config into one Loom-owned schema. | Keeps `loom` domain-neutral, allows each project stage to own its own config, and preserves direct Pipeline construction without `loom.config`. | Revisit when a stable project schema-extension API is intentionally designed. |
| Schema authoring | No YAML `_schema_`, no project schema registry, and no automatic `_target_` schema inference in v1. | Project schema imports from config files, Hydra structured-config style registries, and constructor-signature schema inference. | Avoids unclear ownership, surprising imports, and accidental coupling between config composition and project validation. | Revisit only with a deliberate project schema-extension design. |
| Security-first config artifacts | Persisted config artifacts and fingerprints are produced before variable/resolver values are resolved. Full resolved config is in-memory only by default. | Persisting the complete resolved config and hashing resolved resolver outputs by default. | Prevents resolved environment variables and other runtime values from being written to run artifacts by default. | Revisit only with an explicit opt-in persistence policy and secret classification model. |

## Practical Design Notes

Public Python API surface:

- Current default is to preserve `compose_config(...)` and extend returned
  composition/provenance data as needed.

CLI surface:

- No public CLI behavior in v1. Override syntax is designed so v2 CLI can expose
  it through the existing composition API.

Persisted records and file layout:

- `compose_config` should return serializable composition manifest and source
  snapshot data.
- Runner/run-store persistence may later write `config/composition_manifest.json`
  and `config/source_snapshots/`; v1 config modules should not write run
  directories directly.

Import boundaries and dependencies:

- Expected work stays under `src/loom/config/` and uses existing errors,
  serialization, fingerprint, provenance, YAML/config loading, and URI helpers.
- Config composition must not import pipeline execution, stores, CLI, plugin
  discovery, or project code.

Failure modes and diagnostics:

- Errors should identify config path, source file or override, include stack,
  resolved path or URI, schema boundary when relevant, and expected versus
  actual shape where useful.
- Include-resolution errors should state which strict rule failed: exact filename
  required, unsupported extension or extension probing, path escaped the config
  tree without explicit authoring, duplicate candidate, unclear CLI resolution
  base, unsupported URI scheme, missing target, or include cycle.

Maintainability and extensibility:

- The refined plan should split v1 into narrower phases: model/schema/merge
  foundations, recursive includes, source-aware validation/errors,
  `compose_config` integration with provenance/fingerprints, source
  artifact metadata/rebuildability, and hardening/docs/e2e.
- Main risk is phase coupling between source-location metadata, provenance,
  fingerprints, and manifest shape. Designing manifest and source artifact schema
  scaffolding early should reduce that risk.
- The current `implementation-plan-v1.md` must be refined because it still
  includes `_copy_`.

Scalability and future compatibility:

- V1 is local and deterministic. Remote and plugin URI behavior is deferred to
  later roadmap phases.

## Expected Composition And Resolution Order

This is the current working order to refine in `implementation-plan-v1.md`.
The guiding rule is: file-defined composition first, user-defined composition
second, recipe expansion before ordinary user value overrides, artifact-safe
provenance/fingerprints before resolver execution, and runtime-only resolution
last.

1. Load the base YAML config as a single UTF-8 YAML document with a non-empty
   mapping root. Hierarchical nested mappings are allowed. YAML streams with
   multiple `---` documents in one file are out of scope.
2. Load overlay YAML files in the user-provided order, one by one, using the
   same loading rules.
3. Merge each overlay over the accumulated file-authored tree in order. Nested
   mappings recursively merge. Scalars, lists, and explicit `null` replace whole
   values. `_replace_: true` discards lower-precedence mapping content at that
   path before applying the overlay mapping. Source authorship must survive each
   merge.
4. Validate file-authored composition directives before expansion: placement,
   value type, unsupported `_copy_`, invalid `_replace_`, unsupported URI
   scheme, and ambiguity-decision-tree failures.
5. Expand file-authored includes recursively. Include resolution uses the source
   context of the `_include_` directive:
   - base-authored includes resolve relative to the base file;
   - overlay-authored includes resolve relative to the overlay file;
   - explicit relative paths, absolute paths, and `file://` are accepted only
     under their strict rules.
6. For each file-authored include site, load and recursively expand the included document
   first, then merge local sibling keys over the included mapping. Sibling
   overrides are recorded as explicit composition decisions. Include swaps over
   existing lower-precedence mapping content require same-site `_replace_: true`.
7. Build an inspectable file-composed tree plus composition-site records. At this
   point file-defined includes, replacements, and sibling customizations have
   been applied, but user override strings have not.
8. Parse user override strings in order. Treat `path=value` as a strict update
   and `+path=value` as an explicit add. Dot paths remain simple and do not
   support escaping literal-dot keys in v1.
9. Apply user-defined composition overrides before recipe expansion:
   - `path._include_=...` updates an existing file-defined include site at
     `path`, re-expands that component, and records that the user overrode the
     file-authored component decision.
   - Adding a brand-new user include site must be explicit and must satisfy the
     same strict replacement rules as file-authored includes.
   - CLI-authored bare includes fail unless the root config and destination
     config path provide one clear base; explicit relative paths, absolute
     paths, and `file://` remain accepted under strict rules.
10. Reject any unsupported or late composition directive that cannot be handled
    deterministically. In particular, `_copy_` is unsupported in v1, and recipe
    outputs should not introduce new include directives unless a later design
    explicitly allows another include pass.
11. Do not execute variable interpolation or resolver expressions for artifact
    generation or fingerprints. Composition directives must be decidable from
    authored values and source context. Resolver-dependent include targets or
    resolver-dependent composition control flow fail in v1 rather than silently
    becoming runtime-dependent.
12. Expand registered trusted `_recipe_` blocks into plain mappings and record
    recipe manifest entries using artifact-safe inputs. Recipe declarations,
    arguments, and output fingerprints preserve unresolved interpolation
    expressions as authored text. If a recipe cannot expand without executing a
    resolver value, v1 should fail with an explicit unsupported/runtime-dependent
    recipe error.
13. Apply ordinary user value overrides against the expanded config. Strict
    update overrides must target paths that now exist after file composition,
    user composition overrides, and recipe expansion. Explicit `+` add overrides
    create missing paths. This lets users override recipe-produced paths.
14. Validate stable `loom`-owned schema boundaries that can be checked before
    runtime value resolution while leaving project-owned pass-through mappings
    alone.
15. Build artifact-safe composition provenance, recipe provenance, composition
    manifest records, source artifact records, and config fingerprints before
    resolver execution. Fingerprints include authored source content hashes,
    stable composition context, override strings/values, expanded unresolved
    config content, and resolver expressions as authored text. They do not hash
    resolved environment variables or other resolver outputs by default.
16. Produce the default persisted/redacted config artifact from the unresolved
    expanded config plus resolver-path metadata. It must not contain resolved
    environment variable values or other runtime resolver outputs by default.
17. Resolve final OmegaConf-style interpolation across the expanded and
    user-overridden config in memory for runtime use. Built-in OmegaConf
    resolvers may execute; custom resolver-style interpolation is not
    implemented in v1 and should fail with `NotImplementedError`.
18. Perform any final runtime-only validation and optional instantiation. A full
    resolved config may exist in memory for the caller, but run-store
    persistence must not write it by default.

Functional impacts:

- Overlay order is meaningful and must be preserved exactly.
- Later overlays can change file-authored include selections before file-defined
  include expansion.
- User override strings apply after file-defined composition, so ordinary value
  updates can target values introduced by included files.
- User composition overrides such as `path._include_=...` replace an existing
  file-defined include decision and cause the affected component subtree to be
  recomposed before recipes and ordinary user value overrides.
- Recipe expansion creates the concrete config shape before ordinary user value
  overrides, so users can override recipe-produced paths, but v1 recipe
  expansion must not depend on executing resolver values.
- Persisted artifacts support rebuilding authored/composed config inputs and
  comparing the artifact-safe composition fingerprint. They do not prove that
  environment variables or other resolver outputs match a previous run.
- Resume from config artifacts should report whether the authored composition
  matches. If unresolved resolver expressions are present, exact runtime-value
  replay is not guaranteed in v1 unless a later opt-in secret fingerprinting
  policy is added.
- A sibling value authored next to an include customizes the included component
  after the included file loads.
- Because user-defined composition happens after file-defined composition, the
  implementation needs composition-site records rather than a one-pass
  pre-include override merge.
- Overrides that appear to target recipe input arguments before expansion need a
  strict classification rule. The default design is that ordinary value
  overrides target the expanded result; pre-expansion recipe argument override
  behavior must be explicit if added.
- Absolute source paths help humans debug provenance, but matching/rebuildability
  should be based on content and stable composition context so manifests can be
  portable.
- `_target_` instantiation is separate from composition. When `instantiate()` is
  called, nested target values should be constructed bottom-up before their
  parent target is constructed. Add tests for nested target construction order
  instead of relying on plan prose.

Resume implications from D29:

- V1 config artifacts support an authored-composition resume check: rebuild the
  artifact-safe expanded config from source artifacts/manifests, compare the
  artifact-safe fingerprint, and report whether the authored composition inputs
  match.
- V1 config artifacts do not support an exact resolved-runtime replay guarantee
  when resolver expressions are present. Re-running the config may resolve
  `oc.env` or other supported runtime resolvers differently because the old
  resolved values were intentionally not persisted.
- If exact runtime replay is requested from artifacts that contain resolver
  expressions, the resume flow should fail closed or warn explicitly that only
  authored composition equivalence can be checked.
- A later opt-in feature could add secret-aware runtime-value fingerprints,
  keyed HMACs, or explicit resolved-config persistence, but those are deferred
  because each option weakens the default security posture or adds key
  management.

D32 composition manifest explanation:

- The composition manifest is the machine-readable receipt for a composed config
  artifact. It records the ordered decisions and source facts needed to explain,
  compare, inspect, and later attempt to rebuild an artifact-safe composed
  config.
- It is distinct from provenance prose or error context. Provenance can be
  broader and human-facing; the manifest should be narrow, versioned, plain
  serializable data that future run-store, resume, and CLI features can read
  without re-running composition first.
- It is also distinct from source artifacts. Source artifact records identify
  source files by stable metadata and hashes, and optionally raw snapshot
  payloads. The manifest references those source records and says how they were
  used: base config, overlay order, include site, replacement, recipe input, or
  override source.
- For run-store, the manifest is the object the runner can persist next to run
  metadata without needing to understand config internals. For resume, it is the
  comparison contract: rebuild or reload the current authored config, compare
  manifest schema version, source hashes, composition decisions, resolver
  expression paths, and artifact-safe fingerprint, then report whether authored
  composition still matches.
- The main design risk is schema overreach. V1 should define the manifest as a
  stable, versioned, additive contract for artifact-safe composition facts, not
  as a complete internal trace or a promise to preserve exact runtime resolver
  values.
- The manifest must not couple `loom.pipeline` to `loom.config`. Pipeline
  construction and execution should continue to accept normal Python/data inputs
  without reading manifest records. Runner/run-store/resume tooling may persist
  and compare manifests as run artifacts, but the manifest is an artifact
  contract rather than a pipeline API dependency.

## Config Design Decision Review Queue

Review status values:

- open: not yet discussed with the user.
- confirmed: current behavior or proposed behavior is accepted.
- change-needed: refine `implementation-plan-v1.md`, feature docs, or phase
  hardening instructions before implementation.

Current hardening/refactor instructions from reviewed decisions:

- D01: Preserve a strict config/pipeline boundary. `loom.pipeline` must not
  import `loom.config`, require composed config objects, or rely on config for
  construction. Add import-boundary and direct-Python-construction tests where
  needed.
- D02: Keep v1 trusted-config-only. Documentation and errors should explicitly
  say untrusted configs are unsupported.
- D03: Keep `compose_config` as the simple public path, but design scoped
  lower-level public inspection APIs for intermediate composition stages. These
  APIs must return stable records/plain data and must not become required by
  pipeline.
- D04: Keep authored config input narrow and predictable: single-document UTF-8
  YAML files, non-empty mapping roots, and plain-data-only parsed values.
  Hierarchical/nested YAML mappings and multi-file composition through includes
  remain supported; multi-document YAML streams are not part of v1.
- D05: Treat resolved absolute file paths as provenance context only. Semantic
  artifact-safe fingerprints and rebuildability should rely on content hashes
  plus stable composition context such as source role/order, config path,
  authored include value, portable relative path where available, and source
  snapshot IDs.
- D06: Preserve ordered overlays applied one-by-one. V1 must track source
  authorship through merge so include resolution, provenance, and errors know
  whether a value came from base, an overlay, or an override.
- D07: Keep strict merge semantics: mappings recursively merge; scalars, lists,
  and explicit `null` replace whole values; no list patching/deletion/splicing
  in v1.
- D08: Keep `_replace_: true` strict and explicit. Replacement is required when
  lower-precedence mapping content is discarded. For v1, treat unnecessary
  `_replace_` where nothing exists to replace as an author-intent mismatch that
  fails with an actionable error; this can be relaxed later.
- D09: Keep dot-path override syntax strict and simple in v1. Do not add escape
  syntax for literal-dot keys.
- D10: Keep typed override parsing, but document it precisely and add a literal
  string rule. Prefer JSON-quoted scalar strings for values that would otherwise
  parse as booleans, numbers, or `null`.
- D11: Change v1 composition order from "all overrides before includes" to
  "file-defined composition, then user-defined composition/overrides, then
  resolution." This requires composition-site records so user overrides can
  replace file-defined include choices after the baseline file composition has
  been evaluated.
- D12: Support many include sites across a config, but only one `_include_`
  directive per mapping node. Do not support list-valued includes, multiple
  includes inside one mapping node, scalar/list include sites, or Hydra
  defaults-list composition in v1.
- D13: Accept only bare names, exact explicit relative paths, absolute paths,
  and `file://` include targets in v1. Other URI schemes and plugin/remote
  resolvers fail.
- D14: Confirm bare-name resolution from including file plus mapping key path,
  appending exactly `.yaml`.
- D15: Explicit relative paths such as `../shared/foo.yaml` are accepted as
  explicit enough for v1, including when they leave the including config tree;
  record that escape clearly in provenance/errors.
- D16: User-authored bare include replacement is allowed only when replacing an
  existing file-defined include site whose source context is known. Brand-new
  user-authored include sites must use an explicit relative path, absolute path,
  or `file://`. Ordinary user value overrides run after user include replacement,
  so they may target values introduced by the recomposed included file.
- D17: Use the strict include replacement definition. `_replace_: true` is
  required whenever an `_include_` is authored at a path where the accumulated
  lower-precedence value is already a mapping, regardless of key overlap.
- D18: Allow sibling overrides next to `_include_`, but record each sibling
  override as an explicit local customization in provenance/manifest data.
- D19: Add richer path-aware and source-aware composition error context/helpers
  for strict v1 behavior. Errors should include include stacks, authored values,
  resolved targets or candidates, and remediation guidance.
- D20: Exclude `_copy_` from v1 and fail anywhere it appears in authored config
  with an explicit unsupported-directive error.
- D21: Change interpolation policy from rejecting all resolver-style tokens to
  allowing standard built-in OmegaConf resolvers, including `oc.env`, while
  failing custom resolvers with `NotImplementedError` for now. Resolver
  execution is runtime-only by default: artifact generation, manifests, and
  config fingerprints preserve resolver expressions as authored text rather
  than storing resolved values.
- D22: Treat recipes as file-defined behavior that expands before ordinary user
  value overrides. User value overrides should target the expanded concrete
  format only. Do not support pre-expansion recipe argument override syntax in
  v1. Recipe expansion must be artifact-safe in v1; if a recipe requires
  executing resolver values to decide its output shape, fail explicitly instead
  of making persisted artifacts runtime-dependent.
- D23: Harden recipe usage around explicit catalogs for reproducibility. Avoid
  relying on mutable process-global recipe registration in v1 composition paths
  where deterministic rebuildability matters.
- D24: Keep `_target_` import syntax simple and strict. Support dotted
  `package.module.Class` and colon `package.module:Class` forms only. Do not
  support nested object lookup after the final class segment or colon target.
  Instantiation remains separate from composition and constructs nested targets
  bottom-up.
- D25: Keep `_inject_` as instantiation/runtime behavior, but flag runtime object
  fingerprinting as an important pipeline/runtime responsibility. If injected
  objects affect outputs, pipeline/runtime fingerprint policy must account for
  them outside config fingerprints.
- D26: Explicitly support separate Loom pipeline config and project
  experiment/stage config files. `loom.config` validates only Loom-owned
  envelopes and stable Loom contracts; project/stage mappings remain
  project-owned plain data that can be composed, fingerprinted, and passed
  through without Loom schema ownership.
- D27: Do not add YAML `_schema_`, a project schema registry, automatic
  `_target_` schema inference, or project schema imports in v1. Project-specific
  validation remains outside the v1 config module.
- D28: Add structured error context objects/helpers while keeping public
  exceptions as `ConfigError` subclasses. This is important for strict
  composition, source-aware diagnostics, and project tooling.
- D29: Prefer security over exact resolved-value reproducibility. Do not persist
  the full resolved config by default. Generate config artifacts, manifests, and
  config fingerprints before resolver execution; record resolver expressions and
  resolver paths, not resolved environment/runtime values. Resume from artifacts
  can prove authored composition equivalence but cannot guarantee identical
  runtime resolver values in v1.
- D30: Provenance records how the artifact-safe composed config was produced,
  not resolved runtime values. Provenance should include source/order/include/
  override/recipe/fingerprint facts and resolver-expression paths, but should
  avoid storing resolved values. Documentation must warn users not to put
  sensitive values in overrides such as `+auth.token=...`; use environment
  variables and supported resolvers instead.
- D31: Default v1 fingerprints intentionally exclude secret, resolver, and
  runtime values. Exact runtime-value fingerprinting is deferred to a later
  explicitly enabled opt-in policy with strong warnings.
- D32: Make the v1 composition manifest a narrow, versioned, additive
  public-ish artifact contract. It records artifact-safe composition facts for
  run-store/resume/CLI inspection without coupling `loom.pipeline` to
  `loom.config` or requiring pipeline construction to understand manifests.
- D33: Source artifact persistence is security-first by default. Return
  artifact-safe source metadata and content hashes by default. Raw source bytes
  are persisted only through explicit opt-in or a later run-store security
  policy, so v1 can verify authored-composition equivalence when sources are
  available but cannot always rebuild missing config files from artifacts alone.
- D34: Keep `loom.config` persistence-free. It returns serializable artifact
  data but does not write run directories, choose run-store paths, or persist
  raw source snapshots.
- D35: Keep v1 Python-API-only. Public APIs, structured errors, manifests, and
  inspection records should be CLI-ready for later roadmap work, but v1 should
  not add public CLI commands or CLI-only shortcuts.
- D36: Replace the six-phase sketch with a more granular expanded phase strategy
  so public API, schema/artifact contracts, composition order, resolver security,
  recipes, provenance, fingerprints, source artifacts, and docs are reviewed in
  smaller PRs.
- Composition/order implementation note: write focused tests for ordered overlay
  application, source-aware merge authorship, include resolution from overlay
  sources, user include replacement after file include composition, ordinary
  overrides targeting values introduced by includes and recipes, artifact-safe
  fingerprinting before resolver execution, built-in versus custom runtime
  resolver behavior, and bottom-up recursive `_target_` instantiation.

| ID | Decision area | Current or proposed behavior | Functionality provided | Limitation or risk to confirm | Status |
| --- | --- | --- | --- | --- | --- |
| D01 | Module responsibility | `loom.config` may compose configs into plain/typed data and instantiate objects when called directly, but `loom.pipeline` and other components must not depend on `loom.config` for construction or operation. Pipeline must remain usable without config. | Keeps config mechanics domain-neutral without making config a required runtime dependency for pipeline APIs. | Requires import-boundary tests and API checks so pipeline specs/stages/runners can be built directly from Python data. | change-needed |
| D02 | Trust model | Authored configs are trusted project code; no untrusted sandbox or import allow-list mode. | Allows recipes and `_target_` instantiation without heavyweight security machinery. | Unsafe for untrusted config files; docs/errors must state that untrusted configs are unsupported. | confirmed |
| D03 | Public entrypoints | Preserve a simple public `compose_config` entrypoint, and add deliberately scoped lower-level public APIs for inspecting intermediate composition stages. | Normal users get one entrypoint; advanced users and reviewers can inspect staged composition decisions. | Lower-level API must avoid exposing unstable internals or encouraging pipeline coupling to config internals. | change-needed |
| D04 | Config loading | YAML only, UTF-8, `yaml.safe_load`, non-empty root mapping required, plain-data-only values, local filesystem paths resolved strictly. Hierarchical/nested YAML mappings and multi-file composition are supported; multi-document YAML streams are not. | Predictable authored input model and source hashing. | No JSON/TOML, no YAML stream with multiple `---` documents in one file, no empty config files, no non-local source loading. | confirmed |
| D05 | Source path identity | Resolved absolute paths are provenance context only. Fingerprints/rebuildability use content hashes plus stable composition context rather than absolute path identity. | More portable manifests and stable functional matching across relocated projects. | Gives up detecting a move, rename, or different absolute source path as a semantic change by itself; if path identity matters, it must be captured as explicit config content or portable authored context. | change-needed; policy accepted |
| D06 | Overlay model | Base config plus ordered overlays applied one-by-one; nested mappings merge under strict merge semantics while preserving per-value source authorship for v1. | Simple layered config authoring with correct include bases for overlay-authored values. | Requires source-map metadata through merge; composition order must be documented and tested carefully. | change-needed |
| D07 | Merge semantics | Mappings recursively merge; scalars, lists, and explicit `null` replace whole values. `_replace_` is the only whole-section escape hatch in v1. | Small, predictable merge model. | No list patching, deletion, splice, or structural edit language. | confirmed |
| D08 | Whole-section replacement | `_replace_: true` is the only v1 merge marker; it strips from resolved output and discards lower-precedence mapping content. Unnecessary `_replace_` where no lower-precedence content exists fails in v1. | Explicit safe component swaps and explicit author acknowledgement of discarded content. | More verbose and stricter than convenient authoring; can be relaxed later if too noisy. | change-needed; policy accepted |
| D09 | Override syntax | `path=value` updates existing paths; `+path=value` adds missing paths; dot paths split on literal dots; no escaping for literal-dot keys in v1. | Catches typos and forces explicit additions with a small override language. | Keys containing literal dots are not addressable by override strings. | confirmed |
| D10 | Override value parsing | `true`, `false`, `null`, integers, finite floats, JSON arrays/objects parse to typed plain data; other values remain strings; v1 should document JSON-quoted scalar strings for literal typed-looking text. | Useful typed CLI/API overrides without a YAML parser. | Current parser may need refinement for JSON-quoted scalar strings and clear docs for literal text. | change-needed |
| D11 | Composition order | File-defined composition runs first: base plus ordered overlays, file-authored directive validation, and file-authored include expansion. User-defined composition runs second: include replacement before recipe expansion, then ordinary value overrides against the expanded concrete config. Artifact-safe manifests/fingerprints are produced before resolver execution; runtime resolution is last. | File configs define the baseline; users can override file-defined include decisions and recipe-produced values while keeping persisted artifacts secret-safe. | Requires composition-site records, artifact-safe recipe constraints, and careful tests; older pre-include override and resolved-fingerprint model must be changed. | change-needed |
| D12 | Include directive placement | `_include_` is allowed only inside mappings; many include sites across a config are supported, but each mapping node may contain only one `_include_`. | Explicit nested component files at multiple config paths. | No list-valued includes, multiple includes inside one mapping node, scalar/list include sites, or Hydra defaults-list composition. | confirmed |
| D13 | Include target forms | Bare names, exact explicit relative paths, absolute paths, and `file://` are supported. Other URI schemes fail. | Local deterministic composition with a future resolver path. | No package resources, HTTP, S3, plugin resolvers, or remote includes in v1. | confirmed |
| D14 | Bare include resolution | Bare names resolve from including file plus mapping key path and append exactly `.yaml`. | Compact component selection while staying path-derived. | Renames/restructures config directories affect resolution; no `.yml` or extension probing. | confirmed |
| D15 | Explicit path resolution | Explicit paths require exact filenames; relative paths resolve from including file directory. `../shared/foo.yaml` is explicit enough even if it leaves the config tree, and that escape is recorded. | Makes non-local-tree references a visible author decision. | Strict failures may reject convenient path normalization; future versions may refine source-root policy. | confirmed |
| D16 | User-authored include resolution | Bare user include replacement is allowed only at an existing file-defined include site with known source context. Brand-new user include sites require explicit relative path, absolute path, or `file://`. Ordinary user value overrides run after user include replacement. | Users can swap established component slots concisely and still override recomposed included values. | Users cannot invent a new bare-name component slot from CLI/API; they must use explicit paths. | confirmed |
| D17 | Include replacement rule | `_replace_: true` is required whenever an `_include_` is authored at a path where the accumulated lower-precedence value is already a mapping, regardless of key overlap. New paths do not need `_replace_`. | Prevents stale keys surviving component swaps. | Stricter than overlap-only checks; authors must mark all mapping component swaps explicitly. | confirmed |
| D18 | Include sibling merge | Included mapping loads first; sibling keys in the including mapping override under normal merge semantics, and every sibling override is recorded as a local customization. | Allows component defaults plus explicit local customization. | Requires provenance/manifest support so local customizations are visible. | change-needed; policy accepted |
| D19 | Include cycle/missing/ambiguous errors | Fail closed with structured/path-aware/source-aware context: include stack, authored value, resolved target/candidates, and remedy. | Strict, debuggable composition. | Requires richer error context/helpers than current v0 string-only errors. | change-needed; policy accepted |
| D20 | `_copy_` | `_copy_` is excluded from v1 and fails anywhere it appears in authored config. | Keeps v1 focused on strict includes/replacement/rebuildability. | Template reuse waits for a later plan; existing docs/plan must remove copy scope. | confirmed |
| D21 | Interpolation surface | OmegaConf-style interpolation is supported at runtime. Built-in OmegaConf resolver-style interpolation such as `oc.env` may execute only in the runtime-resolution step by default. Custom resolvers are not implemented in v1 and should fail with `NotImplementedError`. Artifact-safe manifests/fingerprints preserve resolver expressions as authored text. | Value reuse plus standard OmegaConf configuration resolver behavior without persisting resolved secrets by default. | Current implementation rejects all `:` resolvers; v1 needs resolver allow-list/detection, docs, ordering tests, and no resolver execution during artifact generation. | change-needed |
| D22 | Recipe model | Recipes are explicitly registered trusted callables/classes. Recipes behave as file-defined behavior and expand before ordinary user value overrides. Ordinary user overrides target only the expanded concrete config, not pre-expansion recipe arguments. Manifest records target, unresolved/artifact-safe args, and artifact-safe output hash. | Reusable high-level config macros with provenance and user override of expanded concrete config. | Recipes cannot depend on executing resolver values to determine output shape in v1; users must know or inspect the expanded shape to override recipe-produced values; recipe argument override syntax is deferred. Recipes execute trusted Python and are not sandboxed. | change-needed; policy accepted |
| D23 | Recipe catalog policy | V1 should harden around explicit `RecipeCatalog` inputs for reproducibility; process-global `register_recipe` should not be the preferred path for deterministic composition. | Composition can be rebuilt with an explicit catalog dependency rather than ambient process state. | Existing convenience API may need documentation, warnings, or compatibility handling. | change-needed |
| D24 | `_target_` instantiation | Instantiation is separate from composition; `_target_` recursively imports/calls Python objects with `_args_`, `_partial_`, and `_inject_`. Support strict dotted `package.module.Class` and colon `package.module:Class`; do not support nested object lookup after the final class segment or colon target. | Keeps resolved config inspectable before object construction and keeps import semantics simple. | Executes/imports trusted project code; nested attributes/classes must be exposed as top-level module objects or factories. | confirmed |
| D25 | Runtime injection | `_inject_` maps constructor kwargs to runtime-provided values and rejects duplicates/missing keys. Config fingerprint does not hash runtime objects directly; pipeline/runtime fingerprint policy must account for semantically meaningful runtime objects. | Keeps runtime-only objects out of persisted config while flagging semantic runtime inputs for the execution layer. | Important cross-module requirement; runtime object fingerprinting must be addressed by pipeline/runtime, not silently ignored. | change-needed |
| D26 | Validation boundaries | Explicitly support separate Loom pipeline config and project experiment/stage config files. Stable `loom` schemas validate only Loom-owned envelopes and contracts; project/stage mappings pass through as project-owned plain data. | Keeps `loom` domain-neutral, lets each stage own its own config file, and preserves Pipeline use without config. | Need exact list of Loom-owned sections and clear docs for where project-owned validation is expected to occur. | change-needed; policy accepted |
| D27 | Schema authoring | No YAML `_schema_`, no project schema registry, no automatic `_target_` schema inference, and no project schema imports in v1. | Avoids unclear ownership, surprising imports, and coupling config composition to project validation. | Project-specific config validation remains outside v1. | confirmed |
| D28 | Error model | Config errors should be path-aware and source-aware, with strict decision-tree remedies. Add structured error context objects/helpers while keeping public exceptions as `ConfigError` subclasses. | Makes strict behavior usable and machine-inspectable for project tooling. | Current errors are mostly string-based; v1 needs richer context without leaking secrets. | change-needed; policy accepted |
| D29 | Security and redaction | Do not persist the full resolved config by default. Save artifact-safe unresolved/redacted expanded config, source metadata/hashes, manifests, provenance, resolver-path metadata, and config fingerprints before resolver execution. Runtime resolver outputs may exist in memory but are not written by default. | Prevents resolved environment variables and other runtime values from leaking into run artifacts by default. Resume can rebuild or compare authored/composed config inputs where sources or opted-in snapshots are available. | Exact runtime-value replay is not guaranteed from config artifacts when env/resolver values are involved. Secret-aware value hashing or opt-in resolved persistence is deferred. | change-needed; policy accepted |
| D30 | Provenance model | Record how the artifact-safe composed config was produced: base/overlay source records, ordering, includes, replacements, override paths and operation kinds, recipes, schema boundaries, source hashes, sibling override paths, resolver-expression paths, security policy, and loom version. Do not record resolved runtime values. | Explains how artifact-safe composed config was produced and what runtime resolver work remains. | Provenance may become large and may still expose user-authored plaintext secrets if authors put secrets directly in config/overrides; docs must warn users to use environment resolvers for secrets. | change-needed; policy accepted |
| D31 | Fingerprint policy | Config fingerprint should be artifact-safe by default: source content hashes, stable composition context, overrides after artifact-safe redaction, recipe declarations/outputs that do not require resolver execution, unresolved expanded config content, and resolver expressions as authored text. Secret/resolver/runtime values are excluded by default. | Resume detects meaningful authored composition changes without storing resolved secrets. | Does not detect changed resolver outputs; exact runtime replay requires a later explicitly enabled opt-in secret-aware fingerprint policy with warnings. | change-needed; policy accepted |
| D32 | Composition manifest schema | Make the v1 manifest a narrow, versioned, additive public-ish artifact contract. Populated records explain artifact-safe base/overlay/override/include/replacement/recipe/resolver/source/fingerprint inputs. Pipeline construction must not depend on reading manifests. | Stable contract for authored-composition resume, CLI inspection, and run-store persistence without coupling pipeline logic to config internals. | Premature schema could overfit v1 unless designed narrowly; runner/run-store can persist the manifest, but pipeline remains usable without config or manifest artifacts. | change-needed; policy accepted |
| D33 | Source artifacts | Config returns artifact-safe source metadata and content hashes for base, overlays, and includes by default. Raw source bytes are not persisted by default; they require explicit opt-in or a later run-store security policy. | Verifies authored-composition equivalence when original sources are available or raw snapshots were opted into. | Cannot always rebuild missing config files from artifacts alone; local/file sources only; raw snapshot persistence needs security warnings and limits. | change-needed; policy accepted |
| D34 | Persistence boundary | `loom.config` returns serializable artifact data but does not write run directories, choose run-store locations, or persist raw source snapshots. | Keeps run-store ownership clear and keeps config composition testable without filesystem side effects beyond reading configured sources. | Rebuildability depends on runner/run-store later persisting returned artifacts and applying any explicit raw-source policy. | confirmed |
| D35 | Public CLI relationship | V1 is Python-API-only. Config APIs, structured errors, manifests, and inspection records should be ready for later CLI use, but v1 adds no public CLI commands or CLI-only shortcuts. | Avoids CLI-specific behavior in core config while leaving v2 CLI a clean wrapping path. | CLI ergonomics remain deferred; Python API docs must be sufficient for v1 users. | confirmed |
| D36 | Test/phase strategy | Replace the six-phase sketch with an expanded PR-sized strategy: boundary/contracts, strict loading/errors, overrides/merge, source-authored overlays, include resolution, file includes, user composition overrides, resolver security, recipes, validation, instantiation, compose orchestration, provenance/manifest/redaction, fingerprints/resume, source artifacts, and hardening/docs/e2e. | Keeps high-risk design changes reviewable and avoids combining public API, persistence contract, security, and composition-order changes in one PR. | More phase overhead; phases can be collapsed only if implementation proves genuinely trivial without reducing review clarity. | change-needed; expanded strategy proposed |

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No global search path or resolver plugins | Keeps v1 deterministic and avoids premature extension APIs. | V11 plugin discovery or V12/V13 remote store work needs explicit resolver contracts. |
| Lists still replace as whole lists | Avoids inventing a list patch language in v1. | A concrete config authoring workflow needs reviewable list mutation semantics. |
| Raw source bytes are not persisted by default | Preserves the security-first artifact policy because authored YAML and overrides may contain inline secrets. | A user needs exact rebuildability after source files disappear and accepts explicit raw-source persistence risk. |

## Expanded Phase Strategy

This supersedes the earlier six-phase sketch. The implementation plan should use
these narrower phases by default because v1 now includes strict composition
ordering, artifact-safe security behavior, public-ish manifest contracts, and
explicit config/pipeline separation. Adjacent phases may be collapsed only when
implementation proves genuinely trivial without reducing review clarity.

| Phase | Scope | Explicitly out of scope | Required evidence |
| --- | --- | --- | --- |
| 1. Boundary and artifact contracts | Establish config/pipeline import-boundary tests; define persistence-free config artifact return contracts; add versioned manifest/source/provenance/fingerprint model skeletons as plain serializable data; document no v1 CLI and no pipeline dependence on manifests. | Behavior-changing composition, includes, resolver execution, run-store writes, CLI commands. | Package/import tests; contract serialization tests for empty/minimal artifact records. |
| 2. Strict loading and structured errors | Enforce single-document UTF-8 YAML, non-empty mapping root, plain-data values, unsupported `_copy_` failure, and `ConfigError` subclass structure with machine-readable context. | Includes, overlays, override application, schema validation, resolver execution. | Unit tests for loader failures, `_copy_` rejection, and structured error fields without secret values. |
| 3. Overrides and merge primitives | Implement strict `path=value` updates, explicit `+path=value` adds, typed override parsing, simple dot paths with no escaping, recursive mapping merge, list/scalar/null replacement, and strict `_replace_`. | Include loading, recipe expansion, final `compose_config` orchestration. | Unit tests for parser, strict/add behavior, invalid paths, `_replace_` required/unnecessary cases, and merge semantics. |
| 4. Source-authored overlays | Apply base plus ordered overlays one-by-one while preserving source authorship metadata and path provenance context. | Recursive includes, user include replacement, recipes, fingerprints. | Unit/integration tests showing overlay order, source-map preservation, and overlay-authored values retaining their source file context. |
| 5. Include resolution primitives | Resolve accepted include target forms: bare names, exact relative paths, absolute paths, and `file://`; enforce `.yaml` bare-name behavior, no probing, no unsupported URI schemes, no resolver-dependent include targets. | Recursive expansion, user-authored include replacement, plugin/remote resolvers. | Unit tests for every target form and failure case, including unsafe normalization and missing/ambiguous targets. |
| 6. File-defined recursive includes | Expand file-authored includes recursively with include stacks, cycle detection, sibling merge/customization records, strict include replacement, and source-aware errors. | User composition overrides, recipes, runtime interpolation, raw source snapshots. | Unit/contract tests for nested includes, cycles, sibling overrides, replacement requirements, include stack records, and include provenance serialization. |
| 7. User composition overrides | Apply user-defined composition after file-defined composition: existing-site bare include replacement, explicit brand-new include sites only, recomposition of swapped subtrees, and ordinary value override pass hooks. | Recipe expansion, resolver execution, final public compose orchestration. | Integration tests for user include swaps, brand-new include restrictions, ordinary overrides targeting recomposed included values, and source-context errors. |
| 8. Resolver security and runtime interpolation | Add resolver-expression scanning, artifact-safe no-execution paths, runtime-only built-in OmegaConf resolver execution, `NotImplementedError` for custom resolvers, and failures for resolver-dependent composition control flow. | Recipes that depend on resolver values, persisted resolved config, secret-aware hashes. | Unit/integration tests proving artifact generation does not execute resolvers, built-ins resolve only at runtime, and custom resolvers fail clearly. |
| 9. Recipe catalog and expansion | Harden explicit `RecipeCatalog`; expand recipes as file-defined behavior before ordinary user value overrides; record artifact-safe recipe entries; reject pre-expansion recipe argument overrides and resolver-dependent recipe output shape. | Ambient process-global recipe reliance for reproducibility, recipe argument override syntax, sandboxing trusted recipe code. | Unit/integration tests for explicit catalog use, expansion order, artifact-safe output hashes, override-after-expansion behavior, and failure on resolver-dependent shape. |
| 10. Loom validation boundaries | Validate only Loom-owned envelopes/contracts after composition stages that are safe to validate; keep project/stage config as pass-through plain data; reject YAML `_schema_`, project schema registries, and automatic `_target_` schema inference. | Project-specific validation systems, CLI UX, pipeline dependence on config. | Unit/integration tests for Loom-owned validation, project-owned pass-through, schema-feature rejection, and structured validation errors. |
| 11. Strict instantiation and runtime injection | Keep instantiation separate from composition; enforce dotted and colon `_target_` forms, no nested object lookup after final class segment/colon target, bottom-up construction, `_partial_`, and `_inject_` duplicate/missing checks. | Pipeline/runtime object fingerprint policy implementation, composition artifact fingerprints. | Unit tests for import forms, invalid targets, bottom-up construction order, partial construction, and injection errors. |
| 12. Public compose orchestration and inspection APIs | Wire the complete `compose_config` order using prior phases; expose simple public entrypoint plus scoped lower-level inspection APIs for intermediate stages; keep pipeline independent and config persistence-free. | Manifest/fingerprint final population, raw source snapshot opt-in, CLI commands. | Package/API tests, integration tests for full order through recipes and runtime resolution, inspection API contract tests, import-boundary tests. |
| 13. Provenance, manifest, and redaction population | Populate artifact-safe provenance and the versioned composition manifest with source/order/include/override/recipe/resolver/security facts; produce default unresolved/redacted config artifact; warn against plaintext secrets in overrides. | Fingerprint comparison logic, raw source bytes by default, resolved config persistence. | Contract tests for manifest/provenance records, redaction tests, no resolved runtime values in default artifacts, docs snippets for secret handling. |
| 14. Artifact-safe fingerprints and resume comparison | Compute default fingerprints before resolver execution from source hashes, stable composition context, unresolved expanded config, resolver expressions, and redacted/allowed override facts; add authored-composition resume comparison helpers if in v1 scope. | Exact runtime-value replay, secret-aware opt-in fingerprints, run-store persistence. | Unit/contract tests for fingerprint stability/change cases, resolver-output exclusion, path portability, and resume comparison outcomes. |
| 15. Source artifacts and raw snapshot opt-in | Return source metadata/hashes by default; add explicit raw source snapshot opt-in or clearly defer it to run-store policy; dedupe raw payloads when enabled. | Default raw source-byte persistence, run directory writes, remote/plugin sources. | Unit/contract tests for source hashes, manifest references, dedupe, opt-in raw payload behavior if implemented, and metadata-only rebuild limitations. |
| 16. Hardening, docs, and e2e | Audit docs, examples, errors, and tests against the final v1 strict model; update implementation-plan status/evidence; run final validation gates. | New composition features, CLI commands, plugin/remote includes, sweeps, `_copy_`. | `make validate-pr`, `make test-summary`, focused e2e composition trees, docs covering limitations and security tradeoffs. |

Phase strategy implications:

- Phases 1, 8, 12, 13, and 14 have public API or artifact-contract impact and
  should use the expanded phase workflow by default.
- Each phase should record accepted debt and future compatibility notes in its
  phase execution plan, especially when it intentionally leaves later phases
  incomplete.
- `implementation-plan-v1.md` should remove `_copy_` implementation scope and
  replace the current broad compose/provenance/source-artifact phase with phases
  12-15.
- No phase should introduce run-store writes or CLI commands.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| What should v1 optimize for: authoring ergonomics, correctness/rebuildability, phase review speed, or later-roadmap compatibility? | Roadmap framing, tradeoffs, phase sizing | Correctness/rebuildability and future-roadmap compatibility | closed |
| Is Phase 4 too broad for one reviewable PR? | Phase shaping and plan-quality gate | Yes; split into compose integration/provenance/fingerprints and source artifacts/rebuildability | closed |
| Should the plan specify exact include extension behavior now? | Include resolution, test expectations | Exact filenames for explicit paths; bare names append exactly `.yaml`; no probing | closed |
| Should composition manifest schema be designed earlier than Phase 4? | Provenance, fingerprints, source artifacts | Yes; schema scaffolding belongs in Phase 1 and is populated later | closed |
| Where should the ambiguity decision tree live in the final implementation plan? | Practical design, reviewability | A plan-level section plus phase-specific acceptance criteria | closed |
| Does the expanded phase strategy create reviewable PR-sized units without excessive process overhead? | Phase shaping | Use the expanded strategy as the implementation-plan draft input; collapse adjacent phases only when implementation is genuinely trivial and review clarity is preserved | open |

## Handoff Notes

Implementation-plan draft inputs:

- Existing target plan: `docs/implementation-plans/implementation-plan-v1.md`.
- Roadmap entry: `docs/implementation-plans/implementation-roadmap.md#v1---rebuildable-config-composition`.
- Primary feature docs: `config.md`, `serialization.md`, `io.md`,
  `fingerprints.md`, `provenance.md`, `errors.md`, and `testing.md`.

Plan-quality-gate risks:

- The original Phase 4 combined too much public behavior, provenance, source
  artifact, and fingerprint work into one PR; the refined plan should split it.
- Include source metadata must remain coherent across base files, overlays, and
  CLI override mappings.
- The existing `implementation-plan-v1.md` must remove `_copy_` scope and tests
  before implementation starts.
- Strict update and `+` add override semantics may break existing v0 workflows if
  compatibility is not handled deliberately.
- Manifest/source artifact records need enough structure for future runner,
  CLI, sweep, plugin, and remote phases without becoming a premature extension
  system.

Assumptions to carry forward:

- V1 remains domain-neutral and trusted-config only.
- V1 starts from the completed v0-post contract set.
- The current implementation plan is the baseline to discuss and refine, not a
  request to implement product code.

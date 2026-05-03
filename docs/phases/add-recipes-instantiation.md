# Phase 5 Expanded Plan: Recipes And Instantiation

## Metadata

- Status: pr_open.
- Branch: `codex/add-recipes-instantiation`.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-recipes-instantiation`.
- Expanded plan path: `docs/phases/add-recipes-instantiation.md`.
- Full plan: `docs/implementation-plans/implementation-plan-v0.md`.
- Source phase: `Phase 5 - Recipes And Instantiation`.
- Base branch: local `develop` at `dddfebe9b33e2f870e0c5053b3f4b08561d3d89d` (`docs: record config composition cleanup`).
- Target branch: `develop`.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers are recorded in the canonical v0 plan.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not rerun the plan-quality gate for this phase.
- Draft/refine status: draft expanded plan was committed as
  `fd6b04cae25432cd57a06e8a7543d9c8300e535a`; final expanded-plan refinement
  is completed by the plan expansion pass recorded in this branch.
- Setup limitations: the original checkout has unrelated uncommitted workflow and docs edits, including deleted or renamed prompt/template files. This worktree was created from committed local `develop`, and this plan uses the committed Phase 5 prompt/template files from this worktree. The first sandboxed worktree creation attempt could not create the nested `codex/add-recipes-instantiation` ref because the sandbox exposed `.git/refs/heads` as read-only; the approved escalated rerun created the branch and worktree successfully. Remote synchronization and GitHub authentication checks were not repeated in this draft pass because the manager assignment supplied the current pushed `develop` commit and remote preflight.
- Prior phase state: Phase 1, Phase 2, Phase 3, and Phase 4 are recorded as merged. Phase 5 is the next pending phase.
- Setup blockers: none for local planning.
- Blockers: none.

## Objective

Implement the two trusted config mechanisms that Phase 4 deliberately deferred:
named `_recipe_` expansion and recursive `_target_` object construction. Recipe
expansion must turn ergonomic project-authored recipe blocks into explicit
plain-data config blocks during composition, while recording deterministic recipe
manifest records. Object instantiation must remain an explicit Python API that
imports trusted targets and constructs nested object graphs only when callers ask
for it.

This phase must keep config behavior domain-neutral. It may import project code
only through explicit trusted `_target_` or registered recipe paths during
recipe expansion or `instantiate()` calls. It must not execute pipeline stages,
parse pipeline specs, persist run directories, discover plugins, sandbox imports,
or serialize injected runtime objects into resolved config.

## Full-Plan Context

Phase 4 added hard config dependencies, trusted YAML composition, overlays,
dot-path overrides, interpolation, top-level validation, redaction, config
provenance, deterministic config fingerprints, and a stable `ComposedConfig`
shape with an empty `recipe_manifest`. It also kept `_target_` values as plain
data and rejected `_recipe_` blocks as an unsupported bridge.

Phase 5 replaces that bridge. The composition flow after this phase is:

```text
load base config
load overlays
recursive merge
apply dot-path overrides
resolve enough interpolation for recipe arguments
expand recipes
resolve interpolation again
validate
redact
compute config provenance, recipe manifest, and fingerprint
```

Later phases consume the results but remain out of scope here:

- Phase 6 parses the resolved `pipeline` mapping into static `PipelineSpec` and
  `StageSpec` objects. Phase 5 must not parse stage mappings or reject future
  Phase 6 stage fields except through config-owned reserved-key rules.
- Phase 7 and Phase 9 persist resolved configs, redacted configs, recipe
  manifests, and provenance through run stores and runners. Phase 5 composition
  still writes nothing.
- Phase 9 instantiates pipeline stage targets as part of local execution.
  Generic `instantiate()` exists in Phase 5, but config composition and pipeline
  parsing must not use it to construct stage objects early.
- Phase 10 hardens representative error messages across subsystems. Phase 5
  still needs path-aware recipe, import, constructor, and injection errors for
  its own acceptance criteria.

Future-phase and deferred work that must remain out of scope includes entry-point
recipe discovery, plugin loading, import sandboxing or allow-list mode, pipeline
execution, stores, runner behavior, pipeline spec parsing, serializing injected
runtime dependencies, functional CLI behavior, domain recipes, domain stages,
domain codecs, schemas, datasets, models, reports, and post-v0 static fan-out
recipe behavior.

## Source Phase Summary

From `docs/implementation-plans/implementation-plan-v0.md`, Phase 5 is
`Status: pending` with branch `codex/add-recipes-instantiation` and PR
`pending`.

- Goal: implement the two reusable config mechanisms allowed in v0: named
  `_recipe_` expansion and recursive `_target_` object construction.
- Required scope:
  - Add recipe protocols/models, explicit recipe catalogs, public
    `register_recipe`, recursive recipe expansion, and recipe provenance
    records.
  - Add target import helpers for dotted and colon paths.
  - Add recursive `_target_` instantiation with `_args_`, `_partial_`, and
    `_inject_`.
  - Validate reserved-key usage and path-aware constructor/import failures.
- Required checkpoints:
  - Define `ConfigRecipe`/`Recipe` contracts and a Pydantic-backed recipe model
    path for typed recipe inputs.
  - `RecipeCatalog` is explicit and instance-based; the public default registry
    must be test-isolated.
  - Recipe expansion recursively replaces mappings with `_recipe_`, records
    path, recipe name, target, input arguments, expanded hash, expanded path,
    and loom version.
  - Update `ComposedConfig.recipe_manifest` from an empty tuple to deterministic
    list-like records represented as plain-data dictionaries.
  - Target imports support `package.module.Class`, `package.module:function`,
    and `package.module:Class`, with path-aware import and constructor errors.
  - Recursive instantiation handles nested mappings/sequences, `_args_`,
    `_partial_=true`, and `_inject_` from an explicit runtime dependency
    mapping.
  - Reserved keys are `_target_`, `_args_`, `_partial_`, `_inject_`, and
    `_recipe_`; misuse fails loudly.
- Acceptance criteria:
  - Recipe registration, lookup, duplicate detection, and unknown-recipe
    failures work.
  - Nested recipes expand deterministically and record useful provenance.
  - Recipe argument pre-resolution supports references to composed base, overlay,
    and override values, and expanded recipe blocks participate in the final
    interpolation pass.
  - Target import supports documented path forms and reports path-aware errors.
  - Recursive instantiation handles nested mappings/sequences, positional args,
    partials, and runtime injection.
  - Trusted config behavior is documented and scoped.

## Current Source And Harness Findings

- `src/loom/config/api.py` defines `ComposedConfig`, implements public
  `compose_config()` by delegating to `loom.config.compose`, and still has
  unsupported Phase 5 stubs for `instantiate()` and `register_recipe()`.
- `ComposedConfig.recipe_manifest` is currently typed as
  `tuple[dict[str, PlainData], ...]`; Phase 5 can populate this existing field
  without changing the dataclass shape.
- `src/loom/config/compose.py` currently rejects any non-`None`
  `recipe_catalog`, fully resolves interpolation, rejects `_recipe_` keys
  through `validate_no_recipe_keys()`, validates top-level fields, redacts, and
  computes provenance/fingerprint.
- `src/loom/config/interpolation.py` owns all OmegaConf usage and returns plain
  data. Recipe argument pre-resolution should reuse this boundary or add a
  neighboring config-owned helper; no other subsystem should import OmegaConf.
- `src/loom/config/validation.py` currently owns Phase 4
  `validate_no_recipe_keys()`. Phase 5 should remove that call from the normal
  composition path, keep top-level validation focused on stable config fields,
  and move recipe/reserved-key validation into the recipe and instantiation
  modules that know the directive context.
- `src/loom/config/provenance.py` has `ConfigSource`, `ParsedOverride`,
  `ConfigProvenance`, and `build_config_fingerprint()`. It records
  `recipe_manifest_count` but does not yet include recipe manifest records in
  the fingerprint payload.
- `src/loom/config/errors.py` has Phase 4 errors, including
  `UnsupportedRecipeError`. Phase 5 should keep existing error imports safe,
  stop using `UnsupportedRecipeError` for successful recipe-capable composition,
  and add the concrete Phase 5 errors named in the decision-complete contract.
- `src/loom/config/recipes/` and `src/loom/config/instantiate/` do not exist yet.
  `docs/structure.md` reserves those subpackages for this phase's work.
- Existing package tests assert `import loom` does not import `loom.config`,
  `omegaconf`, `pydantic`, `yaml`, pipeline, or CLI modules. This boundary must
  remain true.
- Existing Phase 4 config unit tests live under `tests/unit/loom/config/`.
  Existing integration tests live under `tests/integration/config/`.
  Several tests currently assert unsupported recipe behavior and must be updated
  to the Phase 5 behavior rather than removed without replacement.
- The Make harness exposes `make test-package`, `make test-unit`,
  `make test-contract`, `make test-integration`, `make test-e2e`,
  `make validate-pr`, and `make test-summary`. Missing suites are reported by
  the harness rather than by ad hoc shell logic.

## In-Scope Work

- Add `src/loom/config/recipes/` modules aligned with `docs/structure.md`:
  - `__init__.py`
  - `base.py`
  - `catalog.py`
  - `expansion.py`
  - `errors.py`, re-exporting the recipe errors defined in
    `loom.config.errors`
- Add `src/loom/config/instantiate/` modules aligned with `docs/structure.md`:
  - `__init__.py`
  - `targets.py`
  - `recursive.py`
  - `injection.py`
  - `errors.py`, re-exporting the target/instantiation errors defined in
    `loom.config.errors`
- Add a local `ConfigRecipe` protocol in `loom.config.recipes.base` and a public
  Pydantic-backed `Recipe` base model path for typed recipe inputs.
- Add an explicit `RecipeCatalog` class with deterministic registration,
  lookup, duplicate detection, unknown-recipe errors, optional explicit
  replacement, deterministic iteration, and no entry-point discovery.
- Implement the public default recipe registry through `register_recipe()`.
  Tests should prefer fresh explicit catalogs; tests that touch the public
  default registry must use unique registered names or monkeypatch the private
  default.
- Make `compose_config(..., recipe_catalog=...)` accept an explicit
  `RecipeCatalog`; when omitted, use the public default catalog.
- Replace unsupported `_recipe_` rejection with deterministic recursive recipe
  expansion.
- Add recipe manifest records as plain-data dictionaries in
  `ComposedConfig.recipe_manifest`, with path, name, target, arguments,
  expanded hash, expanded path, and loom version.
- Include recipe manifest data in config provenance/fingerprint assembly so
  recipe choices and expansion results affect the composed config fingerprint.
- Add target import helpers for `package.module.Class`,
  `package.module:function`, and `package.module:Class`.
- Implement public `instantiate(value, *, runtime=None)` for recursive target
  construction over mappings and sequences.
- Support `_args_` positional arguments, `_partial_=true`, and `_inject_`
  runtime dependency mapping during instantiation.
- Validate reserved-key usage in recipe blocks and in object graphs passed to
  `instantiate()`.
- Update package, unit, contract, and integration tests for the Phase 5 behavior.

## Out-of-Scope Work

- No entry-point recipe discovery, plugin loading, plugin records, fake entry
  point tests, or automatic registration from installed packages.
- No config sandbox, target allow-list mode, import policy layer, or security
  isolation. Authored configs remain trusted project code in v0.
- No pipeline execution, pipeline spec parsing, graph validation, runner
  behavior, selectors, stores, artifact registration, run directory persistence,
  or status/provenance file writes.
- No serializing injected runtime dependencies into resolved config, redacted
  config, recipe manifests, fingerprints, or config provenance.
- No domain recipes, domain stages, domain codecs, schemas, datasets, models,
  metrics, reports, or fixtures that imply domain behavior in `loom`.
- No static fan-out recipe semantics that splice a returned sequence into a
  parent sequence. V0 recipe expansion replaces one mapping with one expanded
  mapping.
- No stage constructor kwargs policy. Generic `instantiate()` can construct
  ordinary object graphs, but Phase 6 and Phase 9 own how pipeline stage
  `_target_` values are parsed and constructed.
- No top-level `loom.__init__` config exports.
- No PR body creation, full validation run, PR opening, remote push, or product
  implementation during this planning pass.

## Assumptions

- Local `develop` at `dddfebe9b33e2f870e0c5053b3f4b08561d3d89d` is the correct
  Phase 5 base because the manager assignment records it as committed locally and
  pushed to origin.
- `RecipeCatalog` refers to an explicit catalog object. Registered recipe
  implementations are recipe classes/factories or plain function recipes, not
  non-callable long-lived configured recipe instances.
- `Recipe` is a convenience base for typed recipes using Pydantic v2. Recipes do
  not need to inherit from it if they satisfy the local `ConfigRecipe` protocol
  or function recipe contract accepted by `RecipeCatalog`.
- Recipe implementations must be importable enough to produce a stable target
  string for manifest records. Tests should register top-level dummy recipe
  classes/functions rather than local closures whose `__qualname__` contains
  `<locals>`.
- A Phase 5 recipe block has `_recipe_` plus keyword argument keys. `_target_`,
  `_args_`, `_partial_`, and `_inject_` are invalid inside the same mapping
  because they are instantiation directives, not recipe arguments.
- A mapping containing `_recipe_` is atomic for expansion. Its non-reserved
  fields are recipe inputs, not child config nodes. If a recipe input value
  itself contains a nested `_recipe_` mapping, fail as ambiguous recipe nesting in
  v0; recipes that need nested recipes should return those `_recipe_` blocks from
  `expand()` so the manifest order remains parent before child.
- A recipe's `expand()` result must be a mapping normalized to plain data. Static
  fan-out recipes that return sequences are deferred until a later phase defines
  splicing, naming, and provenance semantics.
- Recipe manifest `path` and `expanded_path` are the same in v0 because recipes
  replace their authored block in place. Both fields are recorded so later
  fan-out or relocation behavior can evolve without changing the record shape.
- New Phase 5 path strings should use user-facing config path notation:
  top-level keys as `data`, nested identifier keys as `data.source`, sequence
  items as `pipeline.stages[0]`, non-identifier mapping keys as
  `settings['not-an-id']`, and `$` only for the root mapping. Manifest `path`
  points to the recipe block, not to the `_recipe_` key inside it.
- Recipe argument pre-resolution resolves arguments against the composed
  base/overlay/override config before expansion. It does not require references
  produced only by the recipe's own expansion to resolve early.
- Expanded recipe output participates in the final interpolation pass. A recipe
  may return `${...}` references that become valid only after the expanded block
  is inserted into the config.
- `instantiate()` operates on the value supplied by the caller. It should not
  call `compose_config()` internally and should not expand recipes. Callers that
  want recipe expansion must compose first.
- Runtime injection values are trusted in-process objects. They are not
  plain-data checked and are never included in resolved config or recipe
  manifests.

## Decision-Complete Contract

The executor must treat this section as the implementation contract. If a
required public shape conflicts with current code or with the canonical v0 plan,
stop and report the blocker instead of widening the phase.

### Public API

- `src/loom/config/__init__.py` exports:
  - `ConfigError`
  - `ComposedConfig`
  - `Recipe`
  - `RecipeCatalog`
  - `compose_config`
  - `instantiate`
  - `register_recipe`
- `src/loom/config/recipes/__init__.py` exports `ConfigRecipe`, `Recipe`, and
  `RecipeCatalog`.
- `src/loom/config/instantiate/__init__.py` exports `import_target` and the
  internal recursive `instantiate` implementation used by `loom.config.api`.
- `ConfigRecipe` is importable from `loom.config.recipes` for structural typing,
  but it is intentionally not re-exported from `loom.config`.
- `compose_config` keeps the Phase 4 signature shape:

  ```python
  def compose_config(
      config_path: str | Path,
      overlays: Sequence[str | Path] = (),
      overrides: Sequence[str] = (),
      recipe_catalog: RecipeCatalog | None = None,
  ) -> ComposedConfig: ...
  ```

  Passing `recipe_catalog=None` uses the public default recipe catalog. Passing
  any non-`None` object that is not a `RecipeCatalog` raises
  `ConfigValidationError` before loading files.
- `instantiate` has this public shape:

  ```python
  def instantiate(
      value: object,
      *,
      runtime: Mapping[str, object] | None = None,
  ) -> object: ...
  ```

- `register_recipe` registers into the public default catalog:

  ```python
  def register_recipe(
      name: str,
      recipe: RecipeImplementation,
      *,
      replace: bool = False,
  ) -> None: ...
  ```

- Do not modify `src/loom/__init__.py`; top-level `loom.__all__` remains the
  existing foundational export list.

### Error Classes And Exports

- Define these concrete Phase 5 errors in `loom.config.errors` and include them
  in that module's `__all__`:
  - `RecipeRegistrationError(ConfigError)`
  - `DuplicateRecipeError(RecipeRegistrationError)`
  - `UnknownRecipeError(ConfigError)`
  - `RecipeExpansionError(ConfigError)`
  - `InvalidRecipeOutputError(RecipeExpansionError)`
  - `ReservedConfigKeyError(ConfigValidationError)`
  - `TargetImportError(ConfigError)`
  - `TargetInstantiationError(ConfigError)`
  - `RuntimeInjectionError(TargetInstantiationError)`
- Keep `UnsupportedRecipeError` importable for Phase 4 compatibility, but Phase
  5 success paths must not raise it for `_recipe_` blocks or explicit
  `RecipeCatalog` usage.
- Recipe-specific modules may re-export recipe errors from
  `loom.config.recipes.errors`; instantiation modules may re-export
  target/import errors from `loom.config.instantiate.errors`. The canonical class
  definitions stay in `loom.config.errors` so callers can catch all config errors
  from one module.
- Every new error message must include the relevant config path when known.
  Recipe errors also include the recipe name and implementation target when
  available. Target import and constructor errors include the target import path.
  Wrapped recipe, import, and constructor exceptions must be chained with
  `raise ... from exc`.

### Recipe Contracts And Catalogs

- `ConfigRecipe` is a local structural protocol in
  `loom.config.recipes.base`. Do not add it to `loom.protocols`. It requires:

  ```python
  def expand(self) -> Mapping[str, object]: ...
  ```

- `Recipe` is a Pydantic v2 `BaseModel` subclass for typed recipe inputs. It
  sets `model_config = ConfigDict(extra="forbid")` and exposes a clearly failing
  `expand()` method that subclasses override.
- `RecipeImplementation` accepts exactly these forms:
  - a class or factory callable that accepts recipe keyword arguments and returns
    an object with a callable zero-argument `expand()` method;
  - a plain function recipe that accepts recipe keyword arguments and directly
    returns an expanded mapping.
- Do not accept non-callable preconfigured recipe instances in
  `RecipeCatalog.register()`. Register classes, factories, or function-style
  recipes only.
- For every recipe expansion, call the registered implementation with
  pre-resolved keyword arguments. If the call returns a mapping, treat it as a
  function-style expansion. Otherwise, require a callable `expand()` method and
  call it with no arguments.
- Manifest target strings for registered classes and functions are
  `implementation.__module__ + ":" + implementation.__qualname__`. If a callable
  object is accepted as a factory, use its class module and qualname. Tests must
  avoid local closures because their target strings are not stable enough for
  review.
- `RecipeCatalog` has this public instance API:

  ```python
  class RecipeCatalog:
      def register(
          self,
          name: str,
          recipe: RecipeImplementation,
          *,
          replace: bool = False,
      ) -> None: ...

      def get(self, name: str) -> RecipeImplementation: ...
      def names(self) -> tuple[str, ...]: ...
      def items(self) -> tuple[tuple[str, RecipeImplementation], ...]: ...
      def __contains__(self, name: object) -> bool: ...
      def __len__(self) -> int: ...
  ```

- `RecipeCatalog.register(name, recipe, *, replace=False)` validates:
  - `name` is a non-empty string;
  - `recipe` is a class or callable accepted by the recipe implementation
    contract;
  - duplicate names raise `DuplicateRecipeError` unless `replace=True`;
  - replacement preserves the original registration order for an existing name;
  - registering a new name appends it to the deterministic order.
- `RecipeCatalog.get(name)` returns the registered implementation or raises an
  `UnknownRecipeError` with the recipe name.
- `names()` and `items()` return tuples in registration order so callers cannot
  mutate catalog internals.
- The public default registry is a private module-level catalog used only by
  `register_recipe()` and `compose_config(..., recipe_catalog=None)`. Do not add
  a public reset API in Phase 5. Tests should prefer explicit catalogs and use
  unique names or monkeypatch the private default for the one public default path.

### Recipe Expansion

- A recipe block is a mapping with a `_recipe_` key.
- `_recipe_` must be a non-empty string naming a registered recipe.
- Other non-reserved keys in the block are recipe keyword arguments after
  recipe-argument pre-resolution.
- `_target_`, `_args_`, `_partial_`, and `_inject_` are invalid in a recipe
  block and raise `ReservedConfigKeyError` with the offending key path.
- `_recipe_` mappings nested inside recipe argument values are invalid in v0 and
  raise `RecipeExpansionError`; this avoids ambiguous authored parent/child
  ordering before a later fan-out or nested-argument policy exists.
- Unknown recipes raise `UnknownRecipeError`. Invalid recipe names, recipe
  construction failures, recipe validation failures, non-mapping expansion
  results, non-plain expansion results, and nested expansion failures raise
  `RecipeExpansionError` or `InvalidRecipeOutputError` with path/name/target
  context.
- Expansion walks ordinary mappings in insertion order and sequences by index.
  A mapping with `_recipe_` is replaced atomically by one mapping.
- When a recipe expands to a mapping containing nested `_recipe_` blocks, nested
  recipes are expanded recursively before the parent replacement is returned.
  Manifest records are emitted in parent-before-child order. Child paths are
  derived from the parent insertion path plus the child key or index inside the
  expanded mapping.
- Each manifest record is a plain-data dictionary with exactly these required
  fields:
  - `path`: authored config path of the `_recipe_` mapping.
  - `name`: recipe name.
  - `target`: stable implementation target string in `module:qualname` form.
  - `arguments`: plain-data mapping of pre-resolved recipe arguments.
  - `expanded_hash`: deterministic `hash_mapping()` digest of the fully expanded
    replacement mapping after nested recipe expansion and before final
    interpolation.
  - `expanded_path`: path where the expanded mapping was inserted. This equals
    `path` in v0.
  - `loom_version`: current `loom.__version__`.
- `ComposedConfig.recipe_manifest` is a tuple of these record dictionaries.
- `ConfigProvenance.recipe_manifest_count` equals
  `len(ComposedConfig.recipe_manifest)`.
- The config fingerprint payload includes resolved config, source records,
  overrides, schema version, and recipe manifest records.
- A recipe expansion must not mutate the original merged config tree, the
  selected `RecipeCatalog`, or any manifest record after it has been emitted.

### Recipe Argument Pre-Resolution

- Pre-resolution runs after base/overlay merge and dot-path overrides, before
  recipe expansion.
- It resolves interpolation only for recipe argument values and only against the
  composed base/overlay/override config available at that point.
- It must reuse `loom.config.interpolation` or a neighboring config-owned helper
  so OmegaConf does not leak outside `loom.config`.
- It must not call `resolve_interpolation()` on the entire config before recipe
  expansion. Resolve only the selected recipe argument value or argument subtree
  against the full current config context.
- It must support recipe arguments referencing values introduced by the base
  file, overlays, and CLI overrides.
- It must not require interpolation references in non-recipe config or in future
  expanded recipe output to resolve before expansion.
- References to values that do not exist until the recipe's own expansion fail
  during pre-resolution with `ConfigInterpolationError` at the argument path.
- Resolver-style interpolation such as `${env:VAR}`, `${oc.env:VAR}`, and custom
  resolver tokens remain unsupported and should use the existing
  `ConfigInterpolationError` path.

### Target Import Helpers

- `import_target(path, *, config_path=None)` lives in
  `loom.config.instantiate.targets` and supports:
  - `package.module.Class`
  - `package.module:function`
  - `package.module:Class`
- Colon form splits once at `:`. The module part and object part must both be
  non-empty, and the object part must not contain `.` in v0.
- Dotted form imports the module formed by all path segments before the final
  dot and then loads the final attribute. Dotted paths must contain at least one
  module segment and one attribute segment.
- Attribute chains after the target object are deferred; support exactly one
  object attribute after the module path in v0.
- Empty path strings, empty module/object segments, unsupported colon object
  chains, module import failures, and missing attributes raise
  `TargetImportError`.
- `import_target()` returns the imported object without enforcing callability.
  `instantiate()` raises `TargetInstantiationError` if a target block resolves to
  a non-callable object.

### Recursive Instantiation

- `instantiate()` recursively processes:
  - mappings with `_target_` as target construction blocks;
  - mappings without `_target_` as ordinary dictionaries with recursively
    instantiated values;
  - non-string sequences as lists with recursively instantiated items;
  - scalar values as themselves.
- In a target block:
  - `_target_` is required and must be a non-empty string.
  - `_args_`, when present, must be a non-string sequence and is recursively
    instantiated before being passed as positional arguments.
  - `_partial_`, when present, must be a boolean. If true, return
    `functools.partial(target, *args, **kwargs)` without invoking the target.
  - `_inject_`, when present, must be a mapping of constructor keyword names to
    runtime dependency keys. Both names and keys must be non-empty strings.
  - non-reserved keys are recursively instantiated and passed as keyword
    arguments.
- Validation of `_target_`, `_args_`, `_partial_`, and `_inject_` value types
  happens before importing the target or invoking nested constructors at that
  block.
- Nested `_target_` blocks inside `_args_`, keyword values, mappings, and
  sequences are instantiated before the parent target is called.
- Runtime injection:
  - `runtime=None` is treated as an empty mapping.
  - a non-`None` `runtime` value must be a mapping or fail with
    `RuntimeInjectionError`;
  - each `_inject_` runtime key must exist in the runtime mapping;
  - injected keyword names must not duplicate authored keyword names;
  - injected values are passed through unchanged and are not plain-data checked;
  - injected values are not recorded in resolved config, recipe manifest,
    provenance, or fingerprints.
- Reserved-key misuse:
  - `_recipe_` anywhere in `instantiate()` input raises `ReservedConfigKeyError`
    with a message directing callers to compose configs before instantiation;
  - a mapping containing both `_target_` and `_recipe_` fails because `_recipe_`
    is never valid input to `instantiate()`;
  - `_args_`, `_partial_`, or `_inject_` in a mapping without `_target_` fails
    as `ReservedConfigKeyError`;
  - invalid `_args_`, `_partial_`, or `_inject_` value types fail before target
    import or constructor invocation.
- Constructor failures are wrapped in `TargetInstantiationError` while
  preserving the original exception as the cause.

### Composition Behavior

- `compose_config` continues to write no files.
- Base loading, overlays, recursive merge, overrides, and existing config source
  provenance remain Phase 4 behavior unless recipe support requires a narrow
  adaptation.
- The unsupported `_recipe_` detection step is removed from the normal success
  path and replaced by recipe expansion.
- Top-level validation still runs after recipe expansion and final
  interpolation.
- Redaction still runs after validation and does not mutate `resolved`.
- If a config has no recipes, `recipe_manifest` is `()` and behavior remains
  compatible with Phase 4 except for accepting explicit recipe catalogs.
- If a config has recipes, expansion happens before final interpolation and the
  final `resolved` output contains no `_recipe_` keys.
- `resolved_fingerprint` in `ConfigProvenance` remains the hash of the validated
  resolved config. The top-level config `fingerprint` additionally hashes the
  recipe manifest records so a recipe implementation/name/argument/expansion
  change affects the composed fingerprint even when resolved config happens to
  match.
- `_target_` blocks remain plain data during composition. `compose_config` must
  not import targets or instantiate objects.

### Import Boundaries

- `import loom` must not import `loom.config`, `omegaconf`, `pydantic`, `yaml`,
  pipeline, stores, CLI, plugins, or downstream project packages.
- `import loom.config` may import the hard config dependencies introduced in
  Phase 4.
- `loom.config` may import `loom.serialization`, `loom.fingerprints`,
  `loom.errors`, and package metadata for `loom.__version__`.
- `loom.config` must not import pipeline execution internals, stores, CLI,
  plugin discovery, or downstream project packages except through explicit
  trusted imports requested by recipe expansion or `instantiate()`.

## Design Impact

- Maintainability: recipe behavior is isolated under `loom.config.recipes`, and
  target construction is isolated under `loom.config.instantiate`. `compose.py`
  remains orchestration rather than a monolithic implementation of registries,
  importlib, and constructor logic.
- Extensibility: explicit `RecipeCatalog` objects leave room for later
  entry-point loading into supplied catalogs without changing recipe expansion
  semantics. A Pydantic-backed `Recipe` base gives typed recipe inputs without
  forcing all downstream recipes into nominal inheritance.
- Domain neutrality: `loom` provides the generic registry, expansion,
  provenance, import, and construction mechanics only. It provides no built-in
  domain recipes or target classes.
- Source-tree boundaries: config may depend on serialization, fingerprints,
  errors, and config dependencies. It must not depend on pipeline runners,
  stores, plugins, CLI, or downstream packages.

## Future Compatibility

- Recipe manifest records include both `path` and `expanded_path` even though
  they match in v0, preserving room for later recipe fan-out or relocation
  semantics.
- Explicit catalogs can be populated later by plugin/entry-point helpers without
  turning import-time discovery into a side effect.
- Keeping runtime injection outside resolved config and fingerprints preserves a
  clean boundary between authored reproducible config and ephemeral in-process
  services.
- Target import helpers are narrow but reusable by future pipeline runner code
  when Phase 9 instantiates stage targets.
- `instantiate()` supports generic object graphs now, while Phase 6 and Phase 9
  can still keep stage constructor kwargs out of the v0 stage contract.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Entry-point recipe discovery in Phase 5 | Plugin discovery is explicitly out of scope and belongs to the deferred plugin layer. |
| Import sandbox or allow-list mode | The v0 plan explicitly treats authored configs as trusted project code. |
| Keep rejecting `_recipe_` blocks | Phase 5 acceptance criteria require deterministic recipe expansion and manifest records. |
| Instantiate `_target_` blocks during `compose_config` | Composition must remain side-effect-free and pipeline parsing/execution are later phases. |
| Make every recipe subclass `Recipe` | Structural recipes and plain factories keep downstream extension lightweight; `Recipe` is the typed Pydantic path, not the only path. |
| Allow recipe expansion to return sequences and splice fan-out into lists | Static fan-out semantics need stage naming and graph provenance decisions that are not in Phase 5 scope. |
| Serialize `_inject_` runtime objects into resolved config | Runtime injections are process-local dependencies and may be non-serializable; resolved config must remain authored/plain-data state. |
| Use only a global default recipe registry | Explicit catalogs are required for deterministic setup, tests, and future plugin loading. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Public default recipe registry exists as a convenience | The documented `register_recipe()` API needs a simple default path for small projects. | Revisit if global registry state causes downstream test leakage or plugin setup ambiguity. |
| Recipe expansion returns mappings only | Keeps v0 deterministic and avoids unplanned stage fan-out semantics. | Revisit when a future phase defines sequence splicing, generated stage names, and graph provenance. |
| Target import helper supports only one object attribute after the module path | Covers documented dotted and colon forms while keeping errors reviewable. | Revisit if downstream users need nested class or attribute-chain targets. |
| No sandbox or allow-list mode for target imports | Accepted by the v0 trusted-config plan. | Revisit if users need to run untrusted configs or central policy enforcement. |
| Runtime injection is not represented in fingerprints | Injected objects are ephemeral runtime dependencies, not authored config. | Revisit if injected services are shown to affect reproducible outputs and need explicit fingerprint policy. |

## Reviewability

- Expected PR size and shape: one focused config PR adding recipe and
  instantiation subpackages, updating config API/composition/provenance, and
  adding package, unit, contract, and integration tests. No pipeline/store/runner
  implementation should appear.
- Files and areas to inspect:
  - `src/loom/config/api.py` and `__init__.py` for public API changes.
  - `src/loom/config/compose.py` for composition-order changes.
  - `src/loom/config/provenance.py` for recipe manifest count and fingerprint
    payload updates.
  - `src/loom/config/errors.py` and any local recipe/instantiate error modules.
  - `src/loom/config/recipes/` for recipe contracts, catalog behavior, and
    expansion.
  - `src/loom/config/instantiate/` for target import, recursive construction,
    partials, and injection.
  - Package import-boundary tests for cheap top-level imports.
  - Unit, contract, and integration tests for all Phase 5 acceptance criteria.
- Scope-control checks:
  - No `src/loom/pipeline` implementation changes unless a package import test
    needs a narrow import-boundary assertion.
  - No run-store, artifact-store, runner, selector, graph, or CLI behavior.
  - No entry-point/plugin discovery.
  - No domain-specific recipes or targets in runtime code.
  - No top-level `loom` config re-exports.

## Files And Areas To Inspect

- `src/loom/config/api.py`
- `src/loom/config/__init__.py`
- `src/loom/config/compose.py`
- `src/loom/config/interpolation.py`
- `src/loom/config/validation.py`
- `src/loom/config/provenance.py`
- `src/loom/config/errors.py`
- New `src/loom/config/recipes/` modules.
- New `src/loom/config/instantiate/` modules.
- `src/loom/serialization/plain.py` and `src/loom/fingerprints.py` for
  plain-data normalization and deterministic hashes.
- `src/loom/__init__.py` only to confirm it remains unchanged.
- `tests/package/test_config_api.py` and
  `tests/package/test_import_boundaries.py`.
- Existing and new tests under `tests/unit/loom/config/`.
- New contract tests under `tests/contracts/` for recipe extension behavior.
- Integration tests under `tests/integration/config/`.
- Source references:
  - `docs/implementation-plans/implementation-plan-v0.md`, especially Phase 5,
    deferred features, and overall test plan.
  - `docs/structure.md` sections "Configuration", "Import and Dependency
    Shape", "Runtime Dependency Policy", "What Stays Out of loom", and
    "Test Layout".
  - `docs/features/config.md` sections 5.6, 5.7, 6.3, 7, 11, 12, 15, 16, and
    18.
  - `docs/features/errors.md` for path-aware config, recipe, and target errors.
  - `docs/features/protocols.md` section 12.5 for local recipe protocols.
  - `docs/features/testing.md` for suite ownership and domain-neutral tests.
  - `docs/features/plugins.md` only for deferred entry-point and explicit
    catalog boundaries.

## Implementation Steps

1. Update public API and errors.
   - Add `Recipe`, `RecipeCatalog`, and real `register_recipe()` exports.
   - Replace the `instantiate()` stub with the public wrapper.
   - Add `RecipeRegistrationError`, `DuplicateRecipeError`,
     `UnknownRecipeError`, `RecipeExpansionError`, `InvalidRecipeOutputError`,
     `ReservedConfigKeyError`, `TargetImportError`,
     `TargetInstantiationError`, and `RuntimeInjectionError`.
   - Update package tests for new imports and signatures.

2. Add recipe contracts and catalog behavior.
   - Add `ConfigRecipe`, `Recipe`, recipe implementation typing, target-string
     helpers, and `RecipeCatalog`.
   - Implement duplicate detection, unknown lookup errors, explicit replacement,
     replacement-order preservation, deterministic `names()`/`items()`, and
     default registry registration.
   - Tests: recipe catalog unit tests and recipe contract tests.

3. Add recipe manifest record helpers.
   - Define a frozen internal record type or helper that emits the exact
     plain-data manifest dictionary shape.
   - Compute `expanded_hash` with `hash_mapping()` over fully expanded recipe
     output after nested recipe expansion and before final interpolation.
   - Include `loom.__version__` in records.
   - Tests: record shape, hash determinism, and plain-data validation.

4. Implement recipe argument pre-resolution.
   - Add a config-owned helper that resolves interpolation for recipe arguments
     against the composed base/overlay/override config.
   - Resolve only recipe argument values, not the whole config, before expansion.
   - Preserve unsupported resolver behavior and path-aware
     `ConfigInterpolationError`.
   - Tests: args reference base, overlay, and override values; unresolved
     forward references fail during argument pre-resolution.

5. Implement recursive recipe expansion.
   - Walk mappings/sequences deterministically.
   - Expand `_recipe_` blocks through the selected catalog.
   - Validate reserved-key misuse in recipe blocks and ambiguous `_recipe_`
     mappings inside recipe arguments.
   - Recursively expand nested recipes returned by recipes using parent-before
     child manifest order.
   - Return expanded config plus deterministic manifest records.
   - Tests: nested recipes, unknown recipes, recipe construction errors,
     non-mapping/non-plain outputs, path-aware errors, and deterministic record
     order.

6. Wire recipe expansion into `compose_config`.
   - Accept explicit `RecipeCatalog` values and use the default catalog when
     omitted.
   - Replace unsupported recipe rejection with pre-resolution, expansion, final
     interpolation, validation, redaction, provenance, manifest count, and
     fingerprint updates.
   - Keep no-recipe configs compatible with Phase 4.
   - Tests: existing compose tests updated from rejection to expansion where
     appropriate.

7. Add target import helpers.
   - Implement dotted and colon import forms with clear distinction between
     invalid path syntax, module import failure, and missing attributes.
   - Reject colon object parts containing dots and dotted forms without both a
     module and final attribute.
   - Tests: import class/function targets from domain-neutral test support
     modules and assert path-aware failures.

8. Implement recursive instantiation.
   - Add mapping/sequence recursion, target construction, `_args_`, `_partial_`,
     `_inject_`, and reserved-key validation.
   - Validate reserved directives before importing a target; recursively
     instantiate nested args/kwargs before invoking the parent target.
   - Ensure constructor errors preserve causes and include config path and target
     path.
   - Tests: nested object graphs, positional args, partials, injected runtime
     values, duplicate injection/authored kwargs, missing runtime keys, and
     reserved-key misuse.

9. Update import-boundary and deferred-stub tests.
   - Remove expectations that `register_recipe()` and `instantiate()` are
     unsupported.
   - Keep `import loom` cheap and free of config/hard dependency imports.
   - Assert config imports do not load pipeline, stores, CLI, plugins, or
     downstream project modules before explicit target import/expansion calls.

10. Run targeted checks during implementation.
    - Use focused pytest commands while iterating.
    - Run package, unit, contract, and integration suite targets before executor
      handoff when feasible.
    - Leave `make validate-pr` and `make test-summary` for PR preparation.

## Test Plan

### Package Suite

- Status: required.
- Existing suite target: `make test-package`.
- Expected paths:
  - `tests/package/test_config_api.py`
  - `tests/package/test_import.py`
  - `tests/package/test_import_boundaries.py`
  - `tests/package/test_public_api.py`
- Required assertions:
  - `import loom` succeeds and does not eagerly import `loom.config`,
    `omegaconf`, `pydantic`, `yaml`, `loom.pipeline`, stores, CLI, plugins, or
    downstream project packages.
  - `from loom.config import ConfigError, ComposedConfig, Recipe,
    RecipeCatalog, compose_config, instantiate, register_recipe` works.
  - `compose_config` keeps `config_path, overlays=(), overrides=(),
    recipe_catalog=None` in that order.
  - `instantiate` has the documented `value, *, runtime=None` public shape.
  - `register_recipe` has the documented `name, recipe, *, replace=False`
    public shape.
  - `register_recipe` and `instantiate` no longer raise Phase 5 unsupported
    stub messages for valid inputs.
  - `loom.__all__` remains unchanged and does not include config exports.

### Unit Suite

- Status: required.
- Existing suite target: `make test-unit`.
- Expected paths:
  - `tests/unit/loom/config/test_config_errors.py`
  - `tests/unit/loom/config/test_compose.py`
  - `tests/unit/loom/config/test_config_provenance.py`
  - `tests/unit/loom/config/test_validation.py`
  - `tests/unit/loom/config/recipes/test_catalog.py`
  - `tests/unit/loom/config/recipes/test_expansion.py`
  - `tests/unit/loom/config/recipes/test_manifest.py`
  - `tests/unit/loom/config/instantiate/test_targets.py`
  - `tests/unit/loom/config/instantiate/test_recursive.py`
  - `tests/unit/loom/config/instantiate/test_injection.py`
- Required assertions:
  - New concrete errors inherit from `ConfigError` and preserve wrapped causes.
  - Error modules expose the exact Phase 5 error classes named in this plan, and
    `UnsupportedRecipeError` remains importable but is no longer raised for valid
    recipe-capable composition.
  - `Recipe` validates typed inputs through Pydantic and rejects unknown fields
    by default.
  - Structural recipe implementations do not need to subclass `Recipe`.
  - `RecipeCatalog` registers, looks up, iterates deterministically, rejects
    duplicate names, supports explicit replacement without moving an existing
    name's order, rejects invalid names, returns immutable `names()`/`items()`
    tuples, and reports unknown recipes.
  - The public default registry path through `register_recipe()` is isolated in
    tests and does not leak state across tests.
  - Recipe argument pre-resolution can reference base, overlay, and override
    values without forcing unrelated non-recipe interpolation to resolve early.
  - Recipe argument references to values produced only by the recipe expansion
    fail during pre-resolution with an argument-path error.
  - Recipe blocks reject `_target_`, `_args_`, `_partial_`, and `_inject_` as
    ambiguous reserved keys.
  - `_recipe_` mappings nested inside recipe argument values fail as ambiguous
    recipe nesting in v0.
  - Recipe expansion replaces `_recipe_` mappings, recursively expands nested
    recipes, returns no `_recipe_` keys in final resolved config, and records
    deterministic manifest records with `data`, `data.child`, and
    `pipeline.stages[0]` style paths.
  - Recipe expansion wraps recipe construction, validation, non-mapping output,
    non-plain output, unknown recipe, and nested expansion errors with useful
    path/name/target context.
  - Expanded blocks participate in final interpolation after expansion.
  - Config fingerprints change when recipe arguments, recipe output, manifest
    records, or expanded resolved config change.
  - Target import supports `package.module.Class`, `package.module:function`,
    and `package.module:Class`.
  - Target import rejects empty segments and unsupported attribute chains; errors
    include target path and config path when available.
  - `instantiate()` recursively constructs nested mappings/sequences, preserves
    scalars, passes keyword arguments, passes `_args_` positional arguments,
    returns `functools.partial` for `_partial_=true`, and does not call the
    target in partial mode.
  - `_inject_` pulls runtime values by key, rejects missing runtime keys,
    rejects duplicate injected/authored keyword names, and does not plain-data
    check injected objects.
  - Reserved-key misuse in `instantiate()` fails before import or constructor
    invocation.
  - `_recipe_` anywhere in `instantiate()` input fails with guidance to call
    `compose_config()` before instantiation.
  - Constructor errors are wrapped with original causes preserved.
  - `compose_config` writes no files.

### Contract Suite

- Status: required.
- Existing suite target: `make test-contract`.
- Expected paths:
  - `tests/contracts/test_recipe_contract.py`
  - existing Phase 3 contract tests under `tests/contracts/`
- Required assertions:
  - A downstream-style dataclass recipe class with `expand()` can be registered
    without inheriting from `Recipe`.
  - A downstream-style `Recipe` subclass receives typed Pydantic input
    validation and expands through the same catalog path.
  - A function-style recipe accepted by the catalog expands through the same
    behavior as class-backed recipes.
  - Contract tests remain domain-neutral and use synthetic support classes only.
  - Existing codec and data-source contract tests remain green.

### Integration Suite

- Status: required.
- Existing suite target: `make test-integration`.
- Expected paths:
  - `tests/integration/config/test_compose_config.py`
  - `tests/integration/config/test_compose_recipes.py`
  - optionally `tests/integration/config/test_instantiate_config.py` if a
    public cross-module instantiation flow needs integration coverage
- Required assertions:
  - A base YAML file plus overlays and overrides can select a registered recipe
    from an explicit `RecipeCatalog`.
  - Recipe args reference values introduced by base files, overlays, and
    overrides.
  - A recipe output containing interpolation references resolves correctly in
    the final interpolation pass.
  - Nested recipes expand deterministically and produce a useful manifest with
    paths, names, targets, arguments, expanded hashes, expanded paths, and loom
    version; nested recipe records appear parent before child.
  - Redacted output still masks secret-like values after recipe expansion.
  - Provenance records the correct recipe manifest count and fingerprints change
    when recipe-related inputs or manifest records change.
  - Unknown recipes in realistic config trees fail clearly without partial
    expansion being returned.
  - `compose_config` does not instantiate `_target_` blocks and creates no files
    beside authored configs.
  - `instantiate()` can construct a synthetic domain-neutral nested object graph
    from a composed config subtree when called explicitly.

### E2E Suite

- Status: deferred for this phase.
- Existing suite target: `make test-e2e`.
- Expected path status: `tests/e2e` may remain absent or contain no Phase 5
  tests.
- Required assertions or deferral reason:
  - Phase 5 has no functional CLI, pipeline parser, runner, run store, artifact
    store, or complete user-visible workflow.
  - Full e2e coverage begins after pipeline specs, stores, planning, and local
    execution exist.
  - PR preparation should run `make test-e2e` if the suite exists and document
    the result; otherwise the harness may report `not present`.

### Opt-In Suites

- Status: deferred for this phase.
- Markers affected: `slow`, `slurm`, `network`, and `optional_dependency`.
- Required assertions or deferral reason:
  - No network, SLURM, subprocess, remote store, optional dependency, or slow
    external-service behavior is in scope.
  - Do not add tests marked `slow`, `slurm`, `network`, or
    `optional_dependency`.
  - Plugin/entry-point discovery tests are deferred with the plugin layer.

## Risks

- Recipe argument pre-resolution can accidentally force final interpolation too
  early. Tests must cover recipe args that resolve before expansion and recipe
  outputs that resolve only after expansion.
- The default recipe registry can leak state between tests. Tests must prefer
  explicit `RecipeCatalog` instances and isolate the one public default-registry
  path.
- Target imports execute trusted project imports. The implementation must keep
  this out of `compose_config()` target blocks and only perform it during recipe
  construction/expansion or explicit `instantiate()` calls.
- Generic `instantiate()` could be misread as the Phase 9 stage-construction
  policy. Docs, errors, and tests should keep pipeline stage parsing and runner
  behavior out of this phase.
- Recipe manifest hashes and final config fingerprints can diverge if hashing
  uses different normalized data than `resolved`. Use plain-data normalized
  mappings and existing fingerprint helpers consistently.
- Local dummy target classes/functions used in tests may not produce importable
  target strings if defined inside test functions. Put reusable dummy targets in
  top-level test modules or `tests/support`.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-contract
make test-integration
uv run pytest tests/unit/loom/config/recipes tests/unit/loom/config/instantiate tests/integration/config tests/contracts/test_recipe_contract.py -m "not slow and not slurm and not network and not optional_dependency"
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - public API and config errors;
  - recipe contracts/catalog/default registry;
  - recipe manifest records and expansion;
  - compose integration and fingerprint/provenance updates;
  - target import helpers;
  - recursive instantiation and injection;
  - package/unit/contract/integration tests.
- Tests to run with each slice:
  - package tests after public API changes;
  - recipe unit and contract tests after catalog/expansion changes;
  - compose unit and integration tests after wiring expansion into
    `compose_config`;
  - instantiation unit tests after target import/recursive construction changes;
  - existing contract tests before handoff to ensure Phase 3 extension contracts
    remain green.
- Decisions the executor must not revisit:
  - no plugin or entry-point discovery;
  - no sandbox or allow-list mode;
  - no pipeline parsing, stores, runners, or stage execution;
  - no config writes;
  - no static fan-out sequence splicing;
  - no nested `_recipe_` expansion inside recipe argument values before invoking
    the parent recipe;
  - no top-level `loom` config exports;
  - no serialization of runtime injection objects.
- Conditions that require stopping for the manager:
  - recipe argument pre-resolution cannot be implemented without breaking Phase
    4 interpolation guarantees;
  - implementing recipe manifests requires changing the public
    `ComposedConfig` field shape;
  - target import support appears to require plugin discovery or allow-list
    policy;
  - package import-boundary tests require top-level config imports;
  - fulfilling acceptance criteria appears to require Phase 6 or later pipeline
    behavior.

## Refinement And Review Budget Status

- Plan expansion/refinement: used by this final expanded-plan pass. Do not run
  another automated plan expansion/refinement pass unless the manager explicitly
  reopens the budget.
- Phase implementation refinement: used on 2026-05-03 by the single bounded
  `loom_phase_refiner` pass. Summary: fixed Phase 5 validation/type issues,
  simplified instantiate subpackage parent mutation, preserved the package-level
  `loom.config.instantiate` callable across submodule import/reload order,
  normalized non-string sequence instantiation to lists, tightened nested recipe
  argument rejection before interpolation, and added focused import-order,
  reserved-key, override pre-resolution, manifest fingerprint, and live-API
  regression coverage.
- PR review: unused.

## Completion Notes

- Draft plan: created by `loom_phase_planner` and committed as
  `fd6b04cae25432cd57a06e8a7543d9c8300e535a`.
- Final expanded plan: completed in this pass and ready for
  `loom_phase_executor` handoff after the `plan:` commit.
- Implementation summary: executor commits added recipe contracts/catalogs,
  recursive recipe expansion with deterministic manifest records, recipe-aware
  config composition and fingerprinting, target import helpers, recursive
  explicit instantiation with `_args_`, `_partial_`, and `_inject_`, and
  package/unit/contract/integration coverage.
- Implementation validation reviewed: current diff against `develop`, phase
  commits `92973fd` and `49d6aa2`, manager handoff notes, and an initial
  targeted pytest run. The initial targeted run failed only because
  `tests/unit/loom/test_deferred_stubs.py` still expected Phase 5 APIs to be
  unsupported stubs.
- Refinement scope: blocking issues caused by Phase 5 implementation/tests and
  phase-scoped coverage gaps only. No Phase 6+ pipeline parsing, runner,
  stores, plugin discovery, entry-point loading, or PR preparation work was
  performed.
- Refinement summary: replaced stale deferred-stub expectations with live API
  coverage, removed redundant parent mutation from
  `loom.config.instantiate.__init__`, kept the defensive package-level
  `__setattr__` guard because the public callable and same-named subpackage
  otherwise conflict after submodule imports, made non-string sequences
  instantiate as lists per contract, rejected nested recipe blocks inside recipe
  arguments before interpolation can mask the intended error, corrected lint and
  Pyright issues in the new Phase 5 code/tests, and added regression coverage
  for import order, all reserved recipe directive keys, override-backed recipe
  argument pre-resolution, recipe manifest fingerprint contribution, and
  `UnknownRecipeError` inheritance.
- Refinement validation:
  - `make validate-pr`: passed after installing worktree dependencies with
    `uv sync --all-groups`; includes `ruff check .`, `pyright`, default pytest
    (`221 passed`), and `uv build`.
  - `make test-package` equivalent via harness: `14 passed`.
  - `make test-unit` equivalent via harness: `189 passed`.
  - `make test-contract` equivalent via harness: `9 passed`.
  - `make test-integration` equivalent via harness: `9 passed`.
  - Focused pytest before full validation:
    `tests/package/test_config_api.py tests/unit/loom/test_deferred_stubs.py tests/unit/loom/config/instantiate tests/unit/loom/config/recipes tests/unit/loom/config/test_config_provenance.py tests/unit/loom/config/test_config_errors.py tests/integration/config/test_compose_config.py`
    passed with `49 passed`.
- PR preparation: completed on 2026-05-03. Final diff against `develop`
  was reviewed for Phase 5 scope and matched the expanded plan: recipe
  contracts/catalogs, recursive recipe expansion and manifests, config
  fingerprint/provenance integration, target import helpers, explicit recursive
  instantiation, and package/unit/contract/integration coverage. No Phase 6+
  pipeline parsing, runner, store, plugin discovery, entry-point loading, or
  domain behavior was found in the final diff.
- Final PR-prep validation:
  - `make validate-pr`: passed after rerunning with approved access to the
    existing `uv` cache outside the workspace; includes `ruff check .`,
    `pyright` with 0 errors, default pytest with `221 passed`, and `uv build`
    producing source and wheel distributions.
  - `make test-summary`: passed after rerunning with approved access to the
    existing `uv` cache outside the workspace; wrote `build/test-summary.md`
    with package `14 passed`, unit `189 passed`, contract `9 passed`,
    integration `9 passed`, and e2e `not present`.
- PR body prepared at
  `docs/phases/add-recipes-instantiation-pr-body.md`.
- PR creation status: pending branch push and GitHub PR creation from this
  prepared body.
- Accepted risks and follow-ups:
  - The public default recipe registry remains a v0 convenience; explicit
    catalogs are preferred for deterministic tests and future plugin loading.
  - Recipe expansion returns mappings only; static sequence fan-out remains
    deferred until a later phase defines splicing, generated names, and graph
    provenance.
  - Target imports remain trusted project-code imports with no sandbox or
    allow-list mode in v0.
  - Generic `instantiate()` is available for explicit object graphs, but Phase
    6 and Phase 9 still own pipeline parsing and stage construction policy.
  - Runtime injection values are intentionally excluded from resolved config,
    recipe manifests, provenance, and fingerprints.
- Budget/status evidence: plan expansion/refinement used; phase implementation
  refinement used by commit `f88d16a`; PR review budget remains unused.
- Remaining blockers: none known after PR preparation.

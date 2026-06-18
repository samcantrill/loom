# Phase 4 Expanded Plan: Config Composition

## Metadata

- Status: final expanded plan.
- Branch: `codex/add-config-composition`.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-config-composition`.
- Expanded plan path: `docs/roadmap/stage-0/phases/add-config-composition.md`.
- Full plan: `docs/roadmap/stage-0/implementation-plan.md`.
- Source phase: `Phase 4 - Config Composition`.
- Base branch: local `develop` at `066e210ab915ff35e13bb194a9a9d75d6a405804` (`feat: updated prompts for workflow`).
- Target branch: `develop`.
- Plan quality gate: passed on 2026-05-03 by `loom_plan_reviewer` confirmation review; no remaining blockers are recorded in the canonical v0 plan.
- Plan quality gate loop budget: initial plan review used, automated plan refinement pass used, confirmation review used. Do not start another plan-quality review loop for this phase unless the manager explicitly instructs it.
- Setup limitations: `gh auth status` reports the configured GitHub token for `samcantrill` is invalid, so GitHub PR inspection, push, and PR creation are unavailable until authentication is refreshed. Manager preflight recorded that sandboxed network access cannot resolve GitHub and that escalated remote checks were used previously. This final plan uses the manager-approved local `develop` base.
- Worktree creation note: the first sandboxed `git worktree add` attempt could not create the nested `codex/add-config-composition` ref; the approved escalated rerun created the branch and worktree successfully. This is an environment limitation, not a product blocker.
- Prior phase state: Phase 1, Phase 2, and Phase 3 are recorded as merged. Phase 4 is the next pending phase.
- Setup blockers: none for local planning. Remote PR inspection remains unavailable until GitHub authentication is refreshed.
- Blockers: none.

## Objective

Implement trusted YAML config composition for `loom` without object construction side effects. This phase turns the Phase 1 `loom.config.compose_config` stub into the public composition entrypoint, adds the hard config runtime dependencies, and returns a fully plain-data `ComposedConfig` containing resolved config, redacted config, config provenance, an empty recipe manifest, and a deterministic fingerprint.

The implementation must compose base config, overlays, and dot-path overrides; resolve interpolation through a local wrapper; validate minimal top-level `loom`-owned fields; reject `_recipe_` blocks clearly until Phase 5; redact secret-like keys recursively; and record enough source provenance that source input changes affect the final fingerprint. Composition itself must not write files, instantiate `_target_` objects, parse pipeline specs, create run directories, or perform runner/store behavior.

## Full-Plan Context

Phase 1 created import-safe subsystem skeletons and the `loom.config` stubs. Phase 2 added plain-data serialization, provenance models, and deterministic fingerprint helpers. Phase 3 added local I/O sources/codecs but did not add config behavior or runtime dependencies.

Phase 4 is the first phase that adds hard runtime dependencies: `omegaconf>=2.3`, `pydantic>=2`, and `pyyaml>=6`. These dependencies are intentionally hard after this phase to keep one tested v0 installation shape. The implementation must still preserve cheap top-level imports: `import loom` must not import `loom.config`, OmegaConf, Pydantic, PyYAML, pipeline runners, CLI, stores, plugins, or downstream project packages.

Later phases depend on this phase as follows:

- Phase 5 replaces the unsupported `_recipe_` bridge with deterministic recipe expansion, recipe provenance records, target import helpers, recursive `_target_` instantiation, and runtime dependency injection.
- Phase 6 parses the resolved `pipeline` mapping into static pipeline specs. Phase 4 validates only that required top-level fields exist and leaves pipeline-specific schema validation to Phase 6.
- Phase 7 and Phase 9 persist resolved and redacted config snapshots through run stores and runners. Phase 4 returns in-memory data and writes no files.
- Phase 8 and Phase 9 consume config fingerprints and resolved config values for planning/resume; Phase 4 only computes the whole composed-config fingerprint required by the source phase.

Future-phase and deferred work that must remain out of scope includes recipes, `_target_` object construction, pipeline specs, run stores, config persistence, sandboxing, allow-list mode, Hydra defaults, include graphs, list patch operators, custom expression languages, and domain-specific config semantics.

## Source Phase Summary

From `docs/roadmap/stage-0/implementation-plan.md`, Phase 4 is `Status: pending` with branch `codex/add-config-composition` and PR `pending`.

- Goal: implement trusted YAML config composition and provenance without object construction side effects.
- Required scope: add hard runtime config dependencies; add config loading, recursive merge, dot-path overrides, interpolation, validation, redaction, config provenance, and public `compose_config`; return `ComposedConfig` with resolved config, redacted config, provenance, empty `recipe_manifest`, and fingerprint.
- Required checkpoints:
  - Add dependency entries for `omegaconf>=2.3`, `pydantic>=2`, and `pyyaml>=6`.
  - Split config behavior into loading, merge, overrides, interpolation, validation, redaction, provenance, and compose modules.
  - Use recursive mapping merge, scalar replacement, list replacement, and explicit `null`; do not add list patch operators.
  - Parse override booleans, nulls, integers, floats, JSON arrays/objects, and strings, then apply through dot paths with path-aware errors.
  - Wrap interpolation behind a local API so non-config modules do not become OmegaConf-specific.
  - Redact secret-like keys such as `token`, `secret`, `password`, `api_key`, `credential`, and `private_key` recursively.
  - Reject `_recipe_` blocks with a clear unsupported-recipe `ConfigError` until Phase 5, and return an empty recipe manifest when no recipes are present.
  - Make config composition write nothing by itself.
- Acceptance criteria:
  - Base config and overlays compose in order.
  - Mapping/scalar/list/null merge semantics match the plan.
  - Overrides parse supported scalar and structured values.
  - Interpolation resolves through a wrapped API and reports unresolved values clearly.
  - Required top-level fields are validated.
  - `_recipe_` keys fail clearly as unsupported until Phase 5.
  - Secret-like keys are redacted recursively.
  - Config provenance and fingerprints change when source inputs change.
  - Composition writes no files.

## Current Source And Harness Findings

- `src/loom/config/__init__.py` currently contains Phase 1 unsupported stubs for `compose_config`, `instantiate`, and `register_recipe`, all rooted in `ConfigError`.
- `src/loom/errors.py` already defines the broad `ConfigError` root. Phase 4 concrete errors should live in `loom.config.errors` and inherit from `ConfigError`.
- `src/loom/serialization/plain.py` provides `PlainData`, `ensure_plain_data`, and `to_plain_data`; config outputs should normalize to plain data through these helpers before hashing or returning public data.
- `src/loom/serialization/json.py` and `src/loom/fingerprints.py` provide stable JSON hashing through `hash_mapping`; config fingerprints should reuse these helpers and must not use Python `hash()`.
- `src/loom/provenance` contains generic provenance models, but config-specific provenance is not implemented. `loom.config.provenance` should own detailed config source/override provenance and keep top-level provenance aggregation out of scope.
- `pyproject.toml` has an empty runtime `dependencies` list. `uv.lock` exists and must be updated when the implementation adds hard config dependencies.
- Existing package import-boundary tests assert that `import loom` does not import config, pipeline, or CLI, and that serialization does not import I/O. Phase 4 must extend these guardrails for config and hard dependencies without changing top-level exports.
- `tests/unit/loom/config/` does not exist yet. Config unit tests should mirror the new `src/loom/config/` modules.
- `tests/contracts` and `tests/integration` exist from Phase 3. Phase 4 should add integration coverage for complete `compose_config` flows; contract suite coverage is deferred because this phase introduces no structural extension protocol.
- The Make harness exposes `make test-package`, `make test-unit`, `make test-contract`, `make test-integration`, `make test-e2e`, `make validate-pr`, and `make test-summary`. Missing suite directories are reported as `not present`.

## In-Scope Work

- Add hard runtime dependencies in `pyproject.toml` and update `uv.lock`:
  - `omegaconf>=2.3`
  - `pydantic>=2`
  - `pyyaml>=6`
- Replace the `compose_config` stub with a real public API and keep `instantiate` and `register_recipe` as explicit unsupported Phase 5 stubs.
- Add a frozen slots `ComposedConfig` value object with:
  - `resolved: dict[str, PlainData]`
  - `redacted: dict[str, PlainData]`
  - `provenance: ConfigProvenance`
  - `recipe_manifest: tuple[dict[str, PlainData], ...]`
  - `fingerprint: Fingerprint`
- Add config modules aligned with `docs/structure.md`:
  - `src/loom/config/api.py`
  - `src/loom/config/compose.py`
  - `src/loom/config/load.py`
  - `src/loom/config/merge.py`
  - `src/loom/config/overrides.py`
  - `src/loom/config/interpolation.py`
  - `src/loom/config/validation.py`
  - `src/loom/config/redaction.py`
  - `src/loom/config/provenance.py`
  - `src/loom/config/errors.py`
- Load YAML files by reading raw bytes, digesting those bytes before parsing, decoding as UTF-8, and using `yaml.safe_load` or `yaml.load(..., Loader=yaml.SafeLoader)` only. Do not use `FullLoader`, `UnsafeLoader`, arbitrary YAML object tags, or Python object construction.
- Compose one base config plus zero or more overlay config files in order.
- Apply dot-path overrides after overlays.
- Support override forms `path=value` for existing paths and `+path=value` for new paths. Path segments are dot-separated mapping keys; list indexing, key escaping, and path segments containing literal dots are deferred. `+path=value` creates missing intermediate mapping parents and fails if it encounters an existing non-mapping parent or if the final path already exists.
- Parse override values as exact lowercase booleans, exact lowercase `null`, decimal integers, finite floats, strict JSON arrays/objects, and fallback strings, then validate parsed values as plain data.
- Resolve interpolation through local `loom.config.interpolation` wrapper functions. The rest of `loom` must not receive or depend on OmegaConf objects.
- Keep interpolation support limited to ordinary OmegaConf config-node interpolation such as `${paths.root}` and missing-value detection. Reject resolver-style interpolation containing `:` inside the interpolation token, including `${env:...}`, `${oc.env:...}`, `${now:...}`, and any custom resolver syntax. Do not register, clear, or mutate global OmegaConf resolvers.
- Validate minimal top-level config ownership:
  - Top-level document must be a mapping.
  - `name` is required and must be a non-empty string.
  - `pipeline` is required and must be a mapping.
  - `schema_version`, if present, must be supported version `1`.
  - Unknown project-owned top-level keys pass through unchanged.
- Recursively reject `_recipe_` keys anywhere in the resolved config with an unsupported-recipe `ConfigError` that includes the config path and Phase 5 handoff note.
- Leave `_target_` blocks as plain config data; do not import or instantiate target objects.
- Leave `_include_`, `_copy_`, and `_replace_` as ordinary project-owned keys in Phase 4. They must not be interpreted, stripped, required, rejected, or recorded as composition directives; they still participate in normal merge, override, interpolation, validation pass-through, redaction, provenance, and fingerprint behavior.
- Redact secret-like keys recursively in the returned `redacted` mapping without mutating `resolved`.
- Record config source provenance for base file, overlay files, raw override strings, parsed overrides, source content digests, and config fingerprint payload metadata.
- Compute `ComposedConfig.fingerprint` from a stable mapping that includes resolved config, base/overlay source paths and content digests, raw and parsed overrides, and the config provenance schema version so fingerprints change when source inputs change.
- Add package, unit, and integration tests for Phase 4 behavior.

## Out-of-Scope Work

- No Phase 5 recipe expansion, `Recipe` public model, recipe catalog, `register_recipe` implementation, recipe provenance records, or recipe manifests beyond the required empty tuple.
- No `_target_` target import, recursive object construction, `_args_`, `_partial_`, `_inject_`, constructor validation, or instantiated object graph.
- No pipeline spec parsing, stage schema validation, DAG validation, stage target import, runner behavior, stage context, artifact binding, selectors, planning, resume, execution, or stores.
- No config persistence to run directories, source snapshots, composition manifests, `raw.yaml`, `overlays.yaml`, `cli_overrides.yaml`, `resolved.yaml`, or `resolved.redacted.yaml`. Persistence belongs to later run-store/runner phases.
- No `_include_`, `_copy_`, or `_replace_` directive behavior; these key names pass through as ordinary project-owned keys in Phase 4. No Hydra defaults, include graphs, component search paths, list patch operators, automatic schema inference, YAML `_schema_` bindings, or plugin-discovered composition extensions.
- No config sandbox, import allow-list mode, or security policy beyond safe YAML parsing and no object construction side effects.
- No domain-specific recipes, configs, schemas, stages, codecs, datasets, models, metrics, report helpers, or fixtures.
- No top-level `loom.__init__` config exports.
- No functional CLI behavior.
- No canonical implementation-plan status update, PR body creation, full validation run, PR opening, remote push, or product-code implementation during this planning pass.

## Assumptions

- Local `develop` at `066e210ab915ff35e13bb194a9a9d75d6a405804` is the manager-approved Phase 4 base because manager preflight confirmed local `origin/develop` matched and GitHub authentication is currently invalid.
- Authored configs are trusted project code, but YAML loading should still use safe parsing because Phase 4 must not construct Python objects.
- Public returned config data must be plain-data-compatible. Internal OmegaConf/Pydantic/YAML objects must not escape public APIs.
- `compose_config` has exactly this public signature:

  ```python
  def compose_config(
      config_path: str | Path,
      overlays: Sequence[str | Path] = (),
      overrides: Sequence[str] = (),
      recipe_catalog: object | None = None,
  ) -> ComposedConfig: ...
  ```

  Passing a non-`None` `recipe_catalog` raises `UnsupportedRecipeError` until Phase 5.
- `overlays=None` and `overrides=None` are not accepted in the public contract; they fail with a config-specific error rather than being treated as empty.
- Base and overlay YAML documents must load as mappings. Empty YAML files, YAML `null`, sequences, and scalars at document root fail with path-aware config load or validation errors.
- Overlay mappings may introduce new keys through normal recursive merge. Strict add/update rules apply only to CLI-style overrides.
- Dot-path overrides target mapping keys only. The path syntax splits on `.` and rejects empty segments. Escaping dots in key names and list element updates are deferred until concrete need appears.
- `path=value` must fail if any path segment is missing. `+path=value` must create missing intermediate mapping parents, fail if an existing parent is not a mapping, and fail if the final target path already exists.
- Override value parsing is deterministic: exact lowercase `true`, `false`, and `null`; decimal integer syntax; finite float syntax; strict JSON arrays/objects via `json.loads` with non-finite constants rejected; otherwise the original value text after `=` is a raw string. If the stripped value starts with `[` or `{`, invalid JSON is an `OverrideParseError`, not a fallback string.
- Interpolation resolution must fail clearly for unresolved references, OmegaConf `???` missing values, resolver-style syntax, and OmegaConf parse errors, with config path when available.
- Redaction key matching is case-insensitive and based on normalized key names. Normalize by lowercasing and removing `_`, `-`, and spaces. A key is secret-like when one of the default patterns appears in the normalized key: `token`, `secret`, `password`, `apikey`, `credential`, or `privatekey`.
- A secret-like key's associated value is replaced with the exact string `"***REDACTED***"` regardless of original type. Nonmatching mapping keys and list items are traversed recursively. Redaction does not mutate `resolved`.
- Config provenance may include full raw override values because it is returned in process and later persisted locally by run stores. Error messages and redacted config must not print secret values.
- `ComposedConfig.recipe_manifest` is always an empty tuple in Phase 4.
- The implementation should use Pydantic v2 where it protects stable `loom` boundaries, especially top-level validation and provenance model validation. It should not impose Pydantic schemas on arbitrary project-owned subtrees.
- Updating `uv.lock` may require network access or a warmed cache. If dependency resolution is unavailable during implementation or PR preparation, record the exact limitation in this plan's completion notes and in the PR body.

## Decision-Complete Contract

The executor must treat this section as the implementation contract. If a required public shape conflicts with current code or dependency behavior, stop and report the blocker instead of widening the phase.

### Public API

- `src/loom/config/__init__.py` exports:
  - `ConfigError`
  - `ComposedConfig`
  - `compose_config`
  - `instantiate`
  - `register_recipe`
- `compose_config` is implemented with this exact signature and returns `ComposedConfig`:

  ```python
  def compose_config(
      config_path: str | Path,
      overlays: Sequence[str | Path] = (),
      overrides: Sequence[str] = (),
      recipe_catalog: object | None = None,
  ) -> ComposedConfig: ...
  ```

  `config_path`, `overlays`, and `overrides` may be passed positionally or by keyword. `recipe_catalog` exists only to preserve the canonical future call shape; any non-`None` value raises `UnsupportedRecipeError`.
- `instantiate` remains an unsupported Phase 5 stub that raises `ConfigError` and performs no imports or object construction.
- `register_recipe` remains an unsupported Phase 5 stub that raises `ConfigError` and mutates no global registry.
- Do not add `Recipe` in Phase 4. Phase 5 owns the public recipe contract.
- Do not modify `src/loom/__init__.py`; top-level `loom.__all__` remains the Phase 2/3 list.

### Data Shapes

- `ComposedConfig` is a frozen slots dataclass:

  ```python
  @dataclass(frozen=True, slots=True)
  class ComposedConfig:
      resolved: dict[str, PlainData]
      redacted: dict[str, PlainData]
      provenance: ConfigProvenance
      recipe_manifest: tuple[dict[str, PlainData], ...]
      fingerprint: Fingerprint
  ```

- `resolved` is a normalized plain-data dict representing the fully resolved config.
- `redacted` is a normalized plain-data dict with secret-like values replaced by `"***REDACTED***"`.
- `recipe_manifest` is always `()` in Phase 4.
- `fingerprint` is a canonical digest string produced by `hash_mapping`.
- `ConfigSource` is a config-owned frozen slots dataclass with `to_dict()` and `from_dict()` helpers:

  ```python
  @dataclass(frozen=True, slots=True)
  class ConfigSource:
      kind: Literal["base", "overlay"]
      path: str
      order: int
      content_digest: Digest
      size_bytes: int
  ```

  `path` is the strict resolved filesystem path string from `Path(...).expanduser().resolve(strict=True)`. `content_digest` is computed with `hash_bytes` over the exact raw bytes read from disk before YAML parsing.
- `ParsedOverride` is a config-owned frozen slots dataclass with `to_dict()` and `from_dict()` helpers:

  ```python
  @dataclass(frozen=True, slots=True)
  class ParsedOverride:
      raw: str
      path: str
      operation: Literal["update", "add"]
      value: PlainData
      order: int
  ```

  `path` is the dotted path without the leading `+`; `raw` is the original override string exactly as supplied.
- `ConfigProvenance` is a config-owned frozen slots dataclass with `to_dict()` and `from_dict()` helpers:

  ```python
  @dataclass(frozen=True, slots=True)
  class ConfigProvenance:
      schema_version: int
      config_path: str
      sources: tuple[ConfigSource, ...]
      overrides: tuple[ParsedOverride, ...]
      resolved_fingerprint: Fingerprint
      recipe_manifest_count: int
      metadata: dict[str, PlainData]
  ```

  `schema_version` is always `1`; `config_path` equals the base source resolved path; `sources[0]` is the base source with `order=0`; overlay sources follow the provided order with `order=1..n`; `recipe_manifest_count` is always `0`; `metadata` is a plain-data dict and may be empty.

### Error Behavior

- Add `loom.config.errors` with concrete errors rooted in `ConfigError`:
  - `ConfigLoadError`
  - `ConfigMergeError`
  - `OverrideParseError`
  - `OverrideApplyError`
  - `ConfigInterpolationError`
  - `ConfigValidationError`
  - `ConfigRedactionError`
  - `ConfigProvenanceError`
  - `UnsupportedRecipeError`
- Error messages must include config path, file path, overlay order, override path, or operation context when available. Include a raw override string only when doing so does not expose a parsed secret-like key/value; otherwise redact the value portion.
- Preserve lower-level causes when wrapping YAML parser errors, file read errors, JSON override parse errors, OmegaConf errors, Pydantic validation errors, plain-data validation errors, and fingerprint input errors.
- Do not add structured `ErrorContext`, error codes, CLI formatting, or a diagnostics framework in this phase.
- Do not include raw secret values in error messages.

### Composition Behavior

- Load the base config first, then overlay files in the provided order.
- Merge overlays into the accumulated mapping:
  - mapping plus mapping: recursive merge
  - scalar plus anything or anything plus scalar: replacement by higher-precedence value
  - list plus list or list plus any value: replacement by higher-precedence value
  - explicit YAML `null`: replacement by `None`
- Apply overrides after all overlays.
- Resolve interpolation after overrides and before recipe detection/validation.
- Detect `_recipe_` keys after interpolation and fail before returning.
- Treat `_include_`, `_copy_`, and `_replace_` as ordinary project-owned keys during this phase. They are not composition directives, and their presence must not trigger validation failures unless they violate another documented Phase 4 rule.
- Validate top-level fields after interpolation and unsupported-recipe detection.
- Redact after validation.
- Build provenance and fingerprint from the same normalized source data used for composition.
- Return the `ComposedConfig`.
- Do not write files at any point.

### YAML Loading Contract

- Loading uses `Path(...).expanduser().resolve(strict=True)` for each base and overlay path.
- The loader reads exact bytes once for digesting and parsing. It computes `content_digest` with `hash_bytes(raw_bytes)` and `size_bytes` from `len(raw_bytes)`.
- The loader decodes as UTF-8 and parses only with PyYAML safe parsing: `yaml.safe_load` or `yaml.load(..., Loader=yaml.SafeLoader)`.
- Missing files, unreadable files, invalid UTF-8, invalid YAML, unsafe Python object tags, empty documents, YAML `null`, root sequences, and root scalars raise `ConfigLoadError` with file path and source kind/order context.
- YAML mapping keys must be strings after parsing. Non-string keys raise `ConfigLoadError` or `ConfigValidationError` with the failing config path.
- Loaded values are normalized through `ensure_plain_data` before merge. Non-finite floats, timestamps, bytes, sets, Python objects, and other non-plain values fail before composition continues.
- The loader and composer must not create, modify, delete, or snapshot files.

### Override Contract

- An override string is split at the first `=`. Missing `=`, empty path, empty path segments, and a bare `+` path raise `OverrideParseError`.
- A leading `+` on the path selects `operation="add"`; otherwise the operation is `update`.
- Path segments are mapping keys. No list-index syntax exists. If traversal reaches a list, scalar, `None`, or any non-mapping parent, override application raises `OverrideApplyError`.
- `path=value` updates only an already existing final key. Missing parents or missing final key fail.
- `+path=value` creates missing intermediate mapping parents, but fails if an existing parent is not a mapping or the final key already exists.
- Explicit `null` override values set the target to `None`; they do not delete keys.
- Value parsing:
  - exact `true` and `false` parse to booleans;
  - exact `null` parses to `None`;
  - decimal integer syntax parses to `int`;
  - finite float syntax parses to `float` and rejects non-finite results;
  - values whose stripped text starts with `[` or `{` parse as strict JSON arrays/objects and reject `NaN`, `Infinity`, and `-Infinity`;
  - any other value remains the original string text after `=`.
- Parsed values are normalized through `ensure_plain_data` before application and before provenance recording.

### Interpolation Boundary

- `loom.config.interpolation` owns all OmegaConf usage.
- The wrapper accepts plain data and returns plain data.
- The only supported interpolation behavior is ordinary config-node interpolation resolved by OmegaConf, for example `${paths.root}` and strings containing `${paths.root}`.
- Resolver-style syntax is unsupported. Before resolving, the wrapper must reject interpolation tokens containing `:` so `${env:VAR}`, `${oc.env:VAR}`, `${now:%Y%m%d}`, `${oc.select:...}`, and custom resolver syntax all raise `ConfigInterpolationError`.
- The wrapper must not call OmegaConf resolver registration, resolver clearing, or any other global resolver mutation.
- The wrapper translates OmegaConf exceptions into `ConfigInterpolationError`.
- Missing values represented by OmegaConf `???` fail as `ConfigInterpolationError`.
- Other config modules may call the wrapper but must not expose OmegaConf containers or require callers to import OmegaConf.
- Non-config modules must not import OmegaConf.

### Import Boundary

- `import loom` must not import `loom.config`, `omegaconf`, `pydantic`, or `yaml`.
- `import loom.config` may import the hard config dependencies.
- `loom.serialization`, `loom.io`, `loom.provenance`, and `loom.fingerprints` must not import `loom.config`.
- The config package must not import pipeline, stores, execution, CLI, plugin discovery, or downstream project packages.

## Design Impact

- Maintainability: splitting config behavior by load, merge, overrides, interpolation, validation, redaction, provenance, and compose keeps tests source-mirrored and prevents one monolithic composition module from owning every edge case.
- Extensibility: local wrappers for interpolation and provenance make future backend changes, recipes, and stricter config modes additive without leaking OmegaConf details across the codebase.
- Domain neutrality: validation is limited to `loom`-owned top-level boundaries and the Phase 4 `_recipe_` unsupported directive. Project-owned keys pass through as plain data.
- Source-tree boundaries: config may depend on serialization, fingerprints, errors, and standard primitives, but must not depend on pipeline execution, stores, CLI, plugins, or domain packages.

## Future Compatibility

- `ComposedConfig.recipe_manifest` is present now and empty so Phase 5 can populate it without changing the return shape.
- Keeping `recipe_catalog` in the `compose_config` signature as an unsupported `None`-only argument preserves the future call shape while avoiding recipe behavior in Phase 4.
- Keeping `_target_` blocks as plain data lets Phase 5 implement instantiation and Phase 6 parse stage target paths without Phase 4 side effects.
- Config provenance source records can be extended later with source snapshots, include/copy stacks, composition manifests, and recipe expansion records.
- The interpolation wrapper preserves room to add carefully scoped resolvers later after their provenance and fingerprint implications are explicit.
- Strict mapping-only override paths keep the first implementation reviewable. List index paths and escaped key segments can be added later without changing existing behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Optional config extras instead of hard dependencies | The canonical v0 plan explicitly chooses hard config dependencies after Phase 4 to keep one tested installation shape. |
| Use OmegaConf objects as public `resolved` config | Public config data must stay plain-data-compatible for stable hashing, redaction, provenance, and later persistence. |
| Implement recipes in Phase 4 | Phase 5 owns recipe contracts, expansion, recipe provenance, and catalogs. Phase 4 must fail `_recipe_` blocks clearly. |
| Implement `_target_` instantiation in Phase 4 | Object construction side effects are explicitly out of scope and belong to Phase 5. |
| Interpret `_include_`, `_copy_`, or `_replace_` as composition directives | These are deferred post-v0 composition features and would widen the PR beyond the approved Phase 4 acceptance criteria. |
| Explicitly reject `_include_`, `_copy_`, or `_replace_` in Phase 4 | The canonical Phase 4 acceptance criteria require `_recipe_` rejection only. Treating these names as ordinary project-owned keys preserves scope and avoids prematurely reserving future directive semantics. |
| Add list patch operators or list-index override syntax | The plan requires list replacement only. Complex list behavior is deferred until there is concrete recurring need. |
| Validate arbitrary project-owned config schemas with Pydantic | `loom` owns only stable boundaries. Project-specific schemas belong to recipes or downstream code. |
| Compute fingerprints from resolved config only | The acceptance criteria require fingerprints to change when source inputs change, so source paths/digests and overrides must participate. |
| Persist config snapshots during composition | Persistence belongs to run stores and runner phases. Phase 4 composition must write no files. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Hard config dependencies after Phase 4 | Accepted by the v0 implementation plan to avoid an early optional extras matrix. | After Phase 10, revisit if downstream users need a primitives-only install. |
| Dot-path overrides support mapping keys only, with no escaping or list indexing | Keeps the first override implementation deterministic and reviewable. | Revisit when real configs need dotted key literals or list element updates. |
| Interpolation wrapper is intentionally narrow and does not add custom resolvers | Avoids nondeterministic or hidden fingerprint inputs before the provenance model is explicit. | Revisit when env/time/custom resolver semantics are documented with provenance and fingerprint policy. |
| `_include_`, `_copy_`, and `_replace_` pass through as ordinary keys | Phase 4 owns only base/overlay/override composition and `_recipe_` rejection. | Revisit in the post-v0 composition-directive phase that defines include/copy/replace semantics and migration notes. |
| Config provenance does not include source snapshots or composition manifests | Phase 4 writes no files and later run-store phases own persisted snapshots. | Revisit in run-store/runner phases or a post-v0 composition-manifest phase. |
| Recipe manifest is always empty | Required bridge behavior until Phase 5. | Phase 5 replaces this debt with deterministic recipe expansion records. |

## Reviewability

- Expected PR size and shape: one focused config-composition PR with dependency metadata, new `src/loom/config/` modules, package/unit/integration tests, and no pipeline/store/runner behavior.
- Files and areas to inspect:
  - `pyproject.toml` and `uv.lock` for hard dependency changes only.
  - `src/loom/config/__init__.py` and `api.py` for public exports and stubs.
  - `src/loom/config/load.py`, `merge.py`, `overrides.py`, and `interpolation.py` for composition semantics.
  - `src/loom/config/validation.py`, `redaction.py`, `provenance.py`, and `compose.py` for public return behavior.
  - `src/loom/config/errors.py` for local concrete errors rooted in `ConfigError`.
  - `src/loom/__init__.py` should be unchanged.
  - Package import-boundary tests for cheap top-level imports.
  - Unit and integration tests for all Phase 4 acceptance criteria.
- Scope-control checks:
  - No recipes or target instantiation.
  - No pipeline spec parsing or runner/store writes.
  - No Hydra/defaults/include/copy/replace directive behavior; `_include_`, `_copy_`, and `_replace_` pass through as ordinary keys.
  - No domain-specific config keys or fixtures.
  - No top-level `loom` config re-exports.

## Files And Areas To Inspect

- `src/loom/config/__init__.py` for existing stubs and final public config imports.
- New `src/loom/config/` modules listed in the in-scope section.
- `src/loom/errors.py` for the existing broad `ConfigError` root.
- `src/loom/serialization/plain.py` and `src/loom/serialization/json.py` for plain-data normalization and JSON behavior.
- `src/loom/fingerprints.py` for stable hashing helpers.
- `src/loom/provenance/` for generic provenance boundaries and to avoid duplicating non-config capture behavior.
- `src/loom/__init__.py` and package tests for cheap top-level import behavior.
- `pyproject.toml` and `uv.lock` for dependency updates.
- `Makefile`, `tools/test_harness/cli.py`, and `tests/README.md` for suite targets and absent-suite behavior.
- Existing tests under `tests/package/`, `tests/unit/loom/`, `tests/contracts/`, and `tests/integration/`.
- Source references:
  - `docs/roadmap/stage-0/implementation-plan.md`, especially Phase 4 and the plan quality gate.
  - `docs/structure.md` sections "Configuration", "Runtime Dependency Policy", "Module Responsibilities", "Documentation Map", and "Test Layout".
  - `docs/features/config.md` sections 1 through 10, 13 through 16, and 18, narrowed by the canonical Phase 4 scope.
  - `docs/features/provenance.md` sections for `loom.config.provenance`, config provenance summary, redaction ownership, fingerprints, and relationship to config.
  - `docs/features/fingerprints.md` relationship to config and structured hashing guidance.
  - `docs/features/errors.md` path-aware config error guidance.
  - `docs/features/testing.md` suite layout and phase workflow timing.

## Implementation Steps

1. Add hard config dependencies.
   - Update `pyproject.toml` runtime dependencies.
   - Update `uv.lock` with the new default runtime dependency graph in the same implementation slice.
   - If dependency resolution requires network/cache access that is unavailable, stop and record the exact blocker before editing product code that depends on those packages.

2. Add config error and public API scaffolding.
   - Add `src/loom/config/errors.py`.
   - Add `src/loom/config/api.py` with `ComposedConfig`, real `compose_config`, and Phase 5 stubs for `instantiate` and `register_recipe`.
   - Update `src/loom/config/__init__.py` exports.
   - Tests: package public API and config error inheritance.

3. Implement YAML loading.
   - Add safe YAML loading with path-aware file, UTF-8 decode, unsafe-tag, non-string-key, non-plain-data, and parser errors.
   - Validate that loaded documents are mappings and reject empty/null, sequence, and scalar roots.
   - Record resolved source path, source kind, source order, raw byte content digest, and byte size.
   - Tests: `tests/unit/loom/config/test_load.py`.

4. Implement recursive merge.
   - Add pure merge helpers for mapping recursion, scalar replacement, list replacement, and explicit `None`.
   - Treat `_include_`, `_copy_`, and `_replace_` like any other mapping keys; avoid directive behavior and list patching.
   - Tests: `tests/unit/loom/config/test_merge.py`.

5. Implement override parsing and application.
   - Parse `path=value` and `+path=value`.
   - Parse supported scalar and structured values with strict JSON object/list behavior and finite floats only.
   - Apply to mapping-only dot paths with strict update/add behavior, missing intermediate parent creation for `+`, and path-aware failures.
   - Tests: `tests/unit/loom/config/test_overrides.py`.

6. Implement interpolation wrapper.
   - Add local wrapper around OmegaConf creation/resolution/to-container behavior.
   - Reject resolver-style interpolation before OmegaConf resolution and do not mutate global OmegaConf resolvers.
   - Translate unresolved references, `???` missing values, unsupported resolver syntax, and OmegaConf failures into `ConfigInterpolationError`.
   - Return plain data only.
   - Tests: `tests/unit/loom/config/test_interpolation.py`.

7. Implement validation and unsupported recipe detection.
   - Add Pydantic v2 models or validators for top-level `name`, `pipeline`, and optional `schema_version`.
   - Add recursive `_recipe_` detection with config path reporting.
   - Preserve unknown project-owned keys, including `_include_`, `_copy_`, `_replace_`, and `_target_`.
   - Tests: `tests/unit/loom/config/test_validation.py` and recipe-rejection cases in `test_compose.py`.

8. Implement redaction.
   - Add recursive key-pattern redaction without mutating resolved data.
   - Redact nested mapping/list structures and mixed-case/hyphen/underscore key variants.
   - Tests: `tests/unit/loom/config/test_redaction.py`.

9. Implement provenance and fingerprint assembly.
   - Add config provenance dataclasses with plain-data `to_dict`/`from_dict`.
   - Include base/overlay source digests, raw and parsed overrides, resolved fingerprint, and recipe manifest count.
   - Compute `ComposedConfig.fingerprint` from source inputs plus resolved config.
   - Tests: `tests/unit/loom/config/test_provenance.py`.

10. Implement composition orchestration.
    - Wire load, merge, overrides, interpolation, recipe detection, validation, redaction, provenance, and fingerprint into `compose_config`.
    - Ensure no writes occur by testing around temp config directories.
    - Tests: `tests/unit/loom/config/test_compose.py` and integration tests.

11. Update package import-boundary tests.
    - Add assertions that `import loom` does not import `loom.config`, `omegaconf`, `pydantic`, or `yaml`.
    - Add assertions that `import loom.config` exposes Phase 4 public API.
    - Keep top-level `loom.__all__` unchanged.

12. Run targeted checks during implementation.
    - Use focused direct pytest commands while iterating.
    - Run `make test-package`, `make test-unit`, and `make test-integration` before executor handoff when feasible.
    - `make test-contract` may report existing Phase 3 contract tests; no new Phase 4 contract tests are required.

13. Leave final PR validation to `loom_pr_preparer`.
    - `loom_pr_preparer` must run `make validate-pr` and `make test-summary`.
    - If dependency installation or test commands require `UV_CACHE_DIR=/tmp/uv-cache`, record that in the PR body and completion notes.

## Test Plan

### Package Suite

- Status: required.
- Existing suite target: `make test-package`.
- Expected paths:
  - `tests/package/test_import.py`
  - `tests/package/test_public_api.py`
  - `tests/package/test_import_boundaries.py`
- Required assertions:
  - `import loom` succeeds and preserves the current cheap top-level public exports exactly.
  - `import loom` does not eagerly import `loom.config`, `omegaconf`, `pydantic`, `yaml`, `loom.pipeline`, `loom.cli`, stores, plugins, or downstream project packages.
  - `import loom.config` succeeds after hard config dependencies are installed.
  - `from loom.config import ConfigError, ComposedConfig, compose_config, instantiate, register_recipe` works.
  - `inspect.signature(compose_config)` matches `config_path, overlays=(), overrides=(), recipe_catalog=None` in that order.
  - `compose_config` is callable and no longer raises the Phase 1 unsupported message for valid inputs.
  - `instantiate` and `register_recipe` still raise clear Phase 5 `ConfigError` stubs without importing targets or mutating registries.
  - `loom.__all__` remains unchanged and does not include config exports.

### Unit Suite

- Status: required.
- Existing suite target: `make test-unit`.
- Expected paths:
  - `tests/unit/loom/config/test_errors.py`
  - `tests/unit/loom/config/test_load.py`
  - `tests/unit/loom/config/test_merge.py`
  - `tests/unit/loom/config/test_overrides.py`
  - `tests/unit/loom/config/test_interpolation.py`
  - `tests/unit/loom/config/test_validation.py`
  - `tests/unit/loom/config/test_redaction.py`
  - `tests/unit/loom/config/test_provenance.py`
  - `tests/unit/loom/config/test_compose.py`
- Required assertions:
  - Concrete config errors inherit from `ConfigError` and preserve wrapped causes.
  - YAML loading reads mappings safely, uses safe parsing only, rejects missing files, invalid UTF-8, invalid YAML, unsafe Python object tags, empty documents, root sequences, root scalars, non-string mapping keys, and non-plain values with file/path context.
  - Base and overlay source digests are computed from raw bytes, are stable, and change when file content changes.
  - Recursive merge preserves nested mappings and replaces scalars, lists, and explicit nulls.
  - Recursive merge treats `_include_`, `_copy_`, and `_replace_` as ordinary keys.
  - Override parsing handles booleans, nulls, integers, finite floats, strict JSON arrays, strict JSON objects, and fallback strings.
  - Override parsing rejects malformed overrides, invalid JSON arrays/objects, JSON non-finite constants, empty paths, and empty path segments.
  - Override application updates existing mapping paths, adds new mapping keys only through `+`, creates missing intermediate mapping parents for `+`, rejects missing update paths, rejects duplicate add paths, rejects traversal through lists/scalars/nulls, and reports the failing path.
  - Interpolation resolves ordinary config references after overlays and overrides.
  - Interpolation rejects resolver syntax such as `${env:VAR}`, `${oc.env:VAR}`, `${now:%Y}`, and `${oc.select:missing,default}` without registering or mutating global resolvers.
  - Interpolation failures for unresolved references, `???` missing values, unsupported resolver syntax, or OmegaConf errors become `ConfigInterpolationError` with useful path/context.
  - Validation requires top-level `name` and `pipeline`, rejects invalid `schema_version`, and preserves unknown project-owned keys including `_include_`, `_copy_`, and `_replace_`.
  - `_recipe_` keys at root or nested paths raise `UnsupportedRecipeError` with the exact config path and Phase 5 unsupported message.
  - `_target_` keys remain plain data and do not trigger imports or object construction.
  - Redaction recursively masks secret-like keys by replacing the associated value with `"***REDACTED***"`, handles case and separator variants, preserves non-secret values, and does not mutate resolved data.
  - `ConfigSource`, `ParsedOverride`, and `ConfigProvenance` `to_dict`/`from_dict` round-trip as plain data and record sources and overrides deterministically.
  - `ComposedConfig.fingerprint` changes when base file content, base path, overlay file content, overlay path, overlay order, raw overrides, parsed override values, or resolved config changes.
  - `compose_config` returns resolved, redacted, provenance, empty recipe manifest, and fingerprint for valid configs.
  - `compose_config` rejects non-`None` `recipe_catalog`, `overlays=None`, and `overrides=None` with config-specific errors.
  - `compose_config` writes no files in the config directory or current working directory.

### Contract Suite

- Status: deferred for new Phase 4 coverage.
- Existing suite target: `make test-contract`.
- Expected paths:
  - Existing Phase 3 contract tests remain under `tests/contracts/`.
- Required assertions or deferral reason:
  - Phase 4 introduces no structural extension protocol like `Codec`, `DataSource`, `Stage`, `ArtifactStore`, `RunStore`, or recipe catalog.
  - Public `compose_config` behavior is covered by package, unit, and integration suites.
  - Phase 5 should add contract-style coverage for recipes and target instantiation if it introduces extension contracts.
  - PR preparation should still run `make test-contract` so existing contract coverage remains green.

### Integration Suite

- Status: required.
- Existing suite target: `make test-integration`.
- Expected paths:
  - `tests/integration/config/test_compose_config.py` or `tests/integration/test_config_composition.py`.
- Required assertions:
  - A base YAML file plus multiple overlay YAML files compose in order through the public `compose_config` API.
  - Overrides applied through the public API affect the final resolved config after overlays.
  - Interpolation can reference values introduced by base files, overlays, and overrides.
  - Required top-level validation runs after interpolation.
  - Redacted output masks nested secret-like keys while resolved output retains full values.
  - `_include_`, `_copy_`, and `_replace_` remain in resolved output as ordinary authored keys when present.
  - Provenance records the base source, overlay sources in order, and override records.
  - Fingerprints differ when a source file changes, overlay order changes, or an override changes.
  - `_recipe_` in a realistic config tree fails clearly without partial expansion.
  - No files are created beside the authored configs.
  - The integration fixture remains domain-neutral and uses synthetic config keys only.

### E2E Suite

- Status: deferred for this phase.
- Existing suite target: `make test-e2e`.
- Expected path status: `tests/e2e` may remain absent or contain no Phase 4 tests.
- Required assertions or deferral reason:
  - Phase 4 has no functional CLI, pipeline parser, runner, run store, artifact store, or complete user workflow.
  - Full public workflow e2e coverage begins after pipeline specs, stores, planning, and local execution exist.
  - PR preparation should run `make test-e2e` if the suite exists and document the result; otherwise the harness may report `not present`.

### Opt-In Suites

- Status: deferred for this phase.
- Markers affected: `slow`, `slurm`, `network`, and `optional_dependency`.
- Required assertions or deferral reason:
  - Phase 4 config dependencies are hard default runtime dependencies, not optional dependency behavior.
  - No network, SLURM, subprocess, remote store, or slow external-service behavior is in scope.
  - Do not add tests marked `slow`, `slurm`, `network`, or `optional_dependency`.
  - The default test command already excludes opt-in markers; PR preparation should document if any unrelated opt-in tests exist.

## Risks

- Dependency resolution may fail in the current environment because GitHub auth is invalid and sandboxed network access is limited. The implementation phase must record exact dependency-update blockers if `uv lock` cannot run.
- OmegaConf interpolation behavior can leak through if containers or exceptions escape the wrapper. Unit tests must assert plain-data output and config-specific error wrapping.
- Redaction can accidentally mutate resolved data or miss key variants. Tests must cover nested mappings/lists and mixed-case/underscore/hyphen variants.
- Fingerprinting only resolved config would miss source-input-only changes. The fingerprint payload must include source paths, source content digests, and override records.
- Validating too much of the `pipeline` tree would pull Phase 6 behavior forward. Phase 4 validation must remain top-level only.
- Leaving `instantiate` as a stub may require updating old Phase 1 tests whose expected message said Phase 4. That is intentional because object construction is now Phase 5 scope.

## Validation Commands

Targeted development commands:

```sh
make test-package
make test-unit
make test-integration
make test-contract
uv run pytest tests/unit/loom/config tests/integration/config -m "not slow and not slurm and not network and not optional_dependency"
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices:
  - dependencies and public API/errors;
  - YAML load and source digest provenance;
  - merge and override helpers;
  - interpolation wrapper;
  - validation and unsupported recipe detection;
  - redaction;
  - provenance/fingerprint assembly;
  - final compose orchestration and tests.
- Tests to run with each slice:
  - package tests after public API/export changes;
  - config unit tests after each module slice;
  - integration tests after `compose_config` orchestration;
  - existing contract tests before handoff to ensure Phase 3 extension contracts remain green.
- Decisions the executor must not revisit:
  - no recipes or target instantiation;
  - no pipeline/store/runner behavior;
  - no persistence writes from composition;
  - no top-level `loom` config exports;
  - no include/copy/replace directive behavior; `_include_`, `_copy_`, and `_replace_` are ordinary project-owned keys for this phase;
  - no list-patch or list-index override behavior;
  - no resolver-style interpolation or OmegaConf global resolver mutation;
  - no changes to `loom.__init__`.
- Conditions that require stopping for the manager:
  - dependency resolution cannot update `uv.lock`;
  - OmegaConf cannot satisfy the documented interpolation wrapper without leaking OmegaConf objects;
  - required source-input fingerprint behavior conflicts with existing fingerprint helpers;
  - package import-boundary tests require top-level config imports;
  - implementing a required acceptance criterion appears to require Phase 5 or later behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: used.
- PR review: unused.

## Completion Notes

- Draft plan: created by `loom_phase_planner` in this planning pass.
- Final expanded plan: refined by `loom_phase_plan_expander` in this pass.
- Implementation summary: completed in commits `d0a3857` (implementation) and `749355a` (tests).
- Dependency lock update: manager reran `UV_CACHE_DIR=/tmp/uv-cache uv lock` with network escalation after implementation; `uv.lock` now includes `omegaconf`, `pydantic`, `pyyaml`, and transitive runtime dependencies and is included in the refinement commit.
- Implementation validation: Phase 4 targeted pytest, package, unit, integration, contract, Pyright, and `make validate-pr` passed locally during the refinement pass.
- Refinement summary: completed by `loom_phase_refiner` on 2026-05-03 in the single allowed implementation/test refinement pass.
- PR preparation: completed by `loom_pr_preparer` on 2026-05-03. The canonical
  plan status was updated to `pr_open`, and the PR body was prepared at
  `docs/roadmap/stage-0/phases/add-config-composition-pr-body.md`.
- Final PR-prep validation:
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr`: passed; Ruff passed,
    Pyright reported 0 errors, default pytest passed with 175 tests, and
    `uv build` produced sdist and wheel artifacts.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary`: passed and wrote
    `build/test-summary.md`; package passed with 13 tests, unit passed with
    153 tests, contract passed with 4 tests, integration passed with 5 tests,
    and e2e was not present.
- PR creation status: opened as
  https://github.com/samcantrill/loom/pull/7. Verified with
  `gh pr view 7 --json baseRefName,headRefName,state,url`; `baseRefName` is
  `develop`, `headRefName` is `codex/add-config-composition`, and state is
  `OPEN`.
- Remaining product blockers: none known after this refinement and PR-prep
  validation pass.

### Phase Refinement Report

#### Metadata

- Phase: `Phase 4 - Config Composition`.
- Branch: `codex/add-config-composition`.
- Worktree: `/home/samcantrill/work/loom-worktrees/add-config-composition`.
- Expanded phase plan: `docs/roadmap/stage-0/phases/add-config-composition.md`.
- Refiner: `loom_phase_refiner`.
- Refinement date: 2026-05-03.
- Phase implementation refinement budget status after this pass: used.

#### Refinement Scope

- Validation output reviewed: manager-provided Phase 4 pytest collection failure; local reruns of the Phase 4 targeted pytest command; `make test-unit`; `make validate-pr`.
- Blocking issues caused by this phase:
  - `src/loom/config/validation.py` imported a Pydantic model that generated a schema over the recursive `PlainData` alias at import time, causing `RecursionError` during test collection.
  - New config tests had expectations that conflicted with the finalized Phase 4 override and interpolation order contract.
  - New config unit test filenames collided with existing unit test module basenames during full unit-suite collection.
  - Several Phase 4 helpers and tests did not narrow `PlainData` before returning or indexing mappings, causing Pyright failures.
- Issues confirmed out of scope: none.

#### Fixes Made

| Issue | Change | Evidence |
| --- | --- | --- |
| Pydantic recursive `PlainData` schema generation failed during collection. | Replaced the validation model with direct top-level checks for `name`, `pipeline`, and `schema_version` while preserving unknown project-owned keys and default `schema_version=1`. | Phase 4 targeted pytest passed. |
| Phase 4 tests contradicted finalized override/interpolation semantics. | Updated tests to use `+` for added override keys and assert interpolation after overrides against the composed config. | Phase 4 targeted pytest passed. |
| Full unit collection found duplicate test module basenames. | Renamed config test modules to `test_config_errors.py` and `test_config_provenance.py`. | `make test-unit` passed. |
| Pyright could not prove plain-data mapping/list shapes. | Added runtime narrowing in config helpers and focused test assertions/casts without changing public behavior. | `uv run pyright` and `make validate-pr` passed. |

#### Tests Or Validation Re-Run

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/config tests/integration/config tests/package/test_config_api.py tests/package/test_import_boundaries.py tests/unit/loom/test_deferred_stubs.py
result: passed, 44 tests
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-package
result: passed, 13 tests
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-unit
result: passed, 153 tests
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-integration
result: passed, 5 tests
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make test-contract
result: passed, 4 tests
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pyright
result: passed, 0 errors
```

```text
command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright passed, default pytest passed with 175 tests, and `uv build` produced sdist and wheel
```

#### Remaining Blockers

- None known.

#### PR Preparation Handoff

- Completion notes updated in expanded phase plan: yes.
- Budget status updated: yes, phase implementation refinement is `used`; PR review remains `unused`.
- Final validation completed by `loom_pr_preparer`: `make validate-pr` and
  `make test-summary` passed with `UV_CACHE_DIR=/tmp/uv-cache`.
- Suite evidence recorded: yes, in
  `docs/roadmap/stage-0/phases/add-config-composition-pr-body.md`.

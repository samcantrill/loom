# Implementation Plan v1

## Metadata

- Status: ready for phase implementation
- Related planning notes:
  `docs/implementation-plans/roadmap-v1-planning-notes.md`
- Related brief: none; roadmap-version planning notes are the approved intent
  artifact for this v1 refinement.
- Related specifications: existing `docs/features/` config, serialization, I/O,
  fingerprints, provenance, errors, and testing documents where present.
- Draft pass: updated from roadmap-version planning notes
- Refine pass: phase specifications and testing obligations refined from
  `.codex/prompts/feature-brief-draft.md`,
  `.codex/prompts/feature-brief-refine.md`,
  `.codex/prompts/specification-draft.md`,
  `.codex/prompts/specification-refine.md`,
  `.codex/prompts/implementation-plan-draft.md`, and
  `.codex/prompts/implementation-plan-refinement.md`
- Plan quality gate: passed on 2026-05-05 by `loom_plan_reviewer`
  confirmation review; no blocking findings remain
- Blockers: none recorded

## Goal

Implement `loom` v1 as a strict, explicit, artifact-safe configuration
composition layer over the v0 configuration system.

V1 prioritizes correctness, rebuildability, future-roadmap compatibility, and
reviewable behavior over short syntax. It lets config authors split large
configs into nested component files, safely swap model/dataset/stage components,
inspect how a composed config was produced, and persist artifact-safe composition
records for later run-store, resume, and CLI work.

V1 includes `_include_`, `_replace_`, strict update overrides, explicit `+`
add overrides, source-aware errors, a narrow versioned composition manifest,
artifact-safe fingerprints, and source metadata/hashes. V1 explicitly excludes
`_copy_` implementation.

## Context

V0 config composition supports:

- YAML loading.
- Base config plus ordered overlays.
- Dot-path overrides.
- OmegaConf-style interpolation.
- Named `_recipe_` expansion.
- Recursive `_target_` instantiation.
- Redaction, provenance, and fingerprints.

V0 explicitly defers recursive include graphs. V1 fills that gap with a narrow,
strict composition feature:

```yaml
model:
  _include_: resnet50
```

For `configs/experiment.yaml`, this resolves by default to:

```text
configs/model/resnet50.yaml
```

The included content loads first, then local sibling keys override it through
the same strict merge semantics used elsewhere in config composition.

V1 also adds whole-section replacement for safe component swaps:

```yaml
model:
  _replace_: true
  _include_: vit_b16
```

`_copy_` remains deferred. If `_copy_` appears in authored config in v1, loading
must fail with an explicit unsupported-directive `ConfigError`.

## Desired Outcome

After v1 is complete:

- Config authors can split nested config components into separate YAML files.
- `_include_` works recursively inside mappings.
- Multiple include sites across a config are supported, with at most one
  `_include_` per mapping node.
- `_replace_: true` lets overlays, override mappings, and future generated
  configs replace whole mapping sections without stale lower-precedence keys
  leaking through.
- Override strings distinguish strict updates from explicit `+` additions.
- File-defined composition runs before user-defined composition.
- User-defined include swaps can replace existing file-defined component choices
  before recipes and ordinary value overrides.
- Ordinary user value overrides target the expanded concrete config, including
  recipe-produced paths.
- Relative includes resolve from the including file and mapping key path.
- Exact explicit paths, absolute paths, and `file://` URIs are supported.
- Include expansion is deterministic, cycle-safe, and provenance-rich.
- Built-in OmegaConf resolver-style interpolation can execute at runtime, while
  artifact generation and default fingerprints preserve resolver expressions as
  authored text.
- Custom resolver-style interpolation raises a structured
  `ConfigUnsupportedResolverError` that is both a `ConfigError` subclass and a
  `NotImplementedError` in v1.
- Config artifacts do not persist resolved environment variables or other
  resolver outputs by default.
- Runs can persist a narrow composition manifest and artifact-safe source records
  sufficient to compare authored composition and, when raw source snapshots are
  explicitly enabled, rebuild authored inputs where possible.
- Validation remains scoped to stable `loom`-owned boundaries.
- `loom.pipeline` and other runtime modules remain usable without `loom.config`
  or composition manifests.

## Non-Goals

- No `_copy_` support in v1.
- No Hydra-compatible defaults lists or config groups.
- No Hydra launchers, sweepers, or runtime composition behavior.
- No arbitrary expression language in YAML.
- No multi-document YAML streams with multiple `---` documents in one file.
- No advanced list patching, list insertion, deletion, or splice operators.
- No broad registry aliases for every component.
- No automatic schema inference for arbitrary `_target_` classes.
- No YAML `_schema_` directive, project schema registry, or automatic import of
  project schema classes from config files.
- No untrusted config sandboxing or import allow-list mode.
- No plugin-discovered composition extensions.
- No custom include resolvers beyond built-in local path and `file://` behavior.
- No custom OmegaConf-style resolver execution in v1.
- No public CLI commands in v1.
- No run-store writes from `loom.config`.
- No default persistence of raw source bytes or fully resolved config artifacts.

## Public Config Surface

V1 preserves the simple public entrypoint:

```python
cfg = compose_config(
    config_path="configs/experiment.yaml",
    overlays=["configs/local.yaml"],
    overrides=["run.seed=123"],
)
```

Composition directive expansion is part of `compose_config`; ordinary callers do
not need a separate expansion step.

V1 keeps `ComposedConfig` as the public return object and extends it
additively. Existing field names remain available:

- `resolved`: the in-memory runtime-resolved config for Python callers; this is
  not the default persistence artifact.
- `redacted`: the redacted artifact-safe config view. By Phase 13 this view is
  based on the unresolved expanded config plus resolver-path metadata, not on
  resolved resolver outputs.
- `provenance`: `ConfigProvenance`, extended additively for v1 composition
  facts.
- `recipe_manifest`: the existing recipe manifest tuple, refined by Phase 9.
- `fingerprint`: the primary default config fingerprint. By Phase 14 this is the
  artifact-safe fingerprint computed before resolver execution.

V1 adds these fields with stable names and additive semantics:

- `unresolved`: the expanded plain config after includes, user composition,
  recipes, ordinary overrides, and pre-runtime validation, before resolver
  execution.
- `manifest`: `CompositionManifest`, the narrow versioned artifact contract for
  run-store, resume, and future CLI inspection.
- `source_artifacts`: a tuple of `SourceArtifactRecord` values for default
  metadata/hash source records.
- `fingerprint_records`: a tuple of `ConfigFingerprintRecord` values for
  artifact-safe fingerprint details and later comparison.

Phase 12 exposes one lower-level public inspection API:

```python
inspection = inspect_config_composition(
    config_path="configs/experiment.yaml",
    overlays=("configs/local.yaml",),
    overrides=("run.seed=123",),
    recipe_catalog=catalog,
)
```

`inspect_config_composition(...)` accepts the same composition inputs as
`compose_config(...)` and returns `ConfigCompositionInspection`. That object is
plain serializable where practical and exposes stable, additive stage records
for file-authored composition, user composition, recipe expansion, ordinary
override application, validation, artifact generation, and runtime resolution.
`compose_config(...)` may be implemented as a wrapper over this inspection path.
Other lower-level helpers remain private unless this plan explicitly names and
exports them.

Stable artifact contracts in v1 are `CompositionManifest`,
`SourceArtifactRecord`, `ConfigProvenance`, and `ConfigFingerprintRecord`.
`ConfigCompositionInspection` is public for debugging and tests, but it is not a
persistence contract and must not become a dependency of `loom.pipeline`.

## Config And Pipeline Boundary

`loom.config` may compose configs and may instantiate trusted Python objects
when called directly. `loom.pipeline` and other runtime components must not
import `loom.config`, require `ComposedConfig`, or rely on composition manifests
for construction or operation.

Pipeline construction must remain possible directly from Python objects or plain
data. Config composition is one optional way to produce those inputs.

Required implementation safeguards:

- Add import-boundary tests proving `loom.pipeline` does not depend on
  `loom.config`.
- Add direct-construction tests for pipeline-facing APIs where v1 touches nearby
  contracts.
- Keep manifests as artifact contracts for run-store/resume/CLI tooling, not as
  pipeline APIs.

## Design Principles

- Keep authoring explicit. `_include_`, `_replace_`, and `+` overrides are
  visible author decisions, not hidden search or schema behavior.
- Fail closed on ambiguity. If intent is unclear, load or composition should fail
  with a structured, actionable error.
- Preserve source authorship through every authoring operation. Include
  resolution, errors, provenance, manifests, fingerprints, and source artifacts
  depend on knowing which file, overlay, include site, recipe, or override
  introduced a value.
- Keep `loom` domain-neutral. Validate only stable `loom` envelopes and
  contracts; project/stage config remains project-owned plain data.
- Prefer artifact-safe defaults. Persist authored expressions, hashes, manifests,
  and redacted/unresolved config records by default, not resolved runtime values.
- Keep persistence outside config. `loom.config` returns serializable artifacts;
  runner/run-store owns writing them.
- Keep v1 Python-API-only while leaving clean public contracts for future CLI
  wrapping.
- Prefer small, reviewable phase PRs. Do not combine public API, artifact
  schema, security, and composition-order changes in one large PR.

## Constraints

- Domain neutrality: configuration composition must not encode project-specific
  model, dataset, experiment, or pipeline semantics.
- Source-tree boundaries: `loom.config` may not depend on pipeline execution,
  stores, CLI modules, plugin discovery, or project code.
- Dependency constraints: do not introduce heavyweight runtime dependencies
  unless a phase execution plan records an explicit design reason.
- Security constraints: default artifacts must not persist resolved env/runtime
  values or raw source bytes.
- Compatibility constraints: preserve the v0 public `compose_config` path where
  possible and keep deferred roadmap features unblocked.
- Operational constraints: `loom.config` reads configured sources and returns
  serializable artifacts, but does not write run directories.

## Key Design Choices

- File-defined composition runs before user-defined composition.
- User include swaps are allowed only against known file-defined include sites
  unless the user provides an explicit path, absolute path, or `file://`.
- Recipes are file-defined behavior and expand before ordinary user value
  overrides.
- Ordinary user overrides target the expanded concrete config only.
- Resolver execution is runtime-only by default; artifact records preserve
  resolver expressions.
- The manifest is a narrow versioned artifact contract, not a pipeline API.
- Source artifacts default to metadata/hashes; raw source bytes are opt-in or
  deferred to run-store policy.
- `_copy_` is explicitly unsupported in v1.

## Conflicts And Tradeoffs

- Security vs exact replay: v1 intentionally gives up exact runtime resolver
  replay from default artifacts to avoid persisting secrets.
- Strictness vs authoring convenience: v1 prefers explicit failures for
  ambiguous include swaps, path typos, and unsupported directives.
- Rebuildability vs raw source exposure: metadata/hashes are default; exact
  rebuild of missing source files requires raw snapshot opt-in.
- Reviewability vs phase count: the expanded strategy creates more phases, but
  keeps public API, artifact schema, resolver security, and orchestration changes
  separately reviewable.
- CLI readiness vs CLI scope: public APIs and errors should be CLI-ready, but v1
  deliberately ships no CLI commands.
- Existing feature-doc drift: `docs/features/config.md` still describes older
  post-v0 expectations for `_copy_`, default source snapshots, resolved config
  snapshots, and pipeline/config call direction. This implementation plan is the
  source of truth for v1 where it conflicts with those older notes. Phase 16
  must align the feature docs before v1 is marked complete.

## Maintainability Assessment

The plan keeps behavior in narrow, testable modules: loading, overrides, merge,
overlay source tracking, include resolution, recursive include expansion,
resolver handling, recipes, validation, instantiation, orchestration, artifacts,
fingerprints, and source records. This avoids one large composition engine PR and
lets reviewers inspect each behavioral boundary independently.

Main maintainability risks:

- source-authorship metadata can become tangled if it is added late;
- manifest/provenance/fingerprint models can drift if each phase invents local
  shapes;
- resolver security can regress if artifact and runtime paths are not tested
  separately.

Mitigation: model skeletons land early, each phase has unit tests for its own
strict decision tree, and integration tests are added only when multiple stages
interact.

## Extensibility Assessment

V1 leaves room for later CLI, sweeps, plugins, remote stores, `_copy_`, and
secret-aware fingerprint policies by keeping extension points out of the first
strict implementation. The only public-ish artifact contract added in v1 is the
versioned manifest and associated records; those should be additive and schema
versioned so future fields can be introduced without changing pipeline logic.

Future extensions must not require `loom.pipeline` to understand config
manifests, and they must not reinterpret v1 artifact-safe fingerprints as exact
runtime fingerprints.

## Specification Refinement Basis

The phase specifications below apply the feature-brief and specification prompt
discipline directly to the implementation plan because this roadmap version is
being refined from planning notes rather than a separate new brief/spec pair.
Each phase must be clear enough that a phase execution plan can proceed without
making product or public API decisions.

Each phase must identify:

- supported behavior and invariants;
- public API or artifact-shape expectations, if any;
- invalid inputs and failure modes;
- domain-neutral examples or fixtures where behavior depends on file layout;
- non-goals and future behavior to preserve;
- acceptance criteria that can be objectively reviewed;
- suite-level test obligations.

Phase execution plans must use `.codex/templates/phase-execution-plan.md` and
must expand the suite obligations below into package, unit, contract,
integration, e2e, and opt-in test sections. Unit tests are required for as much
behavior as is reasonable. A phase may defer a suite only when the behavior is
not yet integrated enough for that suite to add signal, and the deferral reason
must be explicit.

## Config Loading

V1 accepts authored config files with these rules:

- YAML only.
- UTF-8 text.
- `yaml.safe_load`.
- Exactly one YAML document per file.
- Non-empty mapping root required.
- Plain-data values only after parse.
- Local filesystem sources and `file://` sources only.

Hierarchical nested YAML mappings and multi-file composition through includes
are supported. Multi-document YAML streams are out of scope.

## Include Syntax

`_include_` is allowed only inside mappings:

```yaml
model:
  _include_: resnet50
  dropout: 0.2
```

The included value must resolve to a config document with a mapping root. After
expansion, the node is equivalent to:

```text
recursive_merge(load(configs/model/resnet50.yaml), {"dropout": 0.2})
```

Siblings override included values. Normal merge rules apply:

- mappings recursively merge;
- scalars replace;
- lists replace as whole lists;
- explicit `null` remains explicit `null`.

If an `_include_` is authored at a config path that already has accumulated
lower-precedence mapping content, the same mapping must also contain
`_replace_: true`. This requirement applies regardless of key overlap. Component
swaps should fail loudly unless the author explicitly discards the previous
component mapping.

An include at a new path does not need `_replace_`.

V1 supports many include sites across a config, but each mapping node may
contain only one `_include_`. These are out of scope:

- list-valued includes;
- multiple includes inside one mapping node;
- `_include_` inside scalar or list nodes;
- Hydra defaults-list composition.

## Replace Syntax

`_replace_` is allowed only inside mappings:

```yaml
model:
  _replace_: true
  _include_: vit_b16
```

When the mapping is merged over an existing destination mapping, the destination
mapping is discarded before the marker mapping is applied. The final artifact
config omits `_replace_`.

`_replace_` must be exactly boolean `true`. Other values fail with a
path-aware `ConfigError`.

In v1, unnecessary `_replace_: true` where no lower-precedence mapping exists
should fail as an author-intent mismatch. This is stricter than needed for the
merge algorithm, but it keeps the decision tree explicit and can be relaxed
later if real workflows prove it too noisy.

## Copy Syntax

`_copy_` is excluded from v1.

If `_copy_` appears anywhere in authored config, composition must fail with an
unsupported-directive error. The error should name the config path, authored
source, and the fact that `_copy_` is deferred to a later roadmap plan.

## Include Resolution

Accepted target forms:

- bare names;
- exact explicit relative paths;
- exact absolute paths;
- `file://` URIs.

Other URI schemes fail.

Bare names resolve from the including file plus the mapping key path and append
exactly `.yaml`:

```yaml
# configs/experiment.yaml
model:
  _include_: resnet50
```

resolves to:

```text
configs/model/resnet50.yaml
```

```yaml
# configs/experiment.yaml
model:
  encoder:
    _include_: small
```

resolves to:

```text
configs/model/encoder/small.yaml
```

Explicit relative paths resolve from the including file directory:

```yaml
optimizer:
  _include_: ../shared/optimizer.yaml
```

`../shared/optimizer.yaml` is accepted as explicit enough even when it leaves
the including config tree. That escape should be recorded in provenance/errors.

Explicit paths require exact filenames. V1 does not probe `.yml`, append
extensions for explicit paths, or try fallback candidates. Bare names append
exactly `.yaml`.

Include paths that require resolver execution are unsupported in v1. Composition
control flow must be decidable from authored values and source context before
runtime resolver execution.

## Overrides And Merge Semantics

Override strings distinguish strict updates from intentional additions:

```text
path=value:
  update an existing path; fail if the path does not exist

+path=value:
  add a new path; fail if the path already exists
```

Dot paths split on literal dots. V1 does not support escaping literal-dot keys.

Override values parse to typed plain data:

- `true`;
- `false`;
- `null`;
- integers;
- finite floats;
- JSON arrays;
- JSON objects;
- strings otherwise.

Documentation should explain how to author literal strings that look like typed
values, preferably with JSON-quoted scalar strings where supported.

Merge semantics are intentionally small:

- mappings recursively merge;
- scalars replace;
- lists replace as whole lists;
- explicit `null` replaces with `null`;
- `_replace_: true` is the only whole-section replacement marker.

No list patching, deletion, insertion, or splice language is included in v1.

## Composition And Resolution Order

The required v1 order is:

1. Load the base YAML config.
2. Load overlay YAML files in user-provided order.
3. Merge each overlay over the accumulated file-authored tree, preserving source
   authorship.
4. Validate file-authored composition directives before expansion.
5. Expand file-authored includes recursively. Include resolution uses the source
   context of the `_include_` directive.
6. For each file-authored include, load and recursively expand the included
   document first, then merge sibling keys over it. Record sibling overrides as
   explicit local customizations.
7. Build an inspectable file-composed tree plus composition-site records.
8. Parse user override strings in order.
9. Apply user-defined composition overrides before recipe expansion:
   - `path._include_=...` can update an existing file-defined include site and
     recompose that component subtree.
   - Brand-new user include sites must use explicit relative paths, absolute
     paths, or `file://`.
   - Bare user include replacement is allowed only at existing file-defined
     include sites with known source context.
10. Reject unsupported or late composition directives, including `_copy_`.
11. Do not execute variable interpolation or resolver expressions for artifact
    generation or default fingerprints.
12. Expand registered trusted `_recipe_` blocks into plain mappings using
    artifact-safe inputs.
13. Apply ordinary user value overrides against the expanded config. Ordinary
    overrides target the expanded concrete config, not pre-expansion recipe
    arguments.
14. Validate stable `loom`-owned schema boundaries that can be checked before
    runtime value resolution.
15. Build artifact-safe provenance, manifest records, source artifact records,
    and default config fingerprints before resolver execution.
16. Produce the default persisted/redacted config artifact from the unresolved
    expanded config plus resolver-path metadata.
17. Resolve final OmegaConf-style interpolation in memory for runtime use.
18. Perform runtime-only validation and optional instantiation where applicable.

Functional impacts:

- Overlay order is meaningful and must be preserved exactly.
- An include authored in an overlay resolves relative to the overlay file, not
  the base file.
- User composition overrides happen after file-defined composition, so the
  implementation needs composition-site records rather than one pre-include
  override merge.
- Recipe expansion creates the concrete config shape before ordinary user value
  overrides.
- Resolver outputs are runtime values by default, not persisted artifact facts.

## Interpolation And Resolver Policy

OmegaConf-style interpolation is supported at runtime.

Built-in OmegaConf resolver-style interpolation, including `oc.env`, may execute
only during runtime resolution by default. Artifact generation, manifests, and
default fingerprints preserve resolver expressions as authored text.

Custom resolver-style interpolation is not implemented in v1. Encountering a
custom resolver must raise `ConfigUnsupportedResolverError`. That exception
must be a `ConfigError` subclass with the same structured context fields as
other config errors and must also satisfy the `NotImplementedError` contract so
callers can catch either `ConfigError` or `NotImplementedError`.

Composition control flow cannot depend on resolver execution in v1. These cases
should fail explicitly:

- resolver-dependent include targets;
- resolver-dependent replacement decisions;
- recipes that require resolver outputs to decide their output shape.

## Recipe Model

Recipes remain trusted project code.

V1 should harden recipe usage around explicit `RecipeCatalog` inputs for
reproducibility. Process-global recipe registration should not be the preferred
path for deterministic v1 composition.

Recipes behave as file-defined behavior:

- recipe expansion happens before ordinary user value overrides;
- ordinary user overrides target only the expanded concrete config;
- pre-expansion recipe argument override syntax is not supported in v1.

Recipe manifest entries should record artifact-safe target, arguments, and
output hashes while preserving unresolved interpolation expressions as authored
text. If a recipe cannot expand without executing resolver values, v1 should
fail explicitly.

## Instantiation And Runtime Injection

Instantiation remains separate from composition.

V1 supports strict `_target_` import syntax:

- dotted `package.module.Class`;
- colon `package.module:Class`.

V1 does not support nested object lookup after the final dotted class segment or
after the colon target. Nested classes or attributes must be exposed through
top-level module objects or factories.

Recursive instantiation should construct nested targets bottom-up before the
parent target is constructed.

`_inject_` remains runtime behavior. It maps constructor kwargs to
runtime-provided values and rejects duplicate or missing injected keys.

Config fingerprints do not hash runtime objects directly. If injected runtime
objects affect outputs, pipeline/runtime fingerprint policy must account for
them outside v1 config fingerprints.

## Correctness And Validation

V1 validates composition directives during expansion:

- `_include_` placement and value type;
- `_replace_` placement and value;
- unsupported `_copy_`;
- unsupported URI schemes;
- include cycles;
- missing include targets;
- non-mapping include content when sibling overrides require a mapping;
- include over existing lower-precedence mapping content without `_replace_`;
- unnecessary `_replace_` where no lower-precedence mapping exists.

Stable schema validation remains scoped to `loom`-owned envelopes and contracts.
V1 must make this boundary concrete before public orchestration:

- Generic `compose_config(...)` must not require arbitrary project configs to
  have top-level `name`, `pipeline`, or `schema_version` keys.
- Existing unconditional top-level validation such as `name` plus `pipeline`
  must be narrowed, moved behind an explicit Loom pipeline-envelope validation
  path, or replaced before it is used in the generic v1 composition path.
- A Loom pipeline envelope is Loom-owned only when the caller explicitly chooses
  the pipeline-config validation path or the composed value is otherwise inside a
  documented Loom-owned envelope. Unknown keys fail only inside that envelope and
  its documented stage, artifact, input, and output spec substructures.
- Composition directive shapes are Loom-owned where they appear:
  `_include_`, `_replace_`, `_copy_`, resolver-dependent composition controls,
  recipe directives, override operation records, and instantiation directives
  are validated by their owning phases.
- Recipe argument contracts are Loom-owned only for registered Loom recipe
  wrappers or explicit `RecipeCatalog` entries that declare Loom-owned
  validation.
- Composition manifest, provenance, source artifact, and fingerprint records are
  Loom-owned artifact contracts and validate their own schema/version fields.
- Project experiment, model, dataset, and stage parameter mappings pass through
  globally as project-owned plain data unless they are inside one of the
  documented Loom-owned envelopes or directive blocks above.

The exact authored key `_schema_` is reserved and unsupported in v1; if it
appears in authored YAML, composition fails with a structured unsupported-schema
error rather than importing or consulting project schemas. `_target_` remains an
instantiation directive only. V1 must not infer schemas from `_target_`
constructors or validate project mappings against constructor signatures during
composition.

V1 explicitly supports separate Loom pipeline config and project experiment/stage
config files. Each project stage may own its own config file. `loom.config`
composes and fingerprints those plain-data payloads without claiming schema
ownership.

## Security, Redaction, And Persistence

V1 chooses security over exact resolved-value reproducibility by default.

Default artifact behavior:

- do not persist the full resolved config;
- do not persist resolved environment variable values;
- do not persist custom runtime resolver outputs;
- do not persist raw source bytes by default;
- do persist artifact-safe unresolved/redacted expanded config;
- do persist resolver-expression path metadata;
- do persist source metadata/hashes;
- do persist artifact-safe provenance, manifest, and fingerprints.

The full resolved config may exist in memory for the caller after runtime
resolution. Runner/run-store persistence must not write it by default.

Documentation must warn users not to put sensitive values directly in overrides,
for example `+auth.token=...`. Users should put secrets in environment variables
or another runtime secret mechanism and reference them with supported resolvers.

`loom.config` remains persistence-free. It returns serializable artifact data but
does not write run directories, choose run-store paths, or persist raw source
snapshots.

## Provenance, Manifest, Fingerprints, And Source Artifacts

Composition provenance records how the artifact-safe composed config was
produced, not resolved runtime values.

Provenance should record:

- base and overlay sources;
- overlay ordering;
- include sites;
- authored include strings;
- resolved local/file target metadata;
- replacement markers;
- sibling customization paths;
- override paths and operation kinds;
- recipe records;
- schema-boundary checks;
- source hashes;
- resolver-expression paths;
- artifact security policy;
- `loom` version.

The composition manifest is the machine-readable receipt for a composed config
artifact. It is a narrow, versioned, additive public-ish artifact contract for
run-store, resume, and future CLI inspection. It must not couple `loom.pipeline`
to `loom.config`.

The manifest is distinct from:

- provenance prose or broad diagnostic context;
- source artifact payloads;
- resolved runtime config.

The manifest references source artifact records and explains how they were used:
base config, overlay order, include site, replacement, recipe input, or override
source.

Default config fingerprints are artifact-safe. They should include:

- source content hashes;
- stable composition context;
- source role and order;
- config paths;
- authored include values;
- portable relative paths where available;
- source artifact IDs;
- override paths and artifact-safe values;
- recipe declarations and artifact-safe outputs;
- unresolved expanded config content;
- resolver expressions as authored text.

Default config fingerprints should not include resolved environment variables,
custom resolver outputs, runtime objects, or machine-local absolute path identity
as semantic input. Absolute paths are provenance context only.

Source artifacts default to metadata and content hashes. Raw source bytes are
not persisted by default. Raw source snapshots require explicit opt-in or a
later run-store security policy. Therefore:

- v1 can verify authored-composition equivalence when original sources are
  available;
- v1 can rebuild missing authored files only when raw snapshots were explicitly
  enabled;
- v1 cannot guarantee exact runtime-value replay when resolver expressions are
  present.

Resume from config artifacts should report the distinction between authored
composition equivalence and exact runtime-value replay.

## Errors

V1 should expose path-aware and source-aware errors as `ConfigError` subclasses
with structured context.

Errors should include, where relevant:

- config path;
- source file, overlay, included file, recipe, replacement mapping, or override;
- authored directive value;
- resolved target or candidate path;
- include stack;
- schema boundary;
- expected value shape and actual value shape;
- security/redaction classification when relevant;
- explicit remediation guidance.

V1 should add structured errors for:

- `_include_` outside a mapping;
- invalid include value type;
- unsupported include URI scheme;
- missing include target;
- ambiguous include resolution;
- unsafe include path normalization;
- resolver-dependent include target;
- non-mapping include content when sibling overrides are present;
- recursive include cycle;
- `_replace_` outside a mapping or not boolean `true`;
- missing `_replace_` for include over existing mapping content;
- unnecessary `_replace_` where no lower-precedence mapping exists;
- unsupported `_copy_`;
- update override for a missing path;
- add override for an existing path;
- literal-dot key override attempts if detected;
- custom resolver-style interpolation through `ConfigUnsupportedResolverError`;
- resolver-dependent recipe output shape;
- stable schema validation failure after composition;
- unknown key in a `loom`-owned schema boundary.

Errors and provenance must avoid leaking resolved resolver values. Redaction must
be applied before serializing error-related artifact records that may contain
authored plaintext secrets.

## Source Structure

Expected additions or updates under `src/loom/config/`:

```text
artifacts.py or equivalent model module
composition.py
errors.py
includes.py
instantiation.py or equivalent existing module
interpolation.py or equivalent existing module
manifest.py or equivalent model module
merge.py or equivalent existing merge module
overrides.py or equivalent existing override module
provenance.py
recipes.py or equivalent existing recipe module
source_artifacts.py
validation.py or equivalent existing validation module
```

Responsibilities:

- artifact/manifest/source/fingerprint models: plain serializable data contracts.
- `composition.py`: staged composition orchestration and inspection APIs.
- `errors.py`: structured `ConfigError` context helpers.
- `includes.py`: recursive include expansion, source-aware merge with siblings,
  cycle detection, and include records.
- interpolation helpers: resolver scanning, artifact-safe no-execution paths,
  runtime-only built-in resolver execution, and custom resolver failure.
- recipe helpers: explicit catalog behavior, artifact-safe recipe expansion, and
  recipe records.
- instantiation helpers: strict `_target_` import semantics and bottom-up
  recursive construction.
- `merge.py`: recursive merge and `_replace_` marker handling.
- `overrides.py`: strict update and explicit `+` add override parsing and
  application.
- `source_artifacts.py`: content-addressed source metadata/hash records and
  optional raw snapshot payload handling.
- `validation.py`: source-aware validation for stable `loom` schema boundaries.

These modules may use existing config load, serialization, fingerprint, and
provenance helpers. They must not import pipeline execution, stores, CLI modules,
plugin discovery, or project code.

## Integration With V0

V1 modifies config composition, not downstream pipeline behavior:

- Config loading still owns file parsing.
- Merge semantics stay unchanged except for strict `_replace_` behavior.
- Dot-path overrides remain the user-facing mechanism, but v1 hardens them into
  strict update overrides and explicit `+` add overrides.
- Interpolation still uses the existing wrapped OmegaConf behavior, but resolver
  execution is runtime-only by default for artifact safety.
- Recipes still expand before final ordinary user value overrides.
- Typed validation still applies only at stable `loom`-owned boundaries and
  recipe inputs.
- `_target_` instantiation remains separate from composition.
- Persistence still belongs to runner/run-store.

If existing v0 provenance or fingerprint models cannot represent included
sources, replacements, resolver-expression paths, source artifacts, or manifest
records, extend those models in `loom.config` rather than adding unrelated
parallel formats.

## Future Compatibility

V1 should preserve later roadmap stages:

- V2 CLI commands should wrap `compose_config` and inspection APIs without
  adding separate composition behavior.
- V10 sweeps should generate trial override mappings that flow through
  `compose_config`.
- V11 plugin discovery may later provide explicit composition extensions, but v1
  should not load plugins automatically or define the extension API early.
- V12 and v13 remote store work may influence future URI resolvers, but v1
  should start with local and `file://` behavior.
- `_copy_` can be reconsidered after strict include/replacement/source-artifact
  behavior is implemented and reviewed.
- Secret-aware runtime-value fingerprints, keyed HMACs, or full resolved-config
  persistence can be considered later as explicit opt-in policies.

## Phased Implementation

Use the expanded path by default for phases with public API, artifact contract,
security, or composition-order impact. Adjacent phases may be collapsed only if
implementation proves genuinely trivial and review clarity is preserved.

## Phase Specification And Test Standard

Every phase must preserve the accepted v1 decisions and must not reopen product
choices already settled in this plan. The phase execution plan should define a
scope contract, not an exhaustive code recipe.

Testing defaults:

- Package tests are required when public modules, imports, or package boundaries
  change.
- Unit tests are required for pure behavior, edge cases, failure modes, and
  strict decision-tree branches.
- Contract tests are required for public-ish artifact records, structured
  errors, manifests, provenance, fingerprints, and source artifact data shapes.
- Integration tests are required when multiple composition stages interact.
- E2E tests are deferred until behavior is available through public
  `compose_config`, then required for representative domain-neutral config
  trees.
- Opt-in tests are not expected in v1 unless a raw-source snapshot opt-in path is
  implemented.

Behavioral tests should include both valid and invalid cases. Strict failures
must assert the structured error context, not only the message string. Security
tests must assert that default artifacts do not contain resolved resolver values
or raw source bytes unless an explicit opt-in path is under test.

| Phase | Behavioral specification to lock | Unit test obligations | Contract/integration/e2e obligations |
| --- | --- | --- | --- |
| 1. Boundary and artifact contracts | `loom.pipeline` remains independent from `loom.config`; artifact records are plain data with schema/version fields; manifests are artifact contracts, not pipeline APIs. | Import-boundary checks and minimal model construction/serialization. | Contract tests for empty/minimal manifest, provenance, source artifact, and fingerprint record shapes; no integration/e2e yet. |
| 2. Strict loading and structured errors | YAML input is single-document UTF-8 with non-empty mapping root; `_copy_` is unsupported everywhere; errors are `ConfigError` subclasses with structured context. | Loader success/failure matrix, multi-doc rejection, empty-root rejection, `_copy_` rejection, plain-data enforcement. | Contract tests for error context serialization and redaction-safe fields; no integration/e2e yet. |
| 3. Overrides and merge primitives | Strict update vs `+` add; typed parser; no literal-dot escaping; recursive mapping merge; scalar/list/null replacement; strict `_replace_`. | Parser values, update/add success and failure, ordering, merge cases, `_replace_` required/unnecessary/invalid cases. | Contract tests if override or merge provenance records are exposed; no e2e. |
| 4. Source-authored overlays | Ordered overlays merge one-by-one and preserve per-value source authorship for later include resolution and errors. | Overlay ordering, source-map updates, replacement interactions with overlays. | Integration tests for base plus multiple overlays with source-context assertions. |
| 5. Include resolution primitives | Accepted target forms resolve deterministically; explicit paths are exact; bare names append `.yaml`; unsupported/ambiguous/resolver-dependent targets fail. | Bare/relative/absolute/`file://` cases, `.yaml` rule, no `.yml` probing, unsafe normalization, missing target, unsupported URI, resolver expression target. | Contract tests for include resolution result/error records if exposed; no recursive integration yet. |
| 6. File-defined recursive includes | File-authored includes expand recursively with include stacks, cycle detection, sibling customizations, strict replacement, and source-aware failures. | Nested include expansion, sibling merge, cycle detection, missing target, non-mapping include content, replacement requirement. | Contract tests for include stack/provenance records; integration tests for base and overlay-authored includes. |
| 7. User composition overrides | User include swaps run after file composition; bare user include works only at existing include sites; brand-new include sites require explicit targets; ordinary overrides can target recomposed values. | Existing-site swap, brand-new explicit include, brand-new bare include failure, ordinary override path checks after recomposition. | Integration tests for recomposed subtree behavior and source-context errors. |
| 8. Resolver security and runtime interpolation | Artifact paths scan but do not execute resolvers; built-in resolvers execute only at runtime; custom resolvers fail; resolver-dependent composition control flow fails. | Resolver scanner, no-execution sentinel resolver tests, built-in runtime resolution, custom resolver `ConfigUnsupportedResolverError`/`NotImplementedError`, resolver-dependent include failure. | Integration tests proving artifacts/fingerprints preserve expressions and omit resolved values. |
| 9. Recipe catalog and expansion | Explicit catalogs are preferred for deterministic composition; recipes expand before ordinary value overrides; pre-expansion arg overrides and resolver-dependent recipe shape fail. | Catalog lookup, expansion order, override-after-expansion, artifact-safe args/output hashes, failure cases. | Integration tests with include + recipe + ordinary override order; contract tests for recipe manifest records. |
| 10. Loom validation boundaries | Only explicit Loom-owned envelopes/contracts validate; generic project configs do not need top-level `name`/`pipeline`; YAML `_schema_`, project schema registries, and automatic `_target_` schema inference are unsupported. | Loom-owned unknown-key failure, project pass-through, unconditional top-level validation removal/narrowing, schema feature rejection, structured validation context. | Integration tests after include/override composition; no e2e until public compose is wired. |
| 11. Strict instantiation and runtime injection | Instantiation is separate; dotted/colon targets only; no nested lookup beyond final class/colon target; nested targets construct bottom-up; `_inject_` checks duplicates/missing keys. | Import form matrix, invalid target forms, bottom-up order, `_partial_`, `_inject_` duplicate/missing errors. | Integration only if existing instantiation public path needs full config inputs; no artifact contract changes. |
| 12. Public compose orchestration and inspection APIs | `compose_config` executes the full accepted order; `inspect_config_composition` exposes stable stage records; `ComposedConfig` has the additive v1 field shape; pipeline and persistence boundaries hold. | Orchestration collaborator tests, `ComposedConfig` compatibility tests, and inspection API shape tests. | Package/API tests, full-order integration tests through runtime resolution, import-boundary tests; limited e2e through public `compose_config`. |
| 13. Provenance, manifest, source records, and redaction population | Artifact-safe provenance, default source metadata/hash records, manifest records, and redacted artifacts explain composition without resolved runtime values; plaintext-secret override warnings are documented. | Redaction rules, resolver-value omission, source-record population, provenance population for includes/overrides/recipes/schema boundaries. | Contract tests for manifest/provenance/source-record serialization; integration tests for artifact output from public compose. |
| 14. Artifact-safe fingerprints and resume comparison | Fingerprints are computed before resolver execution from artifact-safe inputs and Phase 13 source records; abs paths are provenance context only; resume compares authored composition, not runtime values. | Fingerprint stability/change matrix, source-record hash usage, path portability, resolver-output exclusion, redacted override handling. | Contract tests for fingerprint records and resume comparison results; integration tests for changed included files/overrides. |
| 15. Raw snapshot opt-in and source artifact hardening | Default source metadata/hashes already exist; raw source bytes are opt-in or explicitly deferred to run-store policy; duplicate raw payloads dedupe when enabled. | Duplicate handling, opt-in raw payload behavior if implemented, metadata-only rebuild limitations. | Contract tests for source artifact raw-snapshot fields and manifest references; integration tests for metadata-only equivalence checks; no default raw-byte e2e. |
| 16. Hardening, docs, and e2e | Docs and examples match supported v1 only; final behavior is covered through public APIs; validation evidence is recorded. | Regression unit tests for gaps found during implementation. | E2E tests for representative config trees; `make validate-pr`; `make test-summary`. |

## Phase Design And Review Matrix

This table supplies the per-phase design-impact and reviewability notes that
phase execution plans must expand. If a phase introduces additional debt during
implementation, record it in that phase execution plan and PR body.

| Phase | Design impact | Future compatibility | Alternatives rejected / debt | Reviewability |
| --- | --- | --- | --- | --- |
| 1 | Establishes artifact contracts and import boundaries before behavior changes. | Keeps pipeline independent and manifests usable by future run-store/CLI code. | Rejects manifest-as-pipeline API. | Small model/import diff; inspect serialization and imports. |
| 2 | Centralizes strict loading and error context. | Leaves later composition phases with consistent diagnostics. | Rejects permissive YAML streams and silent `_copy_`. | Pure loader/error behavior with focused unit tests. |
| 3 | Hardens override and merge primitives used by every later phase. | Preserves future sweeps by making generated overrides follow the same strict language. | Rejects list patching and literal-dot escaping in v1. | Pure helper behavior; high unit coverage expected. |
| 4 | Adds source authorship as a first-class merge concern. | Enables overlay-authored includes and source-aware errors. | Debt if source-map model proves too narrow; revisit before Phase 6. | Inspect source tracking separately from include logic. |
| 5 | Fixes deterministic include target policy before recursive loading. | Leaves plugin/remote resolver contracts for later roadmap work. | Rejects extension probing and global search paths. | Resolution matrix is objectively testable. |
| 6 | Implements file-authored recursive composition. | Provides base for user swaps, manifests, and source artifacts. | Defers user composition overrides to Phase 7. | Recursive behavior isolated from public orchestration. |
| 7 | Adds user-defined composition after file-defined composition. | Preserves future CLI/sweep wrapping through the same API semantics. | Rejects brand-new bare include slots. | Integration tests show recomposition and override targeting. |
| 8 | Separates artifact-safe resolver scanning from runtime execution. | Leaves room for future custom resolver policy without leaking secrets now. | Rejects artifact-time resolver execution and custom resolvers. | Security-sensitive; tests must prove non-execution. |
| 9 | Makes recipes deterministic enough for artifact records. | Leaves recipe argument override syntax for later design. | Rejects ambient process-global catalog as deterministic path. | Expansion order and failure modes are testable. |
| 10 | Defines Loom/project validation ownership. | Keeps domain-neutral project configs possible. | Rejects YAML schema systems in v1. | Validation-boundary tests should be narrow and clear. |
| 11 | Keeps object construction separate while tightening import semantics. | Leaves pipeline/runtime object fingerprint policy outside config. | Rejects nested attribute lookup after final target. | Pure instantiation tests; no composition artifacts. |
| 12 | Wires public composition and inspection APIs. | Future CLI and sweeps wrap this path. | Defers final artifact population to avoid one broad PR. | Main orchestration PR; scope controlled by prior helpers. |
| 13 | Populates artifact-safe records, default source metadata/hash records, and redaction before fingerprints depend on them. | Run-store/resume/CLI can persist/inspect coherent records later. | Rejects resolved config persistence and raw source bytes by default. | Contract-heavy PR; verify no secret/runtime leaks and source-record references are stable. |
| 14 | Defines default config fingerprint and resume comparison semantics from Phase 13 artifact/source records. | Leaves opt-in runtime-value fingerprints for later policy. | Accepts no exact resolver replay by default. | Fingerprint matrix should make review objective. |
| 15 | Adds only raw snapshot opt-in behavior or records an explicit run-store-policy deferral. | Future run-store can persist opted-in raw payloads without changing default source-record contracts. | Rejects raw bytes by default. | Raw snapshot/dedupe behavior isolated from manifest/fingerprint defaults. |
| 16 | Consolidates docs, e2e, and final evidence. | Avoids promising deferred CLI/plugin/sweep/copy behavior. | No new features during hardening. | Evidence-focused final PR. |

### Phase 1 - Boundary And Artifact Contracts

Status: merged
Branch: `codex/config-boundary-artifact-contracts`
PR: https://github.com/samcantrill/loom/pull/23

Goal:

- Establish config/pipeline boundaries and plain artifact contract skeletons.

Scope:

- Add config/pipeline import-boundary tests.
- Define persistence-free config artifact return contracts.
- Add versioned manifest, source artifact, provenance, and fingerprint model
  skeletons as plain serializable data.
- Document no v1 CLI and no pipeline dependence on manifests.

Out of scope:

- Behavior-changing composition.
- Includes.
- Resolver execution.
- Run-store writes.
- CLI commands.

Acceptance criteria:

- `loom.pipeline` remains importable and constructible without `loom.config`.
- Minimal artifact records serialize as plain data with schema/version fields.
- Manifest records are documented as artifact contracts, not pipeline APIs.

Test expectations:

- Package/import tests.
- Contract serialization tests for empty or minimal artifact records.

Phase metadata:

- Worktree: `/home/samcantrill/work/loom-worktrees/config-boundary-artifact-contracts`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- Merge result: GitHub reports PR #23 merged into `develop` at
  `f146e1bc49cd49c069fbdd47491c61dbc2f8ef5f` on 2026-05-05 before the
  bounded phase PR review approved it.
- Implementation summary: added `loom.config.artifacts` skeleton contracts for
  `CompositionManifest`, `SourceArtifactRecord`, and
  `ConfigFingerprintRecord`; added unit/contract serialization coverage and
  import-boundary checks proving `loom.pipeline` remains independent from
  `loom.config`.
- Validation summary: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall suite
  status `passed`; GitHub CI check `checks` passed on PR #23.
- Blocking review finding: `CompositionManifest.__post_init__` did not validate
  or normalize nested plain data inside `recipe_manifest` when constructed
  directly. A local probe confirmed
  `CompositionManifest(schema_version=1, recipe_manifest=({"bad": {1, 2}},))`
  creates a record containing a `set`, violating the Phase 1 plain-data artifact
  contract.
- Blocker resolution: user authorized one scoped blocker-resolution subagent
  pass after the gate stopped. Follow-up PR
  https://github.com/samcantrill/loom/pull/24 merged into `develop` at
  `d9d45cddcb206ea480253d79fcd1dcff8c13c5fa` on 2026-05-05 after local
  validation and GitHub CI `checks` passed. The fix normalizes and freezes
  `recipe_manifest` during construction and rejects nested non-plain payloads
  with `ConfigProvenanceError`.
- Follow-up notes: later phases populate these skeletons; no compose, include,
  resolver, run-store, CLI, root-export, or `ComposedConfig` behavior was added
  in Phase 1. No remaining Phase 1 blockers prevent Phase 2.

### Phase 2 - Strict Loading And Structured Errors

Status: merged
Branch: `codex/config-loading-errors`
PR: https://github.com/samcantrill/loom/pull/25

Goal:

- Enforce v1 loading rules and structured error foundations.

Scope:

- Enforce single-document UTF-8 YAML.
- Require non-empty mapping roots.
- Preserve plain-data-only parsed values.
- Reject unsupported `_copy_` anywhere in authored config.
- Add or refine `ConfigError` subclasses with machine-readable context.

Out of scope:

- Includes.
- Overlays.
- Override application.
- Schema validation.
- Resolver execution.

Acceptance criteria:

- Loader failures include path/source context.
- `_copy_` fails explicitly as unsupported.
- Structured errors can be serialized or inspected without parsing strings.

Test expectations:

- Unit tests for loader failures, `_copy_` rejection, and structured error
  fields without resolved secret values.

Phase metadata:

- Worktree: `/home/samcantrill/work/loom-worktrees/config-loading-errors`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- Merge result: PR #25 merged into `develop` at
  `bc748ff58c61614bca1177de2bd1b1e8051e3b6d` on 2026-05-05 before the
  bounded phase PR review approved it.
- Implementation summary: added config-domain structured error context,
  context-bearing loader errors, single-document UTF-8 YAML enforcement,
  non-empty mapping-root enforcement, plain-data parsed values, and recursive
  `_copy_` unsupported-directive rejection.
- Validation summary: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall suite
  status `passed`; GitHub CI check `checks` passed on PR #25.
- Blocking review finding: recursive YAML aliases could trigger unstructured
  `RecursionError` during `_copy_` directive scanning before plain-data
  normalization. A self-referential alias such as `root: &root` with
  `child: *root` violated the Phase 2 structured loader-failure contract.
- Blocker resolution: user authorized one scoped post-merge blocker-resolution
  pass. Follow-up PR https://github.com/samcantrill/loom/pull/26 merged into
  `develop` at `e03f1c1dfd7426a5ffd962e90cb915267bcb3a15` on 2026-05-05
  after local validation and GitHub CI `checks` passed. The fix rejects
  recursive YAML aliases as structured `ConfigLoadError` values with
  `code="non_plain_data"` before directive scanning.
- Follow-up notes: no includes, overlays, override application, schema
  validation, resolver execution, persistence, CLI, manifest/provenance
  population, fingerprint behavior, or Phase 3+ semantics were added.

### Phase 3 - Overrides And Merge Primitives

Status: merged
Branch: `codex/config-overrides-merge`
PR: https://github.com/samcantrill/loom/pull/27

Goal:

- Implement strict override and merge primitives.

Scope:

- Strict `path=value` update overrides.
- Explicit `+path=value` add overrides.
- Typed override parsing.
- Simple dot paths with no escaping.
- Recursive mapping merge.
- Scalar/list/null replacement.
- Strict `_replace_` handling.

Out of scope:

- Include loading.
- Recipe expansion.
- Final `compose_config` orchestration.

Acceptance criteria:

- Update overrides fail on missing paths.
- Add overrides fail on existing paths.
- `_replace_` is required for discarded lower-precedence mappings and fails when
  unnecessary.
- Lists replace as whole lists.

Test expectations:

- Unit tests for parser behavior, strict/add overrides, invalid paths,
  `_replace_` required/unnecessary cases, and merge semantics.

Phase metadata:

- Worktree: `/home/samcantrill/work/loom-worktrees/config-overrides-merge`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- Merge result: PR #27 merged into `develop` at
  `362adf642170db274652b194b20b6592d2d8be71` on 2026-05-05 after PR review,
  blocker resolution, local validation, and GitHub CI `checks` passed.
- Implementation summary: added strict `_replace_` merge semantics, including
  root-level replacement, recursive mapping merge when `_replace_` is absent,
  scalar/list/null and type replacement behavior, marker validation and
  omission, nested marker handling inside replacement subtrees, input
  non-mutation, and focused strict override/merge coverage.
- Validation summary: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall suite
  status `passed`; GitHub CI check `checks` passed on PR #27.
- Blocking review finding: nested `_replace_` markers could leak into returned
  config when they appeared inside a whole-section replacement subtree.
- Blocker resolution: user authorized one scoped blocker-resolution pass on the
  open PR branch. Commit `ea42824d65f65f730b1bf1bb163c1caa35f7ffa5` prevents
  nested markers from leaking by consuming them when a corresponding
  lower-precedence mapping exists and rejecting them with `ConfigMergeError`
  otherwise; targeted tests, `make validate-pr`, `make test-summary`, and
  GitHub CI all passed afterward.
- Follow-up notes: override and merge errors remain message-only stable
  subclasses; no includes, source-authored overlays, recipe ordering changes,
  public inspection API, persistence, CLI, provenance population, fingerprints,
  `_copy_`, escaped-dot paths, list indexing, or list patching were added.

### Phase 4 - Source-Authored Overlays

Status: merged
Branch: `codex/config-source-overlays`
PR: https://github.com/samcantrill/loom/pull/28

Goal:

- Apply base plus ordered overlays while preserving source authorship.

Scope:

- Load overlays in user-provided order.
- Merge overlays one-by-one.
- Preserve source authorship metadata and path provenance context.
- Ensure overlay-authored values retain overlay file context for later include
  resolution.

Out of scope:

- Recursive includes.
- User include replacement.
- Recipes.
- Fingerprints.

Acceptance criteria:

- Overlay order is preserved exactly.
- Source maps identify whether values came from base or a specific overlay.
- Include-like values authored in overlays retain overlay source context.

Test expectations:

- Unit/integration tests for overlay order, source-map preservation, and
  overlay-authored source context.

Phase metadata:

- Worktree: `/home/samcantrill/work/loom-worktrees/config-source-overlays`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- Merge result: PR #28 merged into `develop` at
  `6b825fe971b1e2043861b84161b4ba2462813660` on 2026-05-05 after local
  validation, GitHub CI `checks` passed, and PR review found no blocking
  implementation issues. Live PR facts were verified with base `develop`, head
  `codex/config-source-overlays`, and state `MERGED`.
- Implementation summary: added internal immutable config path/source-map
  helpers for loaded base plus ordered overlays, threaded the source-aware
  overlay helper through `compose_config` without changing public
  `ComposedConfig` fields, and added unit/integration coverage for overlay
  order, source authorship, list/container coverage, `_replace_` replacement
  parity with `merge_configs`, and overlay-authored `_include_` values as
  ordinary data.
- Validation summary: `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr`
  passed; `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with
  overall 588 passed, 0 failed, 0 errors, 8 skipped, and 428 deselected.
  GitHub CI check `checks` passed on PR #28.
- Blocker resolution: the expanded-path implementation refinement fixed
  source-map `_replace_` replacement semantics to match Phase 3 `merge_configs`.
  A user-authorized PR-validation blocker pass then fixed a Pyright test-helper
  type issue and renamed the integration source-map test file to avoid pytest
  optional-suite module basename collisions.
- PR review: `loom_phase_reviewer` found no blocking implementation findings;
  the only note was process metadata staleness after PR #28 had already merged
  before the manager merge step.
- Follow-up notes: no include resolution, recursive includes, user include
  replacement, public inspection/source-map API, manifest/provenance population,
  fingerprint changes, raw source persistence, CLI behavior, pipeline imports,
  or root package exports were added.

### Phase 5 - Include Resolution Primitives

Status: merged
Branch: `codex/config-include-resolution`
PR: https://github.com/samcantrill/loom/pull/29
Follow-up PR: https://github.com/samcantrill/loom/pull/30

Goal:

- Resolve accepted include target forms strictly and deterministically.

Scope:

- Bare-name resolution from including file plus mapping key path.
- Exact relative paths.
- Exact absolute paths.
- `file://` URIs.
- `.yaml` bare-name behavior.
- No extension probing.
- Unsupported URI scheme failures.
- Resolver-dependent include target failures.

Out of scope:

- Recursive expansion.
- User-authored include replacement.
- Plugin/remote resolvers.

Acceptance criteria:

- Every accepted target form resolves deterministically.
- Explicit paths require exact filenames.
- Bare names append exactly `.yaml`.
- Ambiguous, missing, unsafe, unsupported, or resolver-dependent targets fail.

Test expectations:

- Unit tests for every target form and failure case, including unsafe
  normalization and missing/ambiguous targets.

PR-open notes:

- Phase execution plan: `docs/phases/config-include-resolution.md`.
- PR target: `develop`; stack predecessor: none.
- PR verification: `gh pr view 29 --json baseRefName,headRefName,state,url`
  returned `baseRefName` `develop`, `headRefName`
  `codex/config-include-resolution`, `state` `OPEN`, and URL
  `https://github.com/samcantrill/loom/pull/29`.
- Implementation summary: added internal include target resolution primitives,
  local-only `file://` handling, strict bare-name and explicit target
  classification, structured include-resolution errors, and phase-scoped
  unit/contract coverage. A user-authorized blocker pass added bare-name
  containment validation for normalized symlink escapes.
- Validation: `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed; `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed
  with overall 620 passed, 0 failed, 0 errors, 8 skipped, and 429 deselected.
- PR review: `loom_phase_reviewer` found one blocking `file://` decoded-path
  representability issue. The user-authorized blocker-resolution subagent fixed
  it, but PR #29 had already merged before that commit reached `develop`.
- Merge result: PR #29 merged into `develop` at 2026-05-05T08:49:43Z with
  merge commit `efa914c65e2f76967e3d945b934d56a3864fed7c`.
- Blocker follow-up: PR #30 cherry-picked the exact scoped fix onto updated
  `develop`; it merged at 2026-05-05T08:59:44Z with merge commit
  `5612c3b30dd6ef87a5be05e3223019389bf452d3`.
- Follow-up validation: PR #30 GitHub CI `checks` passed; local
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed; local
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall
  621 passed, 0 failed, 0 errors, 8 skipped, and 429 deselected.
- Follow-up notes: Phase 5 now rejects decoded `file://` paths with embedded
  NUL bytes before candidate validation using structured
  `ConfigIncludeResolutionError` context. No recursive include expansion, user
  include replacement, public inspection/source-map API, manifest/provenance
  population, fingerprint changes, raw source persistence, CLI behavior,
  pipeline imports, or root package exports were added.

### Phase 6 - File-Defined Recursive Includes

Status: merged
Branch: `codex/config-file-includes`
PR: https://github.com/samcantrill/loom/pull/31
Follow-up PR: https://github.com/samcantrill/loom/pull/32

Goal:

- Expand file-authored includes recursively under the strict decision tree.

Scope:

- Recursive include expansion.
- Include stacks.
- Cycle detection.
- Sibling merge and local customization records.
- Strict include replacement.
- Source-aware include errors.

Out of scope:

- User composition overrides.
- Recipes.
- Runtime interpolation.
- Raw source snapshots.

Acceptance criteria:

- Nested includes work.
- Include cycles fail with include-stack context.
- Sibling overrides are recorded.
- Include swaps over existing mapping content require same-site `_replace_`.

Test expectations:

- Unit/contract tests for nested includes, cycles, sibling overrides,
  replacement requirements, include stack records, and include provenance
  serialization.

PR-open notes:

- Phase execution plan: `docs/phases/config-file-includes.md`.
- PR target: `develop`; stack predecessor: none.
- PR verification: `gh pr view https://github.com/samcantrill/loom/pull/31
  --json baseRefName,headRefName,state,url` returned `baseRefName`
  `develop`, `headRefName` `codex/config-file-includes`, `state` `OPEN`,
  and URL `https://github.com/samcantrill/loom/pull/31`.
- Implementation summary: added internal file-authored recursive include
  expansion after source-aware file merge and before overrides/recipes,
  include stack/cycle diagnostics, source-aware include expansion errors,
  local customization/include-site records, and same-site `_replace_`
  enforcement for include swaps over existing mappings.
- Validation: `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall 639
  passed, 0 failed, 0 errors, 8 skipped, and 430 deselected.
- Scope notes: no user include swaps, recipes/order refactor, runtime
  interpolation changes, public inspection API, new public `ComposedConfig`
  fields, manifest/provenance/source-artifact/fingerprint population, raw
  source persistence, CLI behavior, pipeline imports, plugin/remote/global
  resolvers, or root package exports were added.
- PR review: `loom_phase_reviewer` found one blocking `_replace_` leakage
  issue for markers authored inside included files. The user-authorized
  blocker-resolution subagent fixed it, but PR #31 had already merged before
  that commit reached `develop`.
- Merge result: PR #31 merged into `develop` at 2026-05-05T09:53:09Z with
  merge commit `5b8229fedf3ec939b93351fbff503d35dbab9ee5`.
- Blocker follow-up: PR #32 cherry-picked the exact scoped fix onto updated
  `develop`; it merged at 2026-05-05T10:06:34Z with merge commit
  `a9ede97b26c37b3dcdab0db4bc34d2241d06e511`.
- Follow-up validation: PR #32 GitHub CI `checks` passed; local
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed; local
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall
  642 passed, 0 failed, 0 errors, 8 skipped, and 430 deselected.
- Follow-up notes: Phase 6 now rejects root and nested unconsumed `_replace_`
  markers authored inside included files, while preserving valid overlay
  same-site `_replace_: true` include swaps. No Phase 7+ scope was added.

### Phase 7 - User Composition Overrides

Status: merged
Branch: `codex/config-user-composition-overrides`
PR: https://github.com/samcantrill/loom/pull/33

Goal:

- Apply user-defined composition after file-defined composition.

Scope:

- Existing-site bare include replacement.
- Explicit brand-new user include sites only.
- Recomposed swapped component subtrees.
- Ordinary value override pass hooks for later expanded config updates.

Out of scope:

- Recipe expansion.
- Resolver execution.
- Final public compose orchestration.

Acceptance criteria:

- `path._include_=...` can replace an existing file-defined include site.
- Brand-new user include sites require explicit path, absolute path, or
  `file://`.
- Ordinary overrides can target values introduced by recomposed includes.

Test expectations:

- Integration tests for user include swaps, brand-new include restrictions,
  ordinary overrides targeting recomposed included values, and source-context
  errors.

Completion notes:

- Phase execution plan:
  `docs/phases/config-user-composition-overrides.md`.
- PR target: `develop`; stack predecessor: none; root phase PR was merged into
  `develop`.
- Implementation summary: adds the private user-composition stage between
  file-defined include expansion and ordinary value overrides. The phase
  partitions include-composition overrides from ordinary overrides, replaces
  exact recorded include sites with source-local context, replays local sibling
  customizations over replacement includes, supports brand-new explicit
  relative/absolute/`file://` include additions, rejects brand-new bare include
  targets, rejects `+` against existing include sites, and preserves ordinary
  override relative order after recomposition.
- Scope notes: no public root exports, new `ComposedConfig` fields,
  manifest/artifact/fingerprint/provenance population, CLI behavior, pipeline
  imports, resolver execution, recipe-ordering changes, or `_copy_` support
  were added.
- Validation: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall
  651 passed, 0 failed, 0 errors, 8 skipped, and 430 deselected. Focused
  Phase 7 targeted checks passed with 22 override/composition tests and
  73 broader config/import-boundary tests.
- PR review: `loom_phase_reviewer` found no blocking correctness, scope,
  import-boundary, domain-neutrality, or validation-evidence issues. The PR
  review budget is consumed.
- PR notes: opened and verified on 2026-05-05 as PR #33 with base `develop`
  and head `codex/config-user-composition-overrides`; GitHub CI `checks`
  passed, and the PR merged into `develop` at 2026-05-05T10:50:29Z with merge
  commit `e15279dee60920c8d943ecd9d3fbc1dbaaa3d89f`.
- Stack maintenance: no successor phase branch depended on
  `codex/config-user-composition-overrides` when the PR merged; branch and
  worktree cleanup are safe after this metadata update.

### Phase 8 - Resolver Security And Runtime Interpolation

Status: merged
Branch: `codex/config-resolver-security`
PR: https://github.com/samcantrill/loom/pull/34

Goal:

- Separate artifact-safe resolver handling from runtime interpolation.

Scope:

- Resolver-expression scanning.
- Artifact-safe no-execution paths.
- Runtime-only built-in OmegaConf resolver execution.
- `ConfigUnsupportedResolverError` for custom resolvers; this error must be both
  a `ConfigError` and a `NotImplementedError`.
- Failures for resolver-dependent composition control flow.

Out of scope:

- Recipes that depend on resolver values.
- Persisted resolved config.
- Secret-aware hashes.

Acceptance criteria:

- Artifact generation does not execute resolvers.
- Built-in resolvers can execute only in runtime resolution.
- Custom resolver-style interpolation fails with structured context.
- Resolver-dependent include or composition decisions fail.

Test expectations:

- Unit/integration tests proving no resolver execution during artifact
  generation, built-in runtime resolution, and custom resolver failure.

Completion notes:

- Phase execution plan: `docs/phases/config-resolver-security.md`.
- PR target: `develop`; stack predecessor: none; root phase PR was merged into
  `develop`.
- Implementation summary: adds private no-execution resolver scanning for
  authored resolver-expression metadata, enforces the Phase 8 runtime resolver
  allow-list of `oc.env` only, resolves `oc.env` through Loom-owned runtime
  code instead of OmegaConf's mutable global resolver registry, raises
  structured `ConfigUnsupportedResolverError` for custom and non-allow-listed
  resolver expressions before execution, and preserves the existing
  `ConfigIncludeResolutionError` / `resolver_dependent` contract for
  resolver-dependent include targets and user-composition include overrides.
- Scope notes: no public root exports, public `ComposedConfig` fields,
  manifest/source-artifact/fingerprint/provenance population, CLI behavior,
  pipeline imports, run-store writes, resolver plugins, remote resolvers,
  recipe behavior changes, or `_copy_` support were added.
- Validation: `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall
  667 passed, 0 failed, 0 errors, 8 skipped, and 431 deselected. Focused
  Phase 8 targeted checks passed with 24 resolver/error tests and 83
  include/recipe/compose/import tests.
- PR review: `loom_phase_reviewer` consumed the Phase 8 review budget after PR
  #34 merged and found one blocking issue: the initial allow-listed `oc.env`
  path still delegated execution to OmegaConf's mutable global resolver
  registry. The user-authorized blocker-resolution subagent fixed that issue in
  follow-up PR #35.
- Merge result: PR #34 merged into `develop` at 2026-05-05T11:30:58Z with
  merge commit `f297a48279351d81da87a7408801c6a647e54cd8`; GitHub CI check
  `checks` passed.
- Blocker follow-up: PR https://github.com/samcantrill/loom/pull/35 merged
  into `develop` at 2026-05-05T11:52:47Z with merge commit
  `afa85f8ede952b87504726de09e9f877cec376e0`; GitHub CI check `checks`
  passed. The follow-up added regression coverage proving global replacement
  of OmegaConf's `oc.env` resolver is not executed by `resolve_interpolation()`
  or public `compose_config()`.
- Stack maintenance: no successor phase branch depended on
  `codex/config-resolver-security` or
  `codex/config-resolver-security-ocenv-blocker` when PR #35 merged; branch and
  worktree cleanup are safe after this metadata update.

### Phase 9 - Recipe Catalog And Expansion

Status: merged
Branch: `codex/config-recipes-catalog`
PR: https://github.com/samcantrill/loom/pull/36

Goal:

- Harden recipe expansion around explicit catalogs and artifact-safe behavior.

Scope:

- Explicit `RecipeCatalog` composition paths.
- Recipe expansion as file-defined behavior.
- Expansion before ordinary user value overrides.
- Artifact-safe recipe records.
- Rejection of pre-expansion recipe argument override syntax.
- Rejection of resolver-dependent recipe output shape.

Out of scope:

- Ambient process-global recipe reliance for deterministic rebuildability.
- Recipe argument override syntax.
- Sandboxing trusted recipe code.

Acceptance criteria:

- Recipes expand before ordinary value overrides.
- Ordinary overrides target expanded concrete paths.
- Recipe records preserve unresolved resolver expressions as authored text.
- Recipes that require resolver outputs for output shape fail.

Test expectations:

- Unit/integration tests for explicit catalog use, expansion order,
  artifact-safe output hashes, override-after-expansion behavior, and
  resolver-dependent shape failure.

Completion notes:

- Phase execution plan: `docs/phases/config-recipes-catalog.md`.
- PR target: `develop`; stack predecessor: none; root phase PR was merged into
  `develop`.
- Implementation summary: reorders composition so include expansion and user
  composition overrides run before recipe expansion, ordinary overrides apply
  to recipe-expanded concrete paths, recipe argument handling preserves authored
  resolver-style expressions for artifact-safe records and hashes, and recipe
  expansion rejects resolver-shaped output keys before producing successful
  artifacts.
- Scope notes: explicit `RecipeCatalog` composition remains the deterministic
  v1 path while existing default-catalog and `register_recipe(...)`
  compatibility remain intact. No CLI behavior, pipeline imports, run-store
  writes, public inspection fields, source-artifact or fingerprint population,
  resolver-output or raw-source persistence, `_copy_`, plugin/remote behavior,
  or recipe sandboxing were added.
- Validation: targeted Phase 9 suite passed with 97 tests;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall
  677 passed, 0 failed, 0 errors, 8 skipped, and 431 deselected.
- PR review: `loom_phase_reviewer` consumed the Phase 9 PR review budget after
  PR #36 merged and found no blocking correctness, scope, import-boundary, or
  test-evidence issues. The only residual risk is the documented conservative
  resolver-dependent shape detection for opaque trusted Python recipes.
- Merge result: PR #36 merged into `develop` at 2026-05-05T12:30:17Z with
  merge commit `b3f579cc8c719e526915f902960b1a47ee5018a8`; GitHub CI check
  `checks` passed.
- Stack maintenance: no successor phase branch depended on
  `codex/config-recipes-catalog` when PR #36 merged; branch and worktree
  cleanup are safe after this metadata update.

### Phase 10 - Loom Validation Boundaries

Status: merged
Branch: `codex/config-validation-boundaries`
PR: https://github.com/samcantrill/loom/pull/37

Goal:

- Validate only `loom`-owned boundaries and preserve project-owned pass-through
  data.

Scope:

- Stable Loom-owned envelope/contract validation only when an explicit Loom
  envelope or artifact record is present.
- Removal, narrowing, or replacement of generic top-level `name` plus
  `pipeline` validation from the public `compose_config` path.
- Project/stage config pass-through for generic composition inputs.
- Rejection of YAML `_schema_`, project schema registries, and automatic
  `_target_` schema inference.
- Structured validation errors with source context.

Out of scope:

- Project-specific validation systems.
- CLI UX.
- Pipeline dependence on config.

Acceptance criteria:

- Generic project configs can compose without top-level `name`, `pipeline`, or
  `schema_version`.
- Unknown keys fail only inside explicit Loom-owned pipeline envelopes, stage
  specs, artifact/input/output specs, recipe contracts, and artifact record
  schemas.
- Project-owned mappings pass through globally unless they contain a reserved
  Loom directive key whose owning phase must validate it.
- Exact authored `_schema_` keys fail as unsupported schema-authoring
  directives.
- `_target_` nodes are not used for composition-time schema inference.

Test expectations:

- Unit/integration tests for Loom-owned validation, project-owned pass-through
  without `name`/`pipeline`, schema-feature rejection, `_target_` inference
  non-behavior, and structured validation errors.

Completion notes:

- Phase execution plan: `docs/phases/config-validation-boundaries.md`.
- PR target: `develop`; stack predecessor: none; root phase PR was merged into
  `develop`.
- Revised workflow gate: the pre-submit blocker gate ran before PR submission
  and found no blocking correctness, scope, import-boundary, test-evidence, or
  PR-body accuracy issues. It consumed the Phase 10 PR-review budget for the
  current implementation diff, PR body draft, suite evidence, scope boundary,
  and known review risks.
- Implementation summary: removes implicit top-level `name`/`pipeline`/schema
  defaulting from public composition, keeps generic project payloads
  pass-through for redaction/provenance/fingerprints, rejects authored
  `_schema_` alongside existing `_copy_` unsupported directive checks with
  source-aware structured context, keeps `_target_` inert during composition,
  and lets `ConfigValidationError` carry structured context.
- Scope notes: no `loom.pipeline` imports, project schema API, CLI behavior,
  public inspection fields, persistence, `_copy_` support, raw source or
  resolver-output persistence, plugin/remote behavior, run-store writes, or
  Phase 11 instantiation behavior were added.
- Validation: targeted Phase 10 groups passed with 47 and 38 tests;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall
  685 passed, 0 failed, 0 errors, 8 skipped, and 432 deselected.
- Merge result: PR #37 merged into `develop` at 2026-05-05T13:18:49Z with
  merge commit `66ef93b71e831d658942479b6e6e12aabe624423`; GitHub CI check
  `checks` passed.
- Stack maintenance: no successor phase branch depended on
  `codex/config-validation-boundaries` when PR #37 merged. The GitHub merge
  command merged the PR but could not delete the local branch while its
  worktree was attached; branch and worktree cleanup are safe after this
  metadata update.

### Phase 11 - Strict Instantiation And Runtime Injection

Status: merged
Branch: `codex/config-instantiation-strict`
PR: https://github.com/samcantrill/loom/pull/38

Goal:

- Keep instantiation separate while tightening target and injection behavior.

Scope:

- Strict dotted and colon `_target_` forms.
- No nested object lookup after final class segment or colon target.
- Bottom-up recursive construction.
- `_partial_`.
- `_inject_` duplicate and missing key checks.

Out of scope:

- Pipeline/runtime object fingerprint policy implementation.
- Composition artifact fingerprints.

Acceptance criteria:

- Accepted import forms work.
- Invalid target forms fail clearly.
- Nested targets construct bottom-up.
- Runtime injection failures are explicit.

Test expectations:

- Unit tests for import forms, invalid targets, bottom-up construction order,
  partial construction, and injection errors.

Completion notes:

- Phase execution plan: `docs/phases/config-instantiation-strict.md`.
- PR target: `develop`; stack predecessor: none; root phase PR was merged into
  `develop`.
- Revised workflow gate: the pre-submit blocker gate ran before PR submission
  and found no blocking or non-blocking correctness, scope, import-boundary,
  test-evidence, or PR-body accuracy issues. It consumed the Phase 11 PR-review
  budget for the current implementation diff, PR body draft, suite evidence,
  scope boundary, and known review risks.
- Implementation summary: keeps runtime object construction on the explicit
  `loom.config.instantiate(...)` path, preserves strict dotted and colon
  `_target_` import semantics without nested lookup or fallback splitting,
  verifies bottom-up nested construction and `_partial_` behavior, and tightens
  `_inject_` runtime validation for invalid shapes, duplicate keys, missing
  runtime values, and falsey non-mapping runtime inputs.
- Scope notes: no compose-time instantiation, `loom.pipeline` imports,
  registries, allow-lists, plugin/global target lookup, CLI behavior,
  persistence, artifact/fingerprint/source-record changes, `_copy_` support, or
  future-phase orchestration/inspection behavior were added.
- Validation: targeted Phase 11 import, recursive, injection, package/import
  boundary, and compose `_target_` guard tests passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall 698
  passed, 0 failed, 0 errors, 8 skipped, and 432 deselected.
- Merge result: PR #38 merged into `develop` at 2026-05-05T13:57:08Z with
  merge commit `68b7ec02753fd02640cace4ec05fd96e2dc1ee14`; GitHub CI check
  `checks` passed.
- Stack maintenance: no successor phase branch depended on
  `codex/config-instantiation-strict` when PR #38 merged. The GitHub merge
  command merged the PR but could not delete the local branch while its
  worktree was attached; branch and worktree cleanup are safe after this
  metadata update.

### Phase 12 - Public Compose Orchestration And Inspection APIs

Status: merged
Branch: `codex/config-compose-orchestration`
PR: https://github.com/samcantrill/loom/pull/39

Goal:

- Wire the complete public `compose_config` order using prior phases.

Scope:

- Full staged composition order.
- Simple public `compose_config`.
- Public `inspect_config_composition` API for intermediate stages.
- Additive v1 `ComposedConfig` fields: `unresolved`, `manifest`,
  `source_artifacts`, and `fingerprint_records`, while preserving existing
  `resolved`, `redacted`, `provenance`, `recipe_manifest`, and `fingerprint`
  names.
- Config/pipeline independence.
- Persistence-free config artifact return shape.

Out of scope:

- Final manifest/fingerprint population.
- Raw source snapshot opt-in.
- CLI commands.

Acceptance criteria:

- Full order works through includes, user composition overrides, recipes,
  ordinary value overrides, validation, runtime interpolation, and optional
  instantiation.
- `inspect_config_composition` exposes stable additive stage records without
  leaking unstable internals.
- `ComposedConfig` compatibility tests prove existing fields still work and new
  v1 artifact fields are present.
- Pipeline remains independent.

Test expectations:

- Package/API tests.
- Integration tests for full order through recipes and runtime resolution.
- Inspection API contract tests.
- Import-boundary tests.

Completion notes:

- Phase execution plan: `docs/phases/config-compose-orchestration.md`.
- PR target: `develop`; stack predecessor: none; root phase PR was merged into
  `develop`.
- Revised workflow gate: the pre-submit blocker gate ran before PR submission
  and found one blocker: inspection contract coverage was claimed in the PR
  body but was not included in final suite evidence. A scoped
  blocker-resolution pass marked the inspection contract test as
  `contract`/`optional_dependency`, reran validation, refreshed the PR body and
  phase notes, and confirmation review found no remaining blockers. The
  pre-submit gate consumed the Phase 12 PR-review budget for the current
  implementation diff, PR body, suite evidence, scope boundary, and known
  review risks.
- Implementation summary: adds public `inspect_config_composition(...)`,
  `ConfigCompositionInspection`, and `ConfigCompositionStageRecord`; routes
  public composition and inspection through the same staged full-order flow;
  extends `ComposedConfig` additively with `unresolved`, `manifest`,
  `source_artifacts`, and `fingerprint_records`; and keeps Phase 12 artifact
  fields as placeholders for later population phases.
- Scope notes: no final manifest/source/fingerprint/redaction/provenance
  population, raw source snapshots, resolver-output persistence, default
  instantiation, pipeline imports, CLI behavior, store writes, plugin/remote
  include behavior, `_copy_` support, or broader resolver/include/target
  semantics were added.
- Validation: targeted package/API/import-boundary, unit compose,
  config-extra inspection contract, integration config/pipeline, and existing
  e2e checks passed; `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall 703
  passed, 0 failed, 0 errors, 9 skipped, and 432 deselected.
- Merge result: PR #39 merged into `develop` at 2026-05-05T14:48:03Z with
  merge commit `16cc13cb15643b0ef113af2d67f2bc44b5b479ae`; GitHub CI check
  `checks` passed.
- Stack maintenance: no successor phase branch depended on
  `codex/config-compose-orchestration` when PR #39 merged. The GitHub merge
  command merged the PR but could not delete the local branch while its
  worktree was attached; branch and worktree cleanup are safe after this
  metadata update.

### Phase 13 - Provenance, Manifest, Source Records, And Redaction Population

Status: merged
Branch: `codex/config-manifest-provenance`
PR: https://github.com/samcantrill/loom/pull/40

Goal:

- Populate artifact-safe provenance, default source metadata/hash records,
  manifest, and redacted artifact records.

Scope:

- Source/order/include/override/recipe/resolver/security facts.
- Default source metadata and content-hash records for base configs, overlays,
  includes, and recipe source references where available.
- Versioned composition manifest.
- Manifest references to source artifact records.
- Default unresolved/redacted config artifact.
- Warnings/docs for plaintext secrets in overrides.

Out of scope:

- Fingerprint comparison logic.
- Raw source bytes by default.
- Raw snapshot opt-in and dedupe behavior.
- Resolved config persistence.

Acceptance criteria:

- Manifest records all artifact-safe composition decisions needed for later
  resume and CLI inspection.
- Manifest references the default source metadata/hash records it depends on.
- Default artifact records contain no resolved runtime values.
- Redaction applies before serializing sensitive authored paths.

Test expectations:

- Contract tests for manifest/provenance records.
- Contract tests for default source artifact records and manifest references.
- Redaction tests.
- No-resolved-runtime-values artifact tests.
- Docs snippets for secret handling.

Completion notes:

- Phase execution plan: `docs/phases/config-manifest-provenance.md`.
- PR target: `develop`; stack predecessor: none; root phase PR was merged into
  `develop`.
- Revised workflow gate: the pre-submit blocker gate ran before PR submission
  and found two blockers. First, user include replacement/addition source
  records could retain stale file-authored include references or omit added
  includes. Second, artifact-facing provenance/manifest override metadata could
  expose raw plaintext secret values, including nested JSON secret-like values.
  The user-authorized scoped blocker-resolution pass fixed both blockers, and a
  bounded confirmation gate passed with no remaining blocking findings.
- Implementation summary: populates artifact-safe source metadata/hash records
  for base, overlay, include, and safe recipe sources; builds composition
  manifest references and provenance metadata from the effective composition
  facts; emits default unresolved/redacted artifact views without raw source
  bytes or resolved resolver outputs; keeps user include source records aligned
  after include replacements/additions; and redacts raw plaintext secret
  override strings and nested secret-like override values while continuing to
  accept plaintext overrides.
- Scope notes: no Phase 14 resume comparison/fingerprint comparison algorithm,
  Phase 15 raw source snapshot opt-in/dedupe behavior, persistence, run-store or
  CLI behavior, pipeline imports, `_copy_`, plugin/remote/global include
  resolvers, resolved config persistence, or raw source-byte default artifacts
  were added.
- Validation: targeted Phase 13 package/import-boundary, unit config
  artifact/provenance/redaction/compose, contract artifact/inspection, and
  config integration provenance suites passed with 100 tests;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` passed;
  `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` passed with overall 711
  passed, 0 failed, 0 errors, 9 skipped, and 432 deselected.
- Pre-merge target check: PR #40 was verified immediately before merge with
  base `develop`, head `codex/config-manifest-provenance`, state `OPEN`, clean
  merge state, and successful GitHub CI `checks`. A formal GitHub approval
  review could not be posted because GitHub does not allow the PR author to
  approve their own PR; the focused confirmation gate supplied the workflow
  review approval.
- Merge result: PR #40 merged into `develop` at 2026-05-05T15:57:54Z with
  merge commit `389161f6102e12e7f4c7a1b55d42144e06c01f04`; GitHub CI check
  `checks` passed.
- Stack maintenance: no successor phase branch depended on
  `codex/config-manifest-provenance` when PR #40 merged. The GitHub merge
  command merged the PR but could not delete the local branch while its
  worktree was attached; branch and worktree cleanup are safe after this
  metadata update.

### Phase 14 - Artifact-Safe Fingerprints And Resume Comparison

Status: pending
Branch: `codex/config-artifact-fingerprints`
PR: pending

Goal:

- Compute artifact-safe fingerprints and compare authored composition for resume
  checks.

Scope:

- Fingerprints before resolver execution.
- Source hashes from Phase 13 source artifact records.
- Stable composition context.
- Unresolved expanded config.
- Resolver expressions as authored text.
- Redacted or allowed override facts.
- Authored-composition resume comparison helpers if kept in v1 scope.

Out of scope:

- Exact runtime-value replay.
- Secret-aware opt-in fingerprints.
- Run-store persistence.

Acceptance criteria:

- Fingerprints change for meaningful authored composition changes.
- Fingerprints do not change solely because machine-local absolute path context
  changes.
- Resolver outputs are excluded by default.
- Resume comparison distinguishes authored-composition match from runtime-value
  replay.

Test expectations:

- Unit/contract tests for fingerprint stability and change cases,
  resolver-output exclusion, path portability, and resume comparison outcomes.

### Phase 15 - Raw Snapshot Opt-In And Source Artifact Hardening

Status: pending
Branch: `codex/config-source-artifacts`
PR: pending

Goal:

- Define explicit raw snapshot behavior and harden source artifact limitations
  after default source metadata/hash records are already populated.

Scope:

- Backward-compatible extension of Phase 13 source artifact records.
- Manifest references to raw snapshot availability or explicit deferral.
- Duplicate-source handling.
- Explicit raw source snapshot opt-in, or clear deferral to run-store security
  policy.

Out of scope:

- Default raw source-byte persistence.
- Run directory writes.
- Remote/plugin sources.

Acceptance criteria:

- Default source metadata/hash records are already populated by Phase 13 and
  remain backward-compatible.
- Raw snapshot opt-in, if implemented, can reconstruct missing authored source
  files for supported local/file sources.
- Duplicate raw payloads are deduped when raw snapshots are enabled.

Test expectations:

- Unit/contract tests for raw snapshot fields, manifest references, dedupe,
  opt-in raw payload behavior if implemented, and metadata-only rebuild
  limitations.

### Phase 16 - Hardening, Documentation, And End-To-End Coverage

Status: pending
Branch: `codex/harden-config-composition-v1`
PR: pending

Goal:

- Harden full v1 behavior, update docs, and close reviewability gaps.

Scope:

- Feature docs and examples.
- Alignment updates for `docs/features/config.md`, `docs/features/provenance.md`,
  `docs/features/fingerprints.md`, `docs/features/resume.md`, and
  `docs/features/testing.md` where v1 changes accepted behavior.
- End-to-end composition coverage.
- Error audit.
- Security and resume limitation docs.
- Final validation evidence.

Out of scope:

- Public CLI behavior.
- Plugin discovery.
- Remote include sources.
- Sweeps.
- `_copy_`.

Acceptance criteria:

- Docs cover supported v1 behavior only.
- Existing feature docs no longer promise `_copy_` in v1, default raw source
  snapshots, default resolved-config persistence, or pipeline dependence on
  config artifacts.
- E2E tests cover representative strict composition flows.
- Limitations around resolver values, raw source snapshots, and resume are clear.
- `make validate-pr` and `make test-summary` pass.

Test expectations:

- Final import/public API checks.
- Regression coverage from implementation.
- Contract tests for manifest/provenance/source artifact serialization.
- Realistic domain-neutral integration and e2e composition flows.

## Test Structure And Fixtures

Tests should mirror config package ownership and avoid monolithic catch-all test
files.

Expected unit layout:

```text
tests/unit/loom/config/
  test_artifacts.py
  test_compose.py
  test_errors.py
  test_include_resolution.py
  test_includes.py
  test_instantiation.py
  test_interpolation.py
  test_manifest.py
  test_merge.py
  test_overlays.py
  test_overrides.py
  test_provenance.py
  test_recipes.py
  test_source_artifacts.py
  test_validation.py
```

If v0 already owns files such as `test_load.py`, `test_redaction.py`, recipe
tests, or instantiation tests, v1 should extend existing source-mirrored files
rather than duplicate coverage.

Expected integration layout:

```text
tests/integration/config/
  test_compose_full_order.py
  test_compose_includes.py
  test_compose_overrides.py
  test_compose_provenance.py
  test_compose_resolvers.py
  test_compose_validation.py
```

Fixture strategy:

- Generated temporary YAML is the default.
- Checked-in golden fixture trees are allowed only when file layout is part of
  behavior, such as bare-name resolution, relative paths, `file://`, source
  hashes, and provenance stack assertions.
- Shared helpers belong under `tests/support`.
- Fixture data must stay domain-neutral.
- Tests must not import downstream project packages, use network access, depend
  on plugin discovery, or require Hydra behavior.

## Overall Test Plan

Unit tests should cover:

- loader rules and single-document YAML failures;
- structured `ConfigError` subclasses and context;
- strict update and `+` add overrides;
- override value parsing;
- recursive mapping merge and `_replace_`;
- ordered overlay application and source authorship;
- include target resolution;
- recursive include expansion and include stacks;
- user include replacement;
- resolver scanning and runtime-only built-in resolution;
- custom resolver `ConfigUnsupportedResolverError` and `NotImplementedError`
  compatibility;
- explicit recipe catalog behavior and expansion order;
- validation boundaries and project pass-through;
- `_target_` import forms and bottom-up instantiation;
- `_inject_` errors;
- manifest/provenance/source artifact serialization;
- artifact-safe fingerprints and resume comparison;
- no-resolved-secret artifact persistence.

Integration tests should cover:

- complete `compose_config` flow with base config, overlays, strict/add
  overrides, includes, recipes, interpolation, validation, redaction, provenance,
  manifest, source artifacts, and fingerprints;
- base config includes and overlay includes resolving relative to their authored
  files;
- user include replacement after file-defined composition;
- ordinary overrides targeting values introduced by includes and recipes;
- built-in resolver runtime resolution without artifact-time execution;
- custom resolver failure;
- recipe expansion before ordinary value overrides;
- project-owned pass-through validation;
- source metadata/hash changes affecting artifact-safe fingerprints;
- resume comparison distinguishing authored composition from runtime-value
  replay.

End-to-end tests should:

- use public `compose_config` with small synthetic domain-neutral config trees;
- assert the artifact-safe config is self-contained and contains no `_include_`,
  `_replace_`, or `_copy_` markers;
- assert path-aware errors for missing includes, include cycles, add/update
  override misuse, unsupported `_copy_`, custom resolvers, and include swaps
  without `_replace_`;
- avoid running stages or requiring CLI behavior.

Validation gates:

```sh
make validate-pr
make test-summary
```

## Plan Quality Gate

Status: passed on 2026-05-05 by `loom_plan_reviewer` confirmation review; no
blocking findings remain.

Gate budget status:

- Initial `loom_plan_reviewer` review: used on 2026-05-05.
- Automated plan refinement pass: used on 2026-05-05.
- Confirmation review: used on 2026-05-05; no findings.

Initial review findings addressed by the refinement pass:

- Moved default source metadata/hash record population into Phase 13 so
  manifest and fingerprint phases do not back-edit public-ish artifact
  contracts.
- Defined the additive v1 `ComposedConfig` field shape and the public
  `inspect_config_composition` inspection API.
- Made Loom-owned validation boundaries concrete, including removal or narrowing
  of unconditional top-level `name`/`pipeline` validation for generic project
  configs.
- Resolved the custom resolver exception contract with
  `ConfigUnsupportedResolverError`, a structured config error that is also a
  `NotImplementedError`.
- Aligned roadmap planning-note metadata with the implementation-plan handoff.

Before implementation starts, review this v1 plan for:

- config/pipeline boundary preservation;
- deterministic include resolution;
- strict composition order;
- artifact-safe resolver behavior;
- provenance and manifest completeness without resolved-value leaks;
- scoped validation boundaries;
- compatibility with v0 config composition;
- source artifact and resume limitations;
- future compatibility with CLI, sweeps, plugins, and remote URI work;
- accepted technical debt;
- phase reviewability; and
- suite-level test strategy.

## Accepted Debt

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No `_copy_` in v1 | Keeps v1 focused on strict includes, component swaps, artifacts, and security. | Strict include/replacement/source artifact behavior is implemented and reviewed. |
| No global search path or plugin include resolvers | Keeps v1 deterministic and avoids premature extension APIs. | Plugin discovery or remote store roadmap work defines explicit resolver contracts. |
| Lists replace as whole lists | Avoids inventing a list patch language in v1. | A concrete workflow needs reviewable list mutation semantics. |
| Raw source bytes are not persisted by default | Preserves security because authored YAML and overrides may contain inline secrets. | A user needs exact rebuildability after source files disappear and accepts explicit raw-source persistence risk. |
| Exact runtime resolver values are not replayable from default config artifacts | Avoids persisting env secrets and runtime values. | A later opt-in secret-aware fingerprint or resolved persistence policy is designed. |
| V1 is Python-API-only | Keeps core behavior clean before CLI UX decisions. | V2 CLI planning begins. |

## Assumptions And Defaults

- V1 begins after v0 config composition, merge, provenance, redaction,
  fingerprints, recipe expansion, and v0-post hardening are complete.
- Authored configs are trusted project code.
- Local filesystem and `file://` include resolution are required.
- Other URI schemes and custom include resolvers are deferred.
- `_replace_` is the only v1 merge marker.
- Normal overrides update existing paths; `+` overrides add missing paths.
- Dot-path override syntax has no literal-dot escaping in v1.
- Typed models remain internal validation contracts for `loom`-owned sections,
  not a YAML schema authoring feature.
- Project/stage configs remain project-owned plain data unless explicitly inside
  a Loom-owned boundary.
- Lists replace as whole lists.
- Built-in OmegaConf resolvers may execute only during runtime resolution by
  default.
- Custom OmegaConf-style resolvers are deferred and raise
  `ConfigUnsupportedResolverError`, which is also catchable as
  `NotImplementedError`, in v1.

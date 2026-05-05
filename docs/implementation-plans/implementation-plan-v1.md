# Implementation Plan v1

## Metadata

- Status: draft implementation plan
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
- Plan quality gate: pending `loom_plan_reviewer`
- Blockers: none recorded; phase execution must not begin until the plan quality
  gate passes

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
- Custom resolver-style interpolation raises `NotImplementedError` in v1.
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

V1 should also expose deliberately scoped lower-level inspection APIs for
intermediate composition stages. These APIs should return stable records or
plain serializable data suitable for debugging, tests, reviews, and future CLI
inspection. They must not become a dependency of `loom.pipeline`.

If `ComposedConfig` needs new fields, prefer explicit artifact data such as:

- unresolved expanded config;
- in-memory runtime-resolved config;
- redacted artifact config;
- composition manifest;
- provenance records;
- source artifact records;
- artifact-safe fingerprint records.

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
custom resolver should raise `NotImplementedError` with structured context.

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

Stable schema validation remains scoped to `loom`-owned envelopes and contracts:

- pipeline config envelopes, if any are owned by `loom`;
- stage specs;
- artifact/input/output specs;
- recipe argument contracts;
- composition manifest records;
- provenance records;
- source artifact records;
- fingerprint records.

Project experiment and stage config files may be composed as plain data, but
project-owned mappings are not globally validated by `loom`. There is no YAML
`_schema_`, project schema registry, project schema import from config, or
automatic `_target_` schema inference in v1.

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
- custom resolver-style interpolation;
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
| 8. Resolver security and runtime interpolation | Artifact paths scan but do not execute resolvers; built-in resolvers execute only at runtime; custom resolvers fail; resolver-dependent composition control flow fails. | Resolver scanner, no-execution sentinel resolver tests, built-in runtime resolution, custom resolver `NotImplementedError`, resolver-dependent include failure. | Integration tests proving artifacts/fingerprints preserve expressions and omit resolved values. |
| 9. Recipe catalog and expansion | Explicit catalogs are preferred for deterministic composition; recipes expand before ordinary value overrides; pre-expansion arg overrides and resolver-dependent recipe shape fail. | Catalog lookup, expansion order, override-after-expansion, artifact-safe args/output hashes, failure cases. | Integration tests with include + recipe + ordinary override order; contract tests for recipe manifest records. |
| 10. Loom validation boundaries | Only Loom-owned envelopes/contracts validate; project/stage mappings pass through; YAML `_schema_`, project schema registries, and automatic `_target_` schema inference are unsupported. | Loom-owned unknown-key failure, project pass-through, schema feature rejection, structured validation context. | Integration tests after include/override composition; no e2e until public compose is wired. |
| 11. Strict instantiation and runtime injection | Instantiation is separate; dotted/colon targets only; no nested lookup beyond final class/colon target; nested targets construct bottom-up; `_inject_` checks duplicates/missing keys. | Import form matrix, invalid target forms, bottom-up order, `_partial_`, `_inject_` duplicate/missing errors. | Integration only if existing instantiation public path needs full config inputs; no artifact contract changes. |
| 12. Public compose orchestration and inspection APIs | `compose_config` executes the full accepted order; lower-level inspection APIs expose stable stage records; pipeline and persistence boundaries hold. | Orchestration collaborator tests and inspection API shape tests. | Package/API tests, full-order integration tests through runtime resolution, import-boundary tests; limited e2e through public `compose_config`. |
| 13. Provenance, manifest, and redaction population | Artifact-safe provenance and manifest records explain composition without resolved runtime values; redaction applies before artifact serialization; plaintext-secret override warnings are documented. | Redaction rules, resolver-value omission, provenance population for includes/overrides/recipes/schema boundaries. | Contract tests for manifest/provenance serialization; integration tests for artifact output from public compose. |
| 14. Artifact-safe fingerprints and resume comparison | Fingerprints are computed before resolver execution from artifact-safe inputs; abs paths are provenance context only; resume compares authored composition, not runtime values. | Fingerprint stability/change matrix, path portability, resolver-output exclusion, redacted override handling. | Contract tests for fingerprint records and resume comparison results; integration tests for changed included files/overrides. |
| 15. Source artifacts and raw snapshot opt-in | Source metadata/hashes are default; raw source bytes are opt-in or deferred to run-store policy; duplicate raw payloads dedupe when enabled. | Source hash determinism, changed-source hashes, duplicate handling, opt-in raw payload behavior if implemented. | Contract tests for source artifact records and manifest references; integration tests for metadata-only equivalence checks; no default raw-byte e2e. |
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
| 13 | Populates artifact-safe records and redaction. | Run-store/resume/CLI can persist/inspect records later. | Rejects resolved config persistence by default. | Contract-heavy PR; verify no secret/runtime leaks. |
| 14 | Defines default config fingerprint and resume comparison semantics. | Leaves opt-in runtime-value fingerprints for later policy. | Accepts no exact resolver replay by default. | Fingerprint matrix should make review objective. |
| 15 | Adds source identity and optional raw snapshot behavior. | Future run-store can persist returned records directly. | Rejects raw bytes by default. | Source hashing/dedupe behavior isolated. |
| 16 | Consolidates docs, e2e, and final evidence. | Avoids promising deferred CLI/plugin/sweep/copy behavior. | No new features during hardening. | Evidence-focused final PR. |

### Phase 1 - Boundary And Artifact Contracts

Status: pending
Branch: `codex/config-boundary-artifact-contracts`
PR: pending

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

### Phase 2 - Strict Loading And Structured Errors

Status: pending
Branch: `codex/config-loading-errors`
PR: pending

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

### Phase 3 - Overrides And Merge Primitives

Status: pending
Branch: `codex/config-overrides-merge`
PR: pending

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

### Phase 4 - Source-Authored Overlays

Status: pending
Branch: `codex/config-source-overlays`
PR: pending

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

### Phase 5 - Include Resolution Primitives

Status: pending
Branch: `codex/config-include-resolution`
PR: pending

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

### Phase 6 - File-Defined Recursive Includes

Status: pending
Branch: `codex/config-file-includes`
PR: pending

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

### Phase 7 - User Composition Overrides

Status: pending
Branch: `codex/config-user-composition-overrides`
PR: pending

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

### Phase 8 - Resolver Security And Runtime Interpolation

Status: pending
Branch: `codex/config-resolver-security`
PR: pending

Goal:

- Separate artifact-safe resolver handling from runtime interpolation.

Scope:

- Resolver-expression scanning.
- Artifact-safe no-execution paths.
- Runtime-only built-in OmegaConf resolver execution.
- `NotImplementedError` for custom resolvers.
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

### Phase 9 - Recipe Catalog And Expansion

Status: pending
Branch: `codex/config-recipes-catalog`
PR: pending

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

### Phase 10 - Loom Validation Boundaries

Status: pending
Branch: `codex/config-validation-boundaries`
PR: pending

Goal:

- Validate only `loom`-owned boundaries and preserve project-owned pass-through
  data.

Scope:

- Stable Loom-owned envelope/contract validation.
- Project/stage config pass-through.
- Rejection of YAML `_schema_`, project schema registries, and automatic
  `_target_` schema inference.
- Structured validation errors with source context.

Out of scope:

- Project-specific validation systems.
- CLI UX.
- Pipeline dependence on config.

Acceptance criteria:

- Unknown keys fail only inside Loom-owned schemas.
- Project-owned mappings pass through globally.
- Schema-authoring features are rejected or ignored as unsupported according to
  their exact authored form.

Test expectations:

- Unit/integration tests for Loom-owned validation, project-owned pass-through,
  schema-feature rejection, and structured validation errors.

### Phase 11 - Strict Instantiation And Runtime Injection

Status: pending
Branch: `codex/config-instantiation-strict`
PR: pending

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

### Phase 12 - Public Compose Orchestration And Inspection APIs

Status: pending
Branch: `codex/config-compose-orchestration`
PR: pending

Goal:

- Wire the complete public `compose_config` order using prior phases.

Scope:

- Full staged composition order.
- Simple public `compose_config`.
- Scoped lower-level inspection APIs for intermediate stages.
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
- Inspection APIs expose stable records without leaking unstable internals.
- Pipeline remains independent.

Test expectations:

- Package/API tests.
- Integration tests for full order through recipes and runtime resolution.
- Inspection API contract tests.
- Import-boundary tests.

### Phase 13 - Provenance, Manifest, And Redaction Population

Status: pending
Branch: `codex/config-manifest-provenance`
PR: pending

Goal:

- Populate artifact-safe provenance, manifest, and redacted artifact records.

Scope:

- Source/order/include/override/recipe/resolver/security facts.
- Versioned composition manifest.
- Default unresolved/redacted config artifact.
- Warnings/docs for plaintext secrets in overrides.

Out of scope:

- Fingerprint comparison logic.
- Raw source bytes by default.
- Resolved config persistence.

Acceptance criteria:

- Manifest records all artifact-safe composition decisions needed for later
  resume and CLI inspection.
- Default artifact records contain no resolved runtime values.
- Redaction applies before serializing sensitive authored paths.

Test expectations:

- Contract tests for manifest/provenance records.
- Redaction tests.
- No-resolved-runtime-values artifact tests.
- Docs snippets for secret handling.

### Phase 14 - Artifact-Safe Fingerprints And Resume Comparison

Status: pending
Branch: `codex/config-artifact-fingerprints`
PR: pending

Goal:

- Compute artifact-safe fingerprints and compare authored composition for resume
  checks.

Scope:

- Fingerprints before resolver execution.
- Source hashes.
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

### Phase 15 - Source Artifacts And Raw Snapshot Opt-In

Status: pending
Branch: `codex/config-source-artifacts`
PR: pending

Goal:

- Return source metadata/hashes by default and define explicit raw snapshot
  behavior.

Scope:

- Source metadata and content hashes for base configs, overlays, and includes.
- Manifest references to source artifact records.
- Duplicate-source handling.
- Explicit raw source snapshot opt-in, or clear deferral to run-store security
  policy.

Out of scope:

- Default raw source-byte persistence.
- Run directory writes.
- Remote/plugin sources.

Acceptance criteria:

- Source hashes are deterministic and change when source content changes.
- Metadata-only source artifacts can verify authored composition when original
  sources are available.
- Raw snapshot opt-in, if implemented, can reconstruct missing authored source
  files for supported local/file sources.
- Duplicate raw payloads are deduped when raw snapshots are enabled.

Test expectations:

- Unit/contract tests for source hashes, manifest references, dedupe, opt-in raw
  payload behavior if implemented, and metadata-only rebuild limitations.

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
- custom resolver `NotImplementedError`;
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

Status: pending

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
- Custom OmegaConf-style resolvers are deferred and raise `NotImplementedError`
  in v1.

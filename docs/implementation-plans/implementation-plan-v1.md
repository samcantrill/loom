# Implementation Plan v1

## Goal

Implement `loom` v1 as explicit, rebuildable config composition over the v0
configuration system.

The v1 target is a deterministic composition layer with `_include_`,
`_replace_`, `_copy_`, and composition source snapshots. It lets users split
large configs into nested component files, replace whole components during
experiments and sweeps, reuse stage/component config templates, and rebuild the
authored composition inputs that produced a run. This is not Hydra
compatibility and does not introduce Hydra defaults, launchers, sweepers,
custom interpolation resolvers, plugin extension hooks, or an arbitrary YAML
expression language.

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
explicit composition feature:

```yaml
model:
  _include_: resnet50
```

For `configs/experiment.yaml`, this resolves by default to:

```text
configs/model/resnet50.yaml
```

The included content loads first, then local sibling keys override it through
the same merge semantics used elsewhere in config composition.

V1 also adds whole-section replacement:

```yaml
model:
  _replace_: true
  _include_: vit_b16
```

and in-document subtree reuse:

```yaml
pipeline:
  stages:
    train_alt:
      config:
        _copy_: stage_configs.train_base
        optimizer:
          lr: 0.0001
```

## Desired Outcome

After v1 is complete:

- Config authors can split nested config components into separate files.
- `_include_` works recursively inside mappings.
- `_replace_` lets overlays, override mappings, and sweep-generated configs
  replace whole mapping sections without stale sibling keys leaking through.
- `_copy_` deep-copies a composed subtree and lets local sibling keys override
  the copied values.
- Override strings distinguish strict updates from explicit `+` additions.
- Relative includes are resolved from the including file and mapping key path.
- Explicit local paths and `file://` URIs are supported.
- Include and copy expansion are deterministic, cycle-safe, and
  provenance-rich.
- Overlays and CLI overrides can replace included values predictably.
- Runs can persist a composition manifest and source snapshots sufficient to
  rebuild the authored composition inputs even if project files later change.
- Validation remains scoped to existing `loom` boundaries and reports
  composition-aware source context for failures.
- Resolved config snapshots are complete and do not require include expansion at
  read time.

## Non-Goals

- No Hydra-compatible defaults lists or config groups.
- No Hydra launchers, sweepers, or runtime composition behavior.
- No arbitrary expression language in YAML.
- No advanced list patching, list insertion, deletion, or splice operators.
- No broad registry aliases for every component.
- No automatic schema inference for arbitrary `_target_` classes.
- No YAML `_schema_` directive, structured-config registry, or automatic import
  of project schema classes from config files.
- No untrusted config sandboxing or import allow-list mode.
- No plugin-discovered composition extensions.
- No custom include resolvers beyond built-in local path and `file://`
  behavior.
- No custom OmegaConf-style interpolation resolvers.

## Public Config Surface

V1 should preserve the v0 public entrypoint:

```python
cfg = compose_config(
    config_path="configs/experiment.yaml",
    overlays=["configs/local.yaml"],
    overrides=["run.seed=123"],
)
```

Composition directive expansion is part of `compose_config`; callers should not
need a separate public step for normal use.

V1 should not add public extension hooks for custom include resolvers or custom
interpolation resolvers. If `ComposedConfig` needs new fields, prefer explicit
data such as `composition_manifest` and `source_snapshots` over parallel
private state hidden inside provenance.

## Include Syntax

`_include_` is allowed only inside mappings:

```yaml
model:
  _include_: resnet50
  dropout: 0.2
```

The included value must resolve to a config document. After expansion, the node
is equivalent to:

```text
recursive_merge(load(configs/model/resnet50.yaml), {"dropout": 0.2})
```

Siblings override included values. Normal v0 merge rules apply:

- mappings recursively merge;
- scalars replace;
- lists replace as whole lists;
- explicit `null` remains explicit `null`.

If an `_include_` is applied at a config path that already has
lower-precedence mapping content, the same mapping must also contain
`_replace_: true`. This is intentionally stricter than normal recursive merge:
component swaps should fail loudly unless the author explicitly discards the
previous component mapping. An include at a new path does not need `_replace_`
because there is no prior mapping to discard.

Multiple includes in one mapping are out of scope for v1. If a user needs to
combine multiple components, they should compose through an overlay or a recipe
until a later plan defines list-valued includes.

## Replace Syntax

`_replace_` is allowed only inside mappings:

```yaml
model:
  _replace_: true
  _include_: vit_b16
```

When the mapping is merged over an existing destination mapping, the
destination mapping is discarded before the marker mapping is applied. The final
resolved config omits `_replace_`.

This is primarily for component swaps in overlays, override mappings, and later
sweep-generated trial configs. It prevents values from the previous component
from surviving through normal recursive merge semantics.

When `_include_` appears while replacing an existing mapping, `_replace_: true`
is required in the same mapping. If the marker is missing, composition should
fail with a path-aware config error rather than merge the new included content
with existing keys.

If `_replace_: true` appears where there is no existing destination value, the
marker is stripped and the mapping is used as written. `_replace_` must be a
boolean true value; other values fail with a path-aware config error.

## Copy Syntax

`_copy_` is allowed only inside mappings:

```yaml
stage_configs:
  train_base:
    batch_size: 64
    epochs: 20
    optimizer:
      _include_: adam

pipeline:
  stages:
    train_small:
      config:
        _copy_: stage_configs.train_base
        optimizer:
          lr: 0.0003
```

The `_copy_` value is an explicit dot path to another subtree in the composed
config. The source subtree is deep-copied as plain config data, then local
sibling keys merge over it. The copied result is not a live alias.

Copy expansion should happen after include expansion so copied templates already
contain included defaults. Copy expansion must detect cycles and should reject
missing source paths, non-mapping copy sites with sibling overrides, and copies
that would require implicit global name lookup.

## Include Resolution

Resolution rules:

- If `_include_` has a URI scheme, only `file://` is supported in v1.
- `file://` is built in.
- If `_include_` is an explicit relative or absolute path, resolve it relative
  to the including file directory unless absolute.
- If `_include_` is a bare name, resolve it using the mapping key path below the
  including file directory and append `.yaml`.

Examples:

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

```yaml
optimizer:
  _include_: ../shared/optimizer.yaml
```

resolves relative to the including file directory:

```text
shared/optimizer.yaml
```

```yaml
optimizer:
  _include_: file:///abs/project/configs/optimizer/adam.yaml
```

resolves through built-in `file://` handling.

The detailed phase plan should define exact path normalization, accepted file
extensions, and whether extensionless explicit paths try `.yaml` before failing.
The default should be conservative and deterministic.

Other URI schemes and custom include resolvers are out of scope for v1.

## Composition Order

V1 should treat base files, overlays, and CLI dot-path overrides as
authoring-level inputs before expanding composition directives:

```text
load base config
load overlays
parse CLI dot-path overrides into a highest-precedence override mapping
recursive merge overlays and override mapping into base config, honoring _replace_
recursively expand includes
recursively expand copies
resolve enough interpolation for recipe args
expand recipes
resolve interpolation again
validate
redact
compute config provenance and fingerprint
```

For ordinary values, CLI overrides remain the highest-precedence authoring
input. Representing them as an override mapping before directive expansion lets
users and later sweep planners change component selections with overrides such
as `model._include_=vit_b16`, or replace a section by adding
`+model._replace_=true` alongside the include override.

Override strings should distinguish updates from intentional additions:

```text
path=value:
  update an existing path; fail if the path does not exist

+path=value:
  add a new path; fail if the path already exists
```

This lets users introduce variables or structured override branches explicitly,
for example `+vars.learning_rate=0.0003`, while ordinary overrides catch typos.
The same add form is used to add a replacement marker from CLI overrides:
`+model._replace_=true`.

The implementation must preserve source-location metadata through the merge so
an include authored in an overlay resolves relative to that overlay file. A
bare include authored by CLI override should resolve relative to the root config
file directory and the overridden config path unless the value is an explicit
path or `file://` URI.

Copy expansion happens after include expansion so copied templates contain
their included defaults before local copy-site overrides are applied.

## Correctness And Validation

V1 should harden validation around the existing composition model rather than
introducing a new schema authoring feature.

Typed models should remain internal correctness contracts for stable `loom`
boundaries:

- pipeline specs;
- stage specs;
- artifact/input/output specs;
- recipe arguments;
- composition manifest records;
- provenance records.

Project-owned config subtrees should remain plain data unless they are recipe
arguments, `_target_` constructor inputs, or part of a `loom`-owned schema.
There should be no YAML `_schema_` directive and no Hydra-style structured
config registry in v1.

Directive validation happens during expansion:

- `_include_`, `_replace_`, and `_copy_` placement;
- directive value types;
- `_include_` over existing mapping content without `_replace_: true`;
- missing include targets;
- missing copy sources;
- include and copy cycles;
- non-mapping content when sibling overrides require a mapping.

Stable schema validation happens after composition directives, recipes, and
interpolation have produced the resolved config shape. Unknown keys should be
rejected only where a `loom` schema owns the section. Unknown keys in
project-owned pass-through mappings should not fail globally.

Validation and composition errors should carry source context:

- config path;
- source file, overlay, included file, copied source, replacement mapping, or
  CLI override;
- include/copy stack when relevant;
- schema boundary when relevant;
- expected value shape and actual value shape.

## Provenance And Fingerprints

Composition provenance should record:

- config path where `_include_`, `_replace_`, or `_copy_` appeared;
- raw directive value;
- resolved URI or path;
- built-in resolution mode;
- source hash;
- included document schema version, if present;
- include stack;
- copy source path and destination path;
- replacement path and replaced value hash, when available;
- source snapshot identifier for every authored source document;
- stable schema boundary and schema version when a `loom` schema validates a
  composed section;
- schema defaults or coercions that affect the resolved config, if any;
- loom version;
- whether local sibling keys overrode included values.

Config fingerprints must change when:

- an included file changes;
- an include target changes;
- a copied source subtree changes;
- a replacement marker or replacement value changes;
- sibling overrides change;
- overlays or CLI overrides change included values.

Resolved config snapshots should be self-contained. Reading
`config/resolved.yaml` from a run directory should not require the original
included files to still exist.

To rebuild the authored composition process, v1 should also produce data for
the runner/run store to persist:

```text
config/composition_manifest.json
config/source_snapshots/
```

The composition manifest should reference content-addressed source snapshots
for the base config, overlays, included files, and any other authored sources
whose content affects directive expansion. The source snapshots and manifest
are separate from `resolved.yaml`: `resolved.yaml` is the final value snapshot,
while the manifest and source snapshots explain and preserve the inputs that
produced it.

## Errors

V1 should add path-aware config errors for:

- `_include_` outside a mapping;
- `_replace_` outside a mapping or not boolean `true`;
- `_copy_` outside a mapping;
- invalid include value type;
- invalid copy path type;
- `_include_` over an existing mapping without `_replace_: true`;
- update override for a missing path;
- add override for an existing path;
- missing include target;
- missing copy source;
- unsupported include URI scheme;
- non-mapping include content when sibling overrides are present;
- non-mapping copy source when sibling overrides are present;
- recursive include cycle;
- recursive copy cycle;
- stable schema validation failure after composition;
- unknown key in a `loom`-owned schema boundary;
- duplicate or ambiguous resolution if the detailed plan allows extension
  probing.

Cycle errors should include the include stack. Missing file errors should show
both the authored include value and the resolved path. Copy errors should show
both the source path and the destination path. Validation errors should show the
schema boundary and the authored source that produced the failing value when
that source metadata is available.

## Source Structure

Expected additions or updates under `src/loom/config/`:

```text
composition.py
includes.py
copies.py
source_snapshots.py
merge.py or equivalent existing merge module
overrides.py or equivalent existing override module
validation.py or equivalent existing validation module
```

Responsibilities:

- `composition.py`: directive expansion orchestration, source-location metadata,
  and integration with existing compose flow.
- `includes.py`: recursive tree walk, merge of included content with sibling
  overrides, cycle detection, provenance record creation.
- `copies.py`: `_copy_` path resolution, deep-copy expansion, copy cycle
  detection, and copy provenance.
- `source_snapshots.py`: content-addressed source snapshot records for base,
  overlay, and included config documents.
- `merge.py` or the existing merge module: `_replace_` marker handling and
  replacement provenance hooks.
- `overrides.py` or the existing override module: strict update override and
  explicit `+` add override parsing/application.
- `validation.py` or the existing validation module: source-aware validation
  errors for stable `loom` schema boundaries after composition.

These modules may use existing config load, merge, errors, serialization,
fingerprint, and provenance helpers. They must not import pipeline execution,
stores, CLI modules, plugin discovery, or project code.

`_replace_` should live with the existing merge implementation rather than in a
separate directive-expansion module because it changes mapping merge semantics.

## Integration With V0

V1 should modify config composition, not downstream pipeline behavior:

- Config loading still owns file parsing.
- Merge semantics stay unchanged except for the explicit `_replace_` mapping
  marker.
- Dot-path overrides remain the same user-facing mechanism, but v1 hardens them
  into strict update overrides and explicit `+` add overrides.
- Interpolation still uses the existing wrapped OmegaConf behavior.
- Recipes still expand after include and copy expansion.
- Typed validation still applies only at existing `loom`-owned boundaries and
  recipe inputs.
- `_target_` instantiation remains separate from composition.
- Persistence still belongs to the runner and run store.

If existing v0 config provenance models cannot represent included source files,
copies, replacements, or source snapshots, extend those models in
`loom.config.provenance` rather than adding parallel directive-only provenance
formats.

## Future Compatibility

V1 should preserve later roadmap stages:

- V2 CLI commands should get composition behavior automatically through
  `compose_config`.
- V10 sweeps should generate trial override mappings that flow through
  `compose_config` without implementing their own include, copy, or replacement
  behavior.
- V11 plugin discovery may later provide explicit composition extensions, but
  v1 should not load plugins automatically or define the extension API early.
- V12 and v13 remote store work may influence future URI resolvers, but v1
  should start with local and `file://` behavior.

## Phased Implementation

### Phase 1 - Composition Directive Model And Resolution

Status: pending
Branch: `codex/add-config-composition-directives`
PR: pending

Goal:

- Define composition provenance records, directive errors, source-location
  metadata, `_replace_` merge behavior, include path resolution rules, and
  source-aware validation expectations.

Acceptance criteria:

- Bare-name, relative-path, absolute-path, and `file://` include values resolve
  deterministically.
- Unsupported URI schemes fail clearly.
- `_replace_` replaces destination mappings and is omitted from resolved config.
- `_include_` over existing mapping content fails unless `_replace_: true` is
  present in the same mapping.
- Override strings support `path=value` update semantics and `+path=value`
  add-only semantics.
- YAML `_schema_` bindings and project schema imports are not interpreted as
  composition behavior; unknown-key handling is limited to `loom`-owned schema
  boundaries.
- Unit tests cover key-path based default resolution.

### Phase 2 - Recursive Include And Copy Expansion

Status: pending
Branch: `codex/add-recursive-config-composition`
PR: pending

Goal:

- Expand `_include_` and `_copy_` recursively after authoring-level merge.

Acceptance criteria:

- Included mapping content merges with sibling overrides.
- Include swaps over existing mapping content require `_replace_: true`.
- Nested includes work.
- Cycles fail with include-stack context.
- Missing or invalid include documents fail with path-aware errors.
- `_copy_` deep-copies composed subtrees and local siblings override copied
  values.
- Copy cycles and missing copy sources fail with path-aware errors.

### Phase 3 - Composition Integration, Provenance, And Snapshots

Status: pending
Branch: `codex/integrate-config-composition`
PR: pending

Goal:

- Integrate `_include_`, `_replace_`, `_copy_`, composition manifests, and
  source snapshots into `compose_config` and persisted provenance data.

Acceptance criteria:

- Base configs, overlays, and CLI overrides merge before include/copy expansion,
  with CLI as highest precedence.
- Config fingerprints change when included files change.
- Config fingerprints change when copied source subtrees or replacement markers
  change.
- Resolved/redacted config snapshots are self-contained.
- Composition provenance records every included source, copy, replacement, and
  source hash.
- Composition provenance records stable schema boundaries and schema versions
  when existing `loom` validation models validate composed sections.
- Source snapshot records are sufficient for the runner/run store to persist
  rebuildable config inputs.

### Phase 4 - Hardening And Docs

Status: pending
Branch: `codex/harden-config-composition`
PR: pending

Goal:

- Document composition directives, add integration/e2e coverage, and harden
  edge cases.

Acceptance criteria:

- Docs include examples for component includes, sibling overrides, explicit
  paths, `file://` URIs, `_replace_`, `_copy_`, and source snapshots.
- Tests cover overlays that contain includes, CLI overrides of included values,
  CLI replacement of component selections, interpolation with included/copied
  values, recipes after includes/copies, source snapshot manifests, and
  redaction of included secrets.
- Tests cover source-aware validation errors after composition and prove
  project-owned pass-through mappings are not globally rejected.
- `make validate-pr` and `make test-summary` pass.

## Overall Test Plan

Unit tests:

- include value validation;
- bare-name resolution;
- relative and absolute path resolution;
- `file://` resolution;
- unsupported schemes;
- include swap without `_replace_` error;
- update override missing-path error;
- add override existing-path error;
- add override creation for new variables and structured branches;
- cycle detection;
- `_replace_` merge behavior;
- `_copy_` path resolution and deep-copy behavior;
- copy cycle detection;
- sibling override merge semantics;
- composition provenance serialization;
- source-aware validation error data;
- scoped unknown-key behavior for `loom`-owned vs project-owned sections;
- source snapshot hashing.

Integration tests:

- base config includes;
- overlay includes;
- overlay replacing an included component;
- CLI override replacing an included component;
- CLI add override introducing a new variable;
- stage config reuse with `_copy_`;
- CLI override of included values;
- interpolation that references included and copied values;
- stable schema validation after composition;
- recipe expansion after include and copy expansion;
- redaction of included secrets;
- provenance for stable schema boundaries and schema versions;
- fingerprint changes from included source edits;
- fingerprint changes from copied source edits and replacement markers;
- composition manifest plus source snapshots are sufficient to reconstruct
  authored inputs.

Validation gates:

```sh
make validate-pr
make test-summary
```

## Plan Quality Gate

Status: pending

Before implementation starts, review this v1 plan for:

- deterministic resolution;
- provenance completeness;
- source-aware validation behavior;
- scoped typed validation boundaries;
- compatibility with v0 config composition;
- rebuildability of composition manifests and source snapshots;
- future compatibility with CLI, sweeps, plugins, and remote URI work;
- accepted technical debt; and
- test strategy.

## Assumptions And Defaults

- V1 begins after v0 config composition, merge, provenance, redaction,
  fingerprints, and recipe expansion are available.
- `_include_` is trusted project config, consistent with the v0 trusted-config
  model.
- Local filesystem and `file://` include resolution are required.
- Other URI schemes and custom include resolvers are deferred.
- Include and copy expansion do not add new merge semantics.
- `_replace_` is the only new merge marker in v1.
- Normal overrides update existing paths; `+` overrides add missing paths.
- Typed models remain internal validation contracts for `loom`-owned sections,
  not a YAML schema authoring feature.
- Lists still replace as whole lists.
- Custom OmegaConf-style resolvers are deferred.

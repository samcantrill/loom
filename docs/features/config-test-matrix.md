# Configuration Behavior Test Matrix

This matrix records the behavior attributes that should remain covered for
`weave`. It focuses on observable public behavior and accepted v1
constraints. Internal helper tests are useful when they pin narrow edge cases,
but at least one public API path should exist for each major capability.

## Composition Pipeline

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| Source loading accepts a single non-empty YAML mapping with string keys. | Empty files, empty mappings, non-mapping roots, non-string keys, recursive aliases, multiple YAML documents, invalid UTF-8, unsafe YAML tags, invalid YAML syntax. | Unit load tests plus public compose invalid-YAML regression coverage. |
| Composition order is stable. | Load, overlay merge, include expansion, include overrides, recipe argument interpolation, recipe expansion, ordinary overrides, resolver scan, runtime interpolation, validation, redaction, provenance, fingerprint, artifact placeholders, composed config. | `inspect_config_composition` stage-order contract. |
| `compose_config` and `inspect_config_composition(...).to_composed_config()` agree. | Resolver values, overlays, overrides, artifacts, fingerprints, raw snapshot flags. | Integration consistency tests. |
| Config remains domain-neutral. | No required `name`, `pipeline`, stage, or store-specific keys. | Generic payload composition tests. |

## Overlays And Merge Semantics

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| Later overlays win over earlier inputs. | Multiple overlays, scalar/list/null replacement, mapping recursion, nested mapping conflicts. | Unit merge/source-map tests and integration overlay tests. |
| `_replace_: true` replaces a mapping and is consumed. | Root replace, nested replace, nested replace inside an already replaced mapping, no sibling replacement keys, lower value missing, lower value non-mapping, marker value not true. | Unit merge/source-map tests. |
| Source maps track authorship after merge. | Base descendants that survive, overlay-owned scalar/list replacements, overlay-owned include-like keys, replacement sites. | Source-map tests. |
| Multi-overlay replacement remains inspectable. | Overlay 1 introduces a mapping; overlay 2 replaces it; provenance keeps base/overlay ordering. | Follow-up integration test. |

## Includes

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| `_include_` expands local YAML mappings. | Include in base, include in overlay, include inside lists or nested mappings, local sibling customizations. | Unit include expansion and public compose include tests. |
| Bare include targets resolve from the include-site-derived directory. | Nested bare names, names with dash/underscore/digits, explicit `.yaml` requirement, dot-prefixed names not treated as bare names. | Include resolver tests. |
| Explicit relative, absolute, and `file://` targets are strict. | Parent segments, normalized candidates, missing exact file, URI host/query/fragment rejection, malformed escapes, NUL decoding, directory targets. | Include resolver tests. |
| Include resolution cannot escape unsafely. | Symlink escape, unsupported URI schemes, remote URLs, plugin/global search paths. | Include resolver tests for local-only behavior. |
| Nested includes resolve relative to the including file. | Includes nested several levels deep, nested bare names, nested explicit relative paths. | Unit and integration include tests. |
| Include cycles are detected by resolved path. | Cycles through explicit paths, cycles through bare names, context includes stack and attempted target. | Unit helper test plus public compose regression. |
| Included roots must be mappings. | List/scalar included root, replacement target not mapping. | Unit and public user-override tests. |
| `_replace_` authored inside included files is rejected unless consumed by the including site. | Root marker, nested marker, unconsumed local marker. | Unit and public compose tests. |
| Existing mapping swaps require same-site `_replace_`. | Overlay include over existing mapping without marker, same-site marker with local customizations. | Unit and integration include tests. |

## User Composition Overrides

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| Include-target overrides run before ordinary overrides. | Existing include replacement followed by ordinary update/add, repeated updates where last wins. | Integration override tests. |
| Existing include replacement replays local customizations. | Local add, local override, nested include replacement, source-local bare replacement target. | Integration override tests. |
| New include addition requires `+path._include_=`. | Explicit target required, bare target rejected, adding over existing concrete container rejected, missing parent creation. | Integration override tests. |
| Include targets cannot depend on resolver expressions. | Existing include replacement with `${...}`, brand-new include addition with `${...}`. | Integration resolver/override tests. |
| Ordinary overrides are strict. | Update missing path fails, add existing path fails, add creates parents, list/non-mapping parents fail, numeric-like path segments are strings. | Unit override tests. |
| Override values parse predictably. | Booleans, null, integers, finite floats, JSON arrays/objects, invalid JSON, non-finite floats, string preservation. | Unit override parsing tests. |

## Recipes

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| Explicit `RecipeCatalog` registration is trusted project code. | Callable functions, callable classes, duplicate registration, replacement preserving order, invalid names, non-callable implementations. | Unit catalog tests. |
| Recipe arguments resolve node interpolation before expansion. | Arguments referencing base/overlay values, resolver expressions preserved as authored facts, override-to-expanded-away argument rejected. | Unit and integration recipe tests. |
| Recipe output can contain nested recipes. | Expansion order, path recording, manifest order, final interpolation after expansion. | Unit recipe expansion tests. |
| Recipe output remains plain data. | Non-mapping output, non-plain output, resolver-dependent output keys, reserved keys in recipe blocks, nested `_recipe_` inside authored args. | Unit and integration recipe tests. |
| Recipe output can contain inert `_target_` nodes. | Compose does not instantiate, explicit `instantiate` later constructs nested targets. | Follow-up integration test. |

## Interpolation And Resolvers

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| Node interpolation resolves after ordinary overrides. | Override changes referenced value, missing interpolation target, interpolation in lists and nested mappings. | Unit and integration interpolation tests. |
| Resolver expressions are scanned without execution for artifact facts. | Multiple resolver tokens, resolver tokens inside larger strings, list/nested paths, stable metadata ordering. | Unit scan tests and public artifact tests. |
| Only Loom-owned `oc.env` executes. | Global resolver replacement is ignored, non-allowlisted OmegaConf built-ins rejected, custom resolvers rejected, `oc.env` output treated literally. | Unit and integration resolver tests. |
| Resolver outputs are not persisted by default. | Environment value changes should not alter artifact-safe fingerprint when authored expression is unchanged. | Fingerprint and e2e tests. |

## Target Import And Instantiation

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| `import_target` supports dotted and `module:object` forms. | Empty target, missing module/object, multiple colons, colon form with dotted object path, dotted form fallback rejection, nested attribute lookup rejection. | Unit target import tests. |
| `instantiate` recursively constructs target graphs. | Nested mappings, lists, tuples, bottom-up order, `_args_`, kwargs, `_partial_`, runtime injection. | Unit recursive instantiation tests. |
| Reserved keys are structural. | `_recipe_` in instantiate input rejected, `_args_`/`_partial_`/`_inject_` outside target rejected, non-string `_target_`, invalid `_args_`, invalid `_partial_`. | Unit instantiation tests. |
| Runtime injection is explicit and strict. | Missing runtime key, duplicate static/injected key, non-mapping runtime, invalid injected mapping/key/value. | Unit injection tests. |
| Compose keeps targets inert. | Plain `_target_` nodes, nested target nodes, targets produced by recipes, explicit later instantiation. | Integration compose and follow-up handoff tests. |

## Artifacts, Provenance, Fingerprints, And Redaction

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| `ComposedConfig` carries resolved, unresolved, redacted, provenance, manifest, source artifacts, fingerprint records, recipe manifest, and raw source snapshot bundle. | `to_dict`/`from_dict` round trips, schema versions, plain-data metadata, nested recipe manifest thawing. | Contract tests. |
| Source artifact records are metadata-only by default. | Base, overlays, includes, replacement includes, added includes, recipe records, source reference ordering. | Contract, integration, and e2e tests. |
| Artifact-safe fingerprints are stable and portable. | Absolute temp-root changes, overlay content changes, recipe manifest changes, include target/content changes, redacted secret overrides, wrong-label comparison. | Unit and integration fingerprint tests. |
| Redaction applies recursively to secret-like keys. | Case-insensitive names, punctuation variants, nested JSON overrides, resolver expressions preserved, safe keys unaffected. | Unit redaction and public artifact tests. |
| Raw source snapshots are opt-in. | Default disabled refs, opt-in available payloads, deduped identical source text, unsupported recipe records, nested replacement include sources, no raw bytes in fingerprint. | Integration source snapshot tests plus follow-up combined-case test. |

## Import Boundaries

| Behavior | Important edge cases | Existing or expected coverage |
| --- | --- | --- |
| Top-level imports are lightweight. | `import loom`, `import weave`, `from weave.instantiate import instantiate`. | Package import-boundary tests. |
| Package-owned dependencies stay inside `weave`. | `weave` owns YAML/OmegaConf/Pydantic dependencies for config authoring; Loom runtime internals do not import composition modules except through approved adapters. | Package import-boundary tests. |
| Runtime layers stay separated. | `weave` does not import pipeline/execution/stores/CLI; pipeline can consume plain target data without importing config composition internals. | Package import-boundary tests. |

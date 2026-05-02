# `loom.plugins` Specification

## 1. Purpose

`loom.plugins` centralizes optional extension discovery for `loom`.

It exists so downstream packages can contribute recipes, codecs, executors, data
sources, and other extension points without modifying the generic `loom` source
tree.

The plugin layer should answer:

```text
Which installed packages advertise loom extension points?
Which entry point groups does loom understand?
How are entry points loaded explicitly and deterministically?
How are duplicates handled?
How are load failures reported?
How do discovered objects get registered with the correct subsystem registry?
```

It should not answer:

```text
How does a recipe expand?
How does a codec decode bytes?
How does an executor submit work?
How does config composition work?
How does a CLI command run a pipeline?
```

The core rule is:

```text
Plugin discovery is explicit, opt-in, and adapter-shaped.
```

Importing `loom` should not discover or import third-party plugins.

### 1.1 Alignment With `loom.md`

[loom.md](loom.md) keeps plugin behavior outside the minimum runtime kernel. This
document describes the deferred extension layer that can connect downstream
recipes, codecs, sources, executors, and CLI additions to explicit registries
without making plugin discovery a side effect of importing `loom`.

---

## 2. Core Position

`loom.plugins` is an optional coordination layer above subsystem registries.

Recommended dependency shape:

```text
config recipes / io codecs / executors / sources
        ^
        |
plugins
        ^
        |
cli or application setup
```

It may use:

```text
importlib.metadata
typing
loom.serialization
loom.config recipe catalog APIs
loom.io codec/source registry APIs
loom.pipeline executor registry APIs, when implemented
```

It should not import:

```text
project packages except through explicit entry point loading
pipeline runner lifecycle
SLURM command wrappers directly
CLI modules
large optional dependencies
```

This keeps plugin discovery available to setup code without creating import-time
side effects in lower layers.

---

## 3. Package Boundary

### 3.1 `loom.plugins`

Owns public plugin discovery helpers.

Responsibilities:

```text
define known entry point groups
list installed entry points
load selected entry points
return structured plugin records
report plugin load failures
apply deterministic duplicate policy
optionally register loaded objects into subsystem registries
```

### 3.2 `loom.config.recipes`

Owns recipe behavior and recipe catalog registration.

Plugin responsibilities:

```text
discover recipe entry points
load recipe classes/functions
register them with a RecipeCatalog when asked
```

Plugin non-responsibilities:

```text
validate recipe input schemas
expand recipes
compose configs
```

### 3.3 `loom.io.codecs`

Owns codec behavior and codec registry registration.

Plugin responsibilities:

```text
discover codec entry points
load codec classes or factory functions
instantiate codecs if required by policy
register codecs with CodecRegistry when asked
```

Plugin non-responsibilities:

```text
decode resources
select codecs during artifact loading
implement codec schemas
```

### 3.4 `loom.pipeline.executors`

Owns executor behavior and executor registry registration.

Plugin responsibilities:

```text
discover executor entry points, later
load executor factories, later
register executor names, later
```

Plugin non-responsibilities:

```text
submit jobs
generate scheduler scripts
run stages
```

### 3.5 `loom.cli`

Owns command-line presentation.

Plugin responsibilities:

```text
provide data for optional plugin list/debug commands
support explicit discovery flags when needed
```

The CLI should call plugin APIs. Plugin APIs should not import CLI modules.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
known entry point group constants
generic entry point listing
generic entry point loading
PluginRecord value object
PluginLoadResult value object
recipe entry point loading
codec entry point loading
explicit registration into supplied registries
duplicate name detection
clear plugin-specific errors
no import-time discovery
tests with fake entry points
```

### 4.2 Should Support Soon

```text
executor entry point loading
source backend entry point loading
plugin provenance records
CLI inspection command
strict and best-effort discovery modes
entry point filtering by package/name/group
```

### 4.3 Should Not Support in v0

```text
plugin marketplace behavior
automatic installation
dependency resolution
version solving
remote plugin indexes
automatic discovery on import loom
automatic loading of all plugins before every command
plugin sandboxing
untrusted plugin execution
domain-specific extension validation
```

Installed plugins are trusted Python code. Loading an entry point imports and may
execute code from the installed package.

---

## 5. Terminology

### 5.1 Plugin

A plugin is an installed Python package that advertises one or more `loom` entry
points.

### 5.2 Entry Point

An entry point is package metadata that maps a name to an import target.

Example:

```toml
[project.entry-points."loom.codecs"]
array_npy_v1 = "project.codecs:ArrayNpyCodec"
```

### 5.3 Entry Point Group

An entry point group is a namespace for one kind of extension.

Examples:

```text
loom.recipes
loom.codecs
loom.executors
loom.sources
```

### 5.4 Entry Point Name

The entry point name is the key in the group.

Example:

```toml
json_v1 = "loom.io.codecs.json_codec:JSONCodec"
```

Here `json_v1` is the entry point name. The loaded codec may still expose a
runtime key such as `json.v1`.

### 5.5 Loaded Object

The loaded object is what `entry_point.load()` returns.

It may be:

```text
class
function
factory object
already-instantiated object, though this is discouraged
```

Subsystem registration policy decides what shapes are accepted.

### 5.6 Registry

A registry maps stable names or keys to implementations.

Examples:

```text
RecipeCatalog
CodecRegistry
SourceRegistry
ExecutorRegistry
```

Plugins discover objects. Registries own runtime lookup.

---

## 6. Guiding Design Principles

### 6.1 Discovery Is Explicit

Do not discover plugins during:

```text
import loom
import loom.config
import loom.io
import loom.pipeline
```

Discovery should happen only when a caller asks:

```python
load_recipe_entry_points(catalog)
load_codec_entry_points(registry)
```

### 6.2 Loading Is Trusted Code Execution

Entry point loading imports third-party Python modules.

Document this clearly:

```text
Do not load untrusted installed packages as loom plugins.
```

This aligns with the broader rule that authored configs are trusted project
code.

### 6.3 Keep Registries Explicit

Avoid hidden global mutation as the only path.

Good:

```python
catalog = RecipeCatalog()
load_recipe_entry_points(catalog)
```

Bad:

```text
import loom.plugins silently mutates global recipe and codec registries
```

### 6.4 Keep Failure Policy Configurable

Some workflows want strict plugin loading. Others want best-effort discovery.

Support:

```text
strict=True:
  first plugin load failure raises

strict=False:
  collect failures in result and continue
```

Default should be conservative for commands that explicitly request plugins.

### 6.5 Deterministic Duplicate Policy

Duplicate entry point names or runtime keys should not be resolved by import
order accidents.

Recommended default:

```text
duplicates are errors
```

Allow replacement only through explicit `replace=True` or caller policy.

### 6.6 Keep Plugin Metadata Separate From Runtime Objects

Plugin records should track:

```text
entry point group
entry point name
entry point value
distribution/package name
loaded object type
load status
```

Do not require every runtime object to carry all plugin metadata.

### 6.7 Avoid Marketplace Semantics

The plugin package is not a package manager.

It should not:

```text
search remote indexes
install packages
upgrade packages
resolve dependency conflicts
trust-score plugins
```

Python packaging tools own installation.

---

## 7. Entry Point Groups

### 7.1 Recipes

Group:

```text
loom.recipes
```

Example:

```toml
[project.entry-points."loom.recipes"]
local_jsonl_manifest = "project.recipes:LocalJsonlManifestRecipe"
```

Loaded object should be acceptable to `RecipeCatalog.register`.

### 7.2 Codecs

Group:

```text
loom.codecs
```

Example:

```toml
[project.entry-points."loom.codecs"]
array_npy_v1 = "project.codecs:ArrayNpyCodec"
```

Loaded object should be:

```text
Codec instance
Codec class with no-arg constructor
factory returning a Codec
```

The exact accepted shapes should be defined by `CodecRegistry` integration.

### 7.3 Sources

Future group:

```text
loom.sources
```

Example:

```toml
[project.entry-points."loom.sources"]
s3 = "project.sources:S3SourceFactory"
```

Defer until source registry support needs remote backends.

### 7.4 Executors

Future group:

```text
loom.executors
```

Example:

```toml
[project.entry-points."loom.executors"]
cluster = "project.executors:ClusterExecutorFactory"
```

Defer until executor registry shape is stable.

### 7.5 CLI Commands

Do not support arbitrary third-party CLI command injection in v0.

Reason:

```text
CLI command extension creates help, dependency, and stability concerns.
Project packages can expose their own CLIs that call loom APIs.
```

---

## 8. Public API

### 8.1 Recommended Imports

```python
from loom.plugins import (
    PluginRecord,
    PluginLoadResult,
    load_entry_points,
    load_recipe_entry_points,
    load_codec_entry_points,
)
```

### 8.2 Initial Files

Recommended:

```text
src/loom/plugins/__init__.py
src/loom/plugins/entrypoints.py
src/loom/plugins/errors.py
```

### 8.3 Stable Exports

`plugins/__init__.py` should re-export only stable helpers:

```python
from loom.plugins.entrypoints import (
    PluginRecord,
    PluginLoadResult,
    load_entry_points,
    load_recipe_entry_points,
    load_codec_entry_points,
)
from loom.plugins.errors import (
    PluginError,
    PluginLoadError,
    DuplicatePluginError,
    InvalidPluginError,
)
```

Avoid exposing internal adapter functions until needed.

---

## 9. Plugin Records

### 9.1 `PluginRecord`

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class PluginRecord:
    group: str
    name: str
    value: str
    distribution: str | None = None
    version: str | None = None
```

This record describes an advertised entry point before or after loading.

### 9.2 `LoadedPlugin`

Optional structure:

```python
@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    record: PluginRecord
    object: object
```

Use this only if callers need metadata alongside loaded objects.

### 9.3 `PluginLoadResult`

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class PluginLoadResult:
    group: str
    loaded: tuple[LoadedPlugin, ...]
    failures: tuple[PluginFailure, ...]
    duplicates: tuple[PluginDuplicate, ...] = ()
```

For simple helpers, returning loaded objects may be enough. A structured result
is better for CLI/debugging and best-effort mode.

### 9.4 Plain Data Conversion

Plugin records should be plain-data serializable.

This helps:

```text
provenance
debug output
CLI JSON
tests
```

Do not attempt to serialize loaded Python objects.

---

## 10. Discovery API

### 10.1 `list_entry_points`

Representative signature:

```python
def list_entry_points(
    group: str,
    *,
    package: str | None = None,
) -> tuple[PluginRecord, ...]: ...
```

Behavior:

```text
query importlib.metadata.entry_points
filter by group
optionally filter by distribution/package
return PluginRecord values
do not load target objects
```

### 10.2 `load_entry_points`

Representative signature:

```python
def load_entry_points(
    group: str,
    *,
    names: Iterable[str] | None = None,
    strict: bool = True,
) -> PluginLoadResult: ...
```

Behavior:

```text
list entry points for group
filter by names when provided
detect duplicates
load selected entry points
return loaded objects and failures
raise in strict mode on failure
```

### 10.3 Name Filtering

Name filtering lets callers avoid importing every plugin.

Example:

```python
load_entry_points("loom.codecs", names=["array_npy_v1"])
```

This is useful for tests and project-specific setup.

### 10.4 Distribution Metadata

When available, record:

```text
distribution name
distribution version
```

This is useful for provenance and debugging.

Do not fail if distribution metadata is unavailable.

---

## 11. Recipe Plugin Loading

### 11.1 Purpose

Recipe plugin loading populates a `RecipeCatalog` from installed entry points.

Representative signature:

```python
def load_recipe_entry_points(
    catalog: RecipeCatalog,
    *,
    group: str = "loom.recipes",
    strict: bool = True,
    replace: bool = False,
) -> PluginLoadResult: ...
```

### 11.2 Registration Policy

For each loaded entry point:

```text
entry point name becomes recipe name by default
loaded object becomes recipe implementation
catalog.register(name, object, replace=replace)
```

If recipe implementations expose their own name, decide whether entry point name
or object name wins. Recommended v0:

```text
entry point name is authoritative
```

Reason:

```text
it is visible in package metadata
it avoids importing objects just to decide names during listing
```

### 11.3 Validation

The recipe catalog should validate recipe shape.

Plugin loader should add context when wrapping errors:

```text
entry point group
entry point name
entry point value
distribution
catalog registration error
```

---

## 12. Codec Plugin Loading

### 12.1 Purpose

Codec plugin loading populates a `CodecRegistry` from installed entry points.

Representative signature:

```python
def load_codec_entry_points(
    registry: CodecRegistry,
    *,
    group: str = "loom.codecs",
    strict: bool = True,
    replace: bool = False,
) -> PluginLoadResult: ...
```

### 12.2 Accepted Shapes

Recommended v0 accepted shapes:

```text
Codec instance:
  register directly

Codec class:
  instantiate with no arguments

factory function:
  call with no arguments, register returned codec
```

Keep this policy narrow. If a codec needs constructor arguments, configure it
through `_target_` and explicit config instead of entry point discovery.

### 12.3 Codec Key

The runtime codec key should come from the codec object:

```text
codec.key
```

The entry point name is metadata and fallback context, not necessarily the codec
key.

If they differ, that is acceptable but should be visible in debug output.

### 12.4 Duplicate Codec Keys

Duplicate runtime codec keys should be errors by default.

Example:

```text
Entry point "project_json" loaded codec key "json.v1", but that key is already registered.
```

Allow replacement only through explicit `replace=True`.

---

## 13. Executor and Source Plugins

### 13.1 Deferred Executor Plugins

Executor plugins should wait until the executor registry contract is stable.

Possible future loader:

```python
load_executor_entry_points(registry, group="loom.executors")
```

### 13.2 Deferred Source Plugins

Source backend plugins should wait until source registry behavior is stable for
remote backends.

Possible future loader:

```python
load_source_entry_points(registry, group="loom.sources")
```

### 13.3 Why Defer

Recipes and codecs are simpler extension points.

Executors and sources involve:

```text
resource access
credentials
scheduler commands
filesystem effects
optional dependencies
security-sensitive configuration
```

Keep them explicit until real use cases shape the API.

---

## 14. Duplicate Handling

### 14.1 Duplicate Entry Point Names

Within the same group, duplicate entry point names should be errors by default.

Reason:

```text
installation order should not decide which plugin wins
```

### 14.2 Duplicate Runtime Keys

Some plugins load objects that expose runtime keys:

```text
codec.key
executor.name
source scheme
```

Duplicate runtime keys should also be errors by default.

### 14.3 Replacement

Allow replacement only when caller explicitly requests it:

```python
load_codec_entry_points(registry, replace=True)
```

Prefer explicit project setup for overrides:

```python
registry.register(ProjectJSONCodec(), replace=True)
```

### 14.4 Error Messages

Duplicate errors should include:

```text
group
name or runtime key
first entry point
conflicting entry point
distributions
```

---

## 15. Failure Policy

### 15.1 Strict Mode

Strict mode:

```text
raise on duplicate
raise on load failure
raise on invalid plugin object
raise on registry registration failure
```

Use strict mode for reproducible production runs.

### 15.2 Best-Effort Mode

Best-effort mode:

```text
return failures in PluginLoadResult
continue loading other plugins when safe
do not hide failures
```

Use best-effort mode for plugin inspection commands.

### 15.3 Load Failures

Load failures can come from:

```text
missing dependency
import error
constructor error
invalid object shape
duplicate registration
registry validation error
```

Errors should preserve the original exception through chaining.

---

## 16. Security and Trust

### 16.1 Trusted Installed Packages

Loading an entry point imports installed Python code.

Treat plugin loading like importing a package:

```text
only load plugins from trusted environments
```

### 16.2 No Sandbox

V0 should not attempt to sandbox plugin code.

Reason:

```text
Python sandboxing is hard
configs are already trusted project code
entry points are installed code
```

### 16.3 Secret Handling

Plugin metadata normally should not contain secrets.

Still, error messages should avoid dumping:

```text
full environment variables
credentials in URLs
large object reprs
```

### 16.4 Import-Time Side Effects

The best mitigation for plugin side effects is explicit loading.

Do not load plugins during:

```text
loom --help
import loom
import loom.io
import loom.config
```

unless a user command explicitly asks for plugin discovery.

---

## 17. Provenance

### 17.1 Plugin Provenance

When plugins are loaded for a run, provenance can record:

```text
entry point group
entry point name
entry point value
distribution name
distribution version
loaded runtime key, when relevant
load status
```

### 17.2 Why It Matters

Plugin provenance helps answer:

```text
which package supplied this codec?
which recipe implementation expanded this config?
did this run use entry point discovery or explicit registration?
which plugin version was installed?
```

### 17.3 Boundary

`loom.provenance` owns persisted provenance document shapes.

`loom.plugins` can provide plain-data plugin records for provenance to include.

---

## 18. CLI Integration

### 18.1 Possible Commands

Future commands:

```bash
loom plugins list
loom plugins list --group loom.codecs
loom plugins check
```

### 18.2 `loom plugins list`

Should:

```text
list advertised entry points
not load plugins by default
support --load to verify loading explicitly
support --format json
```

### 18.3 `loom plugins check`

Should:

```text
load selected groups in best-effort or strict mode
report load failures
report duplicates
return non-zero when checks fail
```

### 18.4 Deferred

Plugin CLI commands are not required for v0 pipeline execution. They are useful
once third-party plugins are common.

---

## 19. Error Model

### 19.1 Error Types

Recommended hierarchy:

```python
class PluginError(LoomError): ...
class PluginDiscoveryError(PluginError): ...
class PluginLoadError(PluginError): ...
class DuplicatePluginError(PluginError): ...
class InvalidPluginError(PluginError): ...
class PluginRegistrationError(PluginError): ...
```

If `LoomError` does not exist yet, start with `Exception` and move under shared
errors later.

### 19.2 Error Context

Errors should include:

```text
group
entry point name
entry point value
distribution
runtime key, when available
target registry
```

### 19.3 Example Errors

Load failure:

```text
Could not load plugin entry point "project_array" from group "loom.codecs".
Target: project.codecs:ArrayNpyCodec.
Distribution: project-codecs 0.4.0.
Reason: No module named numpy.
```

Duplicate:

```text
Duplicate codec key "json.v1" while loading loom.codecs.
Existing: loom.io.codecs.json_codec:JSONCodec.
Conflicting: project.codecs:ProjectJSONCodec.
```

Invalid plugin:

```text
Invalid codec plugin "array_npy_v1".
Expected Codec instance, no-argument Codec class, or no-argument factory.
Actual object: project.codecs:ArrayNpyCodecConfig.
```

---

## 20. Testing Strategy

### 20.1 Discovery Tests

Test:

```text
list_entry_points filters by group
list_entry_points returns PluginRecord values
distribution metadata is included when available
missing distribution metadata does not fail
empty groups return empty tuple
```

### 20.2 Loading Tests

Use fake entry point objects.

Test:

```text
load_entry_points loads selected group
name filtering works
strict mode raises on load failure
best-effort mode records load failure
original exceptions are chained
```

### 20.3 Duplicate Tests

Test:

```text
duplicate entry point names rejected
duplicate codec keys rejected
replace=True allows explicit replacement where registry supports it
duplicate error includes both sources
```

### 20.4 Recipe Plugin Tests

Test:

```text
recipe entry point registers with catalog
entry point name is recipe name
invalid recipe object raises InvalidPluginError
catalog registration error is wrapped with plugin context
```

### 20.5 Codec Plugin Tests

Test:

```text
codec instance registers
codec class with no args instantiates and registers
factory function returns codec and registers
constructor failure is reported
missing codec key is invalid
duplicate runtime key is rejected
```

### 20.6 Import Boundary Tests

Test:

```text
import loom does not discover plugins
import loom.io does not discover plugins
import loom.config does not discover plugins
loom --help does not load plugin modules
explicit load call imports plugin target
```

### 20.7 CLI Tests

When plugin CLI exists, test:

```text
loom plugins list does not load targets by default
loom plugins list --load reports load results
loom plugins check returns non-zero on failures
JSON output includes group/name/value/distribution
```

---

## 21. Implementation Plan

### 21.1 Phase 1: Errors and Records

Create:

```text
src/loom/plugins/__init__.py
src/loom/plugins/errors.py
src/loom/plugins/entrypoints.py
```

Implement:

```text
PluginError
PluginLoadError
DuplicatePluginError
InvalidPluginError
PluginRecord
PluginLoadResult
```

### 21.2 Phase 2: Generic Discovery

Implement:

```text
list_entry_points
load_entry_points
entry point group constants
strict and best-effort modes
duplicate entry point name detection
```

Use `importlib.metadata.entry_points`.

### 21.3 Phase 3: Recipe Integration

Implement:

```text
load_recipe_entry_points
RecipeCatalog registration adapter
recipe plugin validation
recipe plugin tests
```

### 21.4 Phase 4: Codec Integration

Implement:

```text
load_codec_entry_points
CodecRegistry registration adapter
codec instance/class/factory handling
runtime codec key duplicate reporting
```

### 21.5 Phase 5: Provenance Support

Add:

```text
PluginRecord.to_dict
PluginLoadResult summary conversion
loaded plugin provenance summaries
```

### 21.6 Phase 6: CLI Support

Add when useful:

```text
loom plugins list
loom plugins check
```

### 21.7 Phase 7: Future Extension Points

After registries stabilize:

```text
load_source_entry_points
load_executor_entry_points
```

---

## 22. Open Questions

### 22.1 Should Plugin Discovery Be Enabled by Default?

Recommended v0 answer:

```text
no for imports;
yes only when an explicit setup path asks for discovery.
```

For example, a CLI `--plugins` or config field can request plugin loading later.

### 22.2 Should Entry Point Names or Object Keys Win?

Recommended answer:

```text
recipes: entry point name wins
codecs: object codec.key wins
```

Recipe names are catalog names. Codec keys are part of the codec contract.

### 22.3 Should Plugin Loading Instantiate Classes?

Recommended answer:

```text
yes only for no-argument classes/factories at simple extension points.
```

Anything requiring configuration should be built through `loom.config`
`_target_`.

### 22.4 Should Plugins Be Version-Constrained?

Recommended v0 answer:

```text
record distribution versions but do not solve constraints.
```

Python packaging owns dependency compatibility. Plugin validation can fail
clearly when an object is incompatible.

### 22.5 Should Third-Party CLI Commands Be Supported?

Recommended answer:

```text
not initially
```

Project packages can expose their own console scripts. Adding command injection
to `loom` should wait for a concrete need.

---

## 23. Summary

`loom.plugins` should be a small, explicit entry-point discovery layer.

Its main jobs are:

```text
list plugin entry points
load selected entry points
return structured load results
register recipes with recipe catalogs
register codecs with codec registries
detect duplicates deterministically
report plugin failures clearly
support provenance and optional CLI inspection
```

It should not become:

```text
a plugin marketplace
a package installer
a dependency resolver
a sandbox
a global import-time registry mutator
a domain-specific extension framework
```

Keeping plugin discovery explicit lets `loom` remain cheap to import,
deterministic in tests, and extensible for downstream packages that need recipes,
codecs, executors, or source backends.

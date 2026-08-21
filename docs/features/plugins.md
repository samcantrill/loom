# `loom.plugins` Specification

## 1. Purpose

`loom.plugins` centralizes optional extension discovery for `loom`.

It exists so downstream packages can contribute recipes, codecs, executors, data
sources, event sinks, and other extension points without modifying the generic
`loom` source tree.

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
How is a runtime event defined or emitted?
How does a notification backend deliver messages?
How does config composition work?
How does a CLI command run a pipeline?
```

The core rule is:

```text
Plugin discovery is explicit, opt-in, and adapter-shaped.
```

## Current Support

`loom.plugins` discovers and loads selected installed extension entry points
only when a caller asks it to. Direct event-sink registration is also available
through the runtime's explicit registry, without plugin discovery on import.

## Quick Start

Run the direct event-sink walkthrough:

```sh
uv run python examples/extensions/event-sink/run_event_sink.py
```

## Deferred

Import-time discovery, implicit installation, and service-specific notification
SDKs are not plugin-layer behavior.

Importing `loom` should not discover or import third-party plugins.

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) keeps plugin behavior outside the minimum runtime kernel. This
document describes the deferred extension layer that can connect downstream
recipes, codecs, sources, executors, event sinks, and CLI additions to explicit
registries without making plugin discovery a side effect of importing `loom`.

---

## 2. Core Position

`loom.plugins` is an optional coordination layer above subsystem registries.

Recommended dependency shape:

```text
config recipes / io codecs / executors / sources / event sinks
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
weave recipe catalog APIs
loom.io codec/source registry APIs
loom.pipeline executor registry APIs, when implemented
loom reliability event models, when implemented
```

It should not import:

```text
project packages except through explicit entry point loading
pipeline runner lifecycle
SLURM command wrappers directly
CLI modules
large optional dependencies
service-specific notification SDKs
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
optionally register loaded event sinks with an event sink registry
```

### 3.2 `weave.recipes`

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

### 3.5 Runtime Event Sinks

Runtime event semantics belong to `loom` reliability and execution layers.

Plugin responsibilities:

```text
discover event sink entry points
load observe-only event sink callables explicitly
register event sinks with a supplied event sink registry
report event sink load or registration failures
```

Plugin non-responsibilities:

```text
define runtime event semantics
emit lifecycle events
deliver Slack, email, PagerDuty, webhook, or monitoring notifications
decide whether a callback failure should fail a run
mutate plans, configs, artifacts, or run-store state
```

### 3.6 `loom.cli`

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
event sink entry point loading after runtime event models are stable
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
loom.sources
loom.executors
loom.artifact_store_backends
loom.run_exporters
loom.sweep_providers
loom.event_sinks
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
EventSinkRegistry
```

Plugins discover objects. Registries own runtime lookup.

### 5.7 Event Sink

An event sink is an observe-only callable that receives a structured runtime
event emitted by the execution or reliability layer.

Representative shape:

```python
EventSink = Callable[[PipelineEventRecord | EventReference, EventSinkContext], object]
```

Event sinks may send notifications, append audit logs, or forward events to an
external system. They must not mutate `loom` plans, configs, artifacts, stage
outputs, status transitions, retry decisions, or store records.

Runtime event names, payload shape, persistence, and callback failure policy
belong to the reliability and execution specifications. Plugin discovery only
loads and registers sink objects when explicitly requested.

---

## 6. Guiding Design Principles

### 6.1 Discovery Is Explicit

Do not discover plugins during:

```text
import loom
import weave
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
config = compose_config_with_catalog("experiment.yaml", recipe_catalog=catalog)
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

### 6.8 Keep Event Sinks Observe-Only

Event sinks are observers of committed runtime facts.

They may:

```text
receive PipelineEventRecord or EventReference values
write external audit or notification side effects
raise errors that are recorded as callback failures
```

They must not:

```text
change a pipeline plan
change config composition
change stage outputs
change artifact commit behavior
change retry, skip, or failure decisions
change run-store status directly
```

By default, event sink failures should be recorded and execution should
continue. A future strict mode may make callback failures fatal for audit-heavy
workflows, but that policy belongs to reliability/runtime options rather than
plugin loading.

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

### 7.5 Event Sinks

Registry-ready group:

```text
loom.event_sinks
```

Example:

```toml
[project.entry-points."loom.event_sinks"]
audit_log = "project.audit:LoomAuditSink"
```

Loaded object should be:

```text
event sink callable
event sink class with no-arg constructor
factory returning an event sink callable
```

The sink receives `PipelineEventRecord` or `EventReference` values from runtime
event dispatch. It should return `None` and must not mutate the event or runtime
state.

Programmatic registration remains the lowest-level setup path. Entry point
loading is available through `load_event_sink_entry_points(records, registry,
...)` and only registers into the supplied `EventSinkRegistry`.

### 7.6 Readiness Classifications

Readiness reports independent facts, not one broad claim. Every known group has
these fixed facets: `contract`, `python_injection`, `registry`,
`plugin_loading`, `cli_selection`, and `fresh_process_reconstruction`. A facet
is `supported`, `unsupported`, or `not_applicable`, and carries local evidence.
The compatibility `status` is derived: it is `registry-ready` only when both
`registry` and `plugin_loading` are supported; otherwise it is `listing-only`.

| Group | Contract / injection | Registry / loading | CLI / reconstruction | Derived status and revisit trigger |
| --- | --- | --- | --- |
| `loom.recipes` | supported / supported | supported / supported | unsupported / unsupported | registry-ready; add explicit run selection and activation evidence when a consumer needs them |
| `loom.codecs` | supported / supported | supported / supported | unsupported / unsupported | registry-ready; add explicit run selection and activation evidence when a consumer needs them |
| `loom.sources` | supported / `not_applicable` | `not_applicable` / `not_applicable` | `not_applicable` / `not_applicable` | listing-only; add a source-owned registry and adapter contract |
| `loom.executors` | supported / supported | unsupported / unsupported | unsupported / unsupported | listing-only; add an executor implementation registry and loader |
| `loom.artifact_store_backends` | unsupported / `not_applicable` | `not_applicable` / `not_applicable` | `not_applicable` / `not_applicable` | listing-only; publish a store-owned backend contract and registry |
| `loom.run_exporters` | supported / `not_applicable` | `not_applicable` / `not_applicable` | `not_applicable` / `not_applicable` | listing-only; define supplied exporter/importer registries |
| `loom.sweep_providers` | supported / `not_applicable` | `not_applicable` / `not_applicable` | `not_applicable` / `not_applicable` | listing-only; define a supplied provider registry |
| `loom.event_sinks` | supported / supported | supported / supported | unsupported / unsupported | registry-ready; add explicit lifecycle selection and activation evidence when needed |

`loom plugins list` and `loom plugins check` JSON use v2 envelopes so they can
include the full `group_readiness` records while preserving existing record and
group fields. Text diagnostics print each facet and its evidence.

Listing-only means discovery, CLI list output, and selected diagnostics may
report installed entry point metadata, but Stage 14 must not import targets,
construct runtime objects, mutate registries, probe credentials, validate URI
schemes, or claim run readiness for that group.

Stage 15 adds a specialized artifact-store backend adapter boundary. Artifact-store backend entry points
may be loaded only by code that supplies an `ArtifactStoreBackendRegistry`.
Loading a descriptor into that supplied registry proves descriptor compatibility;
it does not prove URI reachability, credentials, read/write/list support, or run
readiness. Those facts are checked through Stage 15 backend preflight targets
and handler capability admission.

### 7.7 CLI Commands

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
    load_event_sink_entry_points,
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

## 14. Event Sink Plugins

### 14.1 Purpose

Event sink plugin loading connects installed trusted packages to runtime event
observation.

The plugin layer discovers and loads sinks. The reliability and execution layers
define events, emit events, persist event records, and decide callback failure
policy.

Current signature:

```python
def load_event_sink_entry_points(
    records: Iterable[PluginRecord],
    registry: EventSinkRegistry,
    *,
    selected: Iterable[PluginRecord] | None = None,
    strict: bool = True,
) -> PluginLoadResult: ...
```

Programmatic registration should be available before entry point loading:

```python
event_sinks = EventSinkRegistry()
event_sinks.register("audit_log", ProjectAuditSink())
```

Entry point names are used as deterministic registry names, and the registration
path stays explicit and instance-local for deterministic tests.

### 14.2 Accepted Shapes

Recommended accepted shapes:

```text
callable event sink:
  register directly

event sink class:
  instantiate with no arguments

factory function:
  call with no arguments, register returned callable
```

Anything requiring configuration should be built through `weave`
`_target_` or project setup code, then registered programmatically.

### 14.3 Event Semantics Boundary

Runtime event records are facts emitted by `loom`.

Event sink plugins may observe:

```text
run.created
run.opened
run.planned
run.started
run.completed
run.failed
stage.planned
stage.started
stage.completed
stage.failed
stage.skipped
stage.reused
stage.blocked
```

The event list, event payload, persistence behavior, and timing of emission are
owned by the reliability and execution specifications. Event sinks should see
events only after the corresponding durable state transition has been recorded
where a durable transition exists.

### 14.4 Callback Failure Policy

Default behavior:

```text
record callback failure
continue execution
preserve the original callback exception through chaining or failure context
```

Callback failures are visible as event-adjacent observer facts when event
persistence and the runtime sink context can record them. A strict failure
policy may be added later, but plugin loading does not make observer failures
part of run correctness by default.

### 14.5 Event Persistence

When event sinks are configured, event persistence should be enabled by default
unless the caller explicitly disables it.

Persisted event records and observer facts are plain-data-compatible and do not
include loaded Python sink objects, callback closure state, raw credentials, or
large payloads.

### 14.6 Notification Boundary

Core `loom` should not provide service-specific notification backends.

Examples that belong in plugins or external wrappers:

```text
Slack
email
Teams
PagerDuty
generic webhook delivery
monitoring service SDKs
```

Core only needs the structured event record and observe-only sink registration
surface.

---

## 15. Duplicate Handling

### 15.1 Duplicate Entry Point Names

Within the same group, duplicate entry point names should be errors by default.

Reason:

```text
installation order should not decide which plugin wins
```

### 15.2 Duplicate Runtime Keys

Some plugins load objects that expose runtime keys:

```text
codec.key
executor.name
source scheme
event sink name
```

Duplicate runtime keys should also be errors by default.

### 15.3 Replacement

Allow replacement only when caller explicitly requests it:

```python
load_codec_entry_points(registry, replace=True)
```

Prefer explicit project setup for overrides:

```python
registry.register(ProjectJSONCodec(), replace=True)
```

### 15.4 Error Messages

Duplicate errors should include:

```text
group
name or runtime key
first entry point
conflicting entry point
distributions
```

---

## 16. Failure Policy

### 16.1 Strict Mode

Strict mode:

```text
raise on duplicate
raise on load failure
raise on invalid plugin object
raise on registry registration failure
```

Use strict mode for reproducible production runs.

### 16.2 Best-Effort Mode

Best-effort mode:

```text
return failures in PluginLoadResult
continue loading other plugins when safe
do not hide failures
```

Use best-effort mode for plugin inspection commands.

### 16.3 Load Failures

Load failures can come from:

```text
missing dependency
import error
constructor error
invalid object shape
duplicate registration
registry validation error
event sink callback registration error
```

Errors should preserve the original exception through chaining.

---

## 17. Security and Trust

### 17.1 Trusted Installed Packages

Loading an entry point imports installed Python code.

Treat plugin loading like importing a package:

```text
only load plugins from trusted environments
```

### 17.2 No Sandbox

V0 should not attempt to sandbox plugin code.

Reason:

```text
Python sandboxing is hard
configs are already trusted project code
entry points are installed code
```

### 17.3 Secret Handling

Plugin metadata normally should not contain secrets.

Still, error messages should avoid dumping:

```text
full environment variables
credentials in URLs
large object reprs
```

### 17.4 Import-Time Side Effects

The best mitigation for plugin side effects is explicit loading.

Do not load plugins during:

```text
loom --help
import loom
import loom.io
import weave
import loom.pipeline
```

unless a user command explicitly asks for plugin discovery.

---

## 18. Provenance

### 18.1 Plugin Provenance

When plugins are loaded for a run, provenance can record:

```text
entry point group
entry point name
entry point value
distribution name
distribution version
loaded runtime key, when relevant
load status
registered event sink name, when relevant
```

### 18.2 Event Sink Provenance

When event sink plugins are loaded for a run, provenance can record:

```text
entry point group
entry point name
entry point value
distribution name
distribution version
registered sink name
callback failure policy
event persistence setting
```

Do not persist loaded callback objects or service credentials.

### 18.3 Why It Matters

Plugin provenance helps answer:

```text
which package supplied this codec?
which recipe implementation expanded this config?
which package supplied this event sink?
did this run use entry point discovery or explicit registration?
which plugin version was installed?
```

### 18.4 Boundary

`loom.provenance` owns persisted provenance document shapes.

`loom.plugins` can provide plain-data plugin records for provenance to include.

---

## 19. CLI Integration

### 19.1 Commands

Implemented inspection commands:

```bash
loom plugins list
loom plugins list --group loom.codecs
loom plugins list --group loom.event_sinks
loom plugins check
```

### 19.2 `loom plugins list`

Should:

```text
list advertised entry points
not load plugins by default
support --load to verify loading explicitly
support --format json
```

### 19.3 `loom plugins check`

Should:

```text
load selected registry-ready groups in best-effort mode
report load failures
report duplicates
return non-zero when checks fail
return non-zero for unsupported listing-only load/check requests
```

For listing-only groups such as `loom.artifact_store_backends`,
`loom plugins check` reports metadata and listing-only status without importing
targets or claiming runtime availability. For `loom.event_sinks`, checks may
load selected targets into a scratch `EventSinkRegistry` but must not dispatch
events or write observer facts.

### 19.4 Event Sink Inspection

Plugin inspection commands may list event sink entry points without loading
them. Loading event sink targets requires an explicit `--load` or check command
because targets may import service SDKs or project packages.

Runtime event streaming or event-record inspection belongs to a future
CLI/runtime event feature, not to generic plugin listing. Current read-only
inspection uses run-store APIs for events, callback failures, and observer
links.

### 19.5 Deferred

Plugin CLI commands are not required for v0 pipeline execution. They are useful
once third-party plugins are common.

---

## 20. Error Model

### 20.1 Error Types

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

### 20.2 Error Context

Errors should include:

```text
group
entry point name
entry point value
distribution
runtime key, when available
target registry
event sink name, when available
```

### 20.3 Example Errors

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

Invalid event sink:

```text
Invalid event sink plugin "audit_log".
Expected a callable sink, no-argument sink class, or no-argument factory.
Actual object: project.audit:AuditConfig.
```

Callback registration failure:

```text
Could not register event sink "audit_log" from group "loom.event_sinks".
Target: project.audit:LoomAuditSink.
Reason: event sink name is already registered.
```

---

## 21. Testing Strategy

### 21.1 Discovery Tests

Test:

```text
list_entry_points filters by group
list_entry_points returns PluginRecord values
distribution metadata is included when available
missing distribution metadata does not fail
empty groups return empty tuple
```

### 21.2 Loading Tests

Use fake entry point objects.

Test:

```text
load_entry_points loads selected group
name filtering works
strict mode raises on load failure
best-effort mode records load failure
original exceptions are chained
```

### 21.3 Duplicate Tests

Test:

```text
duplicate entry point names rejected
duplicate codec keys rejected
replace=True allows explicit replacement where registry supports it
duplicate error includes both sources
```

### 21.4 Recipe Plugin Tests

Test:

```text
recipe entry point registers with catalog
entry point name is recipe name
invalid recipe object raises InvalidPluginError
catalog registration error is wrapped with plugin context
```

### 21.5 Codec Plugin Tests

Test:

```text
codec instance registers
codec class with no args instantiates and registers
factory function returns codec and registers
constructor failure is reported
missing codec key is invalid
duplicate runtime key is rejected
```

### 21.6 Event Sink Plugin Tests

Test:

```text
event sink callable registers
event sink class with no args instantiates and registers
factory function returns callable and registers
invalid non-callable sink raises InvalidPluginError
duplicate sink name is rejected
callback failure policy records and continues by default
event persistence setting is represented in plain data
```

Runtime event emission tests belong to reliability and execution suites. Plugin
tests should use fake `PipelineEventRecord` or `EventReference` values and fake
registries rather than running a pipeline.

### 21.7 Import Boundary Tests

Test:

```text
import loom does not discover plugins
import loom.io does not discover plugins
import weave does not discover plugins
import loom.pipeline does not discover plugins
loom --help does not load plugin modules
explicit load call imports plugin target
```

### 21.8 CLI Tests

When plugin CLI exists, test:

```text
loom plugins list does not load targets by default
loom plugins list --load reports load results
loom plugins check returns non-zero on failures
JSON output includes group/name/value/distribution
event sink entry points are listed without loading targets by default
```

---

## 22. Implementation Plan

### 22.1 Phase 1: Errors and Records

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

### 22.2 Phase 2: Generic Discovery

Implement:

```text
list_entry_points
load_entry_points
entry point group constants
strict and best-effort modes
duplicate entry point name detection
```

Use `importlib.metadata.entry_points`.

### 22.3 Phase 3: Recipe Integration

Implement:

```text
load_recipe_entry_points
RecipeCatalog registration adapter
recipe plugin validation
recipe plugin tests
```

### 22.4 Phase 4: Codec Integration

Implement:

```text
load_codec_entry_points
CodecRegistry registration adapter
codec instance/class/factory handling
runtime codec key duplicate reporting
```

### 22.5 Phase 5: Provenance Support

Add:

```text
PluginRecord.to_dict
PluginLoadResult summary conversion
loaded plugin provenance summaries
```

### 22.6 Phase 6: CLI Support

Landed for plugin inspection:

```text
loom plugins list
loom plugins check
```

### 22.7 Phase 7: Future Extension Points

After registries stabilize:

```text
load_source_entry_points
load_executor_entry_points
load_artifact_store_backend_entry_points
load_run_exporter_entry_points
load_sweep_provider_entry_points
```

### 22.8 Phase 8: Event Sink Plugins

Landed after runtime event models and an event sink registry stabilized:

```text
load_event_sink_entry_points
event sink registration adapter
observe-only sink validation
callback failure record integration through runtime dispatch
```

---

## 23. Open Questions

### 23.1 Should Plugin Discovery Be Enabled by Default?

Recommended v0 answer:

```text
no for imports;
yes only when an explicit setup path asks for discovery.
```

For example, a CLI `--plugins` or config field can request plugin loading later.

### 23.2 Should Entry Point Names or Object Keys Win?

Recommended answer:

```text
recipes: entry point name wins
codecs: object codec.key wins
event sinks: entry point name wins unless the registry defines explicit names
```

Recipe names are catalog names. Codec keys are part of the codec contract.
Event sink names are observer registration names and should be deterministic in
debug output.

### 23.3 Should Plugin Loading Instantiate Classes?

Recommended answer:

```text
yes only for no-argument classes/factories at simple extension points.
```

Anything requiring configuration should be built through `weave`
`_target_`.

### 23.4 Should Plugins Be Version-Constrained?

Recommended v0 answer:

```text
record distribution versions but do not solve constraints.
```

Python packaging owns dependency compatibility. Plugin validation can fail
clearly when an object is incompatible.

### 23.5 Should Third-Party CLI Commands Be Supported?

Recommended answer:

```text
not initially
```

Project packages can expose their own console scripts. Adding command injection
to `loom` should wait for a concrete need.

### 23.6 Should Event Sinks Be Enabled by Default?

Recommended answer:

```text
no for imports;
no for ordinary runs unless explicitly registered;
yes for event persistence when event sinks are explicitly configured, unless disabled.
```

Event sink registration is trusted code setup. Runtime event persistence should
default to inspectability once sinks are configured, but callers may disable it
when event volume becomes a problem.

---

## 24. Summary

`loom.plugins` should be a small, explicit entry-point discovery layer.

Its main jobs are:

```text
list plugin entry points
load selected entry points
return structured load results
register recipes with recipe catalogs
register codecs with codec registries
register event sinks with event sink registries
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
a service-specific notification package
```

Keeping plugin discovery explicit lets `loom` remain cheap to import,
deterministic in tests, and extensible for downstream packages that need recipes,
codecs, executors, source backends, or event sinks.

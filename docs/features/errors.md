# `loom.errors` Specification

## 1. Purpose

`loom.errors` defines the shared exception base classes and error-context
conventions for `loom`.

It exists so all subsystems can raise precise errors while downstream code and
the CLI can still handle failures consistently.

The package should answer:

```text
What is the common base class for loom exceptions?
Which broad categories can users catch?
What context should errors carry?
How should path-aware errors be represented?
How should subsystem errors wrap lower-level exceptions?
How should errors become CLI messages and exit codes?
```

It should not answer:

```text
Every concrete config error type.
Every concrete codec error type.
Every concrete pipeline planning error type.
How a stage should recover from a domain-specific failure.
How a scheduler reports every possible backend failure.
```

The core rule is:

```text
Shared roots live in loom.errors.
Concrete errors live next to the subsystem that raises them.
```

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) requires clear error handling across configuration,
construction, pipeline planning, execution, artifact state, resume, provenance,
and CLI presentation. This document turns that requirement into a shared error
model while preserving subsystem ownership of concrete failures and avoiding
domain-specific recovery semantics.

---

## 2. Core Position

`loom.errors` is a low-level shared module.

Recommended dependency shape:

```text
errors
  ^
  |
serialization / io / config / artifacts / pipeline / provenance / plugins / cli
```

It should depend only on:

```text
dataclasses
typing
```

It should not import:

```text
loom.config
loom.pipeline
loom.io
loom.serialization
project code
optional dependencies
```

This keeps the shared error root safe to import from any subsystem.

---

## 3. Package Boundary

### 3.1 `loom.errors`

Owns shared roots and common formatting/context conventions.

Responsibilities:

```text
LoomError
shared broad category roots
ErrorContext
path/context formatting helpers
structured error-to-dict conversion
exception chaining policy documentation
```

### 3.2 Subsystem Error Modules

Own concrete errors raised by that subsystem.

Examples:

```text
loom.config.errors.TargetInstantiationError
loom.serialization.errors.PlainDataError
loom.io.codecs.errors.UnknownCodecError
loom.pipeline.errors.StageContractError
loom.pipeline.stores.errors.CorruptRunStateError
loom.plugins.errors.PluginLoadError
```

Subsystem errors should inherit from a shared root, directly or through a
subsystem root.

### 3.3 `loom.cli`

Owns terminal presentation and exit code mapping.

Responsibilities:

```text
catch known LoomError values
format user-facing messages
honor --traceback
return documented exit codes
```

`loom.errors` may provide structured data and default message formatting, but the
CLI owns final presentation.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
LoomError base class
ErrorContext value object
broad category roots
message plus context fields
path-aware formatting
to_dict for machine output
exception chaining policy
subsystem inheritance conventions
basic CLI exit category mapping
tests for context rendering and inheritance
```

### 4.2 Should Support Soon

```text
hint support
did-you-mean suggestions supplied by callers
error code strings
JSON error output helpers
multi-error aggregation
warning model, if needed
```

### 4.3 Should Not Support in v0

```text
large custom diagnostics framework
localized messages
rich terminal rendering dependency
automatic typo correction everywhere
remote error reporting
error telemetry
domain-specific recovery instructions
full traceback persistence policy
```

Keep the shared layer small. Subsystems can add precise errors as needed.

---

## 5. Terminology

### 5.1 Loom Error

Any exception raised intentionally by `loom` and rooted under `LoomError`.

### 5.2 User-Facing Error

An error expected from invalid input, invalid state, missing files, bad configs,
stage failures, or backend failures.

These should produce concise CLI messages.

### 5.3 Internal Error

An unexpected bug or invariant violation.

These may still be wrapped in `LoomError` if detected intentionally, but unknown
exceptions should remain visible with `--traceback`.

### 5.4 Context

Structured fields that locate the failure.

Examples:

```text
config path
document path
file path
URI
run ID
stage name
artifact ID
input or output name
operation
```

### 5.5 Hint

Optional user-actionable guidance.

Example:

```text
Run `loom status runs/example` to inspect the failed stage.
```

### 5.6 Cause

The original lower-level exception.

Use Python exception chaining:

```python
raise ConfigLoadError(...) from exc
```

---

## 6. Guiding Design Principles

### 6.1 Broad Catching, Precise Raising

Subsystems should raise precise concrete errors.

Users should be able to catch broad roots:

```python
try:
    runner.run(request)
except PipelineError:
    ...
except ConfigError:
    ...
except LoomError:
    ...
```

### 6.2 Concrete Errors Stay Local

Do not put every concrete error in `loom.errors`.

Good:

```text
loom.errors.PipelineError
loom.pipeline.errors.StageContractError
```

Bad:

```text
loom.errors.StageContractError
loom.errors.UnknownCodecError
loom.errors.SlurmDependencyError
```

Local concrete errors keep modules understandable and avoid a giant root file.

### 6.3 Errors Must Be Path-Aware Where Possible

Errors should include the best available location:

```text
config path: pipeline.stages[2]._target_
stage: train
artifact: train.best_checkpoint
file: runs/example/stages/train/outputs.json
URI: file:///data/input.json
```

Generic messages without locations become expensive to debug.

### 6.4 Preserve Causes

Wrapping should add context, not erase the cause.

Good:

```python
raise CorruptRunStateError(
    "Could not read stage status.",
    context=ErrorContext(path="runs/example/stages/train/status.json"),
) from exc
```

Bad:

```python
raise CorruptRunStateError(str(exc))
```

### 6.5 Do Not Leak Secrets

Errors can include config paths and key names, but should not print unredacted
secret values.

Potentially sensitive fields:

```text
tokens
passwords
API keys
remote URLs with credentials
environment variable values
full command lines
```

Config and provenance redaction own detailed policy. Error constructors should
avoid including raw values unless needed and safe.

### 6.6 Separate Stage Failures From Loom Failures

A stage can fail because project code raised an exception. That is data for the
run result.

The executor/runner should generally persist:

```text
stage status FAILED
exception type
message summary
traceback path
logs
```

and reserve raised `LoomError` values for infrastructure problems such as bad
configuration, missing run state, invalid outputs, or unusable executors.

### 6.7 Machine Output Needs Structured Errors

CLI JSON output and tests should not parse human text.

Errors should support:

```python
error.to_dict()
```

or an equivalent helper that returns plain-data-compatible fields.

---

## 7. Public API

### 7.1 Recommended Imports

```python
from loom.errors import (
    LoomError,
    ErrorContext,
    ValidationError,
    ContractError,
    ConfigError,
    SerializationError,
    LoomIOError,
    ArtifactError,
    PipelineError,
    ExecutionError,
    ProvenanceError,
    PluginError,
)
```

### 7.2 Stable Top-Level Roots

Recommended roots:

```python
class LoomError(Exception): ...
class ValidationError(LoomError): ...
class ContractError(LoomError): ...
class ConfigError(LoomError): ...
class SerializationError(LoomError): ...
class LoomIOError(LoomError): ...
class ArtifactError(LoomError): ...
class FingerprintError(LoomError): ...
class PipelineError(LoomError): ...
class ExecutionError(PipelineError): ...
class ProvenanceError(LoomError): ...
class PluginError(LoomError): ...
```

The exact list can be introduced incrementally. The key requirement is that
subsystem roots share `LoomError`.

### 7.3 Import Stability

Subsystem modules may define their root locally and re-export it:

```python
from loom.errors import ConfigError
```

Then:

```python
from loom.config import ConfigError
from loom.errors import ConfigError
```

can both remain stable.

---

## 8. `LoomError`

### 8.1 Purpose

`LoomError` is the shared base for intentional `loom` failures.

Representative structure:

```python
class LoomError(Exception):
    def __init__(
        self,
        message: str,
        *,
        context: ErrorContext | None = None,
        hint: str | None = None,
        code: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None: ...
```

### 8.2 Required Fields

Every `LoomError` should have:

```text
message
```

Optional fields:

```text
context
hint
code
details
```

### 8.3 String Representation

`str(error)` should return a concise human-readable message.

It can include formatted context, but should avoid huge detail dumps.

### 8.4 Machine Representation

Recommended:

```python
def to_dict(self) -> dict[str, object]: ...
```

Shape:

```json
{
  "type": "ConfigValidationError",
  "message": "unknown stage",
  "code": "pipeline.unknown_stage",
  "context": {
    "config_path": "pipeline.stages[2].depends_on[0]"
  },
  "hint": null,
  "details": {}
}
```

Values should be plain-data compatible.

---

## 9. `ErrorContext`

### 9.1 Purpose

`ErrorContext` carries structured location fields.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class ErrorContext:
    path: str | None = None
    config_path: str | None = None
    document_path: str | None = None
    file_path: str | None = None
    uri: str | None = None
    run_id: str | None = None
    run_dir: str | None = None
    stage: str | None = None
    input_name: str | None = None
    output_name: str | None = None
    artifact_id: str | None = None
    codec_key: str | None = None
    operation: str | None = None
```

### 9.2 Field Meanings

```text
path:
  generic path within a structured document

config_path:
  path within authored or resolved config

document_path:
  path within a persisted JSON/YAML document

file_path:
  local filesystem path

uri:
  resource or artifact URI

run_id/run_dir:
  run identity

stage:
  stage name

input_name/output_name:
  stage input/output binding name

artifact_id:
  artifact identifier

codec_key:
  codec identifier

operation:
  operation being attempted
```

### 9.3 Extensibility

Do not add domain-specific fields such as:

```text
subject_id
model_name
dataset_split
metric_name
```

Project code can put domain metadata into `details` if needed.

### 9.4 Context Merging

Wrapping code may add context.

Recommended helper:

```python
def with_context(self, **updates: object) -> LoomError: ...
```

or create a new error with merged context.

Do not mutate existing context objects.

---

## 10. Error Codes

### 10.1 Purpose

Error codes are stable strings for machine handling.

Examples:

```text
config.load_failed
config.unknown_recipe
pipeline.cycle
pipeline.stage_contract
run_store.corrupt_state
io.unknown_codec
plugins.load_failed
```

### 10.2 V0 Policy

Error codes are optional in v0.

If included:

```text
use lowercase dotted strings
do not include dynamic values
keep codes stable once released
```

### 10.3 Human Messages Still Matter

Codes do not replace readable messages.

Every error should still have a clear `message`.

---

## 11. Broad Error Categories

### 11.1 `ValidationError`

Use for invalid structured input:

```text
invalid config shape
invalid pipeline spec
invalid artifact ref
invalid serialized document
```

Subsystems may subclass it:

```text
ConfigValidationError
PipelineValidationError
ArtifactValidationError
```

### 11.2 `ContractError`

Use when an implementation violates a declared contract:

```text
stage returns undeclared output
codec returns unsupported type
plugin object has invalid shape
recipe expands to invalid structure
```

### 11.3 `ConfigError`

Use for config loading, composition, recipe, override, interpolation, validation,
and target instantiation failures.

### 11.4 `SerializationError`

Use for conversion between Python objects, plain data, JSON, YAML, and schema
versioned documents.

### 11.5 `LoomIOError`

Use for URI, source, codec, byte access, and checksum verification failures.

The name `LoomIOError` avoids confusion with Python's built-in `IOError`.

### 11.6 `ArtifactError`

Use for artifact reference validation, artifact store operations, checksum
validation, artifact type mismatches, and artifact load/save failures.

### 11.7 `FingerprintError`

Use for digest formatting, hash algorithm, structured fingerprint input, and
fingerprint comparison failures.

### 11.8 `PipelineError`

Use for pipeline spec validation, graph planning, stage binding, resume,
execution orchestration, and stage contract failures.

### 11.9 `ExecutionError`

Use for runner or executor infrastructure failures.

Expected stage failures can be represented as `StageExecutionResult` data rather
than thrown through the runner as raw exceptions.

### 11.10 `ProvenanceError`

Use for provenance capture, validation, and redaction failures.

### 11.11 `PluginError`

Use for entry point discovery, load failures, duplicate plugins, invalid plugin
objects, and registration failures.

---

## 12. Subsystem Error Placement

### 12.1 Config

Local module:

```text
loom.config.errors
```

Examples:

```text
ConfigLoadError
ConfigMergeError
OverrideParseError
InterpolationError
ConfigValidationError
RecipeExpansionError
TargetInstantiationError
```

All should inherit from `ConfigError`.

### 12.2 Serialization

Local module:

```text
loom.serialization.errors
```

Examples:

```text
SerializationError
DeserializationError
PlainDataError
SchemaVersionError
```

`SerializationError` should inherit from `loom.errors.SerializationError` or be
the re-exported root itself. Avoid two incompatible classes with the same name.

### 12.3 I/O

Local modules:

```text
loom.io.errors
loom.io.sources.errors
loom.io.codecs.errors
```

Examples:

```text
UnsupportedURIError
DataSourceError
SourceNotFoundError
CodecError
UnknownCodecError
CodecDecodeError
ChecksumError
```

All should inherit from `LoomIOError`.

### 12.4 Pipeline

Local module:

```text
loom.pipeline.errors
```

Examples:

```text
PipelineValidationError
PipelinePlanningError
StageExecutionError
StageContractError
ArtifactBindingError
ResumeError
```

All should inherit from `PipelineError`.

### 12.5 Stores

Local module:

```text
loom.pipeline.stores.errors
```

Examples:

```text
RunStoreError
RunAlreadyExistsError
RunNotFoundError
CorruptRunStateError
RunLockedError
AtomicWriteError
```

These should inherit from `PipelineError` or a store root under `PipelineError`.

### 12.6 Plugins

Local module:

```text
loom.plugins.errors
```

Examples:

```text
PluginLoadError
DuplicatePluginError
InvalidPluginError
PluginRegistrationError
```

All should inherit from `PluginError`.

---

## 13. Message Shape

### 13.1 Recommended Human Format

Use short sections:

```text
Could not read stage status.

Run:
  example

Stage:
  train

Path:
  runs/example/stages/train/status.json

Reason:
  invalid JSON at line 1 column 12
```

### 13.2 First Line

The first line should be enough for a compact summary:

```text
Pipeline DAG contains a cycle.
```

### 13.3 Context Sections

Context sections should be stable and easy to scan:

```text
Config path:
Stage:
Input:
Output:
Artifact:
URI:
Path:
Operation:
Reason:
Hint:
```

### 13.4 Details

`details` are for structured data, not a dumping ground for huge values.

Keep details:

```text
plain-data compatible
small
non-secret
useful for JSON output
```

---

## 14. Wrapping Policy

### 14.1 When to Wrap

Wrap lower-level exceptions when crossing subsystem boundaries.

Examples:

```text
OSError -> DataSourceError
json.JSONDecodeError -> DeserializationError or CorruptRunStateError
ImportError -> TargetImportError or PluginLoadError
subprocess.CalledProcessError -> SlurmSubmissionError
```

### 14.2 When Not to Wrap

Do not wrap when the error is already precise and context is sufficient.

Example:

```python
raise
```

if catching only to re-raise the same `LoomError` without adding context.

### 14.3 Add Context While Wrapping

Good:

```python
except OSError as exc:
    raise SourceNotFoundError(
        "Could not open resource.",
        context=ErrorContext(uri=uri, operation="open rb"),
    ) from exc
```

### 14.4 Preserve Original Cause

Always use `from exc` when wrapping an exception.

Use `from None` only when intentionally hiding an irrelevant internal parse
detail. This should be rare.

---

## 15. Aggregated Errors

### 15.1 Purpose

Some operations discover multiple errors:

```text
config validation
pipeline validation
sweep expansion
plugin loading in best-effort mode
```

### 15.2 V0 Policy

Start simple:

```text
raise the first error for execution-blocking failures
return structured validation results for multi-error reporting when APIs need it
```

### 15.3 Future `ErrorGroup`

Possible future root:

```python
class LoomErrorGroup(LoomError):
    errors: tuple[LoomError, ...]
```

Python's `ExceptionGroup` can also be considered for supported versions.

Do not introduce a custom group until a concrete command needs multi-error
reporting.

---

## 16. CLI Mapping

### 16.1 Exit Codes

Recommended mapping:

```text
0:
  success

1:
  command completed but requested operation failed

2:
  usage or argument parse error

3:
  ConfigError

4:
  PipelineError during validation/planning

5:
  ExecutionError or failed run

6:
  run state, artifact inspection, or store error

7:
  executor or scheduler submission error

130:
  KeyboardInterrupt
```

### 16.2 CLI Formatting

Top-level CLI should catch `LoomError` and print:

```text
message
context
hint
```

No traceback by default.

### 16.3 `--traceback`

With `--traceback`, print full Python traceback including chained causes.

### 16.4 JSON Error Output

For machine-readable commands:

```json
{
  "ok": false,
  "error": {
    "type": "PipelineValidationError",
    "message": "unknown stage",
    "code": "pipeline.unknown_stage",
    "context": {
      "config_path": "pipeline.stages[1].depends_on[0]"
    },
    "hint": null
  }
}
```

---

## 17. Stage Failures and Tracebacks

### 17.1 Expected Stage Failure

If project stage code raises, execution should usually record a failed stage
result:

```text
status FAILED
exception_type
message
traceback_path
stdout/stderr paths
exit code, for subprocess
```

### 17.2 Infrastructure Failure

Raise `ExecutionError` or an executor-specific error for infrastructure issues:

```text
cannot create stage work directory
cannot build subprocess command
executor unavailable
run store write failed
stage result file missing
```

### 17.3 Traceback Storage

The execution layer owns traceback files.

The shared error layer only defines how the raised infrastructure error points
to them:

```text
context.file_path = "runs/example/stages/train/traceback.txt"
```

---

## 18. Redaction and Safe Values

### 18.1 Safe Context

Generally safe:

```text
field names
config paths
stage names
artifact IDs
codec keys
local filenames
```

Potentially sensitive:

```text
config values
environment values
tokens in URIs
command-line override values
remote URLs
```

### 18.2 Constructor Responsibility

Callers constructing errors should pass safe context and details.

Do not make the base error class inspect and redact arbitrary nested objects in
v0.

### 18.3 Hints

Hints should not include secrets.

Good:

```text
Hint: check that the recipe name is registered.
```

Bad:

```text
Hint: use token abc123...
```

---

## 19. Examples

### 19.1 Config Error

```text
Could not instantiate target project.stages.SummarizeStage.

Config path:
  pipeline.stages[1]

Reason:
  __init__() got an unexpected keyword argument 'formatterr'

Did you mean:
  formatter
```

### 19.2 Pipeline Binding Error

```text
Invalid pipeline input binding.

Stage:
  summarize

Input:
  manifest

Reference:
  build_manifest.manifest

Reason:
  stage "build_manifest" does not declare output "manifest"
```

### 19.3 Run Store Error

```text
Could not read stage status.

Run:
  example

Stage:
  train

Path:
  runs/example/stages/train/status.json

Reason:
  invalid JSON at line 1 column 12
```

### 19.4 Plugin Error

```text
Could not load plugin entry point "project_array".

Group:
  loom.codecs

Target:
  project.codecs:ArrayNpyCodec

Reason:
  No module named numpy
```

---

## 20. Testing Strategy

### 20.1 Base Error Tests

Test:

```text
LoomError stores message
LoomError stores context
LoomError stores hint and code
str(error) is readable
to_dict returns plain data
details must be plain-data compatible, if enforced
```

### 20.2 Context Tests

Test:

```text
ErrorContext to_dict omits None fields
context formatting is stable
config_path renders as Config path
stage renders as Stage
file_path renders as Path
context merging does not mutate original
```

### 20.3 Inheritance Tests

Test:

```text
ConfigError is LoomError
PipelineError is LoomError
LoomIOError is LoomError
ArtifactError is LoomError
PluginError is LoomError
subsystem concrete errors inherit expected root
```

### 20.4 Wrapping Tests

Test:

```text
wrapping preserves __cause__
wrapped error adds context
error message does not drop original reason
from None is not used accidentally in common wrappers
```

### 20.5 CLI Mapping Tests

Test:

```text
ConfigError maps to config exit code
PipelineValidationError maps to planning exit code
ExecutionError maps to execution exit code
KeyboardInterrupt maps to 130
--traceback prints chained traceback
JSON output includes structured error
```

### 20.6 Redaction Tests

Test:

```text
errors do not print detail values marked redacted
secret-like values are not included by default
URI credential redaction helper, if implemented
```

---

## 21. Implementation Plan

### 21.1 Phase 1: Shared Base

Create:

```text
src/loom/errors.py
```

Implement:

```text
ErrorContext
LoomError
to_dict
basic context formatting
```

### 21.2 Phase 2: Broad Roots

Add:

```text
ValidationError
ContractError
ConfigError
SerializationError
LoomIOError
ArtifactError
FingerprintError
PipelineError
ExecutionError
ProvenanceError
PluginError
```

Keep constructors inherited from `LoomError`.

### 21.3 Phase 3: Subsystem Alignment

Update subsystem error modules to inherit from shared roots:

```text
loom.config.errors
loom.serialization.errors
loom.io.errors
loom.pipeline.errors
loom.pipeline.stores.errors
loom.plugins.errors
```

Avoid duplicate incompatible root classes.

### 21.4 Phase 4: CLI Formatting

Add CLI helper:

```text
format_error
error_to_exit_code
error_to_json
```

These can live in `loom.cli.errors`, using the shared error structure.

### 21.5 Phase 5: Tests

Add:

```text
tests/unit/loom/test_errors.py
subsystem inheritance tests
CLI error mapping tests
```

### 21.6 Phase 6: Documentation Updates

As subsystem implementations land, update local error docs to reference the
shared roots.

---

## 22. Open Questions

### 22.1 Should Roots Be Defined Centrally or Re-Exported?

Recommended v0 answer:

```text
define broad roots in loom.errors;
re-export from subsystem packages where convenient.
```

This gives downstream users stable broad imports.

### 22.2 Should `ValidationError` Be Named More Specifically?

Potential concern:

```text
ValidationError conflicts visually with Pydantic and other libraries.
```

Recommended answer:

```text
use `ValidationError` under loom.errors because it is namespaced;
use specific names such as ConfigValidationError locally.
```

### 22.3 Should Error Codes Be Required?

Recommended v0 answer:

```text
no
```

Make `code` optional. Add codes to high-traffic errors once CLI/JSON automation
needs them.

### 22.4 Should Details Be Arbitrary Objects?

Recommended answer:

```text
no
```

Details should be plain-data compatible so JSON output and provenance remain
safe.

### 22.5 Should Warnings Use This System?

Recommended answer:

```text
not initially
```

Use Python warnings or structured result warnings until a unified warning model
is needed.

---

## 23. Summary

`loom.errors` should provide a small shared foundation for errors across the
package.

Its main jobs are:

```text
define LoomError
define broad subsystem roots
provide structured ErrorContext
support path-aware messages
support machine-readable error dictionaries
document wrapping and chaining policy
support CLI exit code mapping
```

It should not become:

```text
a dumping ground for every concrete exception
a diagnostics framework
a redaction engine
a telemetry system
a replacement for subsystem-specific errors
```

Keeping the shared layer small lets subsystems raise precise local errors while
giving users, tests, and the CLI one consistent way to catch, format, and inspect
failures.

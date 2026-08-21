# `loom.protocols` Specification

## 1. Purpose

`loom.protocols` defines the small set of package-wide structural protocols that
are genuinely generic across `loom`.

It exists so low-level shared contracts can be expressed without creating a
heavy inheritance framework or forcing downstream packages to subclass `loom`
base classes.

The module should answer:

```text
Which tiny structural behaviors are safe to use across subsystems?
Which contracts are generic enough to belong at the top level?
How should protocol imports remain cheap and dependency-light?
When should a protocol stay in its subsystem package instead?
How should protocol behavior be tested?
```

It should not answer:

```text
What is a pipeline stage?
What is a codec?
What is a data source?
What is an artifact store?
What is a run store?
What is a config recipe?
```

Those contracts belong to their subsystem packages.

The core rule is:

```text
Top-level protocols are tiny, generic, and dependency-light.
Subsystem protocols stay with the subsystem that owns their semantics.
```

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) favors structural protocols and explicit registries over
inheritance-heavy frameworks. This document applies that principle only to
package-wide protocols; stage, codec, source, store, recipe, and executor
contracts remain in their subsystem docs because their semantics are narrower.

---

## 2. Core Position

`loom.protocols` is a low-level shared module.

Recommended dependency shape:

```text
typing / typing_extensions, if needed
        |
        v
loom.protocols
        |
        v
refs / records / artifacts / config / io / pipeline / stores
```

It should depend only on:

```text
typing
```

or, only if needed for supported Python versions:

```text
typing_extensions
```

It should not import:

```text
weave
loom.pipeline
loom.io
loom.artifacts
loom.serialization
project code
optional dependencies
```

This keeps protocol imports safe for every layer.

---

## 3. Package Boundary

### 3.1 `loom.protocols`

Owns only package-wide generic protocols.

Initial candidates:

```text
Validatable
Fingerprintable
PlainSerializable, if needed
```

### 3.2 Subsystem Protocols

Subsystem protocols stay local.

Examples:

```text
loom.pipeline.stage.Stage
loom.io.codecs.base.Codec
loom.io.sources.base.DataSource
weave.recipes.base.ConfigRecipe
loom.pipeline.stores.artifact_store.ArtifactStore
loom.pipeline.stores.run_store.RunStore
loom.pipeline.executors.base.Executor
```

These protocols carry subsystem semantics and should not be pulled into the
top-level protocol module.

### 3.3 Contract Tests

`loom.protocols` defines structural expectations. `tests/contracts` defines
behavioral expectations for extension points.

Do not put test helpers in the runtime module.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
Validatable protocol
Fingerprintable protocol
cheap imports
stable public exports
unit tests for runtime-checkable behavior, if enabled
clear documentation of what does not belong here
```

### 4.2 Should Support Soon

```text
PlainSerializable protocol, if explicit to_dict support appears everywhere
Named protocol, if many objects expose stable name fields
HasMetadata protocol, only if broadly useful
```

### 4.3 Should Not Support in v0

```text
Stage
Codec
DataSource
ConfigRecipe
ArtifactStore
RunStore
Executor
large lifecycle protocols
domain-specific protocols
abstract base classes
registration logic
runtime validation framework
```

Adding broad protocols too early creates fake generality and import coupling.

---

## 5. Terminology

### 5.1 Protocol

A structural typing interface from Python's `typing.Protocol`.

An object satisfies a protocol by shape, not by inheritance.

### 5.2 Structural Typing

Structural typing means this works:

```python
class Thing:
    def validate(self) -> None:
        ...
```

`Thing` can satisfy `Validatable` without subclassing it.

### 5.3 Nominal Inheritance

Nominal inheritance requires explicit subclassing:

```python
class Thing(ValidatableBase):
    ...
```

`loom` should avoid nominal base classes for extension points unless a concrete
need appears.

### 5.4 Runtime Checkable Protocol

A protocol decorated with `@runtime_checkable` can be used with `isinstance`.

Use this sparingly. Runtime checks for protocols only verify attribute presence,
not full method signatures or behavior.

---

## 6. Guiding Design Principles

### 6.1 Prefer Structural Contracts

Downstream code should not need to inherit from `loom` classes to participate.

Good:

```python
class ProjectStage:
    def run(self, context):
        ...
```

Bad:

```python
class ProjectStage(RequiredLoomStageBase):
    ...
```

### 6.2 Keep Top-Level Protocols Rare

A protocol belongs in `loom.protocols` only when multiple unrelated subsystems
need the same tiny behavior.

Examples that may qualify:

```text
validate()
fingerprint()
to_dict()
```

Examples that do not qualify:

```text
run(context)
encode/decode bytes
open(uri)
save artifact
mark stage status
```

### 6.3 Do Not Hide Semantics

If a protocol's method has substantial behavior requirements, keep it in the
owning subsystem where that behavior can be documented.

For example, a `Codec` is not just any object with `encode` and `decode`. It has
codec keys, metadata rules, error rules, and registry behavior. It belongs in
`loom.io.codecs`.

### 6.4 Avoid Heavy Runtime Validation

Protocols are mainly for type checking and documentation.

Runtime validation should be explicit and local:

```text
codec registry validates codec.key and encode/decode behavior
pipeline validates stage run behavior
run store contract tests validate status behavior
```

### 6.5 Stable Imports Matter

Public imports should stay stable:

```python
from loom.protocols import Validatable, Fingerprintable
```

If internals move later, preserve this import path.

### 6.6 Protocols Do Not Replace Tests

A protocol says an object has a method. Contract tests prove the method behaves
correctly.

Use both:

```text
Protocol:
  shape

Contract test:
  behavior
```

---

## 7. Public API

### 7.1 Recommended Imports

```python
from loom.protocols import (
    Validatable,
    Fingerprintable,
)
```

Possible future:

```python
from loom.protocols import PlainSerializable
```

### 7.2 `__all__`

Recommended:

```python
__all__ = [
    "Validatable",
    "Fingerprintable",
]
```

Add future names only when implemented and documented.

---

## 8. `Validatable`

### 8.1 Purpose

`Validatable` represents objects that can validate their own structural
invariants.

Representative protocol:

```python
class Validatable(Protocol):
    def validate(self) -> None:
        ...
```

### 8.2 Behavior

`validate()` should:

```text
raise a LoomError or subsystem-specific validation error on invalid state
return None on success
avoid mutating the object
avoid I/O unless explicitly documented by the subsystem
```

### 8.3 Use Cases

Possible use cases:

```text
ResourceRef validation
ArtifactRef validation
PipelineSpec validation
StageSpec validation
SweepSpec validation
```

Subsystems may also expose dedicated validation functions instead of relying on
this protocol.

### 8.4 Non-Goals

`Validatable` should not define:

```text
schema conversion
config composition
artifact existence checks
domain correctness
```

Structural validation is not domain validation.

---

## 9. `Fingerprintable`

### 9.1 Purpose

`Fingerprintable` represents objects that can produce a stable semantic
fingerprint.

Representative protocol:

```python
class Fingerprintable(Protocol):
    def fingerprint(self) -> str:
        ...
```

### 9.2 Behavior

`fingerprint()` should:

```text
return an algorithm-prefixed digest string
be deterministic for semantically equivalent input
avoid wall-clock time and process-specific values
use loom.fingerprints helpers where practical
```

### 9.3 Use Cases

Possible use cases:

```text
stage fingerprint input helpers
artifact payload descriptors
config views
manifest filters
```

### 9.4 Caution

Do not use `Fingerprintable` to hide fingerprint policy.

Pipeline planning still owns which values go into a stage fingerprint. This
protocol only describes an object that can supply a digest for its own semantic
identity.

---

## 10. Future `PlainSerializable`

### 10.1 Purpose

A future `PlainSerializable` protocol may describe objects that can convert
themselves to plain data.

Possible shape:

```python
class PlainSerializable(Protocol):
    def to_dict(self) -> dict[str, object]:
        ...
```

### 10.2 Defer Until Needed

Do not add this until conversion behavior is stable across core objects.

Reasons:

```text
to_dict return type should align with loom.serialization.PlainData
from_dict behavior may be object-specific
schema version policy differs by document
```

### 10.3 Avoid Over-Generalization

Not every serializable object should be reconstructed generically.

Serialization policy remains in `loom.serialization` and public object
constructors.

---

## 11. Runtime Checking

### 11.1 Default Policy

Do not make every protocol runtime-checkable by default.

Runtime protocol checks are shallow and can create false confidence.

### 11.2 When To Use `@runtime_checkable`

Use it only when a registry or public API genuinely needs:

```python
isinstance(obj, Validatable)
```

Even then, prefer explicit checks when behavior matters.

### 11.3 Runtime Validation Belongs Locally

Examples:

```text
RecipeCatalog validates recipe expand behavior
CodecRegistry validates codec key and methods
Pipeline validates stage outputs
RunStore contract tests validate status persistence
```

---

## 12. Relationship to Subsystem Protocols

### 12.1 Stage

`Stage` belongs in `loom.pipeline.stage`.

Reason:

```text
stage semantics depend on StageContext, declared inputs, outputs, artifacts,
metadata, failure handling, and execution lifecycle.
```

### 12.2 Codec

`Codec` belongs in `loom.io.codecs.base`.

Reason:

```text
codec semantics depend on byte encoding, metadata, codec keys, registries, and
I/O errors.
```

### 12.3 DataSource

`DataSource` belongs in `loom.io.sources.base`.

Reason:

```text
source semantics depend on URIs, open modes, stat metadata, glob behavior, and
source errors.
```

### 12.4 Stores

`ArtifactStore` and `RunStore` belong in `loom.pipeline.stores`.

Reason:

```text
store semantics depend on persistence layout, atomic writes, locks, artifact
indexes, and status transitions.
```

### 12.5 Recipes

`ConfigRecipe` belongs in `weave.recipes`.

Reason:

```text
recipe semantics depend on config expansion, recipe catalogs, provenance, and
validation.
```

### 12.6 Stage 29 Scheduling Resources

`ResourcePlanner` belongs beside the managed queue scheduler, for example under
`loom.queue.scheduling`, rather than in `loom.protocols`.

Reason:

```text
its semantics depend on versioned whole-run placement requests, agent
inventory/availability, bounded candidate claims, exact reservation units, and
scheduler-safe failure explanations
```

Stage 29 has one accepted scheduler implementation, so it adds no public
`Scheduler` protocol. Its current hard constraints and soft preferences are
versioned tagged data with built-in dispatch, so it also adds no public callable
protocol for submitted rules. These choices keep the extension surface attached
to a real consumer and prevent wire or stored data from authorizing code
loading.

---

## 13. Error Model

### 13.1 Protocol Errors

`loom.protocols` should not define many errors.

Most failures should be raised by the subsystem using the protocol:

```text
ConfigValidationError
StageContractError
CodecRegistrationError
ArtifactValidationError
```

### 13.2 Shared Roots

If protocol-related errors need broad catching, use shared roots from
`loom.errors`:

```text
ValidationError
ContractError
```

Avoid adding `ProtocolError` until a concrete need appears.

---

## 14. Testing Strategy

### 14.1 Unit Tests

Test:

```text
protocols import cheaply
public exports are stable
simple objects satisfy Validatable for static type examples
simple objects satisfy Fingerprintable for static type examples
runtime_checkable behavior, only if enabled
```

### 14.2 Import Boundary Tests

Test:

```text
import loom.protocols does not import weave
import loom.protocols does not import loom.pipeline
import loom.protocols does not import loom.io
import loom.protocols does not import optional dependencies
```

### 14.3 Contract Tests

Behavioral contract tests belong in `tests/contracts`, not in
`tests/unit/loom/test_protocols.py`.

Examples:

```text
test_stage_contract.py
test_codec_contract.py
test_source_contract.py
test_artifact_store_contract.py
test_run_store_contract.py
```

---

## 15. Implementation Plan

### 15.1 Phase 1: Module and Exports

Create:

```text
src/loom/protocols.py
```

Implement:

```text
Validatable
Fingerprintable
__all__
```

### 15.2 Phase 2: Import Boundary Tests

Add:

```text
tests/unit/loom/test_protocols.py
tests/package/test_import.py coverage for cheap imports
```

### 15.3 Phase 3: Subsystem Alignment

Ensure subsystem protocols remain local:

```text
Stage -> loom.pipeline.stage
Codec -> loom.io.codecs.base
DataSource -> loom.io.sources.base
ArtifactStore -> loom.pipeline.stores.artifact_store
RunStore -> loom.pipeline.stores.run_store
```

### 15.4 Phase 4: Contract Tests

Add or align reusable contract tests for extension points under:

```text
tests/contracts/
```

---

## 16. Open Questions

### 16.1 Should `PlainSerializable` Exist?

Recommended v0 answer:

```text
not initially
```

Use explicit `to_dict` and `from_dict` methods on public objects first.

### 16.2 Should Protocols Be Runtime Checkable?

Recommended v0 answer:

```text
no unless a public API needs isinstance checks
```

Runtime protocol checks are shallow.

### 16.3 Should `HasMetadata` Exist?

Recommended answer:

```text
not until multiple unrelated subsystems need it
```

Many objects have metadata, but metadata semantics differ.

### 16.4 Should Protocols Be Re-Exported From `loom.__init__`?

Recommended answer:

```text
no
```

Keep top-level `loom` imports focused on public vocabulary such as refs,
records, artifacts, and fingerprints.

---

## 17. Summary

`loom.protocols` should be a tiny, dependency-light module for genuinely generic
structural contracts.

Its main jobs are:

```text
define Validatable
define Fingerprintable
keep imports cheap
document which protocols stay in subsystems
support structural typing without inheritance-heavy frameworks
```

It should not become:

```text
a dumping ground for every extension point
a runtime validation framework
a base-class hierarchy
a source of domain-specific contracts
```

Keeping top-level protocols small preserves the architecture: shared generic
vocabulary at the top level, subsystem semantics inside each subsystem, and
project behavior in downstream code.

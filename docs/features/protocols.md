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

For installed downstream implementations, the opt-in `loom.testing` package
provides bounded caller-sampled checks for codecs, resource validators,
executors, and event sinks. It returns versioned plain-data reports and is not
imported by runtime or package roots. These checks execute trusted supplied
objects and samples; they do not discover plugins or prove remote behavior,
credentials, performance, concurrency, or reachability.

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

### 12.6 Stage 29 Scheduling And Agent Extensions

`ResourcePlanner`, `HardConstraintEvaluator`, `PreferenceScorer`, and
`SchedulingPolicy` belong in the import-light `loom.scheduling` subsystem beside
the fixed managed stage-placement kernel, rather than in `loom.protocols` or
under the whole-run queue package.

`ResourcePlanner` does not replace the existing resource-validator protocol.
Validation owns authored/runtime entry shape and canonicalization; the planner
receives those accepted values and owns scheduling merge, feasibility, and
claims. Reconstruction preserves their separate identities.

The dependency direction is deliberate: `loom.scheduling` does not import
`loom.pipeline` at runtime. Its protocols consume scheduling-owned immutable
views of already-validated resource entries. The higher-level
`loom.pipeline.runtime` adapter converts the existing canonical
`ResourceEntry`/`ResourceRequest` values into those views, composes the built-in
CPU and memory planners, and rebuilds the existing durable codec. This avoids an
import cycle without introducing a second authored resource schema.

Reason:

```text
their semantics depend on resolved stage placement, versioned agent inventory/
availability, bounded candidate claims, mandatory-versus-additive feasibility,
integer preference vectors, exact reservation units, and scheduler-safe
explanations/proposals
```

The fixed `SchedulingKernel` is concrete rather than a public full-scheduler
protocol. It owns component/version validation, bounded candidate construction,
non-overridable system checks, additive-rule/score ordering, proposal validation,
and the guarantee that scheduling returns data without mutation. A custom hard
evaluator may only remove a candidate, a preference may only add a bounded
integer score, and a policy may select only an existing kernel-validated
candidate ID or a typed wait. None may reserve, bind, launch, or commit stage
truth.

Hard evaluators and preference scorers also validate/canonicalize their own
bounded tagged specs at admission. Only resolved immutable specs enter a
scheduling snapshot; invalid, unknown, or nondeterministically reconstructed
specs fail before queueing. `SchedulingPolicy` is selected/configured only by
trusted deployment composition and is validated before readiness.

Each implementation has a scheduling-subsystem descriptor and is supplied
through an instance-local registry frozen by trusted deployment composition.
The descriptor separates implementation fingerprint from a non-secret canonical
configuration fingerprint; changing configured semantics creates a new identity
even when package code is unchanged.
Tagged stored/wire specs select only an allowed kind/version already present in
that registry; they never carry callables or import targets. Stage 29 supports
direct Python composition and public bounded `loom.testing` conformance checks,
not automatic plugin discovery. A full scheduler/lifecycle plugin, universal
service registry, and payload-selected rule remain excluded.

`AgentResourceProvider` belongs with the agent application surface, not in
`loom.scheduling` or root `loom.protocols`, because it owns local observation,
durable prepare/reconcile/activate/abort/release, and private live provider
tokens. It is paired with a pure `ResourcePlanner` through a negotiated
resource-claim contract; wire claims contain only safe versioned evidence.
Planner and provider keep distinct implementation descriptors; compatible data
is not permission for a replacement implementation to adopt old live state.
Existing queue assignment/GPU providers may be compatibility-adapted behind
this stronger lifecycle.

Coordinator-state, agent-journal, and client/agent/operator application-port
protocols remain subsystem infrastructure boundaries. They have current SQLite,
in-memory-test, direct, and HTTP implementations, but are not package-root
plugin APIs. Their methods express semantic atomic transitions and least-
privilege views rather than generic CRUD or one broad service object.

Per-run authority remains a separate service/API owner. Stage 29 adds only a
narrow coordinator authority adapter whose construction captures an
authenticated least-privilege coordinator principal and expected authority
service/workspace/generation identity. Direct or verified owner-only IPC and
persistent mTLS HTTP adapters invoke the same authority authorization and
expected-state operations. This is infrastructure, not a downstream plugin
protocol; agents and workers never receive it or direct authority database
access. A separate coordinator infrastructure reconciler may adopt a rotated
service generation only after complete retained-run continuity: every retained
run reproduces its last-acknowledged authority revision/canonical full-snapshot
fingerprint and each nonterminal attempt/execution fence matches exactly. The
coordinator checkpoint is comparison evidence, not authority truth. A pristine
empty authority is valid only when the coordinator has no retained admitted
run. Neither the scheduling kernel nor an agent may make that decision.

Dependency readiness is not another resource or scheduler protocol: one
authority-side planning predicate is shared by orchestration and assignment CAS,
while the pure kernel receives only already-ready stage attempts.

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

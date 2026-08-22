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
receives those accepted values and owns scheduling merge, closed opportunity
validation/canonicalization, intrinsic resource feasibility, complete bounded
claim search, claim validation, and explanations. Intrinsic means quantity,
unit, allocation mode, per-instance attributes, and topology among instances of
that resource. Additive hard evaluators operate only on complete placements and
own cross-resource, agent, pool/site, or whole-placement predicates.
Reconstruction preserves validator and planner as separate identities.

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
availability, complete bounded candidate claims, mandatory-versus-additive
feasibility, checked tiered preference vectors and quality bands, exact
namespaced reservation units, and scheduler-safe
explanations/proposals
```

The fixed `SchedulingKernel` is concrete rather than a public full-scheduler
protocol. It owns component/version validation, complete bounded per-resource
and composite candidate construction, non-overridable system checks,
additive-rule ordering, checked site-owned lexicographic tier aggregation,
durable-time fallback eligibility, grouped-work proposal validation, and the
guarantee that scheduling returns data without mutation. Any exhausted search
is indeterminate and cannot authorize assignment; Stage 29 has no partial-search
winner-proof contract. A custom hard evaluator may only remove a complete
candidate, a preference may only return bounded utility/quality-band evidence,
and a policy may select only an existing kernel-validated
`(stage_work_id, candidate_id)` from grouped `WorkEvaluation` values or a typed
wait. None may reserve, exceed run concurrency, bind, launch, or commit stage
truth.

Hard evaluators and preference scorers also validate/canonicalize their own
bounded tagged specs at admission. Only resolved immutable specs enter a
scheduling snapshot; invalid, unknown, or nondeterministically reconstructed
specs fail before queueing. `SchedulingPolicy` is selected/configured only by
trusted deployment composition and is validated before readiness. It belongs
to a coordinator scheduling epoch rather than a stage placement; each
assignment records that policy descriptor and bounded decision evidence so a
later policy epoch can reorder only still-unassigned work.

Each implementation has a scheduling-subsystem descriptor and is supplied
through an instance-local registry frozen for one trusted deployment
configuration epoch. Registries distinguish active bindings for fresh
resolution from exact descriptor-keyed retained bindings required by
nonterminal work or live claims; reload preserves all references or fails
before swap.
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

Stage 29 adds a concrete ready-stage SLURM composition, not a generic
`ExternalScheduler` plugin protocol. Existing `SlurmCommandRunner`, pure
resource/directive mapping, deterministic script rendering, parsable job-ID,
status, and cancel seams remain under `loom.pipeline.executors.slurm`. The
coordinator application/store owns the durable route/profile admission,
submission-operation state machine, exact handle reconciliation, bootstrap
authorization, and lifecycle join. Historical whole-run queue/live SLURM
controllers keep their separate ownership.

The coordinator assignment target is a closed tagged value. The managed variant
names an agent/session/offer/claim. The SLURM variant names one retained profile,
request fingerprint, and stable submission operation and holds no agent claim.
Semantic store operations atomically enforce the run concurrency/profile slots,
bind the exact authority attempt, persist intent/`SUBMITTING`, record the closed
accepted/definitely-rejected/unknown outcome, associate one exact scheduler
handle, and reconcile restart. They do not expose generic submit-row CRUD or
permit a second automatic external call.

A separate restricted bootstrap application view is an infrastructure port. Its
construction captures an assignment-scoped principal; operations verify the
exact profile, assignment, submission operation, scheduler job, bootstrap
incarnation, request digest, issuer epoch, and fence. It may register/reconcile,
use the assignment-scoped artifact port, request one exact grant/start permit,
and report process/result facts. It cannot publish offers, accept arbitrary
work, inspect unrelated runs, submit jobs, impersonate an agent, or invoke
authority directly. Direct test adapters and authenticated transport adapters
must produce the same domain outcomes.

Remote agents use an outbound-only topology. They authenticate the expected
coordinator, perform a no-mutation capability handshake, register or resume the
coordinator-issued durable session, reconcile journal/outbox/claim/transfer
facts, publish a fresh current-epoch offer, and hold one availability-revision-
bound long poll. The coordinator—not the poll or agent—chooses one globally
validated ready-work/candidate pair and completes that exact request after its
reservation transaction. Agents expose no inbound scheduling listener and do
not communicate with peers. Local direct/IPC and remote HTTP adapters must
produce the same application outcomes.

Protected role configuration supplies explicit local state roots, endpoints
and expected service identities, trust/certificate/key references, principal/
pool policy, manageable provider-backed resources, scheduling components, and
resident capabilities, plus protected named SLURM profiles and bootstrap
credential/data-path configuration when enabled. These are deployment inputs rather than protocol body
authority. Exact CLI/env names and route layout remain private; private keys and
authority credentials never enter job configuration, durable work records,
offers, audit output, or worker environments.

After explicit first initialization, inter-service startup order is not a
protocol dependency. An early agent reconnects at zero availability, a
coordinator without agents retains waiting work, and a coordinator without its
authority may admit only `PENDING_AUTHORITY`. Authority then coordinator then
agents is the recommended low-noise order, not a safety requirement. A new
connection or process epoch never creates capacity: reconciliation and a fresh
offer/work request are mandatory before delivery.

Reload is split at that owner boundary. The coordinator's transaction validates
and swaps planners, hard evaluators, preference scorers, scheduling policy, and
SLURM profiles while retaining exact profile bindings named by nonterminal
submissions.
An agent's independent transaction validates and swaps its pools, providers,
inventory, and resident capabilities. Each retains the descriptors referenced
by its own durable nonterminal state. There is no distributed configuration
transaction; incompatible claim-contract revisions temporarily make an
opportunity ineligible.

Those semantic ports also fix identity and replay behavior. Managed admission
atomically creates-or-returns one `(coordinator_id, run_uri)` record
bound to a normalized intent digest and execution owner. Its coordinator commit
may be `PENDING_AUTHORITY`, with the authority-operation intent already durable;
only reconciliation of the exact authority owner, intent digest, and operation
receipt promotes it to `ACTIVE` and exposes work. Exact replay returns either
state and conflicting intent/owner is not another admission. A stable
coordinator ID belongs to the state root while a process epoch rotates;
assignments preserve their issuer epoch. `StageWorkRecord` rebuild reproduces
the same ID for its admission/stage/attempt/readiness-generation key.

Critical agent events carry stable IDs and a monotonic per-assignment sequence.
The coordinator transition accepts next-or-exact-replay, reports gaps without
advancing, and acknowledges only durably stored contiguous evidence. Direct and
HTTP adapters expose the same definite domain outcomes. Timeout, disconnect,
caller cancellation, or 5xx after send is indeterminate and must replay the
same principal/operation/idempotency-key/request-digest; connection close is not
a domain cancellation command.

An agent reconnect normally resumes its durable session. Clean rollover is a
semantic retirement transaction requiring the authenticated old session,
fenced delivery, and an exact empty complete session-reference set,
followed by a tombstone. Any non-empty, lost, or unavailable old session uses the
separate positive-containment recovery operation. These are infrastructure
contracts, not an extensible session provider.

Session allocation is a coordinator idempotent operation; the agent persists
the registration operation identity/digest before send and the returned session
identity before its first offer. The authoritative retirement query
also covers provider preparations, work requests/delivery, results/outputs, and
sequenced event/outbox state, and must be extended when another session-scoped
durable reference is introduced. Authentication is evaluated against the
current credential-policy revision on every request and long-poll renewal.
Credential removal fences future operations on an existing connection but does
not itself retire a session or contain a process.

Per-run authority remains a separate service/API owner. Stage 29 adds only a
narrow coordinator authority adapter whose construction captures an
authenticated least-privilege coordinator principal and expected authority
service/workspace/generation identity. Direct or verified owner-only IPC and
persistent mTLS HTTP adapters invoke the same authority authorization and
expected-state operations. This is infrastructure, not a downstream plugin
protocol; agents and workers never receive it or direct authority database
access. The authority also binds each managed run to the stable coordinator ID
and owns the effective cancellation epoch; the coordinator owns only the durable
client request and control fan-out. A separate coordinator infrastructure
reconciler may adopt a rotated service generation only after one authority-owned
consistent authority-relevant cut. Before each coordinator-originated authority
mutation, the coordinator persists a stable operation ID, canonical intent
digest, principal, and expected state/revision; authority stores the matching
receipt atomically with its domain mutation. Each retained admission/tombstone
must either match the last acknowledged checkpoint or advance through an
ordered chain of those receipts. A regression, missing receipt, owner/intent
mismatch, unexplained mutation, or torn cut fails closed. The coordinator
checkpoint is comparison evidence, not authority truth. A pristine empty
authority is valid only when the coordinator has no authority-relevant retained
admission/tombstone. Neither the scheduling kernel nor an agent may make that
decision.

The transfer port likewise separates durable object identity from permission.
One immutable assignment-scoped transfer ID owns exact offset/content/finalize
progress, while a renewable short-lived authorization ID/revision gates byte
operations. Expiry or coordinator epoch change invalidates only that
authorization; exact replay resumes the same transfer and conflicting content
fails closed.

Production role-store ports distinguish explicit initialization from opening an
existing role. Initialization alone may create a verified absent/empty target
and stable role identity; ordinary start requires the expected identity and
fails on missing, corrupt, or mismatched state. In-memory test adapters do not
weaken this production behavior.

Coordinator infrastructure also owns one injectable/testable time source with
a durable nondecreasing accepted-time high-water. Scheduling snapshots receive
its explicit `as_of`; offer expiry, receipt/freshness, and fallback use the same
accepted time. This is not a public scheduling-policy hook. Runtime clock
regression or an out-of-policy jump yields a closed degraded outcome and no new
scheduling until reconciliation.

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

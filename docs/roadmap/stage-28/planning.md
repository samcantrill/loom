# Roadmap v28 Planning: Reconstructable Runtime Extensions And Lifecycle Hooks

Status: confirmed; implementation-plan and cross-stage correction quality gates passed
Roadmap stage: v28
Evidence tree: `/home/can134/work/active/loom` on `develop` at
`2c05906c15791a025ff2cae90633d77efdc89aac`; unrelated concurrent roadmap edits
are preserved
Planning route: expanded because public plugin/executor registration, durable
worker reconstruction, resource-validation threading, and callback contracts
interact
Current gate: planning workflow complete; Phase 1 not started
Blockers: none; Stage 27 is a sequencing dependency rather than a planning
blocker

## Plain-Language Overview

Stage 28 makes four existing extension promises true through the complete path
that users actually run. A Python protocol or installed entry point is not, by
itself, proof that Loom can select that implementation from the CLI or rebuild
it in a fresh worker. The stage separates those capabilities, reports them
honestly, and implements only the combinations with a current runtime consumer.

The four in-scope extension types are:

| Extension | What project code supplies | Process that constructs it |
| --- | --- | --- |
| Ordinary executor | How one stage request is executed | The dispatch owner, before it launches or calls the executor |
| Codec | How a project artifact is encoded and decoded | Each parent or worker process that constructs the artifact store |
| Resource validator | How a custom resource kind is checked | Each process that parses or reconstructs pipeline/runtime resources |
| Event sink | What observe-only action follows a lifecycle event | Only the process that commits that event |

The intended user journey is deliberately explicit:

1. A downstream package implements one of the public contracts and checks it
   with the opt-in `loom.testing` helpers.
2. The package publishes a normal Python entry point for the owning subsystem.
3. A Python composition root injects the object directly, or a CLI caller
   selects the exact `GROUP:NAME` with `--plugin`.
4. Loom records only safe entry-point identity and passes only the applicable
   selectors to a fresh process.
5. That process rediscovers and verifies the selected entry point before using
   project stage code, configuration, artifacts, or callbacks.

Nothing is loaded merely because it is installed or mentioned in stored run
data. With no explicit activation, current built-in behavior and import cost
remain unchanged. This is not a universal plugin container: each subsystem
keeps its own registry and each process builds only the dependencies it consumes.

## Current State

| Extension surface | Reachable behavior now | Missing or intentional limit |
| --- | --- | --- |
| Stages | `Stage`, `factory._target_`, CLI config, and worker reconstruction form the strongest extension path. | No gap in the motivating path; keep this as the model. |
| Codecs | `CodecRegistry` and explicit `loom.codecs` loading work. | CLI/artifact-store defaults replace the selected registry in fresh workers. |
| Executors | `PipelineRunner` accepts an `Executor`; descriptors describe capabilities. | CLI uses a private built-in switch; `loom.executors` is listing-only; descriptor and factory can disagree. |
| Resource validation | `ResourceValidatorRegistry` composes custom dotted kinds. | specs, runtime parsers, and continuations repeatedly fall back to built-ins. |
| Artifact stores/backends | Factories are injectable; backend descriptors, handlers, registry/loader, config, preflight, and capability checks exist. | “Listing-only” does not distinguish descriptor loading from runtime reachability. |
| Run/authority stores | Store protocols and `RuntimeServices` allow explicit implementations. | Authority remains deployment wiring, not ambient plugin activation. |
| Event sinks | Registry, `RunRequest` injection, plugin loader, post-append dispatch, observer links, and captured failures work. | Sinks see every event and normal run CLI setup cannot activate them. |
| Sweep/run exchange/source | Provider and adapter protocols exist; run exchange exposes portable records; `DataSource` has a local implementation. | Sweep specs are closed to built-ins, convenience exchange APIs choose local adapters, and no runtime source consumer exists. |
| Reliability/queue policy | Reliability protocols and operational queue/provider seams exist. | Some have no runner consumer; queue/placement seams own authority-sensitive behavior and Stage 25 remains pending. |

The problem is not a shortage of protocols. It is the unreported gap between a
contract, a selectable implementation, and reconstruction in the process that
actually consumes it.

## Evidence And Scope

The current path is evidenced by `pipeline/stage_factory.py`, `specs.py`,
`io/codecs/registry.py`, `plugins/codecs.py`, `stores/local_artifacts.py`,
`executors/base.py`, `runtime/capabilities.py`, `execution/runner.py`,
`execution/models.py`, `execution/stage_worker.py`, `execution/continuation.py`,
`pipeline/resources.py`, `pipeline/event_sinks.py`, `execution/eventing.py`,
`plugins/diagnostics.py`, and `cli/run.py`. Existing package/contract tests
already protect cheap imports, explicit discovery, codec loading, descriptors,
worker records, event dispatch, and future plugin-group listing.

Stage 26 settles the operational lifecycle catalog and corrects commit-before-
observe ordering without adding notification policy. Generic scheduling,
observed usage, and new reuse design remain deferred beyond Stage 26. Stage 27
keeps GPU inventory/layout/provisioning. Stage 28 owns exact event-name filters
and custom resource validation but must not take lifecycle or authority
ownership from their existing subsystems.

## Minimum Useful Change

A downstream package implements an ordinary stage `Executor`, codec, resource
validator, and event sink; runs versioned conformance checks; then activates the
implementations explicitly from Python or relevant CLI commands. The dispatch
owner builds the executor. A fresh artifact/config worker rebuilds codecs and
validators. A lifecycle-commit owner rebuilds event sinks, which may subscribe
to exact event names. With no activation, behavior and import cost are unchanged.

## Functional Requirements

| ID | Requirement | Observable acceptance |
| --- | --- | --- |
| FR-1 | Defaults and loading stay explicit. | Existing calls select built-ins; help/list/status/inspect/default run import no plugin target. |
| FR-2 | Readiness uses independent capabilities. | Diagnostics report contract, Python injection, registry, plugin loading, CLI selection, and fresh-process reconstruction as supported, unsupported, or not applicable, with evidence. |
| FR-3 | Downstream contract checks are public and bounded. | Codecs, validators, ordinary executors, and sinks return versioned reports without `pytest` or discovery side effects. |
| FR-4 | Executor behavior and capability claims stay paired. | One registration owns matching descriptor/factory/name; mismatch fails before execution. |
| FR-5 | Activation is exact and instance-local. | Repeated `GROUP:NAME` selectors resolve one record each into caller-owned registries; no global mutation occurs. |
| FR-6 | Resource validation survives every construction boundary. | Validate, plan, preflight, run, runtime parsing, config reconstruction, and continuation use the selected registry. |
| FR-7 | Artifact handling uses the selected codecs. | Local and subprocess artifact-store factories use the custom codec registry. |
| FR-8 | Each process constructs only dependencies it consumes. | Workers rebuild codec/validator state; dispatch owners build executors; lifecycle owners build sinks, without recursion or duplicate observation. |
| FR-9 | Durable evidence stores identity, never objects. | Versioned plain data records selected entry points; no callable, registry, credential, or plugin-private state is serialized. |
| FR-10 | Reconstruction fails closed. | Missing, duplicate, changed-target, invalid, or unsupported activation fails before stage/sink invocation. |
| FR-11 | Event subscriptions remain observe-only. | Unfiltered sinks observe all; filtered sinks observe an exact allowlist after commit; failures remain recorded and non-fatal. |
| FR-12 | Narrower protocols remain honest. | Sources/reliability stay contract-only; run exchange documents direct adapters; sweep discovery waits for a custom-spec boundary; authority stays explicit. |

## Functionality Agreement

| Question | Decision | Reason | Status |
| --- | --- | --- | --- |
| What is “extension readiness”? | Six independent capabilities, not one maturity ladder. | CLI and worker applicability differ by component. | locked |
| What loads project code? | Direct Python setup or exact explicit CLI activation. | Installed/stored metadata alone remains inert. | locked |
| What becomes executable? | Ordinary stage executors, codecs, validators, and observe-only sinks. | Each has a current consumer and demonstrated gap. | locked |
| Is there one extension registry? | No; subsystem registries remain authoritative and setup composes them privately. | Avoid a service locator and duplicate ownership. | locked |
| Does a worker rebuild its dispatch executor? | No; it rebuilds only worker-side dependencies. | Rebuilding a launcher can recurse or resubmit. | locked |
| Can callbacks change behavior? | No; only post-commit observation with exact event filters. | Mutable hooks create a second lifecycle/policy owner. | locked |
| Does resume/inspection auto-load stored plugins? | Inspection never loads; user-started resume explicitly reselects; an authorized prepared worker verifies recorded activations. | Opening imported/old evidence must not execute code. | locked |
| Are all protocols wired? | No; a registry requires a real consumer and authoritative decision path. | Protocol shape alone is insufficient. | locked |

## Behavior Baseline

| Scenario | Required behavior |
| --- | --- |
| Ordinary run | Existing built-ins, zero discovery. |
| Python executor | Direct `PipelineRunner(executor=...)` remains valid. |
| CLI executor | Activation registers descriptor/factory; preflight uses the descriptor; the factory receives explicit services/options. |
| Subprocess codec | Worker verifies activation and builds `LocalArtifactStore` with the selected registry. |
| Custom resource | The same validator parses parent/worker config; executor descriptor separately decides capability. |
| Filtered sink | `stage.completed` fires only after durable commit; unrelated events do not invoke it. |
| Failing sink | Failure evidence is recorded, later sinks run, and runtime state is unchanged. |
| Changed environment | Reconstruction mismatch fails before stage construction or artifact decoding. |

## Minimum Design

`loom.plugins.diagnostics` remains the executable owner for entry-point group
readiness. `PluginGroupReadiness` keeps its existing fields and adds a sorted
capability mapping with keys `contract`, `python_injection`, `registry`,
`plugin_loading`, `cli_selection`, and `fresh_process_reconstruction`. Each
entry is plain data with `status` (`supported`, `unsupported`, or
`not_applicable`) and concise `evidence`; the legacy group `status` is derived
from these facets rather than separately maintained. Feature docs apply the
same vocabulary to non-plugin seams; no global readiness registry is added.

An opt-in `loom.testing` package is never imported by runtime/package roots. It
provides immutable `ContractFinding` and `ContractReport` values with contract
name/version, deterministic findings, `ok`, `to_dict()`, and
`raise_for_errors()`, plus checks for the four in-scope types. Checks accept
caller sample cases/fixtures so shallow structural checks do not overpromise
behavior.

`loom.pipeline.executors` owns an `ExecutorFactory` callable with explicit
keyword inputs `services: RuntimeServices` and `options: RunOptions`, plus
`ExecutorRegistration` (`descriptor`, `factory`) and an instance-local
`ExecutorRegistry`. There is no wrapper context and no separately supplied
executor name. The registry rejects duplicates, projects descriptors for
capability validation, and validates the built executor's name once against the
descriptor. Built-in ordinary executors use the same path; SLURM afterok/single-
job remain specialized continuations.

Relevant commands accept repeated exact selectors, for example:

```text
--plugin loom.executors:project-executor
--plugin loom.codecs:array-npy-v1
--plugin loom.resource_validators:accelerator.tpu
--plugin loom.event_sinks:project-audit
```

The plugin layer resolves each to exactly one existing `PluginRecord`. Prepared
metadata contains one reserved versioned document of sorted record summaries:
group, name, target, and available distribution name/version. Existing
`PluginRecord` gains strict readback if sufficient; no generic component-
reference schema is added. Workers re-discover and compare applicable records
before importing stage code.

`loom.resource_validators` becomes a known group. Its entry-point name is the
sole resource-kind identity and its target must directly satisfy the existing
`ResourceValidator` callable contract. The loader calls
`ResourceValidatorRegistry.with_validator(record.name, target)`, which remains
the sole kind/duplicate validator; no registration wrapper, class constructor,
or no-argument factory form is added. Executor targets normalize to
`ExecutorRegistration`. Existing codec and sink target forms remain compatible.

Dependency threading stays targeted:

- pipeline/runtime parse functions accept an optional validator registry;
  `StageSpec.resources` remains the existing authored plain-data field and
  durable shape, while construction retains an internal validated
  `ResourceRequest` so its property never reparses through built-ins and no
  validator callable is serialized;
- `RunRequest` carries supplied validator and sink registries as live explicit
  dependencies;
- existing `artifact_store_factory` remains the only artifact-store constructor
  and closes over the codec registry;
- `PipelineRunner` still receives an already-built executor; and
- worker/continuation setup reconstructs applicable registries before parsing
  and passes them to existing APIs.

Each composition root has a closed activation allowlist and rejects other or
listing-only groups before importing a target: validate accepts resource
validators; plan accepts executor registrations and resource validators;
preflight and run accept all four in-scope groups; direct stage workers accept
only codecs and validators; self-finalizing stage-job continuations additionally
accept event sinks. Generated commands receive only their applicable subset.

`EventSinkRegistry.register` remains compatible and accepts an optional
immutable exact-event subscription. Plugin values may remain callable
observe-all sinks or a small sink-registration value with a subscription.
Dispatch remains synchronous, ordered, post-append, and best-effort. No payload
predicate, mutable context, async guarantee, or fatal mode is introduced.

Slack and Discord remain direct downstream event sinks: the subscription is the
sole generic event filter, while project code owns message/severity projection,
the webhook client, and the secret. Stage 28 explicitly activates that sink in
the lifecycle-owning process, and credentials never enter activation metadata.
A mutable hook is different because it may replace, veto, retry, or otherwise
change an execution decision. Such hooks need separate ordering, failure,
provenance, resume, and process-ownership contracts and remain deferred. Phase
3 records both boundaries and provider recipes without a core notification API.

## Complexity Delta

Added for current consumers: richer existing diagnostics; opt-in conformance
reports; paired executor registration without a context wrapper; one direct-
callable validator plugin group; exact CLI activation and nested durable
evidence; targeted registry threading/worker verification; exact event
subscriptions.

Excluded: a universal registry/service locator, globals, live-object
serialization, automatic loading, generic arbitrary import references, a second
artifact constructor, unconsumed provider registries, scheduler/queue/authority
bootstrapping, mutable hooks, async delivery, cursors/outboxes, and service SDKs.

## Design Agreement

| ID | Requirements | Decision and authoritative owner | Status |
| --- | --- | --- | --- |
| DQ-1 | FR-1, FR-2 | Plugin diagnostics owns per-capability status/evidence and derives the legacy compatibility summary. | locked |
| DQ-2 | FR-3 | Test support depends on runtime contracts; runtime never imports it. | locked |
| DQ-3 | FR-4 | Executor registry solely pairs ordinary descriptors/factories; factories take existing services/options directly. | locked |
| DQ-4 | FR-5, FR-9, FR-10 | Group/name selects; resolved record identifies; plugin helpers validate. | locked |
| DQ-5 | FR-6 | Entry-point name plus existing registry owns validator registration; parsers/spec/runtime constructors own threading and internal typed retention without changing `StageSpec.resources`. | locked |
| DQ-6 | FR-7 | Existing artifact-store factory owns codec placement. | locked |
| DQ-7 | FR-8 | Closed command-specific allowlists ensure CLI/worker roots construct only locally consumed dependencies. | locked |
| DQ-8 | FR-11 | Event registry filters exact names after authoritative append; runner/store owns lifecycle. | locked |
| DQ-9 | FR-12 | Authority and unconsumed policies/providers do not become Stage 28 plugins. | locked |

## Expanded Design Review

Removal-first result after the single bounded correction: **pass**. EDR-1
through EDR-5 removed the redundant factory/validator wrappers, made readiness
evidence facet-specific, preserved the authored resource shape, and closed
activation allowlists per process. EDR-6 through EDR-8 confirmed the minimum
durable activation record, sink subscription, and conformance support. No
product decision was reopened and no maintainer choice was required.

| ID | Disposition | Requirements / decisions | Finding and smallest correction | Status |
| --- | --- | --- | --- | --- |
| EDR-1 | remove | FR-4, FR-8; DQ-3, DQ-7 | `ExecutorFactoryContext` owns no invariant: the registration already owns executor identity, while `RuntimeServices` and `RunOptions` already own the proposed fields. Remove the context and type the factory directly over the existing explicit inputs. Do not pass `executor_name` separately; validate the constructed executor name once against the registration descriptor before execution. | resolved: direct factory inputs |
| EDR-2 | remove | FR-5, FR-6; DQ-4, DQ-5 | `ResourceValidatorRegistration` duplicates the entry-point name and the existing registry's kind/validator pair. Make the exact entry-point name the sole kind identity, normalize the selected target directly to a `ResourceValidator`, and let `ResourceValidatorRegistry.with_validator` remain the sole duplicate/kind validator. A no-argument factory form is future-only unless needed to obtain that callable and should not create another registration value. | resolved: direct callable target |
| EDR-3 | simplify | FR-2; DQ-1 | A capability-to-status mapping plus one group-level `reason` cannot provide evidence for six independent capabilities. Keep the six fixed keys, but give each capability its own deterministic status and concise evidence in the existing readiness result; derive the legacy `status` compatibility summary from those facets rather than maintaining a second readiness judgment. | resolved: facet evidence and derived summary |
| EDR-4 | simplify | FR-6, FR-9; DQ-5 | `StageSpec.resources` is an existing public plain-data field and serialized config boundary. Preserve that shape. Retain the already validated `ResourceRequest` as construction-time/internal typed state (with no validator callable serialized), so `resource_request` does not silently reparse through built-ins. Do not replace the authored field or change its durable representation. | resolved: public shape preserved |
| EDR-5 | simplify | FR-1, FR-5, FR-8, FR-10; DQ-4, DQ-7 | Repeated `GROUP:NAME` syntax is suitably exact, but activation must be limited at each command/composition root to groups that process actually consumes. Reject an inapplicable or listing-only group before loading its target; pass only the applicable selected records to each worker or lifecycle owner. | resolved: closed per-command allowlists |
| EDR-6 | keep | FR-9, FR-10; DQ-4 | A versioned activation manifest is required by fresh-process comparison. Store it as one reserved typed entry in the existing prepared-run metadata, round-trip strict `PluginRecord` summaries, and keep only sorted identity fields. No second artifact, generic component-reference schema, object, credential, or plugin-private state is justified. | pass |
| EDR-7 | keep | FR-11; DQ-8 | Exact event subscription state has a current CLI/plugin consumer, and a small immutable sink-registration value is the minimum way for a selected plugin to carry it while callable sinks remain observe-all. Filtering stays in `EventSinkRegistry` after append; predicates, mutation, async delivery, fatal mode, and delivery state remain excluded. | pass |
| EDR-8 | keep | FR-3; DQ-2 | Opt-in `loom.testing` reports have a current downstream conformance consumer and preserve dependency direction because runtime/package roots never import them. Caller-provided behavioral samples prevent structural checks from claiming unsupported semantics; no discovery or test-runner dependency is needed. | pass |

Domain neutrality, composition, dependency direction, reproducibility, examples,
and phase traceability otherwise pass: downstream targets remain downstream;
subsystem registries stay instance-local; durable state contains identity only;
reconstruction compares before target/stage/codec/sink use; and the three causal
validation combinations map directly to the three proposed vertical phases.
The manager verified EDR-1 through EDR-5 in the minimum design, complexity
delta, and DQ-1/DQ-3/DQ-5/DQ-7. The review is closed without a second pass.

## Examples And Validation

| Example or invariant | Owner | Minimal coverage | Status |
| --- | --- | --- | --- |
| Default import safety | CLI/plugin setup | Subprocess import/help/list/status/default-run checks. | planned |
| Executor identity | Executor registry | Mismatches fail before execute; valid synthetic CLI executor succeeds. | planned |
| Codec/resource worker parity | Artifact factory/resource parser | Local and real subprocess non-built-in codec/kind; missing activation fails before target construction. | planned |
| Activation mismatch | Plugin reconstruction | Missing, duplicate, target mismatch, invalid registration; structured redacted errors. | planned |
| Filtered committed callback | Store/dispatcher/registry | `stage.completed` only, committed-state read, ordered continuation after one failure. | planned |
| Conformance report | `loom.testing` | Passing/failing deterministic serialized reports with no pytest/discovery side effect. | planned |
| Validation versus capability | Validator/executor descriptor | Custom kind accepted by schema but supported/unsupported/unknown per descriptor. | planned |

Combined coverage is limited to activation + codec/resource + real worker;
executor factory + descriptor + CLI preflight/run; and commit + filter + callback
failure. Other dimensions remain focused.

## Phase Shaping

| Phase | Vertical outcome | Scope and exclusions | Acceptance | Status |
| --- | --- | --- | --- | --- |
| 1. Truthful extension contracts | Users inspect exact readiness and run versioned conformance checks. | Diagnostics/docs/test support only; no runtime activation. | Facets match evidence; reports are deterministic and import-safe. | pending |
| 2. Reconstructable runtime extensions | CLI custom executor runs; codecs/validators survive all parent/worker parse boundaries. | Executor registry, activation, resource threading, artifact factory, worker verification; no scheduler/queue/authority/source/export/sweep plugin. | Synthetic CLI executor plus custom codec/resource local and subprocess proof; defaults unchanged. | pending |
| 3. Filtered lifecycle observers | Python/CLI selected sinks observe exact committed event types in lifecycle-owning processes. | Sink filters and activation propagation; no mutation, service adapter, severity policy, async delivery, cursor, or outbox. | `stage.completed` only, post-commit visibility, ordered failure proof, observe-all compatibility. | pending |

Three phases isolate non-mutating truth/test support, cross-process component
assembly, and callback behavior while each leaves a useful result.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Evidence/current outcome | Reachable seams and gaps support FR-1 through FR-12 and the four-component minimum. | pass |
| Proportionality/ownership | Existing registries/factories/metadata are reused; selection, validation, capability, artifacts, lifecycle, and filtering each have one owner. | pass |
| Validation/phases | Three causal combinations and three vertical phases are explicit. | pass |
| Expanded design review | EDR-1 through EDR-8 recorded; one bounded correction resolved EDR-1 through EDR-5 and the manager verified all findings in place. | pass |
| Manifest/phase consistency | The compact manifest links exactly three phase plans with matching slugs, branches, ownership, dependencies, shared contracts, and pending statuses. | pass |
| Independent plan review | One review found two contract-identifier/derivation blockers, one removable lookup, and two ownership/traceability concerns; one bounded correction fixed all findings. | pass |
| Cross-stage correction | Stage 26 notification values/helper were removed; Phase 3 now has one filter/registration path and direct provider sinks. | pass |
| Maintainer approval | The maintainer explicitly approved the stage and the removal-first Stage 26/28 split on 2026-08-20. | pass |

Gate result: planning, expanded design-safety review, implementation planning,
independent plan review, one bounded design correction, and one bounded plan
correction are complete. Phase 1 remains pending until Stage 27 remotely merges.

## Decisions And Deferrals

| Item | Decision/deferral | Revisit trigger |
| --- | --- | --- |
| Stages | Keep `factory._target_`; no stage plugin group. | A non-config discovery consumer appears. |
| Stores/authority | Keep factories and `RuntimeServices`; clarify readiness only. | A second safe deployment bootstrap consumer. |
| Events | Exact names only; observe-all default; no delivery state or core message/severity projection. | Two concrete providers need one stable shared projection, or accepted work requires richer filters/at-least-once delivery. |
| Sweeps | No discovery while custom spec/mode is undefined. | Accepted custom sweep-spec contract. |
| Run exchange | Document direct exporter/importer use; no registry. | Two name-based bootstrap consumers. |
| Sources | Contract-only. | A runtime path needs source selection. |
| Reliability | Classifier/evaluator/adapter remain contract-only. | Accepted automatic retry or other concrete consumer. |
| Reuse/queue | New reuse semantics are deferred; Stage 25 owns queue policy. | An accepted later design creates a second discovery need. |
| Provenance/preflight contributors | No generic contributor registries. | Two downstream contributors need one safe result boundary. |

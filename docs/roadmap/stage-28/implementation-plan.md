# Roadmap Stage 28 Implementation Plan: Reconstructable Runtime Extensions And Lifecycle Hooks

Status: ready; plan quality gate passed
Roadmap stage: `v28`
Planning document: `docs/roadmap/stage-28/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 in progress
Blockers: none; Stage 26's Phase 3 dependency is remotely merged

## Summary

- Goal: make selected downstream executors, codecs, resource validators, and
  event sinks honestly testable and usable through their applicable Python,
  CLI, and fresh-process paths without adding a universal extension framework.
- Approved behavior: planning `FR-1` through `FR-12` preserve inert defaults,
  report six readiness capabilities, publish conformance reports, pair ordinary
  executor descriptors/factories, select exact entry points, preserve custom
  resource/codec behavior across workers, reconstruct only local consumers,
  persist safe identity, fail closed, filter committed events, and leave
  unconsumed protocols honest.
- Fixed design: `DQ-1` through `DQ-9` and resolved `EDR-1` through `EDR-8`
  retain subsystem ownership, remove redundant contexts/registrations, preserve
  authored resource data, use closed process-specific activation allowlists,
  and keep hooks observe-only.
- Minimum useful change: a downstream package can validate and explicitly
  activate one ordinary executor, codec, validator, and filtered sink; local and
  subprocess paths use the applicable components while default runs discover
  nothing.
- Deliberately excluded: global registries/service locators, live-object
  serialization, automatic activation, custom submitted scheduling, authority
  plugins, source/export/sweep registries, unwired reliability policies,
  mutable hooks, async delivery, cursors/outboxes, and service adapters.
- Validation source: planning `Examples And Validation` limits combined tests
  to activation/worker parity, factory/descriptor/CLI, and commit/filter/failure.
- Out of scope: every planning deferral and Stage 25, 26, or 27 policy/authority
  decision.

## Planned Downstream Journey

The following snippets illustrate the planned public shapes. They are acceptance
examples for implementation, not claims about APIs available before the
corresponding phase merges.

First, project code checks its implementation with dependency-light contract
support. The report contains deterministic, versioned plain data and covers only
the cases supplied by the caller:

```python
from loom.testing import check_codec_contract

report = check_codec_contract(
    ProjectArrayCodec(),
    roundtrip_values=(small_array, empty_array),
)
report.raise_for_errors()
```

An ordinary executor is registered as one descriptor/factory pair so its
capability claims and constructed behavior cannot drift independently:

```python
registration = ExecutorRegistration(
    descriptor=project_executor_descriptor,
    factory=lambda *, services, options: ProjectExecutor(
        services=services,
        options=options,
    ),
)
```

The downstream package exposes exact entry points using the registry owned by
each subsystem:

```toml
[project.entry-points."loom.executors"]
project-executor = "my_project.executors:registration"

[project.entry-points."loom.codecs"]
array-npy-v1 = "my_project.codecs:numpy_codec"

[project.entry-points."loom.resource_validators"]
"accelerator.tpu" = "my_project.resources:validate_tpu"

[project.entry-points."loom.event_sinks"]
project-audit = "my_project.audit:audit_sink"
```

Relevant commands activate only the explicitly named records. Repeated options
compose the caller-owned registries without mutating a process-global default:

```text
loom run \
  --plugin loom.executors:project-executor \
  --plugin loom.codecs:array-npy-v1 \
  --plugin loom.resource_validators:accelerator.tpu \
  --plugin loom.event_sinks:project-audit \
  ...
```

The parent records only versioned identity under `plugin_activations`; no
callable, registry, credential, constructor arguments, or plugin-private state
is durable. A fresh process receives its applicable current selectors,
rediscovers them, and compares group/name/target plus available distribution
evidence before it constructs project runtime behavior. Stored metadata alone
never authorizes loading.

Finally, an event sink may observe an exact set of committed event names while
existing unfiltered sinks retain observe-all behavior:

```python
registry.register(
    "project-audit",
    ProjectAuditSink(),
    subscription=EventSinkSubscription(
        event_types=("stage.completed", "run.failed"),
    ),
)
```

The callback remains synchronous and best-effort. Its return value is ignored;
failure is recorded without changing the run or preventing later matching
sinks. This is an observer, not a mutable execution hook.

## Shared Constraints

- Architecture and dependency direction:
  - owning subsystem registries remain authoritative; only CLI/application
    composition roots call plugin discovery and pass targeted dependencies;
  - `loom.pipeline.runtime` remains import-light and does not discover plugins;
  - `loom.testing` may depend on public runtime contracts, but runtime and
    package roots never import it; and
  - CLI owns parsing/presentation, not registry validation, capability policy,
    artifact construction, or event semantics.
- Shared public and durable contracts:
  - readiness uses exactly `contract`, `python_injection`, `registry`,
    `plugin_loading`, `cli_selection`, and
    `fresh_process_reconstruction`; each maps to plain `status` and `evidence`;
    the existing group fields remain. Legacy `status` is `registry-ready` only
    when both `registry` and `plugin_loading` are supported and is
    `listing-only` for every other facet combination;
  - `ContractFinding` contains `code`, `status` (`pass` or `fail`), and
    `message`; `ContractReport` contains `contract`, positive
    `contract_version`, deterministic findings, `ok`, `to_dict()`, and
    `raise_for_errors()`. Phase 1 fixes the v1 identifiers/code catalogs for
    `loom.codec`, `loom.resource_validator`, `loom.executor`, and
    `loom.event_sink`; semantic catalog changes require the affected contract
    version to change;
  - an `ExecutorFactory` is called with explicit keyword-only
    `services: RuntimeServices` and `options: RunOptions`; an
    `ExecutorRegistration` contains only `descriptor` and `factory`;
    `ExecutorRegistry` registers/resolves/builds by descriptor name, rejects
    duplicates, exposes a descriptor-registry projection, and validates the
    built executor name once;
  - `loom.resource_validators` targets are direct `ResourceValidator`
    callables, keyed solely by entry-point name and registered through existing
    `ResourceValidatorRegistry.with_validator`;
  - repeated `--plugin GROUP:NAME` selects exactly one metadata record. A
    `PluginActivationManifest` schema-version 1 contains a sorted tuple of
    strict `PluginRecord` summaries and is nested under the reserved
    `plugin_activations` prepared-run/worker metadata key;
  - `plugin_activations` is reserved: caller-supplied `RunRequest.metadata`
    collisions are rejected, never merged or replaced. Only the composition
    root may attach a manifest produced from the current explicit selection;
    execution treats it as propagation evidence, and a worker loads only the
    explicit applicable selectors in its generated current command before
    comparing that evidence;
  - exact group/name/target must match on reconstruction. When both sides expose
    distribution name/version, they must also match; unavailable distribution
    evidence produces a bounded diagnostic rather than invented identity;
  - `EventSinkSubscription` contains a non-empty, unique, deterministic tuple
    of exact event types. `None` means observe all. `EventSinkRegistration`
    contains a sink plus optional subscription, and existing plain callable
    registration remains compatible.
- Activation applicability:
  - validate: resource validators;
  - plan: executor registrations and resource validators;
  - preflight/run: ordinary executors, codecs, resource validators, and sinks;
  - direct stage worker: codecs and resource validators; and
  - self-finalizing stage job: codecs, validators, and sinks.
  Inapplicable/listing-only groups fail before target import; generated commands
  receive only their applicable subset.
- Reproducibility, compatibility, and trust:
  - explicitly activated installed targets are trusted project code; discovery
    and stored metadata alone are inert;
  - a downstream Slack, Discord, or similar integration keeps its webhook
    credential, network client, message projection, and severity choices in
    project/plugin construction and remains only an observe-only event sink;
  - `StageSpec.resources` and all existing durable config/artifact/event shapes
    remain unchanged; no callable or secret is persisted;
  - `PipelineRunner(executor=...)`, unfiltered sink registration, default
    registries, and built-in CLI names remain compatible; and
  - dispatch owners build executors, artifact/config consumers build
    codecs/validators, and lifecycle commit owners build sinks.
- Shared invariant ownership:
  - plugin helpers own selection, target normalization, activation records, and
    reconstruction comparison;
  - executor registry owns descriptor/factory/name pairing;
  - resource registry/parser owns kind validation, while executor descriptors
    own capability admission;
  - artifact-store factories own codec placement;
  - runner/store owns lifecycle commit; event registry owns filtering and
    best-effort callback order; and
  - conformance checks own only bounded downstream test evidence.
- Decisions no phase may reopen: no universal registry/context wrapper,
  validator registration wrapper, automatic loading, changed authored resource
  shape, mutable hook or general hook bus, worker reconstruction of its dispatch
  executor, or declarative registry for a protocol without a current consumer.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `truthful-extension-contracts` | in_progress | `docs/roadmap/stage-28/phases/truthful-extension-contracts.md` | `agent/stage-28-p1-truthful-extension-contracts` | pending | Plugin readiness, public conformance support, architecture/docs | Let users determine and test exactly what each in-scope extension contract currently supports. |
| 2 | `reconstructable-runtime-extensions` | pending | `docs/roadmap/stage-28/phases/reconstructable-runtime-extensions.md` | `agent/stage-28-p2-reconstructable-runtime-extensions` | pending | Executor registry, explicit activation, resource/codec threading, worker verification | Execute a custom CLI executor and preserve custom codec/resource behavior through a real fresh worker. |
| 3 | `filtered-lifecycle-observers` | pending | `docs/roadmap/stage-28/phases/filtered-lifecycle-observers.md` | `agent/stage-28-p3-filtered-lifecycle-observers` | pending | Event subscriptions, sink activation, lifecycle-owner propagation and proof | Select an observe-only sink that receives exact committed lifecycle events without affecting correctness. |

Phase 1 is independently useful and non-mutating. Phase 2 supplies the shared
activation/reconstruction path. Phase 3 reuses it for callbacks and does not
expand delivery semantics.

## Quality Gate

- Planning gate: functionality/minimum-design agreements passed; one expanded
  design review and one bounded correction resolved `EDR-1` through `EDR-8`.
- Manager review: manifest and all three linked phase plans are traceable,
  consistent, vertically useful, and preserve the reviewed ownership/import
  boundaries.
- Optional independent review: one expanded pass completed. It found missing
  initial conformance identifiers, an incomplete legacy-readiness derivation,
  one redundant executor lookup, reserved-metadata ownership ambiguity, and one
  Phase 3 traceability omission.
- Correction: one bounded correction fixed the four v1 contract catalogs and
  ordering, total `registry-ready`/`listing-only` derivation, sole `resolve`
  lookup, collision rejection/inert stored metadata, and Phase 3 FR/DQ/EDR plus
  sink-v2 traceability. The later maintainer-approved cross-stage correction
  removed Stage 26 notification types and made Phase 3's subscription the sole
  generic provider filter. Manager verification found no remaining blocker.
- Ready for implementation: yes. The maintainer removed the non-technical Stage
  27 sequencing gate on 2026-08-21. Stage 26's lifecycle-event dependency is
  limited to Phase 3 and is satisfied on current `origin/develop`.
- Accepted risks: explicit plugin packages may be absent from worker
  environments; distribution metadata may be unavailable; public conformance
  checks prove only supplied cases; synchronous sinks can add latency; custom
  ordinary executors cannot claim submitted-continuation support.
- Revisit triggers: an accepted remote/submitted custom executor; two source or
  provider selection consumers; required configured plugin state; measured sink
  latency/delivery requirements; or at least two concrete provider sinks needing
  one stable shared message projection.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |

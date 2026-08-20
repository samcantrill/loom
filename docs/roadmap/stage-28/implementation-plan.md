# Roadmap Stage 28 Implementation Plan: Reconstructable Runtime Extensions And Lifecycle Hooks

Status: ready; plan quality gate passed
Roadmap stage: `v28`
Planning document: `docs/roadmap/stage-28/planning.md`
Artifact layout: `manifest-and-phase-plans-v1`
Target branch: `develop`
Current phase: Phase 1 pending
Blockers: Stage 27 must remotely merge before Phase 1 starts; no planning blocker

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
  shape, mutable hook, worker reconstruction of its dispatch executor, or
  declarative registry for a protocol without a current consumer.

## Phase Index

| Phase | Slug | Status | Phase plan | Branch | PR | Ownership | Goal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `truthful-extension-contracts` | pending | `docs/roadmap/stage-28/phases/truthful-extension-contracts.md` | `agent/stage-28-p1-truthful-extension-contracts` | pending | Plugin readiness, public conformance support, architecture/docs | Let users determine and test exactly what each in-scope extension contract currently supports. |
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
  sink-v2 traceability. Manager verification found no remaining blocker.
- Ready for implementation: yes; Phase 1 remains execution-blocked until Stage
  27 remotely merges.
- Accepted risks: explicit plugin packages may be absent from worker
  environments; distribution metadata may be unavailable; public conformance
  checks prove only supplied cases; synchronous sinks can add latency; custom
  ordinary executors cannot claim submitted-continuation support.
- Revisit triggers: an accepted remote/submitted custom executor; two source or
  provider selection consumers; required configured plugin state; measured sink
  latency/delivery requirements; or Stage 26 accepting richer notification
  policy.

## Completion

| Phase | PR and merge | Implementation and validation | Residual risk | Cleanup |
| --- | --- | --- | --- | --- |
| 1 | pending | pending | pending | pending |
| 2 | pending | pending | pending | pending |
| 3 | pending | pending | pending | pending |

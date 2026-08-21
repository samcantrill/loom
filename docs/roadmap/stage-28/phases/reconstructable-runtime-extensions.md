# Phase 2 Execution Plan: Reconstructable Runtime Extensions

## Metadata

- Status: blocked
- Roadmap stage and phase: v28 Phase 2
- Manifest: `docs/roadmap/stage-28/implementation-plan.md`
- Branch: `agent/stage-28-p2-reconstructable-runtime-extensions`
- Worktree root and path: `../loom-worktrees` /
  `stage-28-p2-reconstructable-runtime-extensions`
- Base revision: `d4115c2` (`origin/develop` after Phase 1 merge metadata)
- PR target: `develop`
- PR title: `Stage 28 phase 2: reconstruct selected runtime extensions`
- Dependencies: Phase 1 merged; planning `FR-1`, `FR-2`, and `FR-4` through
  `FR-10`; `DQ-3` through `DQ-7`; `EDR-1` through `EDR-6`
- Workflow path: expanded because one nested durable activation schema and
  fresh-worker trust boundary causally interact; use at most one phase-planner
  refinement if the current source still leaves that risk unresolved
- Blockers: expanded review found two accepted-contract failures after the 3/3
  correction budget was consumed: resume does not compare current selections to
  durable activation evidence before import, and Phase 2 accepts deferred event
  sinks into run/continuation activation paths

## Objective And Context

- Vertical outcome: a project selects a conforming ordinary executor from the
  CLI, and its selected custom codec/resource validator works identically in
  parent and real subprocess worker processes.
- Earlier dependency: Phase 1's readiness/report vocabulary and current direct
  injection, descriptor, codec loader, resource registry, artifact factory, and
  stage-worker paths.
- Later work explicitly out of scope: event sink CLI activation/filtering,
  submitted custom executors, service notifications, source/export/sweep
  discovery, queue/authority plugins, and reliability policy wiring.

Plain-language result: a component that works in the CLI parent will not
silently disappear when Loom crosses a serialization or process boundary. The
dispatch owner builds the selected executor, while artifact/config consumers
rebuild only codecs and validators. Exact recorded identity proves what was
selected; the current explicit command remains the authority to load it.

## Current Source And Harness

- Relevant files/symbols:
  - `pipeline/executors/base.py` and `cli/run.py::_build_executor`;
  - `pipeline/runtime/capabilities.py` descriptor registry/validation;
  - `plugins/entrypoints.py`, `codecs.py`, `diagnostics.py`, and public exports;
  - `pipeline/resources.py`, `specs.py`, runtime option/metadata parsers, and
    pipeline validation;
  - `pipeline/stores/local_artifacts.py` and execution artifact-store factory
    call sites;
  - `execution/models.py`, `runner.py`, `stage_worker.py`, `continuation.py`,
    `prepared_run.py`, and `services.py`; and
  - subprocess/container/SLURM worker command builders plus validate, plan,
    preflight, run, stage, and stage-job CLI composition roots.
- Existing tests/seams: plugin adapter/future-group contracts, executor
  capability contracts, runtime resource tests, CLI command unit tests,
  stage-worker/continuation contracts, real subprocess integration, container/
  SLURM command tests, and import-boundary tests.
- Constraints: plugin discovery stays above subsystem registries; runtime models
  do not import plugin loaders; existing artifact-store factory remains sole
  construction owner; metadata is plain/redacted; worker commands cannot expose
  authority credentials beyond existing guarded args.

## Scope

In scope:

- instance-local ordinary `ExecutorRegistry`, direct factory signature,
  descriptor projection, built-in registrations, and executor plugin loader;
- `loom.resource_validators` known group and direct-callable loader;
- strict `PluginRecord` readback, schema-v1 activation manifest, exact selector
  parser/resolver, comparison diagnostics, and plugin provenance/readiness;
- repeated `--plugin` support at the fixed command allowlists;
- validator registry threading through pipeline/runtime parsing, validation,
  planning, preflight, execution, worker, and continuation paths while
  preserving `StageSpec.resources`;
- codec registry placement through existing artifact-store factories;
- applicable activation propagation in prepared run/request metadata and
  worker/continuation commands; and
- local/subprocess end-to-end examples/tests plus fake command coverage for
  other fresh-process builders.

Out of scope:

- a global/default mutable registry, universal extension object, new config
  target language, arbitrary stored plugin configuration, auto-loading from an
  imported/old run, package installation/version solving, or plugin isolation;
- rebuilding the dispatch executor inside a stage worker;
- changing artifact refs/codecs, resource request serialization, executor
  protocol, status/failure lifecycle, authority/store ownership, or SLURM
  continuation semantics; and
- custom executor use in managed queues or remote submitted continuation.

Assumptions:

- an activated target is trusted installed project code;
- custom plugin code is installed in every process where it is applicable;
- a selected ordinary executor follows the existing one-stage request/result
  contract and does not require a new continuation protocol; and
- missing distribution metadata cannot prove identity, so exact group/name/
  target remains mandatory and the absence is reported.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - without `--plugin`, no discovery occurs and built-in behavior is byte-for-
    byte compatible where serialized outputs are unchanged;
  - a selector has exact `GROUP:NAME` syntax, names one in-scope group for that
    command, and resolves exactly one metadata record before import;
  - invalid/inapplicable/listing-only/missing/duplicate/mismatched targets fail
    before downstream stage target construction;
  - capability validation uses the selected executor registration's descriptor;
  - validator acceptance never implies executor support; and
  - a direct worker sees only codec/validator activation records, never executor
    or sink records.
- Public shapes:
  - `ExecutorFactory` protocol called as
    `factory(services=services, options=options) -> Executor`;
  - frozen `ExecutorRegistration(descriptor, factory)`;
  - instance-local `ExecutorRegistry.register`, `resolve`, `build`, `names`,
    and read-only `descriptor_registry` projection; `resolve` is the sole public
    lookup and raises the typed registry error for an unknown name;
  - `LOOM_RESOURCE_VALIDATORS_GROUP = "loom.resource_validators"` and
    `load_resource_validator_entry_points(...)` following existing selected/
    strict/result behavior;
  - `load_executor_entry_points(...)` accepting a registration instance or
    no-argument factory returning one, with entry-point/descriptor name match;
  - `PluginRecord.from_summary(...)`; and
  - frozen `PluginActivationManifest(schema_version=1, plugins=...)` with strict
    `to_dict()/from_dict()` and deterministic unique group/name records.
- Durable shape: `metadata["plugin_activations"]` is exactly the activation
  manifest dictionary. Prepared-run metadata may contain the full run set;
  each `StageWorkerRequest` contains only its applicable subset. Existing
  metadata/document schema versions remain otherwise unchanged.
- Reserved-key ownership: caller-provided `RunRequest.metadata` containing
  `plugin_activations` is rejected before execution and is never merged or
  overwritten. The authorized composition root alone attaches a manifest built
  from current explicit selectors. Execution propagates but does not activate
  from that value; generated worker commands carry the applicable current
  selectors, and the worker imports those targets only before comparing them to
  the recorded subset. Stored/caller metadata by itself is never activation
  authority.
- Comparison: group/name/target always match. If current and recorded package or
  version are both non-null they match; absent evidence is a stable warning,
  not a fabricated value. Raw import exceptions are chained internally but CLI/
  worker messages remain bounded and redacted.
- Resource compatibility: `StageSpec.resources` stays plain data; an internal
  non-comparing typed request is set during construction and returned by
  `resource_request`. Every `from_dict`/parse facade accepts an optional registry
  where the selected path needs it; existing callers default to built-ins.
- Cross-phase: Phase 3 may activate existing sink plugins using the manifest but
  cannot change its schema or broaden worker applicability.
- Private discretion: registry mutability internals, activation helper module
  split, how built-in factories are lazily assembled, command-option helper
  placement, internal typed-request field name, and transport of already-
  validated manifests between CLI helpers.

## Proportionality

- Existing seams reused: `PluginRecord`/generic loader, descriptor registry,
  resource registry, `RunRequest.metadata`, prepared/worker metadata, artifact-
  store factories, executor injection, and current worker commands.
- Material additions/current justification: paired factories close the actual
  CLI gap; activation identity is required for worker parity; registry threading
  fixes a demonstrated custom-kind failure.
- Deferred hardening: configurable plugin constructors, semantic package locks,
  cryptographic plugin identity, hot reload, worker installation, remote
  distribution, new durable sidecars, and cross-host acceptance.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Descriptor/factory/result name match | Executor registry | Plugin registration/factory | Wrong preflight claims or audit identity | duplicate and three mismatch cases before execute |
| Selector is exact/applicable before import | CLI/plugin resolver | User selector or installed metadata | Unexpected trusted code execution | per-command negative matrix with import sentinel |
| Activation identity round-trips | Plugin manifest | prepared metadata/process boundary | Worker runs different component | schema/readback/order and mismatch tests |
| Reserved activation metadata has one writer | CLI/application composition root | caller `RunRequest.metadata` collision or imported run evidence | stored data causes code loading or hides current selection | collision rejection and inert-metadata tests |
| Authored resource shape is stable | Stage spec/resource parser | custom registry construction | config/fingerprint compatibility break | exact resources serialization/equality regression |
| Custom validation survives reparse | Resource parser/spec/runtime call sites | default-registry fallback | parent validates, worker fails late | validate/plan/preflight/run/worker/continuation matrix |
| Validation does not grant capability | Executor descriptor validation | custom resource callable | unsupported scheduling request accepted | supported/unsupported/unknown descriptor cases |
| Codec registry reaches artifact consumer | Artifact-store factory | parent/worker construction | unknown codec or wrong payload | non-built-in roundtrip local and subprocess |
| Worker receives only applicable targets | process composition roots | full parent activation set | recursive executor or duplicate sink | exact generated args/request metadata assertions |

## Implementation Slices

1. Add executor registry/factories and executor/validator plugin adapters with
   focused public, duplicate, normalization, and import tests.
2. Add strict activation selection/manifest/comparison, safe diagnostics, and
   command-specific option allowlists without yet changing execution.
3. Thread the validator registry through specs/runtime/validation/planning/
   preflight and retain the internal typed request with unchanged authored data.
4. Assemble selected executor/codec/validator dependencies in CLI run paths;
   project descriptors into capability checks and close codec registry over the
   existing artifact-store factory.
5. Propagate applicable manifest subsets through prepared requests and worker/
   continuation command builders; reconstruct and compare before project code.
6. Add synthetic plugin fixtures, local/subprocess E2E proof, fake container/
   SLURM command assertions, docs/readiness updates, and full validation.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Public imports and inert defaults | new exports intentional; root/help/default commands import no target |
| Unit | required | registries, parsing, manifest, allowlists, builders | duplicates/mismatches, exact shapes, applicable subsets, default compatibility |
| Contract | required | plugin/executor/resource/worker contracts | selected/strict loader results, name pairing, schema readback, worker failure codes |
| Integration | required | cross-component parent/worker parity | custom kind/codec through config, capability, artifact store, continuation, subprocess |
| E2E / opt-in | required local; remote deferred | user-visible CLI custom executor and subprocess | synthetic installed/fake entry points; no real scheduler/container required |

Targeted commands:

    .venv/bin/pytest -q tests/contracts/test_plugin_future_groups_contract.py tests/contracts/test_executor_capabilities_contract.py tests/contracts/test_stage_worker_contract.py tests/contracts/test_codec_contract.py
    .venv/bin/pytest -q tests/unit/loom/plugins tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/unit/loom/pipeline/execution/test_stage_worker.py
    .venv/bin/pytest -q tests/unit/loom/cli/test_validate.py tests/unit/loom/cli/test_plan.py tests/unit/loom/cli/test_preflight.py tests/unit/loom/cli/test_run.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/pipeline/test_stage_job_continuation.py tests/e2e/test_cli_runs_e2e.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: plugin/runtime import cycle, hidden default-registry reparse,
  activation evidence leaking code/config, worker identity mismatch after stage
  import, or treating custom validation as capability support.
- Review focus: `EDR-1` through `EDR-6`, metadata subsets, every reparse call
  site, executor name validation, and unchanged no-activation behavior.
- Stop if: supporting a custom executor requires new submitted-operation/
  authority semantics; activation needs arbitrary serialized constructor state;
  `StageSpec.resources` must change; or a worker must auto-load from untrusted
  stored evidence without prepared current-command authorization.
- Accepted debt/revisit: version evidence is packaging metadata, not a content
  hash; real cross-host/container availability remains environment-owned.

## Executor Handoff

- Read: this plan plus planning `FR-1`, `FR-2`, `FR-4` through `FR-10`,
  `DQ-3` through `DQ-7`, and `EDR-1` through `EDR-6`.
- Safe slices: the six numbered vertical slices; do not begin worker propagation
  before manifest/resource tests pass.
- Do not revisit: direct factory inputs, direct validator callable, unchanged
  resource shape, exact selectors, process allowlists, nested manifest, or no
  worker-side dispatch executor.
- Manager action required for: any new durable document/schema, custom submitted
  executor need, arbitrary plugin configuration, or inability to fail before
  project import.

## Workflow State

- Manager preparation: complete; branch, worktree, base, predecessor merge,
  target, title, ownership, source seams, and targeted tests verified
- Expanded planning: not needed; the reviewed activation-manifest and worker
  trust boundary remains decision-complete on the current base
- Implementation: complete at `71aca78` after executor work plus three bounded
  manager corrections for missing composition-root wiring, an isolated-harness
  test-module collision, and import/readiness/preflight compatibility
- Refiner: not used; all concrete findings had direct manager-local fixes
- Pre-submit gate: passed after the clean rebase onto `origin/develop` at
  `e7506b5`; `make validate-pr` completed Ruff, Pyright, 2,260 default tests
  with 1 hardware skip, 135 config-extra tests with 3 skips, and package build; `make test-summary`
  wrote a fully passing six-tier receipt
- Independent review: completed on PR #228 with two product blockers: resume
  identity comparison occurs too late or not at all, and Phase 2 event-sink
  activation violates the deferred lifecycle-owner/worker-subset boundary
- Blocker corrections: 3/3
- PR and merge: PR #228 is open and CI passed; merge is prohibited while the
  review blockers remain

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `c2cfa12` introduced the registries, adapters, activation evidence, and first worker wiring. `e60e309` completed validator threading across config/runtime/preflight/continuation roots, built-in factory composition, worker-only activation subsets, authored-resource preservation, and a real custom executor/codec/validator subprocess path. `af44469` removed an isolated pytest module-name collision. `71aca78` restored lazy imports and no-plugin compatibility while making readiness diagnostics match the executable groups. Changes stay within CLI composition, plugin adapters/diagnostics, runtime parsing/capabilities, execution reconstruction, executor command builders, tests, and the accepted docs. |
| Tests added or updated | Added strict manifest/selector, executor registry/loader, direct validator, resource reparse, worker command, and synthetic installed-entry-point fixtures. The real CLI E2E selects a project subprocess executor plus non-built-in codec/resource kind, asserts independent parent/child validator PIDs, loads the custom payload, and verifies the exact worker activation subset. Phase-targeted acceptance: 189 passed. Gate-failure compatibility cluster: 153 passed. |
| Validated revision/tree state and evidence | Clean rebased source/test tree at `7dd69f8` plus evidence-only roadmap commits. `make validate-pr` passed Ruff, Pyright, default 2,260 passed / 1 skipped / 115 deselected, config-extra 135 passed / 3 skipped / 2,264 deselected, and package build. `make test-summary` wrote `build/test-summary.md`: package 116, unit 1,594, contract 285, integration 209, E2E 56, and config-extra 135 passed with no failures or errors. |
| Validation-relevant changes after evidence | none; only this phase execution-plan evidence is updated after the successful receipts. |
| PR, review, and merge | PR [#228](https://github.com/samcantrill/loom/pull/228) is ready, targets `develop`, is mergeable, and passed CI. Expanded review found two blockers, so it remains open and unmerged. |
| Residual risk and cleanup | Blocked at 3/3 corrections. Smallest fixes are to compare every resume selection, including empty selection, with recorded activation metadata before importing targets; and to remove event sinks from Phase 2 run/continuation allowlists and worker projections. Cross-host installation and package-evidence limitations remain accepted. |

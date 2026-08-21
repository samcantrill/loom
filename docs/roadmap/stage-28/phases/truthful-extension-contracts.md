# Phase 1 Execution Plan: Truthful Extension Contracts

## Metadata

- Status: in_progress
- Roadmap stage and phase: v28 Phase 1
- Manifest: `docs/roadmap/stage-28/implementation-plan.md`
- Branch: `agent/stage-28-p1-truthful-extension-contracts`
- Worktree root and path: `../loom-worktrees` /
  `stage-28-p1-truthful-extension-contracts`
- Base revision: `e3968f7` (`origin/develop`)
- PR target: `develop`
- PR title: `Stage 28 phase 1: publish truthful extension contracts`
- Dependencies: planning `FR-1` through `FR-3`, `FR-12`, `DQ-1`, `DQ-2`, and
  `EDR-3`/`EDR-8`; no cross-stage runtime dependency
- Workflow path: fast; the expanded stage design review already fixed the only
  public report/readiness decisions
- Blockers: none

## Objective And Context

- Vertical outcome: a downstream developer can inspect what each extension
  group actually supports and run stable behavior checks against each extension
  type Stage 28 will make executable.
- Earlier dependency: current plugin diagnostics, protocol/contract tests, and
  import-boundary behavior.
- Later work explicitly out of scope: runtime activation, executor factories,
  resource/codec worker wiring, and sink filtering.

Plain-language result: a maintainer can answer “does this extension merely have
a Python interface, or can Loom also register, load, select, and reconstruct
it?” without reading implementation code. A downstream package can then run a
small public check over its own representative values instead of copying Loom's
internal tests. This phase changes claims and test support only; it does not
make any new runtime path executable.

## Current Source And Harness

- Relevant files and symbols:
  - `src/loom/plugins/diagnostics.py`: `PluginGroupReadiness`, readiness maps,
    `PluginDiagnosticResult`, and check/summarize helpers;
  - `src/loom/cli/plugins.py`: v1 list/check envelopes and text formatting;
  - `src/loom/plugins/__init__.py`: cheap public diagnostic exports;
  - `src/loom/io/codecs/base.py`, `pipeline/resources.py`,
    `pipeline/executors/base.py`, and `pipeline/event_sinks.py`: checked
    contracts; and
  - `docs/features/plugins.md`, `protocols.md`, `testing.md`, `execution.md`,
    `runtime-resources.md`, and `reliability.md`: current claims.
- Existing tests and seams: `tests/package/test_plugins_api.py`, plugin CLI
  tests, `tests/contracts/test_codec_contract.py`, executor/resource capability
  tests, event-sink tests, and package import-boundary tests.
- Import/dependency constraints: `loom.testing` is opt-in and absent from root
  re-exports; it uses no `pytest`, plugin discovery, CLI, config composition, or
  optional runtime dependency.

## Scope

In scope:

- enrich existing plugin-group readiness with the six fixed facets and
  facet-local evidence while deriving the existing group status;
- expose the richer details in text and JSON plugin diagnostics with explicit
  schema-version handling;
- add `src/loom/testing/` as a typed, dependency-light downstream test-support
  package;
- implement the four public check entrypoints and shared report/finding values;
- update canonical docs with the full current extension matrix, including
  unsupported/not-applicable paths and deferral triggers; and
- update source-tree ownership/import documentation.

Out of scope:

- changing any runtime selection or execution behavior;
- loading a listing-only group to make its readiness test pass;
- auto-discovery, fixtures tied to a downstream domain, a pytest plugin, test
  command runner, coverage service, or generalized validation framework; and
- claiming that supplied cases prove backend reachability, performance,
  credentials, concurrency, or remote behavior.

Assumptions:

- the v1 plugin CLI payload is externally observable; additions use a v2
  envelope while retaining the existing record/group fields;
- check functions may execute supplied user objects and are therefore documented
  as test-only trusted code; and
- Phase 2 and 3 update facet evidence as executable paths land.

## Fixed Contracts And Private Discretion

- Observable behavior:
  - each known group always has all six readiness facets in fixed order;
  - group `status` is `registry-ready` if and only if both the `registry` and
    `plugin_loading` facets are `supported`; every other combination, including
    either facet being `unsupported`/`not_applicable` and all facets being
    `not_applicable`, derives `listing-only`. The other four facets never change
    this compatibility summary;
  - text output names unsupported/not-applicable paths without importing
    targets; and
  - reports contain a finding for every check performed, in stable code order.
- Public shapes:
  - `ContractFinding(code: str, status: Literal["pass", "fail"], message: str)`;
  - `ContractReport(contract: str, contract_version: int, findings: tuple[...])`
    with `ok`, `to_dict()`, and `raise_for_errors()`;
  - `check_codec_contract(codec, *, roundtrip_values, metadata_cases=())`;
  - `check_resource_validator_contract(kind, validator, *, valid_entries,
    invalid_entries)`;
  - `check_executor_contract(executor, *, requests)`; and
  - `check_event_sink_contract(sink, *, events, context_factory)`.
  All return `ContractReport`; iterable inputs are normalized once to immutable
  tuples. Exact private finding messages may improve, but public finding codes
  and contract versions change only with contract semantics.
- Initial contract identifiers and required finding order:

  | Checker | `contract` | Version | Required finding codes in order |
  | --- | --- | --- | --- |
  | Codec | `loom.codec` | 1 | `codec.protocol`, `codec.key`, then for each caller roundtrip/metadata case in caller order: `codec.encode`, `codec.decode`, `codec.roundtrip` |
  | Resource validator | `loom.resource_validator` | 1 | `resource_validator.kind`, `resource_validator.callable`, `resource_validator.registration`, then `resource_validator.accepts_valid` for each valid entry and `resource_validator.rejects_invalid` for each invalid entry, preserving each caller order |
  | Executor | `loom.executor` | 1 | `executor.protocol`, `executor.name`, then for each request in caller order: `executor.execute`, `executor.result_type`, `executor.result_identity` |
  | Event sink | `loom.event_sink` | 1 | `event_sink.callable`, then `event_sink.invoke` for each event in caller order |

  Repeated case codes are allowed and retain caller order. If a prerequisite
  fails, every requested dependent check still produces its fixed code as a
  `fail` finding without invoking unsafe downstream behavior. Phase 3 bumps
  only `loom.event_sink` to version 2 when subscription semantics are added;
  other names, versions, and catalogs remain unchanged. A later semantic code
  addition/removal/reorder requires that contract's version bump.
- Trust/failure boundaries: checkers catch supplied-object exceptions into
  findings unless interpreter/process termination escapes normally; they do not
  discover, instantiate, isolate, retry, or time out user code.
- Cross-phase contracts: Phase 2/3 reuse report values and update readiness
  evidence; they must not change Phase 1 report schema.
- Reproducibility/compatibility: `to_dict()` is plain data with deterministic
  finding order; no persisted runtime artifact is added; existing plugin fields
  and Python readiness access remain.
- Private discretion: file split inside `loom.testing`, normalization helpers,
  exception-message wording, and whether the v1 CLI formatter delegates to a
  shared v2 formatter.

## Proportionality

- Existing seam reused: current readiness values, CLI diagnostics, public
  protocols, and internal contract-test cases.
- Material additions/current justification: facet evidence prevents false
  support claims; installed test support lets downstream packages validate
  implementations without copying repository tests.
- Deferred hardening: randomized/property tests, environment probes, remote
  executor/store suites, pytest integration, plugin compatibility solvers, and
  a registry of arbitrary contracts.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Readiness matches executable behavior | Plugin diagnostics | Maintainer changes loader/CLI/worker support but leaves stale facets | Users activate an unsupported path | Exact expected facet/evidence tests per known group |
| Legacy status has one source | Readiness derivation | Manually maintained summary diverges from facets | Conflicting API/CLI claims | Construction/serialization tests prohibit independent value |
| Reports do not overclaim | Individual checker | Shallow protocol match or omitted supplied case | False downstream confidence | Passing/failing behavioral cases and documented limits |
| Test support stays out of runtime imports | Package roots/import tests | Accidental re-export/import | Added cost/cycle or pytest-like dependency | Clean-interpreter module graph assertions |
| Report output is deterministic/plain | `ContractReport` | Unordered input or raw exception/object detail | Unstable CI evidence | order and plain-data serialization tests |

## Implementation Slices

1. Add facet-local status/evidence and derived legacy status to plugin
   diagnostics; update list/check formatting and compatibility tests.
2. Add report/finding foundations under opt-in `loom.testing` with cheap import
   tests.
3. Add four bounded checkers by adapting existing contract behaviors and using
   caller-provided cases.
4. Update plugin/protocol/testing/structure docs with the authoritative matrix,
   usage snippets, applicability, and deferrals.
5. Run targeted and full validation; reconcile readiness values only with code
   that exists at this phase revision.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | Cheap imports and public surface | Root/runtime imports omit `loom.testing`; direct import has no pytest/discovery side effect. |
| Unit | required | Facet/status/report validation | Fixed keys/statuses/evidence, derived summary, deterministic report and errors. |
| Contract | required | Checker meaning | Pass/fail codec, validator, executor, and sink cases with stable codes. |
| Integration | required | CLI diagnostic compatibility | Text and v2 JSON reflect facet evidence without loading listing-only targets. |
| E2E / opt-in | deferred | External implementations | Downstream packages own their case suites; no external runtime is required. |

Targeted commands:

    .venv/bin/pytest -q tests/package/test_plugins_api.py tests/contracts/test_codec_contract.py tests/contracts/test_executor_capabilities_contract.py tests/package/test_pipeline_event_sinks_api.py
    .venv/bin/pytest -q tests/unit/loom/plugins/test_diagnostics.py tests/unit/loom/cli/test_plugins.py tests/unit/loom/testing

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: compatibility break in plugin diagnostic output; checker APIs that
  hide required cases; accidental runtime dependency on test support.
- Review focus: readiness truth, derived legacy status, public report economy,
  and import direction.
- Stop if: a checker needs domain data or a runtime service; existing CLI JSON
  compatibility cannot be maintained without a product decision; or tests show
  `loom.testing` entering ordinary imports.
- Accepted debt/revisit: supplied cases bound conformance evidence. Add a new
  checker only when a public extension with a downstream consumer needs it.

## Executor Handoff

- Read: this entire phase plan plus planning `FR-1` through `FR-3`, `FR-12`,
  `DQ-1`, `DQ-2`, `EDR-3`, and `EDR-8`.
- Safe slices: the five numbered slices in order; docs may follow tested shapes.
- Do not revisit: six facet names, derived legacy status, four checker scope,
  no pytest/runtime-root dependency, and no runtime activation.
- Manager action required for: any proposed public report-field change,
  additional extension type, or incompatibility in existing JSON fields.

## Workflow State

- Manager preparation: complete; branch, worktree, base, target, title,
  dependency boundary, source seams, and targeted tests verified
- Expanded planning: not needed; stage-level design review resolved report risk
- Implementation: complete at `a391ba5ff03c4f3c5e0934fb9f9f784db983483c`; phase source,
  tests, and canonical documentation are committed
- Refiner: not needed unless a qualified blocker is returned
- Pre-submit gate: pending
- Independent review: manager-local fast path
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `a391ba5ff03c4f3c5e0934fb9f9f784db983483c`: `src/loom/plugins/diagnostics.py`, `src/loom/plugins/__init__.py`, and `src/loom/cli/plugins.py` add derived six-facet readiness and v2 CLI diagnostic payloads; `src/loom/testing/` adds report values and the four bounded public checkers; phase-scoped docs update `docs/features/plugins.md`, `docs/features/protocols.md`, `docs/features/testing.md`, and `docs/structure.md`. |
| Tests added or updated | `tests/unit/loom/testing/test_contracts.py`, `tests/package/test_testing_api.py`, `tests/unit/loom/plugins/test_diagnostics.py`, `tests/package/test_plugins_api.py`, and `tests/contracts/test_cli_plugins_contract.py`; targeted phase selection passed 43 tests. |
| Validated revision/tree state and evidence | Source/test/docs tree at `a391ba5ff03c4f3c5e0934fb9f9f784db983483c`: `ruff check .` passed; changed-path Pyright passed with 0 errors; `uv build` passed; `make test-summary` passed all 2,313 selected tests (3 skipped) and wrote `build/test-summary.md` at `2026-08-21T00:15:00+00:00`. `make validate-pr` was started on the stable tree, but this executor's command runner ended its receipt before the full gate completed; the manager must obtain that single gate receipt before pre-submit. |
| Validation-relevant changes after evidence | none; this completion-record-only commit does not alter source, tests, dependencies, build, or validation configuration. |
| PR, review, and merge | pending |
| Residual risk and cleanup | No product or phase-design blocker. The only outstanding gate is the manager's complete `make validate-pr` receipt; `loom.testing` intentionally proves only caller-supplied trusted cases and does not claim remote/backend behavior. |

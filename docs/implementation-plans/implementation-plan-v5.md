# Implementation Plan v5: Stage Worker And Subprocess Execution

## Metadata

- Status: refined implementation plan
- Related planning notes:
  `docs/implementation-plans/roadmap-v5-planning-notes.md`
- Related source docs:
  - `docs/implementation-plans/implementation-roadmap.md`
  - `docs/implementation-plans/implementation-plan-v4.md`
  - `docs/features/execution.md`
  - `docs/features/reliability.md`
  - `docs/features/state.md`
  - `docs/features/run-store.md`
  - `docs/features/cli.md`
  - `docs/features/preflight.md`
  - `docs/features/testing.md`
  - `docs/structure.md`
- Draft pass: complete on 2026-05-07 from confirmed roadmap v5 planning notes
- Refine pass: complete on 2026-05-07 after the initial
  `loom_plan_reviewer` quality-gate review
- Plan quality gate: passed on 2026-05-07 after initial
  `loom_plan_reviewer` review, one refinement pass, and confirmation review
- Blockers: none known

## Goal

Implement the v5 stage-worker and subprocess execution substrate for `loom`.
After v5, one prepared stage attempt can run from durable Loom state in a
separate worker process, and a serial `SubprocessExecutor` can drive a whole
run through the same parent-owned lifecycle and persistence semantics as local
execution.

The version should create a stable future-executor contract first, with local
debugging strong enough to validate that contract and observable behavior.

## Context

V0 through v3 establish the local runtime kernel, authored config/source
records, CLI core, local diagnostics, logs, artifact inspection, and preflight
infrastructure. V4 is assumed complete for this plan and provides the runtime
options/resources layer v5 depends on: normalized `RunOptions`, resolved
per-stage runtime handoff data, executor descriptors and capabilities,
runtime/resource preflight checks, and persisted safe `runtime.json` metadata.

The remaining execution gap is process isolation. Local execution still runs
stage code in the coordinator process. V5 creates the bridge required before
SLURM, container, and future remote executors can invoke Loom stage work without
embedding runner internals or depending on parent-process memory.

The roadmap names v5 as "Stage worker and subprocess execution". The confirmed
planning notes define two user-visible workflows:

- `loom run CONFIG --executor subprocess` for serial whole-run subprocess
  execution.
- `loom stage run --run-uri RUN_URI --stage STAGE` as the stable direct worker
  entry point for one prepared stage attempt, with `--attempt N` available for
  parent-launched or future scheduler/container commands.

## Desired Outcome

When all phases are complete:

- Users can run a small pipeline through local and subprocess execution with
  equivalent persisted semantics for status, outputs, result records, failures,
  logs, traceback paths, executor metadata, and v3 inspection compatibility.
- `loom stage run --run-uri RUN_URI --stage STAGE` executes only the requested
  prepared stage attempt from durable Loom records.
- Parent runner code prepares and finalizes stage lifecycle; the worker writes
  only the structured result handoff for its assigned attempt.
- Successful and failing subprocess stages persist schema-versioned
  request/result/failure metadata with explicit attempt identity.
- Subprocess failures preserve exit-code and signal facts separately when the
  operating system reports a signal termination.
- Missing, invalid, stale, mismatched, or conflicting worker results fail
  loudly and leave useful diagnostics.
- Subprocess preflight detects missing worker command or unresolvable Python
  executable for selected subprocess execution without launching user stage
  code.
- Examples demonstrate local/subprocess success behavior, subprocess failure
  inspection, direct worker execution, and missing/invalid result diagnostics
  where practical.

## Non-Goals

- No SLURM script planning or live scheduler submission.
- No Docker, Apptainer, or other container command construction.
- No automatic retries, retry policy, rich failure categorization, or cleanup
  policy.
- No timeout enforcement beyond recording process result metadata.
- No worker pools or parallel scheduling.
- No plugin-discovered executors.
- No remote stores.
- No sweeps, run catalogs, run bundles, dashboards, or domain-specific worker
  behavior.
- No full environment variable persistence.
- No sandboxing or untrusted-code isolation guarantee.
- No full `stages/<stage>/attempts/<n>/...` archive layout unless a refinement
  review finds an implementation blocker that cannot be handled with
  latest-stage-compatible records.

## Constraints

- Keep `loom` domain-neutral.
- Preserve the source-tree and import boundaries in `docs/structure.md`.
- Treat authored configs as trusted project code.
- Use run-store and artifact-store APIs instead of execution or executor code
  path-walking store internals where public APIs exist.
- Keep CLI as an outer presentation layer. Lower layers must not import
  `loom.cli`.
- Keep execution responsible for lifecycle and worker orchestration; executors
  own backend invocation and process collection; stores own persistence.
- Add no heavyweight runtime dependencies. Standard library `subprocess` and
  existing local helpers should be enough.
- Default tests must be local, synthetic, deterministic, and network-free.
- V5 implementation must not alter semantic fingerprints differently for
  equivalent local/subprocess execution unless an explicit future policy says
  so.

## Design Principles

- Stable future-executor contract comes before minimizing the subprocess diff.
- Worker reconstruction is durable-only: no pickled objects, raw stage objects,
  opaque parent payloads, or parent-process memory dependencies.
- Parent owns final commit semantics. Worker owns only one assigned stage
  attempt and the structured handoff it writes.
- Request/result records are schema-versioned and validated.
- Attempt identity is explicit in records and APIs, while public direct worker
  use does not require users to know attempt counts when one unambiguous
  prepared/running attempt exists.
- Subprocess execution should be a debuggable local preview of later
  scheduler/container behavior.
- Debug metadata should be useful but privacy-preserving: persist redacted
  command/process/log facts, not full environment values.
- Tests are part of the contract, not a late cleanup activity.

## Key Design Choices

- Public worker command:
  `loom stage run --run-uri RUN_URI --stage STAGE`.
- `--attempt N` is an advanced/internal exact-attempt flag used by
  parent-launched subprocesses and future scheduler/container commands.
- `--config` is not part of the stable worker CLI unless durable run metadata
  proves insufficient during implementation.
- Execution-owned modules define stage execution request/result contracts and
  worker APIs.
- `loom.pipeline.executors.subprocess` owns subprocess command construction,
  process launch, stdout/stderr capture, result readback, and process metadata.
- Stage request/result/failure records are schema-versioned and describe
  exactly one prepared stage attempt.
- Failure and process-result records preserve signal metadata separately from
  exit codes when a worker process terminates by signal.
- Worker reconstructs from durable Loom state: run URI, stage, attempt,
  prepared request/input/fingerprint metadata, resolved config/source
  snapshots, pipeline spec, run/artifact-store records, prior stage artifacts,
  and the v4 resolved runtime handoff.
- Execution exposes a parent-side prepare-stage-attempt API before direct worker
  or subprocess orchestration uses the contract. The prepare API writes the
  request/input/fingerprint/log-path metadata and records the prepared/running
  attempt identity without invoking worker code.
- V5 keeps latest-stage-compatible files for status, inputs, outputs,
  fingerprints, failures, provenance, logs, and diagnostics while adding
  explicit attempt identity and request/result records.
- Production `SubprocessExecutor` is process-isolating and serial. Fake,
  injectable, and in-memory runner paths may exist for deterministic component
  tests.
- Exit-code handling and failure normalization are one policy surface:
  structured success cannot override a nonzero worker process exit, and signal
  termination is reported as process failure rather than flattened into an
  ambiguous exit-code-only record.
- Selected subprocess preflight failures for missing worker command or Python
  executable are `FAIL`, not warnings.
- Security/trust assumptions are explicit: authored configs are trusted, and
  subprocess isolation is not a sandbox.

## Conflicts And Tradeoffs

- Stable executor contract vs implementation size: v5 accepts broader
  request/result/schema/testing work so later SLURM and container phases do not
  duplicate runner internals.
- Latest-stage compatibility vs attempt history: v5 records attempt identity
  but defers full attempt archive directories until retries or reliability work
  creates real multi-attempt history.
- Minimal stale-worker validation vs full locking: v5 validates result identity
  and expected prepared/running state, but defers locks, leases, and
  multi-coordinator semantics.
- Production process isolation vs test determinism: production subprocess runs
  real worker processes, while tests may use fake/in-memory runners to validate
  contracts without fragile process management.
- Debuggability vs secret safety: v5 persists redacted command/process/log
  metadata and inherited-environment summary, not full environment values.
- Dedicated preflight/diagnostics phase vs fewer PRs: user confirmed
  preflight/diagnostics should remain its own review boundary.
- Dedicated hardening/examples phase vs finishing earlier: user confirmed final
  hardening/docs should remain its own phase because comprehensive behavior
  validation and examples are critical.

## Maintainability Assessment

Maintainability depends on preserving one owner for each part of the new
contract. Execution owns lifecycle and worker orchestration. Executors own
backend invocation and process collection. Stores own persistence APIs and
layout. CLI adapts user input into public execution APIs and presents results.

The biggest maintainability risk is accidentally creating a second runner in
the worker or subprocess executor. The plan prevents this by making the worker
write only a structured handoff and making the parent runner validate outputs,
write final state, and finalize the whole run.

The second risk is scattering failure handling across CLI, executor, worker,
and store code. V5 centralizes exit-code/result interpretation and failure
normalization so missing, invalid, stale, mismatched, and conflicting results
are all explicit tested outcomes.

The phase breakdown keeps each review slice bounded: pure contracts and store
APIs first, then direct worker behavior, then production subprocess
orchestration, then preflight/diagnostics, then cross-component hardening,
examples, and docs.

## Extensibility Assessment

V5 is the extension base for later executor roadmap versions:

- V6/V7 SLURM phases can invoke the same `loom stage run` worker command
  instead of embedding stage logic in generated scripts.
- V14/V15 container executors can launch the same worker contract inside
  Docker/Apptainer contexts.
- V16 reliability policies can build on attempt identity, baseline failure
  records, exit-code semantics, and missing-result handling.
- Later remote-store work can replace local path assumptions with store-backed
  reconstruction because the worker contract is already durable-record-driven.
- Plugin-discovered executors can later populate descriptor/capability
  registries without changing the worker command.

The plan deliberately does not implement retry, timeout, pool, scheduler,
container, plugin, remote-store, cleanup, or sandboxing behavior before their
own roadmap versions.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No full attempt archive directories | Preserve v0/v3 diagnostics compatibility and avoid layout churn before retries exist. | Automatic retries, cleanup/retention, or reliability policies need attempt history. |
| No heavyweight locking or lease semantics | Serial subprocess execution has one parent coordinator; minimal result-identity validation is enough for v5. | Parallel scheduling, retries, remote stores, scheduler coordination, or duplicate-worker recovery. |
| No retry or rich failure policy | Belongs to v16 reliability; v5 only needs baseline failure records and attempt identity. | v16 reliability policies or a prior phase needing retry-aware failure categorization. |
| No timeout enforcement | Timeout policy is executor/reliability work beyond the v5 contract. | v16 reliability or an executor phase that can enforce timeouts. |
| No worker pools or parallel scheduling | V5 validates the one-stage worker contract through serial orchestration. | Later execution/reliability phase introduces parallel scheduling or pools. |
| No SLURM/container command construction | Later executor phases own backend-specific command and submission behavior. | v6/v7 for SLURM, v14/v15 for Docker/Apptainer. |
| No plugin-discovered executors | Plugin discovery belongs to v11. | v11 plugin discovery. |
| No remote stores | Remote store semantics belong to later remote-store roadmap work. | v12/v13 remote-store phases. |
| No cleanup/retention policy | Cleanup is separate operational lifecycle work. | v17 cleanup/retention work. |
| No full environment persistence | Avoid accidental secret persistence and keep v5 privacy policy simple. | Later explicit environment overlay, clean environment, scheduler/container environment capture, or opt-in provenance policy. |
| No sandboxing guarantee | Authored configs are trusted project code; subprocess isolation is not a security boundary. | Container/remote execution phases if stronger isolation becomes a product goal. |

## Plan Quality Gate

- Status: passed on 2026-05-07
- Required reviewer: `loom_plan_reviewer`
- Required before: creating any v5 phase execution plan or starting Phase 1
  implementation
- Review focus:
  - stability of the worker CLI, Python API, and schema contracts for future
    SLURM/container invocation;
  - correctness of the parent/worker lifecycle and commit boundary;
  - existence and reviewability of the parent-side prepare-stage-attempt API
    before direct worker and subprocess phases depend on prepared attempts;
  - sufficiency of durable-only worker reconstruction inputs from v4 and prior
    phases;
  - explicit request-schema coverage for the v4 resolved per-stage runtime
    handoff, without requiring workers to reinterpret raw config/profile inputs;
  - compatibility of latest-stage-compatible layout with v3 diagnostics and
    future retry/reliability work;
  - failure semantics for nonzero exits, signal terminations, missing results,
    invalid results, stale/mismatched results, and conflicts;
  - subprocess preflight and diagnostics integration without launching user
    stage code;
  - package, unit, contract, integration, E2E, and example test obligations;
  - clarity of deferred later-version owners and trust/security assumptions.
- Loop budget:
  - Initial review: used on 2026-05-07; blockers found for pending refine/gate
    state, Phase 3/Phase 4 subprocess CLI/preflight boundary, and missing
    signal semantics.
  - Gate refinement pass: used on 2026-05-07; Phase 3 now owns minimal
    subprocess descriptor/CLI executor factory/preflight compatibility, Phase 4
    owns worker/Python availability checks and diagnostics UX, and signal
    metadata is part of the v5 schema/process contract.
  - Confirmation review: used on 2026-05-07; no blocking findings remained.
- Current gate result: passed.

Refinement summary:

- Pending draft/refine metadata was resolved by marking the implementation plan
  refined and recording that the v4 prerequisite is verified complete on
  `develop`.
- The `loom run --executor subprocess` acceptance path remains in Phase 3, but
  Phase 3 now explicitly owns the minimal executor descriptor registration, CLI
  executor selection/factory wiring, and preflight compatibility needed for the
  run to pass current `loom run` gates. Phase 4 keeps selected-subprocess
  worker-command/Python availability checks, concise failure UX, diagnostics,
  and JSON output behavior.
- Signal metadata was added to the request/result/failure contract, process
  mapping, diagnostics, CLI output, and test expectations where relevant.

## Phased Implementation

### Phase 1 - Contracts And Persistence

Status: merged
Branch: `codex/stage-worker-contracts`
PR: https://github.com/samcantrill/loom/pull/77

Goal:

- Establish the stable request/result/failure contract and persistence surface
  for one prepared stage attempt.

Scope:

- Define stage execution request and worker result records with schema
  versions, validation, and serialization.
- Define the execution-owned prepare-stage-attempt API boundary that creates one
  prepared attempt without invoking worker code.
- Add baseline failure/result metadata fields for subprocess handoff,
  including attempt identity, log paths, traceback paths, executor metadata,
  timestamps, status, exit code, and signal when applicable.
- Include an explicit request-field contract for the v4 resolved per-stage
  runtime handoff reference or safe summary, so workers and future executors do
  not reinterpret raw config/profile inputs.
- Add or extend run-store/artifact-store APIs needed for prepared attempt
  request/result persistence without path walking from execution code.
- Add or extend store APIs for reading/writing prepared request metadata,
  input/fingerprint metadata, log-path allocations, and result handoff records
  by run URI, stage, and attempt.
- Preserve latest-stage-compatible files while recording explicit attempt
  identity in new or updated records.
- Add metadata redaction helpers needed by persisted executor records.
- Align source feature docs early where they conflict with the confirmed v5
  contract, including `--run-uri` over legacy `--run-dir` worker spelling, no
  normal `--config` worker input, parent-owned finalization, latest-stage
  compatibility, and store/API-owned layout.

Out of scope:

- Worker CLI behavior.
- Real subprocess process launch.
- Preflight checks.
- Attempt archive directories and retry history.
- Direct worker CLI argument parsing beyond source-doc alignment for the
  confirmed command contract.

Acceptance criteria:

- Request/result/failure records round-trip through the selected serialization
  path and reject invalid, missing, or conflicting required fields.
- Persisted records include run URI, stage, attempt, schema version, timestamps,
  and executor/log/failure fields needed by later phases, including separate
  exit-code and signal fields for process failures.
- Request records include or reference the v4 resolved per-stage runtime handoff
  needed by workers and future executors.
- The prepare-stage-attempt API writes enough durable state for Phase 2 worker
  execution tests to use real prepared attempts rather than hand-crafted store
  fixtures.
- Store-facing APIs preserve current diagnostics-compatible latest-stage
  layout.
- Redaction helpers avoid persisting full environment values or unredacted
  sensitive command metadata.
- `docs/features/execution.md`, `docs/features/cli.md`, and related store/state
  docs no longer present worker behavior that conflicts with this plan's
  `--run-uri`, no-normal-`--config`, and parent-finalization decisions.

Test expectations:

- Package: import-boundary tests for new public record/store exports.
- Unit: schema validation, serialization, redaction, missing fields, invalid
  status, exit-code and signal fields, result/failure field combinations, and
  resolved runtime handoff request-field validation.
- Contract: prepare-stage-attempt API contract, run-store/artifact-store
  request/result/failure persistence contracts, and source-doc contract
  alignment for worker identity/finalization behavior.
- Integration: temporary run directory persistence/readback through store APIs.
- E2E: not required in this phase.
- Opt-in: none.

Design impact:

- Creates the durable contract that parent runners, workers, subprocess, and
  future executors share.
- Creates the parent-side preparation boundary that later phases use instead of
  preparing attempts through ad hoc fixtures or subprocess-specific code.

Future compatibility:

- Records attempt identity without committing to attempt archive directories,
  leaving retry history to later reliability work.
- Carries or references the v4 resolved stage runtime handoff so v6 SLURM
  scripts and v14/v15 container executors can consume executor/resource/runtime
  facts without duplicating config/profile merge logic.

Alternatives rejected:

- Unversioned ad hoc JSON.
- Opaque parent payloads.
- CLI-owned state mutation.
- Full attempt archive layout in v5.
- Worker-side reconstruction from raw config paths.

Debt introduced:

- Exact attempt history is not preserved beyond latest-stage-compatible
  records.
- The exact prepare API shape may need refinement when Phase 2 and Phase 3 wire
  it into worker and subprocess execution.

Reviewability:

- Review as pure models, validation, source-doc alignment, preparation boundary,
  and store API changes before process or CLI behavior exists.

Notes:

- PR feature focus: `Stage Worker`
- Intended PR title: `Stage Worker - Phase 1: Contracts and Persistence`

Completion summary:

- PR opened on 2026-05-07 against `develop` and merged on 2026-05-07:
  https://github.com/samcantrill/loom/pull/77.
- Implemented schema-versioned stage-worker request/result records,
  signal-aware failure metadata, executor metadata redaction, store APIs for
  `worker_request.json` and `worker_result.json`, local handoff path helpers,
  and the parent-owned `prepare_stage_attempt` API.
- Updated source docs for `--run-uri`, no normal worker `--config`,
  parent-owned finalization, signal metadata, and latest-stage-compatible
  worker handoff files.
- Validation before PR: `make validate-pr` passed, including Ruff, Pyright
  with config extra, default/config-extra test harnesses, and build.
- Suite evidence before PR: `make test-summary` passed; package 50 passed/1
  skipped, unit 569 passed/1 skipped, contract 53 passed/2 skipped,
  integration 15 passed/7 skipped/7 deselected, e2e 16 passed, config-extra
  397 passed/703 deselected.
- Automated review and merge: manager review found no blocking findings, PR
  target was verified as base `develop` and head `codex/stage-worker-contracts`,
  GitHub CI `checks` completed successfully, merge state was `CLEAN`, and the
  PR was squash-merged with merge commit
  `82ecfb9cadd08abc2286b91ad94d04ac58a5d54f`.
- Follow-up notes: Phase 2 must consume the prepared request/store APIs for
  direct worker execution; Phase 3 owns subprocess process launch and current
  CLI executor selection wiring.

### Phase 2 - Worker Execution And Direct CLI

Status: merged
Branch: `codex/stage-worker-cli`
PR: https://github.com/samcantrill/loom/pull/78

Goal:

- Implement the one-stage worker API and `loom stage run` command against
  durable run metadata.

Scope:

- Add execution-owned worker orchestration APIs that reconstruct one prepared
  stage attempt from durable Loom state.
- Use the Phase 1 prepare-stage-attempt API to create or locate prepared
  attempts for direct worker tests and CLI behavior. Do not require hand-crafted
  store fixtures for normal worker integration tests.
- Implement direct `loom stage run --run-uri RUN_URI --stage STAGE` with
  advanced/internal `--attempt N` support and narrow metadata/debug flags.
- Implement attempt inference only when exactly one unambiguous
  prepared/running attempt exists.
- Execute stage code through the local stage execution machinery and write the
  structured worker result handoff.
- Implement worker exit codes `0`, `1`, `2`, `3`, and `130`.
- Add fake/injectable and in-memory runner paths for component tests where
  useful.

Out of scope:

- Production subprocess parent orchestration.
- Whole-run subprocess execution.
- Preflight integration.
- Worker-owned final stage/run finalization.
- Defining a second prepare-attempt path separate from the Phase 1 execution
  API.

Acceptance criteria:

- Direct worker command executes exactly one prepared stage attempt and does not
  plan the whole pipeline or mutate unrelated stages.
- Worker reconstructs only from durable Loom records and prior stage artifacts.
- Worker reconstruction consumes the prepared request metadata, including the
  v4 resolved stage runtime handoff reference or safe summary, instead of
  accepting raw config paths or parent-process payloads.
- Users do not write handoff/status mutation code.
- Worker returns clear usage/state errors for ambiguous or missing attempts.
- Worker writes a structured result handoff and exits with the documented code.

Test expectations:

- Package: public worker API and CLI import-boundary tests.
- Unit: command parsing, attempt inference, exit-code mapping, durable
  reconstruction errors, and result handoff validation.
- Contract: worker writes only the handoff it owns and respects parent/worker
  commit boundary.
- Integration: direct worker success/failure against temporary prepared runs
  created through the prepare-stage-attempt API, using synthetic stages and
  in-memory/fake runner support.
- E2E: direct worker smoke success/failure if phase scope permits.
- Opt-in: none.

Design impact:

- Introduces the stable worker entry point future executors invoke.

Future compatibility:

- `--attempt` gives parent, scheduler, and container launches precise identity
  without requiring public users to know attempt counts.

Alternatives rejected:

- `--config` as a normal worker input.
- Pickled payloads.
- Worker-side planning.
- Worker-owned finalization.

Debt introduced:

- Direct worker is still tied to local durable run-store semantics; remote
  store concerns remain future work.

Reviewability:

- Review as isolated worker behavior before adding real subprocess process
  control.

Notes:

- PR feature focus: `Stage Worker`
- Intended PR title: `Stage Worker - Phase 2: Worker Execution and Direct CLI`

Completion summary:

- PR opened on 2026-05-07 against `develop` and merged on 2026-05-07:
  https://github.com/samcantrill/loom/pull/78.
- Implemented execution-owned direct worker APIs for prepared-attempt
  inference, durable reconstruction, local execution, and structured
  `worker_result.json` handoff writes.
- Added `loom stage run --run-uri RUN_URI --stage STAGE [--attempt N]` with
  text/JSON output and direct-worker exit codes `0`, `1`, `2`, `3`, and `130`.
- Preserved parent-owned finalization: the worker does not write final stage
  outputs, failure records, provenance, artifact indexes, stage status, or run
  status.
- Added package, unit, contract, and integration coverage for public exports,
  CLI parsing/output, attempt inference, state errors, handoff-only
  persistence, successful worker execution, and stage-failure handoffs.
- Validation before PR: targeted tests passed with 24 passed; targeted Pyright
  passed; `make validate-pr` passed after rebasing onto current `develop`;
  `make test-summary` passed with package 50 passed/1 skipped, unit 579
  passed/1 skipped, contract 54 passed/2 skipped, integration 18 passed/7
  skipped/7 deselected, e2e 16 passed, and config-extra 400 passed/717
  deselected.
- Automated review and merge: manager review found a duplicate worker handoff
  overwrite risk, which was fixed before merge by rejecting existing
  `worker_result.json` handoffs for the same attempt. After that fix, review
  found no remaining blocking findings. PR target was verified as base
  `develop` and head `codex/stage-worker-cli`, GitHub CI `checks` completed
  successfully, merge state was `CLEAN`, and the PR was squash-merged with
  merge commit `bcb2c41cb391ffb4176d3c396d11df8edb486025`.
- Stack maintenance: branch was rebased onto current `develop` after `develop`
  advanced with `docs: add v3 v4 examples`.
- Follow-up notes: Phase 3 must consume the direct worker command and handoff
  readback contract for subprocess process launch and parent-owned run
  finalization; Phase 4 still owns selected-executor preflight and diagnostics
  UX.

### Phase 3 - Subprocess Executor And Serial Run Integration

Status: merged
Branch: `codex/subprocess-executor`
PR: https://github.com/samcantrill/loom/pull/79

Goal:

- Add production subprocess execution and serial whole-run integration through
  the normal parent runner lifecycle.

Scope:

- Implement `SubprocessExecutor` command construction, worker process launch,
  stdout/stderr capture, result-file location, process metadata collection, and
  structured result readback.
- Register the subprocess executor descriptor/capability metadata needed for
  runtime validation and current selected-executor preflight to recognize the
  executor without loading optional backends.
- Add CLI executor selection/factory wiring so `loom run CONFIG --executor
  subprocess` invokes `SubprocessExecutor` through the existing run path.
- Wire `loom run CONFIG --executor subprocess` into the existing planner and
  parent runner lifecycle as a serial one-worker-per-runnable-stage path using
  the shared prepare-stage-attempt API.
- Keep parent-owned final commit semantics: output validation, outputs/failure,
  provenance/status, and run finalization.
- Implement conflict handling where process exit and structured result
  disagree.
- Preserve signal metadata separately from exit codes when subprocesses
  terminate by signal.
- Use fake/injectable process runner support for deterministic component tests
  and real subprocess integration tests for the production path.

Out of scope:

- Parallel scheduling and worker pools.
- Timeout enforcement.
- SLURM/container command construction.
- Heavy locking, leases, or multi-coordinator semantics.
- Worker command/Python executable availability checks beyond the minimal
  selected-executor compatibility required for the current `loom run`
  preflight gate; Phase 4 owns those diagnostics.

Acceptance criteria:

- A small success pipeline runs through local and subprocess execution with
  equivalent persisted outputs/status/result metadata.
- A small failure pipeline fails loudly with structured failure metadata,
  stdout/stderr paths, traceback path when applicable, and redacted executor
  command metadata.
- Missing, invalid, stale, and conflicting worker results become explicit
  failures.
- Nonzero process exit always fails the stage, including structured-success
  conflicts.
- Signal termination always fails the stage and records the signal fact
  distinctly from ordinary process exit code metadata.
- Current `loom run` preflight no longer rejects the selected subprocess
  executor merely because the executor name is unknown or unsupported.

Test expectations:

- Package: subprocess executor export/import-boundary tests.
- Unit: command construction, redaction, process result mapping, signal
  mapping, missing/invalid result handling, and conflict semantics.
- Contract: parent/worker commit boundary, result identity validation, and
  failure normalization through real prepared attempts.
- Integration: serial subprocess orchestration for synthetic success/failure
  pipelines using temporary run directories.
- E2E: `loom run --executor subprocess` success/failure smoke coverage through
  the real CLI selection path.
- Opt-in: none.

Design impact:

- Proves the worker contract through real process isolation while keeping the
  runner lifecycle parent-owned.

Future compatibility:

- Provides the launch/result pattern later scheduler and container executors
  adapt without reimplementing stage execution.

Alternatives rejected:

- Treating subprocess as a second runner.
- Relying only on in-memory tests.
- Accepting nonzero exits as success when structured result says success.
- Deferring all subprocess preflight compatibility to Phase 4, because Phase 3
  must produce reviewable `loom run --executor subprocess` evidence through the
  current CLI gate.

Debt introduced:

- No parallelism, timeout enforcement, retries, or multi-coordinator safety.

Reviewability:

- Review as process orchestration and whole-run integration after contracts and
  worker behavior are already established.

Notes:

- PR feature focus: `Stage Worker`
- Intended PR title: `Stage Worker - Phase 3: Subprocess Executor and Serial Run Integration`

Completion summary:

- PR opened on 2026-05-07 against `develop`:
  https://github.com/samcantrill/loom/pull/79.
- Implemented `SubprocessExecutor`, subprocess worker command construction,
  process metadata redaction, worker result readback, process/result conflict
  handling, missing/invalid/mismatched result failures, and signal-aware
  process failure mapping.
- Wired `loom run CONFIG --executor subprocess` through CLI executor selection
  and the parent runner's prepared-worker path. The worker writes only
  `worker_result.json`; the parent runner still owns final outputs, failure
  persistence, provenance, artifact indexes, stage status, and run status.
- Registered an import-light subprocess runtime descriptor so selected
  subprocess execution passes current executor capability validation without
  loading executor implementation modules through runtime imports.
- Added package, unit, contract, integration, and e2e coverage for subprocess
  exports/import boundaries, command construction, process failure mapping,
  signal metadata, result conflicts, runner preparation/finalization, CLI
  selection, and real success/failure subprocess CLI smoke runs.
- Validation before PR: focused tests passed with 36 passed/1 skipped; focused
  Ruff and Pyright passed; `make validate-pr` passed; `make test-summary`
  passed with package 50 passed/1 skipped, unit 587 passed/1 skipped, contract
  55 passed/2 skipped, integration 20 passed/7 skipped/7 deselected, e2e 18
  passed, and config-extra 400 passed/730 deselected.
- Automated review and merge: manager review found no blocking findings after
  the import-boundary fix. PR target was verified as base `develop` and head
  `codex/subprocess-executor`, GitHub CI `checks` completed successfully,
  merge state was `CLEAN`, and the PR was squash-merged with merge commit
  `72580b5161e9cef7af51ce9b8cdae9641fb53b32`.
- Follow-up notes: Phase 4 must build subprocess worker/Python availability
  preflight and concise diagnostics UX on the process metadata and failure
  records introduced here; timeout enforcement, retries, leases, and parallel
  subprocess scheduling remain deferred.

### Phase 4 - Preflight, Diagnostics, And CLI UX

Status: merged
Branch: `codex/subprocess-preflight-diagnostics`
PR: https://github.com/samcantrill/loom/pull/80

Goal:

- Make subprocess execution diagnosable and validate selected executor
  availability before running user stage code.

Scope:

- Add subprocess preflight checks under the existing preflight and executor
  capability model.
- Fail selected subprocess preflight when the worker command or Python
  executable is unavailable.
- Keep checks deterministic and avoid launching user stage code.
- Add concise CLI failure output for worker/subprocess failures, including
  stage, attempt when known, exit code, signal when applicable, message,
  stdout/stderr paths, and traceback/failure path.
- Ensure existing v3 diagnostics/status/log/artifact inspection can explain
  subprocess failures from persisted records.
- Support machine-readable output through existing JSON/output conventions.

Out of scope:

- New diagnostics command family.
- Scheduler/container preflight checks.
- Full environment persistence.

Acceptance criteria:

- Selected subprocess preflight reports structured failures for missing worker
  command or Python executable.
- Selected subprocess preflight distinguishes missing worker/Python availability
  from generic unknown-executor rejection, which Phase 3 resolves for normal
  subprocess selection.
- CLI output remains concise and local-run-like in normal runs.
- Failure output points users to persisted logs and failure records.
- Existing inspection paths read subprocess metadata without importing project
  stage code unnecessarily.

Test expectations:

- Package: preflight/check ID import-boundary tests where public.
- Unit: check result construction, selected-executor failure severity, CLI
  formatting including signal facts, JSON output shape, and no-user-code
  preflight behavior.
- Contract: diagnostics compatibility with persisted failure/log metadata.
- Integration: CLI/preflight subprocess failure scenarios with controlled PATH
  or fake executable resolution.
- E2E: failure UX smoke coverage through `loom run --executor subprocess`.
- Opt-in: none.

Design impact:

- Separates operability and diagnostics from the core executor wiring.

Future compatibility:

- Establishes the selected-executor availability pattern for SLURM/container
  checks in later versions.

Alternatives rejected:

- Warning-only selected-subprocess availability failures.
- Verbose default command dumps.
- Checks that run user stage code.

Debt introduced:

- Exact check IDs and CLI formatting may evolve with later executor phases.

Reviewability:

- Review as dedicated preflight and diagnostics behavior, as confirmed during
  roadmap planning.

Notes:

- PR feature focus: `Stage Worker`
- Intended PR title: `Stage Worker - Phase 4: Preflight, Diagnostics, and CLI UX`

Completion summary:

- PR opened against `develop` on 2026-05-07:
  https://github.com/samcantrill/loom/pull/80
- Merged into `develop` on 2026-05-07 with merge commit
  `fa4ba4b19a6e58f15a31fcf76014b77f1b4b8c3a`.
- Implementation summary: added selected-subprocess preflight checks for the
  current Python executable and `loom stage run` worker importability, gated so
  local executor preflight output remains unchanged. Extended run failure
  summaries and text output with optional attempt, executor, exit code, signal,
  failure record, stdout, stderr, and traceback paths. Updated focused
  preflight, CLI, and execution docs for current subprocess diagnostics UX.
- Review and validation: manager review found no blocking issues. PR #80
  targeted `develop`; GitHub CI `checks` passed on commit
  `a2303f4a7da4efbe958da8ea5f2aed68520bcdea`. Local validation passed before
  merge: `make validate-pr`; `make test-summary` with package 50 passed/1
  skipped, unit 593 passed/1 skipped, contract 55 passed/2 skipped,
  integration 20 passed/7 skipped/7 deselected, e2e 18 passed, config-extra
  401 passed/736 deselected.
- Follow-up notes: Phase 5 still owns broader examples, final contract
  hardening, and deferred behavior documentation.

### Phase 5 - Contract Hardening, Examples, And Documentation

Status: pending
Branch: `codex/subprocess-contract-hardening`
PR: pending

Goal:

- Harden cross-component behavior, provide examples, and document deferred
  later-version behavior and trust assumptions.

Scope:

- Add comprehensive cross-component tests for local/subprocess equivalence,
  worker result validation, failure normalization, stale/mismatched results,
  missing/invalid results, signal-aware process failures, redacted metadata,
  and diagnostics compatibility.
- Add local, synthetic examples that demonstrate:
  - local vs subprocess success behavior;
  - subprocess stage failure with logs/failure inspection;
  - direct `loom stage run` against a prepared stage;
  - missing/invalid worker result diagnostics where practical.
- Document no sandboxing guarantee, trusted authored configs, privacy defaults,
  and full-environment-persistence deferral.
- Document deferred behavior with later-version owners and revisit triggers:
  retries/failure policy, timeouts, worker pools/parallel scheduling, SLURM,
  containers, plugins, remote stores, cleanup/retention, attempt archive
  directories, and stronger locking.
- Run final validation and prepare evidence needed for plan review and later PR
  bodies.

Out of scope:

- Implementing any deferred later-version behavior.
- Real cluster/container examples requiring external systems.
- Network or downstream-project-dependent examples.

Acceptance criteria:

- Component and cross-component behavior has comprehensive test evidence.
- Examples are runnable locally with synthetic/domain-neutral stages.
- Docs explicitly state what v5 does, what it does not do, and which later
  versions own deferred behavior.
- Plan-quality-gate inputs and phase handoff evidence are clear for review.

Test expectations:

- Package: final public export/import sweep.
- Unit: targeted regression tests for hardening gaps found in prior phases.
- Contract: executor contract tests covering local/subprocess equivalence,
  parent/worker boundaries, and signal-aware failure metadata where practical
  without making default tests platform-fragile.
- Integration: durable reconstruction, diagnostics, and subprocess
  orchestration edge cases.
- E2E: synthetic success and failure pipelines through both local and
  subprocess; example smoke tests where practical.
- Opt-in: none.

Design impact:

- Converts design decisions into verified behavior and user-facing examples.

Future compatibility:

- Documentation gives later roadmap versions explicit ownership of deferred
  behavior.

Alternatives rejected:

- Shipping the contract without examples.
- Treating docs as implicit.
- Deferring cross-component validation.

Debt introduced:

- Examples remain local/synthetic until later executor phases add real backend
  examples.

Reviewability:

- Review as a dedicated hardening and documentation phase so broad validation
  and examples do not obscure earlier implementation PRs.

Notes:

- PR feature focus: `Stage Worker`
- Intended PR title: `Stage Worker - Phase 5: Contract Hardening, Examples, and Documentation`

Completion summary:

- TBD

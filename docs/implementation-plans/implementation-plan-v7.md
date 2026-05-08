# Implementation Plan v7: SLURM Live Operations

## Metadata

- Status: ready for phase implementation
- Related planning notes:
  `docs/implementation-plans/roadmap-v7-planning-notes.md`
- Plan review report:
  `docs/implementation-plans/implementation-plan-v7-plan-review-report.md`
- Refinement summary:
  `docs/implementation-plans/implementation-plan-v7-refinement-summary.md`
- Confirmation review report:
  `docs/implementation-plans/implementation-plan-v7-confirmation-review-report.md`
- Related source docs:
  - `docs/implementation-plans/implementation-roadmap.md`
  - `docs/implementation-plans/implementation-plan-v6.md`
  - `docs/features/slurm.md`
  - `docs/features/execution.md`
  - `docs/features/runtime-resources.md`
  - `docs/features/preflight.md`
  - `docs/features/cli.md`
  - `docs/features/run-store.md`
  - `docs/features/state.md`
  - `docs/features/provenance.md`
  - `docs/features/testing.md`
  - `docs/loom.md`
  - `docs/structure.md`
- Draft pass: complete on 2026-05-08 from confirmed roadmap v7 planning notes
- Refine pass: complete on 2026-05-08 from initial plan-quality review findings
- Plan quality gate: passed on 2026-05-08 after initial review, one refinement
  pass, and confirmation review
- Blockers: none known for plan drafting. Phase implementation must verify
  that the v6 SLURM script-planning and continuation contracts are present on
  the actual implementation base.

## Goal

Implement the v7 live SLURM operations layer for `loom`.

After v7, users can select `slurm-single-job` or `slurm-afterok` without
`--dry-run` to submit real SLURM jobs from the v6 submission artifacts. Loom
records scheduler job IDs, partial submissions, status snapshots, cancellation
attempts, and safe scheduler metadata; exposes scheduler-aware inspection and
cancellation through general Loom commands; and preserves deterministic,
cluster-free default validation through fake command runners.

## Context

V6 is assumed complete for this plan. It provides deterministic SLURM dry-run
artifacts, schema-versioned planned submission manifests, structured
`SlurmOptions`, generic resource mapping, logical job keys, wrapper log paths,
prepared-run continuation for single-job scripts, and a generic
execution-owned stage-job runner for afterok scripts.

V7 turns that dry-run contract into optional live scheduler operations. The
version adds the first real `sbatch` integration, maps v6 logical job keys to
scheduler job IDs, records status/cancellation facts, and makes submitted runs
inspectable after the submit process exits.

The confirmed design deliberately keeps scheduler operations backend-neutral at
the user surface. Users should use general commands such as
`loom status RUN_URI --jobs` and `loom cancel RUN_URI --jobs`; the CLI discovers
the submitted backend from persisted records and delegates to backend APIs. A
SLURM-specific command group is deferred unless later diagnostics cannot fit the
general command model.

The largest cross-cutting change is adding shared submitted lifecycle states:
`RunStatus.SUBMITTED` and `StageStatus.SUBMITTED`. The planning discussion
accepted the moderate status/resume/diagnostics/test cost because a common
lifecycle is cleaner than requiring each submitted executor to invent its own
queued or pending semantics.

## Desired Outcome

When all phases are complete:

- `loom run CONFIG --executor slurm-single-job` generates or updates v6
  artifacts, writes a draft live manifest, calls `sbatch --parsable`, records
  the scheduler job ID, marks the run `SUBMITTED`, and returns concise text and
  schema-versioned JSON output.
- `loom run CONFIG --executor slurm-afterok` submits all planned `RUN` stages
  in topological order, uses scheduler-native `afterok` dependencies among
  submitted upstream job IDs, marks submitted stages `SUBMITTED`, and records
  every successful and failed submission incrementally.
- `--dry-run` remains the non-submitting preview path and does not call
  scheduler commands.
- Shared Loom status vocabulary includes `SUBMITTED` for submitted executors.
  Scheduler states such as SLURM `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`,
  `CANCELLED`, `TIMEOUT`, `OUT_OF_MEMORY`, `NODE_FAIL`, and `DEPENDENCY`
  remain backend metadata, not replacements for Loom status.
- Live manifests preserve logical job keys, scheduler job IDs, raw
  `sbatch --parsable` output, dependency job IDs, command records, status
  snapshots, cancellation attempts, wrapper log paths, and partial failure
  records.
- General scheduler-aware status is available through
  `loom status RUN_URI --jobs`. Default `loom status RUN_URI` remains
  persisted-state-only and does not query SLURM.
- General submitted-job cancellation is available through
  `loom cancel RUN_URI --jobs`, targets the latest active submission by
  default, records per-job outcomes, and returns nonzero on partial
  cancellation.
- Re-submitting into a run directory with active old submitted jobs fails
  loudly by default.
- Partial afterok submission preserves already-submitted job IDs, marks the
  submission `PARTIAL`, returns nonzero, and directs the user to explicit
  cancellation if cleanup is desired.
- Missing `sbatch` is a live-submission error. Missing `squeue` or `sacct` is
  a warning unless the user requested an operation that requires the missing
  command.
- Scheduler-aware status prefers run-store final state, then `sacct` final
  accounting data, then `squeue` active queue data, then persisted manifest
  state, and reports uncertainty rather than inventing final outcomes.
- Default validation remains local, deterministic, synthetic, and cluster-free
  through fake command runners.
- A comprehensive opt-in real SLURM acceptance suite is available for
  maintainers to run on a cluster. It is explicitly marked, skipped by default,
  and covers live submit/status/cancel/dependency/log/artifact behavior.

## Non-Goals

- No controller-style just-in-time downstream submission.
- No job arrays.
- No multi-node MPI orchestration.
- No containerized SLURM jobs or Docker/Apptainer/Singularity wrapping.
- No remote artifact synchronization, remote run stores, or cross-cluster
  submission.
- No automatic retry execution from scheduler failure categories.
- No automatic cleanup or cancellation after partial submission.
- No force/resubmit policy over active submitted jobs.
- No distributed lock manager.
- No dashboard, long-running service, or database-backed scheduler monitor.
- No default test dependency on a real SLURM cluster.
- No Python SLURM dependency.

## Constraints

- Keep `loom` domain-neutral. Project code owns module loading, conda or venv
  activation, site-specific data paths, and domain stage behavior.
- Preserve the source-tree boundaries in `docs/structure.md`.
- Keep SLURM command construction, scheduler parsing, live manifest models,
  status mapping, and cancellation mechanics under
  `loom.pipeline.executors.slurm`.
- Keep shared submitted lifecycle, continuation contracts, and submitted
  backend discovery under generic execution/run-store boundaries.
- Keep planning as the source of `RUN`, `REUSE`, `SKIP`, `STALE`, and
  `BLOCKED` decisions. The SLURM executor consumes a persisted plan and must
  not decide resume semantics.
- Keep the CLI as a thin outer layer: parse arguments, call Python APIs, format
  text/JSON, and choose exit codes. CLI modules must not parse scheduler
  output or path-walk SLURM layouts when store APIs exist.
- Use run-store APIs and path helpers for run-scoped generated artifacts,
  manifests, logs, and submitted-operation discovery.
- Do not persist environment variable values, unredacted resolved configs,
  resolver outputs, or raw secret-bearing adapter payloads by default.
- Treat authored configs and script prelude lines as trusted project code.
- Use `make validate-pr` before phase PR review and `make test-summary` before
  PR preparation.

## Design Principles

- Submitted executors share a common Loom lifecycle.
- Scheduler state supplements Loom state; it does not replace run/store status
  or stage provenance.
- Live submission extends the v6 manifest model instead of replacing it.
- The manifest is the canonical submitted-job identity source. Per-job state
  files may be derived convenience artifacts only.
- Partial submission and partial cancellation are first-class outcomes, not
  exceptional states to hide.
- Operational safety beats convenience for v7: fail loudly over active old jobs
  and require explicit cancellation or future force policies.
- Default validation stays fake-command and cluster-free. Real SLURM coverage
  is opt-in, documented, and safe for shared clusters.
- Scheduler command execution is fakeable and isolated from CLI and generic
  execution code.
- All new persisted scheduler facts must be artifact-safe and reviewable.

## Key Design Choices

- Add `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED` as shared non-terminal
  statuses for work accepted by an external submitted executor but not yet
  started by the Loom runner or stage-job worker.
- Define generic `SUBMITTED -> RUNNING` continuation semantics for submitted
  stage jobs: `loom stage-job run` may accept a submitted prepared attempt only
  when run URI, stage name, attempt, executor/backend identity, and submission
  metadata match, then transitions the stage to `RUNNING` through shared
  lifecycle helpers. This must not allow arbitrary stale submitted state to
  bypass local/subprocess lifecycle guards.
- Add generic submitted-operation records and run-store discovery helpers so
  general CLI commands can locate the latest submission, latest active
  submission, backend, mode, submission ID, manifest path, and active/terminal
  state.
- Define the generic submitted-operation registry contract with
  `schema_version`, `run_uri`, `submission_id`, `backend`, `mode`,
  `created_at`, `updated_at`, `state`, `manifest_relative_path`, summary counts,
  and optional backend metadata. Generic state values are `PREPARED`,
  `SUBMITTING`, `SUBMITTED`, `PARTIAL`, `CANCELLING`, `CANCELLED`, `COMPLETED`,
  `FAILED`, and `UNKNOWN`. The latest submission is selected by created time
  with submission ID as deterministic tie-breaker; the latest active submission
  is the newest record whose state or non-terminal job summary indicates active
  submitted work. Backend-specific job details remain in backend manifests.
- Keep SLURM payloads nested in SLURM models and manifests. Generic
  submitted-operation records identify the backend and point to backend-owned
  detail.
- Extend v6 `slurm/submissions/<submission_id>/manifest.json` with live
  fields: submission status, submitted timestamps, submit host/user, scheduler
  job IDs, raw job ID output, dependency job IDs, command result records,
  failed submission records, scheduler status snapshots, and cancellation
  attempts.
- Add a small SLURM command runner/client abstraction for `sbatch --parsable`,
  `squeue`, `sacct`, and `scancel`, with fake implementations for default
  tests.
- Use `sbatch --parsable` as the required live-submission interface and support
  common outputs such as `123456` and `123456;cluster`.
- Submit `slurm-afterok` jobs up front in topological order. Downstream jobs
  receive `afterok` dependencies on submitted upstream scheduler job IDs.
  Controller-style delayed submission is deferred.
- Write a draft manifest before live submission and update it after every
  successful `sbatch` call.
- Do not automatically cancel jobs after partial afterok submission. Preserve
  the partial record, return nonzero, and tell the user how to cancel.
- Implement `loom status RUN_URI --jobs` as the canonical scheduler-aware
  inspection path. It may persist scheduler snapshots under submission
  metadata, but it must not silently rewrite core Loom statuses.
- Implement `loom cancel RUN_URI --jobs` as the canonical submitted-job
  cancellation path. It mutates Loom status only where safe and never overwrites
  final `SUCCEEDED` or `FAILED` stage outcomes.
- Keep `loom slurm ...` deferred unless a later executor-specific diagnostic
  cannot fit general commands.
- Add an opt-in real SLURM cluster acceptance suite that validates live
  behavior comprehensively enough for maintainers, while default validation
  remains synthetic.
- Use the existing v6 `manifest.json` filename as the canonical submitted
  SLURM manifest path. V7 must not create a second `submission.json` source of
  truth.

## Conflicts And Tradeoffs

- Shared lifecycle consistency vs smaller diff: v7 accepts a cross-cutting
  `SUBMITTED` status change because executor-specific queued states would make
  future submitted backends and general commands less consistent.
- General CLI surface vs executor-specific clarity: v7 favors
  backend-discovering `status --jobs` and `cancel --jobs` over requiring users
  to remember SLURM-specific commands.
- Manifest ownership vs per-job lookup convenience: the manifest remains
  canonical to keep recovery deterministic. Derived per-job files can be added
  only as implementation support.
- Status visibility vs accidental repair: scheduler-aware status records
  snapshots and reports uncertainty, but it does not reconcile core Loom status
  unless an explicit future repair/reconcile policy is added.
- Operational safety vs convenience: v7 fails loudly over active submitted jobs
  and defers force/resubmit.
- Partial submission recoverability vs automatic cleanup: preserving partial
  records and requiring explicit cancellation avoids surprising users and avoids
  hiding partial cleanup failures.
- Fake tests vs cluster realism: fake command runners provide deterministic
  edge-case coverage; opt-in real cluster acceptance proves operational
  behavior against a real scheduler without making default CI cluster-bound.

## Maintainability Assessment

The main maintainability risk is that live SLURM support could become a second
runner with separate lifecycle rules. This plan avoids that by putting shared
`SUBMITTED` status and submitted-operation discovery in generic execution/store
boundaries first, then layering SLURM command execution and manifest extensions
on top.

The second risk is excessive CLI coupling. The plan keeps the CLI as a
presenter over Python APIs. Scheduler parsing, command execution, dependency
mapping, and cancellation result normalization live under
`loom.pipeline.executors.slurm`.

The third risk is accidental state repair or false certainty. Scheduler-aware
status can persist scheduler snapshots, but core Loom status remains
authoritative and is mutated only through lifecycle or explicit cancellation
paths.

The fourth risk is secret leakage through live scheduler artifacts. Each phase
that writes scheduler metadata must preserve the v6 secret boundary and include
tests for redacted or artifact-safe persisted records.

## Extensibility Assessment

The shared `SUBMITTED` lifecycle and submitted-operation registry give future
submitted executors a common foundation. Container, cloud batch, or remote
submission backends can expose the same generic status/cancel discovery surface
while keeping backend-specific state nested in their own manifests.

The submitted-operation registry is intentionally small and backend-neutral. It
standardizes discovery, ordering, active/terminal predicates, and manifest
pointers without importing SLURM job semantics into generic execution or
run-store modules.

The SLURM command runner boundary is also a future extension point. Reliability,
cleanup, retry, and status policies can consume command result records and
status snapshots without moving subprocess calls into generic execution or CLI
modules.

The v6 logical job key model remains the stable bridge between plan semantics
and scheduler job IDs. Later run catalogs, retry logic, cleanup, retention, and
job arrays can index or derive sidecars from the manifest without replacing the
source of submitted-job identity.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Shared `SUBMITTED` status is cross-cutting | Consistent executor lifecycle is more valuable than keeping submitted state hidden in SLURM metadata. | A second submitted backend shows `SUBMITTED` is too coarse, or status/resume semantics become ambiguous. |
| Status inspection records scheduler snapshots but does not reconcile core statuses | Avoids silent repair and false certainty from stale or incomplete scheduler data. | A future explicit repair/reconcile command or v16 reliability policy needs controlled mutation. |
| No force/resubmit over active jobs | Duplicate submitted work can corrupt run-store state and artifacts. | Users need safe resubmission after partial or stale submitted jobs. |
| No automatic cleanup after partial submission | Automatic cancellation can surprise users and can partially fail. | Cleanup/retry policy is designed with explicit user intent and recovery tests. |
| Manifest is canonical for submitted-job identity | Keeps recovery and cancellation deterministic for v7. | Very large DAGs, job arrays, or catalog indexing require derived sidecars. |
| Real-cluster acceptance is extensive but not a certification matrix | SLURM sites differ too much for one suite to certify every policy or accounting configuration. | A dedicated CI cluster or site-specific acceptance profiles become available. |

## Plan Quality Gate

- Status: passed
- Required reviewer: `loom_plan_reviewer`
- Required before: creating any v7 phase execution plan or starting Phase 1
  implementation
- Review focus:
  - whether `SUBMITTED` is correctly scoped as shared Loom lifecycle state and
    not scheduler-specific state;
  - whether the generic submitted-operation registry is sufficient for
    backend-neutral status and cancellation without overfitting to SLURM;
  - whether scheduler status snapshots supplement, rather than silently
    rewrite, core Loom status;
  - whether the manifest schema extensions preserve v6 logical job keys and
    secret-safety guarantees;
  - whether partial afterok submission and cancellation semantics are durable,
    explicit, and safe;
  - whether the phase order isolates cross-cutting state work before live
    scheduler behavior;
  - whether CLI, execution, run-store, diagnostics, and SLURM import boundaries
    are preserved;
  - whether package, unit, contract, integration, e2e, and opt-in cluster
    acceptance obligations are adequate;
  - whether accepted debt and revisit triggers are concrete enough for later
    reliability, cleanup, catalog, controller, array, and container work.
- Loop budget:
  - Initial review: used on 2026-05-08; blocking findings were missing
    submitted stage-job startup semantics, inconsistent `submission.json` vs
    `manifest.json` path naming, underspecified submitted-operation registry
    state predicates, and underspecified cancellation mutation outcomes.
  - Gate refinement pass: used on 2026-05-08; refined this plan to add the
    `SUBMITTED -> RUNNING` continuation contract, standardize on
    `manifest.json`, define the generic submitted-operation registry state
    contract, and add a cancellation mutation matrix.
  - Confirmation review: used on 2026-05-08; no blocking findings remained.
- Current gate result: passed. Phase implementation may begin after a
  scope-complete phase execution plan is created.

## Phased Implementation

### Phase 1 - Submitted Lifecycle And Registry Foundations

Status: merged
Branch: `codex/slurm-submitted-lifecycle`
PR: https://github.com/samcantrill/loom/pull/88

Goal:

- Add the shared submitted lifecycle vocabulary and generic submitted-operation
  discovery contract before SLURM live submission uses it.

Scope:

- Add `RunStatus.SUBMITTED` and `StageStatus.SUBMITTED`.
- Update status parsing, serialization, display ordering, transition helpers,
  run-store read/write tests, diagnostics summaries, CLI status output, and
  resume interpretation for the new non-terminal state.
- Add lifecycle helpers for marking runs and stages submitted without implying
  they are running.
- Add generic stage-job continuation validation for `SUBMITTED -> RUNNING`:
  the continuation may accept a submitted prepared attempt only when run URI,
  stage name, attempt, executor/backend identity, and submission metadata match
  the persisted submitted-operation and manifest records.
- Add generic submitted-operation records and run-store helpers for discovering
  latest submission, latest active submission, backend, mode, submission ID,
  manifest path, and active/terminal state.
- Define generic submitted-operation state values and predicates:
  `PREPARED`, `SUBMITTING`, `SUBMITTED`, `PARTIAL`, `CANCELLING`,
  `CANCELLED`, `COMPLETED`, `FAILED`, and `UNKNOWN`; active states are
  `SUBMITTED`, `PARTIAL`, `CANCELLING`, `UNKNOWN`, or any record with
  non-terminal job summary counts; terminal states are `CANCELLED`,
  `COMPLETED`, and pre-job `FAILED`.
- Define deterministic ordering for latest/latest-active selection using
  `created_at` and submission ID tie-breaks.
- Add diagnostics/inspection shapes so ordinary status can show persisted
  submitted state without scheduler queries.

Out of scope:

- No SLURM command runner, `sbatch`, `squeue`, `sacct`, or `scancel`.
- No live submission.
- No scheduler status snapshots.
- No cancellation.

Acceptance criteria:

- Shared status enums and status records round-trip `SUBMITTED`.
- Existing local and subprocess lifecycle behavior remains unchanged.
- Planning/resume treats `SUBMITTED` as non-terminal and not reusable.
- Submitted-operation records are backend-neutral and can point to
  backend-specific manifests without CLI path walking.
- Registry records include schema version, run URI, submission ID, backend,
  mode, state, manifest relative path, timestamps, summary counts, and optional
  backend metadata only.
- Latest and latest-active discovery are deterministic and share one active
  predicate used by submit, status, and cancel.
- `loom stage-job run` can transition a matching submitted prepared attempt to
  `RUNNING` without accepting stale or mismatched submitted state.
- Ordinary `loom status RUN_URI` can display persisted submitted status without
  scheduler access or project imports.
- No generic code imports `loom.pipeline.executors.slurm`.

Test expectations:

- Package: status, execution, stores, diagnostics, and CLI imports remain
  optional-backend-safe.
- Unit: status parsing/display, transition helpers, lifecycle submit writers,
  submitted-operation validation, active/terminal predicates, latest selection,
  submitted stage-job validation, and resume interpretation.
- Contract: run-store submitted-operation read/write/discovery behavior.
- Integration: `loom status` displays submitted run/stage state from persisted
  store records only, and `loom stage-job run` accepts only matching submitted
  prepared attempts before marking them `RUNNING`.
- E2E: status CLI smoke coverage for submitted state and stage-job submitted
  continuation smoke coverage.
- Opt-in: none.

Design impact:

- This is the cross-cutting public lifecycle change and must land before live
  scheduler behavior.

Future compatibility:

- Future submitted executors reuse the same lifecycle and registry.

Alternatives rejected:

- SLURM-only submitted metadata.
- Backend-specific queued lifecycle names.
- Treating scheduler `PENDING` as Loom `RUNNING`.

Debt introduced:

- `SUBMITTED` is intentionally coarse; backend-specific queue/accounting state
  lives in submitted-operation metadata.

Reviewability:

- Review is focused on status/store/diagnostics semantics without scheduler
  command behavior.

Notes:

- This phase should be treated as the primary public status compatibility slice
  for v7.

Completion summary:

- Phase execution plan and PR body are recorded in
  `docs/phases/slurm-submitted-lifecycle.md` and
  `docs/phases/slurm-submitted-lifecycle-pr-body.md`.
- Implemented shared `SUBMITTED` run/stage lifecycle, generic
  submitted-operation registry records and local store discovery, persisted
  submitted-operation status summaries, and guarded `SUBMITTED -> RUNNING`
  stage-job continuation validation.
- Validation before PR opening: `make validate-pr` passed; `make test-summary`
  passed with package 52 passed / 1 skipped, unit 703 passed / 1 skipped,
  contract 61 passed / 2 skipped, integration 33 passed / 7 skipped / 9
  deselected, e2e 22 passed, and config-extra 411 passed / 871 deselected.
- PR #88 targeted `develop` from `codex/slurm-submitted-lifecycle` and was
  squash-merged on 2026-05-08 as merge commit
  `90533a813573c7a3de2501040a02aa606599b128`.
- Final merge gate: PR target verified as `develop`, head verified as
  `codex/slurm-submitted-lifecycle`, GitHub CI `checks` passed, and manager
  pre-submit review found no remaining scope, validation, or PR-body blockers.
- Stack and cleanup: no successor branches were based on Phase 1; the remote
  phase branch was deleted after merge.

### Phase 2 - SLURM Live Command And Manifest Models

Status: merged
Branch: `codex/slurm-live-command-models`
PR: https://github.com/samcantrill/loom/pull/89

Goal:

- Extend v6 SLURM planned submissions into live-submission records and add a
  testable SLURM command runner boundary.

Scope:

- Add SLURM command runner/client abstractions for `sbatch --parsable`,
  `squeue`, `sacct`, and `scancel`.
- Add fake command runners for deterministic tests.
- Add job ID parser support for `123456` and `123456;cluster`, preserving raw
  output separately.
- Extend v6 manifest models with schema-versioned live fields: submission
  status, submitted timestamps, submit host/user, scheduler job IDs, raw
  command output, command return records, dependency job IDs, failed submission
  records, status snapshots, and cancellation attempts.
- Keep `slurm/submissions/<submission_id>/manifest.json` as the canonical
  live manifest path. Do not introduce `submission.json`.
- Add SLURM-specific errors for command absence, nonzero exit, unparseable job
  IDs, capability unavailability, and manifest update failures.
- Add bounded raw-output and redaction policy for persisted scheduler command
  facts.

Out of scope:

- No `loom run` live submission integration.
- No scheduler-aware CLI status.
- No cancellation command behavior.
- No real scheduler calls in default tests.

Acceptance criteria:

- SLURM live records can represent prepared, submitted, partial, failed, and
  cancelled submission outcomes.
- Fake command runners can simulate success, command-not-found, nonzero exit,
  unparseable output, delayed accounting, missing queue data, and partial
  cancellation.
- Raw scheduler output persistence is bounded and secret-safe by default.
- Manifest schemas reject inconsistent live fields such as dependency job IDs
  without corresponding submitted upstream jobs.
- All live submission APIs and registry records refer to the same canonical
  `manifest.json` path.
- SLURM module imports do not require scheduler commands.

Test expectations:

- Package: SLURM module imports without optional scheduler dependencies.
- Unit: job ID parser, command result normalization, fake runner behavior,
  manifest validation, redaction, and error models.
- Contract: manifest schema round-trips and rejects unsafe or inconsistent live
  fields.
- Integration: fake-runner command flows without live `sbatch`.
- E2E: none.
- Opt-in: none.

Design impact:

- Establishes the SLURM adapter boundary for all later live operations.

Future compatibility:

- Later retry, status, cleanup, and cancellation policies can consume the same
  command-result and manifest records.

Alternatives rejected:

- CLI subprocess calls.
- Python SLURM dependencies.
- Raw unstructured manifest append logs.

Debt introduced:

- Fake runners may miss site-specific command quirks until opt-in acceptance
  tests exercise a real cluster.

Reviewability:

- Review is concentrated on pure models, parsers, fakeable command APIs, and
  secret-safe persistence.

Notes:

- Keep command runner APIs under `loom.pipeline.executors.slurm`.

Completion summary:

- Phase execution plan and PR body are recorded in
  `docs/phases/slurm-live-command-models.md` and
  `docs/phases/slurm-live-command-models-pr-body.md`.
- Implemented fakeable SLURM command runner contracts, bounded command result
  persistence, `sbatch --parsable` job ID parsing, live manifest schema version
  2 records, canonical `manifest.json` live read/write helpers, and
  unit/contract/integration coverage.
- Validation before PR opening: `make validate-pr` passed; `make test-summary`
  passed with package 52 passed / 1 skipped, unit 709 passed / 1 skipped,
  contract 63 passed / 2 skipped, integration 35 passed / 7 skipped / 9
  deselected, e2e 22 passed, and config-extra 411 passed / 881 deselected.
- PR #89 targeted `develop` from `codex/slurm-live-command-models` and was
  squash-merged on 2026-05-08 as merge commit
  `bd5564f235bf3015458eb156d283bd044b1ac541`.
- Final merge gate: PR target verified as `develop`, head verified as
  `codex/slurm-live-command-models`, GitHub CI `checks` passed, and manager
  pre-submit review found no remaining scope, validation, or PR-body blockers.
- Stack and cleanup: no successor branches were based on Phase 2; the remote
  phase branch was deleted by the merge operation.

### Phase 3 - Live Single-Job Submission

Status: merged
Branch: `codex/slurm-live-single-job`
PR: https://github.com/samcantrill/loom/pull/90

Goal:

- Make `slurm-single-job` submit one real scheduler job when selected without
  `--dry-run`.

Scope:

- Wire `loom run CONFIG --executor slurm-single-job` to generate or update v6
  artifacts, write a draft manifest, call `sbatch --parsable`, parse the job
  ID, update submitted-operation records, mark the run `SUBMITTED`, and return
  text/JSON submission output.
- Preserve `--dry-run` as the non-submitting preview path.
- Add live-submission preflight for required `sbatch`, writable
  submission/log directories, command-runner capability, and active old
  submitted jobs.
- Return structured errors for missing `sbatch`, nonzero `sbatch`, unparseable
  job IDs, manifest write failures, and active old job guards.
- Ensure the generated single-job script invokes the v6 prepared-run
  continuation path and does not recursively select a submitted executor.

Out of scope:

- No afterok multi-job submission.
- No scheduler-aware status beyond persisted submitted records.
- No cancellation.
- No force/resubmit.

Acceptance criteria:

- Non-dry-run `slurm-single-job` submits exactly one job through the command
  runner and records job ID, raw output, script path, wrapper log paths,
  manifest path, and submitted-operation metadata.
- Missing `sbatch`, failed `sbatch`, or unparseable job IDs return structured
  errors and do not mark the run successfully submitted.
- Re-submission with active old submitted jobs fails loudly.
- CLI text output includes run URI, manifest path, job ID, wrapper log paths,
  and status hint.
- CLI JSON output uses a schema-versioned envelope and does not include
  unredacted secret-bearing values.

Test expectations:

- Package: no new import-time scheduler requirement.
- Unit: single-job submission service, command construction, preflight
  branches, active-job guard, and structured errors.
- Contract: CLI JSON envelope and submitted manifest fields.
- Integration: fake-runner live single-job submission, active-job guard, and
  failure paths.
- E2E: CLI fake-runner smoke for live single-job submission.
- Opt-in: real single-job acceptance coverage is added in Phase 7 once
  status/cancel exists.

Design impact:

- First live operation over v6 artifacts; validates the shared submitted
  lifecycle with one job.

Future compatibility:

- Whole-run container or batch executors can mirror the same submitted-run
  pattern.

Alternatives rejected:

- Adding a separate `loom submit` command.
- Requiring an extra `--submit` flag.
- Replaying unredacted resolved configs.

Debt introduced:

- Final job outcome still requires later scheduler-aware status or the inner
  runner's run-store updates.

Reviewability:

- One-job scope keeps live submission mechanics reviewable before afterok
  partial failure is added.

Notes:

- This phase should not add `squeue`, `sacct`, or `scancel` user behavior even
  if the command runner models already exist.

Completion summary:

- Merged on 2026-05-08 via PR #90, merge commit
  `df04062de0e4fccb74c5c83c6f0f7281a1fa2feb`.
- Added the live `slurm-single-job` submission service, CLI live-result
  output, fakeable command-runner submission path, live manifest updates,
  submitted-operation registry updates, and run `SUBMITTED` persistence.
- Updated SLURM executor descriptors and preflight so live single-job requires
  `sbatch` while `slurm-afterok` remains live-deferred to Phase 4.
- Added unit, contract, integration, and e2e fake-runner coverage for live
  single-job success, unavailable `sbatch`, active submission guards, stable
  CLI JSON/text output, and persisted registry/status facts.
- Validation: `make validate-pr` passed before merge; `make test-summary`
  passed with package 52 passed/1 skipped, unit 714 passed/1 skipped,
  contract 65 passed/2 skipped, integration 37 passed/7 skipped/9 deselected,
  e2e 23 passed, and config-extra 411 passed/891 deselected.
- PR #90 target verified as `develop`, head verified as
  `codex/slurm-live-single-job`, GitHub `checks` completed successfully, and
  manager review found no blocking findings before merge.

### Phase 4 - Live Afterok DAG Submission

Status: merged
Branch: `codex/slurm-live-afterok`
PR: https://github.com/samcantrill/loom/pull/91

Goal:

- Make `slurm-afterok` submit planned `RUN` stages as scheduler-dependent jobs
  in topological order.

Scope:

- Submit all planned `RUN` stage jobs up front with scheduler-native `afterok`
  dependencies among submitted upstream job IDs.
- Mark submitted stages `SUBMITTED` with scheduler metadata, preserving
  `PENDING`, `SKIPPED`, and `BLOCKED` semantics for non-submitted stages.
- Write and update live manifests incrementally after each successful
  `sbatch`.
- Record dependency job IDs after upstream submission and before downstream
  submission.
- On partial submission, preserve submitted job IDs, record the failed job and
  raw error, mark submission `PARTIAL`, return nonzero, and print explicit
  cancellation guidance.
- Enforce active old submitted-job guard for afterok submissions.
- Ensure stage scripts invoke the v6 execution-owned stage-job runner.
- Ensure submitted stage-job startup uses the Phase 1 `SUBMITTED -> RUNNING`
  validation contract and rejects mismatched run URI, stage name, attempt,
  backend, or submission metadata before user stage code.

Out of scope:

- No controller-style just-in-time downstream submission.
- No automatic cancellation after partial submission.
- No scheduler-aware status beyond persisted submitted records.
- No job arrays.
- No force/resubmit.

Acceptance criteria:

- Afterok submissions use scheduler job IDs for dependency flags and logical
  job keys for persisted identity.
- Jobs are submitted in plan topological order.
- Downstream jobs are not submitted when required upstream submitted job IDs are
  missing.
- Partial failure records already-submitted jobs and failed jobs without losing
  recovery data.
- CLI output and JSON clearly distinguish complete submitted and partial
  submitted outcomes.
- Stage `SUBMITTED` records are written only for jobs accepted by `sbatch`.
- Submitted afterok jobs can start from `StageStatus.SUBMITTED` and transition
  to `RUNNING` only through the generic continuation validation contract.

Test expectations:

- Package: unchanged.
- Unit: dependency construction, topological submission order, incremental
  manifest writes, partial submission handling, active-job guard, and stage
  `SUBMITTED` writes.
- Contract: manifest and CLI JSON for successful and partial afterok
  submissions.
- Integration: fake-runner two-stage, branched, and fan-in DAG submissions;
  partial failures; resume-safe submitted records; and submitted stage-job
  startup validation from accepted afterok manifests.
- E2E: CLI fake-runner smoke for afterok success and partial failure.
- Opt-in: real afterok acceptance coverage is added in Phase 7 once
  status/cancel exists.

Design impact:

- Adds the main operational complexity: multi-job dependency submission and
  partial recovery.

Future compatibility:

- Later retries, cleanup, and job arrays can reuse logical-job to scheduler-job
  mappings.

Alternatives rejected:

- Controller mode.
- Automatic rollback cancellation.
- Manifest replacement.
- Job arrays in v7.

Debt introduced:

- Force/resubmit over partial or stale active jobs remains deferred.

Reviewability:

- Review focuses on dependency correctness, incremental persistence, and
  failure behavior.

Notes:

- Fake-runner tests should include partial failure at more than one DAG
  position.

Completion summary:

- Merged on 2026-05-08 via PR #91, merge commit
  `d6c452b2109f09f2b4f77042df0803ba7cda1478`.
- Added live `slurm-afterok` submission with scheduler-ID `afterok`
  dependencies, incremental manifest and submitted-operation persistence,
  accepted-stage `SUBMITTED` records, partial submission JSON/text output,
  live afterok preflight support, and lazy submitted stage-job worker-request
  materialization at startup.
- Added unit, contract, integration, and e2e fake-runner coverage for afterok
  success, dependency wiring, active guards, partial failure, CLI output, and
  submitted stage-job startup.
- Validation: `make validate-pr` passed before merge; `make test-summary`
  passed with package 52 passed/1 skipped, unit 719 passed/1 skipped,
  contract 67 passed/2 skipped, integration 40 passed/7 skipped/9 deselected,
  e2e 25 passed, and config-extra 411 passed/903 deselected.
- PR #91 target verified as `develop`, head verified as
  `codex/slurm-live-afterok`, GitHub `checks` completed successfully, and
  manager review found no blocking findings before merge.

### Phase 5 - Scheduler-Aware Status

Status: merged
Branch: `codex/slurm-scheduler-status`
PR: https://github.com/samcantrill/loom/pull/92

Goal:

- Add general scheduler-aware inspection through `loom status RUN_URI --jobs`.

Scope:

- Add `--jobs` to `loom status`.
- Discover the latest submission through generic submitted-operation records.
- Query SLURM through backend APIs using run-store final state first, `sacct`
  final accounting data second, `squeue` active queue data third, and manifest
  state last.
- Persist status snapshots under submission metadata without rewriting core
  run/stage statuses.
- Map scheduler states to Loom-facing job status summaries while keeping raw
  SLURM state in backend metadata.
- Report uncertainty, missing command capability, stale data, conflicts,
  dependency-blocked jobs, and worker-never-started cases in text and
  schema-versioned JSON output.

Out of scope:

- No cancellation.
- No scheduler query for ordinary `loom status`.
- No repair/reconcile mutation of core statuses.
- No retry classification or retry execution.

Acceptance criteria:

- `loom status RUN_URI` remains scheduler-free by default.
- `loom status RUN_URI --jobs` shows run-store status, stage status, job IDs,
  scheduler state, exit code where available, dependency state, log paths, and
  uncertainty warnings.
- Missing `sacct` or delayed accounting does not fail when queue or manifest
  data can explain uncertainty.
- Missing required status commands for a requested status operation produce
  clear structured diagnostics.
- Scheduler snapshots are persisted in backend metadata and are artifact-safe.
- Core Loom run/stage status is not silently rewritten by status inspection.

Test expectations:

- Package: CLI status remains import-light.
- Unit: scheduler state mapping, precedence, uncertainty, snapshot
  serialization, and missing-capability branches.
- Contract: status JSON schema with job data and warnings.
- Integration: fake `sacct`/`squeue` scenarios for final, active, missing,
  stale, contradictory, dependency-blocked, and worker-never-started data.
- E2E: CLI fake-runner status for submitted, running, completed, failed,
  dependency-blocked, cancelled, and unknown jobs.
- Opt-in: real status acceptance coverage is added in Phase 7.

Design impact:

- Integrates scheduler facts while preserving Loom state authority.

Future compatibility:

- Reliability and catalog work can consume persisted scheduler snapshots.

Alternatives rejected:

- Scheduler queries by default.
- Scheduler state as primary Loom status.
- Silent core-state repair from status inspection.

Debt introduced:

- Core stage status may remain `SUBMITTED` while scheduler snapshots report a
  terminal pre-worker failure.

Reviewability:

- Review can focus on read/inspect semantics without cancellation side effects.

Notes:

- Status output must communicate uncertainty explicitly rather than inferring
  success from missing scheduler data.

Completion summary:

- Phase execution plan and PR body are recorded in
  `docs/phases/slurm-scheduler-status.md` and
  `docs/phases/slurm-scheduler-status-pr-body.md`.
- Implemented `loom status RUN_URI --jobs` for the latest submitted SLURM
  operation, with run-store/`sacct`/`squeue`/manifest precedence, job-level
  text and JSON output, status snapshot persistence in the live manifest,
  compact submitted-operation backend metadata, and explicit warnings for
  uncertainty, stale data, conflicts, dependency-blocked jobs, and
  worker-never-started cases.
- Ordinary `loom status RUN_URI` remains scheduler-free, and status inspection
  does not rewrite core run or stage statuses.
- Validation before merge: `make validate-pr` passed with default 895 passed /
  17 skipped / 10 deselected, config-extra 412 passed / 920 deselected, and
  build succeeded; `make test-summary` passed with package 52 passed / 1
  skipped, unit 724 passed / 1 skipped, contract 69 passed / 2 skipped,
  integration 43 passed / 7 skipped / 10 deselected, e2e 32 passed, and
  config-extra 412 passed / 920 deselected.
- PR #92 targeted `develop` from `codex/slurm-scheduler-status` and was
  squash-merged on 2026-05-08 as merge commit
  `e7fe5e48a78c80f00a448dcc03d9245b3f3a51ea`.
- Final merge gate: PR target verified as `develop`, head verified as
  `codex/slurm-scheduler-status`, GitHub CI `checks` passed, and manager local
  review found and resolved the `sacct` state normalization edge for values
  such as `CANCELLED by 123`.
- Stack and cleanup: no successor branches were based on Phase 5; the remote
  phase branch was deleted by the merge operation.

### Phase 6 - Submitted-Job Cancellation

Status: merged
Branch: `codex/slurm-job-cancellation`
PR: https://github.com/samcantrill/loom/pull/93

Goal:

- Add general submitted-job cancellation through `loom cancel RUN_URI --jobs`.

Scope:

- Add `loom cancel RUN_URI --jobs` and schema-versioned text/JSON output.
- Discover the latest active submission by default.
- Add specific submission ID selection if the Phase 1/5 registry plumbing
  already supports it cleanly; otherwise document the omission and leave exact
  selection to a follow-up.
- Use SLURM `scancel` through backend APIs for non-terminal submitted jobs.
- Record per-job cancellation attempts and outcomes.
- Return nonzero on partial cancellation.
- Mark run/stages `CANCELLED` only where safe and never overwrite final
  `SUCCEEDED` or `FAILED` stage outcomes.
- Skip completed or otherwise terminal jobs and report that decision.
- Implement this cancellation mutation matrix:

| Outcome | Run status mutation | Stage status mutation | Manifest/registry result | Exit behavior |
| --- | --- | --- | --- | --- |
| Full cancellation of all non-terminal targets | Mark run `CANCELLED` only when no submitted jobs remain active and no final failed stage status would be overwritten. | Mark submitted stages `CANCELLED` only when their job is cancelled and the stage is not already `SUCCEEDED` or `FAILED`. | Record every per-job cancellation and mark registry `CANCELLED`. | Exit 0. |
| Partial cancellation | Do not mark the run fully `CANCELLED`. | Successfully cancelled submitted stages may become `CANCELLED`; failed or unknown targets remain `SUBMITTED` or their current non-terminal state. | Record per-job outcomes and keep registry active as `PARTIAL` or `UNKNOWN`. | Return nonzero. |
| Unknown scheduler outcome | Do not mutate core run status. | Do not mutate stage status unless a target is proven cancelled. | Record uncertainty and keep registry active. | Return nonzero or structured warning according to whether the requested cancellation failed. |
| Already terminal target | Do not overwrite final run status. | Leave `SUCCEEDED`, `FAILED`, or already `CANCELLED` stages unchanged. | Record skipped terminal target; update registry only if no active jobs remain. | Exit 0 when no requested active target failed. |
| Missing `scancel` or command-runner failure before any target action | No core status mutation. | No stage status mutation. | Record command failure when a manifest can be updated; registry remains active. | Return nonzero structured error. |

Out of scope:

- No cancellation of older historical submissions by default.
- No automatic cancellation after partial submission.
- No retry loop for failed `scancel` calls.
- No cleanup/delete operation.

Acceptance criteria:

- Cancellation targets known non-terminal jobs from the latest active
  submission.
- Completed jobs and final `SUCCEEDED` or `FAILED` stages are left alone.
- Partial cancellation is visible in output, JSON, and persisted records.
- Cancellation cannot claim full success when some jobs remain active or
  unknown.
- Missing `scancel` for a requested cancel operation fails clearly.
- The cancellation mutation matrix is covered by unit, contract, and
  integration tests.

Test expectations:

- Package: CLI cancel imports remain optional-backend-safe.
- Unit: target selection, safe status mutation, cancellation result mapping,
  terminal-job skipping, partial outcomes, unknown outcomes, missing-command
  outcomes, and every cancellation mutation matrix row.
- Contract: cancellation JSON and manifest cancellation records.
- Integration: fake `scancel` success, partial failure, missing command, and
  terminal-job skip scenarios.
- E2E: CLI fake-runner cancellation smoke.
- Opt-in: real cancellation acceptance coverage and cleanup behavior are added
  in Phase 7.

Design impact:

- Adds the main mutating scheduler operation after status semantics are stable.

Future compatibility:

- Cleanup and retry policies can build on per-job cancellation records.

Alternatives rejected:

- Best-effort output-only cancellation.
- Cancellation of all historical submissions by default.
- Automatic cleanup after partial submission.

Debt introduced:

- No automatic cleanup workflow or retry loop for failed `scancel` calls.
- Specific submission selection may be deferred if it complicates the first
  safe cancellation path.

Reviewability:

- Review can focus on explicit mutation and partial-failure safety.

Notes:

- Cancellation output should be conservative and avoid claiming a run is fully
  cancelled unless every target job outcome supports that claim.

Completion summary:

- Phase execution plan and PR body are recorded in
  `docs/phases/slurm-job-cancellation.md` and
  `docs/phases/slurm-job-cancellation-pr-body.md`.
- Implemented `loom cancel RUN_URI --jobs` for the latest active submitted
  SLURM operation, with per-job `scancel`, schema-versioned JSON/text output,
  live-manifest cancellation attempts, submitted-operation backend metadata,
  terminal-target skips, partial/unknown outcomes, and nonzero exit behavior
  for failed requested cancellation.
- Core status mutation remains conservative: successfully cancelled non-final
  stages may become `CANCELLED`; full cancellation can mark the run
  `CANCELLED`; final `SUCCEEDED` or `FAILED` stages are never overwritten; a
  final failed stage prevents marking the run `CANCELLED`.
- Exact submission ID selection, retries, cleanup, and real-cluster
  cancellation acceptance remain deferred to follow-up or Phase 7 scope.
- Validation before merge: `make validate-pr` passed with default 911 passed /
  17 skipped / 10 deselected, config-extra 412 passed / 936 deselected, and
  build succeeded; `make test-summary` passed with package 52 passed / 1
  skipped, unit 731 passed / 1 skipped, contract 72 passed / 2 skipped,
  integration 45 passed / 7 skipped / 10 deselected, e2e 36 passed, and
  config-extra 412 passed / 936 deselected.
- PR #93 targeted `develop` from `codex/slurm-job-cancellation` and was
  squash-merged on 2026-05-08 as merge commit
  `c2c45c23b13a4082019342ccef8e36f2b6a55a7c`.
- Final merge gate: PR target verified as `develop`, head verified as
  `codex/slurm-job-cancellation`, GitHub CI `checks` passed, and manager local
  review found no blocking issues after the registry active-summary edge case
  was fixed before PR opening.
- Stack and cleanup: no successor branches were based on Phase 6; remote and
  local branch/worktree cleanup were handled after merge.

### Phase 7 - Preflight, Opt-In Cluster Acceptance, Docs, And Hardening

Status: pending
Branch: `codex/slurm-acceptance-hardening`
PR: pending

Goal:

- Complete operational validation, documentation, and final edge-case coverage
  for the v7 live SLURM feature set.

Scope:

- Add or finish preflight check IDs for required `sbatch`, optional
  `squeue`/`sacct`, `scancel` when cancellation is requested,
  profile-required fields, writable submission/log directories, active old
  submissions, and command-runner capabilities.
- Add an env-gated, skipped-by-default real SLURM acceptance suite that
  maintainers can run on a cluster.
- Cover at least live single-job success, live afterok two-stage success,
  afterok branch or fan-in dependency behavior where practical, status during
  queued/running work and after completion, a tiny intentional worker failure
  or dependency-blocked path, cancellation of a queued or sleeping job, wrapper
  stdout/stderr log creation, manifest job/dependency/snapshot/cancellation
  records, and ordinary run-store status/output/artifact/failure metadata
  written by real jobs.
- Keep fake-command tests as the deterministic suite for hard-to-force
  scheduler failures such as missing commands, unparseable `sbatch`, partial
  submission at a specific DAG node, contradictory `sacct`/`squeue` results,
  and partial `scancel`.
- Harden docs, examples, structured error messages, JSON schema documentation,
  fake-command e2e coverage, and secret-safety regressions.
- Verify that live manifests, command records, scheduler snapshots,
  cancellation records, CLI output, and generated scripts do not persist
  environment values, unredacted resolved configs, resolver outputs, or raw
  secret-bearing adapter payloads by default.

Out of scope:

- No default real-cluster requirement.
- No promise that every SLURM site supports every optional acceptance case.
- No controller mode, job arrays, retries, cleanup, remote stores, or
  containers.
- No certification matrix for every site-specific SLURM configuration.

Acceptance criteria:

- Default validation remains deterministic, local, and cluster-free.
- Opt-in cluster acceptance tests are clearly documented and impossible to run
  accidentally.
- Acceptance tests can be selected by marker or environment and can skip
  individual cases when a site lacks required optional behavior, while still
  failing loudly for core submit/status/cancel regressions.
- Preflight reports missing `sbatch` as a live-submission error and missing
  optional status commands as warnings unless the requested operation requires
  them.
- Docs explain live submission, dry-run preview, status, cancellation,
  uncertainty, partial submission, active-job guards, and cleanup guidance.
- `make validate-pr` and `make test-summary` expectations are clear for PR
  preparation.

Test expectations:

- Package: full import suite.
- Unit: remaining preflight, error, schema, output, and redaction branches.
- Contract: final CLI and manifest schema contracts.
- Integration: fake-command coverage for the full submit/status/cancel flow.
- E2E: local fake-command CLI flows for single-job, afterok, partial failure,
  status, and cancellation.
- Opt-in: real SLURM cluster acceptance suite gated by explicit environment
  variables or markers.

Design impact:

- Consolidates operational evidence and user-facing documentation after core
  behavior lands.

Future compatibility:

- Gives v8 catalog work inspectable submitted, partial, cancelled, and failed
  run records, and gives later SLURM features a real-cluster acceptance-test
  scaffold.

Alternatives rejected:

- Requiring real SLURM in default CI.
- Limiting real validation to a tiny smoke check.
- Omitting real-cluster validation entirely.

Debt introduced:

- Real-cluster coverage is extensive but still not a certification matrix for
  every SLURM site.

Reviewability:

- Final phase is documentation, evidence, and edge-case hardening rather than
  new core behavior.

Notes:

- Real-cluster tests must include timeouts and cleanup safeguards suitable for
  shared clusters.

Completion summary:

- TBD

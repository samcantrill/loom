# Phase 5 Execution Plan: Contract Hardening, Examples, And Documentation

## Metadata

- Status: in_progress
- Feature focus: Stage Worker
- PR title: `Stage Worker - Phase 5: Contract Hardening, Examples, and Documentation`
- Branch: `codex/subprocess-contract-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/subprocess-contract-hardening`
- Phase execution plan path: `docs/phases/subprocess-contract-hardening.md`
- Full plan: `docs/implementation-plans/implementation-plan-v5.md`
- Source phase: Phase 5 - Contract Hardening, Examples, And Documentation
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase PR, merge-eligible when automated review, validation, CI, and scope gates pass
- Workflow path: expanded path, because this phase spans final cross-component behavior, runnable examples, public docs, and final v5 evidence
- Successor dependency notes: none inside v5. Later roadmap work may build on the documented deferred executor/reliability owners.
- Plan quality gate: passed on 2026-05-07 after initial review, one refinement pass, and confirmation review
- Plan quality gate loop budget: consumed as recorded in `docs/implementation-plans/implementation-plan-v5.md`
- Draft pass: completed by manager on 2026-05-07
- Refine pass: completed by manager on 2026-05-07 for expanded path
- Setup limitations: none; Phases 1 through 4 are merged on `develop`, and this worktree was created from `develop`.
- Blockers: none known

## Objective

Finish v5 by hardening the local/subprocess worker contract with missing edge-case tests, adding local synthetic examples for subprocess execution and direct workers, and documenting trust, privacy, and deferred executor/reliability behavior clearly.

## Full-Plan Context

Phases 1 through 4 introduced durable prepared attempts, direct `loom stage run` workers, serial subprocess execution, selected-subprocess preflight, and concise failure diagnostics. Phase 5 should not change those contracts. It converts the final behavior into broader tests, runnable examples, and explicit documentation so later executor phases can extend the same boundaries.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 4 PR #80 is merged
- Why this base branch is correct: all earlier v5 phases are merged into `develop`
- Retarget/rebase plan after predecessor merge: none
- Branch cleanup constraints: branch may be deleted after the Phase 5 PR is merged because no v5 successor depends on it

## Source Phase Summary

- Goal: harden cross-component behavior, provide examples, and document deferred later-version behavior and trust assumptions.
- Required scope: local/subprocess equivalence tests, worker result validation, failure normalization, missing/invalid/mismatched/stale result coverage, signal-aware process failures, redacted metadata evidence, diagnostics compatibility, runnable examples for local/subprocess success, subprocess failure diagnostics, direct `loom stage run`, and docs for no-sandboxing, trusted configs, privacy defaults, full-environment deferral, retries/timeouts/parallelism/SLURM/container/plugins/remote stores/cleanup/attempt archives/locking deferrals.
- Required checkpoints: comprehensive evidence without adding real external systems or changing runtime semantics.

## Current Source And Harness Findings

- Existing subprocess unit tests cover command construction, success handoff, missing result, structured-success/process-failure conflict, signal metadata, and failed worker result wrapping.
- Gaps that remain in subprocess unit coverage: invalid worker result payloads, inner run URI/stage/attempt mismatches, process launch exceptions, and explicit redacted process metadata assertions.
- Existing integration coverage confirms subprocess success/failure finalization, but local/subprocess equivalence and diagnostics inspection can be made more explicit.
- Existing examples are cataloged by `examples/**/example.yaml`; smoke examples execute through `tests/integration/docs/test_v0_python_examples.py`.
- Existing docs mention subprocess execution and deferred behavior across execution, preflight, CLI, testing, reliability, SLURM, container, remote-store, and run-store specs; Phase 5 should tighten focused sections rather than rewrite whole docs.

## In-Scope Work

- Add missing unit tests for subprocess invalid, mismatched, stale, launch-error, signal, and redaction behavior.
- Add contract/integration assertions for local/subprocess equivalence, parent/worker finalization boundaries, and diagnostics compatibility.
- Add runnable local synthetic examples for:
  - local versus subprocess success behavior;
  - subprocess stage failure followed by status/log diagnostics;
  - direct `loom stage run` against a prepared stage.
- Add example manifests and smoke-test coverage through the existing example harness where practical.
- Document current v5 subprocess guarantees, no sandboxing guarantee, trusted authored config assumptions, privacy/redaction defaults, and full environment persistence deferral.
- Document later-version owners and revisit triggers for retries, timeouts, worker pools/parallel scheduling, SLURM, containers, plugins, remote stores, cleanup/retention, attempt archive directories, and stronger locking.

## Out-of-Scope Work

- Implementing deferred behavior such as retries, timeouts, parallel scheduling, SLURM, containers, remote stores, cleanup, stronger locks, or attempt archives.
- Real cluster/container examples requiring external systems.
- Network or downstream-project-dependent examples.
- Public API redesign or CLI schema redesign.
- Changing subprocess command construction or parent finalization semantics except to fix concrete test-discovered defects.

## Assumptions

- Synthetic example stages can live under `examples/pipelines/subprocess-run/` and be imported by adding the example directory to `sys.path`, matching existing local examples.
- Direct worker examples may use public Python APIs to prepare a durable attempt, then invoke the public `loom stage run` CLI command.
- Missing/invalid/stale worker result diagnostics can be covered with injected `process_runner` functions and direct store writes without launching real broken subprocesses.
- Existing redaction helpers are the authority for privacy defaults; Phase 5 should assert use, not introduce a new redaction policy.

## Design Impact

- Maintainability: hardening tests capture edge cases that future executor adapters must preserve.
- Extensibility: examples and docs make the local/subprocess bridge explicit for later scheduler/container work.
- Domain neutrality: examples use numeric/text synthetic stages only.
- Reviewability: final v5 docs/tests are separated from earlier implementation phases.

## Future Compatibility

- Tests should describe behavior through public/store-facing contracts, not private subprocess implementation details except where injected process-runner helpers are already established.
- Examples should remain local and deterministic so later remote/SLURM/container examples can be added as separate manifests.
- Deferred behavior docs should name owners and revisit triggers so future plans can implement without re-litigating v5 scope.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Implement retries/timeouts/parallelism while hardening | Explicitly deferred and too broad for the final hardening phase. |
| Add examples that require shell-installed `loom` | Existing smoke harness runs Python scripts from the source tree. |
| Use real broken Python executables or PATH manipulation for all edge cases | Injected process runners are deterministic and avoid environment fragility. |
| Fold subprocess examples into local-run examples only | Separate examples make subprocess behavior and direct worker workflow discoverable. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Examples remain local and synthetic | Phase 5 must not require external systems. | Later executor phases add scheduler/container/remote-store support. |
| Direct worker example prepares attempts through Python APIs | There is no standalone public CLI command for preparing one attempt. | A future diagnostics or worker-preparation CLI command is introduced. |
| Attempt archive examples remain documentation-only | Retry/retention layout is deferred. | Retry or attempt-retention roadmap begins. |

## Reviewability

- Expected PR size and shape: medium tests/docs/examples PR, with little or no production code unless a concrete hardening bug is found.
- Files and areas to inspect: subprocess executor tests, integration diagnostics/pipeline tests, new examples, example catalog manifests, execution/preflight/testing/reliability docs, and phase plan/PR body.
- Scope-control checks: no deferred behavior implemented, no external dependency, no real cluster/container/network requirement, no public API redesign, and no broad doc rewrites beyond v5 ownership.

## Implementation Steps

1. Add missing unit/contract/integration hardening tests around subprocess worker result validation, failure normalization, redaction, local/subprocess equivalence, and diagnostics compatibility.
2. Add runnable examples and manifests under the existing examples catalog.
3. Update focused docs for v5 guarantees, trust/privacy, and deferred behavior owners/revisit triggers.
4. Run focused tests and full validation, then prepare the final PR body.

## Test Plan

### Package Suite

- Status: required
- Expected paths: package import/export tests if examples or docs reveal a missing public import.
- Required assertions or deferral reason: final public imports remain stable; no new heavyweight dependencies are introduced.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/executors/test_subprocess_executor.py` and adjacent execution model/attempt tests as needed.
- Required assertions or deferral reason: invalid worker result, inner run URI/stage/attempt mismatches, launch exceptions, signal facts, redacted process metadata, and failure details.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_executor_contract.py` and `tests/contracts/test_stage_worker_contract.py` if needed.
- Required assertions or deferral reason: local/subprocess executor protocol compatibility and parent/worker finalization boundary evidence remain explicit.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_subprocess_executor_integration.py`, `tests/integration/diagnostics/test_cli_status_logs.py`, and `tests/integration/docs/test_v0_python_examples.py`.
- Required assertions or deferral reason: local/subprocess equivalence, subprocess failure status/log/failure inspection, examples smoke, and durable reconstruction compatibility.

### E2E Suite

- Status: required
- Expected paths: `tests/e2e/test_cli_core.py` or example smoke coverage.
- Required assertions or deferral reason: existing local/subprocess success and failure CLI smoke remains the e2e obligation; add only if a hardening gap is not covered elsewhere.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected beyond existing optional dependency markers.
- Required assertions or deferral reason: Phase 5 uses local deterministic tests only and does not require SLURM, containers, remote stores, plugins, network, or downstream projects.

## Risks

- Example scripts can become slow if they run too many full subprocess pipelines. Keep smoke scripts small and deterministic.
- Direct worker examples can accidentally imply a stable public "prepare attempt" CLI. Document that preparation is Python API driven in v5.
- Broad docs can blur current support and future scaffolding. Separate "current v5" from "deferred" sections.
- Additional contract tests can become platform-fragile if signal semantics depend on OS behavior. Use injected process results for signal facts.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/contracts/test_executor_contract.py tests/contracts/test_stage_worker_contract.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/diagnostics/test_cli_status_logs.py tests/integration/docs/test_v0_python_examples.py tests/e2e/test_cli_core.py
uv run pyright tests/unit/loom/pipeline/executors/test_subprocess_executor.py tests/integration/pipeline/test_subprocess_executor_integration.py tests/integration/diagnostics/test_cli_status_logs.py tests/integration/docs/test_v0_python_examples.py examples
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by manager on 2026-05-07.
- Final phase execution plan: refined by manager on 2026-05-07 before implementation to identify concrete hardening gaps, example scope, documentation boundaries, and deferred behavior ownership.
- Implementation summary: TBD
- Implementation validation: TBD
- Refinement summary: TBD

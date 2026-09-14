# Phase 1 Execution Plan: Stage-Owned Target Validation

## Metadata

- Status: merged
- Roadmap stage and phase: Stage 38, Phase 1
- Manifest: `docs/roadmap/stage-38/implementation-plan.md`
- Branch: `agent/stage-38-p1-stage-target-validation`
- Worktree: `stage-38-p1-stage-target-validation` under the recorded root
- Base revision: `f4b1ae76f63d33f2d481916bf36147f372e6225d`
- PR target: develop
- PR title: `fix(cli): preserve stage-owned data during target validation`
- Dependencies: independent upstream audit accepted; no predecessor PR
- Workflow path: bounded implementation; independently reviewed as required
- Blockers: none

## Objective And Context

Make `loom validate --check-targets` check outer stage factories and other
applicable generic targets without independently constructing nested targets
owned by a stage. This is FR-1 and preserves FR-4 compatibility. The old local
guard is evidence of the needed projection, not a replacement file to copy.
Resource mapping, GPU grammar remediation, and process timeouts are later work.

## Current Source And Harness

Primary source is `src/loom/cli/validate.py`: `handle` composes and statically
validates before checking stage factories and generic targets. The first
checker consumes the pipeline spec; the second currently receives the complete
resolved config with only outer factory skip paths. Locked Weave traverses
children even under a skipped path. Pipeline `stage_factory.py:construct_stage`
passes factory init values to the outer constructor without generic nested
instantiation. Stage specs freeze plain data, so init mappings need not be
mutable dict instances.

Existing orchestration tests are `tests/unit/loom/cli/test_validate.py`; public
CLI/composition coverage is `tests/e2e/test_cli_core.py`. Existing harmless
constructor markers live in `tests/support/config_samples.py`. Inspect those
seams before adding a new fixture. The existing default and JSON/text warning
tests must retain their meaning. Use the phase worktree's locked Python 3.12
environment, not the dirty checkout or the active rphys environment.

## Scope

In scope: the smallest validation projection, focused unit and public CLI tests,
small supporting constructor fixtures if needed, and current configuration/CLI
documentation. The manager owns Stage 38 planning/manifest metadata; the executor
updates only this card's workflow/completion receipt.

Manager-qualified gate correction A-11 also owns only the no-mutation assertion
block in `tests/integration/queue/test_slurm_ready_stage.py:_exercise_mixed_route_run`.
The supported daemon cycle refreshes scheduler evidence concurrently; hold its
existing `_cycle_lock` across the before/request/after assertion, preserving
full equality checks. No queue product behavior, new synchronization API, or
other SLURM assertions are in scope for this correction.

Out of scope: Weave changes, stage execution, recursive construction of init,
pipeline parsing redesign, new registry, dependency or durable schema changes,
resource/timeout implementation, unrelated source formatting, and modifications
to the original checkout.

Assume authored config is trusted code and target checking is explicit consent
to construction. This is an ownership correction, not sandboxing or globally
side-effect-free validation. User constructors remain free to perform their own
work; Loom must not run nested stage-owned constructors independently.

## Fixed Contracts And Private Discretion

- Outer factory checking remains pipeline-owned and occurs before generic
  checking. Invalid outer imports, constructor arguments, and non-Stage results
  still fail with existing error/warning behavior.
- Generic traversal sees neither pipeline metadata nor stage factory/init and
  stage config target graphs. Those are data under the existing stage contract.
- Generic targets outside these owned subtrees remain checked. Do not disable
  the generic checker or drop unrelated config to obtain a green test.
- Input composed configuration is unchanged by the projection. Factory init
  reaches the outer constructor with existing frozen/plain mapping semantics.
- The checked count is exactly the outer factories plus applicable generic
  target blocks, not omitted nested stage-owned blocks. Warning code, opt-in
  consent boundary, JSON envelope, exit codes, and static default stay stable.
- No run is submitted, stage run method invoked, or run directory created by
  this change. Public imports and composed/persisted configuration remain intact.
- Private helper names, detached-copy strategy, and marker-fixture placement
  are implementation discretion. Prefer the smallest readable projection and
  existing fixture mechanisms; a new generalized traversal abstraction is not
  required for this single CLI consumer.

## Proportionality

Reuse the two current checkers and add only the boundary projection between
composition and generic checking. Skipping the outer path alone was proven
insufficient; changing Weave traversal globally would change unrelated consumers.
Do not add arbitrary malformed internal object cases. Public authored data and
the generic checker boundary are the supported producers under test.

## Invariant Ownership

| Invariant | Owner | Reachable boundary / consequence | Coverage |
| --- | --- | --- | --- |
| Stage-owned target graphs remain data | CLI projection | Authored nested targets otherwise run early or with wrong semantics | Public CLI markers in all three owned locations |
| Outer factory and generic targets are still checked | Existing pipeline and Weave checkers | Overbroad filtering hides invalid unrelated targets | Valid marker counts, invalid outer, invalid generic |
| Config remains unchanged | Projection | Shared composed data is reused for later interpretation | Nested equality before/after checking |
| Warnings and counts describe actual behavior | CLI result owner | User misunderstands consent or targets checked | JSON count/warning and existing text/default tests |

## Implementation Slices

1. Inspect the current composition/checker path and existing marker fixtures;
   establish one failing public regression on the current baseline.
2. Add the minimal detached validation view and wire only generic checking to it.
3. Cover metadata, stage config, and init nesting; verify generic targets,
   invalid outer factories, immutable init semantics, and no input mutation.
4. Update CLI/config docs to describe which targets run on opt-in consent and
   which remain stage-owned data. Remove contradictory "all targets" wording
   only where this command's behavior is documented.
5. Run the targeted lanes and stable final gates; commit the implementation and
   complete the phase receipt without preparing a PR.

## Test And Validation Plan

| Suite | Requirement | Minimal assertions |
| --- | --- | --- |
| Unit | required | Projection does not mutate inputs; orchestration order, errors, warning/count contracts |
| E2E | required | Authored YAML through public CLI, real harmless constructors; nested targets inert, outer and unrelated targets checked |
| Package/contract | final gate | No new public exports/dependencies; existing stage semantics remain compatible |
| Integration | affected CLI tests and final gate | Existing composition/checking remains functional |
| Live runtime | not needed for this phase | No execution or host-runtime behavior changes |

Targeted commands:

    .venv/bin/python -m pytest -q tests/unit/loom/cli/test_validate.py tests/e2e/test_cli_core.py

Final commands:

    make validate-pr
    make test-summary

Run final gates once the validation-relevant tree is stable. Record exact commit
or tree evidence and summary path; do not reuse old-checkout or baseline receipts
as implementation validation. A local gate failure must be classified before
correcting anything outside this phase.

## Risks, Review, And Stops

Main risks are over-filtering unrelated targets, accidental input mutation,
double construction, altered init semantics, misleading counts, and stale docs.
Independent review must trace the production path and tests, not merely approve
the private helper. Stop for a missing public contract, unavoidable unrelated
changes, source overlap, or a baseline gate failure requiring broader correction.
Do not perform optional hardening or reopen the approved ownership boundary.

## Executor Handoff

Read Current Source And Harness through this heading, plus Metadata and manifest
Shared Constraints. Implement slices 1-5 only after the manager records startup
readiness. You are not alone: do not revert other work. Write only the scoped
CLI/test/doc owners and this card's receipts. Do not delegate, create workflow
sidecars, push/open a PR, review, merge, or remove a worktree. Return commits,
checks, changed paths, and any bounded blocker to the manager.

## Workflow State

- Manager preparation: complete; source, locked baseline, 236-test receipt,
  independent audit dispositions, scope, and executor packet verified
- Expanded planning: no new first-phase product decision
- Implementation: complete
- Pre-submit gate: passed; scope, ownership, source/tests, docs, and fresh
  `make validate-pr` / `make test-summary` receipts verified
- Independent review: passed at PR head `140775dbbd4b29ca0d844f6ce776c7d7a7432897`;
  no blockers or corrections, including A-11 test-only synchronization
- Blocker corrections: 1/3 (A-11 test-only synchronization; manager-owned)
- PR and merge: [PR #277](https://github.com/samcantrill/loom/pull/277), squash
  merged to develop at `133505b12d3e0bea53a42533ec240ff4f1b3562b`

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | Generic checker receives a new top-level mapping without `pipeline`; pipeline checker retains outer construction. CLI source, unit/E2E tests, README and CLI docs changed. A-11 changes only the existing integration test's synchronization. |
| Tests added or updated | Real public CLI marker regression (baseline failed at 7 targets versus expected 4), invalid outer and generic targets, projection non-mutation and orchestration. Targeted CLI: 24 passed. Corrected SLURM integration file: 15 passed. |
| Validated revision/tree state and evidence | `74f117c1ca34e73ae28c60ac689569a18bfa9f5d`: `make validate-pr` passed (Ruff, Pyright, default 2,794 passed, config-extra 157 passed / 3 opt-in runtime skips, build); `make test-summary` passed (package 122, unit 1,964, contract 300, integration 339, E2E 69, config-extra 157 / 3 skips), evidence `build/test-summary.md`. |
| Validation-relevant changes after evidence | None; only roadmap evidence/receipts updated. |
| PR, review, and merge | PR #277 independently approved with no findings; remotely merged to develop at `133505b12d3e0bea53a42533ec240ff4f1b3562b`. Merged tree is identical to the reviewed head plus approved roadmap receipts. |
| Residual risk and cleanup | Phase worktree and local/remote branch removed. Generated `build` test evidence and `dist` packages retained in `stage-38-integration` under the recorded worktree root. Original dirty checkout preserved. |

The first full gate exposed A-11 (one timestamp race; 2,793 other tests passed).
The correction used the existing cycle lock without weakening record equality,
and both required gates then passed. Earlier interrupted validation had lost
receipts; its remaining owned supervisor was positively quiescent and shut down
through its existing clean-shutdown API. No old receipt was reused as a pass.

The full `pipeline` mapping is excluded from generic construction, rather than
recursively editing three named subtrees. `PipelineSpec`/`StageSpec` reject
unknown orchestration fields; accepted metadata, output metadata, resource
attributes, placement, config, and init values are plain pipeline-owned data.
`docs/features/execution.md` assigns generic Weave construction outside pipeline
stage specs and stage construction to the existing pipeline owner. No generic
construction consumer is removed inside this boundary. Unrelated top-level
targets retain their original values and generic traversal; the projection itself
does not mutate composed data.

Manager takeover is limited to the executor's remaining documentation, missing
gate evidence, and commit: the resumed executor's sandbox failed before command
execution, while parent commands remained available. No implementation was
discarded or restarted and no second executor was spawned.

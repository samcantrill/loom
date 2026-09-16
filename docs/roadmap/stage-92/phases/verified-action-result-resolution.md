# Phase 2: Verified Action Result Resolution And Fresh Execution

## Metadata And Scope

- Status: in_progress; predecessor gates passed, source-bound execution plan in preparation.
- Base: `32f8d90d4af6ea8f0e4ccb78a024b5dc7de67ed2`.
- U1: PR #331 merged at `a0d29b3fedac7495bbb994e630b07aa41f7cf579`; metadata published and shared synchronization passed at the base above.
- Coordination branch: `agent/stage-92`; use the manifest's clean control and stage worktree paths.
- Branch: `agent/stage-92-p2-verified-action-result-resolution`.
- PR title: `Stage 92 Native Project Contracts And Result Resolution - Phase 2: Verified Action Result Resolution And Fresh Execution`.
- Target: develop; execution context and approved protocol are in the [manifest](../implementation-plan.md).
- Fixed contract owner: native contract sections Native Execution Identity And
  Selection, Delivery Packages And Source Ownership (U2), and Example And
  Validation Contract (U2 rows and Genericity Fixture And Acceptance).

Deliver one native selectable-result lifecycle: a versioned causal execution key
distinct from legacy fingerprints; actual committed input identities; qualified
code/assets/installation separated from captured graph authorship; fenced claims;
candidate verification and original-result bindings; demand-aware cancellation,
restart and retention; installed verify_result with opaque namespaced reason
codes and artifact-identifying errors; idempotent fresh_stages generation that
does not change scientific keys or replace default results. Preserve whole-target
reconciliation and legacy resume. Successful actions in failed source graphs
remain eligible; failures/corruption never become a cache miss or silent retrain.

Reuse existing authority/coordination/read-model and immutable shared-closure
owners. Keep hashing and installed callbacks outside short database transactions.
Preserve control prerequisites and recheck mutable authority/retention when
binding. No copied producer commits, rphys cache/scheduler, scientific reason-code
enum, result-selection plugin registry or new Weave mechanism.

## Validation And Startup

At startup trace current U1 source and bind exact selectors. Required cases are
owned by the approved contract: changed alias/unrelated branch hit; science,
actual producer, implementation/output contract differences miss; one concurrent
producer; cancellation of original versus final demand; restart; successful
action from failed graph; native integrity and project-semantic rejection;
malformed verdict/code/port handling; default/fresh/replay/conflicting replay;
default result retained after fresh. Reuse the U1 installed text fixture and
existing native lifecycle/retention/publication tests.

Add `tests/integration/queue/test_action_result_resolution.py` and extend affected
fingerprint/resume, reconciled-run, submission/CLI and shared-publication owners.
Use locked Python 3.12 lanes. Final gate: `make validate-pr` and
`git diff --check`, then required independent actual-head review. Native tests do
not replace rphys's changed-installation physical gate.

## Source Binding And Named Startup Question

U1's committed report/context protocol is landed and independently reviewed.
Existing source owners at the selected base:

- `queue/local_daemon_execution.py` reconciles native admissions through
  `RunOrchestrator` into the global ready window and dispatches all placements.
  Its `_cancel` currently installs a run-wide cancellation epoch and fans out
  local, remote and SLURM containment. That path cannot simply run unchanged
  against an action retained by another graph's demand.
- `pipeline/stores/sqlite_authority.py` and the coordinator authority adapters
  own fenced attempt/commit/status mutations. Existing coordination, read models,
  stage-work records and cleanup references own the relevant durable projections.
- `queue/_preparation_operations.py` accepts idempotent intent under a short
  transaction, persists selected installation/capture state, and reconciles
  whole-target preparation/verification. `queue/preparation.py` owns immutable
  preparation codecs. Fresh selection/generation must extend these owners and
  the native RunRequest/CLI projections coherently.
- `queue/resident_readiness.py` already qualifies declared source roots,
  imports, distributions, Python and executor/container identity. Its separate
  project/environment/executor fingerprints are distinct from the captured
  composition. Reuse explicit installed source/asset qualification; never strip
  files heuristically from whole-source evidence.
- `pipeline/planning/fingerprints.py` retains legacy alias/config/source-edge
  audit identity. Add causal action identity alongside it; use existing output
  specs, actual original commit/ref/closure identities and native reuse bindings.
- `queue/_shared_publication.py` owns immutable shared closure retention,
  publication and receipt validation. Preserve original facts and bytes.

One bounded planning refinement is needed before implementation: trace the
smallest native authority/coordinator ownership change that allows a graph to
cancel its demands while an original action producer remains fenced and running
for another graph, and then cancels/settles only at the final demand. Identify
concrete run-epoch, assignment, commit, restart, read-model and retention owners
and the required causal tests. Resolve implementation wiring under the approved
logical claim/result/binding contract; do not add a second scheduler, rewrite
producer identities, narrow supported deployments, or change the fixed protocol.
The refinement may edit only this card and must return a source-backed approach
or a precisely evidenced missing accepted decision.

Manager will complete remaining selectors/implementation steps after this
named question is resolved. No product implementation or U2 validation has run.

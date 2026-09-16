# Phase 2: Verified Action Result Resolution And Fresh Execution

## Metadata And Scope

- Status: pending; U2 requires merged/published/synchronized U1.
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

Implementation/source/validation/review/PR/merge evidence: pending. Select the
actual merged predecessor base and finish the source-bound execution card before
any U2 implementation. Fixed public behavior remains at its approved owner.

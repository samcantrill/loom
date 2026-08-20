# Phase 3 Execution Plan: HTTP Recovery Parity And Renewal Proof

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 24, Phase 3
- Manifest: `docs/roadmap/stage-24/implementation-plan.md`
- Branch: `agent/stage-24-p3-http-recovery-parity-and-renewal-proof`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-24-p3-http-recovery-parity-and-renewal-proof`
- Base revision: `a7afd44153860ba131db7ee26c186cc0188b1497`, current
  `origin/develop`; the branch adopts the unpublished Phase 2 changes through
  blocked-state commit `5194d06fde20ac619c24f2a516c537a494e3b3a3`
- PR target: `develop`
- PR title: `Operational Lifecycle Validation - Phase 3: HTTP Recovery Parity`
- Dependencies: Phase 1 merged; Phase 2 is explicitly blocked and opened no PR
- Workflow path: narrow maintainer-directed replacement phase
- Blockers: none

## Objective And Evidence

Publish the complete Stage 24 Phase 2 behavior only after the supported HTTP
authority path can provide the same expired-controller and expired-attempt facts
as direct SQLite, and after controller-renewal coverage proves exclusivity past
the original lease expiry.

Independent review reproduced a supported-path failure: the central repository
returned both recovery facts, while
`AuthorityClientBackedPerRunAuthorityStore.scan_recovery()` returned an empty
tuple unconditionally. The runner correctly requires those facts before it
records `INTERRUPTED`/`STALE` and starts attempt 2, so HTTP-backed recovery could
never progress. The review also showed that the renewal test used a frozen
clock: it proved renewal calls and shutdown, but not the accepted post-expiry
ownership behavior.

Phase 2 otherwise passed its focused tests, `make validate-pr`, and
`make test-summary` with 2,285 passes. Phase 3 adopts that implementation; it
does not reopen output-commit lineage, migration, corruption repair, hard-loss,
or authority-loss design.

## Scope And Fixed Contracts

In scope:

- Add one run-level recovery-scan HTTP path using the existing
  `AuthorityProtocolOperationKind.RECOVERY_SCAN`, `RecoveryRecord`, protocol
  result field, and `AuthorityRepository.scan_recovery()` behavior.
- Route the client response through
  `AuthorityClientBackedPerRunAuthorityStore.scan_recovery()` with the existing
  response/version/error handling.
- Prove through the real service client/adapter boundary that an expired
  controller and each expired active attempt are returned, while live leases
  are omitted.
- Prove the public HTTP-backed resume path can consume those facts and reach
  recovery before attempt 2 if the existing harness can do so without adding a
  second unrelated orchestration surface. At minimum, contract-test adapter
  parity and retain the existing runner recovery test that consumes the store
  protocol.
- Replace the frozen renewal clock with deterministic mutable time and prove a
  competitor remains rejected after the initial lease expiry but before the
  renewed expiry. Retain proof that renewal stops and the lease is released.
- Run affected protocol, client, service, adapter, renewal, recovery, and
  operational suites, then the full repository gates and receipt.

Out of scope:

- New recovery records, lifecycle states, database schema, public recovery CLI,
  PID inspection, automatic stealing, network retry policy, process
  reattachment, or broader partition testing.
- Weakening the runner so a new controller lease alone authorizes recovery.
- Reworking the already validated append-only output-commit or migration
  design, except for a concrete regression caused by this narrow wiring.

Fixed behavior:

- Repository authority remains the single owner of recovery facts.
- The HTTP layer transports those facts without reinterpreting them.
- The runner continues to require an expired old-controller fact and one fact
  for every incomplete active attempt before mutation.
- Live or ambiguous ownership still fails closed.
- A healthy renewed controller remains exclusive after the original expiry;
  release ends renewal and permits later ownership.
- Existing HTTP protocol metadata, generation/workspace checks, and structured
  rejection handling apply to the new operation.

## Invariant Ownership

| Invariant | Owner | Boundary | Consequence | Required proof |
| --- | --- | --- | --- | --- |
| HTTP recovery facts equal repository recovery facts. | Repository plus protocol transport | Service route/client/adapter | Managed-service crash can never safely resume, or facts are silently lost. | Real HTTP adapter returns expired controller and attempt records and omits live records. |
| Recovery remains fail-closed. | Runner | Adapter result | Split-brain attempt 2 or unsafe takeover. | Missing facts still reject; complete HTTP facts permit the existing recovery sequence. |
| Renewal extends exclusive ownership. | Authority lease owner | Mutable time crossing original expiry | Two live controllers after a long run. | Renew before expiry, advance past original expiry, reject competitor, then release normally. |

## Implementation And Validation

Implementation slices:

1. Add the route constant, mutation operation/dispatch, service method, client
   method, and package exports for run recovery scan. Reuse existing protocol
   result serialization; do not bump the already-current v2 protocol unless an
   actual incompatible shape change is demonstrated.
2. Replace the HTTP adapter stub with client delegation and add service/client/
   adapter tests covering exact record transport and error handling.
3. Make renewal time mutable, synchronize on renewal rather than sleep, cross
   the original expiry, test competing acquisition, then confirm normal release.
4. Run focused gates, full validation and receipt, then perform manager review
   specifically against the two independent findings.

Focused commands may be narrowed to exact tests, but must cover:

    uv run pytest tests/unit/loom/pipeline/stores/test_authority_client.py
    uv run pytest tests/unit/loom/authority/test_mutation_service.py
    uv run pytest tests/integration/authority/test_mutation_api.py
    uv run pytest tests/unit/loom/pipeline/execution/test_authority_adapter.py
    uv run pytest tests/integration/pipeline/test_controller_lease_renewal.py

Final gates:

    make validate-pr
    make test-summary

## Risks, Stops, And Workflow State

- Main risk: accidentally expose workspace coordination recovery instead of
  per-run controller/attempt recovery. Keep distinct paths and result fields.
- Main race risk: a time-based test that observes only a method call. Synchronize
  on a renewal performed after time advances, then cross the original expiry.
- Stop if the existing v2 result cannot carry records, the repository scan has
  backend-specific semantics, HTTP transport changes recovery meaning, or the
  TTL proof requires production timing hooks.
- Implementation: in progress
- Corrections: 0/3
- Pre-submit gate: pending
- Review: manager-local, focused on closure of the two recorded findings
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Adopted implementation | Phase 2 commits through `5194d06`; no Phase 2 PR was opened. |
| HTTP recovery parity | pending |
| Renewal post-expiry proof | pending |
| Focused and full validation | pending |
| Review, PR, merge, metadata, cleanup | pending |

# Phase 9F Execution Plan: Session Replacement And Recovery Operations

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 9F
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p9f-session-replacement-recovery-operations`
- Worktree root: `/home/can134/work/active/loom-worktrees`
- Worktree path: create after Phase 9E is remotely merged
- Base revision: current `origin/develop` after the Phase 9E merge
- PR target: `develop`
- PR title: `feat(scheduling): close recovery operations and replacement`
- Dependency: Phases 9C2, 9D, and 9E remotely merged. Blocked Phases 9 through
  9C remain read-only evidence; the blocked Phase 9 plan's `Session replacement`
  heading retains the approved behavior contract.
- Workflow path: expanded because session identity replacement joins every
  retained owner and closes the stage-wide public/operational surface.
- Blocker corrections: 0/3

## Objective And Context

Complete Stage 29 by safely replacing a lost agent session only after every
reference to the old session is terminal, released, or covered by qualifying
positive containment. Expose the remaining authenticated recovery/status
operations consistently, document the hard cut, and prove the complete stage
with fresh-process E2E and repository validation.

No backward compatibility is supported. Old or missing protected state,
profiles, descriptors, schema identities, and copied roots fail closed and
require explicit reinitialization; they are never treated as empty healthy
state or adopted into a new session.

## Scope

In scope:

- Build one authoritative complete old-session reference query spanning
  assignments, provider preparations/claims, deliveries, controls, transfers,
  results/outputs, sequenced events, outbox entries, release operations, and
  retained managed-supervisor evidence.
- Permit replacement only when every reference is terminal-and-released or has
  target-owned qualifying containment followed by the required close/release
  saga. Partial enumeration or weak evidence rejects replacement.
- Create a genuinely new session identity. It inherits no live claim, work
  request, availability revision, transfer identity/authorization, provider
  token, process identity, or supervisor launch.
- Keep the replacement session at zero availability until a fresh full provider
  observation is recorded and every old-session reference is reconciled.
- Reject delayed old-session offers, polls, controls, transfers, events,
  results, outputs, outbox acknowledgements, and releases by immutable session,
  assignment, process, execution-fence, and operation identity.
- Complete joined coordinator/agent status for unresolved reference count,
  containment evidence, recovery arbitration, retry decision, physical release,
  replacement readiness, and the reason capacity remains withheld.
- Complete authenticated Python, direct, HTTP, and CLI operations for status,
  guarded close, and session replacement without duplicating policy in routes
  or presentation layers.
- Update operational guidance for supervisor-before-agent startup, hard-cut
  initialization, restart, unknown work, guarded close, physical release,
  session replacement, diagnostics, and accepted residual risks.
- Run final Stage 29 E2E, `make validate-pr`, and a fresh `make test-summary`.

Out of scope:

- Automatic replacement/takeover, supervisor or coordinator HA, power fencing,
  checkpoint migration, legacy-root import, best-effort PID/job inference, or
  periodic automated recovery.

## Fixed Contracts

Replacement checks the complete set, not a convenient subset:

```python
references = coordinator.list_complete_session_references(old_session_id)
if not references.complete:
    return ReplacementRejected(reason="incomplete_reference_enumeration")
if not all(item.terminal_and_released or item.qualifying_containment for item in references.items):
    return ReplacementRejected(reason="incomplete_containment")
```

The startup/replacement order is fixed:

```text
old complete reference set resolved
  -> new protected session identity created
  -> zero availability and no work polling
  -> fresh provider/config observation recorded
  -> retained ownership rechecked
  -> one fresh full availability observation published
  -> work polling enabled
```

Facts from the old identity remain useful audit evidence but cannot mutate the
new session or current authority truth. A human reason or operator role can
authorize an operation; neither can substitute for complete references,
positive containment, authority CAS, or physical release evidence.

## Invariant Ownership

| Invariant | Owner | Material consequence | Required evidence |
| --- | --- | --- | --- |
| Replacement evaluates the complete old-session set | Coordinator joined reference query | Hidden live work overlaps new capacity | Every reference class omitted/included causal tests |
| New session inherits no old capability or claim | Agent/session root and providers | Cross-session mutation or double allocation | Fresh-process stale-fact rejection matrix |
| Capacity follows fresh physical observation only | Agent/provider availability owner | Unsafe capacity advertisement | Zero-capacity barriers through replacement |
| Every public transport invokes one domain operation | Queue application/authorizer | Divergent auth or lifecycle behavior | Python/direct/HTTP/CLI parity tests |
| Final evidence matches the final tree | Manager validation gate | Unreviewed Stage 29 behavior | E2E, `make validate-pr`, fresh summary receipt |

## Implementation Slices

1. Implement complete session-reference enumeration, replacement eligibility,
   new-session creation, zero-availability startup, and stale old-fact rejection.
2. Finish joined status plus Python/direct/HTTP/CLI operations and operational
   guidance through the existing application and authorization boundaries.
3. Add the full managed/SLURM restart-recovery-replacement E2E matrix, run all
   repository gates, and correct only concrete accepted-contract failures.

## Test And Validation Plan

- Unit: complete reference projection, eligibility reasons, identity/profile/
  schema hard cut, and stale old-session fact rejection.
- Contract: least-privilege Python/direct/HTTP/CLI parity and redacted joined
  status with no transport-owned policy.
- Integration: real fresh processes for supervisor, agent, and coordinator;
  partial reference sets; delayed old facts; contained and unknown managed/SLURM
  work; replacement zero-capacity/fresh-observation order.
- E2E: local and remote managed restart, SLURM no-resubmit, guarded terminal-
  versus-close, existing-policy retry, and different-session replacement.
- Final gate: `make validate-pr`, then `make test-summary` without source, test,
  dependency, build, or validation changes after the receipt.

## Risks, Review, And Stops

- Main risks are an incomplete reference query, stale old facts mutating new
  state, capacity published before provider truth, transport-specific authority,
  or a validation receipt made stale by later edits.
- Stop if any supported owner cannot enumerate its old-session references or if
  replacement requires inferring containment from absence rather than a trusted
  receipt.
- Independent review is required for complete-reference and stale-fact safety.

## Executor Handoff

- Start only after Phase 9E is remotely merged and this branch is based on
  current `origin/develop`.
- Read this plan, Phase 9C2/9D/9E completion records, and the blocked Phase 9 plan's
  `Session replacement` section.
- Implement all three slices and run the final gates. Do not add compatibility,
  edit roadmap metadata, perform GitHub operations, or delegate.

## Workflow State

- Manager preparation: pending Phase 9E merge
- Implementation: pending
- Validation and review: pending
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and tests | pending |
| Validated revision and evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |

# Phase 14 Execution Plan: Reload And Authority Composition

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 14
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p14-reload-authority-composition`
- Worktree root and path: `/home/can134/work/active/loom-worktrees/stage-29-p14-reload-authority-composition`
- Base revision: `961b87f8ec1a490bd38e9c1de5992a75b18bd2dc`
- PR target: `develop`
- PR title: `Stage 29 phase 14: complete protected role composition`
- Dependencies: remotely merged Phase 13A; Phase 13 remains read-only evidence
- Workflow path: expanded; durable configuration identity and authority trust boundary
- Blockers: none

## Objective And Context

- Vertical outcome: the protected coordinator/outbound-agent YAML constructs and
  safely reloads the full supported scheduling, provider, SLURM, and authority
  composition, then restarts from the persisted active revision.
- Earlier dependency: Phase 13A delivers the validated Phase 13 serve-owned
  supervisor lifetime and offer publication versus renewal; reload that changes
  availability must use those semantics.
- Later work explicitly out of scope: new management read commands, portable
  local-owner policy, and example journeys belong to Phase 15.

## Current Source And Harness

- `src/loom/queue/deployment.py` owns protected schema-v1 loading but currently
  constructs only built-in local capacity/profiles and TLS policy.
- `src/loom/queue/local_daemon.py` binds the full deployment fingerprint and
  accepts an optional trusted scheduling loader not wired by CLI service paths.
- `src/loom/queue/agent_session_transport.py` similarly binds the outbound
  configuration and has an optional trusted loader.
- `src/loom/cli/queue.py` loads service config once, constructs role clients
  without source loaders, and emits success for rejected reload receipts.
- `src/loom/queue/local_daemon_execution.py` directly constructs
  `SQLitePerRunAuthorityStore` at production call sites despite an existing
  scoped coordinator wrapper.
- Existing scheduling/provider component protocols and authority client/store
  adapters are reused; no new generic plugin or store framework is needed.

## Scope

In scope:

- Canonical immutable-role and reloadable-active configuration projections,
  fingerprints, persisted revisions/epochs, startup checks, and hard-cut schema.
- Trusted loader wiring from `source_path` for coordinator and outbound agent.
- Protected schema for authority selection/TLS identity, priority resolver,
  scheduling planners/rules/scorers/policy, ready-stage SLURM profiles and
  provider, embedded agent provider composition, and remote resident provider
  composition.
- Explicit trusted `_target_` construction and validation against existing
  public protocols/descriptors/claim contracts.
- Queue-owned coordinator-authority protocol plus injected per-run factory;
  direct embedded and authenticated persistent adapters.
- Nonzero CLI result for rejected coordinator or agent reload receipts.

Out of scope:

- Automatic target discovery, untrusted/sandboxed config, new scheduling or
  provider semantics, authority HA, migration, or secret serialization into
  fingerprints.
- Phase 15 list/detail/operation CLI additions.

Assumptions:

- Authored owner-protected config is trusted project/site code.
- Existing authority client configuration can express the supported HTTPS
  endpoint and scoped service/workspace identity; extend only the narrow role
  adapter required by current coordinator operations.
- Immutable supervisor executable profile-set identity cannot live-reload.

## Fixed Contracts And Private Discretion

- Observable behavior: reload rereads the exact protected source; immutable
  changes are rejected without swap; a complete valid replacement persists its
  active fingerprint/epoch and becomes live; restart accepts that exact active
  revision. Rejected reload receipts exit nonzero.
- Durable shapes: role binding stores role kind, stable ID, schema/root/service
  identity and immutable fingerprint. Active configuration stores monotonically
  changing revision, reloadable fingerprint, and scheduling/configuration epoch.
- Trust boundary: only protected local source creates `_target_` objects.
  Configured persistent authority uses authenticated least privilege; embedded
  direct access is an explicit trusted composition.
- Cross-phase contracts: Phase 15 reads scheduling/time/configuration revisions
  but does not mutate fingerprint ownership.
- Reproducibility: fingerprints use canonical non-secret authored values; live
  objects, source absolute path, certificates' secret bytes, and ambient state
  are excluded unless already part of a stable public descriptor.
- Private choices: internal dataclass names, target-construction helper, adapter
  class names, and transaction layout may vary.

## Proportionality

- Existing seam reused: protected loader, component registries/descriptors,
  provider conformance, scoped authority wrapper, authority clients, and reload
  control protocols.
- Material additions are required by current service commands and previously
  advertised reload/composition behavior.
- Deferred: general dependency injection container, plugin discovery, remote
  config server, configuration history UI, and authority federation.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Immutable role identity never changes in place | role binding/startup validator | protected file edit/reload | wrong root/service/supervisor takeover | immutable mutation matrix |
| Active config is complete and restartable | role active-configuration transaction | reload and crash/response loss | live/durable divergence | crash/restart and exact fingerprint tests |
| Every configured target satisfies its existing contract | protected composition loader | trusted but malformed target | runtime scheduler/provider failure | dummy good/bad target tests |
| Production authority access follows injected configured adapter | queue execution authority protocol/factory | direct SQLite construction | bypassed trust/service boundary | fake/HTTPS composition and source guard |

## Implementation Slices

1. Define canonical immutable/reloadable projections and role active-state
   persistence; replace full-YAML binding and add startup/reload crash tests.
2. Expand and version the protected coordinator/agent schemas; construct and
   validate configured scheduling, SLURM, provider, priority, and authority
   objects exactly once.
3. Wire source-based trusted loaders into both production serve paths and make
   rejected coordinator and outbound-agent reloads fail the CLI command.
4. Define/inject the coordinator-authority protocol/factory, adapt embedded and
   authenticated authority owners, and remove direct SQLite construction from
   production execution.
5. Run full composition/reload/restart matrices and hard-cut old configs/roots.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | intentional authority/config exports | cheap import and `__all__` |
| Unit | required | projection fingerprints, schema, target checks, CLI exits | canonical equality/change and malformed targets |
| Contract | required | planner/provider/policy/authority structural adapters | downstream dummy implementations |
| Integration | required | successful reload/restart and HTTPS/direct authority paths | persisted active revision and exact calls |
| E2E | required | real coordinator/agent service reload | protected file replacement and process restart |

Targeted commands:

    uv run --extra config pytest tests/unit/loom/queue/test_deployment.py tests/unit/loom/cli/test_queue.py
    uv run --extra config pytest tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_local_daemon_production.py tests/contracts

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: fingerprinting secrets/paths, persisting active config before an
  unusable replacement, duplicating scheduling registries, or broadening the
  authority protocol into database CRUD.
- Review focus: restart after reload and proof that persistent execution never
  silently falls back to direct SQLite.
- Stop if: existing authenticated authority APIs cannot implement an operation
  required by the production daemon without a material public authority design
  decision; target construction needs untrusted loading; or Phase 13A's immutable
  supervisor profile decision is contradicted.
- Accepted debt: certificate/config rotation is explicit reload and active
  service connection replacement; distributed config coordination is deferred.

## Executor Handoff

- Read section range: this entire phase plan plus Stage 29 planning FR-35-38 and
  DD-35-37.
- Safe implementation slices: 1-5 above.
- Decisions not to revisit: two fingerprint domains, source-based trusted
  loaders, complete eager composition, injected authority, and nonzero rejected
  reload outcomes.
- Conditions requiring manager action: missing authority capability, new
  heavyweight dependency, compatibility/migration requirement, or scope drift
  into Phase 15.

## Workflow State

- Manager preparation: passed at clean current `origin/develop`
  `961b87f`; Phase 13A merge/cleanup, FR-35 through FR-38, DD-35 through
  DD-37, source owners, target matrices, authority seam, and stop conditions
  were verified
- Expanded planning: no phase-planner pass needed; the approved plan already
  fixes both fingerprint domains, trusted eager target construction, the narrow
  authority factory, and reload CLI semantics. Independent review remains
  required for the durable reload and authority trust boundaries.
- Implementation: pending
- Refiner: not needed
- Pre-submit gate: pending
- Independent review: required for authority trust and durable reload/restart boundary
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |

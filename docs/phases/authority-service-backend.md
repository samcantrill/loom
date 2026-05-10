# Phase 7 Execution Plan: Authority Service Backend

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 7 - Concrete Service/Database Backend
- Status: in_progress
- Branch: `codex/authority-service-backend`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-service-backend`
- Stack predecessor: none; Phase 6 merged before branch creation.
- Base branch: `develop`
- PR target branch: `develop`
- PR: pending
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 7: Authority Service Backend`
- Draft pass: complete on 2026-05-10
- Refine pass: complete on 2026-05-10 because this phase defines a new
  backend, service lifecycle, capability claims, and concurrency behavior.
- Phase implementation refinement budget: unused
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

## Scope

This phase introduces the first concrete service-backed authority backend
without making it the default runtime authority.

The implementation will:

- Add a stdlib-only local authority service endpoint with explicit
  start/connect/health/stop lifecycle for deterministic tests.
- Add a service client selected through `create_run_store()` by
  `AuthorityConfig` using `co_located_service`, `managed_service`, or
  `allocation_scoped_service` backend kinds.
- Keep clients service-bound: the public client receives an endpoint and
  credentials, not a shared authority database path.
- Back the service with an in-process authoritative record model that owns runs,
  run status, run leases, stages, attempts, stage leases, submitted operations,
  output commits, artifact facts, recovery records, cleanup candidates, audit
  events, monotonic revisions, and backend clock/TTL state.
- Declare supported and unsupported backend capabilities precisely, including
  service endpoint support, transaction isolation, consistent reads, fencing,
  leases, snapshots, and explicitly unsupported production persistence,
  shared-filesystem direct authority, unauthenticated hosted operation, and
  deferred finalization.
- Add backend diagnostics and config validation for service health,
  unavailable services, unsafe direct database paths, and topology assumptions.
- Prove the backend against the public `RunStore`/`StageStore` conformance
  harness.
- Add deterministic integration coverage for concurrent run admission and
  concurrent stage mutation through separate service clients.

## Out Of Scope

- Making the service backend the default authority for all runtime paths.
- Hosted production operations, authentication beyond local test credentials,
  authorization, tenancy, or high availability.
- A scheduler, queue, worker daemon, or adaptive retry system.
- Remote artifact payload movement.
- Deferred finalization envelope execution, which Phase 8 owns.
- Removing the transitional SQLite authority backend.
- Advertising shared-filesystem SQLite as a multi-host authority mode.

## Design Impact

Very high. This phase introduces a new authority backend family and the
service-bound configuration path later HPC and multi-host phases will depend on.

## Future Compatibility

The service client boundary lets Phase 8 carry endpoints into HPC profiles and
lets later phases replace the deterministic local service core with a durable
database-backed service without changing `RunStore`/`StageStore` callers.

## Alternatives Rejected

- Pointing clients at a shared SQLite authority file. That would bypass the
  service boundary and reintroduce shared-file authority claims.
- Adding a heavyweight web framework or database dependency. The first backend
  only needs deterministic service semantics for contract and integration
  coverage.
- Claiming production or arbitrary multi-host support from the local service
  fixture. Capability records and diagnostics must be honest.

## Debt Introduced

- The deterministic local service is not a production hosted service and does
  not provide tenancy, durable operations, or high availability.
- Workspace-level resource counters and deferred finalization remain capability
  declarations until Phase 8 expands deployment profiles and fallback modes.

## Acceptance Criteria

- `create_run_store()` can construct a service-backed `RunStore` from a public
  `AuthorityConfig`.
- The service-backed store passes the public authority conformance harness.
- Client construction fails closed when endpoint, credentials, or service health
  are invalid.
- Clients do not accept a direct shared database path as service authority.
- Capability diagnostics describe supported consistency guarantees and
  unsupported production/HPC modes.
- Deterministic integration tests show separate clients concurrently admitting
  runs and mutating different stages through the service endpoint.
- The backend remains opt-in and does not replace transitional SQLite defaults.

## Suite Obligations

- Package: service modules do not add heavyweight imports to public package
  import paths.
- Unit: service config parsing, endpoint validation, capability diagnostics,
  health/unavailability mapping, stale transitions, leases, idempotency, and
  client direct-path rejection.
- Contract: add service backend to the public `RunStore`/`StageStore`
  conformance harness.
- Integration: local service lifecycle plus concurrent run/stage behavior
  through separate clients.
- E2E: not required for default CLI adoption in this phase.
- Opt-in: no real HPC or externally hosted service tests.

## Implementation Summary

- Pending.

## Validation Evidence

- Pending.

## Stop Conditions

- The selected service mechanism requires a heavyweight runtime dependency.
- Service clients must share a direct writable database file to pass the
  conformance harness.
- The backend cannot provide honest capability diagnostics for unsupported
  production/HPC topologies.
- Deterministic service lifecycle tests are flaky or require network access
  outside local loopback.

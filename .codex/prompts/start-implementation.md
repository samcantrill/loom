Start the `loom` v0 Phase 2 implementation workflow as the managing agent.

Repository: `/home/samcantrill/work/loom`
Base branch: `develop`
Worktree root: `/home/samcantrill/work/loom-worktrees`
Full plan: `docs/implementation-plans/implementation-plan-v0.md`
Manager prompt: `.codex/prompts/phase-loop-management.md`
Assigned phase: `Phase 2 — Primitives And Serialization`
Phase branch: `codex/add-primitives-serialization`
Phase worktree: `/home/samcantrill/work/loom-worktrees/add-primitives-serialization`

First, make sure the current workflow/docs changes needed to start Phase 2 are
committed or otherwise present on `develop`. Then follow the manager workflow
for Phase 2 only.

The plan quality gate has already passed in
`docs/implementation-plans/implementation-plan-v0.md`. Confirm that the plan
still records the gate as passed before assigning Phase 2 work. If the gate is
missing, not passed, or has unresolved blocking findings, stop and report the
blocker instead of starting implementation. Do not rerun Phase 0 unless the user
explicitly asks.

Phase 1 has already merged through PR #1. Confirm that Phase 1 is recorded as
`merged` in `docs/implementation-plans/implementation-plan-v0.md` and that
Phase 2 is the next `pending` phase before assigning work. If Phase 1 is not
recorded as `merged`, or if another phase is unexpectedly pending ahead of
Phase 2, stop and report the blocker.

Maintain a loop budget while managing the workflow. A gate may consume only the
review/refinement passes allowed by `.codex/prompts/phase-loop-management.md`.
Before assigning any reviewer or refiner, check whether that gate's pass has
already been used in the current thread, expanded phase plan, PR body, or
implementation-plan notes. If it is unclear, assume the budget is consumed and
report the blocker instead of starting another automated pass.

Start by reading:

- `AGENTS.md`
- `.codex/prompts/phase-loop-management.md`
- `docs/implementation-plans/implementation-plan-v0.md`
- `docs/structure.md`
- `docs/phases/add-foundation-skeleton.md`
- Any existing Phase 2 plan in `docs/phases/`

Phase 2: primitives and serialization

Goal:

- Implement the generic value objects and serialization helpers used by every
  later subsystem.

Required Phase 2 workflow:

1. Confirm Phase 2 is the next pending phase and earlier required gates are
   satisfied.
2. Check for an existing Phase 2 branch, worktree, expanded phase plan, or PR.
   If one exists, inspect it and resume safely instead of creating duplicates.
3. Assign Phase 2 planning to `loom_phase_planner` using
   `.codex/prompts/implementation-phase-planning.md`. The draft expanded phase
   plan must use branch `codex/add-primitives-serialization`, worktree
   `/home/samcantrill/work/loom-worktrees/add-primitives-serialization`, and a
   `docs/phases/` filename matching the branch summary.
4. Assign the committed draft phase plan to `loom_phase_plan_expander` using
   `.codex/prompts/implementation-phase-plan-expansion.md`.
5. Assign implementation and phase-scoped tests to `loom_phase_executor` using
   `.codex/prompts/implementation-phase-execution.md`.
6. Assign at most one bounded implementation/test refinement pass to
   `loom_phase_refiner` using
   `.codex/prompts/implementation-test-refinement.md`, only if the phase
   implementation refinement budget is still unused.
7. Assign PR preparation to `loom_pr_preparer` using
   `.codex/prompts/pull-request-preparation.md`. Ensure `make validate-pr` and
   `make test-summary` are run or any unavailable checks are clearly justified
   in the expanded phase plan and PR body.
8. Stop after the Phase 2 PR is opened or the PR body is prepared. Report the
   branch, worktree, expanded phase plan path, PR link or reason it was not
   opened, validation evidence, accepted risks, remaining blockers, and exact
   files changed.

Phase 2 scope reminders:

- Add public primitives:
  - `ResourceRef`
  - `ArtifactRef`
  - `Record`
  - `InMemoryManifest`
  - `ManifestView`
  - generic record filters
  - provenance models
  - package-wide generic protocols
  - stable fingerprint helpers
- Add serialization helpers for:
  - plain data checks and conversion
  - dataclass conversion
  - stable JSON output
  - schema-version validation
- Preserve checksum and fingerprint as distinct concepts.
- `ResourceRef` and `ArtifactRef` must be frozen typed dataclasses with URI,
  type/key metadata, schema version, checksum, fingerprint/provenance metadata
  where applicable, and no loading methods.
- `Record` must be a frozen typed dataclass with generic resources, metadata,
  annotations, and provenance. It must not grow domain fields.
- `InMemoryManifest` must reject duplicate record IDs and preserve deterministic
  iteration.
- `ManifestView` must support lazy generic filters such as `HasResource`,
  `MetadataEquals`, and `MetadataIn`.
- Provenance models must cover code, environment, run, and stage context without
  heavyweight dependency inspection.
- Lightweight provenance capture helpers must cover git state when available,
  standard-library environment facts, selected package versions through
  `importlib.metadata`, command argv/cwd, and artifact input/output lineage.
  Helpers must degrade to explicit unavailable/unknown values rather than
  requiring git, network access, or heavyweight dependency inspection.
- Fingerprint helpers must use stable JSON and cryptographic hashes. Never use
  Python built-in `hash()` for persisted identities.
- Serialization must emit only plain structured data and must not perform
  filesystem writes.
- Serialization must not import the I/O subsystem.
- Update `loom.__init__` only with stable cheap public exports that are
  implemented in Phase 2 and allowed by the v0 public surface.

Phase 2 acceptance reminders:

- Frozen typed primitives have deterministic equality and plain-data conversion.
- `ResourceRef.codec_key` round-trips when set, omitted, or explicitly `None`.
- Manifests reject duplicate record IDs and preserve deterministic iteration.
- Manifest views support generic filtering without domain semantics.
- Fingerprints are deterministic across mapping insertion order.
- Serialization outputs only plain structured data.
- Serialization does not import the I/O subsystem.

Phase 2 test reminders:

- Add focused tests for refs, artifacts, records, manifests, provenance,
  lightweight provenance capture, fingerprints, optional `ResourceRef.codec_key`
  serialization, plain-data serialization, dataclass conversion, JSON helpers,
  and schema helpers.
- Preserve Phase 1 import-boundary expectations.
- Run relevant targeted tests while implementing, then `make validate-pr` and
  `make test-summary` during PR preparation.

Rules:

- Do not start Phase 3 or any later implementation phase.
- Do not implement I/O sources, codecs, filesystem writes, artifact stores,
  pipeline planning, pipeline execution, config composition, recipes, object
  construction, schema migrations, or domain-specific helpers.
- Do not add hard config runtime dependencies.
- Do not create phase work directly in the original checkout.
- Do not approve, merge, or clean up the Phase 2 PR/worktree unless the user
  explicitly asks for that follow-up.
- Do not loop on review/refinement; after the bounded pass, escalate blockers to
  the user.
- Keep `loom` domain-neutral and aligned with `docs/structure.md`.
- Make the smallest reasonable assumption when ambiguous and document it in the
  expanded phase plan and PR body.

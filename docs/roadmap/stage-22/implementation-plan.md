# Roadmap Stage 22 Implementation Plan: Examples And Deferred Behavior Documentation

Status: draft; planning confirmation, design-safety review, and plan quality
gate pending
Roadmap stage: `v22`
Planning document: `docs/roadmap/stage-22/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: none; implementation has not started
Blockers:

- Planning confirmation is pending.
- Formal design-safety review is pending.
- Implementation-plan quality gate is pending.

## Summary

- Goal: make implemented Loom functionality demonstrable through curated,
  validated examples and make deferred behavior explicit enough to guide future
  roadmap decisions.
- Source functionality-agreement gate: drafted in
  `docs/roadmap/stage-22/planning.md`; not yet formally confirmed.
- Approved behavior: pending.
- Source behavior confirmation: pending.
- Key design constraints: docs/example-only scope, domain neutrality,
  default-local validation, no new runtime behavior, no provider SDK or network
  requirements in default checks, and public API/CLI examples only.
- Source design-agreement gate: pending.
- Future-roadmap impact: deferred behavior becomes a structured register with
  rationale, ownership, future-candidate links, and revisit triggers.
- Reusable interface, adapter, or protocol assumptions: if metadata schemas are
  introduced, they stay plain-data, docs-owned, and validation-only; core
  runtime modules do not import them.
- Examples covered: authoring, execution, operations, reliability, events,
  cleanup/retention, bundles, sweeps, plugins, containers, SLURM, and manual
  external-system flows where applicable.
- Source phase shaping: four draft phases.
- Source plan quality gate: pending.
- Out of scope: runtime features, executor/store/plugin behavior,
  domain-specific examples, hosted docs publishing, provider-backed default
  validation, and broad generated-doc tooling.

## Implementation Workflow State

- Implementation-plan quality gate: pending
- Review pass: pending
- Refinement pass: pending
- Confirmation review: pending
- Automatic merge mode: enabled after plan quality gate and phase PR gates
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-22/planning.md`
- Functionality and behavior baseline: drafted, pending confirmation.
- Design agreement: pending.
- Design-safety review: pending.
- Examples and validation strategy: drafted.
- Phase shaping: drafted.
- Implementation readiness blockers:
  - Planning confirmation pending.
  - Design-safety review pending.
  - Plan quality gate pending.

## Desired Outcome

When all phases are complete:

- `examples/README.md` and related group READMEs provide a stable catalog of
  runnable, full, manual, illustrative, and `internal_demo` examples.
- Example manifests record stable IDs, owning feature docs, owning roadmap
  stages, validation tier, public surfaces demonstrated, and external
  prerequisites when any exist.
- Runnable examples are covered by default validation or an explicitly named
  local test path.
- Manual examples are clearly excluded from default validation and document why.
- A deferred-behavior register records unsupported behavior, rationale, related
  docs/examples, owning future-roadmap candidate when known, and revisit
  trigger.
- Feature docs and examples stop using vague future-tense promises where a
  concrete deferral or future candidate is available.

## Non-Goals

- No new runtime, executor, authority, cleanup, retention, event, plugin,
  artifact, sweep, store, or CLI behavior beyond docs/example validation.
- No domain-specific tutorial project in core Loom.
- No real cluster, cloud service, hosted backend, network, container daemon, or
  provider SDK requirement in the default suite.
- No hosted documentation site.
- No broad generated documentation system.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep examples domain-neutral and synthetic.
- User-facing examples must use public Python APIs or CLI commands.
- Internal fixtures may remain as internal demos but must not be presented as
  primary user-facing examples.
- Validation helpers may inspect docs and example metadata, but core runtime
  modules must not import examples or documentation tooling.

## Design Principles

- Demonstrate what exists. Examples should not imply future behavior is
  currently supported.
- Label execution assumptions. Default-runnable, opt-in, manual, illustrative,
  and `internal_demo` examples should be distinguishable from metadata alone.
- Public surface first. User-facing examples should not rely on private test
  helpers.
- Deferrals need owners. Unsupported behavior should point to a rationale and
  future review trigger.
- Docs validation stays lightweight. Checks should catch stale example metadata
  and broken public snippets without turning documentation into a runtime
  framework.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `examples-inventory-contracts` | pending | `codex/examples-inventory-contracts` | pending | examples metadata, docs validation tests | Define inventory/status metadata and consistency checks | unit, integration docs checks | catalog status/tier examples |
| 2 | `examples-coverage-catalog` | pending | `codex/examples-coverage-catalog` | pending | `examples/`, example READMEs, coverage docs | Update runnable/manual examples and catalog gaps | docs/example integration, targeted CLI smoke | authoring/execution/operations |
| 3 | `deferred-behavior-register` | pending | `codex/deferred-behavior-register` | pending | deferred register, feature-doc links, roadmap links | Capture deferred behavior and future candidates | schema/link checks, docs review | unsupported behavior examples |
| 4 | `examples-docs-final-audit` | pending | `codex/examples-docs-final-audit` | pending | docs audit, final evidence, plan metadata | Remove stale promises and record final validation | `make validate-pr`, `make test-summary` | final catalog |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Planning confirmation pending | `docs/roadmap/stage-22/planning.md` | Confirm or refine the draft scope before phase execution plans. | pending |
| Design-safety review pending | roadmap workflow | Review docs/example scope for future-roadmap compatibility and overpromise risk. | pending |
| Implementation-plan quality gate pending | roadmap workflow | Run plan review, at most one refinement pass if needed, and confirmation review. | pending |

## Phase 1: Example Inventory And Metadata Contracts

Status: pending
Slug: `examples-inventory-contracts`
Branch: `codex/examples-inventory-contracts`
Worktree: `/home/samcantrill/work/loom-worktrees/examples-inventory-contracts`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: fast path unless design-safety review requires expansion

### Scope

- Goal: define the example inventory shape, status/tier vocabulary, and
  lightweight consistency validation.
- Files/modules owned:
  - `examples/README.md`
  - `examples/**/example.yaml`
  - Existing docs/example validation tests or new docs-only validation tests
  - Targeted docs under `docs/features/*-example-coverage.md`
- Behavior implemented:
  - Metadata conventions for example ID, status, tier, public surfaces,
    owning docs, owning roadmap stage, prerequisites, and validation command.
  - Consistency checks for manifests and README references.
- Out of scope: adding new runtime examples beyond metadata normalization.
- Dependencies: planning and quality gate pass.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted docs/example metadata tests | Manifest and README consistency | yes |
| Existing docs/example integration tests | Preserve runnable example behavior | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: do not start until plan quality gate passes
- Merge record: pending

## Phase 2: Runnable Example Coverage And Catalog Cleanup

Status: pending
Slug: `examples-coverage-catalog`
Branch: `codex/examples-coverage-catalog`
Worktree: `/home/samcantrill/work/loom-worktrees/examples-coverage-catalog`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: fast path unless coverage gaps require expansion

### Scope

- Goal: make implemented feature families discoverable through runnable or
  explicitly classified examples.
- Files/modules owned:
  - `examples/authoring/`
  - `examples/execution/`
  - `examples/operations/`
  - Focused `docs/features/*-example-coverage.md`
  - Example integration tests
- Behavior implemented:
  - Catalog entries and README updates for supported examples.
  - No-example rationale for implemented feature families that should not have
    a runnable example.
  - Manual/illustrative classification for external-system examples.
- Out of scope: implementing missing runtime behavior just to make an example
  runnable.
- Dependencies: Phase 1.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Docs/example integration tests | Runnable examples still execute | yes |
| Targeted CLI smoke tests where examples use CLI | Public command examples remain valid | yes |
| Manifest consistency tests | Catalog and metadata stay synchronized | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 1 must be merged or used as stack predecessor
- Merge record: pending

## Phase 3: Deferred Behavior Register And Future-Roadmap Traceability

Status: pending
Slug: `deferred-behavior-register`
Branch: `codex/deferred-behavior-register`
Worktree: `/home/samcantrill/work/loom-worktrees/deferred-behavior-register`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path if the register changes roadmap scope

### Scope

- Goal: convert scattered unsupported/future behavior notes into a structured
  deferred-behavior register.
- Files/modules owned:
  - New or existing docs location for the deferred-behavior register
  - Feature docs that mention deferred behavior
  - `docs/roadmap.md` deferred candidate links where appropriate
  - Docs validation tests if a schema is introduced
- Behavior implemented:
  - Register entries with behavior, current user-facing location, reason,
    owning future candidate when known, and revisit trigger.
  - Cross-links from feature docs and examples to register entries.
- Out of scope: assigning every possible future idea to a committed roadmap
  version.
- Dependencies: Phase 1 metadata conventions; Phase 2 example locations where
  useful.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Deferred-register schema/link checks | Register entries remain well formed and linked | yes |
| Targeted docs checks | Feature docs point to concrete deferrals | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 2 must be merged or used as stack predecessor
- Merge record: pending

## Phase 4: Final Docs Audit And Validation Evidence

Status: pending
Slug: `examples-docs-final-audit`
Branch: `codex/examples-docs-final-audit`
Worktree: `/home/samcantrill/work/loom-worktrees/examples-docs-final-audit`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: fast path unless final audit finds broad stale-doc drift

### Scope

- Goal: finish stale-promise cleanup, final catalog polish, and suite evidence.
- Files/modules owned:
  - `README.md`
  - `examples/README.md`
  - Targeted feature docs
  - `docs/roadmap/stage-22/implementation-plan.md`
  - PR body artifact for the phase
- Behavior implemented:
  - Final docs consistency pass.
  - Validation evidence recorded.
  - Completion metadata and accepted follow-ups.
- Out of scope: new examples beyond small corrections required by audit.
- Dependencies: Phases 1 through 3.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted docs/example tests | Confirm final docs and examples | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Final suite evidence for PR body | yes |

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 3 must be merged or used as stack predecessor
- Merge record: pending

## Cross-Phase Validation

- Full relevant test command: each phase runs targeted docs/example checks plus
  `make validate-pr` and `make test-summary` before PR preparation.
- Docs/template checks: example manifests, README links, feature-doc links,
  deferred-register entries, and roadmap references.
- Domain-neutrality checks: examples use synthetic data and do not import
  downstream project packages.
- Example/demo checks: runnable examples remain local by default; manual
  examples state external prerequisites.
- Manual review focus: overpromising unsupported behavior, stale future-tense
  text, hidden external dependencies, `internal_demo` flows presented as user-facing
  examples, and deferrals without revisit triggers.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Planning confirmation pending | blocker | Confirm or refine `docs/roadmap/stage-22/planning.md`. | pending |
| Design-safety review pending | blocker | Review docs/example scope before phase execution. | pending |
| Plan quality gate pending | blocker | Run implementation-plan review after planning/design confirmation. | pending |

Gate result:

- Status: pending
- Review evidence:
- Accepted risks:
  - Some examples will remain manual because real external systems are not
    available in default validation.
  - The deferred-behavior register may start incomplete and grow as docs are
    audited.
- Revisit triggers:
  - Runnable examples require external services to stay meaningful.
  - Deferred-register entries become broad enough to need a dedicated roadmap
    restructuring stage.
  - Users need generated hosted documentation rather than in-repo docs.

## Final Approval

- Approval status: pending planning confirmation, design-safety review, and
  plan quality gate
- Approved scope: pending
- Accepted risks:
  - Manual examples remain manual and excluded from default validation.
  - Stage 22 is docs/example work, not runtime implementation.
- Deferred items:
  - New runtime behavior.
  - Domain-specific tutorial packages.
  - Hosted documentation publishing.
  - External-service-backed default validation.

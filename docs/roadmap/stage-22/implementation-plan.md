# Roadmap Stage 22 Implementation Plan: Examples And Validation Refinement

Status: phase 2 merged; phase 3 pending
Roadmap stage: `v22`
Planning document: `docs/roadmap/stage-22/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: Phase 3, `examples-e2e-workflows`
Blockers:

- None for stage-level design or plan quality.
- Phase execution plans are still required before each remaining phase begins.

## Summary

- Goal: make implemented Loom functionality demonstrable and trustworthy
  through robust examples, integration tests, end-to-end tests, and refined
  documentation.
- Source functionality-agreement gate: drafted in
  `docs/roadmap/stage-22/planning.md`; confirmed by user request to run the
  design review quality gate on 2026-05-18.
- Approved behavior: robust examples, integration testing behavior, e2e testing
  behavior, documentation refinement, and manual/no-example classification for
  unsupported or external-system behavior.
- Source behavior confirmation: 2026-05-18 design review quality gate request.
- Key design constraints: docs/examples/tests-only scope, domain neutrality,
  default-local validation, no new runtime behavior, no provider SDK or network
  requirements in default checks, and public API/CLI examples only.
- Source design-agreement gate: passed on 2026-05-18.
- Roadmap impact: example and validation gaps may inform later roadmap review,
  but v22 does not own future-feature planning.
- Reusable interface, adapter, or protocol assumptions: if metadata schemas are
  introduced, they stay plain-data, docs-owned, and validation-only; core
  runtime modules do not import them.
- Examples covered: authoring, execution, operations, reliability, events,
  cleanup/retention, bundles, sweeps, plugins, containers, SLURM, and manual
  external-system flows where applicable.
- Source phase shaping: four reviewed phases.
- Source plan quality gate: passed on 2026-05-18.
- Out of scope: runtime features, executor/store/plugin behavior,
  domain-specific examples, hosted docs publishing, provider-backed default
  validation, broad generated-doc tooling, and future-feature planning work.

## Implementation Workflow State

- Implementation-plan quality gate: passed on 2026-05-18
- Review pass: completed locally on 2026-05-18
- Refinement pass: not needed; no blocking findings remained
- Confirmation review: completed locally on 2026-05-18
- Automatic merge mode: enabled after plan quality gate and phase PR gates
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-22/planning.md`
- Functionality and behavior baseline: confirmed by user request to run the
  design review quality gate on 2026-05-18.
- Design agreement: passed.
- Design-safety review: passed.
- Examples and validation strategy: reviewed.
- Phase shaping: reviewed.
- Implementation readiness blockers:
  - None for stage-level design or plan quality.
  - Phase execution plans are still required before each remaining phase begins.

## Desired Outcome

When all phases are complete:

- `examples/README.md` and related group READMEs provide a stable catalog of
  runnable, full, manual, illustrative, and `internal_demo` examples.
- Example manifests record stable IDs, owning feature docs, owning roadmap
  stages, validation tier, public surfaces demonstrated, external prerequisites
  when any exist, and the relevant validation path.
- Runnable examples are covered by integration and/or e2e validation.
- Integration tests exercise examples against public APIs, fake/local backends,
  temporary run roots, authority modes, and realistic local workflows.
- End-to-end tests cover representative CLI and Python user journeys without
  requiring external services in the default suite.
- Manual examples are clearly excluded from default validation and document why.
- Feature docs and examples align their claims with named validation paths or
  clear manual status.

## What This Means In Practice

Stage 22 is a confidence and usability stage over behavior that already exists.
It should make Loom easier to evaluate without expanding the runtime surface.
Phase work should preserve this framing:

- A runnable local execution example should show a small synthetic pipeline using
  public CLI or Python entrypoints, write outputs under explicit example run
  roots, and point to the integration or e2e test that validates the workflow.
- A SLURM dry-run example should be runnable locally and validated through
  generated scripts, manifests, dependencies, and worker commands. A live SLURM
  submission walkthrough remains manual because it needs a real scheduler.
- A container example should validate fake/local command construction, preflight
  diagnostics, generated records, and failure behavior. Real Docker or Apptainer
  daemon behavior remains manual unless a later stage provides deterministic
  default validation.
- An operations or authority example should prove inspectable lifecycle,
  diagnostics, offline import, resource, or failure behavior through public
  commands/APIs and fake/local backends rather than private fixtures.
- Documentation should say whether each example is smoke, full, manual,
  illustrative, or `internal_demo`, and should link runnable claims to named
  validation paths.

If an example cannot be made runnable without new runtime behavior, external
services, provider credentials, a real cluster, or a daemon, the correct Stage 22
outcome is a no-example rationale or manual classification, not feature
implementation.

## Non-Goals

- No new runtime, executor, authority, cleanup, retention, event, plugin,
  artifact, sweep, store, or CLI behavior beyond docs/example/test validation.
- No broad future-feature planning pass.
- No domain-specific tutorial project in core Loom.
- No real cluster, cloud service, hosted backend, network, container daemon, or
  provider SDK requirement in the default suite.
- No hosted documentation site.
- No broad generated documentation system.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep examples domain-neutral and synthetic.
- User-facing examples must use public Python APIs or CLI commands.
- Internal fixtures may remain as `internal_demo` flows but must not be
  presented as primary user-facing examples.
- Validation helpers may inspect docs and example metadata, but core runtime
  modules must not import examples or documentation tooling.
- Integration/e2e tests must stay deterministic, local/fake-backed by default,
  and isolated through temporary directories.

## Design Principles

- Demonstrate what exists. Examples should not imply unsupported behavior is
  currently supported.
- Prove workflows, not only snippets. Runnable examples should have integration
  or e2e evidence.
- Label execution assumptions. Default-runnable, opt-in, manual, illustrative,
  and `internal_demo` examples should be distinguishable from metadata alone.
- Public surface first. User-facing examples should not rely on private test
  helpers.
- Docs validation stays lightweight. Checks should catch stale example metadata
  and broken public snippets without turning documentation into a runtime
  framework.

## Design Pass Findings

Local design pass status: completed; formal design-safety review passed on
2026-05-18.

| Finding | Resolution |
| --- | --- |
| "Robust examples" needed an explicit bar. | Added quality criteria around public surfaces, hermetic output roots, stable assertions, named validation paths, and manual prerequisite labeling. |
| Integration and e2e were overlapping. | Integration now proves component collaboration and persisted/fake-backend behavior; e2e proves representative user journeys. |
| Phase work could drift into runtime implementation. | Non-goals, stop conditions, and phase scopes now state that missing behavior yields no-example rationale or manual classification, not feature work. |
| Documentation refinement needed test evidence. | Docs must name validation tiers or test paths for runnable workflows. |

## Quality Bar

A runnable example is robust only when it:

- Uses public Python APIs or supported CLI commands.
- Uses synthetic, domain-neutral data and project-local stage code.
- Runs from a clean checkout with generated output redirected through
  `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT` where applicable.
- Avoids hidden reliance on previously generated local state.
- Produces stable, reviewable output or assertions.
- Has a named integration or e2e validation path.
- Documents manual limits when fake/local validation does not prove a real
  external system.

Integration tests in this stage should prove collaboration across implemented
boundaries, such as example entrypoints plus config composition, runner plus
store, CLI plus diagnostics, authority plus fake/local backends, or artifact
records plus export/import surfaces. They should assert persisted records,
diagnostics, generated artifacts, or public command/API results, not just
successful process exit.

E2E tests should prove representative user journeys. They should cover a small
number of high-value CLI or public Python flows, including success behavior and
stable failure or diagnostic behavior where natural. Exhaustive option
permutations remain lower-level test work.

## Coverage Matrix

| Area | Required example evidence | Required validation evidence |
| --- | --- | --- |
| Authoring and config | Composition, includes, overlays, recipes, target instantiation, artifact safety, and structured errors | Docs/example integration with manifest/source/fingerprint assertions where applicable |
| Local execution | Local run and resume examples using temporary run roots | Integration and/or e2e proving runner, store, artifacts, and resume behavior |
| Runtime profiles and options | Public run-options or runtime-profile examples | Integration proving normalization reaches execution or preflight boundaries |
| Subprocess and workers | Fake/local subprocess examples with logs and failures | Integration/e2e proving worker command, persisted failure records, and inspection |
| SLURM | Dry-run runnable examples plus live manual examples | Dry-run integration/e2e only; real cluster remains manual |
| Containers | Fake-Docker runnable examples and manual live guidance | Fake command/preflight/failure integration; real daemon remains manual |
| Authority and operations | Lifecycle, offline import, resources, diagnostics, and failure examples | Integration/e2e through authority modes, fake/local backends, and public CLI/API |
| Reliability, events, cleanup, retention | Runnable examples when surfaces exist, otherwise no-example rationale | Integration/e2e proving facts, diagnostics, events, cleanup reports, or retention inspection where public |
| Bundles, sweeps, plugins, artifacts | Runnable public workflows for implemented surfaces | Integration/e2e proving export/import, sweep manifests, plugin loading/listing, or artifact refs |

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Inventory source | Keep `example.yaml` and README metadata as the source of truth | Low ceremony and consistent with current examples, but validation must catch drift |
| Test tiering | Preserve smoke/full/manual plus `internal_demo` classification | Fits existing harness while giving V22 room to harden full/e2e coverage |
| Integration vs. e2e | Separate component-boundary proof from user-journey proof | Keeps e2e focused and avoids slow exhaustive workflows |
| External systems | Fake/local default validation; real systems remain manual | Default suite stays deterministic and dependency-light |
| Missing examples | Add no-example rationale or manual classification instead of runtime work | Keeps phase scope clean but may leave some feature families less demonstrable until a later feature stage |

## Conflicts And Tradeoffs

- More example validation can slow the default gate. The accepted tradeoff is
  to keep smoke examples fast, route broader local workflows through named
  integration/e2e paths, and record any suite-tier pressure in completion notes.
- Manual examples are less convincing than executable examples. They remain
  acceptable only for real external systems that cannot be made deterministic
  without new dependencies or infrastructure.
- A consolidated catalog can drift from per-feature docs. Phase 1 must add
  metadata and README consistency checks before later phases add more examples.
- E2E coverage is intentionally representative. Broad permutation testing
  belongs in unit, contract, or integration suites.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Full examples may remain outside the fastest smoke path | Keeps default docs/example validation fast enough for PR use | Users rely on full examples for core onboarding and they are not regularly validated |
| Some external-system workflows remain manual | Real clusters, daemons, and providers are not deterministic default dependencies | A fake-backed or hosted deterministic fixture becomes available |
| Example metadata remains YAML rather than a typed public schema | This is docs/test metadata, not runtime data | Validation helpers or downstream docs tooling need a stable schema contract |
| E2E workflows are representative rather than exhaustive | Prevents the suite from duplicating lower-level coverage | Regressions repeatedly escape through untested end-to-end paths |

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `examples-inventory-contracts` | merged | `codex/examples-inventory-contracts` | [#196](https://github.com/samcantrill/loom/pull/196) | examples metadata, docs validation tests | Define inventory/status metadata and consistency checks | unit, integration docs checks | catalog status/tier examples |
| 2 | `examples-integration-coverage` | merged | `codex/examples-integration-coverage` | [#197](https://github.com/samcantrill/loom/pull/197) | `examples/`, integration tests, coverage docs | Harden runnable examples and integration behavior | docs/example integration, targeted integration paths | authoring/execution/operations |
| 3 | `examples-e2e-workflows` | pending | `codex/examples-e2e-workflows` | pending | e2e tests, CLI/Python workflow docs | Cover representative end-to-end workflows | targeted e2e and CLI workflow checks | public journeys |
| 4 | `examples-docs-refinement` | pending | `codex/examples-docs-refinement` | pending | docs audit, final evidence, plan metadata | Align docs with validated examples and record final evidence | `make validate-pr`, `make test-summary` | final catalog |

## Implementation Readiness Blockers

| Gate item | Source | Resolution | Status |
| --- | --- | --- | --- |
| Planning confirmation | `docs/roadmap/stage-22/planning.md` | User asked to run the design review quality gate on the refined scope on 2026-05-18. | passed |
| Design-safety review | roadmap workflow | Reviewed docs/example/test scope for overpromise, domain neutrality, future-roadmap impact, public-contract safety, and external-dependency risk. | passed |
| Implementation-plan quality gate | roadmap workflow | Reviewed maintainability, extensibility, future compatibility, tradeoffs, technical debt, test strategy, and reviewability. | passed |
| Phase execution plans | phase workflow | Create a phase execution plan before each implementation phase. | pending |

## Phase 1: Example Inventory And Metadata Contracts

Status: merged
Slug: `examples-inventory-contracts`
Branch: `codex/examples-inventory-contracts`
Worktree: `/home/samcantrill/work/loom-worktrees/examples-inventory-contracts`
PR: [#196](https://github.com/samcantrill/loom/pull/196)
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

### Acceptance Evidence

- Behavior evidence: example manifests expose stable IDs, statuses, validation
  tiers, public surfaces, and validation commands.
- Design-decision evidence: validation checks treat metadata as docs/test
  inputs and do not create runtime imports.
- Documentation evidence: catalog and feature coverage docs are linked and
  internally consistent.
- Domain-neutrality evidence: metadata does not introduce domain-specific
  example categories.

### Phase Workflow State

- Phase execution plan: completed in `docs/roadmap/stage-22/phases/examples-inventory-contracts.md`
- Planning/refinement budget: draft completed; refine pass not needed
- Implementation/refinement budget: unused; targeted and full validation passed
- PR review budget: used by managing-agent local review on 2026-05-18; no blockers found
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: passed before PR submission
- Merge record: merged into `develop` on 2026-05-18 via [#196](https://github.com/samcantrill/loom/pull/196), merge commit `b02304bad363ccd4a6103f3385d5b11188693230`

### Completion And Merge Notes

- Implementation summary: added docs-owned inventory metadata to all existing
  example manifests, documented the manifest vocabulary in `examples/README.md`,
  and tightened docs integration checks for owner docs, roadmap stages,
  validation paths, README catalog membership, focused coverage references, and
  manual rationale.
- Validation: targeted docs integration passed
  (`UV_CACHE_DIR=.uv-cache uv run --active pytest tests/integration/docs/test_v0_python_examples.py`,
  `35 passed`). `make validate-pr` passed after rerunning outside sandbox
  restrictions: Ruff, Pyright, default pytest, config-extra pytest, and
  `uv build` all passed. `make test-summary` passed with overall `2443 passed`,
  `21 skipped`, and `2017 deselected`.
- GitHub review and CI: managing-agent local review found no blockers; PR #196
  targeted `develop`, GitHub CI `checks` passed, and the PR was squash-merged
  into `develop`.
- Follow-up notes: Phases 2 and 3 own stronger integration/e2e evidence for
  full/manual examples whose Phase 1 validation path is currently a docs-owned
  coverage reference.

### Risks And Stop Conditions

- Risks:
  - Metadata expansion may become too broad for simple YAML manifests.
  - Existing examples may need reclassification.
- Stop conditions:
  - A validation helper would need runtime package imports from examples.
  - A manifest field requires implementing feature behavior to populate it.
- Assumptions:
  - Existing `tests/integration/docs/test_v0_python_examples.py` can be evolved
    or supplemented without creating a separate framework.

## Phase 2: Robust Examples And Integration Behavior

Status: merged
Slug: `examples-integration-coverage`
Branch: `codex/examples-integration-coverage`
Worktree: `/home/samcantrill/work/loom-worktrees/examples-integration-coverage`
PR: [#197](https://github.com/samcantrill/loom/pull/197)
Base branch: `develop`
Target branch: `develop`
Workflow path: fast path unless coverage gaps require expansion

### Scope

- Goal: make implemented feature families discoverable through robust runnable
  examples backed by integration tests.
- Files/modules owned:
  - `examples/authoring/`
  - `examples/execution/`
  - `examples/operations/`
  - Focused `docs/features/*-example-coverage.md`
  - Integration tests for example workflows
- Behavior implemented:
  - Catalog entries and README updates for supported examples.
  - Integration coverage through public APIs, fake/local backends, temporary
    run roots, and realistic local workflows.
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
| Targeted integration suite paths | Example behavior crosses public API and local/fake backend boundaries | yes |
| Manifest consistency tests | Catalog and metadata stay synchronized | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Acceptance Evidence

- Behavior evidence: runnable examples execute through public APIs or CLI and
  use temporary output/run roots.
- Integration evidence: tests assert persisted records, diagnostics, generated
  artifacts, or fake/local backend behavior, not only process success.
- Documentation evidence: example READMEs describe the validation path and
  manual boundaries.
- Scope-control evidence: missing runtime behavior is handled as no-example
  rationale or manual classification.

### Phase Workflow State

- Phase execution plan:
  `docs/roadmap/stage-22/phases/examples-integration-coverage.md`
- Planning/refinement budget: completed on fast path; refine pass not needed
- Implementation/refinement budget: unused; no refiner pass needed
- PR review budget: satisfied by manager review with no blocking findings
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 1 merged before this phase started
- Merge record: merged into `develop` on 2026-05-18 via
  [#197](https://github.com/samcantrill/loom/pull/197), merge commit
  `91c1585e849f662417acdc11ae22dc2b1806c500`
- Implementation summary: added focused integration coverage for five
  `validation: full` operations examples, updated their manifest
  `validation_path` values to named test paths, and documented evidence in
  operations and authority example-coverage docs without changing runtime code.
- Checks: `make validate-pr` passed locally with Ruff, Pyright 0 errors,
  default harness `1963 passed, 26 skipped, 21 deselected`, config-extra
  `456 passed, 3 skipped, 2001 deselected`, and `uv build` success.
  `make test-summary` passed with `2448 passed, 21 skipped,
  2022 deselected` overall. GitHub CI `checks` passed for PR #197 before
  merge.
- Stack maintenance: no successor branch depended on
  `codex/examples-integration-coverage`; the PR was squash-merged into
  `develop` with branch deletion requested. Phase 3 should branch from updated
  `develop`.

### Risks And Stop Conditions

- Risks:
  - Integration coverage can become a broad retest of lower-level behavior.
  - Examples may duplicate implementation-specific setup.
- Stop conditions:
  - Making an example runnable requires new runtime behavior.
  - An example needs real external services for default validation.
  - Tests rely on persistent generated state outside temporary directories.
- Assumptions:
  - Fake/local backends are sufficient to demonstrate implemented external
    integration surfaces.

## Phase 3: End-To-End Workflow Behavior

Status: pending
Slug: `examples-e2e-workflows`
Branch: `codex/examples-e2e-workflows`
Worktree: `/home/samcantrill/work/loom-worktrees/examples-e2e-workflows`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: fast path unless e2e gaps expose broad docs drift

### Scope

- Goal: cover representative CLI and Python user journeys with e2e or
  equivalent workflow tests.
- Files/modules owned:
  - E2E tests for public example workflows
  - CLI/Python example READMEs where command flows are documented
  - Focused feature docs that describe example-backed journeys
- Behavior implemented:
  - End-to-end coverage for selected authoring, execution, operations,
    diagnostics, export/import, events, cleanup/retention, and other implemented
    workflows where available.
  - Stable command snippets or Python entrypoints that match validated behavior.
  - Clear boundaries for workflows that remain manual.
- Out of scope: real external-system e2e validation in the default suite.
- Dependencies: Phases 1 and 2.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted e2e tests | Representative user journeys pass locally | yes |
| Targeted CLI workflow tests | Command examples match public behavior | yes |
| Docs/example integration tests | Existing examples still run | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Suite evidence for PR body | yes |

### Acceptance Evidence

- User-journey evidence: selected CLI/Python workflows run end to end and
  assert stable user-visible results.
- Failure/diagnostic evidence: at least one representative stable failure or
  diagnostic path is covered where the workflow naturally exposes one.
- Tiering evidence: slow or broad flows have explicit suite placement.
- Documentation evidence: command snippets and README claims match validated
  behavior.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 2 must be merged or used as stack predecessor
- Merge record: pending

### Risks And Stop Conditions

- Risks:
  - E2E tests can become slow or flaky if they cover too much.
  - Golden output can become brittle.
- Stop conditions:
  - A workflow needs real network, cluster, daemon, or provider credentials in
    default validation.
  - E2E coverage starts duplicating large option matrices.
- Assumptions:
  - Representative journeys can be selected from already implemented public
    workflows.

## Phase 4: Documentation Refinement And Final Validation

Status: pending
Slug: `examples-docs-refinement`
Branch: `codex/examples-docs-refinement`
Worktree: `/home/samcantrill/work/loom-worktrees/examples-docs-refinement`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: fast path unless final audit finds broad stale-doc drift

### Scope

- Goal: finish stale-text cleanup, example-output alignment, final catalog
  polish, and suite evidence.
- Files/modules owned:
  - `README.md`
  - `examples/README.md`
  - Targeted feature docs
  - `docs/roadmap/stage-22/implementation-plan.md`
  - PR body artifact for the phase
- Behavior implemented:
  - Final docs consistency pass.
  - Documentation that names validation paths for robust examples.
  - Completion metadata and accepted follow-ups.
- Out of scope: new examples beyond small corrections required by audit.
- Dependencies: Phases 1 through 3.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| Targeted docs/example tests | Confirm final docs and examples | yes |
| Targeted integration/e2e tests touched by docs refinement | Confirm named validation paths remain true | yes |
| `make validate-pr` | Repository PR gate | yes |
| `make test-summary` | Final suite evidence for PR body | yes |

### Acceptance Evidence

- Documentation evidence: README and feature-doc claims name validation tiers
  or mark manual prerequisites.
- Final validation evidence: `make validate-pr` and `make test-summary`
  results are recorded for PR preparation.
- Reviewability evidence: completion metadata identifies any examples that
  remain manual, full-only, or intentionally absent.
- Scope-control evidence: no runtime behavior, provider SDK, or domain-specific
  tutorial work lands in the final cleanup.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: unused
- Implementation/refinement budget: unused
- PR review budget: unused
- Blocker-resolution budget: 0 of 3 used
- Pre-submit blocker gate: Phase 3 must be merged or used as stack predecessor
- Merge record: pending

### Risks And Stop Conditions

- Risks:
  - Final docs audit can expand into unrelated roadmap cleanup.
  - Example output snippets may overfit incidental formatting.
- Stop conditions:
  - Docs refinement requires changing product behavior.
  - A broad future-feature planning pass is needed to explain a doc.
- Assumptions:
  - Focused docs updates can align examples without restructuring feature docs
    wholesale.

## Cross-Phase Validation

- Full relevant test command: each phase runs targeted docs/example,
  integration, or e2e checks plus `make validate-pr` and `make test-summary`
  before PR preparation.
- Docs/template checks: example manifests, README links, feature-doc links,
  roadmap references, and validation path names.
- Domain-neutrality checks: examples use synthetic data and do not import
  downstream project packages.
- Example/demo checks: runnable examples remain local by default; manual
  examples state external prerequisites.
- Manual review focus: overpromising unsupported behavior, stale future-tense
  text, hidden external dependencies, `internal_demo` flows presented as
  user-facing examples, and validation claims without named test evidence.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| No blocking design-safety findings | info | Scope is docs/examples/tests-only, domain-neutral, fake/local-backed by default, and explicit about manual/no-example outcomes. | passed |
| No blocking plan-quality findings | info | Phases are reviewable, have validation obligations, acceptance evidence, risks, and stop conditions. | passed |
| Phase execution plans pending | non-blocking | Required before implementation of each phase, but not a blocker for the stage-level quality gate. | pending |

Gate result:

- Status: passed on 2026-05-18
- Review evidence:
  - `docs/roadmap/stage-22/planning.md` records functionality traceability,
    user intent, requirements, quality bar, coverage matrix, design choices,
    design-safety evidence, validation strategy, and phase shaping.
  - This implementation plan records planning readiness, design principles,
    quality bar, coverage matrix, key choices, conflicts, technical debt,
    per-phase acceptance evidence, validation obligations, and stop conditions.
  - `docs/structure.md` and `docs/GLOSSARY.md` constraints are reflected through
    domain-neutral examples, public API/CLI surfaces, and no runtime imports from
    examples or docs tooling.
  - `docs/features/testing.md` constraints are reflected through local/fake
    default validation, no real clusters/services/provider SDKs in default
    checks, and explicit separation of integration and e2e responsibilities.
- Accepted risks:
  - Some examples will remain manual because real external systems are not
    available in default validation.
  - E2E coverage will be representative rather than exhaustive across every
    command permutation.
- Revisit triggers:
  - Runnable examples require external services to stay meaningful.
  - Integration/e2e validation becomes too slow for the default gate and needs
    finer suite tiering.
  - Users need generated hosted documentation rather than in-repo docs.

## Final Approval

- Approval status: approved for phase execution planning; implementation has not
  started
- Approved scope: robust examples, integration testing behavior, e2e testing
  behavior, documentation refinement, and manual/no-example classification for
  unsupported or external-system behavior
- Accepted risks:
  - Manual examples remain manual and excluded from default validation.
  - Stage 22 is docs/example/integration/e2e refinement work, not runtime
    implementation.
- Deferred items:
  - New runtime behavior.
  - Domain-specific tutorial packages.
  - Hosted documentation publishing.
  - External-service-backed default validation.
  - Broad future-feature planning work.

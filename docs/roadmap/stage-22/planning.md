# Roadmap Stage 22 Planning: Examples And Deferred Behavior Documentation

## Metadata

- Roadmap stage: v22
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap.md` defines v21 as cleanup and retention.
  - `docs/roadmap/stage-21/` exists in the current checkout as untracked draft
    cleanup/retention planning artifacts.
  - Stage 22 assumes v21 eventually lands before examples and deferral docs are
    finalized, but the stage can be planned now because it is documentation and
    example-catalog work.
- Planning artifact status: draft from user request
- Current discussion stage: roadmap stage added; formal design-safety review
  and implementation-plan quality gate pending before phase execution
- Stage gates:
  - Roadmap framing: drafted
  - Intent discovery: drafted
  - Capability triage and candidate functional requirements: drafted
  - Functionality agreement review: pending
  - Functionality and behavior confirmation: pending
  - Context compaction/reset checkpoint: not needed yet
  - Design agreement review: pending
  - Design safety review: pending
  - Examples and validation strategy: drafted
  - Phase shaping: drafted
  - Implementation readiness: pending
  - Handoff: pending
- Related implementation plan:
  `docs/roadmap/stage-22/implementation-plan.md`
- Related feature docs:
  - `docs/features/testing.md`
  - `docs/features/cli.md`
  - `docs/features/config.md`
  - `docs/features/pipeline.md`
  - `docs/features/execution.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/reliability.md`
  - `docs/features/preflight.md`
  - `docs/features/plugins.md`
  - `docs/features/remote-stores.md`
  - `docs/features/config-example-coverage.md`
  - `docs/features/slurm-example-coverage.md`
  - `docs/features/authority-example-coverage.md`
  - `docs/features/container-example-coverage.md`
- Blockers:
  - Formal planning confirmation and design-safety review are pending before
    implementation-plan quality gate or phase execution.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| User request | Add a roadmap stage focused on examples and documenting deferred behavior so available functionality can be demonstrated and future roadmap items can be planned. | stage purpose | The stage should demonstrate existing behavior and organize future work, not implement unrelated runtime features. |
| `docs/roadmap.md` | Every roadmap version should have deferred work, primary feature docs, and reviewability expectations. | roadmap fit | Stage 22 turns those scattered deferred notes into an explicit register. |
| `examples/README.md` | Examples are grouped by authoring, execution, and operations, with validation tiers for smoke, full, and manual examples. | example catalog baseline | Stage 22 can consolidate and harden this existing pattern. |
| `docs/features/*-example-coverage.md` | Config, SLURM, authority, and container coverage already track example behavior. | precedent | Stage 22 should unify these coverage documents instead of inventing a separate vocabulary. |
| `docs/features/testing.md` | Default tests should be deterministic, local, and avoid real clusters, cloud services, network, or optional provider dependencies. | validation policy | Runnable examples must respect default-suite constraints. |
| `docs/GLOSSARY.md` | Standardizes terms such as authored config, run URI, run store, stage store, authority, status, and planner action. | vocabulary | Examples and deferred behavior should use repository terms consistently. |
| `docs/structure.md` | Docs define module boundaries, contracts, test expectations, and deferred work. | documentation boundary | Stage 22 is documentation/example hardening, not runtime architecture expansion. |

## Roadmap Extraction

Baseline roadmap outcome:

- Users can find examples by goal and understand which public Python APIs or
  CLI commands each example demonstrates.
- Runnable examples are validated and remain domain-neutral.
- Manual and illustrative examples are clearly labeled with their external
  assumptions.
- Deferred behavior is captured in a structured register with owners,
  rationale, related docs/examples, future-roadmap candidates, and revisit
  triggers.
- Feature docs stop promising future behavior implicitly; unsupported behavior
  is either linked to a future candidate or explicitly out of scope.

Prerequisites:

- Roadmap stages v0 through v21 have established the implemented runtime,
  operational, event, cleanup, and retention surface that the examples should
  demonstrate.
- Existing `examples/` layout and example manifests are available.
- Existing example coverage documents provide a starting point for inventory.

Primary feature docs:

- `testing.md`
- `cli.md`
- `config.md`
- `pipeline.md`
- `execution.md`
- `run-store.md`
- `artifacts.md`
- `reliability.md`
- `preflight.md`
- `plugins.md`
- `remote-stores.md`

Deferred or out-of-scope roadmap work:

- No new runtime, executor, store, cleanup, event, plugin, artifact, or CLI
  functionality beyond docs/examples needed to demonstrate already-implemented
  behavior.
- No domain-specific tutorial project in core Loom.
- No default validation that requires real SLURM, Docker, Apptainer, cloud
  services, network access, hosted services, or provider SDK credentials.
- No hosted documentation site or broad generated-doc tooling unless a later
  docs publishing stage chooses it.

Future-roadmap touchpoints:

- Deferred behavior entries become inputs to future roadmap review rather than
  scope for Stage 22.
- Optional integrations such as MLflow, Prefect, OpenTelemetry, W&B, cloud
  stores, Hydra bridges, and provider-specific deletion can link to the
  register when their future adapter design starts.
- Downstream packages can use the example taxonomy without requiring Loom core
  to absorb project-specific stages or datasets.

Compatibility obligations:

- Existing example IDs and README links should remain stable or have redirects
  and clear migration notes.
- Existing runnable examples should keep passing unless the stage intentionally
  reclassifies them with a documented reason.
- Existing coverage docs should either remain as focused subdocuments or be
  linked from the consolidated inventory.

## User Intent

Target audience:

- New users evaluating what Loom can do now.
- Contributors deciding where to add example coverage for a feature.
- Roadmap planners deciding which deferred behavior deserves a future stage.

User-visible outcome:

- A user can start from `examples/README.md` or the roadmap and find a working
  demonstration of implemented functionality.
- A user can distinguish supported, runnable, opt-in, manual, illustrative,
  `internal_demo`, and deferred behavior without reading implementation plans.
- Maintainers can identify deferred behavior that has repeated user-facing
  pressure and should become a future roadmap candidate.

Success criteria:

- The example inventory covers every first-class implemented feature family by
  this stage or explicitly records why a feature lacks an example.
- Runnable examples have validation coverage.
- Manual examples state their external prerequisites and do not appear as
  default-supported behavior.
- Deferred behavior entries have rationale and revisit triggers.

Non-goals:

- Add new user-facing runtime behavior.
- Add domain-specific examples to core Loom.
- Add provider SDKs or network-backed validation to the default suite.
- Replace feature docs with examples.

Constraints:

- Keep Loom domain-neutral.
- Keep examples local, synthetic, and dependency-light by default.
- Use public APIs and CLI commands, not private test helpers, for user-facing
  examples.
- Mark fixture-heavy support flows as internal demos rather than primary user
  examples.

## Functional Requirements

| ID | Requirement | What | Why | User-visible behavior | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Example inventory | Build a consolidated list of examples with IDs, groups, status, tier, owner docs, owning roadmap stage, and validation command. | Users need to see what is available. | `examples/README.md` and related docs provide a navigable catalog. | Manifest/README consistency tests. | drafted |
| FR-2 | Runnable demonstration coverage | Ensure implemented feature families have runnable examples or explicit no-example rationale. | Available functionality should be demonstrable. | Users can run examples for supported workflows without external services. | Docs/example integration tests. | drafted |
| FR-3 | Manual and illustrative labeling | Classify examples requiring real external systems as manual or illustrative. | Avoid overpromising default support. | READMEs and manifests state prerequisites and validation status. | Manifest validation checks required fields for non-runnable examples. | drafted |
| FR-4 | Deferred behavior register | Record unsupported/deferred behavior with owner, rationale, future candidate, and revisit trigger. | Future roadmap planning needs traceable inputs. | Deferrals have one lookup table rather than scattered vague notes. | Link and schema checks for register entries. | drafted |
| FR-5 | Future-tense docs audit | Replace stale future-tense promises with landed behavior or explicit deferrals. | Docs should be truthful as the roadmap matures. | Feature docs distinguish implemented, deferred, and out-of-scope behavior. | Targeted docs checks and review. | drafted |
| FR-6 | Validation tiers | Keep smoke/full/manual and `internal_demo` classification consistent. | Default checks must remain local and fast. | Users know what `make validate-pr` covers and what is opt-in. | Example harness tests. | drafted |

## Proposed Implementation Shape

Likely docs and examples:

- `examples/README.md`
- `examples/**/README.md`
- `examples/**/example.yaml`
- `docs/features/*-example-coverage.md`
- A new or consolidated deferred-behavior register under `docs/features/` or
  `docs/roadmap/stage-22/`, chosen during phase planning.
- `docs/roadmap.md`
- `docs/roadmap/stage-22/implementation-plan.md`

Likely validation helpers:

- Existing docs/example integration tests.
- Lightweight manifest and link validation for example metadata.
- Targeted tests that assert runnable examples avoid hidden external
  dependencies and generated local state assumptions.

Dependency direction:

- Example docs may import or execute public Loom APIs.
- Validation may read example metadata.
- Core runtime modules must not import examples or docs.

Extension points and flexibility boundaries:

- New example groups may be added by user goal when a roadmap feature has a
  distinct workflow.
- Validation tiers may grow, but default validation must remain local and
  deterministic.
- Deferred behavior entries may point to future candidates without assigning
  implementation scope prematurely.

Future-roadmap impact:

- The deferred-behavior register becomes a staging area for future roadmap
  design reviews.
- Repeated unsupported-behavior entries can justify a later roadmap stage.
- Examples can reveal missing docs or test gaps without forcing feature work
  into Stage 22.

## Design Safety Review Evidence

Status: pending formal design-safety review before phase execution.

Draft safety constraints to review:

- Stage 22 must not implement runtime behavior while documenting examples.
- Examples must not imply domain features are part of core Loom.
- Manual examples must not be counted as default validation evidence.
- Deferred behavior must not become an implicit promise unless it has a future
  candidate and revisit trigger.
- Example validation must not require external services in the default suite.

## Examples And Validation Strategy

Examples to cover:

- Authoring: config composition, includes, replacement overlays, recipes,
  artifact safety, target instantiation, structured errors.
- Execution: local execution, run options, runtime profiles, subprocess,
  Docker fake-backed paths, SLURM dry-run paths, offline-first import.
- Operations: diagnostics, captured logs, failing runs, authority lifecycle,
  resource preflight and leases, submitted status, cleanup/retention when v21
  lands.
- Manual/illustrative: live SLURM, live container daemon, remote/provider
  backends, future optional integrations.

Validation strategy:

- Package/import: only if docs validation adds public helper exports.
- Unit: manifest parsing, inventory generation, and deferred-register schema.
- Contract: stable example/deferred metadata shape if a public schema is added.
- Integration: runnable examples through the docs/example harness.
- E2E: selected CLI examples that are already supported and local.
- Opt-in: manual examples remain documented but excluded from default gates.

## Phase Shaping

| Phase | Focus | Output | Validation |
| --- | --- | --- | --- |
| 1 | Example inventory and metadata contracts | Consolidated inventory shape, manifest/README checks, status/tier vocabulary | unit, integration docs checks |
| 2 | Runnable example coverage and catalog cleanup | Public examples updated or rationalized across authoring/execution/operations | docs/example integration, targeted CLI smoke |
| 3 | Deferred behavior register and roadmap traceability | Structured deferred-behavior register and feature-doc cross-links | schema/link checks, docs review |
| 4 | Final docs audit and validation evidence | Stale promise cleanup, final catalog, suite evidence, implementation-plan metadata | `make validate-pr`, `make test-summary` |

## Implementation Readiness

Status: not ready for phase execution.

Required before implementation begins:

- Confirm the planning artifact or accept the draft scope.
- Complete design-safety review.
- Pass the implementation-plan quality gate.
- Create phase execution plans before any phase implementation.

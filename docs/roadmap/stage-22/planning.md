# Roadmap Stage 22 Planning: Examples And Validation Refinement

## Metadata

- Roadmap stage: v22
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap.md` defines v21 as cleanup and retention.
  - `docs/roadmap/stage-21/` exists in the current checkout with
    cleanup/retention planning artifacts.
  - Stage 22 assumes v21 eventually lands before final example coverage is
    closed, but the stage can be planned now because its focus is examples,
    integration/e2e validation, and documentation refinement.
- Planning artifact status: design-safety reviewed; implementation plan quality
  gate passed
- Current discussion stage: roadmap stage refocused and approved for phase
  execution planning; phase execution plans still required before implementation
- Stage gates:
  - Roadmap framing: completed
  - Intent discovery: completed
  - Capability triage and candidate functional requirements: completed
  - Functionality agreement review: completed
  - Functionality and behavior confirmation: completed by user request to run
    the design review quality gate on 2026-05-18
  - Context compaction/reset checkpoint: not needed yet
  - Design agreement review: completed
  - Design safety review: passed on 2026-05-18
  - Examples and validation strategy: reviewed
  - Phase shaping: reviewed
  - Implementation readiness: ready for phase execution planning
  - Handoff: pending phase execution plans
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
  - None for the stage-level design review quality gate.
  - Phase execution plans are still required before implementation begins.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| User refinement | Focus v22 purely on robust examples, end-to-end testing behavior, integration testing behavior, documentation updates, and refinement. | stage purpose | Planning future features is not primary v22 scope. |
| `docs/roadmap.md` | Every roadmap version should have reviewable scope, tests, and deferred work to prevent scope creep. | roadmap fit | V22 is a docs/examples/testing refinement stage over landed behavior. |
| `examples/README.md` | Examples are grouped by authoring, execution, and operations, with validation tiers for smoke, full, and manual examples. | example catalog baseline | V22 should harden this catalog and its validation evidence. |
| `docs/features/*-example-coverage.md` | Config, SLURM, authority, and container coverage already track example behavior. | precedent | V22 should consolidate and complete example coverage documents. |
| `docs/features/testing.md` | Default tests should be deterministic, local, and avoid real clusters, cloud services, network, or optional provider dependencies. | validation policy | Integration and e2e behavior must stay local/fake-backed by default. |
| `docs/GLOSSARY.md` | Standardizes terms such as authored config, run URI, run store, stage store, authority, status, and planner action. | vocabulary | Examples and validation docs should use repository terms consistently. |
| `docs/structure.md` | Docs define module boundaries, contracts, test expectations, and deferred work. | documentation boundary | V22 should refine docs and validation without expanding runtime architecture. |

## Roadmap Extraction

Baseline roadmap outcome:

- Users can find examples by goal and run the examples that are supported in
  the default local environment.
- Runnable examples are covered by integration or e2e tests.
- Manual and illustrative examples are clearly labeled with their external
  assumptions and are not counted as default validation evidence.
- Integration tests prove example behavior through public APIs, fake/local
  backends, temporary run roots, and realistic local workflows.
- End-to-end tests prove representative CLI and Python user journeys without
  requiring real clusters, cloud services, or network access.
- Documentation accurately describes the validated example behavior and the
  validation tier for each example.

Prerequisites:

- Roadmap stages v0 through v21 have established the implemented runtime,
  operational, event, cleanup, and retention surface that the examples should
  demonstrate.
- Existing `examples/` layout and example manifests are available.
- Existing example coverage documents provide a starting point for inventory.
- Existing integration and e2e test suites provide a place to hang example
  validation without creating a new test framework unless necessary.

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
  functionality beyond docs/examples/tests needed to validate already
  implemented behavior.
- No broad future-feature planning pass.
- No domain-specific tutorial project in core Loom.
- No default validation that requires real SLURM, Docker, Apptainer, cloud
  services, network access, hosted services, or provider SDK credentials.
- No hosted documentation site or broad generated-doc tooling unless a later
  docs publishing stage chooses it.

Future-roadmap touchpoints:

- V22 may reveal missing examples or validation gaps that become later roadmap
  inputs, but it should not assign or implement those features.
- Downstream packages can use the example and validation taxonomy without
  requiring Loom core to absorb project-specific stages or datasets.

Compatibility obligations:

- Existing example IDs and README links should remain stable or have redirects
  and clear migration notes.
- Existing runnable examples should keep passing unless the stage intentionally
  reclassifies them with a documented reason.
- Existing coverage docs should either remain as focused subdocuments or be
  linked from the consolidated inventory.
- New tests should fit the existing package/unit/contract/integration/e2e suite
  vocabulary.

## User Intent

Target audience:

- New users evaluating what Loom can do now.
- Contributors deciding where to add example coverage for a feature.
- Maintainers deciding whether examples, integration tests, and e2e tests
  reflect the public behavior they claim.

User-visible outcome:

- A user can start from `examples/README.md` or the roadmap and find a working
  demonstration of implemented functionality.
- A user can tell which examples run by default, which are full/opt-in, and
  which are manual or illustrative.
- Docs and examples identify the integration or e2e validation path backing
  each runnable workflow.

Success criteria:

- The example inventory covers every first-class implemented feature family by
  this stage or explicitly records why a feature lacks an example.
- Runnable examples have integration and/or e2e validation coverage.
- Manual examples state their external prerequisites and do not appear as
  default-supported behavior.
- Documentation claims about examples and workflows are backed by named tests
  or clearly marked as manual.

Non-goals:

- Add new user-facing runtime behavior.
- Add domain-specific examples to core Loom.
- Add provider SDKs or network-backed validation to the default suite.
- Replace feature docs with examples.
- Run a future-feature planning pass.

Constraints:

- Keep Loom domain-neutral.
- Keep examples local, synthetic, and dependency-light by default.
- Use public APIs and CLI commands, not private test helpers, for user-facing
  examples.
- Mark fixture-heavy support flows as `internal_demo` rather than primary user
  examples.
- Keep integration and e2e tests deterministic and isolated through temporary
  directories and fake/local backends.

## Roadmap Item Explanation

Stage 22 turns implemented Loom behavior into trusted demonstrations. It does
not add runtime features. It answers three practical questions for users and
maintainers:

- What can be tried now?
- What evidence proves the example still works?
- What behavior is intentionally manual, illustrative, or deferred?

The stage matters because earlier roadmap stages add many separate capabilities:
configuration, execution, run stores, artifacts, authority, diagnostics,
subprocesses, SLURM planning, containers, bundles, sweeps, plugins, events, and
cleanup/retention. Without a deliberate examples and validation stage, those
capabilities can exist in code while remaining hard to discover, hard to run,
or easy to overstate in documentation.

Concrete implementation meaning:

| Workstream | Example outcome | Why it matters |
| --- | --- | --- |
| Example inventory | A local execution example records its stable ID, owning feature doc, owning roadmap stage, validation tier, demonstrated public surfaces, and test path in `example.yaml` and the README catalog. | Users should not need to infer what an example proves or whether it is still maintained. |
| Robust runnable examples | A tiny synthetic pipeline can be run from a clean checkout through a public CLI command or public Python API, writing generated files under `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT`. | Examples should be reproducible on a contributor machine without hidden local state. |
| Integration tests | A fake-backed container or SLURM dry-run example asserts generated records, diagnostics, manifests, scripts, or failure files, not only a zero exit code. | Integration tests should prove meaningful collaboration across Loom boundaries. |
| E2E tests | A representative CLI journey can run a small pipeline, inspect status, and exercise a stable diagnostic or failure path. | Users need confidence that documented workflows work as workflows, not only as isolated functions. |
| Manual and deferred behavior | Live SLURM submission, real Docker or Apptainer daemons, hosted authority services, provider SDKs, and cloud or network-backed flows are marked manual unless default validation can prove them deterministically. | Documentation should not imply default support for behavior the local suite does not validate. |
| Documentation refinement | Feature docs link examples to validation tiers or named test paths, and manual guidance names the external capability it requires. | Claims in docs become reviewable evidence instead of prose that can drift. |

For example, SLURM support should distinguish a runnable dry-run planning
example from a live-cluster submission example. The dry-run example can be
validated locally by checking generated scripts, manifests, dependencies, and
worker commands. The live-cluster example remains manual because it requires a
real scheduler. Both examples are useful, but only the dry-run example counts as
default validation evidence.

Similarly, a container example can demonstrate command construction, preflight
diagnostics, and failure recording with fake/local command behavior. It should
not require a Docker daemon in the default suite. If a real-daemon walkthrough is
kept, it must be marked manual and explain the prerequisite.

The intended end state is a catalog where a user can browse by goal, choose an
example, see whether it is smoke, full, manual, illustrative, or
`internal_demo`, run supported examples locally, and trace each runnable claim
back to integration or e2e evidence.

## Functional Requirements

| ID | Requirement | What | Why | User-visible behavior | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Example inventory | Build a consolidated list of examples with IDs, groups, status, tier, owner docs, owning roadmap stage, and validation command. | Users need to see what is available. | `examples/README.md` and related docs provide a navigable catalog. | Manifest/README consistency tests. | drafted |
| FR-2 | Robust runnable examples | Ensure implemented feature families have runnable examples or explicit no-example rationale. | Available functionality should be demonstrable. | Users can run examples for supported workflows without external services. | Docs/example integration tests. | drafted |
| FR-3 | Integration testing behavior | Validate examples through public APIs, fake/local backends, temporary run roots, and realistic local workflows. | Examples should prove integration boundaries, not only snippets. | Example docs cite the integration tests that back them. | Targeted integration suite paths. | drafted |
| FR-4 | End-to-end testing behavior | Validate representative CLI and Python user journeys across authoring, execution, operations, diagnostics, and cleanup-related flows where available. | Users need confidence in full workflows. | Example docs cite e2e or equivalent workflow tests. | Targeted e2e suite paths and golden summaries where useful. | drafted |
| FR-5 | Manual and illustrative labeling | Classify examples requiring real external systems as manual or illustrative. | Avoid overpromising default support. | READMEs and manifests state prerequisites and validation status. | Manifest validation checks required fields for non-runnable examples. | drafted |
| FR-6 | Documentation refinement | Update READMEs and feature docs so claims align with validated example behavior. | Docs should be truthful and maintainable. | Feature docs distinguish validated examples from manual guidance. | Targeted docs checks and review. | drafted |
| FR-7 | Validation tiers | Keep smoke/full/manual and `internal_demo` classification consistent. | Default checks must remain local and fast. | Users know what `make validate-pr` covers and what is opt-in. | Example harness tests. | drafted |

## Proposed Implementation Shape

Likely docs and examples:

- `examples/README.md`
- `examples/**/README.md`
- `examples/**/example.yaml`
- `docs/features/*-example-coverage.md`
- `docs/features/testing.md`
- `docs/roadmap.md`
- `docs/roadmap/stage-22/implementation-plan.md`

Likely validation helpers:

- Existing docs/example integration tests.
- Lightweight manifest and link validation for example metadata.
- Targeted integration tests that assert examples avoid hidden external
  dependencies and generated local state assumptions.
- Targeted e2e tests for representative public CLI/Python workflows.

Dependency direction:

- Example docs may import or execute public Loom APIs.
- Validation may read example metadata.
- Core runtime modules must not import examples or docs.

Extension points and flexibility boundaries:

- New example groups may be added by user goal when a roadmap feature has a
  distinct workflow.
- Validation tiers may grow, but default validation must remain local and
  deterministic.
- Integration/e2e helpers should validate examples, not become new public
  runtime APIs.

Future-roadmap impact:

- Example and validation gaps can inform later roadmap review.
- V22 does not assign or implement future features.

## Design Pass Notes

Design pass status: completed locally; formal design-safety review passed on
2026-05-18.

Design findings and resolutions:

- The initial refocused scope was directionally right but too broad around the
  word "robust." This artifact now defines robustness through manifest
  metadata, hermetic execution, explicit validation paths, output assertions,
  and docs alignment.
- Integration and e2e testing need separate responsibilities. Integration tests
  should prove package boundaries and persisted/fake-backend collaboration;
  e2e tests should prove representative user journeys through CLI or public
  Python APIs.
- The stage should not turn into an unbounded coverage sweep. Each example
  family needs either validated runnable coverage, manual classification, or a
  documented no-example rationale.
- Manual examples remain useful only when they name prerequisites and avoid
  being counted as default evidence.

## Quality Bar

A robust runnable example must:

- Use public Python APIs or supported CLI commands.
- Use synthetic, domain-neutral data and project-local stage code.
- Run from a clean checkout with generated outputs redirected through
  `LOOM_EXAMPLE_OUTPUT_ROOT` and `LOOM_EXAMPLE_RUN_ROOT` where applicable.
- Avoid hidden reliance on previously generated local state.
- Assert or print stable, reviewable facts rather than long incidental command
  output.
- Have a named validation path in integration or e2e tests.
- Document what it proves and what external behavior it does not prove.

An integration test for examples must:

- Cross at least one meaningful boundary, such as config plus execution,
  runner plus authority, CLI plus store inspection, fake backend plus public
  API, or docs harness plus example entrypoint.
- Use temporary directories and fake/local backends by default.
- Assert persisted records, command/API results, diagnostics, or generated
  artifacts rather than only process exit status.

An e2e test for examples must:

- Exercise a representative user journey through CLI commands or public Python
  APIs.
- Validate user-visible success and at least one stable failure or diagnostic
  behavior where the workflow naturally has one.
- Stay representative rather than exhaustive; lower-level tests remain
  responsible for option permutations and edge-case matrices.

Documentation refinement must:

- Link example claims to validation tiers or named test paths.
- Keep manual prerequisites explicit.
- Remove stale text when examples or tests prove a behavior has changed.
- Avoid claiming support for external systems that default validation fakes or
  excludes.

## Coverage Matrix

| Area | Example expectation | Integration expectation | E2E expectation | Manual boundary |
| --- | --- | --- | --- | --- |
| Authoring and config | Runnable examples for composition, includes, overlays, recipes, target instantiation, artifact safety, and structured errors | Public composition APIs exercised with manifest/source/fingerprint assertions | Representative Python authoring workflow if not already covered by integration harness | None expected |
| Local execution | Runnable local execution and resume examples | Runner/store/artifact collaboration with temporary run roots | CLI or Python run/resume journey | None expected |
| Runtime profiles and run options | Runnable public API or CLI examples | Option normalization through execution or preflight boundary | Representative run-options journey where user-visible | None expected |
| Subprocess and workers | Runnable fake/local subprocess examples | Worker command, logs, failure records, and store behavior | CLI subprocess journey if command surface is public | Real external process managers remain out of scope |
| SLURM | Runnable dry-run examples and illustrative live examples | Script/manifest generation with fake/no scheduler | Dry-run CLI journey only | Live cluster submission and cancellation remain manual |
| Containers | Runnable fake-Docker examples | Fake command runner, preflight, failure diagnostics, and generated records | Docker CLI journey with fake daemon only | Real Docker/Apptainer runtimes remain manual |
| Authority and operations | Runnable lifecycle, offline import, resource, diagnostics, and failure examples | Authority modes, service/fake backends, diagnostics, and read models | Representative operations CLI journey | Hosted services remain out of scope |
| Reliability, events, cleanup, retention | Examples once surfaces exist, or explicit no-example rationale | Facts, diagnostics, fake event/cleanup paths, and persisted evidence | Representative inspect/cleanup/event journey where public | External sinks/provider deletion remain manual or excluded |
| Bundles, sweeps, plugins, artifacts | Runnable examples for implemented public workflows | Export/import, sweep manifest, plugin listing/loading, and artifact refs through public boundaries | Representative CLI/Python journey where user-facing | Real provider/plugin integrations remain manual |

## Design Choices And Tradeoffs

| Decision | Selected approach | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Example metadata | Keep `example.yaml` as the inventory source and validate it with tests | Matches current repository pattern and avoids a separate docs database | Metadata becomes too complex for YAML validation |
| Validation tiers | Preserve smoke/full/manual plus `internal_demo` classification | Aligns with existing manifests and docs harness | Full examples need stricter default-gate treatment |
| Integration vs. e2e | Split responsibilities by boundary proof versus user journey proof | Prevents e2e tests from becoming expensive edge-case matrices | Users cannot map examples to actual workflows |
| External systems | Use fake/local default validation and keep real systems manual | Keeps `make validate-pr` deterministic and dependency-light | A deterministic hosted or fake-backed acceptance fixture exists |
| Example gaps | Record no-example rationale instead of implementing missing behavior | Keeps V22 from becoming feature work | A missing example blocks user adoption of already implemented behavior |

## Design Safety Review Evidence

Status: passed on 2026-05-18.

Review outcome:

| Criterion | Evidence | Result |
| --- | --- | --- |
| Scope control | Non-goals, phase scopes, and stop conditions all state that missing runtime behavior becomes no-example rationale or manual classification, not feature work. | pass |
| Domain neutrality | Examples must use synthetic data, project-local stage code, public APIs/CLI, and must not import downstream project packages. | pass |
| External dependency safety | SLURM, containers, provider SDKs, cloud, network, hosted services, and real daemons remain fake/local-backed or manual in default validation. | pass |
| Integration/e2e split | Integration proves component collaboration and persisted/fake-backend behavior; e2e proves representative user journeys. | pass |
| Public contract safety | Example metadata remains docs/test-owned YAML unless future validation pressure justifies a stable schema; runtime modules must not import examples or docs tooling. | pass |
| Future-roadmap impact | Example and validation gaps may feed later roadmap review, but V22 does not assign or implement future features. | pass |
| Reviewability | Four phases have explicit ownership, validation obligations, acceptance evidence, risks, and stop conditions. | pass |

Accepted risks:

- Some external-system workflows remain manual because real clusters, daemons,
  providers, and hosted services are not deterministic default dependencies.
- E2E coverage is representative rather than exhaustive; option permutations
  remain lower-level test work.
- Full examples may remain outside the fastest smoke path if default validation
  would become too slow.

No blocking design-safety findings remain.

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
- Unit: manifest parsing and inventory generation if new validation helpers are
  introduced.
- Contract: stable example metadata shape if a public schema is added.
- Integration: runnable examples through the docs/example harness and
  fake/local backend workflows.
- E2E: selected CLI and Python workflows that are supported and local.
- Opt-in: manual examples remain documented but excluded from default gates.

## Phase Shaping

| Phase | Focus | Output | Validation |
| --- | --- | --- | --- |
| 1 | Example inventory and metadata contracts | Consolidated inventory shape, manifest/README checks, status/tier vocabulary | unit, integration docs checks |
| 2 | Robust runnable examples and integration behavior | Public examples updated or rationalized across authoring/execution/operations with integration coverage | docs/example integration, targeted integration suite paths |
| 3 | End-to-end workflow behavior | Representative CLI/Python journeys covered by e2e or equivalent workflow tests | targeted e2e and CLI workflow checks |
| 4 | Documentation refinement and final validation | Stale text cleanup, example output alignment, final catalog, suite evidence | `make validate-pr`, `make test-summary` |

## Implementation Readiness

Status: ready for phase execution planning; implementation has not started.

Required before implementation begins:

- Create phase execution plans before any phase implementation.

Completed gates:

- Planning and behavior scope confirmed by the user request to run the design
  review quality gate on 2026-05-18.
- Design-safety review passed on 2026-05-18.
- Implementation-plan quality gate passed on 2026-05-18.

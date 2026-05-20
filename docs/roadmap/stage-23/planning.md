# Roadmap Stage 23 Planning: Standalone Config Package Extraction

## Metadata

- Roadmap stage: `v23`
- Source roadmap: `docs/roadmap.md`
- Previous version status: Stage 22 implementation plan records complete; all
  phases merged into `develop`.
- Planning artifact status: accepted for implementation-plan drafting after
  design-safety review passed
- Current discussion stage: implementation-plan quality gate passed
- Stage gates:
  - Roadmap framing: completed; user priority is clean separation of
    responsibilities, with Loom retaining functionality required by Loom
    runtime itself
  - Intent discovery: completed; hard switch, no `loom.config` shim, and
    package-owned duplicated helper functionality confirmed
  - Capability triage and candidate functional requirements: completed;
    included capabilities, explicit deferrals, and out-of-scope capabilities
    confirmed
  - Functionality agreement review: completed; queue resolved with no
    unresolved high-impact requirement questions
  - Functionality and behavior confirmation: completed; behavior baseline
    confirmed by user on 2026-05-20
  - Context compaction/reset checkpoint: completed; next pass should reload this
    artifact and the implementation-plan draft before plan-quality review or
    phase execution
  - Design agreement review: completed; design queue resolved with no
    unresolved high-impact `needs discussion` or blocked items
  - Design safety review: completed on 2026-05-20; passed with recorded
    recommendations, accepted risks, and no reopened decisions or blockers
  - Examples and validation strategy: reviewed by design-safety; detailed
    validation commands and golden fixture locations are recorded in the
    implementation-plan draft
  - Phase shaping: reviewed by design-safety; six-phase default shape is
    suitable unless implementation planning finds a narrower reviewable split
  - Implementation readiness: implementation-plan quality gate passed on
    2026-05-20; ready for Phase 1 execution planning
  - Handoff: completed for implementation-plan draft and quality gate
  - Post-gate naming update: user renamed the standalone config package to
    `weave` on 2026-05-20; responsibility split and phase structure are
    unchanged
- Related implementation plan: `docs/roadmap/stage-23/implementation-plan.md`
- Related feature docs:
  - `docs/features/config.md`
  - `docs/features/serialization.md`
  - `docs/features/fingerprints.md`
  - `docs/features/errors.md`
  - `docs/features/plugins.md`
  - `docs/features/testing.md`
  - `docs/features/cli.md`
  - `docs/features/config-test-matrix.md`
  - `docs/structure.md`
  - `docs/loom.md`
- Blockers:
  - None for roadmap-stage planning.
  - No design-safety blockers or reopened `needs discussion` decisions remain.
  - Implementation-plan drafting was explicitly approved by the user on
    2026-05-20.
  - The implementation-plan draft records package layout, dependency metadata,
    import rewrite boundaries, test command names, golden artifact fixtures,
    and package-local validation entrypoints.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | Defines v23 as hard-switching `loom.config` into a standalone `weave` library with package-local tests/examples and explicit Loom adapter edges. | Roadmap scope, exit criteria, deferrals, feature-doc links | Current worktree already adds the v23 roadmap entry and module-coverage updates. |
| `docs/roadmap/stage-22/implementation-plan.md` | Records Stage 22 complete with all phases merged. | Prerequisite status | Stage 23 can be planned as the next roadmap unit. |
| `docs/loom.md` | Loom is the workflow/runtime package for domain-neutral pipeline mechanics; config composition is one supported mechanism, not the runtime purpose. | Boundary framing | Stage 23 should preserve Loom as the runtime package while extracting trusted config authoring. |
| `docs/structure.md` | Owns package boundaries, import direction, and source-tree layout. Current target tree still shows `src/loom/config`. | Layout and documentation impact | Stage 23 must update the source-tree map when the package split is implemented. |
| `docs/features/config.md` | `loom.config` owns composition, includes, overlays, recipes, `_target_`, redaction, provenance, manifests, fingerprints, and path-aware config errors; it must not execute stages or import pipeline/stores/CLI. | Config package ownership | The future package should preserve the same behavior under `weave`. |
| `docs/features/serialization.md` | Plain-data and stable JSON helpers are shared foundations for config records, stores, fingerprints, and documents. | Shared-helper ownership | User priority indicates Loom should keep runtime-required serialization functionality; `weave` may own config-specific equivalents. |
| `docs/features/fingerprints.md` | Hash helpers and digest/fingerprint vocabulary underpin config fingerprints and runtime fingerprints; import-boundary tests currently require `loom.fingerprints` not to import config. | Digest/fingerprint split risk | Config-owned hashing may move down, but runtime fingerprint policy must remain coherent. |
| `docs/features/errors.md` | `ConfigError` is currently a broad Loom error root and is re-exported from `loom.config`; CLI maps error roots to exit categories. | Error compatibility and CLI diagnostics | Stage 23 must define config-owned error roots and Loom-side handling. |
| `docs/features/plugins.md` | Recipe entry-point loading is registry-ready and currently connects plugin discovery to config recipe catalogs; plugin loading remains explicit trusted code execution. | Recipe plugin ownership | Config recipe plugin hooks should move with `weave` where config-owned. |
| `docs/features/testing.md` | Defines unit, package, integration, e2e, contract, import-boundary, marker, and local-check expectations. | Test-suite split | Stage 23 needs package-local config tests plus combined repo validation. |
| `docs/features/cli.md` | CLI passes config composition options to config APIs and owns final command behavior and output. | CLI adapter impact | CLI should call `weave` at adapter edges without moving runtime orchestration into config. |
| `src/loom/config/**` | Current config implementation lives inside Loom and imports Loom serialization, fingerprints, errors, and version metadata. | Current dependency inventory | This is the primary code movement area for Stage 23. |
| `tests/**/config*`, `tests/**/test_config*` | Config coverage currently spans package, contract, integration, and e2e suites under Loom's test tree. | Test relocation and validation planning | Stage 23 must preserve coverage while splitting ownership. |
| `examples/authoring/**` | Current authoring examples import `loom.config`. | Example relocation | Config authoring examples should move beside `weave`. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and architecture docs | `docs/roadmap.md`, `docs/loom.md`, `docs/structure.md`, `docs/roadmap/stage-22/implementation-plan.md` | v23 is a package-boundary stage after completed v22; durable docs must change alongside package layout. | Later design pass should inspect any updated Stage 23 roadmap diff before implementation planning. |
| Feature docs | `config.md`, `serialization.md`, `fingerprints.md`, `errors.md`, `plugins.md`, `testing.md`, `cli.md` | Config ownership is well documented, but the docs still use `loom.config` terminology and assume in-package placement. | Need design agreement on compatibility policy, docs terminology, and helper ownership. |
| Source and tests | `src/loom/config/**`, imports referencing `loom.config`, package import-boundary tests, config integration/e2e tests, authoring examples | Config is currently implemented under `src/loom/config`; runtime code mostly avoids composition internals, with notable current imports from sweeps, queue config, diagnostics preflight, CLI config commands, plugin diagnostics, and examples. | Implementation planning must split explicit config adapter paths from runtime-owned duplicate helper behavior. |
| Prior or adjacent plans | Stage 22 implementation plan and current v23 planning draft | Stage 22 is complete; existing v23 draft captures hard-switch intent and package/test/example separation. | No Stage 23 implementation plan exists yet. |

## Roadmap Extraction

Baseline roadmap outcome:

- Extract trusted config authoring into a standalone `weave` distribution
  with import package `weave`, while `loom` remains the workflow/runtime
  package and depends on config only through explicit adapter paths.

Prerequisites:

- Stage 22 example and validation refinement has landed.
- Existing config composition, recipes, target instantiation, redaction,
  provenance, composition manifests, source artifact records, raw source
  snapshots, and config fingerprints exist under `src/loom/config`.
- Current Loom test harness and import-boundary checks exist and can be extended
  for the package split.

Primary feature docs:

- `config.md`
- `serialization.md`
- `fingerprints.md`
- `errors.md`
- `plugins.md`
- `testing.md`
- `cli.md`
- `examples/`
- `config-test-matrix.md`

Deferred or out-of-scope roadmap work:

- Publishing `weave` to a separate repository.
- Supporting a compatibility shim for `from loom.config import ...`, unless the
  implementation plan explicitly accepts a short-lived shim.
- Splitting Loom workflow/runtime into more installable packages.
- Reworking config semantics, recipe behavior, include resolution, provenance
  schema, or fingerprint policy beyond what package extraction requires.
- Adding Hydra compatibility, untrusted-config sandboxing, or new config
  language features.

Future-roadmap touchpoints:

- Future separate repository extraction for `weave`.
- Plugin recipe entry-point ownership and explicit loading semantics.
- CLI config entrypoints and command diagnostics.
- Runtime sweep override parsing, because current sweep specs import config
  override parsing.
- Runtime serialization and fingerprint helpers should remain Loom-owned when
  Loom requires them for runtime records, stores, resume, artifacts, or
  execution. `weave` may own config-specific equivalents for its own
  artifacts.
- Documentation and examples that distinguish config authoring from runtime
  workflow behavior.

Compatibility obligations:

- Preserve deterministic config artifacts unless a break is explicitly accepted:
  resolved config, redacted config, composition manifests, recipe manifests,
  source artifact records, raw source snapshot records, fingerprint records,
  and structured config error payloads.
- Preserve Loom runtime behavior that consumes composed config through public
  CLI/Python adapter paths.
- Preserve import-boundary intent: `weave` imports no `loom`; Loom runtime
  internals do not import config composition internals.

## Stage Briefing

What this stage is:

- Stage 23 is a package-boundary and ownership stage. It turns the trusted config
  authoring layer from an in-package `loom.config` subsystem into an
  independently installable `weave` library whose import package is
  expected to be `weave`.

Why this stage exists:

- Config authoring has become a coherent product surface on its own: loading,
  composition, overlays, includes, replacement, overrides, recipes, `_target_`
  instantiation, redaction, provenance, manifests, and artifact-safe
  fingerprints. The roadmap now wants that surface to be movable as a unit,
  with its own tests and examples, while Loom focuses on workflow/runtime
  mechanics.

Impacted or linked work:

- Directly impacted code includes `src/loom/config/**`, config public imports,
  recipe plugin integration, config-related CLI adapter paths, config tests,
  authoring examples, packaging metadata, type markers, build configuration,
  import-boundary tests, and documentation links.
- Linked runtime areas include pipeline specs and execution only where they
  consume already composed plain data. Runtime internals should not gain new
  dependency on composition internals during the split.

Likely public surfaces and durable artifacts:

- Public Python import paths will change from `loom.config` to `weave` for
  config-library users.
- The `weave` distribution should publish `weave`, `py.typed`, and
  package-local config examples and tests.
- Loom CLI and Python adapter paths should call `weave` to compose
  authored configs before handing plain data or config artifact records to Loom
  runtime code.
- Durable config artifacts must remain stable unless a deliberate break is
  recorded: composition manifests, source artifact records, raw source snapshot
  records, recipe manifests, redacted config, resolved config outputs exposed to
  callers, and config fingerprint records.

Structure rationale:

- The stage is placed after Stage 22 because examples and validation are already
  consolidated, making it possible to move config examples/tests with evidence
  instead of first inventing coverage during extraction.
- It is intentionally a hard-switch pre-release stage. That keeps the split
  reviewable and avoids a long-lived compatibility layer inside Loom unless the
  implementation plan later finds a concrete need.
- `loom` may depend on `weave`, so no third shared core package is
  required by default. Config-owned helpers can move into `weave`, but
  Loom runtime-required helpers should stay in Loom even when that means small
  duplicated helper implementations across the two packages.

Visible assumptions, risks, and constraints:

- Assumption: pre-release users can tolerate import-path changes from
  `loom.config` to `weave`.
- Assumption: clean responsibility separation is more important than maximizing
  helper reuse between the packages.
- Risk: duplicating small plain-data, stable JSON, digest, fingerprint, or error
  helpers can create drift if golden tests do not lock config artifact behavior.
- Risk: moving helpers used broadly by Loom into `weave` would create an
  inverted dependency where Loom runtime internals lean on the config package
  for functionality Loom should own.
- Risk: config artifact fingerprints or manifests can drift silently if golden
  fixtures are not established before movement.
- Risk: package metadata, editable installs, coverage configuration, Pyright,
  Ruff, and pytest discovery can become noisy if the monorepo package layout is
  not planned before code movement.
- Constraint: `weave` must not import `loom`.
- Constraint: Loom remains domain-neutral and must not move runtime semantics
  into the config package.
- Constraint: default validation should stay local and dependency-light.

User clarification questions and resolved answers:

- Existing draft notes already record a preferred hard switch, `weave`
  import package, `weave` distribution name, no separate repository in
  this stage, and no compatibility shim by default.
- User clarified that the planning priority is a clean separation of
  responsibilities: `loom` should handle functionality required by the Loom
  runtime itself, rather than relying on `weave` as a generic utility
  package.
- User confirmed the hard-switch policy: do not preserve `loom.config` through
  a compatibility shim by default.
- User confirmed that duplicated functionality should exist in each library
  where both libraries require the same category of behavior. Loom owns its
  runtime-required implementation; `weave` owns its config-specific
  implementation.

## User Intent

Target audience:

- Users and downstream projects that want the config authoring library as a
  reusable package.
- Loom runtime users who still expect CLI and Python workflow entrypoints to
  compose authored configs through supported adapter paths.
- Future maintainers who may move `weave` to a separate project.

User-visible outcome:

- Two clear libraries:

```text
weave
  standalone trusted config authoring library

loom
  workflow/runtime library that depends on weave
```

Success criteria:

- `weave` installs, imports, tests, and validates examples independently.
- `weave` imports no `loom` modules.
- `loom` depends on `weave` and its config-facing CLI/Python workflows
  still work.
- Runtime internals consume plain data, runtime specs, and persisted records;
  they do not depend on config composition internals.
- Config artifacts remain golden-test stable or explicit breaks are documented.

Non-goals:

- No new config language features.
- No Hydra compatibility layer.
- No untrusted-config sandbox.
- No public workflow/runtime redesign beyond import rewiring and adapter cleanup
  required by package extraction.
- No split of `loom` workflow/runtime into additional installable packages.
- No immediate move to a separate repository.
- No default requirement to preserve `from loom.config import ...`.

Constraints:

- `weave` must not import `loom`.
- Loom config adapter paths may import `weave`; Loom runtime-required
  serialization, fingerprinting, and error functionality should remain
  Loom-owned.
- Config-owned tests and examples should live beside the config package.
- Authored configs remain trusted project code.
- Keep Loom domain-neutral.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- Stage 23 is about standalone config package extraction and not about new
  runtime behavior or new config semantics.
- Stage 22 is complete, so Stage 23 planning can proceed as the next roadmap
  unit.
- Planning priority is clean separation of responsibilities: Loom keeps
  functionality required by Loom runtime behavior; `weave` owns
  config-specific functionality and should not become Loom's generic utility
  provider.

Intent discovery locked decisions:

- Two-library product shape is confirmed: `weave` is the config authoring
  distribution and import package, and Loom is the workflow/runtime package.
- Hard switch is confirmed: no default `loom.config` compatibility shim.
- Duplicated helper functionality is confirmed where both packages need similar
  behavior. Loom keeps runtime-required serialization, fingerprinting, error,
  and related helpers; `weave` implements config-specific equivalents.

Capability triage and candidate-functional-requirement readback:

- Confirmed included capabilities: create `weave`, move
  config implementation into that package, create config-specific duplicated
  helper functionality where needed, rewire Loom config adapter paths, relocate
  config tests and examples beside the config package, and add golden artifact
  compatibility tests before or during movement.
- Confirmed out-of-scope capabilities: `loom.config` compatibility shim,
  separate repository publication, Hydra compatibility, new config language
  semantics, untrusted-config sandboxing, and broader Loom runtime redesign.

Functionality-agreement readback:

- Resolved. The requirement queue has no unresolved high-impact questions.
- Hard switch/no shim and duplicated package-owned helper functionality are
  confirmed by user decision.
- Golden artifact compatibility, package-local tests/examples, and Loom adapter
  rewiring are confirmed by roadmap evidence and user-approved capability
  triage.

Functionality and behavior confirmation readback:

- Confirmed by user on 2026-05-20.
- Included behavior: direct config-library users import and use `weave`;
  Loom CLI/Python config workflows continue through explicit adapter paths;
  config-owned tests/examples move beside `weave`; golden compatibility
  tests protect config artifacts.
- Default behavior: hard switch with no `loom.config` shim; duplicate helper
  implementations by package ownership; no config semantic changes; no separate
  repository publication in this stage.
- Failure behavior: config errors remain structured and path-aware; Loom CLI
  adapters continue to present config failures as config-facing diagnostics;
  config artifact compatibility breaks require explicit acceptance.
- Explicit deferrals: repository split, shim, Hydra bridge, new config language
  features, untrusted-config sandboxing, and runtime redesign.

Design-agreement follow-up:

- Completed in this pass. Treat roadmap framing, intent, capability triage,
  functionality agreement, behavior baseline, and design agreement as locked
  unless the user explicitly reopens them.
- Design-safety review has completed and did not reopen any locked decision.
  The user explicitly approved continuing through implementation-plan drafting
  on 2026-05-20.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | v23 is a standalone config package extraction stage after complete v22; planning priority is clean responsibility separation. | Preserve hard-switch roadmap framing; do not start implementation planning yet. | None from roadmap framing. | Intent discovery. |
| Intent discovery | Two-library shape, hard switch, no shim, and duplicated package-owned helpers are confirmed. | `weave` import package; `weave` distribution name unless implementation planning finds a packaging reason to change; Loom keeps runtime-required functionality. | None for intent. | Capability triage. |
| Capability triage and candidate functional requirements | Included: package creation, namespace move, duplicated config-specific helpers, Loom adapter rewiring, test/example relocation, golden compatibility. Out of scope: shim, separate repo publication, new config semantics, Hydra bridge, runtime redesign. | Treat roadmap implement bullets as included capabilities. | None for capability triage. | Functionality agreement. |
| Functionality agreement review | FRQ-1 through FRQ-5 resolved. | Hard switch/no shim; duplicated helpers by package ownership; broad config artifact golden coverage; package-local tests/examples; explicit Loom config adapters. | None for functionality agreement. | Behavior confirmation. |
| Functionality and behavior confirmation | Behavior baseline confirmed: hard switch to `weave`, unchanged config semantics/artifacts except explicit accepted breaks, Loom config adapter workflows continue, runtime internals avoid config composition internals. | No shim; duplicated package-owned helpers; config artifacts protected by golden tests. | None for behavior baseline. | Context checkpoint. |
| Context compaction/reset checkpoint | Checkpoint recorded and design agreement resumed from this artifact. | Keep confirmed functionality and behavior locked. | None. | Design agreement review. |
| Design agreement review | Resolved: package layout, helper ownership, adapter boundaries, plugin split, error handling, sweep override ownership, golden fixture timing, and validation split are recorded recommendations. | Use package-owned duplicate helpers; keep Loom runtime helpers in Loom; keep `weave` self-contained. | None for design agreement. | Design-safety review. |
| Design safety review | Completed on 2026-05-20; gate passed with recorded recommendations and accepted risks. | Keep locked decisions unless future implementation evidence finds an actual compatibility or packaging blocker. | None. | Final planning confirmation. |
| Examples and validation strategy | Reviewed by design-safety and carried into the implementation-plan draft. | Config examples move to package-local examples; runtime examples stay under Loom; golden config artifact coverage is mandatory. | None for planning. | Phase execution plans should preserve the recorded suite obligations. |
| Phase shaping | Reviewed by design-safety and refined in the implementation-plan draft. | Keep boundary prep, package scaffold, namespace move, adapter rewiring, test/example relocation, docs/hardening reviewable. | None for planning. | Start with Phase 1 execution planning. |
| Implementation readiness | No design-safety blockers remain; user approved implementation-plan drafting on 2026-05-20; plan quality gate passed on 2026-05-20. | Phase execution planning may begin from the implementation plan. | None for planning. | Phase 1 execution planning. |
| Handoff | Completed for implementation-plan draft and quality gate. | Use the implementation-plan draft as the next workflow artifact. | None for planning. | Draft Phase 1 execution plan when assigned. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Create `weave` distribution and `weave` import package | include confirmed | Primary roadmap outcome. | Package metadata and monorepo layout need design agreement. |
| Move config composition and authoring implementation into `weave` | include confirmed | This is the core extraction. | Includes load, compose, merge, overrides, interpolation, includes, recipes, instantiation, redaction, provenance, artifacts, fingerprints, and target checks. |
| Move config-specific plain-data, stable JSON, digest, fingerprint, and errors into `weave` | include confirmed | Gives config artifacts a self-contained implementation without making `weave` depend on Loom. | Loom should keep functionality required by Loom runtime behavior; duplicated helpers are required where both libraries need equivalent behavior. |
| Rewire Loom CLI/Python config adapter paths to `weave` | include confirmed | Loom still needs authored config workflows. | Runtime internals should consume plain data and config-produced records. |
| Relocate config tests into package-local test tree | include confirmed | Enables future repository extraction. | Keep Loom workflow/runtime tests under Loom. |
| Relocate config authoring examples into package-local examples | include confirmed | Examples should move with the package later. | Authoring examples must not import Loom runtime modules. |
| Add golden artifact compatibility tests before movement | include confirmed | Prevents silent manifest/fingerprint drift. | Golden fixture scope confirmed for all documented config artifacts. |
| Preserve `loom.config` compatibility shim | out of scope confirmed | User confirmed hard switch and no default shim. | Can be reopened only by explicit future user instruction. |
| Publish `weave` to a separate repository | out of scope confirmed | Roadmap defers repository split. | Stage should prepare layout/tests/examples for future move. |
| Add new config semantics or Hydra compatibility | out of scope confirmed | Would expand beyond extraction. | Feature behavior should remain stable. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Confirm hard-switch compatibility policy for `loom.config`. | none | 1 | Keep no compatibility shim by default. | Determines import rewrite scope, docs language, and migration burden. | User confirmed hard switch and no shim. | confirmed |
| FRQ-2 | Confirm helper ownership for plain-data, stable JSON, digest, fingerprint, and config errors. | FRQ-1 | 2 | Keep Loom runtime-required helpers in Loom; give `weave` config-specific helper implementations under config-owned modules. | This is the main dependency-direction risk. | User clarified the responsibility principle; exact module split remains design work. | confirmed |
| FRQ-3 | Confirm golden artifact compatibility scope. | none | 3 | Golden-test resolved config, redacted config, composition manifests, recipe manifests, source records, raw source snapshot records, fingerprint records, and structured config error payloads. | Without fixtures, extraction can silently change durable artifacts. | Roadmap evidence and capability triage confirm this scope. | confirmed |
| FRQ-4 | Confirm test/example relocation as required behavior, not only cleanup. | none | 4 | Treat package-local tests/examples as exit criteria. | This determines package validation and future repo extraction readiness. | Roadmap evidence and capability triage confirm this scope. | confirmed |
| FRQ-5 | Confirm Loom adapter behavior after extraction. | FRQ-1, FRQ-2 | 5 | CLI and Python workflow entrypoints call `weave`; runtime internals consume plain mappings and records. | Prevents config package extraction from turning into runtime redesign. | Roadmap evidence and responsibility-separation intent confirm this scope. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Standalone config package | none | Add an installable `weave` package exposing `weave`. | Makes config authoring reusable and movable. | Package metadata, source tree, typing marker, public exports. | Users import `weave` directly for config authoring. | `weave` imports no `loom`. | Independent package import and installation. | Package import tests and build checks. | confirmed |
| FR-2 | Config implementation namespace move | FR-1 | Move config implementation out of `src/loom/config`. | Completes the hard switch. | Composition, recipes, instantiation, redaction, provenance, artifacts, fingerprints, errors. | `weave.compose_config`, recipe APIs, and instantiation APIs replace `loom.config` for config users. | Existing behavior should be preserved. | Extracted config library. | Existing config tests rerun under package-local test tree. | confirmed |
| FR-3 | Helper ownership split | FR-1 | Keep Loom runtime-required helpers in Loom and move or duplicate only config-specific helpers needed for config-owned records into `weave`. | Avoids circular imports and keeps responsibilities clean without adding a third package. | Plain-data, stable JSON, digest, config fingerprint helpers, config errors. | No direct user behavior except import paths and error classes. | Loom runtime modules keep using Loom-owned helpers; `weave` imports no Loom code and owns its config artifact helpers. | Clean package dependency direction. | Import graph tests and golden artifact tests. | confirmed |
| FR-4 | Loom adapter rewiring | FR-1, FR-2, FR-3 | Update Loom CLI/Python config entrypoints to call `weave`. | Keeps Loom authored-config workflows working. | CLI validate/plan/run, diagnostics preflight, sweeps override parsing, docs examples. | Existing Loom workflows still accept authored configs through supported commands/APIs. | Runtime internals avoid config composition internals. | Runtime depends on config library at adapter edges. | CLI/e2e config workflow tests. | confirmed |
| FR-5 | Test and example relocation | FR-1, FR-2 | Move config-owned tests and examples beside `weave`; keep runtime tests/examples under Loom. | Prepares later repository split. | Package tests, contract tests, integration tests, e2e/public examples, authoring examples. | Config examples can be run or validated without Loom runtime imports. | Repo validation runs package-local and combined suites. | Independent validation. | Package-local pytest target and example validation. | confirmed |
| FR-6 | Golden artifact compatibility | FR-2 | Establish fixtures before/through movement for deterministic config outputs. | Prevents silent durable artifact drift. | Resolved/redacted config, manifests, source records, snapshots, fingerprints, structured errors. | No silent changes to persisted/reviewed config artifacts. | Deliberate breaks require documented acceptance. | Stable extraction. | Golden tests before and after move. | confirmed |

## Behavior Baseline

Included functionality:

- Installable `weave` package with `weave` import package.
- Config implementation moved under `weave`.
- Config-owned tests and examples moved beside the config package.
- Loom depends on `weave` and uses it through explicit config adapter
  paths.
- Golden compatibility tests protect deterministic config artifacts.

User-visible behavior:

- Direct config authoring imports use `weave`.
- Loom CLI/Python workflows still compose authored configs where supported.
- Config examples and docs identify `weave` as the authoring package.

Default behavior:

- Hard switch with no `loom.config` compatibility shim by default.
- Clean separation: Loom keeps runtime-required functionality; `weave`
  owns config-specific functionality.
- No new config semantics.
- No repository split during this stage.

Failure behavior and diagnostics:

- Config errors should remain structured and path-aware.
- CLI should continue to map config failures to config-facing diagnostics.
- Missing optional dependency or packaging failures should point users to the
  relevant `weave` install path once defined.

Explicit deferrals:

- Separate repository publication.
- Compatibility shim for `loom.config`.
- New config features or Hydra bridge.
- Additional Loom package splits.

Out-of-scope behavior:

- Runtime workflow redesign.
- Domain-specific examples, recipes, stages, or schemas.
- Untrusted config execution.

Context compaction/reset checkpoint:

- Checkpoint status: recorded on 2026-05-20; design agreement and
  design-safety review have completed after the checkpoint
- Notes path: `docs/roadmap/stage-23/planning.md`
- Resume instruction: reload this planning artifact, the implementation-plan
  draft, and `.codex/workflows/roadmap-stage-planning.md` before plan-quality
  review or phase execution. Treat roadmap framing, intent discovery,
  capability triage, functionality agreement, behavior baseline, design
  agreement, and design-safety review as locked unless the user explicitly
  reopens them.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Likely modules or packages:

- `packages/weave/pyproject.toml`
- `packages/weave/src/weave/`
- `packages/weave/src/weave/py.typed`
- `packages/weave/src/weave/plain.py` or equivalent config-owned
  plain-data helpers
- `packages/weave/src/weave/json.py` or equivalent config-owned
  stable JSON helpers
- `packages/weave/src/weave/digests.py` or equivalent config-owned
  digest helpers
- `packages/weave/src/weave/errors.py`
- `packages/weave/src/weave/recipes/`
- `packages/weave/src/weave/instantiate/`
- `packages/weave/tests/`
- `packages/weave/examples/`
- `src/loom/cli/validate.py`, `src/loom/cli/plan.py`, `src/loom/cli/run.py`,
  and `src/loom/cli/sweep.py` as explicit config adapter paths
- `src/loom/diagnostics/preflight.py` and `src/loom/queue/config.py` as
  config-consuming adapter paths when they compose or load authored config
- `src/loom/pipeline/sweep/spec.py` as runtime-owned sweep override validation
  that should no longer import config composition internals
- `src/loom/plugins/recipes.py` and plugin diagnostics, split so
  `weave` owns recipe catalog loading while Loom may still list recipe
  entry-point metadata without importing config implementation
- Root packaging, coverage, Pyright, Ruff, pytest, and Makefile validation
  configuration

Likely public classes, functions, or protocols:

- `weave.compose_config`
- `weave.compose_config_with_catalog`
- `weave.inspect_config_composition`
- `weave.ComposedConfig`
- `weave.ConfigCompositionInspection`
- `weave.Recipe`
- `weave.RecipeCatalog`
- `weave.register_recipe`
- `weave.instantiate`
- `weave.check_config_targets`
- Config artifact, fingerprint, provenance, source record, and error classes
  currently exposed through `loom.config`.
- Loom-owned CLI/config adapter helpers that translate `weave` outputs or
  errors into Loom command behavior without making `weave` depend on Loom.

Likely internal helpers:

- Config-owned plain-data validation/normalization helpers for config records.
- Config-owned stable JSON helpers for config override values and config
  fingerprints.
- Config-owned digest/fingerprint helpers used by config artifacts.
- Config-owned error context and wrapping helpers.
- Loom-owned duplicate override path/value validation for sweep specs where
  runtime code needs config-compatible override syntax without importing
  `weave` internals.
- Loom-owned CLI error adapter logic for config failures raised by
  `weave`.
- Import-boundary and package-validation helper scripts or tests.

Data flow:

- Authored config files, overlays, override strings, recipe catalogs, and target
  graphs enter `weave`.
- `weave` returns composed plain data plus config-owned provenance,
  manifests, source records, snapshots, and fingerprint records.
- Loom CLI/API adapter paths pass those results into pipeline planning,
  execution, stores, diagnostics, or display code as plain data and explicit
  records.
- Runtime internals do not call config composition internals.
- Runtime sweep specs validate override-shaped data through Loom-owned duplicate
  parsing/validation or through an adapter-normalized plain-data representation,
  not through direct imports from `weave` composition modules.

Dependency direction:

```text
loom config adapter paths
  -> weave

loom runtime foundations
  -> loom-owned serialization, fingerprinting, and error modules

loom sweep/runtime records
  -> loom-owned override validation and plain-data helpers

weave
  -> no loom imports
```

Extension points and flexibility boundaries:

- Recipe catalogs and recipe plugin loading remain config-owned where they
  populate config recipe catalogs.
- Runtime plugin discovery for codecs, event sinks, artifact stores, exporters,
  and future runtime adapters remains Loom-owned.
- Loom plugin listing may report `loom.recipes` entry-point metadata, but
  loading recipes into a recipe catalog is config-owned.
- Helper modules exposed by `weave` for plain data or digests should be
  config-owned and usable without importing composition modules. Loom runtime
  modules should not depend on those helpers for functionality Loom itself
  requires.

Generic interface, adapter, or protocol shape:

- Use explicit adapter edges in Loom rather than implicit global config state.
- Keep config output as plain data plus explicit config artifact records.
- Keep recipe plugin loading explicit and trusted.
- Use package-owned duplicate helper interfaces when both packages need similar
  behavior; do not create an implicit shared-core package in this stage.
- Treat config errors as config-package errors at the source and Loom CLI
  diagnostics as adapter-owned presentation.

Future-roadmap impact:

- Future separate repository extraction becomes easier because package-local
  source, tests, examples, docs, and validation commands are already separated.
- Future runtime stages should not add direct `weave.compose` imports to
  core runtime internals.
- Future plugin work must distinguish config recipe plugins from Loom runtime
  plugin families.

Compatibility constraints:

- Preserve config artifact outputs unless an implementation-plan decision
  records an accepted break.
- Keep error diagnostics structured and user-facing.
- Avoid long-lived compatibility code unless explicitly accepted.
- Preserve config-compatible sweep override semantics while removing direct
  runtime imports from config implementation modules.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Monorepo package layout for `weave`. | FR-1 | 1 | recorded recommendation | Use `packages/weave/src/weave`, package-local `tests`, and package-local `examples`. | Gives future repo extraction a coherent unit and matches the existing planning draft. | Repo and roadmap evidence give a clear recommendation. | confirmed |
| DAQ-2 | Compatibility shim for `loom.config`. | FRQ-1 | 2 | recorded recommendation | No shim by default; hard switch all imports and docs. | A shim changes review scope, error behavior, and migration story. | User confirmed no default shim. | confirmed |
| DAQ-3 | Helper ownership and neutral module names. | FRQ-2 | 3 | recorded recommendation | Keep Loom runtime-required helpers in Loom; put config-specific helper implementations in `weave.plain`, `weave.json`, `weave.digests`, and config error modules or equivalent config-owned modules. | This is the main circular-import and future-maintenance risk. | User supplied the responsibility principle; design-safety should challenge drift risk, but no further user input is needed unless a third package is proposed. | confirmed |
| DAQ-4 | Loom adapter boundary. | FR-4 | 4 | recorded recommendation | Allow CLI/API config adapter paths to call `weave`; keep pipeline/runtime internals on plain data and explicit records. | Keeps Loom domain-neutral and avoids moving runtime semantics into config. | Repo evidence gives a clear recommendation. | confirmed |
| DAQ-5 | Golden fixture timing. | FR-6 | 5 | recorded recommendation | Capture golden expectations before code movement, then assert stability after movement. | Prevents accidental artifact drift. | Repo evidence gives a clear recommendation. | confirmed |
| DAQ-6 | Recipe plugin ownership. | FR-2, FR-3 | 6 | recorded recommendation | Move config recipe catalog and recipe plugin loading with `weave`; keep non-config plugin families and metadata-only plugin listing in Loom. | Preserves config package completeness without dragging runtime plugins into it. | Repo evidence gives a clear recommendation. | confirmed |
| DAQ-7 | Validation command split. | FR-5 | 7 | recorded recommendation | Define package-local `weave` checks plus combined repo checks in the implementation plan. | Reviewers need independent and integrated evidence. | Repo evidence gives a clear recommendation. | confirmed |
| DAQ-8 | Runtime sweep override ownership. | FR-3, FR-4 | 8 | recorded recommendation | Replace runtime imports from config override modules with Loom-owned duplicate override path/value validation or adapter-normalized plain data. | `src/loom/pipeline/sweep/spec.py` currently imports `loom.config`; Stage 23 must remove that runtime dependency without changing sweep semantics. | Confirmed duplicate-helper policy gives a clear recommendation. | confirmed |
| DAQ-9 | Config error handling across packages. | FR-2, FR-3, FR-4 | 9 | recorded recommendation | Define config-owned error roots in `weave`; update Loom CLI/adapters to catch/translate config errors for diagnostics without making `weave` inherit from or import Loom error roots. | Keeps package ownership clean while preserving CLI failure behavior. | Responsibility-separation intent gives a clear recommendation. | confirmed |
| DAQ-10 | Structure/docs update boundary. | FR-1, FR-2, FR-5 | 10 | auto-approved | Update `docs/structure.md`, config feature docs, CLI/docs examples, and module coverage during implementation so docs match the split. | Prevents stale architecture docs and import examples. | Design-safety upheld this as traceable, local, and low-risk documentation alignment from approved behavior. | confirmed |

## Design Decisions And Rationale

Target package shape:

```text
packages/
  weave/
    pyproject.toml
    src/
      weave/
        __init__.py
        py.typed
        ...
    tests/
      ...
    examples/
      ...

src/
  loom/
    ...
```

Ownership model:

- `weave` owns config loading and composition, overlays, `_include_`,
  `_replace_`, merge semantics, override parsing/application, recipe contracts,
  recipe catalogs, recipe expansion, recipe manifests, config-owned recipe
  plugin hooks, `_target_` import resolution, recursive instantiation, runtime
  injection, redaction, config provenance, source artifact records, composition
  manifests, config fingerprint records, raw source snapshot records,
  config-owned plain-data helpers, config-owned stable JSON helpers,
  config-owned digest/fingerprint helpers, config-owned base errors, structured
  config error context, package-local config examples, and package-local config
  tests.
- `loom` owns pipeline specs, stage specs, DAG validation, planning, selectors,
  resume, execution, executors, stores, authority, queues, run catalogs,
  bundles, runtime events, reliability, cleanup, runtime CLI orchestration,
  workflow/runtime tests, and workflow/runtime examples. It also owns any
  runtime-required helper behavior, including serialization, fingerprinting,
  error roots, and duplicate sweep override validation needed by runtime
  records.

Current dependency inventory:

| Current dependency | Current use | Stage 23 ownership |
| --- | --- | --- |
| `loom.serialization.PlainData` | Public config data contract and record typing | Keep Loom runtime-owned plain-data helpers in Loom; add config-owned equivalent surface in `weave` for config records. |
| `ensure_plain_data`, `to_plain_data` | Validation and normalization of config payloads | Keep Loom runtime-owned helpers in Loom; add config-owned equivalents where config records require them. |
| `freeze_plain_data`, `thaw_plain_data` | Immutable config artifact metadata | Keep Loom runtime-owned helpers in Loom; add config-owned equivalents for config artifact metadata. |
| Stable JSON helpers | Override values and deterministic hashing | Keep Loom runtime-owned stable JSON helpers in Loom; add config-owned stable JSON behavior for config fingerprints. |
| `hash_mapping` | Recipe, provenance, and config fingerprint digests | Keep Loom runtime-owned hashing in Loom; add config-owned digest helpers for config artifacts. |
| `hash_bytes` | Authored source content digests | Keep Loom runtime-owned byte hashing in Loom; add config-owned byte hashing for authored config sources. |
| `Fingerprint`, `Digest` aliases | Type vocabulary for config records | Define config-owned aliases in `weave`. |
| `FingerprintError` | Wrapping config fingerprint failures | Define config-owned error surface in `weave`. |
| `loom.errors.ConfigError` | Base for config-specific errors | Define config-owned base errors in `weave`; map them from Loom CLI/adapters. |
| `loom.__version__` | Recipe manifest producer metadata | Replace with `weave.__version__`. |

Adapter and runtime import split:

| Current import area | Stage 23 design treatment | Rationale |
| --- | --- | --- |
| CLI config commands in `src/loom/cli/validate.py`, `plan.py`, `run.py`, and `sweep.py` | Explicit Loom config adapter paths may import `weave`. | These are user-facing config entrypoints and should preserve CLI behavior. |
| Diagnostics preflight config composition in `src/loom/diagnostics/preflight.py` | Treat as an explicit config-consuming adapter path. | Preflight composes authored config for diagnostics; it should not move runtime semantics into config. |
| Queue config loading/composition in `src/loom/queue/config.py` | Treat as an adapter path when it composes authored config; keep queue runtime records on Loom-owned plain-data helpers. | Queue runtime state remains Loom-owned even if authored config is composed through `weave`. |
| Runtime sweep spec override validation in `src/loom/pipeline/sweep/spec.py` | Replace direct config imports with Loom-owned duplicate validation or adapter-normalized plain data. | Sweep records are runtime-owned and should not import config composition internals. |
| Recipe plugin loading in `src/loom/plugins/recipes.py` and plugin diagnostics | Move recipe catalog loading/registration to `weave`; keep Loom metadata listing for `loom.recipes` where useful. | Recipe catalogs are config-owned, but generic plugin metadata remains Loom-owned. |
| Authoring examples under `examples/authoring/**` | Move config-only examples under `packages/weave/examples`; update Loom examples to use `weave` only as frontend input where needed. | Keeps examples movable with their owning package. |

Alternatives rejected or deferred:

- Third shared core package: not needed by default; clean separation is better
  served by small package-owned helper implementations until drift or release
  cadence proves otherwise.
- Broadly moving Loom runtime-required helpers into `weave`: rejected
  because Loom should handle its own runtime-required functionality.
- Long-lived `loom.config` shim: deferred by roadmap to keep the pre-release
  split simple and reviewable; user confirmed no default shim.
- Immediate separate repository: deferred until package-local layout,
  validation, examples, and docs are coherent inside this repository.
- Config language or runtime behavior changes: out of scope for an extraction
  stage.
- Making config errors inherit from Loom errors: rejected because it would make
  `weave` depend on Loom. Loom CLI/adapters should translate or handle
  config-owned errors at adapter boundaries.
- Keeping sweep override parsing in `weave` as a runtime dependency:
  rejected because sweep specs are Loom runtime records; duplicate or adapted
  validation belongs in Loom.

Debt introduced:

- Small helper duplication may exist between Loom and `weave`. Golden
  tests and import-boundary tests must keep the duplicated behavior stable where
  config artifacts depend on it.
- If no compatibility shim is provided, downstream pre-release import paths must
  update at once. This is accepted for the hard switch and should be revisited
  only by explicit future user instruction.
- Duplicate helper behavior needs golden and focused unit coverage to prevent
  divergence where config artifacts and runtime records intentionally share
  equivalent semantics.

Revisit triggers:

- `weave` needs to move to a separate repository and duplicated helper
  behavior makes release cadence or compatibility policy painful.
- Downstream users need a runtime-only Loom install without config adapter
  dependencies.
- Config artifact compatibility breaks are discovered outside an explicitly
  accepted implementation-plan decision.
- A future user explicitly requests a temporary migration shim despite the
  current hard-switch decision.

## Design Safety Review

Status: completed on 2026-05-20; passed.

Gate result:

- Passed. Implementation-plan drafting does not need another design decision
  from this review, and no locked functionality or design decision was
  reopened.
- Implementation-plan drafting was explicitly approved by the user on
  2026-05-20, satisfying the roadmap-stage workflow handoff requirement.
- The implementation plan must carry forward the recorded recommendations,
  validation obligations, accepted risks, and revisit triggers below.

Required challenge areas:

- Does moving helper modules into `weave` lock Loom runtime into a config
  dependency that future roadmap work would regret? Current planning priority
  says Loom should retain runtime-required helpers instead.
- Are interfaces, adapters, and protocols generic enough for a future separate
  `weave` repository?
- Do recipe plugin hooks move without accidentally moving Loom runtime plugin
  semantics into the config library?
- Are config artifacts stable enough to preserve resume/provenance expectations?
- Does the package layout support independent installation, test execution,
  examples, typing, and future repository extraction?
- Does duplicate helper behavior stay intentionally small, or does it reveal a
  future need for a separate shared-core package after this stage?
- Are runtime adapter boundaries clear enough for queue config, diagnostics
  preflight, sweeps, and plugin listing?

Findings:

- Helper ownership remains safe only if implementation treats duplicate helpers
  as package-owned behavior, not as private copy-paste with unconstrained drift.
  The confirmed hard switch and duplicated-helper policy are upheld because
  `docs/roadmap.md`, `docs/features/serialization.md`, and
  `docs/features/fingerprints.md` make Loom's runtime serialization and
  fingerprint responsibilities independent from config composition. The
  implementation plan must require focused unit tests for `weave` helper
  behavior plus golden artifact tests for behavior that must stay compatible.
- The adapter boundary is acceptable but needs sharper implementation-plan
  wording. CLI commands, diagnostics preflight, queue config loading, and other
  authored-config entrypoints may import `weave`; runtime pipeline,
  queue, sweep, store, authority, and provenance internals must not import
  `weave` composition modules or config-package helper modules for
  functionality Loom owns. `src/loom/pipeline/sweep/spec.py` is the current
  high-risk example and must be converted to Loom-owned override validation or
  adapter-normalized plain data without changing sweep semantics.
- Config artifact compatibility is the largest durable-contract risk. Existing
  config records use Loom serialization, digest, schema, and error helpers.
  Moving them to `weave` is acceptable only if golden fixtures pin the
  public serialized shape before or at the movement boundary and then prove the
  moved package preserves resolved config, redacted config, composition
  manifests, recipe manifests, source artifact records, raw source snapshot
  records, fingerprint records, and structured config error payloads unless the
  implementation plan explicitly accepts a break.
- Error ownership is acceptable with an adapter translation rule. `weave`
  must define config-owned error roots that do not inherit from or import
  Loom's shared `ConfigError`. Loom CLI and other adapter paths should catch
  those config-owned errors explicitly and translate them into the existing CLI
  exit categories and structured output. Runtime internals should continue to
  use Loom-owned error roots.
- Recipe plugin ownership is acceptable if the split is explicit. Config recipe
  catalog loading and registration move with `weave`; generic plugin
  metadata listing, non-config plugin groups, codec/source/executor/artifact
  backend/exporter/event-sink groups, and runtime plugin diagnostics remain
  Loom-owned. The implementation plan should decide whether the recipe entry
  point group name remains `loom.recipes` for compatibility or moves to a
  config-owned group, and it must test metadata-only listing without importing
  config composition.
- The `packages/weave/src/weave` layout is suitable for future
  repository extraction. This is a recorded recommendation, not a blocker,
  because it matches the roadmap and keeps package-local source, tests,
  examples, typing marker, and dependency metadata movable as one unit.
- DAQ-10 was the only auto-approved candidate. It remains auto-approved because
  updating `docs/structure.md`, feature docs, CLI docs, examples, and module
  coverage is directly traceable to the hard switch, has no independent product
  behavior, and is straightforward to validate through docs/import examples and
  package import-boundary checks.

Design-agreement triage:

| Decision | Review outcome | Notes |
| --- | --- | --- |
| DAQ-1 monorepo package layout | upheld as recorded recommendation | Future repository extraction benefits from package-local source/tests/examples; implementation still must confirm build metadata details. |
| DAQ-2 no `loom.config` shim | upheld as recorded recommendation | Locked by user decision; no blocker found that requires reopening. |
| DAQ-3 helper ownership | upheld as recorded recommendation | Accepted with golden/helper test obligations and shared-core revisit trigger. |
| DAQ-4 Loom adapter boundary | upheld as recorded recommendation | Requires explicit allowed/disallowed import-boundary tests. |
| DAQ-5 golden fixture timing | upheld as recorded recommendation | Treat as a phase-1 or earliest-movement obligation. |
| DAQ-6 recipe plugin ownership | upheld as recorded recommendation | Requires entry-point group compatibility decision in implementation planning. |
| DAQ-7 validation command split | upheld as recorded recommendation | Implementation plan must define independent and combined commands. |
| DAQ-8 runtime sweep override ownership | upheld as recorded recommendation | Current direct config import is a required cleanup target. |
| DAQ-9 config error handling | upheld as recorded recommendation | Adapter translation replaces shared inheritance. |
| DAQ-10 structure/docs update boundary | reclassified from auto-approved candidate to auto-approved | Low-risk documentation alignment from approved behavior. |

Required planning revisions and plan carry-forward requirements:

- None were required before implementation-plan drafting. This review recorded
  the needed design-safety constraints directly in this artifact.
- The implementation plan must not leave "adapter edge" implicit. It must list
  allowed Loom modules that may import `weave`, forbidden runtime import
  areas, and tests that fail if runtime internals import config composition
  internals.
- The implementation plan must define the golden fixture strategy before code
  movement changes serialized config artifacts. It should name fixture files or
  fixture-generation steps, the public API used to generate them, and the
  compatibility policy for any intentional break.
- The implementation plan must define package-local validation entrypoints for
  `weave`, combined repository validation, docs/example checks, typing
  and packaging checks, and import-boundary checks.
- The implementation plan must decide recipe plugin entry-point compatibility:
  keep `loom.recipes` as a config-owned group during the hard switch, introduce
  a new config-owned group, or support both with an explicit migration policy.
  This is an implementation-planning decision unless it would change the locked
  no-shim import policy.

Accepted risks:

- Hard switch migration risk is accepted. Downstream pre-release users must
  update imports from `loom.config` to `weave`; reopen only by explicit
  future user instruction or a packaging blocker that prevents Loom's own
  adapter paths from working.
- Helper duplication drift is accepted. Revisit if duplicated plain-data,
  stable JSON, digest, fingerprint, or error behavior grows beyond small
  package-owned implementations, if future separate-repository release cadence
  makes compatibility painful, or if golden artifacts expose incompatible
  behavior.
- Config-owned error roots not inheriting from Loom errors are accepted.
  Revisit if CLI/API consumers cannot preserve structured config diagnostics
  through adapter translation.
- Recipe plugin ownership split is accepted. Revisit if metadata-only Loom
  plugin listing cannot report recipe entry points without importing
  `weave`, or if entry-point group compatibility creates ambiguous
  duplicate loading semantics.
- Monorepo packaging complexity is accepted. Revisit if Pyright, Ruff, coverage,
  build, editable install, or test discovery cannot cleanly validate both
  distributions without heavyweight tooling or a broader repository layout
  change.
- Public package-name availability for `weave` is not verified in planning.
  Revisit before any publication-oriented step or if isolated install checks
  resolve the wrong package.

## Examples And Validation Strategy

Config package tests move under:

```text
packages/weave/tests/
```

These tests should cover:

- Config loading, overlays, includes, replacement, and merge behavior.
- Override parsing and application.
- Interpolation and resolver policy.
- Recipe catalogs, expansion, manifests, and plugin hooks.
- `_target_` import resolution and instantiation.
- Redaction.
- Config provenance, source artifacts, raw source snapshots, composition
  manifests, and config fingerprints.
- Golden fixtures for resolved config, redacted config, recipe manifests,
  composition manifests, source artifact records, and fingerprint records.
- Import-boundary checks proving `weave` imports no `loom`.

Loom workflow/runtime tests remain under the Loom test tree and should cover:

- Runtime behavior that consumes config output through public adapter paths.
- CLI workflows that call `weave` to compose authored config.
- Boundary checks proving runtime internals do not import config composition
  internals.
- End-to-end workflows where config is one input to pipeline execution.

Config examples move under:

```text
packages/weave/examples/
```

Config examples should cover:

- Basic composition.
- Overlays and user overrides.
- Includes and replacement.
- Recipe authoring and expansion.
- `_target_` instantiation and runtime injection.
- Redaction and artifact-safe config output.
- Config provenance, source records, and fingerprint inspection.
- Structured config errors.

Loom examples remain focused on workflow/runtime behavior:

- Pipeline authoring and execution.
- Stores, artifacts, run catalogs, bundles, authority, queues, events, cleanup,
  containers, SLURM, sweeps, plugins, and operational workflows.
- CLI workflows that use `weave` as the config frontend.

The implementation plan should define separate validation commands for:

- `weave` unit, package, contract, integration, and example checks.
- Loom runtime tests.
- Combined repository validation while the packages still live together.

## Phase Shaping Notes

A future implementation plan should likely split this stage into phases similar
to:

1. Boundary and golden fixture preparation.
2. `weave` package scaffold and utility migration.
3. Config implementation namespace move.
4. Loom adapter rewiring and import-boundary cleanup.
5. Test/example relocation and validation command updates.
6. Documentation and final hardening.

The exact phase count can change, but implementation should keep config package
movement, Loom runtime rewiring, and test/example relocation reviewable as
separate diffs where practical.

## Implementation Readiness

Readiness checklist:

- Roadmap framing confirmed: yes
- User clarification window complete: yes
- Intent discovery confirmed: yes
- Capability triage confirmed: yes
- Functionality-agreement queue resolved: yes
- Behavior baseline confirmed: yes
- Context checkpoint recorded: yes
- Design-agreement queue resolved: yes
- Design-safety review completed: yes; passed on 2026-05-20 with no blockers
  or reopened decisions
- Examples and validation strategy confirmed: reviewed by design-safety;
  implementation plan must define concrete commands and fixture locations
- Phase shaping confirmed: reviewed by design-safety; six-phase shape accepted
  as the default planning basis
- Implementation-plan drafting explicitly approved by user: yes, on 2026-05-20
- Implementation-plan quality gate passed: yes, on 2026-05-20 after one
  refinement pass and confirmation review

Open questions:

- None from design-safety review.
- The implementation-plan draft records package metadata direction, validation
  command names, golden fixture file locations, and recipe plugin entry-point
  group compatibility policy within the approved design constraints.

Handoff notes:

- `docs/roadmap/stage-23/implementation-plan.md` has been drafted from this
  planning artifact and passed its plan quality gate. The design-safety gate
  has passed and has no unresolved blockers.
- Do not start phase execution from this planning artifact.

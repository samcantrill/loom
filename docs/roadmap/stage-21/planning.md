# Roadmap Stage 21 Planning: Cleanup And Retention

## Metadata

- Roadmap stage: v21
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap/stage-20/planning.md` exists in the current checkout and
    records Stage 20's confirmed planning baseline.
  - `docs/roadmap/stage-20/implementation-plan.md` exists in the current
    checkout and records Stage 20 complete, with Phases 1 through 4 merged.
  - Stage 21 planning treats Stage 20 event records, event-sink registry,
    observer facts, runtime dispatch helpers, plugin loading, and diagnostics
    as available predecessor surfaces.
- Planning artifact status: confirmed for implementation-plan drafting;
  implementation-plan quality gate passed
- Current discussion stage: implementation-plan quality gate passed; ready for
  phase execution planning
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed; resume design agreement
    review from this artifact in fresh context
  - Design agreement review: confirmed
  - Design safety review: confirmed
  - Examples and validation strategy: confirmed
  - Phase shaping: confirmed
  - Implementation readiness: confirmed
  - Handoff: confirmed
- Related implementation plan: `docs/roadmap/stage-21/implementation-plan.md`
- Related feature docs:
  - `docs/features/reliability.md`
  - `docs/features/artifacts.md`
  - `docs/features/run-store.md`
  - `docs/features/run-catalog.md`
  - `docs/features/cli.md`
  - `docs/features/preflight.md`
  - `docs/features/execution.md`
  - `docs/features/testing.md`
- Blockers:
  - None for implementation-plan drafting.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` v21 | Stage 21 adds conservative cleanup, retention metadata, explicit deletion, and run-collection GC without surprising deletion of user data. | roadmap scope | Data-loss prevention is the primary design constraint. |
| `docs/roadmap.md` v21 | Implement cleanup candidate models for loom-owned temporary files and failed-attempt artifacts recorded in metadata. | candidate scope | Current source already has authority cleanup-candidate records that Stage 21 can build on. |
| `docs/roadmap.md` v21 | Implement cleanup dry-run reporting, explicit deletion APIs, and CLI cleanup commands with confirmation or programmatic delete intent. | user-visible behavior | Deletion must be opt-in and inspectable before it mutates files. |
| `docs/roadmap.md` v21 | Enforce managed roots, metadata or marker ownership, symlink rejection, visible deletion failures, and no arbitrary directory guessing. | safety model | Path safety is a first-class requirement, not an implementation detail. |
| `docs/roadmap.md` v21 | Add artifact retention metadata and inspection support with modes such as keep, temporary, archive, and external as policy hints. | retention behavior | Retention hints do not perform automatic deletion. |
| `docs/roadmap.md` v21 | Add conservative run-collection garbage collection for explicitly selected candidates. | collection scope | Run collection GC should remain metadata-driven and opt-in. |
| `docs/roadmap.md` v21 | Add preflight warnings for cleanup paths outside managed roots and unsupported retention policies. | diagnostics | Preflight should warn about unsafe or unsupported cleanup surfaces before deletion. |
| `docs/roadmap.md` v21 | Defer automatic retention deletion, aggressive artifact GC, global cache collection, organization-specific cleanup policies, remote service retention enforcement, and destructive cleanup without explicit user intent. | scope boundary | Stage 21 must not become an automatic policy engine. |
| `docs/features/reliability.md` | Temporary cleanup targets only paths recorded by Loom, such as atomic-write temp directories, staged container working directories, wrapper temp files, and partial bundle export directories. | candidate ownership | Cleanup should not scan arbitrary directories and guess. |
| `docs/features/reliability.md` | Cleanup safety rules require configured roots, metadata or marker ownership, dry-run output, no symlink following, and visible deletion failures. | safety behavior | Matches roadmap v21 safety obligations. |
| `docs/features/reliability.md` | Programmatic APIs should default to dry-run unless called with explicit delete intent; interactive confirmation belongs in CLI. | API and CLI split | Public APIs should not rely on interactive prompts for safety. |
| `docs/features/reliability.md` | Initial GC should be metadata-driven and conservative, with candidates such as temporary files, failed attempt temp directories, selected old logs, temporary-retention artifacts, and entire run directories only with explicit flags. | GC behavior | Whole-run deletion needs a stronger opt-in than per-file cleanup. |
| `docs/features/reliability.md` | Retention modes are keep, temporary, archive, and external, and are policy hints rather than ownership checks. | retention mode vocabulary | Retention does not replace store ownership or managed-root checks. |
| `docs/features/artifacts.md` | Future artifact stores may support retention intent as metadata, and cleanup commands should inspect the run store before removing artifacts. | artifact contract | Stage 21 should keep `ArtifactRef` lightweight and store-backed. |
| `docs/features/run-store.md` | V0 explicitly deferred large artifact garbage collection and full audit-log event sourcing. | predecessor boundary | Stage 21 can add cleanup without redefining run-store truth. |
| `docs/features/run-store.md` | Attempt archives are deferred until retry or retention policy needs attempt history. | attempt history dependency | Stage 21 may need to rely on Stage 19 attempt and transaction records. |
| `docs/features/cli.md` | `loom clean RUN_URI --failed-temp` and `loom gc RUNS_DIR --older-than 30d` are deferred operational commands that should call underlying APIs. | CLI routing | CLI must not implement deletion policy directly. |
| `docs/features/preflight.md` | Preflight already checks filesystem reachability and handler capability surfaces. | diagnostics integration | Stage 21 can add cleanup and retention warnings without changing execution semantics. |
| `docs/features/execution.md` | Automatic cleanup and retention remain deferred, and Stage 21 is listed as the reliability cleanup command consumer. | execution boundary | Execution should produce facts/candidates; cleanup should be explicit and separate. |
| `docs/features/testing.md` | Tests should use temporary directories and not write outside their temporary directory. | validation constraints | Cleanup tests must be local, deterministic, and filesystem-safe. |
| `docs/loom.md` | Cleanup and retention are post-v0 roadmap work; Loom remains generic scaffolding and avoids domain-specific semantics. | domain neutrality | Retention modes must stay generic. |
| `docs/structure.md` | Runtime package boundaries separate generic Loom mechanics from project code. | import boundaries | Cleanup logic belongs in generic store/diagnostic/CLI surfaces, not project-specific code. |
| `docs/GLOSSARY.md` | Prefer `run_uri`, `RunStore`, `StageStore`, authority, run collection, run catalog, checksum, fingerprint, and artifact terms precisely. | vocabulary | Cleanup planning should distinguish authoritative state from derived catalogs and materialized files. |
| `docs/roadmap/stage-20/planning.md` | Stage 20 defers cleanup, deletion, retention enforcement, and run-collection GC to Stage 21. | predecessor boundary | Stage 21 should consume event facts only as audit evidence, not depend on event sinks for correctness. |
| `docs/roadmap/stage-20/implementation-plan.md` | Stage 20 is complete with event grammar/compatibility, event sink registry and observer facts, runtime dispatch, plugin loading, diagnostics, inspection, and docs merged. | predecessor handoff | Cleanup event emission is now an available Stage 21 capability rather than a conditional future hook. |
| `src/loom/pipeline/events.py` | `PipelineEventRecord` is the canonical schema-versioned durable event record with event id, sequence, occurred timestamp, primary and related resources, payload, causal predecessor, and schema-v1 projection. | event emission surface | Stage 21 cleanup events should use this record family and remain plain-data-compatible. |
| `src/loom/pipeline/event_sinks.py` | `EventSinkRegistry`, dispatch result records, failure records, and observer-link records exist with observe-only semantics. | observer surface | Cleanup may dispatch to configured sinks through Stage 20 machinery, but sinks cannot authorize or block deletion. |
| `src/loom/pipeline/execution/eventing.py` | `RuntimeEventDispatcher` appends durable events before dispatching configured sinks and supports non-durable dispatch warnings. | runtime event flow | Cleanup should reuse the durable-event-before-dispatch ordering where practical. |
| `src/loom/plugins/event_sinks.py` | Explicit event-sink plugin loading into a supplied registry exists. | plugin boundary | Stage 21 should not add cleanup-specific sink loading; existing Stage 20 loading can observe cleanup events. |
| `src/loom/pipeline/stores/read_models.py` | `CleanupCandidateKind` currently includes `staged_payload`, `worker_handoff`, and `materialized_ref`; `CleanupCandidate` has candidate id, kind, URI, reason, recorded timestamp, and revision. | existing source surface | Stage 21 can extend or wrap this model rather than inventing candidate identity from scratch. |
| `src/loom/authority/_repository.py` | `record_cleanup_candidate` and `list_cleanup_candidates` persist cleanup candidates in authority state. | existing authority behavior | Candidate persistence exists, but deletion planning and safety checks are not implemented. |
| `src/loom/pipeline/stores/authority.py` | `RunStore` and `PerRunAuthorityStore` expose `list_cleanup_candidates`. | public/store surface | Cleanup APIs should remain authority-backed and fakeable. |
| `src/loom/diagnostics/backend.py` | Backend inspection already counts and returns cleanup candidates. | inspection foundation | Existing diagnostics can become part of dry-run and status evidence. |
| `src/loom/artifacts.py` | `ExternalArtifactRef` has a generic `retention` mapping; `ArtifactRef` remains lightweight metadata without a first-class retention field. | retention foundation | Stage 21 must decide whether retention stays generic metadata, gains typed records, or both. |
| `tests/unit/loom/pipeline/stores/test_materialization_read_models.py` | Cleanup candidates carry through authoritative read models and bundle metadata. | current tests | Stage 21 should preserve bundle/export visibility while adding cleanup behavior. |
| `tests/unit/loom/pipeline/stores/test_authority_protocol.py` | Authority protocol payloads serialize cleanup candidates. | contract coverage | Existing serialization is a compatibility input for Stage 21. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Workflow and templates | `.codex/workflows/roadmap-stage-planning.md`, `.codex/prompts/roadmap-stage-planning-facilitate.md`, `.codex/prompts/roadmap-stage-functionality-agreement.md`, `.codex/prompts/roadmap-stage-design-agreement.md`, `.codex/prompts/roadmap-stage-design-safety-review.md`, `.codex/templates/roadmap-stage-planning.md` | Workflow requires comprehensive startup briefing, user clarification window, functionality agreement, behavior confirmation, context checkpoint, design agreement, design-safety review, examples, validation, phase shaping, and final confirmation before implementation-plan drafting. | Design-safety review passed; examples/validation and phase shaping remain. |
| Roadmap docs | `docs/roadmap.md` v19-v21 and module coverage table | v19 records reliability facts and cleanup evidence; v20 owns event/audit projection; v21 owns explicit cleanup, retention metadata, and conservative GC. | Stage 21 implementation plan does not exist. |
| Adjacent plans | `docs/roadmap/stage-20/planning.md`, `docs/roadmap/stage-20/implementation-plan.md` | Stage 20 leaves cleanup/deletion/retention to Stage 21 and is now complete with event records, sink registry, dispatch, plugin loading, and diagnostics merged. | Stage 21 still owns all mutating cleanup and retention behavior. |
| Feature docs | `reliability.md`, `artifacts.md`, `run-store.md`, `run-catalog.md`, `cli.md`, `preflight.md`, `execution.md`, `testing.md` focused cleanup, retention, CLI, and safety sections | Feature docs support dry-run-first cleanup, explicit delete intent, managed roots, recorded candidates, metadata/marker ownership, symlink rejection, visible failures, retention hints, and conservative GC. | Exact public API names, deletion-result records, retention schema shape, and run-collection selection semantics remain design decisions. |
| Source and tests | `src/loom/pipeline/stores/read_models.py`, `src/loom/pipeline/stores/authority.py`, `src/loom/pipeline/stores/authority_protocol.py`, `src/loom/authority/_repository.py`, `src/loom/pipeline/stores/service_authority.py`, `src/loom/pipeline/stores/sqlite_authority.py`, `src/loom/pipeline/stores/factory.py`, `src/loom/diagnostics/backend.py`, `src/loom/artifacts.py`, `src/loom/pipeline/events.py`, `src/loom/pipeline/event_sinks.py`, `src/loom/pipeline/execution/eventing.py`, `src/loom/plugins/event_sinks.py`, cleanup/retention/event tests found by `rg` | Current source has cleanup-candidate persistence, read-model and protocol serialization, diagnostics counts, `ExternalArtifactRef.retention`, Stage 20 event records, event sinks, observer facts, dispatch, plugin loading, and tests proving candidate/event carry-through. | No cleanup planner, deletion executor, delete-intent token, path-safety module, retention policy value object, cleanup event taxonomy, or cleanup CLI was found. |

## Roadmap Extraction

Baseline roadmap outcome:

- Users can inspect cleanup candidates before any deletion happens.
- Programmatic cleanup deletion requires explicit delete intent and is limited
  to Loom-owned paths under managed roots.
- CLI cleanup commands provide dry-run output and confirmation behavior.
- Path safety rules reject paths outside managed roots, paths without metadata
  or marker ownership, symlinks, arbitrary directory scans, and invisible
  deletion failures.
- Artifact retention metadata is recorded and inspectable as generic policy
  hints.
- Retention modes include keep, temporary, archive, and external without
  automatic deletion.
- Run-collection garbage collection can select conservative candidates only
  through explicit user intent.
- Preflight warns about unsupported retention policy or cleanup paths that
  cannot be proven safe.

Prerequisites:

- Authority-backed run and stage lifecycle state from v9 and later stages.
- DB-backed/service-backed authority and offline import facts from v10.
- Run catalog and run collection vocabulary from v8 and later authority work.
- Bundle/export visibility from v12, especially for retention metadata and
  cleanup candidates.
- External artifact and payload materialization contracts from v15 and v16.
- Reliability facts, attempt history, timeout/transaction evidence, and cleanup
  candidate records from v19.
- Runtime event/audit records, event-sink registry, observer facts, dispatch,
  plugin loading, and diagnostics from completed Stage 20.

Primary feature docs:

- `docs/features/reliability.md`
- `docs/features/artifacts.md`
- `docs/features/run-store.md`
- `docs/features/run-catalog.md`
- `docs/features/cli.md`
- `docs/features/preflight.md`
- `docs/features/execution.md`
- `docs/features/testing.md`

Deferred or out-of-scope roadmap work:

- Automatic retention deletion.
- Aggressive artifact garbage collection.
- Global cache collection.
- Organization-specific cleanup policies.
- Remote service retention enforcement.
- Destructive cleanup without explicit user intent.
- Remote provider deletion semantics beyond warning or unsupported capability
  reporting.
- Domain-specific retention classes such as model checkpoints, datasets,
  reports, or metrics.

Future-roadmap touchpoints:

- Future remote store adapters may expose store-owned retention or deletion
  capabilities, but Stage 21 should define generic capability checks and
  unsupported-policy warnings rather than first-party cloud deletion behavior.
- Future service deployments may use the same cleanup planning and audit
  records for multi-host cleanup, but Stage 21 should not require a hosted
  cleanup daemon.
- Future organization policy layers can consume retention metadata, cleanup
  reports, and delete results as inputs without becoming part of core Loom.
- Stage 20 event sinks can observe cleanup operation events, but sink delivery
  must not control whether deletion is allowed.

Compatibility obligations:

- Existing cleanup candidate records must remain readable and meaningful.
- Existing bundle/export metadata that carries cleanup candidates must keep
  enough information for inspection and offline import.
- Retention metadata must remain plain-data-compatible and domain-neutral.
- Cleanup reports and delete results should be deterministic enough for tests
  and review.
- The run store and authority remain the source of cleanup candidate truth;
  run catalogs remain derived indexes.
- Default tests must be local, fakeable, deterministic, and network-free.

## Stage Briefing

What this stage is:

- Stage 21 is the point where Loom turns recorded cleanup and retention facts
  into safe, explicit operations.
- It is about planning and executing conservative cleanup only when Loom can
  prove candidate ownership and path safety, and only when a caller has
  explicitly requested deletion.
- It also makes retention intent visible for artifacts and run/bundle
  inspection without treating retention hints as automatic deletion policy.

Why this stage exists:

- Earlier stages deliberately create facts that cleanup needs but avoid
  destructive behavior. Current source already persists cleanup candidates,
  carries them through authoritative read models and bundle metadata, and
  exposes candidate counts in backend diagnostics.
- That foundation is not enough for users because there is no dry-run report,
  no deletion-result model, no CLI cleanup command, no path-safety contract, no
  typed retention vocabulary, and no run-collection GC workflow.
- The roadmap separates Stage 21 from Stage 19 reliability and Stage 20 events
  so the mutating operation can be designed around safety first instead of
  being hidden inside execution, retry, or event delivery.

Impacted or linked work:

- `loom.pipeline.stores` and authority-backed read models provide cleanup
  candidates and likely need cleanup planning/deletion result surfaces.
- `loom.artifacts` may need a first-class retention policy value object or a
  constrained retention metadata shape that remains plain-data-compatible.
- `loom.diagnostics` and preflight can expose unsafe cleanup paths,
  unsupported retention hints, and candidate summaries.
- `loom.cli` can add `clean` and `gc` commands after the underlying APIs exist.
- `loom.runs` or run-catalog utilities may need read-only run-collection
  selection helpers for GC candidates while preserving the catalog as derived
  state.
- Stage 20 event records and event sinks now provide audit and observer
  surfaces for cleanup reports and deletion results, but Stage 21 must not make
  event sinks part of deletion correctness.
- Bundle/export/import flows should preserve retention and cleanup metadata for
  inspection, but export/import should not silently delete files.

Likely public surfaces and durable artifacts:

- A cleanup candidate summary or report model for dry-run output.
- A deletion-intent or cleanup execution options model that makes destructive
  intent explicit in programmatic APIs.
- A deletion result record that lists deleted paths, skipped paths, rejected
  candidates, and failures.
- A path-safety validator for managed roots, ownership evidence, symlink
  rejection, and visible failure reporting.
- Retention mode and retention policy records or constrained metadata
  conventions.
- CLI commands for per-run cleanup and run-collection GC that call public
  cleanup APIs and provide confirmation or `--yes` behavior.
- Preflight diagnostics for unsafe cleanup candidates and unsupported retention
  hints.
- Cleanup event or audit records using the completed Stage 20 event APIs.

Structure rationale:

- The safest planning shape is report first, delete second, and collection GC
  after per-run semantics are stable.
- Cleanup candidate discovery should remain authority-backed and metadata-driven
  because arbitrary directory scanning would violate the roadmap safety rule.
- Retention should start as inspectable policy hints because automatic
  retention enforcement is explicitly deferred.
- CLI behavior should be a thin presentation and confirmation layer over
  public cleanup APIs; deletion rules should live in runtime modules that can
  be tested without a terminal.
- Run-collection GC should select explicit candidates from run metadata and
  catalog/read-model facts, not treat the run catalog as cleanup authority.

Visible assumptions, risks, and constraints:

- The highest risk is accidental deletion of user data; the default should be
  dry-run and rejection when ownership or managed-root safety cannot be proven.
- Stage 21 likely needs to preserve old cleanup candidate records while adding
  richer report or result records around them.
- Retention metadata may need a typed public shape, but it must remain generic
  enough for external stores, bundles, and future organization policies.
- Symlink handling should reject deletion targets that are symlinks or require
  traversal through symlinks.
- Remote or external artifact refs should default to not owned for deletion
  unless a store-owned adapter explicitly proves delete support.
- Whole-run deletion is more dangerous than per-candidate cleanup and should
  likely require a separate explicit flag or intent branch.
- Stage 20 event-sink failure must not prevent or authorize deletion; cleanup
  result records remain the correctness evidence while events provide audit
  projection.

User clarification questions and resolved answers:

- The user agreed with the conservative safety and inspectability priority, and
  clarified that Stage 21 should also support hard cleanup selected by tags,
  datetimes, or other attributes in addition to stale or old cleanup targets.
- Resolution: include explicit filtered cleanup as a first-class Stage 21
  capability. Filters can select or narrow candidates by recorded metadata,
  retention hints, timestamps, candidate kind/reason, status, or similar
  plain-data attributes, but "hard cleanup" still requires explicit delete
  intent and must not bypass managed-root, ownership, symlink, or unsupported
  external-store checks.
- The user confirmed that the first implementation should use a bounded
  selector set rather than a general query language, with `--older-than 7d` as
  the representative CLI shape for age-based cleanup.
- The user confirmed "GC first": the first run-collection GC implementation
  should operate over selected cleanup candidates inside runs. Whole-run
  deletion should be treated as a separate higher-risk mode or future
  capability, not as the default behavior of collection GC.
- The user agreed that future whole-run deletion should be a separate explicit
  capability with stronger gates: terminal run state, no active leases/workers
  or submitted operations, managed-root and marker/provenance proof, symlink
  rejection, retention compatibility, dependency/reference checks, dry-run
  explanation, and deletion result/tombstone records for catalog reconciliation.
- The user agreed that cleanup result records are required, and after Stage 20
  completion this planning pass revises cleanup event emission to an included
  audit projection over cleanup planning and result facts. Event sinks must not
  authorize, block, or define deletion correctness.
- The user confirmed the revised capability split after Stage 20 completion:
  include dry-run reports, explicit delete intent, `loom clean`, path safety,
  retention metadata/inspection, candidate-level run-collection GC, bounded
  selectors, preflight warnings, cleanup result records, and cleanup event
  emission; defer whole-run deletion, cleanup-specific event sink plugins, and
  remote provider deletion enforcement; keep automatic retention enforcement,
  arbitrary query languages, and arbitrary directory/global cache cleanup out
  of scope.
- The user confirmed the functionality and behavior baseline: dry-run first,
  explicit delete intent for mutation, Loom-owned managed-root-only cleanup,
  bounded selectors, candidate-level run-collection GC, cleanup result records
  as correctness evidence, Stage 20 cleanup events as audit projections, and
  observe-only event sinks.

## User Intent

Target audience:

- Confirmed default: Loom users and maintainers who need to inspect and remove
  Loom-owned temporary, failed-attempt, stale, old, or explicitly selected
  tagged/attributed files without risking project data.

User-visible outcome:

- Confirmed default: a dry-run-first cleanup workflow that shows exactly what
  would be removed, supports explicit selection by tags, datetimes, and other
  recorded attributes, requires explicit deletion intent for hard cleanup, and
  records visible results.

Success criteria:

- Users can run dry-run cleanup with bounded selectors such as
  `--older-than 7d` and see exactly which Loom-owned candidates match.
- Users can run run-collection GC across multiple runs and delete selected
  cleanup candidates inside those runs without deleting whole run directories.
- Users can perform hard cleanup for matching candidates only after explicit
  delete intent or CLI confirmation.
- Reports explain selector matches, skipped candidates, rejected unsafe paths,
  and deletion failures.
- Cleanup result records are always produced for mutating cleanup operations,
  and cleanup audit events are emitted through the Stage 20 event surface
  without making event sinks part of deletion correctness.

Non-goals:

- Arbitrary query languages for cleanup selection in the first implementation.
- Selector-driven deletion that bypasses managed-root, ownership, symlink, or
  unsupported-store checks.
- Whole-run directory deletion as part of the first GC behavior.
- Requiring event sinks or successful sink delivery for cleanup correctness.

Constraints:

- Cleanup reports, selectors, delete intent, deletion results, and retention
  records must remain plain-data-compatible and deterministic.
- Cleanup event payloads must be projections of cleanup reports/results, not
  separate sources of truth.
- Cleanup must use authoritative run/store facts for candidate truth; run
  catalogs remain derived indexes.
- CLI owns confirmation and presentation, while tested Python APIs own
  deletion rules.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- Stage 21 optimizes for conservative safety, explicit intent, and
  inspectability over convenience, while still including first-class filtered
  hard cleanup by tags, datetimes, and other recorded attributes.
- Filters are selection policy over cleanup candidates; they do not relax
  managed-root, ownership, symlink, or unsupported-store safety checks.

Intent discovery locked decisions:

- First implementation uses a bounded selector set for filtered hard cleanup.
- `--older-than 7d` is the representative age-selector user flow.
- A general cleanup query language is out of scope for the first
  implementation.
- First run-collection GC implementation deletes selected cleanup candidates
  inside runs, not whole run directories.
- Whole-run deletion is a future or separate explicit capability with stricter
  preconditions and result/tombstone records, not normal cleanup behavior.
- Cleanup result records are mandatory for mutating cleanup. Stage 20 cleanup
  events are included as audit projections, and event sinks are never part of
  deletion authorization or correctness.

Capability triage and candidate-functional-requirement readback:

- Capability split confirmed by the user after Stage 20 completion. Included
  capabilities are per-run dry-run reports, explicit delete intent, `loom
  clean`, path safety, retention metadata/inspection, candidate-level
  run-collection GC, bounded selectors, preflight warnings, cleanup result
  records, and cleanup event emission. Deferred capabilities are whole-run
  deletion, cleanup-specific event sink plugins, and remote provider deletion
  enforcement. Out-of-scope capabilities are automatic retention enforcement,
  arbitrary query languages, and arbitrary directory/global cache cleanup.

Functionality-agreement readback:

- FRQ-1 through FRQ-4 are confirmed. FR-1 through FR-8 are confirmed as the
  Stage 21 functional requirement set. No unresolved high-impact functionality
  questions remain before behavior confirmation.

Functionality and behavior confirmation readback:

- Behavior baseline confirmed by the user. Included behavior is per-run dry-run
  reporting, explicit delete intent, `loom clean`, path safety, retention
  metadata/inspection, candidate-level run-collection GC, bounded selectors,
  preflight warnings, cleanup result records, and cleanup audit event emission.
- Defaults are dry-run first, reject unsafe candidates, use bounded selectors
  only over recorded Loom facts, and emit cleanup events only as projections of
  cleanup reports/results.
- Failure behavior is visible: unsafe paths, missing ownership evidence,
  symlinks, unsupported external/remote deletion, deletion failures, and sink
  failures are all reported through records or diagnostics.
- Explicit deferrals are whole-run deletion, cleanup-specific event sink
  plugins, and remote provider deletion enforcement.
- Out-of-scope behavior is automatic retention enforcement, arbitrary cleanup
  query languages, arbitrary directory/global cache cleanup, destructive
  cleanup without explicit user intent, and event-sink authorization or veto of
  deletion.

Design-agreement follow-up:

- Proposed implementation shape, design-agreement queue, design decisions, and
  triage have been drafted and resolved from repo evidence. Design-safety
  review passed with no unresolved high-impact design questions.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Conservative, explicit, inspectable cleanup is the priority; filtered hard cleanup by tags, datetimes, and attributes is in scope under the same safety checks. | Dry-run first; explicit delete intent required; filters select candidates but do not bypass ownership or path safety. | None at roadmap-framing level. | Discover exact selector workflows, success criteria, non-goals, and constraints. |
| Intent discovery | Use bounded selectors first; `--older-than 7d` is the representative age-selector flow; no arbitrary query language in the first implementation; run-collection GC starts with selected cleanup candidates inside runs, not whole-run deletion; cleanup result records are required and event emission is included as audit projection after Stage 20 completion. | Support stale/old cleanup plus explicit metadata/time/tag selectors over recorded Loom facts. | None at intent level. | Confirm revised capability triage. |
| Capability triage and candidate functional requirements | Include dry-run reports, explicit delete intent, `loom clean`, path safety, retention metadata/inspection, candidate-level GC, bounded selectors, preflight warnings, result records, and cleanup events; defer whole-run deletion, cleanup-specific sink plugins, and remote provider deletion; out of scope automatic retention enforcement, arbitrary queries, and arbitrary directory/global cache cleanup. | Capability set reflects Stage 20 completion and user-confirmed GC/safety priorities. | None. | Functionality agreement review. |
| Functionality agreement review | FR-1 through FR-8 confirmed as the Stage 21 requirement set. | Cleanup result records are correctness evidence; cleanup events are audit projections; run collection GC is candidate-level; selectors are bounded. | None. | Confirm behavior baseline. |
| Functionality and behavior confirmation | Behavior baseline confirmed as drafted. | Dry-run first; explicit delete intent; Loom-owned managed-root-only cleanup; bounded selectors; candidate-level GC; result records as correctness evidence; cleanup events as audit projection; observe-only sinks. | None. | Context checkpoint before design agreement. |
| Context compaction/reset checkpoint | Functionality and behavior checkpoint recorded. | Resume design agreement from `docs/roadmap/stage-21/planning.md` in a fresh context. | None. | Design agreement review. |
| Design agreement review | Cleanup behavior should live in a new tested `loom.pipeline.cleanup` API layer; mutating cleanup result records belong in authority-backed cleanup facts; dry-run previews remain side-effect-free unless explicitly recorded; retention uses typed plain-data policy hints; run-collection GC remains candidate-level; cleanup events project recorded cleanup facts only. | Local filesystem deletion first; bounded selectors over recorded facts; CLI and diagnostics are wrappers/readers, not policy owners. | None. | Design-safety review. |
| Design safety review | Design-safety review passed with hardening notes: cleanup results append authority-backed outcome facts instead of mutating/removing candidates; managed roots must come from trusted authority/store/config facts; the target adapter boundary stays capability/ownership-focused, not policy-owning; unrecorded dry-runs remain side-effect-free. | Recorded recommendations upheld; DAQ-9 and DAQ-10 auto-approved candidates upheld. | None. | Examples and validation strategy. |
| Examples and validation strategy | Confirmed examples cover per-run dry-run, bounded selectors, explicit deletion and result records, path-safety rejection, retention inspection, candidate-level collection GC, cleanup/retention preflight warnings, and cleanup event projection. | Test strategy is layered: package/import for public surfaces, unit for records/selectors/safety/execution/events/preflight, contract for serialization and public guarantees, integration for local filesystem and authority collaboration, CLI/e2e for user-visible commands, final `make validate-pr` and `make test-summary`. | None. | Phase shaping. |
| Phase shaping | Confirmed five implementation phases: cleanup records/retention/selectors/safety contracts; authority-backed dry-run planning and inspection; explicit local deletion and cleanup event projection; candidate-level run-collection GC and preflight warnings; CLI commands, docs, and final validation. | Keep destructive deletion isolated in Phase 3; keep CLI last; every phase preserves authority, safety, and domain-neutral validation obligations. | None. | Implementation readiness and handoff. |
| Implementation readiness | Passed after phase shaping. Roadmap, requirements, design, design-safety, examples, validation, phase shaping, future-roadmap impact, and interface assumptions are recorded with no unresolved `blocked` or `needs discussion` decisions. | Proceed to implementation-plan drafting from this planning artifact. | None. | Draft implementation plan. |
| Handoff | Implementation-plan draft may use this artifact as source of truth. User instruction to continue drafting is recorded as final planning confirmation for this pass. Implementation-plan quality gate passed on 2026-05-18 after a bounded refinement clarifying the Phase 2/Phase 3 durable fact split. | Phase execution planning may proceed from `docs/roadmap/stage-21/implementation-plan.md`. | None. | Draft Phase 1 execution plan. |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Per-run cleanup dry-run reporting | include | Roadmap exit criteria require users to see what Loom would clean before deletion. | Should summarize candidates, ownership evidence, safety checks, and skipped/rejected reasons. |
| Explicit programmatic deletion intent | include | Roadmap requires deletion APIs and explicit user intent. | API should default to dry-run unless destructive intent is provided. |
| CLI `loom clean` presentation and confirmation | include | Roadmap calls for CLI cleanup commands with confirmation or delete intent. | CLI should call underlying cleanup APIs and own interactive confirmation only. |
| Path safety validation | include | Managed roots, metadata/marker ownership, symlink rejection, and visible failures are roadmap requirements. | Needs deterministic local tests. |
| Retention metadata and inspection | include | Roadmap requires retention modes as policy hints and visibility to export/import and inspection workflows. | Needs plain-data compatibility and likely typed validation. |
| Run-collection GC dry-run and explicit deletion | include | Roadmap calls for conservative GC for explicitly selected candidates. | Whole-run deletion should be separate from per-candidate cleanup. |
| Whole-run deletion | defer | User confirmed GC first; deleting a run directory has a larger blast radius and should be a separate higher-risk mode or future capability. | If later added, it should require terminal run status, no active leases/workers/submitted operations, managed-root and marker/provenance proof, retention compatibility, dependency/reference checks, symlink rejection, dry-run explanation, result/tombstone records, and a stronger explicit intent than candidate cleanup. |
| Filtered hard cleanup by tags, datetimes, and attributes | include | User clarified that cleanup should support explicit selection beyond stale or old candidates. | Filters should operate over recorded plain-data facts such as cleanup candidate metadata, retention hints, timestamps, tags, candidate kind/reason, status, stage, run, or artifact attributes. |
| Preflight warnings for cleanup and retention support | include | Roadmap requires warnings for unsafe cleanup paths and unsupported retention policies. | Should be read-only. |
| Cleanup result records | include | User agreed cleanup correctness should depend on cleanup reports/results and authority facts, not event sinks. | Mutating cleanup should always produce deterministic result records for review and reconciliation. |
| Cleanup event emission | include | Stage 20 is complete, so cleanup can project cleanup planning and result facts into `PipelineEventRecord` audit events. | Events should be emitted after cleanup facts/results exist, with configured sinks observe-only and never authorizing or blocking deletion. |
| Cleanup-specific event sink plugins | defer | Stage 20 already provides generic explicit event-sink plugin loading. | Stage 21 should emit generic cleanup events; service-specific cleanup notifications or cleanup sink packages remain external plugins. |
| Remote provider deletion enforcement | defer | Roadmap defers remote service retention enforcement and should avoid cloud-specific behavior. | Stage 21 can warn unsupported by selected stores. |
| Automatic retention enforcement | out of scope | Explicitly deferred by roadmap. | No background deletion, scheduler, daemon, or implicit TTL sweeps. |
| Arbitrary directory cleanup or global cache GC | out of scope | Roadmap rejects arbitrary guessing and global cache collection. | Cleanup must be metadata-driven and rooted in Loom-owned paths. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Lock Stage 21's primary optimization: conservative safety and inspectability versus broader cleanup convenience. | none | 1 | Optimize for safety, explicit intent, and reviewable reports over broad automatic cleanup, while supporting explicit filtered hard cleanup. | This determines defaults, CLI behavior, and whether convenience shortcuts are allowed. | Resolved by user agreement and clarification. | confirmed |
| FRQ-2 | Decide cleanup audit behavior after Stage 20 completion. | FRQ-1 | 2 | Require cleanup result records and include cleanup event emission as an audit projection over cleanup reports/results; deletion correctness should not depend on event sinks. | Stage 20 event APIs are now available, so cleanup can join the runtime audit timeline without coupling deletion to observer delivery. | Resolved by user agreement and Stage 20 completion. | confirmed |
| FRQ-3 | Decide how aggressive run-collection GC should be in the first implementation. | FRQ-1 | 3 | Start with dry-run and explicitly selected cleanup candidates inside runs; defer whole-run deletion to a separate higher-risk mode or future capability. | Run collection GC has higher data-loss blast radius than per-run cleanup. | Resolved by user confirmation to do GC first. | confirmed |
| FRQ-4 | Lock selector scope for filtered hard cleanup. | FRQ-1 | 4 | Support a bounded selector set over recorded Loom facts, including age thresholds such as `--older-than 7d`, tags/metadata, retention mode, timestamps, candidate kind/reason, run/stage status, stage name, artifact id/type, and avoid a general query language. | Selector scope determines CLI/API shape, report explainability, and validation obligations. | Resolved by user confirmation. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Cleanup dry-run reports | none | Build per-run cleanup reports from authority-backed cleanup candidates and safe ownership evidence. | Users must inspect what Loom would clean before deletion. | Include candidate summaries, safety status, rejection reasons, and estimated target paths. | `loom clean ... --dry-run` and Python APIs show candidates without mutating files. | Read cleanup candidates and artifact/materialized refs, validate path safety, return report records. | Per-run cleanup planning. | Unit and contract tests for candidate selection, skipped candidates, and report serialization. | confirmed |
| FR-2 | Explicit deletion intent and result records | FR-1 | Delete only when the caller supplies explicit delete intent, and always produce cleanup result records for mutating cleanup. | Prevent accidental destructive behavior and preserve reviewable evidence. | Include programmatic intent, CLI confirmation/`--yes`, result records, failures, and skipped items. | Users see deleted, skipped, rejected, and failed paths. | Delete only approved safe paths and record deterministic results. Event sinks do not authorize or block deletion. | Safe cleanup execution. | Unit/integration tests using temporary directories, permission failures where practical, result serialization, and no out-of-root deletion. | confirmed |
| FR-3 | Path safety and ownership checks | FR-1 | Enforce managed roots, metadata/marker ownership, symlink rejection, and no arbitrary scans. | This is the core data-loss protection. | Include local filesystem path checks and unsupported handling for non-local or external refs. | Unsafe candidates are rejected with visible reasons. | Validate normalized paths without following symlinks and require ownership evidence. | Cleanup safety contract. | Contract/unit tests for outside-root paths, symlinks, missing markers, and visible errors. | confirmed |
| FR-4 | Retention metadata and inspection | none | Define and validate generic retention hints such as keep, temporary, archive, and external. | Users need to express lifecycle intent without automatic deletion. | Include serialization, inspection, export/import visibility, and unsupported-policy warnings. | Retention is visible in inspection and bundle/export metadata. | Preserve plain-data compatibility and map retention to cleanup eligibility only when explicit cleanup runs. | Retention policy records. | Serialization, artifact inspection, bundle/import, and preflight tests. | confirmed |
| FR-5 | Conservative run-collection GC | FR-1, FR-2, FR-3 | Plan and optionally delete selected cleanup candidates across a run collection without deleting whole run directories. | Users need collection-level maintenance after many runs. | Include explicit candidate selection and dry-run; defer whole-run deletion to a separate higher-risk mode or future capability. | `loom gc ... --dry-run` summarizes selected candidates across runs. | Use run collection/read-model facts and avoid treating the catalog as authoritative. | Run-collection cleanup. | Integration tests with multiple temporary run directories and stale/unsafe candidates. | confirmed |
| FR-6 | Filtered hard cleanup selectors | FR-1, FR-2, FR-3, FR-4 | Select cleanup candidates by bounded selectors such as `--older-than 7d`, tags, datetimes, retention hints, candidate attributes, run/stage status, and artifact attributes before dry-run or explicit deletion. | Users need targeted cleanup beyond stale or old defaults. | Include a small first-class selector set over recorded plain-data facts; avoid an arbitrary query language in first implementation. | `loom clean` and `loom gc` can show or delete candidates matching explicit selectors. | Apply selectors before safety validation and deletion, and explain why each candidate matched, skipped, or was rejected. | Targeted hard cleanup. | Unit/contract tests for selector parsing, metadata matching, timestamp filters, selector explanations, and safety invariants. | confirmed |
| FR-7 | Cleanup and retention preflight warnings | FR-3, FR-4, FR-6 | Warn about unsafe cleanup paths and unsupported retention policies. | Users should see safety/capability problems before deletion. | Include read-only diagnostics; no mutation or provider contact beyond existing capability checks. | Preflight reports unsupported or unsafe cleanup/retention situations. | Inspect candidate paths and store capabilities. | Diagnostics and readiness checks. | Unit tests for warning codes and CLI/diagnostic rendering. | confirmed |
| FR-8 | Cleanup audit event emission | FR-1, FR-2, FR-3, FR-5, FR-6 | Emit Stage 20 `PipelineEventRecord` audit events for cleanup planning and cleanup results after the corresponding cleanup report or result fact exists. | Cleanup should be visible in the runtime audit timeline now that Stage 20 is complete. | Include generic cleanup event names/resources/payloads; exclude cleanup-specific sink plugins or service-specific notifications. | Users and configured event sinks can observe recorded cleanup plans/reports, rejections, deletions, and failures as audit events. | Project recorded cleanup reports/results into events; dispatch configured sinks observe-only; sink failures are visible but do not change cleanup correctness. | Cleanup audit timeline. | Unit/contract/integration tests for event serialization, append-before-dispatch ordering, sink failure non-blocking behavior, and event payload traceability to cleanup result records. | confirmed |

## Behavior Baseline

Included functionality:

- Per-run cleanup dry-run reports over authority-backed cleanup candidates.
- Explicit delete intent for any mutating cleanup operation.
- `loom clean` CLI presentation and confirmation over cleanup APIs.
- Managed-root, metadata/marker ownership, symlink rejection, and visible
  deletion-failure safety checks.
- Generic retention metadata and inspection using keep, temporary, archive, and
  external policy hints.
- Candidate-level run-collection GC across multiple runs.
- Bounded selectors such as `--older-than 7d`, tags/metadata, retention mode,
  timestamps/age, candidate kind/reason, run/stage status, stage name, and
  artifact id/type.
- Cleanup and retention preflight warnings.
- Cleanup result records for mutating cleanup.
- Cleanup audit event emission through the Stage 20 event surface.

User-visible behavior:

- Users can preview cleanup with no mutation, including why each candidate
  matched, skipped, or was rejected.
- Users can delete only by providing explicit delete intent or confirming in
  the CLI.
- Users can run collection-level GC for selected cleanup candidates inside
  runs, without deleting whole run directories.
- Users can inspect retention hints and cleanup results through stable records
  and diagnostics.
- Users and configured Stage 20 event sinks can observe recorded cleanup reports
  and results as audit events.

Default behavior:

- Dry-run first.
- Deletion is disabled unless explicit delete intent is supplied.
- Unsafe candidates are rejected rather than repaired or guessed.
- Cleanup selectors are bounded and operate only over recorded Loom facts.
- Cleanup event emission projects already-created cleanup reports/results; event
  sinks are observe-only.

Failure behavior and diagnostics:

- Paths outside managed roots are rejected.
- Candidates without ownership evidence are rejected.
- Symlinks and paths requiring symlink traversal are rejected.
- Unsupported external or remote deletion is skipped or rejected with a visible
  reason.
- Deletion failures are reported in cleanup result records and do not disappear
  into logs only.
- Event sink failures are recorded through Stage 20 observer-failure surfaces
  and do not change cleanup correctness.

Explicit deferrals:

- Whole-run directory deletion.
- Cleanup-specific event sink plugins.
- Remote provider deletion enforcement.

Out-of-scope behavior:

- Automatic retention enforcement.
- Arbitrary cleanup query languages.
- Arbitrary directory cleanup or global cache garbage collection.
- Destructive cleanup without explicit user intent.
- Event sink authorization or veto of deletion.

Context compaction/reset checkpoint:

- Checkpoint status: confirmed
- Notes path: `docs/roadmap/stage-21/planning.md`
- Resume instruction: reload this planning artifact,
  `.codex/workflows/roadmap-stage-planning.md`,
  `.codex/prompts/roadmap-stage-design-agreement.md`,
  `.codex/prompts/roadmap-stage-design-safety-review.md`, `docs/roadmap.md`,
  `docs/structure.md`, `docs/GLOSSARY.md`, the cited feature docs, and the
  Stage 20 event surfaces before drafting proposed implementation shape and the
  design-agreement queue.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Likely modules or packages:

- Add a focused `loom.pipeline.cleanup` package for cleanup policy and
  execution mechanics. Expected internal modules are `records.py`,
  `selectors.py`, `planning.py`, `safety.py`, `execution.py`, `events.py`, and
  `errors.py`; implementation may collapse modules if the first pass remains
  small, but the ownership boundary should stay explicit.
- Keep cleanup candidate truth and mutating cleanup evidence authority-backed.
  Extend `loom.pipeline.stores.read_models` and
  `loom.pipeline.stores.authority` with explicit recorded cleanup report fact
  records, cleanup result fact contracts, and append/list protocol methods as
  needed. Preserve existing `CleanupCandidate` records and serialization.
  Cleanup result facts should reference candidate ids, target refs, revisions,
  and outcomes instead of mutating or removing candidate rows. Default dry-run
  previews remain side-effect-free and do not append authority facts.
- Add typed retention helpers in `loom.artifacts`, such as `RetentionMode`,
  `RetentionPolicy`, and normalization/serialization helpers, while retaining
  plain-data metadata compatibility and not turning retention into automatic
  deletion.
- Update concrete authority implementations, service authority payloads, and
  store tests to persist and read explicit recorded cleanup report facts and
  mutating cleanup result facts. The SQLite schema remains private to
  implementations.
- Update `loom.diagnostics.backend` and `loom.diagnostics.preflight` to consume
  cleanup/retention facts read-only for warnings and inspection.
- Add thin CLI wrappers, likely `loom.cli.clean` and `loom.cli.gc`, registered
  from `loom.cli.main`, that parse selectors and confirmation flags, call the
  cleanup APIs, and format text/JSON output.
- Use `loom.runs` and run-catalog utilities only for run collection discovery
  and display. Candidate truth and deletion authority must come from each
  run's authoritative store.

Likely public classes, functions, or protocols:

- `CleanupSelectorSet` or equivalent bounded selector record with first-class
  fields for age/timestamp, tag or metadata equality, retention mode, candidate
  kind/reason, run or stage status, stage name, and artifact identity/type.
- `CleanupReport`, `CleanupCandidateDecision`, `CleanupSafetyDecision`, and
  related plain-data records for dry-run output and selector/safety
  explanations.
- `CleanupDeleteIntent` or equivalent explicit destructive-intent token. Public
  APIs should not accept a bare boolean as the only destructive guard.
- `CleanupResultRecord`, `CleanupDeletedTarget`, `CleanupRejectedTarget`, and
  `CleanupFailure` or equivalent result records for mutating operations.
- `CleanupManagedRoot` and `CleanupTarget` records for path-safety validation.
- `RetentionMode`, `RetentionPolicy`, and retention normalization helpers.
- `plan_cleanup(...)`, `execute_cleanup(...)`,
  `plan_collection_gc(...)`, and `execute_collection_gc(...)` or equivalent
  API entrypoints that accept a `RunStore`/authority config and selectors.
- A small `CleanupTargetAdapter`-style protocol may be introduced only around
  target resolution/deletion capabilities. Stage 21 should provide local
  filesystem support and report remote/external deletion as unsupported.

Likely internal helpers:

- Duration and timestamp normalization for selectors such as `--older-than 7d`.
- Selector matching over recorded plain-data facts, including explanation
  strings or reason codes for matched and skipped candidates.
- Candidate-to-target resolution that correlates cleanup candidates,
  materialized refs, artifact facts, retention hints, managed roots, and
  marker/metadata ownership evidence.
- Managed-root resolution from trusted authority/store/config facts and local
  path helpers. A broad run-collection path or user-supplied directory is not
  itself ownership proof.
- Local path safety checks that reject outside-root paths, missing ownership
  evidence, symlink targets, and traversal through symlinked path components.
- Delete execution helpers that remove files/directories only after safety
  approval and record visible failures.
- Event projection helpers that turn persisted explicit cleanup report facts or
  mutating cleanup result facts into compact Stage 20 `PipelineEventRecord`
  payloads.

Data flow:

- Per-run cleanup:
  1. Open the run through `RunStore` or `PerRunAuthorityStore`.
  2. Read authoritative cleanup candidates, materialized refs, artifact facts,
     retention hints, statuses, leases, submitted operations, and revisions.
  3. Apply bounded selectors and produce candidate decisions with match/skip
     explanations.
  4. Resolve selected candidates to cleanup targets and run path-safety checks.
  5. Return a dry-run `CleanupReport` by default without deleting files or
     writing authority/event records.
  6. If explicit delete intent is supplied, execute only approved targets,
     persist a cleanup result fact through authority, and then project the
     recorded fact into cleanup audit events.
- Run-collection GC:
  1. Enumerate candidate `run_uri` values from explicit CLI/API input or run
     collection discovery.
  2. Open each run's authority and run the same per-run selector and safety
     pipeline.
  3. Aggregate per-run reports/results without deleting whole run directories.
- Cleanup events:
  - Events are emitted only after the corresponding explicit cleanup report
    fact or mutating cleanup result fact exists. Unrecorded dry-run previews
    remain side-effect-free. Event sink delivery remains observe-only and
    cannot authorize, veto, or define deletion correctness.

Dependency direction:

- `loom.pipeline.cleanup.records` and `loom.artifacts` retention records should
  remain import-light and depend only on serialization, timestamps, and stable
  value types.
- Store protocols and authority implementations may import cleanup record
  value types for persistence contracts.
- Cleanup planning/execution may import store protocols, read models,
  retention helpers, and event projection helpers. It must not import CLI,
  diagnostics presentation, plugins, or project code.
- CLI and diagnostics import cleanup APIs; cleanup must not import CLI or
  diagnostics.
- Event projection imports Stage 20 event models/dispatch helpers, but cleanup
  correctness depends on authority cleanup facts and result records, not sink
  success.

Extension points and flexibility boundaries:

- Local filesystem deletion is the only first implementation deletion adapter.
  Remote or external refs are reported as unsupported unless a future
  store-owned adapter proves deletion support and ownership.
- Retention modes are generic policy hints. Future organization policies may
  consume them, but Stage 21 does not add policy engines, schedulers,
  background TTL deletion, or domain-specific retention classes.
- Whole-run deletion remains a separate future/higher-risk capability with
  stronger preconditions and tombstone/catalog reconciliation records.
- Event sinks can observe cleanup events through the generic Stage 20 registry.
  Cleanup-specific sink plugins remain deferred.

Generic interface, adapter, or protocol shape:

- The reusable contract is a small cleanup planning/execution API over
  authority-backed facts, bounded selectors, target safety decisions, explicit
  delete intent, and result records.
- The adapter boundary should be target resolution and deletion capability, not
  policy. Store/provider adapters may later prove ownership and perform
  provider-native deletion, but selectors, dry-run reports, result records, and
  safety outcomes stay generic.
- Preflight and diagnostics consume the same plain-data cleanup/retention
  records as CLI and tests; they should not invent separate warning inputs.

Future-roadmap impact:

- Future remote store deletion can implement the target adapter/capability
  boundary without changing selector or result-record semantics.
- Future whole-run deletion can reuse selectors, safety decisions, result
  records, and event projection while adding terminal-state, lease/submission,
  dependency/reference, marker/provenance, and tombstone gates.
- Future organization retention policies can read retention hints and cleanup
  records without becoming part of core Loom Stage 21 behavior.
- Future service or multi-host cleanup can reuse authority facts and result
  records, but Stage 21 should not require a hosted cleanup daemon.

Compatibility constraints:

- Existing cleanup candidate records and retention metadata must remain readable.
- Existing bundle/export/import visibility for cleanup candidates must not be
  reduced.
- New explicit cleanup report, cleanup result, and retention records must be
  schema-versioned or otherwise loud-fail compatible with existing authority
  schema policy.
- Event payloads must be compact projections with references to explicit
  cleanup report records or cleanup result records, not the only durable source
  of cleanup evidence.
- Selector records must remain plain-data-compatible and avoid embedding an
  arbitrary expression language.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Cleanup module/API ownership. | FR-1, FR-2, FR-3, FR-5, FR-6 | 1 | recorded recommendation | Put policy and execution mechanics in `loom.pipeline.cleanup`; keep CLI and diagnostics as wrappers/readers. | Prevents deletion policy from being scattered across CLI, diagnostics, stores, and catalogs. | Repo structure and CLI docs give a clear boundary. | confirmed |
| DAQ-2 | Durable cleanup evidence source. | DAQ-1, FR-2, FR-8 | 2 | recorded recommendation | Persist mutating cleanup result records as authority-backed cleanup facts; use events only as projections. | Deletion correctness needs durable evidence independent of observer delivery. | Existing authority/event split gives a clear answer. | confirmed |
| DAQ-3 | Dry-run side effects and audit recording. | DAQ-2, FR-1, FR-8 | 3 | recorded recommendation | Dry-run previews return deterministic reports without deletion or authority/event writes by default; only explicitly recorded reports or mutating cleanup results are projected into events. | Preserves "dry-run means no mutation" while keeping event facts traceable. | Repo safety goals make side-effect-free dry-run the safe default. | confirmed |
| DAQ-4 | Path safety and local deletion contract. | DAQ-1, DAQ-2, FR-3 | 4 | recorded recommendation | Require managed roots, authority/metadata or marker ownership, symlink rejection, unsupported external/remote handling, and visible failures before deletion. | This is the main data-loss prevention contract. | Roadmap and reliability docs fully specify this branch. | confirmed |
| DAQ-5 | Selector model. | FR-6, DAQ-1 | 5 | recorded recommendation | Use a bounded plain-data selector record with age/timestamp, tag/metadata, retention, candidate, status, stage, and artifact fields; do not add a query language. | Keeps cleanup explainable, testable, and safe. | User already confirmed bounded selectors. | confirmed |
| DAQ-6 | Retention policy shape. | FR-4, DAQ-5 | 6 | recorded recommendation | Add typed `RetentionMode`/`RetentionPolicy` helpers in `loom.artifacts`, serialized as plain-data metadata/hints, without automatic deletion or ownership authority. | Retention must be inspectable and future-friendly without becoming a policy engine. | Feature docs and existing artifact metadata point to this shape. | confirmed |
| DAQ-7 | Run-collection GC authority boundary. | DAQ-1, DAQ-5, FR-5 | 7 | recorded recommendation | Use run collections/catalogs only to discover runs; open each run's authority for candidate truth and delete only selected candidates, not run directories. | Prevents derived catalog data from authorizing deletion. | User confirmed candidate-level GC and store docs define authority. | confirmed |
| DAQ-8 | Cleanup event taxonomy and payload shape. | DAQ-2, DAQ-3, FR-8 | 8 | recorded recommendation | Emit compact generic cleanup events, such as recorded-report and recorded-result events, whose payloads reference cleanup facts and summarize counts/outcomes. | Event names and payloads are public audit surface, but should not duplicate large path lists or become truth. | Stage 20 event grammar supports generic resource refs and payloads. | confirmed |
| DAQ-9 | Remote/external deletion boundary. | DAQ-4, DAQ-6 | 9 | auto-approved candidate | Treat remote/external deletion as unsupported in Stage 21 unless a store-owned future adapter proves capability and ownership. | Avoids accidental cloud/provider-specific behavior. | Roadmap explicitly defers remote enforcement. | confirmed |
| DAQ-10 | CLI and preflight responsibility split. | DAQ-1, DAQ-4, DAQ-5 | 10 | auto-approved candidate | CLI parses/formats/confirms; preflight warns read-only; neither owns deletion policy. | Keeps Python APIs testable and avoids terminal-only safety logic. | CLI and preflight docs already require this split. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Cleanup module/API ownership | Add a focused `loom.pipeline.cleanup` package for planning, selectors, safety, execution, records, event projection, and errors. | No direct user question; resolved from repo structure. | Putting deletion policy in CLI, diagnostics, run catalog, or store implementations. | CLI must stay a wrapper, diagnostics read-only, catalogs derived, and stores authoritative but not policy owners. | Centralizes safety and makes tests target one policy layer. | Future adapters can reuse the same policy layer without changing CLI behavior. | Supports future whole-run and remote cleanup as separate adapters/capabilities. | Creates a public cleanup API surface under `loom.pipeline.cleanup`. | Package/import tests, unit tests for API records, docs update. | Revisit if cleanup grows beyond pipeline/run semantics and needs a top-level facade. | confirmed |
| DAQ-2 | Durable cleanup evidence source | Persist mutating cleanup result records as authority-backed cleanup facts; result records are correctness evidence and events are projections. | User confirmed result records are required and events are audit projections. | Making events or event-sink success the source of deletion truth; storing results only in CLI output/logs. | Authority already owns cleanup candidates, revisions, audit evidence, and snapshots. | Adds explicit persistence work but avoids ambiguous evidence paths. | Future reconciliation and catalogs can read result facts without sink dependencies. | Whole-run deletion can later add tombstones beside the same result family. | Extends authority/read-model contracts with cleanup result facts. | Store protocol, concrete backend, serialization, and event traceability tests. | Revisit if authority schema changes make cleanup facts too heavyweight for non-mutating operations. | confirmed |
| DAQ-3 | Dry-run side effects and audit recording | Dry-run previews are side-effect-free by default; only explicitly recorded cleanup reports or mutating cleanup results are durable and event-projected. | User confirmed dry-run first and inspectable cleanup; no further user choice needed. | Appending audit events for every dry-run by default; treating dry-run as an implicit authority write. | A dry-run that writes events or authority facts is not a true no-mutation preview. | Keeps preview behavior simple and unsurprising. | Still allows future explicit "record report" audit mode without changing delete semantics. | Audit-heavy deployments can later opt into recorded dry-run reports. | Cleanup event projection must accept only durable report/result inputs. | Tests must prove default dry-run does not delete files or append authority/event records. | Revisit if users need mandatory audit trails for previews. | confirmed |
| DAQ-4 | Path safety and local deletion contract | Delete only approved local filesystem targets under managed roots with metadata/marker ownership, symlink rejection, unsupported remote/external handling, and visible failures. | User confirmed safety checks cannot be bypassed by hard-cleanup selectors. | Best-effort deletion, arbitrary directory scans, symlink following, deleting unowned external refs. | Roadmap and feature docs make data-loss prevention the primary constraint. | Concentrates complex filesystem behavior in a small testable validator. | Future providers must prove equivalent ownership and capability before deletion. | Remote deletion, whole-run deletion, and policy engines remain compatible by adding stronger checks. | Defines safety decision records and optional target adapter contract. | Unit/integration tests for outside-root, missing ownership, symlink, failure, and temp-dir deletion cases. | Revisit if managed-root discovery is too implicit in implementation. | confirmed |
| DAQ-5 | Selector model | Use bounded plain-data selectors for age/timestamps, tags/metadata, retention, candidate kind/reason, run/stage status, stage name, and artifact identity/type. | User confirmed bounded selectors first, with `--older-than 7d` representative. | Arbitrary query language; selector flags that imply deletion without safety validation. | Bounded selectors are explainable, serializable, and testable. | Prevents a policy parser from becoming a hidden subsystem. | New selector fields can be added deliberately with tests and docs. | Organization policy layers can later compile to selector records. | Creates `CleanupSelectorSet` and CLI parser mapping. | Selector parsing/matching/explanation tests and CLI contract tests. | Revisit if users need compound boolean logic; do not add it without a separate design pass. | confirmed |
| DAQ-6 | Retention policy shape | Add typed artifact retention helpers while storing retention as generic plain-data metadata/hints; retention never proves ownership or triggers automatic deletion. | User confirmed retention metadata/inspection but automatic enforcement remains out of scope. | Domain-specific retention classes; automatic TTL deletion; making `external` deletable. | Existing `ExternalArtifactRef.retention` and docs already use metadata-style hints. | Gives validation without overloading `ArtifactRef` or stores. | Future stores and policies can consume the same hints. | Remote stores and archive/export workflows can interpret retention later. | Adds `RetentionMode`/`RetentionPolicy` helper records and normalization functions. | Serialization, artifact inspection, bundle/export/import, and preflight warning tests. | Revisit if retention needs stage/run-level policy inheritance beyond artifact metadata. | confirmed |
| DAQ-7 | Run-collection GC authority boundary | Collection GC discovers runs from explicit input/catalogs but opens each run's authority for candidates and result writes; it deletes selected candidates only. | User confirmed GC first and whole-run deletion deferred. | Treating the run catalog as deletion authority; deleting whole run directories in first GC. | Catalogs are derived indexes and cannot authorize destructive actions. | Reuses per-run cleanup code and avoids a second deletion path. | Future whole-run GC can add a separate result/tombstone path. | Supports stacked future features without invalidating first GC. | Adds collection-level report/result aggregation over per-run cleanup APIs. | Integration tests with multiple temp runs and unsafe candidates. | Revisit when whole-run deletion is designed. | confirmed |
| DAQ-8 | Cleanup event taxonomy and payload shape | Emit generic cleanup events for recorded cleanup reports/results with compact payload summaries and references to durable cleanup facts. | User confirmed Stage 20 events are included as audit projections. | Per-file event spam; sink-specific cleanup notifications; events without durable cleanup facts. | Stage 20 event grammar supports generic event names/resources and observe-only sinks. | Keeps audit payloads small and traceable. | Future sinks can observe without changing cleanup APIs. | Future strict-audit or service deployments can strengthen recording policy separately. | Uses `PipelineEventRecord`, `EventResourceRef`, and dispatcher ordering from Stage 20. | Event serialization, append-before-dispatch, sink failure, and fact-reference tests. | Revisit if audit consumers need a finer event taxonomy. | confirmed |
| DAQ-9 | Remote/external deletion boundary | Report remote/external deletion as unsupported unless a future store-owned adapter proves support and ownership. | User confirmed remote provider deletion enforcement is deferred. | First-party cloud deletion behavior in Stage 21; assuming external refs are safe to delete. | Stage 21 must stay domain-neutral and provider-neutral. | Keeps first implementation local and deterministic. | Future adapters can be capability-gated without changing selectors/results. | Aligns with remote-store roadmap deferrals. | Adapter contract should expose capability and ownership proof, not provider policy. | Preflight/cleanup tests for unsupported remote/external candidates. | Revisit when remote store deletion enters roadmap scope. | confirmed |
| DAQ-10 | CLI and preflight responsibility split | CLI owns parsing, formatting, and confirmation; preflight owns read-only warnings; cleanup APIs own policy and deletion behavior. | No direct user question; resolved from CLI/preflight docs. | CLI-implemented deletion rules; preflight mutation; terminal prompts in programmatic APIs. | Keeps Python callers and tests on the same behavior as CLI. | Reduces duplicated safety logic. | Future UIs can call the same cleanup APIs. | Supports service/automation use without terminal assumptions. | Adds CLI command modules that call public cleanup APIs. | CLI contract/e2e tests plus preflight warning-code tests. | Revisit if CLI output needs a reusable formatter API. | confirmed |

Design-safety review notes:

- DAQ-2 remains a recorded recommendation, with an added constraint that
  cleanup results append outcome facts and do not mutate or remove existing
  cleanup candidates.
- DAQ-4 remains a recorded recommendation, with an added constraint that
  managed roots must come from trusted authority/store/config facts and local
  path helpers; collection input paths are discovery hints, not ownership
  proof.
- DAQ-8 remains a recorded recommendation. Compact event payloads are required
  so the durable cleanup fact remains the reviewable source and event records
  do not become large per-file deletion logs.
- DAQ-9 and DAQ-10 were challenged as auto-approved candidates and upheld
  because they directly follow roadmap deferrals, plugin boundaries, CLI
  boundaries, and preflight read-only behavior.

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Whether cleanup should be top-level instead of under `pipeline`; current run-store and candidate dependencies keep it under pipeline for Stage 21. | FR-1, FR-2, FR-3, FR-5, FR-6; `docs/structure.md`; `docs/features/cli.md`. | Reviewed and upheld by design-safety review. | confirmed |
| DAQ-2 | recorded recommendation | Whether result records belong only in events; rejected because event sinks are observe-only. | FR-2, FR-8; Stage 20 event docs/source; authority cleanup candidates. | Record authority-backed cleanup facts as correctness source. | confirmed |
| DAQ-3 | recorded recommendation | Whether dry-run audit emission should be default; rejected because default dry-run must be side-effect-free. | Behavior baseline; FR-1, FR-8. | Record default no authority/event writes for unrecorded dry-run previews. | confirmed |
| DAQ-4 | recorded recommendation | Whether hard-cleanup selectors can bypass safety; rejected by user-confirmed behavior. | FR-3, FR-6; reliability cleanup safety docs. | Record local path-safety contract and unsupported remote boundary. | confirmed |
| DAQ-5 | recorded recommendation | Whether selector language should be more expressive; deferred because bounded selectors were confirmed. | FR-6; user `--older-than 7d` confirmation. | Record selector fields and no query language. | confirmed |
| DAQ-6 | recorded recommendation | Whether retention should be an enforcement policy; rejected by roadmap deferral. | FR-4; artifacts/reliability docs. | Record typed plain-data hints only. | confirmed |
| DAQ-7 | recorded recommendation | Whether GC can trust catalogs; rejected because catalogs are derived. | FR-5; run-store/run-catalog docs. | Record per-run authority as deletion source. | confirmed |
| DAQ-8 | recorded recommendation | Whether events should include per-target full details; rejected in favor of durable fact references and compact summaries. | FR-8; Stage 20 event grammar. | Record generic event projection shape. | confirmed |
| DAQ-9 | auto-approved candidate | Whether Stage 21 should include provider deletion; rejected by roadmap deferral and domain-neutrality. | Capability triage; remote-store deferrals. | Record unsupported external/remote deletion by default. | confirmed |
| DAQ-10 | auto-approved candidate | Whether CLI/preflight should own policy; rejected by existing CLI/preflight boundaries. | CLI/preflight docs; FR-7. | Record wrapper/read-only split. | confirmed |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| DSR-1: Cleanup API ownership is safe if policy stays outside adapters and presentation layers. | DAQ-1, DAQ-4, DAQ-10; FR-1 through FR-7 | Low risk. `loom.pipeline.cleanup` matches current authority/run-store dependencies and avoids CLI/catalog policy drift. | Adapter reuse remains safe only if adapters prove target support/ownership and do not own selector policy, retention semantics, or delete intent. | Keep cleanup policy in `loom.pipeline.cleanup`; keep CLI/preflight wrappers thin and read-only where appropriate. | passed |
| DSR-2: Result facts must be append-only relative to cleanup candidates. | DAQ-2; FR-2, FR-8 | Mutating or deleting candidate records during cleanup would harm auditability, bundle/import compatibility, and future reconciliation. | Result records can be reused by whole-run deletion and catalogs if they reference candidate ids, targets, revisions, and outcomes without erasing candidate evidence. | Added planning notes that cleanup results append outcome facts and do not mutate/remove existing cleanup candidates. | revised and passed |
| DSR-3: Managed-root evidence needs a trusted source. | DAQ-4, DAQ-7; FR-3, FR-5 | Treating `RUNS_DIR` or arbitrary collection input as a managed root would weaken path-safety and future remote-store boundaries. | Target adapters remain reusable if managed roots come from authority/store/config facts and local path helpers, not presentation inputs. | Added planning notes that broad collection paths are discovery hints, not ownership proof. | revised and passed |
| DSR-4: Dry-run and cleanup events have a clear compatibility boundary. | DAQ-3, DAQ-8; FR-1, FR-8 | Default dry-runs that write events would surprise users and make "preview" mutating; per-file events would create noisy public audit surface. | Event projection stays reusable when it references durable report/result facts and emits compact summaries. | Keep unrecorded dry-run previews side-effect-free; keep recorded report/result events compact. | passed |
| DSR-5: Retention and remote/external deletion deferrals are safe. | DAQ-6, DAQ-9; FR-4 | Low risk if retention remains a typed hint and remote/external deletion remains unsupported without future store-owned capability proof. | Future remote providers can add deletion through capability-gated adapters without changing selectors/results. | Keep retention generic and provider-neutral; keep local filesystem as the only Stage 21 deletion adapter. | passed |

Gate result:

- Status: passed
- Reviewer: managing-agent design-safety review using
  `.codex/prompts/roadmap-stage-design-safety-review.md`
- Files read:
  - `docs/roadmap/stage-21/planning.md`
  - `.codex/prompts/roadmap-stage-design-safety-review.md`
  - `docs/roadmap.md`
  - `docs/features/reliability.md`
  - `docs/features/remote-stores.md`
  - `docs/features/plugins.md`
  - `docs/features/run-catalog.md`
  - `docs/features/execution.md`
- Files changed:
  - `docs/roadmap/stage-21/planning.md`
- Blockers: none
- Auto-approved decisions upheld or overturned:
  - Upheld DAQ-9 remote/external deletion boundary.
  - Upheld DAQ-10 CLI and preflight responsibility split.
  - Overturned: none.
- Recorded recommendations:
  - DAQ-1 through DAQ-8 remain recorded recommendations.
  - Add append-only cleanup-result evidence relative to existing candidate
    records.
  - Add trusted managed-root-source constraint for path safety.
- Future-roadmap impact summary:
  - Whole-run deletion can build on selector, safety, result, and event
    projection records, but still needs separate terminal-state, active-lease,
    submitted-operation, dependency/reference, marker/provenance, and tombstone
    gates.
  - Remote deletion can be added later through capability-gated, store-owned
    target adapters without changing core selector/result semantics.
  - Organization policy engines can compile policy into selectors and retention
    hints later without becoming Stage 21 behavior.
  - Service-specific event sinks remain plugins over Stage 20 event contracts.
- Generic interface, adapter, and protocol assessment:
  - Cleanup records and selectors are generic enough if they stay plain-data
    records over authority-backed facts.
  - Target adapters are generic enough only when limited to target resolution,
    capability proof, ownership proof, and deletion execution. They must not
    choose selector policy, retention semantics, or delete intent.
  - Store protocols should expose append/list cleanup facts without exposing
    backend schemas.
- Planning revisions required:
  - Completed in this pass: append-only cleanup-result constraint and
    trusted-managed-root-source constraint.
- Accepted risks:
  - Unrecorded dry-run previews are not persisted or emitted by default.
  - Stage 21 first deletion adapter is local-filesystem only.
  - Cleanup result persistence adds authority schema and compatibility work.
- Revisit triggers:
  - Remote artifact-store deletion or provider retention enforcement enters
    scope.
  - Whole-run deletion enters scope.
  - Audit-heavy deployments require recorded dry-run previews by default.
  - Cleanup result facts become too large or too slow for authority-backed
    storage without compaction or paging.

## Practical Design Notes

Public Python API surface:

- Public cleanup APIs should be callable without a terminal and should default
  to non-mutating report generation.
- Records should be dataclass-style, frozen where practical, typed, and
  plain-data serializable, matching existing authority/read-model conventions.
- Destructive calls should require an explicit `CleanupDeleteIntent` or
  equivalent value object. A bare `delete=True` should not be the primary
  public safety mechanism.
- Collection GC should call the same per-run cleanup APIs and return aggregate
  report/result records.

CLI surface:

- `loom clean RUN_URI` presents per-run cleanup reports and supports bounded
  selectors such as `--older-than 7d`, candidate kind/reason, retention mode,
  and metadata/tag filters as implementation phases confirm exact flag names.
- `loom gc RUNS_DIR` or equivalent collection input presents aggregate reports
  across runs and deletes selected candidates only after confirmation or
  `--yes`.
- CLI confirmation belongs only in CLI; programmatic APIs must express delete
  intent structurally.
- Text output should summarize selected, skipped, rejected, deleted, and failed
  targets. JSON output should expose the underlying plain-data records.

Persisted records and file layout:

- Existing cleanup candidates are already persisted in authority state.
- Retention metadata exists today as generic metadata on some artifact-related
  records; Stage 21 should add typed validation helpers while preserving that
  plain-data shape.
- Mutating cleanup should append cleanup result facts to authority state. If the
  implementation records cleanup reports for audit, those report facts should
  also be authority-backed.
- Cleanup results should reference candidates and outcomes. They must not erase
  candidate evidence or rely on deleting candidate records for reconciliation.
- Unrecorded dry-run previews should not append authority facts or event
  records by default.
- Local filesystem file layout should remain an implementation detail of
  authority backends and local artifact/materialization stores; cleanup APIs
  should use store/path helpers rather than hard-coded sidecar paths where
  possible.
- Managed roots must come from trusted store/config facts and local path
  helpers. A run-collection directory supplied to `loom gc` is a discovery
  input, not proof that every descendant path is safe to delete.

Import boundaries and dependencies:

- Cleanup logic should remain dependency-light and local/fake-testable.
- CLI should not own deletion policy.
- Diagnostics and preflight should remain read-only.
- Cleanup records should be import-light enough for store protocols and tests.
- Cleanup execution may depend on authority/store protocols and local
  filesystem helpers, but not on CLI, diagnostics presentation, plugins, or
  project packages.
- Event projection should be isolated so core cleanup planning can be tested
  without loading sink registries.

Failure modes and diagnostics:

- Unsafe paths are rejected with stable reason codes, not silently omitted.
- Missing ownership evidence is a rejection, not a warning that still permits
  deletion.
- Symlink targets or symlinked path components are rejected for deletion.
- Unsupported remote/external refs are skipped or rejected with explicit
  unsupported-capability reasons.
- Filesystem deletion failures are recorded in cleanup result records and
  surfaced in CLI/API results.
- Event sink failures use Stage 20 observer-failure records and do not alter
  cleanup success/failure.

Extension points and flexibility boundaries:

- Target adapters may later add provider-native deletion, but only behind
  explicit capability and ownership proof.
- Target adapters must not decide selector policy, retention semantics, or
  delete intent.
- Retention hints remain generic and cannot encode organization-specific
  compliance policy inside core Loom.
- Whole-run deletion is outside the Stage 21 first implementation path and must
  be designed separately.

Generic interfaces, adapters, and protocols:

- `CleanupTargetAdapter` or equivalent should resolve recorded candidates into
  concrete cleanup targets and perform deletion for supported backends.
- The adapter boundary must not decide selector policy, retention semantics, or
  delete intent. Those stay in cleanup planning/execution records.
- Store protocols should expose cleanup facts through append/list methods
  rather than leaking backend schemas.
- Cleanup result persistence should be append-only relative to existing
  cleanup candidates. Reconciliation is by candidate/result ids and revisions,
  not by deleting candidate evidence.

Future-roadmap compatibility:

- Whole-run deletion can reuse selector, safety, result, and event projection
  records while adding stronger gates and tombstones.
- Remote deletion can add adapters/capabilities without changing core selector
  semantics.
- Organization policy engines can compile policy into selectors and retention
  hints later without becoming Stage 21 behavior.
- Service deployments can store cleanup facts centrally and still use the same
  CLI/API reports.

Maintainability assessment:

- The proposed boundary keeps deletion policy in one tested module family and
  avoids duplicating safety logic in CLI, diagnostics, catalogs, or stores.
- The main maintainability cost is adding authority persistence contracts for
  cleanup results; that cost is justified because deletion evidence must be
  durable and reviewable.

Extensibility assessment:

- The design can add new selectors and target adapters incrementally.
- Retention remains extensible because it is typed for validation but stored as
  plain data.
- Events remain extensible because they reference durable cleanup facts and
  summarize outcomes rather than encoding every deletion detail as a separate
  event.

Flexibility and expansion assessment:

- The first implementation intentionally favors explicit records over implicit
  policies. That leaves room for future policy layers without creating hidden
  automatic deletion behavior now.
- The collection GC path reuses per-run cleanup, so future expansion can focus
  on selection/discovery without creating a second deletion engine.

Scalability and future compatibility:

- Per-target result records should avoid excessive event payloads. Store the
  detailed result as cleanup facts and emit compact event summaries.
- Collection GC should stream or page run discovery and per-run processing when
  implementation reaches large collections; Stage 21 planning does not require
  a global in-memory catalog mutation.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Cleanup candidate records need wrapper/report/result records instead of direct mutation. | Existing records are already serialized and carried through read models, and design-safety review confirmed candidate evidence should remain append-only. | Revisit during implementation-plan drafting if result facts cannot reference enough ownership or safety evidence without changing candidate records. |
| Local filesystem deletion is the only Stage 21 deletion adapter. | It keeps the first destructive implementation deterministic and testable while remote enforcement is deferred. | Revisit when remote artifact-store deletion or provider retention enforcement enters roadmap scope. |
| Dry-run reports are not persisted by default. | Preserves true dry-run behavior and avoids surprising authority/event writes. | Revisit if audit-heavy deployments require recorded preview reports. |
| Whole-run deletion remains outside first GC. | User confirmed candidate-level GC first and whole-run deletion needs stronger gates. | Revisit when terminal-state, lease/submission, dependency/reference, and tombstone semantics are designed. |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Per-run cleanup dry-run | A run with staged payload and worker handoff candidates reports selected, skipped, and rejected targets without deleting anything or appending authority/event facts by default. | Authority-backed cleanup candidates, local managed roots, materialized refs, and candidate/result records. | Unit tests for report records and selection outcomes; integration tests for no-mutation dry-run behavior. | confirmed |
| Bounded selector cleanup | A caller filters candidates with bounded selectors such as `--older-than 7d`, candidate kind/reason, retention mode, stage name/status, artifact id/type, and metadata/tag equality; report output explains matches and skips. | Cleanup selector records over authoritative plain-data facts. | Unit tests for selector parsing/matching/explanations; contract tests for selector serialization; CLI tests for representative flag mapping. | confirmed |
| Explicit deletion and result records | A caller provides explicit delete intent and only safe Loom-owned targets are removed; the cleanup result appends outcome facts that reference candidate ids and records deleted, skipped, rejected, and failed targets. | Local filesystem run directory and authority-backed cleanup result facts. | Unit tests for delete-intent validation and result serialization; integration tests using temporary directories and visible deletion failures. | confirmed |
| Path-safety rejection | Candidates outside managed roots, without ownership evidence, pointing at symlinks, crossing symlink components, or using unsupported external/remote refs are rejected with stable reason codes. | Local path-safety validation, trusted managed-root facts, and unsupported-capability records. | Unit tests for outside-root, missing ownership, symlink, symlink traversal, and unsupported external/remote refs; integration tests for local filesystem failure cases. | confirmed |
| Retention inspection | Artifacts with keep, temporary, archive, and external retention hints remain inspectable, serializable, and visible in export/import metadata; retention hints do not prove ownership or trigger automatic deletion. | Artifact metadata, bundle/export/import metadata, diagnostics, and preflight. | Unit/contract tests for `RetentionMode`/`RetentionPolicy` normalization and serialization; integration tests for inspection/export/import visibility. | confirmed |
| Run-collection GC dry-run and delete | Multiple runs produce a collection report and optional explicit deletion over selected cleanup candidates without treating the run catalog or collection path as authority and without deleting whole run directories. | Run collection discovery plus per-run authoritative cleanup planning/execution. | Integration tests with multiple temporary runs, stale/unsafe candidates, candidate-level deletion, and no whole-run removal. | confirmed |
| Cleanup and retention preflight warnings | Preflight reports unsafe cleanup candidates, unsupported retention policies, unsupported remote/external deletion, and cleanup paths whose managed-root or ownership evidence cannot be proven. | Read-only diagnostics over cleanup candidates, retention hints, store capabilities, and managed-root facts. | Unit/contract tests for warning ids, severity, plain-data details, and CLI/diagnostic rendering. | confirmed |
| Cleanup audit event | A recorded cleanup report or mutating cleanup result is projected into compact Stage 20 event records after the cleanup fact exists, and configured sinks observe without controlling deletion. | Stage 20 event records, event sink registry, observer failure records, explicit cleanup report records, and cleanup result records. | Unit, contract, and integration tests for event payload traceability, append-before-dispatch ordering, compact payloads, and sink non-blocking behavior. | confirmed |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/import | New cleanup and retention modules remain import-light and public surfaces are intentional. | Package API tests, import-boundary tests, and `py.typed` surface checks for `loom.pipeline.cleanup` and retention helpers. | package | `uv run pytest tests/package`; phase plans should add targeted package/API tests when public imports land. | confirmed |
| Unit | Cleanup records, selector matching/explanations, retention validation, path safety, symlink rejection, delete-intent validation, result records, event projection, sink non-blocking behavior, and preflight warning codes. | Focused unit tests under mirrored source paths; all filesystem cases use temporary directories only. | unit | `make test-unit` plus narrower targets such as `uv run pytest tests/unit/loom/pipeline/cleanup tests/unit/loom/pipeline/stores tests/unit/loom/diagnostics tests/unit/loom/cli` as phases add those paths. | confirmed |
| Contract | Public cleanup records, selector records, retention records, cleanup event payloads, authority cleanup candidate/result compatibility, CLI/API behavior, and plain-data serialization. | Contract tests for schema/version compatibility, round-trips, unsupported external/remote cases, and authority append/list semantics. | contract | `make test-contract` plus cleanup-specific contract paths named in phase plans. | confirmed |
| Integration | Local filesystem cleanup, append-only authority result facts, run-collection GC over temporary run directories, preflight/diagnostics collaboration, and cleanup event append/dispatch ordering. | Integration tests using only temporary directories, fake sinks, and fake or local authority stores; no network or real provider credentials. | integration | `make test-integration` plus cleanup-specific integration paths named in phase plans. | confirmed |
| E2E | CLI `clean` and `gc` dry-run/delete flows, JSON/text output, confirmation/`--yes`, non-zero exits for unsafe deletion attempts, and no whole-run deletion. | CLI/e2e tests without network or external services once the CLI commands are in scope. | e2e | `make test-e2e` or narrower CLI/e2e paths named in phase plans. | confirmed |
| Opt-in | Remote deletion or provider-specific cleanup. | Not expected for Stage 21 by default; tests should prove unsupported behavior with fake refs/capabilities rather than real providers. | opt-in | None for default Stage 21; no network/provider opt-in suite unless a later roadmap stage approves provider deletion. | confirmed |
| Final gate | Repository validation and PR evidence after implementation-plan phases. | Required PR gate plus suite-level evidence. | suite | `make validate-pr`; `make test-summary` | confirmed |

## Phase Sketch

Phase-shaping status: confirmed

Phase split rationale:

- Keep import-light value records, selectors, retention hints, and safety
  decision contracts separate from mutating behavior.
- Land authority persistence and dry-run planning before any deletion path.
- Add explicit deletion and event projection only after result facts exist.
- Add collection GC and preflight after per-run cleanup semantics are stable.
- Add CLI last so command behavior stays a wrapper over tested Python APIs.

### Phase 1 - Cleanup Records, Retention, Selectors, And Safety Contracts

Goal:

- Add the import-light value records and normalization helpers needed for
  cleanup planning without store mutations or filesystem deletion.

Scope:

- `loom.pipeline.cleanup` package skeleton, public record exports, errors, and
  package/import coverage.
- Cleanup report/result, target, managed-root, selector, safety decision, and
  delete-intent value records where they can be defined without persistence.
- Bounded selector normalization and matching over plain-data candidate facts.
- `RetentionMode`/`RetentionPolicy` helpers in `loom.artifacts`, preserving
  existing plain-data metadata compatibility.
- Local path-safety decision helpers that can evaluate paths from trusted
  managed-root inputs without deleting anything.

Out of scope:

- Authority schema or protocol changes.
- Filesystem deletion.
- Cleanup event emission.
- Run-collection GC.
- CLI commands.

Acceptance criteria:

- Public records are strict, typed, deterministic, and plain-data-compatible.
- Bounded selectors cover age/timestamp, metadata/tag, retention mode,
  candidate kind/reason, status/stage, and artifact fields needed by the
  confirmed behavior baseline.
- Path-safety helpers reject outside-root, missing-ownership, symlink target,
  and symlink traversal cases using stable reason codes.
- Retention helpers validate keep, temporary, archive, and external as policy
  hints only.

Test expectations:

- Package: import-light package/API tests for `loom.pipeline.cleanup` and
  retention helpers.
- Unit: record round-trips, selector matching/explanations, duration parsing,
  retention normalization, and path-safety decisions.
- Contract: plain-data schema and compatibility tests for public records.
- Integration: none required except small temporary-directory path-safety tests
  if unit coverage needs real filesystem behavior.
- E2E: none.
- Opt-in: none.

Design impact:

- Establishes the reusable cleanup API vocabulary before store and CLI work.

Future compatibility:

- Leaves target adapters capability/ownership-focused and avoids provider
  deletion policy.

Alternatives rejected:

- A free-form cleanup query language.
- Provider-specific retention classes.
- Safety checks embedded only in CLI commands.

Debt introduced:

- Public record names may need refinement before implementation-plan quality
  gate; revisit during plan review if names overfit implementation details.

Reviewability:

- One PR can review pure records/selectors/safety behavior without destructive
  side effects.

### Phase 2 - Authority-Backed Dry-Run Planning And Inspection

Goal:

- Build side-effect-free cleanup dry-run planning over authoritative run facts,
  explicit recorded cleanup report facts where needed, and cleanup result fact
  contract scaffolding where required for later mutating result persistence.

Scope:

- Extend authority/read-model protocols and concrete authority backends with
  append/list support for explicit recorded cleanup report facts, plus cleanup
  result fact contract scaffolding where required by the selected
  implementation shape. Mutating cleanup result production remains Phase 3.
- Preserve existing `CleanupCandidate` serialization and bundle/import
  visibility.
- Implement per-run `plan_cleanup(...)` dry-run reporting from cleanup
  candidates, materialized refs, artifact facts, retention hints, statuses,
  leases, submitted operations, and trusted managed-root facts.
- Add backend/inspection support for cleanup reports/results and retention
  hints where read-only inspection is in scope.
- Prove unrecorded dry-run previews do not append authority facts or event
  records by default.

Out of scope:

- Filesystem deletion.
- Cleanup event dispatch.
- Collection-level GC.
- CLI commands.

Acceptance criteria:

- Dry-run reports show selected, skipped, and rejected candidates with stable
  reason codes and selector/safety explanations.
- Cleanup report facts and cleanup result facts are append-only relative to
  existing cleanup candidates. Result facts reference candidate ids, target
  refs, revisions, and outcomes.
- Managed roots are resolved only from trusted authority/store/config facts or
  local path helpers, not broad collection input.
- Existing cleanup candidate records remain readable.

Test expectations:

- Package: public imports remain cheap.
- Unit: authority record validation, report construction, candidate/result
  reference validation, and no-write dry-run behavior with fakes.
- Contract: authority protocol serialization and append/list compatibility.
- Integration: local/fake authority dry-run reports with temporary
  directories, candidates, and retention hints.
- E2E: none.
- Opt-in: unsupported remote/external refs can use fake metadata only.

Design impact:

- Establishes authority as the durable cleanup evidence source before mutation.

Future compatibility:

- Whole-run deletion and catalogs can later reconcile by candidate/result ids
  without erasing candidate evidence.

Alternatives rejected:

- Events-only cleanup evidence.
- Mutating or deleting cleanup candidate records when cleanup runs.

Debt introduced:

- Authority schemas grow cleanup fact storage; revisit if result facts require
  paging or compaction.

Reviewability:

- Review can focus on persistence, compatibility, and dry-run semantics without
  filesystem deletion risk.

### Phase 3 - Explicit Local Deletion And Cleanup Event Projection

Goal:

- Implement explicit local filesystem deletion for approved targets and project
  recorded cleanup facts into Stage 20 cleanup audit events.

Scope:

- `execute_cleanup(...)` or equivalent API requiring structured
  `CleanupDeleteIntent`.
- Local filesystem deletion adapter for approved, Loom-owned targets under
  trusted managed roots.
- Cleanup result persistence for deleted, skipped, rejected, and failed
  targets.
- Cleanup event projection for recorded report/result facts using compact
  `PipelineEventRecord` payloads.
- Observe-only sink dispatch behavior and sink-failure non-blocking coverage
  through Stage 20 machinery.

Out of scope:

- Remote/provider deletion.
- Whole-run directory deletion.
- Collection-level GC.
- CLI confirmation behavior.

Acceptance criteria:

- Deletion requires explicit delete intent and never follows symlinks.
- Unsafe or unsupported targets are rejected visibly and not deleted.
- Result facts are appended before cleanup events are projected.
- Event sink failures are visible but do not alter cleanup correctness.
- Unrecorded dry-run previews remain side-effect-free.

Test expectations:

- Package: imports remain cheap with event projection isolated.
- Unit: delete-intent validation, deletion outcomes, event payload projection,
  and sink failure behavior.
- Contract: cleanup event payload serialization and fact-reference
  compatibility.
- Integration: temporary-directory deletion, permission/failure cases where
  practical, result fact append, event append-before-dispatch ordering, fake
  sink failure.
- E2E: none.
- Opt-in: none.

Design impact:

- Introduces the only Stage 21 destructive behavior and binds it to
  append-only evidence.

Future compatibility:

- Local adapter shape can be extended by future store-owned deletion adapters
  without changing selector or result semantics.

Alternatives rejected:

- Bare boolean delete guard as the primary programmatic safety mechanism.
- Per-file event spam as deletion evidence.

Debt introduced:

- Local-only deletion adapter; revisit when provider deletion is planned.

Reviewability:

- One PR can audit all destructive behavior, result evidence, and event
  ordering together.

### Phase 4 - Candidate-Level Run-Collection GC And Preflight Warnings

Goal:

- Add collection-level candidate cleanup and read-only cleanup/retention
  preflight warnings over the stable per-run cleanup APIs.

Scope:

- `plan_collection_gc(...)` and `execute_collection_gc(...)` or equivalent
  aggregate APIs that enumerate runs then call per-run cleanup planning and
  execution.
- Candidate-level GC only; no whole-run directory deletion.
- Run catalog/run collection use only for discovery and presentation; each
  run's authority remains deletion truth.
- Preflight warnings for unsafe cleanup candidates, unsupported retention
  policies, unsupported remote/external deletion, and missing managed-root or
  ownership evidence.
- Diagnostics rendering of cleanup/retention readiness where appropriate.

Out of scope:

- CLI `loom gc` command.
- Whole-run deletion.
- Automatic retention enforcement.
- Remote provider deletion.

Acceptance criteria:

- Collection GC returns aggregate reports/results across runs and preserves
  per-run evidence.
- Collection input paths are discovery hints, not managed-root proof.
- No whole-run directory is removed.
- Preflight is read-only and never deletes, mutates cleanup facts, dispatches
  events, or loads cleanup-specific plugins.

Test expectations:

- Package: imports remain cheap.
- Unit: collection aggregation, catalog discovery boundary, warning ids and
  severity.
- Contract: aggregate report/result serialization and preflight warning
  payloads.
- Integration: multiple temporary run directories, stale/unsafe candidates,
  candidate-level deletion, no whole-run removal, diagnostics/preflight output.
- E2E: none unless implementation includes CLI-facing preflight paths.
- Opt-in: unsupported remote/external refs through fake metadata only.

Design impact:

- Scales cleanup from per-run operations to run collections while preserving
  authority boundaries.

Future compatibility:

- Whole-run deletion can be added later as a separate mode with stronger gates
  and tombstones.

Alternatives rejected:

- Treating run catalogs as cleanup authority.
- Deleting whole run directories in first GC.

Debt introduced:

- Collection processing may start as simple iteration; revisit if large
  collections need paging or streaming.

Reviewability:

- Review can verify collection behavior without mixing in CLI presentation.

### Phase 5 - CLI Commands, Documentation, And Final Validation

Goal:

- Expose cleanup and GC through thin CLI commands and update documentation,
  examples, and final validation evidence.

Scope:

- `loom clean RUN_URI` and `loom gc <collection>` command modules registered
  from `loom.cli.main`.
- CLI parsing for bounded selectors, dry-run/default preview, explicit
  confirmation or `--yes`, and text/JSON formatting.
- CLI errors and non-zero exit behavior for unsafe deletion attempts and
  unsupported requested deletion.
- Feature docs, roadmap implementation notes, and status/backend/preflight docs
  as needed.
- E2E or CLI tests for representative dry-run/delete flows.
- Final `make validate-pr` and `make test-summary` evidence.

Out of scope:

- CLI-owned deletion policy.
- Cleanup-specific event sink plugin loading.
- Provider deletion commands.
- Whole-run deletion flags.

Acceptance criteria:

- CLI commands call public cleanup APIs and do not duplicate deletion policy.
- Dry-run is the default presentation path.
- Mutating CLI cleanup requires confirmation or `--yes`.
- JSON output is plain-data records; text output is concise and explains
  selected, skipped, rejected, deleted, and failed targets.
- Docs accurately state deferrals and safety guarantees.

Test expectations:

- Package: CLI import tests.
- Unit: CLI parser/formatting and error mapping.
- Contract: CLI/API JSON output shape where public.
- Integration: CLI command handlers over temporary runs and fake/local
  authority stores where practical.
- E2E: representative `loom clean` and `loom gc` dry-run/delete flows without
  network or external providers.
- Opt-in: none.

Design impact:

- Makes the cleanup behavior user-visible without moving policy into CLI.

Future compatibility:

- Future UIs or service wrappers can reuse the same cleanup APIs and output
  records.

Alternatives rejected:

- Shell-only cleanup workflows.
- CLI parsing of arbitrary directories or provider payloads as cleanup truth.

Debt introduced:

- CLI flag set intentionally starts bounded; revisit before adding compound
  boolean queries or whole-run deletion flags.

Reviewability:

- Final PR is user-facing and documentation-heavy, with destructive semantics
  already established by earlier phases.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Roadmap extraction, confirmed capability triage, confirmed FR-1 through FR-8, and confirmed behavior baseline. Stage 20 event completion has been reflected in the requirement set. | pass | None. |
| Requirement-to-design traceability | Proposed implementation shape, design-agreement queue, design decisions, and design triage map FR-1 through FR-8 to cleanup APIs, authority facts, retention records, selectors, CLI/preflight wrappers, collection GC, and Stage 20 event projection. | pass | None. |
| Design-safety review completed | Design-safety review passed with DSR-1 through DSR-5 recorded. Planning revisions for append-only cleanup results and trusted managed-root sources were applied. | pass | None. |
| Future-roadmap impact considered | Design agreement and design-safety review record remote deletion, whole-run deletion, organization policy, service cleanup, event sink, and retention touchpoints. | pass | None. |
| Generic interface, adapter, and protocol flexibility considered | Design agreement and design-safety review record cleanup record/API shape, target adapter boundary, authority cleanup fact persistence, retention helpers, CLI/preflight dependency direction, and adapter non-policy ownership. | pass | None. |
| Example-to-validation traceability | Confirmed examples and validation rows map FR-1 through FR-8 to package, unit, contract, integration, e2e, opt-in, and final-gate obligations. | pass | None. |
| Phase-shaping readiness | Confirmed five-phase split maps requirements, design decisions, examples, and validation obligations to reviewable PR-sized phases. | pass | None. |
| Unresolved blocked or needs-discussion functionality or design decisions | None for roadmap framing, intent, capability triage, functionality agreement, behavior baseline, design agreement, or design-safety review. | pass | None. |

Readiness result:

- Status: passed
- Implementation-plan drafting blockers:
  - None.
- Accepted risks:
  - Unrecorded dry-run previews are not persisted or emitted as audit events by
    default so dry-run remains side-effect-free. Revisit if audit-heavy
    deployments require recorded preview reports.
  - Stage 21 first implementation is local-filesystem deletion only. Revisit
    when remote artifact-store deletion or provider retention enforcement is
    explicitly planned.
  - Cleanup result persistence adds authority schema and compatibility work.
    Revisit if result records become too large or too slow for authority-backed
    storage without compaction or paging.
- Assumptions to carry forward:
  - Stage 21 defaults to conservative, explicit, dry-run-first cleanup with
    bounded selectors such as `--older-than 7d`.
  - Cleanup result records remain the correctness source; Stage 20 event records
    are audit projections and event sinks are observe-only.
  - Cleanup policy lives in `loom.pipeline.cleanup`; CLI and preflight do not
    own deletion policy.
  - Validation must stay domain-neutral, local by default, and use temporary
    directories/fake sinks/fake unsupported refs rather than real provider
    credentials.
  - The user instruction to continue drafting the implementation plan is treated
    as final planning confirmation for this pass.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Does the user have clarifying questions about the Stage 21 briefing before capability triage begins? | Roadmap framing | User clarified filtered hard cleanup; no unresolved roadmap-framing clarification remains. | closed |
| What should Stage 21 optimize for relative to the roadmap description? | Roadmap framing, functionality agreement, behavior defaults | Conservative safety, explicit intent, inspectability, and targeted filtered hard cleanup. | closed |
| Which selectors should be first-class for filtered hard cleanup? | Intent discovery, FRQ-4, FR-6 | Bounded selectors first, including `--older-than 7d`, tags/metadata, retention mode, timestamps/age, candidate kind/reason, run/stage status, stage name, and artifact id/type. No general query language in the first implementation. | closed |
| How should cleanup audit events behave after Stage 20 completion? | FRQ-2, design agreement, phase shaping | Cleanup result records are required; cleanup event emission is included as audit projection; event sinks do not control deletion correctness. | closed |
| Should whole-run deletion be included in the first run-collection GC scope, or deferred behind candidate-only GC? | FR-5, GC behavior, phase shaping | Defer whole-run deletion from first GC behavior; first GC deletes selected cleanup candidates inside runs. | closed |
| Are any high-impact design decisions still unresolved before design-safety review? | Design agreement | No. Repo evidence supports the recorded recommendations for cleanup API ownership, authority result facts, side-effect-free dry-runs, path safety, selectors, retention, candidate-level GC, event projection, remote deferral, and CLI/preflight boundaries. | closed |
| Did design-safety review find blockers or decisions needing discussion? | Design-safety review | No blockers. Review upheld DAQ-1 through DAQ-10, added append-only cleanup-result and trusted managed-root-source constraints, and passed the gate. | closed |
| Are examples and validation obligations confirmed before phase shaping? | Examples and validation strategy | Yes. Examples cover all confirmed behavior, including bounded selectors, preflight warnings, append-only results, and cleanup events; validation is layered across package, unit, contract, integration, e2e, opt-in, and final gate checks. | closed |
| Is phase shaping confirmed for implementation-plan drafting? | Phase shaping | Yes. Five phases are confirmed: records/contracts; authority-backed dry-run planning; explicit deletion/events; collection GC/preflight; CLI/docs/final validation. | closed |
| Is the planning artifact ready to hand off into implementation-plan drafting? | Implementation readiness | Yes. All planning gates through phase shaping are confirmed, no unresolved blocker remains, and the user requested continuing to implementation-plan drafting. | closed |

## Handoff Notes

Implementation-plan draft inputs:

- Implementation-plan draft created at
  `docs/roadmap/stage-21/implementation-plan.md`. Design agreement is
  complete, design-safety review has passed, examples and validation strategy
  are confirmed, phase shaping is confirmed, implementation readiness passed,
  and the user requested continuing to implementation-plan drafting.

Design-safety review result:

- Passed. No blockers or decisions needing discussion remain from the
  design-safety pass.

Validation and phase-shaping inputs:

- Examples and validation rows are confirmed. Phase shaping should preserve
  package/import, unit, contract, integration, CLI/e2e, opt-in, and final-gate
  obligations in each phase's scope.
- Confirmed phase split: records/contracts; authority-backed dry-run planning;
  explicit deletion/events; collection GC/preflight; CLI/docs/final validation.

Implementation-readiness result:

- Passed. No planning blockers remain before implementation-plan drafting.

Plan-quality-gate risks:

- Data-loss safety and deletion intent must be precise enough that phase
  implementation cannot invent destructive behavior.
- Retention policy shape must stay generic and not become provider-specific.
- Run-collection GC must not treat derived catalogs as authority.
- Existing cleanup candidate records and bundle/import metadata must remain
  compatible.

Assumptions to carry forward:

- Use `run_uri`, `RunStore`, authority, run collection, run catalog, and
  artifact vocabulary as defined in `docs/GLOSSARY.md`.
- Keep Loom domain-neutral and dependency-light.
- Deletion policy belongs in tested Python APIs; CLI owns presentation and
  confirmation only.

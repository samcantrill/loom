# Roadmap Stage 16 Planning: Artifact Payload Materialization

## Metadata

- Roadmap stage: v16
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap/stage-15/planning.md` exists and records confirmed Stage 15
    planning for the external artifact interface contract.
  - `docs/roadmap/stage-15/implementation-plan.md` exists in the current
    checkout and records a plan-quality-gate-passed Stage 15 implementation
    plan, but Stage 15 source contracts are not present in the current source
    tree yet. Stage 16 planning can use Stage 15 as a design dependency, but
    implementation readiness must recheck landed Stage 15 records, handlers,
    capabilities, and exchange metadata before drafting phases.
- Planning artifact status: draft
- Current discussion stage: roadmap framing
- Stage gates:
  - Roadmap framing: in progress
  - Intent discovery: pending
  - Capability triage and candidate functional requirements: pending
  - Functionality agreement review: pending
  - Functionality and behavior confirmation: pending
  - Context compaction/reset checkpoint: pending
  - Design agreement review: pending
  - Design safety review: pending
  - Examples and validation strategy: pending
  - Phase shaping: pending
  - Implementation readiness: pending
  - Handoff: pending
- Related implementation plan: not created
- Related feature docs:
  - `docs/features/remote-stores.md`
  - `docs/features/artifacts.md`
  - `docs/features/io.md`
  - `docs/features/plugins.md`
  - `docs/features/run-catalog.md`
  - `docs/features/preflight.md`
  - `docs/features/testing.md`
- Blockers:
  - Stage 15 contracts are a prerequisite for implementation-plan drafting.
  - Optional backend adapter selection is unresolved. The roadmap permits at
    most one optional backend family, and only if a concrete downstream need is
    selected. The recommended startup default is fake-backend-first core
    materialization with no real backend family unless the user identifies a
    concrete need.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | V16 adds explicit local, external, and remote payload materialization, publish paths, upload/download paths, checksum verification, staging lifecycle records, bundle export support, import metadata-only preservation, optional backend isolation, fake-backend tests, and opt-in integration tests for any selected backend. | roadmap scope | This is the payload movement stage after the Stage 15 metadata/interface contract. |
| `docs/roadmap.md` | V16 exit criteria require metadata-only preservation by default, explicit materialization only when requested, isolated optional dependencies, and a detailed plan that selects one backend family or explicitly skips backend implementation until needed. | stage acceptance | Backend selection is a first-class planning decision, not an implementation detail. |
| `docs/roadmap.md` | V16 defers broad S3/GCS/Azure/MLflow/DVC parity, remote tracking services, distributed locking, global content-addressed caches, credential lifecycle management, signed manifests, and remote run catalog services. | scope boundaries | Materialization must not become a broad remote storage platform. |
| `docs/roadmap.md` v15 | V15 owns backend-neutral artifact-store APIs, external immutable refs, multi-location semantics, fake handlers, bundle ref semantics, and preflight surface. | prerequisite | Stage 16 should consume landed Stage 15 contracts rather than inventing parallel records. |
| `docs/roadmap.md` v17/v18 | Docker and HPC container executors follow Stage 16. | successor touchpoint | Stage 16 local staging/cache records may later support payload crossing into containers or shared HPC filesystems. |
| `docs/roadmap.md` v19/v20 | Reliability policies and cleanup/retention follow later. | future boundary | Stage 16 may record operation results and staging facts, but retries, retention policy, and garbage collection are later concerns. |
| `docs/roadmap/stage-15/planning.md` | Stage 15 confirmed metadata-first external refs, adjacent artifact summaries, operation-specific capabilities, cheap default preflight, selected remote writes fail closed, explicit immutable lookup, no real backend, and no payload materialization. | design dependency | Stage 16 should preserve the Stage 15 separation between metadata-only refs and explicit payload operations. |
| `docs/roadmap/stage-15/implementation-plan.md` | Stage 15 planned `ArtifactLocationSummary`, `ArtifactStoreRef`, backend descriptors/factories/handlers/registry, operation-specific capabilities, unsupported materialization diagnostics, and Stage 12 exchange rework. | implementation dependency | Stage 16 implementation readiness must recheck these exact landed names and contracts. |
| `docs/features/remote-stores.md` | Remote stores should preserve the artifact-store protocol, avoid hard SDK dependencies, declare capabilities, redact credentials, document atomicity/consistency, use manifest-last commit where needed, record checksums, and keep network-heavy probes optional. | remote materialization design | Strongest source for upload/download, staging, cache, credential, and unsupported-operation boundaries. |
| `docs/features/artifacts.md` | `ArtifactRef` is a lightweight pointer; artifact stores load, register, validate, and persist payloads; run stores index refs and do not load payloads. | artifact ownership | Materialization belongs around artifact-store and run-exchange APIs, not inside `ArtifactRef` loading behavior. |
| `docs/features/io.md` | URI parsing/source access and codec dispatch are separate from pipeline store layout and artifact-store policy. Heavy storage clients belong in optional integrations. | import and dependency boundary | Core materialization should use neutral URI/source helpers without making `loom.io` a remote artifact platform. |
| `docs/features/plugins.md` | Plugin discovery is explicit, opt-in, adapter-shaped, and must not load third-party code at import time. | optional backend boundary | Any selected real backend must live behind optional packaging and explicit loading. |
| `docs/features/preflight.md` | Remote artifact credential probing, large checksum scans, image pulls, and other expensive checks are deferred or opt-in. | diagnostics behavior | Stage 16 can add materialization readiness checks, but default preflight must remain cheap and side-effect-light. |
| `docs/features/run-catalog.md` | Export/import should avoid loading large payloads by default; future remote stores may need staging or metadata-only mode; imported runs are historical-only in v12. | bundle/export/import semantics | Stage 16 should add requested payload movement without making bundle operations implicit downloads. |
| `docs/features/testing.md` | Core tests must avoid real clusters, network services, cloud storage, heavy optional dependencies, and downstream domain fixtures by default. | validation strategy | Fake backend coverage is required for core behavior; real backend tests must be opt-in. |
| `src/loom/pipeline/stores/artifact_store.py` | Current protocols separate local artifact/materialization surfaces from authority lifecycle state. | current source boundary | Existing source has local materialization concepts, but not Stage 15 external backend contracts. |
| `src/loom/pipeline/stores/materialization_read_models.py` | Authoritative read models can include local materialized refs and optional verification warnings without mutating authority. | current source boundary | Useful precedent for derived materialization records and checksum verification semantics. |
| `src/loom/runs/bundles.py` and `src/loom/runs/imports.py` | Bundle export reads completed-run metadata with materialized refs; imports stage payloads before committing target run metadata and can run metadata-only or complete import policies. | current bundle behavior | Stage 16 must extend this carefully for external/remote refs without default downloads or credential requirements. |
| `docs/structure.md` and `docs/GLOSSARY.md` | Keep `loom` domain-neutral; distinguish `ArtifactRef`, `ArtifactAddress`, artifact store, run store, authority, run catalog, checksum, fingerprint, and materialized ref. | vocabulary and architecture | Prevents materialization from becoming domain cache policy or authority truth. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and workflow docs | `.codex/workflows/roadmap-stage-planning.md`, `.codex/templates/roadmap-stage-planning.md`, `docs/roadmap.md` v15-v18 | Workflow requires startup briefing before capability triage. V16 is explicitly a post-contract payload movement stage with a backend-selection decision. | None for startup. |
| Feature docs | `remote-stores.md`, `artifacts.md`, `io.md`, `plugins.md`, `preflight.md`, `run-catalog.md`, `testing.md`, plus `docs/loom.md`, `docs/structure.md`, `docs/GLOSSARY.md` | Feature docs support fake-backend-first behavior, optional dependencies, explicit staging/cache records, checksum verification, metadata-only defaults, and opt-in network/credential checks. | Need later design pass to recheck reliability and cleanup docs for operation-result handoff. |
| Source and tests | `src/loom/pipeline/stores/artifact_store.py`, `src/loom/pipeline/stores/materialization_read_models.py`, `src/loom/runs/models.py`, `src/loom/runs/bundles.py`, `src/loom/runs/imports.py`, targeted `rg` for materialization/publish/upload/download | Current source has local materialization read models and bundle import/export staging, but not Stage 15 external artifact records or backend handlers. | Must recheck source after Stage 15 lands. |
| Prior or adjacent plans | Stage 15 planning and implementation plan; Stage 12 run-bundle excerpts; Stage 17 roadmap | Stage 15 is the contract prerequisite; Stage 12 exchange should preserve external summaries; Stage 17/18 may consume local staging/cache behavior. | Stage 15 is not implemented in the current source tree. |

## Roadmap Extraction

Baseline roadmap outcome:

- Add explicit payload materialization operations for local, external, and
  remote artifact refs after Stage 15 defines stable external artifact records,
  backend handlers, capabilities, and exchange metadata.
- Keep metadata-only workflows safe: external and remote refs can be preserved,
  exported, imported, inspected, and cataloged without credentials or payload
  access unless the caller explicitly requests materialization.
- Add publish/upload/download paths only where backend capabilities support the
  selected operation and fail closed with structured unsupported-operation
  diagnostics otherwise.
- Record local staging lifecycle facts for publishes, remote writes, and
  downloads without treating staging or cache locations as authoritative
  artifact truth.
- Keep optional backend dependencies outside the default install, with fake
  backend coverage for core behavior and opt-in integration tests for any
  selected real backend family.

Prerequisites:

- Landed Stage 15 artifact location/store-ref records, backend
  descriptor/factory/handler/registry contracts, operation capability records,
  redaction helpers, unsupported operation results, preflight checks, and run
  exchange metadata preservation.
- Existing local artifact/materialization surfaces and run-bundle import/export
  behavior.
- Stage 14 explicit plugin discovery and optional backend entry-point group.
- Current preflight result model and cheap/opt-in check conventions.

Primary feature docs:

- `remote-stores.md`
- `artifacts.md`
- `io.md`
- `plugins.md`
- `run-catalog.md`
- `preflight.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Broad parity across S3, GCS, Azure, MLflow, DVC, W&B, HTTP, and other
  providers.
- Remote tracking services, remote run catalog services, distributed locking,
  remote garbage collection, global content-addressed caches, cross-region
  replication, signed manifests, and credential lifecycle management.
- Automatic global cache lookup, partial stage reuse, transparent downloads,
  implicit bundle materialization, and domain-specific cache/reuse policy.
- Retry, timeout, and event-sink policy beyond recording operation results;
  Stage 19 owns reliability policy.
- Retention, deletion, and GC behavior beyond recording cleanup-relevant
  staging/cache facts; Stage 20 owns cleanup and retention.

Future-roadmap touchpoints:

- Stage 17 Docker and Stage 18 HPC container execution may need explicit local
  materialization/staging so payloads can cross container mounts and shared
  filesystem boundaries predictably.
- Stage 19 can wrap materialization operations with retry/timeout/failure-event
  policy using Stage 16 operation result records.
- Stage 20 can use staging/cache records, ownership hints, and capability
  facts to clean derived materialization state without deleting authoritative
  external artifacts.
- Future concrete backend adapter work should reuse the same generic
  handler/capability/materialization operation shape rather than adding
  service-specific APIs to core.

Compatibility obligations:

- Existing local artifact refs, local bundle workflows, metadata-only import,
  catalog listing, and inspection workflows must keep working.
- Default installs must not gain cloud SDKs, tracking SDKs, fsspec, or network
  clients because of Stage 16 core behavior.
- Default commands must not download or upload payloads implicitly.
- Persisted metadata, diagnostics, and PR/debug output must redact credentials
  and avoid serializing backend clients or unsafe exception payloads.
- Checksums must be treated as byte-integrity evidence, while fingerprints
  remain structured identity/reuse evidence.

## Stage Briefing

What this stage is:

- Stage 16 is Loom's explicit artifact payload materialization stage. Stage 15
  is expected to make external and remote artifact facts durable as metadata;
  Stage 16 decides how payload bytes move when a user deliberately asks for
  them to move. The stage covers local copy/link behavior, external publish,
  remote upload/download, checksum verification, staging lifecycle records,
  bundle export/import integration, and optional backend packaging boundaries.

Why this stage exists:

- Earlier stages intentionally keep external refs metadata-first. That lets
  users inspect, catalog, export, and import run evidence without credentials,
  network access, or surprise large payload transfers. The missing piece is an
  explicit operation surface for the cases where payloads really do need to be
  copied, published, uploaded, downloaded, staged, or verified.
- This stage closes that gap without making Loom a general cloud storage
  product. Materialization is an explicit, capability-checked operation on top
  of Stage 15 records and handlers.

Impacted or linked work:

- `loom.artifacts` and Stage 15 artifact records supply the artifact identity,
  location summaries, store refs, published records, and validation policy that
  Stage 16 should consume.
- `loom.pipeline.stores` likely owns the materialization operation protocol,
  backend handler methods, capability admission, staging/cache records, and
  operation result/errors.
- `loom.runs` owns bundle export/import behavior and must keep metadata-only
  workflows as the default while allowing requested payload materialization
  where supported.
- `loom.diagnostics.preflight` likely gains explicit materialization readiness
  checks separate from cheap Stage 15 backend metadata/config checks.
- `loom.plugins` remains explicit discovery/loading coordination. It should not
  auto-load backend SDKs because a materialization API exists.
- `loom.io` can provide URI/source/codec helpers, but it should not own run
  store layout, artifact-store policy, remote credentials, or provider-specific
  transfer semantics.

Likely public surfaces and durable artifacts:

- Public Python APIs for requesting materialization, publish, upload, download,
  and checksum verification over Stage 15 artifact summaries/store refs.
- Structured operation records/results for materialization status, selected
  source and target, backend capability admission, checksum evidence, staging
  paths, derived cache/materialized refs, diagnostics, and redacted backend
  details.
- Optional CLI surface only if the behavior baseline confirms it, likely under
  existing artifact/run command families rather than a broad new provider CLI.
- Bundle/export/import options for explicit payload materialization while
  keeping metadata-only behavior as the default.
- Preflight check IDs for selected materialization operations and optional
  network/credential/checksum probes.
- Optional backend adapter package or extra only if the planning discussion
  selects one concrete backend family.

Structure rationale:

- The stage should start from the Stage 15 contract instead of introducing a
  parallel transfer API. That keeps the durable metadata shape, plugin
  boundary, capability model, redaction, preflight, and run-exchange behavior
  consistent.
- Separating metadata preservation from payload movement keeps the default
  workflow inspectable and cheap, while making expensive or credentialed work
  explicit and testable.
- Treating staging/cache records as derived keeps authority and artifact
  identity stable. A downloaded local file can be useful without becoming the
  canonical external artifact.

Visible assumptions, risks, and constraints:

- Stage 15 is the hard prerequisite. If its landed contracts differ from the
  current plan, Stage 16 must adapt rather than preserve stale names.
- The optional backend decision is unresolved. Selecting a real backend will
  increase packaging, testing, credential, and CI complexity. Skipping a real
  backend keeps the stage generic but means no first-party cloud/tracking
  adapter ships yet.
- Publish semantics need careful wording: publishing an immutable output should
  create durable evidence and fail closed on unsupported capabilities, but it
  should not create automatic global cache lookup or partial stage reuse.
- Bundle materialization must remain opt-in. Import should be able to preserve
  external/remote refs without credentials.
- Credential lifecycle management, distributed locking, retry policy, deletion,
  retention, and cleanup remain later scope.

User clarification questions and resolved answers:

- Pending initial clarification window.

## User Intent

Target audience:

- Draft default: adapter authors and Loom users who need explicit artifact
  payload movement without making every metadata workflow depend on remote
  credentials or optional SDKs.

User-visible outcome:

- Draft default: users can explicitly materialize, publish, upload, download,
  verify, export, or import payloads when backend capabilities allow it, while
  metadata-only workflows continue to work without credentials.

Success criteria:

- Draft default: no implicit payload movement, fake-backend-first core tests,
  stable operation records, Stage 15 compatibility, optional dependencies
  isolated, and at most one concrete backend family selected only if needed.

Non-goals:

- Draft default: no broad provider parity, no remote tracking service, no
  default network probes, no automatic global cache lookup, no distributed
  cache/locking, no credential manager, no GC/deletion policy, and no
  domain-specific artifact semantics.

Constraints:

- Draft default: keep `loom` domain-neutral, import-light, dependency-light,
  explicit, redacted, and fake-testable by default.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- Pending user clarification. Repo evidence supports treating Stage 16 as an
  explicit payload-operation stage layered on Stage 15 contracts with
  metadata-only defaults preserved.

Intent discovery locked decisions:

- Pending.

Capability triage and candidate-functional-requirement readback:

- Pending.

Functionality-agreement readback:

- Pending.

Functionality and behavior confirmation readback:

- Pending.

Design-agreement follow-up:

- Pending.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Repo-backed briefing drafted | Stage 16 consumes Stage 15; fake-backend-first; metadata-only remains default | User clarification window; planning priority; optional backend need | Confirm roadmap framing and user intent |
| Intent discovery |  |  |  |  |
| Capability triage and candidate functional requirements |  |  |  |  |
| Functionality agreement review |  |  |  |  |
| Functionality and behavior confirmation |  |  |  |  |
| Context compaction/reset checkpoint |  |  |  |  |
| Design agreement review |  |  |  |  |
| Design safety review |  |  |  |  |
| Examples and validation strategy |  |  |  |  |
| Phase shaping |  |  |  |  |
| Implementation readiness |  |  |  |  |
| Handoff |  |  |  |  |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Local copy/link materialization | recommended default | Required by roadmap and useful for local bundle/container/HPC workflows. | Needs behavior confirmation for copy vs link defaults. |
| External publish for immutable outputs | recommended default | Required by roadmap and Stage 15 published immutable output records. | Must not imply automatic global cache lookup. |
| Remote upload/download operations | recommended default | Required by roadmap when backend capabilities support them. | Fake backend in core; real backend unresolved. |
| Checksum verification | recommended default | Required by roadmap and remote-store feature spec. | Must distinguish byte checksum from semantic fingerprint. |
| Staging lifecycle records | recommended default | Required by roadmap and future cleanup/reliability stages. | Derived/non-authoritative records by default. |
| Bundle export explicit materialization | recommended default | Required by roadmap; Stage 12/15 exchange should preserve metadata and support requested payload materialization. | Must remain opt-in. |
| Import metadata-only preservation | recommended default | Required by roadmap exit criteria. | Import should not require credentials for metadata-only refs. |
| Optional real backend adapter family | needs discussion | Roadmap permits at most one family only if a concrete downstream need selects it. | Recommended default is skip real backend until a concrete need is identified. |
| Plugin packaging for optional backend | conditional | Required only if a real backend family is selected. | Core packaging should remain dependency-light either way. |
| Network/credential preflight probes | maybe | Useful for selected materialization operations but should remain opt-in. | Default checks should stay cheap. |
| Retry/timeout policy | defer | Stage 19 owns reliability policy. | Stage 16 may record retry-ready operation diagnostics only. |
| Cleanup/retention/GC | defer | Stage 20 owns cleanup and retention. | Stage 16 should record derived staging/cache facts for later cleanup. |
| Distributed locking or global cache | out of scope | Explicitly deferred by roadmap. | Do not include in Stage 16. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Confirm primary planning priority for Stage 16. | none | 1 | Optimize for generic explicit materialization contracts first, with fake-backend behavior and metadata-only defaults preserved. | Sets the center of gravity for API, CLI, examples, and phase boundaries. | User may have a concrete downstream provider need that should shift emphasis. | draft |
| FRQ-2 | Decide whether Stage 16 selects one optional real backend family or explicitly skips real backend implementation. | FRQ-1 | 2 | Skip real backend by default unless the user names a concrete required backend family. | This is an exit-criteria decision and affects dependencies, integration tests, packaging, and CI. | Repo evidence cannot infer downstream provider need. | draft |
| FRQ-3 | Lock default materialization behavior for bundle export/import. | FRQ-1 | 3 | Metadata-only by default; explicit flags/options required for payload movement. | Prevents surprise downloads/uploads and preserves credential-free exchange. | User may want a stricter or more ergonomic default for local-only refs. | draft |
| FRQ-4 | Lock local materialization semantics. | FRQ-1 | 4 | Prefer copy by default with explicit link mode only when safe and local. | Copy is safer across filesystems and bundles; links are efficient but less portable. | Needs maintainer preference because local UX and artifact provenance are affected. | draft |
| FRQ-5 | Lock publish semantics for immutable outputs. | FRQ-1 | 5 | Publish is explicit, immutable, capability-checked, checksum-verified when possible, and does not trigger planner global cache reuse. | Prevents publish from smuggling in Stage 19/20 or cache/reuse behavior. | Repo evidence strongly supports this, but user may want publish prioritized over download. | draft |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Explicit materialization operation surface | none | Provide APIs for requested local/external/remote payload movement over Stage 15 refs and backend capabilities. | Users need payload bytes only when explicitly requested. | Core operation records and fake backend. | Calls return structured success/failure/unsupported results. | Backend handler checks capabilities and records redacted diagnostics. | Materialize, publish, upload, download. | Contract tests with fake backend. | recommended default |
| FR-2 | Metadata-only default preservation | FR-1 | Preserve external/remote refs through inspect/catalog/export/import without credentials or downloads. | Keeps existing workflows cheap, safe, and reviewable. | Run catalog and bundle/import behavior. | Metadata operations do not require backend credentials. | Payload operations are skipped unless explicitly requested. | Safe exchange and review workflows. | No-download assertions and metadata round trips. | recommended default |
| FR-3 | Checksum verification and mismatch diagnostics | FR-1 | Verify byte checksums where provided and supported; report unsupported or mismatch states. | Payload movement needs integrity evidence. | Local and fake remote behavior; selected real backend if any. | Users see clear checksum status. | Operation results separate checksum from fingerprint evidence. | Trustworthy materialization. | Fake mismatch tests. | recommended default |
| FR-4 | Staging and derived materialized-ref records | FR-1 | Record staging/cache/materialized paths, lifecycle status, and cleanup-relevant facts as derived data. | Later reliability and cleanup need facts without making cache authoritative. | Store/run metadata records, not authority lifecycle truth. | Inspection can show derived materialization evidence. | Staging failures are visible and do not corrupt authoritative refs. | Safe publish/download staging. | Failure injection tests. | recommended default |
| FR-5 | Bundle/export/import explicit payload materialization | FR-1, FR-2 | Add options for requested external/remote payload materialization during export/import where supported. | Portable run workflows need a safe path to include payloads when intentionally requested. | Existing `loom.runs` exchange APIs and CLI if confirmed. | Metadata-only remains default; explicit payload requests report unsupported refs. | Bundle code consumes Stage 15 summaries and Stage 16 operation results. | Portable payload transfer. | Bundle export/import fake-backend tests. | recommended default |
| FR-6 | Optional backend adapter selection | FR-1 | Either select one concrete backend family with optional packaging and opt-in tests, or explicitly skip real backend implementation. | Roadmap exit criteria require this decision. | At most one backend family. | If selected, users can opt into that backend; otherwise fake backend proves core behavior. | Optional dependencies remain outside default install. | Concrete integration path, if needed. | Packaging/import tests and opt-in integration marker. | needs discussion |
| FR-7 | Materialization preflight checks | FR-1 | Add explicit checks for selected materialization operations, capabilities, credentials, and network probes where requested. | Users need clear readiness diagnostics before expensive payload operations. | Cheap default checks plus opt-in expensive probes. | Missing capability or credentials appear as structured checks. | Preflight does not upload/download by default. | Operational readiness. | Preflight check-ID tests. | recommended default |

## Behavior Baseline

Included functionality:

- Draft only; pending functionality agreement.

User-visible behavior:

- Draft default: explicit APIs and optional CLI flags/commands for requested
  materialization; metadata-only workflows remain unchanged by default.

Default behavior:

- Draft default: no implicit payload upload, download, publish, or remote
  checksum probe.

Failure behavior and diagnostics:

- Draft default: unsupported capability, missing backend, missing credentials,
  checksum mismatch, unsafe path, partial staging, and backend failure return
  structured diagnostics with redacted details.

Explicit deferrals:

- Draft default: retries/timeouts/events to Stage 19; cleanup/retention/GC to
  Stage 20; broad backend parity and credential lifecycle management out of
  scope.

Out-of-scope behavior:

- Draft default: automatic global cache lookup, distributed cache, provider
  parity, signed manifests, remote catalog services, and domain-specific
  artifact semantics.

Context compaction/reset checkpoint:

- Checkpoint status: pending
- Notes path: `docs/roadmap/stage-16/planning.md`
- Resume instruction: reload this planning artifact and
  `.codex/workflows/roadmap-stage-planning.md`; do not move into design review
  until functionality and behavior are confirmed.
- Functionality and behavior reopened after checkpoint: not applicable

## Proposed Implementation Shape

Likely modules or packages:

- Pending design agreement. Draft expectation:
  - `loom.artifacts` consumes Stage 15 artifact/location records only if new
    operation summaries need import-light public data.
  - `loom.pipeline.stores` owns materialization operation protocols, staging
    records, capability admission, handler methods, and fake backend behavior.
  - `loom.runs` owns bundle/export/import integration.
  - `loom.diagnostics` owns preflight checks.
  - `loom.plugins` owns explicit optional backend loading only when selected.

Likely public classes, functions, or protocols:

- Pending design agreement. Candidate names depend on landed Stage 15 names.

Likely internal helpers:

- Pending design agreement.

Data flow:

- Draft expectation: Stage 15 artifact summary/store ref plus materialization
  request -> backend capability admission -> local staging or transfer handler
  -> checksum verification -> derived materialized/published result record ->
  catalog/bundle/preflight/inspection summaries.

Dependency direction:

- Draft expectation: artifact records remain import-light; stores consume
  records and neutral URI helpers; runs/diagnostics consume public store
  contracts; plugins do not own store semantics.

Extension points and flexibility boundaries:

- Pending design agreement.

Generic interface, adapter, or protocol shape:

- Pending design agreement.

Future-roadmap impact:

- Pending design agreement.

Compatibility constraints:

- Pending design agreement.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Materialization protocol ownership and public API placement. | confirmed FR-1 | 1 | draft | Store-owned protocol with import-light public operation/result records. | Crosses artifacts, stores, runs, diagnostics, and optional backends. | Deferred until functionality is confirmed and Stage 15 contracts are rechecked. | draft |
| DAQ-2 | Optional real backend family shape, if any. | FRQ-2 | 2 | needs discussion candidate | Skip real backend unless a concrete need selects one; if selected, isolate behind optional extra/plugin. | Controls dependency and CI complexity. | Repo cannot infer downstream need. | draft |
| DAQ-3 | Local copy/link policy and provenance semantics. | FRQ-4 | 3 | needs discussion candidate | Copy by default; link only explicit and safe. | Affects portability, performance, checksums, and bundle/container workflows. | Maintainer preference affects UX. | draft |
| DAQ-4 | Staging/cache authority boundary. | FR-4 | 4 | recorded recommendation candidate | Derived records only; never authoritative artifact truth. | Prevents cache/staging paths from corrupting run state semantics. | Repo evidence is strong; design-safety review should challenge. | draft |
| DAQ-5 | Bundle materialization schema compatibility. | FR-5 | 5 | recorded recommendation candidate | Extend Stage 15 run-exchange summaries with explicit operation results rather than provider-specific schema. | Durable bundle artifacts must remain portable. | Depends on landed Stage 15 exchange rework. | draft |
| DAQ-6 | Preflight probe policy. | FR-7 | 6 | recorded recommendation candidate | Cheap by default; network, credentials, payload reads, and checksum scans opt-in. | Avoids surprising side effects and environment-specific failures. | Repo evidence is strong. | draft |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Materialization protocol ownership and public API placement | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | pending | pending | FR-1 | draft after functionality confirmation | pending |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  | pending |

Gate result:

- Status: pending
- Reviewer:
- Blockers:
- Recorded recommendations:
- Future-roadmap impact summary:
- Generic interface, adapter, and protocol assessment:
- Planning revisions required:
- Accepted risks:
- Revisit triggers:

## Practical Design Notes

Public Python API surface:

- Pending design agreement.

CLI surface:

- Pending functionality and behavior confirmation. Draft expectation is to
  prefer narrow options under existing artifact/run command families over a
  broad provider-management CLI.

Persisted records and file layout:

- Pending design agreement. Draft expectation is strict plain operation
  records with redacted backend details and derived staging/cache/materialized
  refs.

Import boundaries and dependencies:

- Pending design agreement. Draft expectation is no optional backend SDK in
  default imports and no plugin discovery on `import loom`.

Failure modes and diagnostics:

- Pending behavior confirmation.

Extension points and flexibility boundaries:

- Pending design agreement.

Generic interfaces, adapters, and protocols:

- Pending design agreement.

Future-roadmap compatibility:

- Pending design agreement.

Maintainability assessment:

- Pending design agreement.

Extensibility assessment:

- Pending design agreement.

Flexibility and expansion assessment:

- Pending design agreement.

Scalability and future compatibility:

- Pending design agreement.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Stage 16 planning starts before Stage 15 source contracts are landed | Planning can identify requirements, but implementation readiness must depend on the landed Stage 15 surface | Stage 15 contracts land or diverge from the current Stage 15 implementation plan |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Fake remote download | Explicit download materializes a payload through fake backend with checksum verification | Core materialization contract | Unit/contract tests | draft |
| Fake publish immutable output | Publish records immutable output evidence and fails closed on unsupported backend capability | Stage 15 published artifact records | Unit/contract tests | draft |
| Metadata-only bundle export with remote ref | Export preserves remote ref and unsupported-materialization diagnostics without download | Run bundle exchange | Contract/integration tests | draft |
| Explicit bundle export with payload materialization | Export includes requested payloads when backend supports download | Run bundle exchange | Integration tests with fake backend | draft |
| Optional backend adapter, if selected | Real backend package is optional and opt-in | Plugins/packaging | Package/import tests plus opt-in integration tests | pending backend decision |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/import boundaries | Default import does not load optional backend SDKs or plugin targets | Package tests | Package | `tests/package` | draft |
| Operation records | Materialization/publish/upload/download records serialize strictly with redaction | Unit/contract | Unit, contract | `tests/unit/loom`, `tests/contracts` | draft |
| Fake backend behavior | Supported, unsupported, failed, checksum mismatch, and missing credential-like states | Unit/contract | Unit, contract | fake backend tests | draft |
| Bundle/export/import | Metadata-only default and explicit payload materialization | Integration/contract | Integration, contract | `tests/unit/loom/runs`, `tests/integration` | draft |
| Preflight | Cheap defaults and opt-in expensive materialization probes | Unit/integration | Unit, integration | `tests/unit/loom/diagnostics` | draft |
| Optional backend, if selected | Optional dependency isolation and opt-in integration behavior | Package/opt-in | Package, opt-in integration | backend-specific marker | pending backend decision |
| Full PR gate | Repository validation | PR gate | Local check | `make validate-pr` | pending implementation planning |
| Suite evidence | PR body evidence | Summary | Local check | `make test-summary` | pending PR preparation |

## Phase Sketch

### Phase 1 - Materialization Operation Records And Local Semantics

Goal:

- Define Stage 16 operation records/results and local copy/link materialization
  semantics over landed Stage 15 artifact summaries.

Scope:

- Public strict plain-data records, redaction, checksum evidence, local copy
  behavior, explicit link mode if confirmed, and fake/local tests.

Out of scope:

- Real remote backend, bundle integration, preflight integration, retries, and
  cleanup.

Acceptance criteria:

- Local materialization succeeds or fails with structured diagnostics and does
  not mutate authoritative lifecycle truth incorrectly.

Test expectations:

- Package: import-light public records.
- Unit: local operation records and checksum behavior.
- Contract: materialization result schema.
- Integration: local temp-directory materialization.
- E2E: not required unless existing CLI/API path is confirmed.
- Opt-in: none.

Design impact:

- Creates durable operation records consumed by later phases.

Future compatibility:

- Records must be generic enough for real backend adapters and Stage 19/20
  policies.

Alternatives rejected:

- Pending.

Debt introduced:

- Pending.

Reviewability:

- Keep local behavior and records together before adding remote/bundle surface.

### Phase 2 - Backend Handler Materialization And Fake Remote Operations

Goal:

- Add backend handler methods/capability admission for publish, upload,
  download, and verify behavior using fake remote backends.

Scope:

- Store-owned protocol additions, fake backend implementation, unsupported
  capability handling, staging lifecycle records, redacted diagnostics.

Out of scope:

- Real backend SDKs and bundle export/import integration.

Acceptance criteria:

- Fake backends prove successful, unsupported, failed, and checksum-mismatch
  operation paths.

Test expectations:

- Package: no optional imports.
- Unit: backend handler and capability admission.
- Contract: fake backend materialization contract.
- Integration: staging failure behavior where practical.
- E2E: not required.
- Opt-in: none unless backend selected later.

Design impact:

- Extends Stage 15 backend contracts from metadata/check/lookup into payload
  operations.

Future compatibility:

- Must not overfit to one provider shape.

Alternatives rejected:

- Pending.

Debt introduced:

- Pending.

Reviewability:

- Keep fake remote behavior isolated from bundle and CLI changes.

### Phase 3 - Bundle, Import, Catalog, And Preflight Integration

Goal:

- Wire explicit materialization into bundle/export/import/catalog and preflight
  while preserving metadata-only defaults.

Scope:

- `loom.runs` options/results, bundle inspect/import/export diagnostics,
  catalog summaries where needed, and materialization preflight check IDs.

Out of scope:

- Real backend SDKs, retries, cleanup, and credential lifecycle management.

Acceptance criteria:

- Metadata-only export/import never downloads by default; explicit
  materialization reports supported and unsupported refs clearly.

Test expectations:

- Package: no import side effects.
- Unit: run exchange and diagnostics.
- Contract: bundle/export/import compatibility.
- Integration: fake-backend explicit materialization workflow.
- E2E: CLI only if confirmed.
- Opt-in: none unless backend selected later.

Design impact:

- Changes user-visible exchange and diagnostics behavior.

Future compatibility:

- Stage 17/18 can consume local materialization facts; Stage 19/20 can consume
  operation/staging records.

Alternatives rejected:

- Pending.

Debt introduced:

- Pending.

Reviewability:

- Keep metadata-only compatibility tests central.

### Phase 4 - Optional Backend Adapter Or No-Backend Finalization

Goal:

- If selected, add one optional backend family with isolated packaging and
  opt-in tests. If no backend is selected, finalize docs/examples proving the
  fake-backend-first contract and explicitly record the no-backend decision.

Scope:

- Optional adapter package/extra and opt-in integration tests, or no-backend
  docs and validation hardening.

Out of scope:

- Additional backend families or broad provider parity.

Acceptance criteria:

- Default install remains dependency-light. The implementation plan either
  records the selected backend and opt-in validation or explicitly skips real
  backend implementation until a concrete need exists.

Test expectations:

- Package: optional dependency isolation.
- Unit: adapter registration if selected.
- Contract: backend conforms to materialization contract if selected.
- Integration: opt-in only for real backend.
- E2E: not default.
- Opt-in: selected backend only, if any.

Design impact:

- Satisfies the roadmap backend-selection exit criterion.

Future compatibility:

- First real backend should pressure-test genericity without becoming a
  template for all providers.

Alternatives rejected:

- Pending.

Debt introduced:

- Pending.

Reviewability:

- Keep provider-specific behavior isolated from core fake backend contract.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Initial extraction maps V16 roadmap bullets to draft FR-1 through FR-7 | block | Confirm roadmap framing, intent, capability triage, and functionality agreement |
| Requirement-to-design traceability | Draft design queue exists but depends on confirmed functionality and landed Stage 15 names | block | Complete behavior confirmation and design agreement |
| Design-safety review completed | Not run | block | Run design-safety review after design agreement |
| Future-roadmap impact considered | Initial touchpoints recorded for v17-v20 | block | Revisit during design agreement and design-safety review |
| Generic interface, adapter, and protocol flexibility considered | Initial notes recommend Stage 15-based generic handler/operation shape | block | Confirm after Stage 15 source recheck |
| Example-to-validation traceability | Draft examples and validation matrix recorded | block | Confirm examples after behavior/design decisions |
| Phase-shaping readiness | Draft four-phase sketch exists | block | Refine after design-safety review |
| Unresolved blocked or needs-discussion functionality or design decisions | Optional backend family, local copy/link defaults, and publish/materialization UX remain unresolved | block | Resolve functionality queue with user |

Readiness result:

- Status: not ready for implementation-plan drafting
- Implementation-plan drafting blockers:
  - User has not confirmed roadmap framing, intent, functionality, behavior, or
    design decisions.
  - Design-safety review has not run.
  - Stage 15 source contracts have not been rechecked as landed implementation.
  - Optional backend family selection is unresolved.
- Accepted risks:
  - Initial planning uses the Stage 15 implementation plan as a dependency even
    though source contracts are not present yet.
- Assumptions to carry forward:
  - Metadata-only defaults remain mandatory unless explicitly reopened.
  - Fake-backend-first core coverage is the default validation strategy.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions about the Stage 16 briefing before capability triage starts? | Roadmap framing | Answer and record them before advancing | open |
| What should Stage 16 optimize for: generic materialization contracts, a concrete backend need, bundle portability, local container/HPC staging, or another priority? | User intent and phase shape | Generic explicit materialization contracts first | open |
| Should Stage 16 select one optional real backend family, or explicitly skip real backend implementation until a concrete need appears? | Scope, dependencies, testing, packaging | Skip real backend by default | open |
| Should local materialization default to copy-only, or allow an explicit link mode in the first implementation plan? | Local behavior and provenance | Copy by default; explicit safe link mode maybe | open |
| Should user-facing CLI work be included in Stage 16, or should this stage expose Python/API behavior plus preflight/bundle options first? | Public surface and phase shape | Include only narrow CLI/options if required by behavior confirmation | open |

## Handoff Notes

Implementation-plan draft inputs:

- Not ready. The planning artifact is in roadmap framing.

Design-safety review result:

- Pending.

Validation and phase-shaping inputs:

- Initial draft only; pending confirmed functionality, design agreement, and
  backend-selection decision.

Plan-quality-gate risks:

- Stage 15 dependency may drift.
- Optional backend selection could expand packaging and validation scope.
- Bundle/import/export materialization could accidentally become implicit
  payload movement if defaults are not locked.
- Staging/cache records could be mistaken for authoritative artifact truth if
  not modeled carefully.

Assumptions to carry forward:

- Keep Loom domain-neutral.
- Preserve metadata-only defaults.
- Keep optional dependencies isolated.
- Use fake backend coverage by default.

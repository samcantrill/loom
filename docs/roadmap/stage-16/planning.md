# Roadmap Stage 16 Planning: Artifact Payload Materialization

## Metadata

- Roadmap stage: v16
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  - `docs/roadmap/stage-15/planning.md` exists and records confirmed Stage 15
    planning for the external artifact interface contract.
  - `docs/roadmap/stage-15/implementation-plan.md` exists in the current
    checkout, records Stage 15 complete with all phases merged, and has no
    remaining implementation blocker.
  - Stage 15 landed-contract recheck completed on 2026-05-15. Current source
    includes artifact value records, artifact-store backend
    descriptor/factory/handler/registry contracts, operation capability and
    unsupported-operation records, immutable lookup helpers, artifact backend
    preflight targets, and run bundle export/import/exchange metadata
    preservation. The focused Stage 15 suite passed with 59 tests.
- Planning artifact status: ready for implementation-plan drafting
- Current discussion stage: implementation-plan drafting
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed
  - Design agreement review: confirmed
  - Design safety review: passed
  - Examples and validation strategy: confirmed
  - Phase shaping: confirmed
  - Implementation readiness: confirmed after Stage 15 landed-contract recheck
  - Handoff: ready for implementation-plan drafting
- Related implementation plan: not created
- Related feature docs:
  - `docs/features/remote-stores.md`
  - `docs/features/artifacts.md`
  - `docs/features/io.md`
  - `docs/features/plugins.md`
  - `docs/features/run-catalog.md`
  - `docs/features/preflight.md`
  - `docs/features/testing.md`
- Blockers: none
- Resolved planning constraint: optional backend adapter selection is resolved
  for planning. Skip a real backend family in Stage 16 unless the user later
  supplies a concrete downstream need before phase implementation begins.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | V16 adds explicit local, external, and remote payload materialization, publish paths, upload/download paths, checksum verification, staging lifecycle records, bundle export support, import metadata-only preservation, optional backend isolation, fake-backend tests, and opt-in integration tests for any selected backend. | roadmap scope | This is the payload movement stage after the Stage 15 metadata/interface contract. |
| `docs/roadmap.md` | V16 exit criteria require metadata-only preservation by default, explicit materialization only when requested, isolated optional dependencies, and a detailed plan that selects one backend family or explicitly skips backend implementation until needed. | stage acceptance | Backend selection is a first-class planning decision, not an implementation detail. |
| `docs/roadmap.md` | V16 defers broad S3/GCS/Azure/MLflow/DVC parity, remote tracking services, distributed locking, global content-addressed caches, credential lifecycle management, signed manifests, and remote run catalog services. | scope boundaries | Materialization must not become a broad remote storage platform. |
| `docs/roadmap.md` v15 | V15 owns backend-neutral artifact-store APIs, external immutable refs, multi-location semantics, fake handlers, bundle ref semantics, and preflight surface. | prerequisite | Stage 16 should consume landed Stage 15 contracts rather than inventing parallel records. |
| `docs/roadmap.md` v10 | V10 owns authority service lifecycle, explicit offline-first execution, offline evidence creation, and strict offline import into authority truth. | authority/import boundary | Stage 16 does not replace v10 offline import. It can make payload evidence easier to materialize when external/remote refs are involved. |
| `docs/roadmap.md` v12 | V12 owns portable run exchange, local bundles, metadata-only export by default, explicit payload selection for local bundles, inspect without extraction, import into local collections or authority-backed targets, and transfer evidence. | bundle/export/import boundary | Stage 16 extends the bundle path for external/remote payloads rather than redefining the portable-run exchange model. |
| `docs/roadmap.md` v17/v18 | Docker and HPC container executors follow Stage 16. | successor touchpoint | Stage 16 local staging/cache records may later support payload crossing into containers or shared HPC filesystems. |
| `docs/roadmap.md` v19/v20 | Reliability policies and cleanup/retention follow later. | future boundary | Stage 16 may record operation results and staging facts, but retries, retention policy, and garbage collection are later concerns. |
| `docs/roadmap/stage-15/planning.md` | Stage 15 confirmed metadata-first external refs, adjacent artifact summaries, operation-specific capabilities, cheap default preflight, selected remote writes fail closed, explicit immutable lookup, no real backend, and no payload materialization. | design dependency | Stage 16 should preserve the Stage 15 separation between metadata-only refs and explicit payload operations. |
| `docs/roadmap/stage-15/implementation-plan.md` | Stage 15 records complete implementation: `ArtifactLocationSummary`, `ArtifactStoreRef`, backend descriptors/factories/handlers/registry, operation-specific capabilities, unsupported materialization diagnostics, immutable lookup helpers, preflight checks, and Stage 12 exchange rework. | implementation dependency | Stage 16 can consume the landed contracts directly, with payload movement layered on top instead of inventing parallel records. |
| `docs/features/remote-stores.md` | Remote stores should preserve the artifact-store protocol, avoid hard SDK dependencies, declare capabilities, redact credentials, document atomicity/consistency, use manifest-last commit where needed, record checksums, and keep network-heavy probes optional. | remote materialization design | Strongest source for upload/download, staging, cache, credential, and unsupported-operation boundaries. |
| `docs/features/artifacts.md` | `ArtifactRef` is a lightweight pointer; artifact stores load, register, validate, and persist payloads; run stores index refs and do not load payloads. | artifact ownership | Materialization belongs around artifact-store and run-exchange APIs, not inside `ArtifactRef` loading behavior. |
| `docs/features/io.md` | URI parsing/source access and codec dispatch are separate from pipeline store layout and artifact-store policy. Heavy storage clients belong in optional integrations. | import and dependency boundary | Core materialization should use neutral URI/source helpers without making `loom.io` a remote artifact platform. |
| `docs/features/plugins.md` | Plugin discovery is explicit, opt-in, adapter-shaped, and must not load third-party code at import time. | optional backend boundary | Any selected real backend must live behind optional packaging and explicit loading. |
| `docs/features/preflight.md` | Remote artifact credential probing, large checksum scans, image pulls, and other expensive checks are deferred or opt-in. | diagnostics behavior | Stage 16 can add materialization readiness checks, but default preflight must remain cheap and side-effect-light. |
| `docs/features/run-catalog.md` | Export/import should avoid loading large payloads by default; future remote stores may need staging or metadata-only mode; imported runs are historical-only in v12. | bundle/export/import semantics | Stage 16 should add requested payload movement without making bundle operations implicit downloads. |
| `docs/features/testing.md` | Core tests must avoid real clusters, network services, cloud storage, heavy optional dependencies, and downstream domain fixtures by default. | validation strategy | Fake backend coverage is required for core behavior; real backend tests must be opt-in. |
| `src/loom/artifacts.py` | Current source exports landed Stage 15 artifact value records including `ArtifactStoreRef`, `ArtifactLocationSummary`, `ExternalArtifactDeclaration`, `PublishedArtifactRecord`, `ImmutableArtifactLookupRequest`, and `ImmutableArtifactLookupResult`. | current source boundary | These remain metadata value objects; Stage 16 should not put payload transfer behavior in `loom.artifacts`. |
| `src/loom/pipeline/stores/artifact_backends.py` and `src/loom/pipeline/stores/immutable_artifacts.py` | Current source exports backend descriptors/factories/handlers/registry, operation capability records, unsupported-operation results, immutable declaration validation, and explicit immutable lookup helpers. | current source boundary | Stage 16 materialization/publish/download/upload behavior should extend these store-owned contracts without changing Stage 15 metadata-only semantics. |
| `src/loom/diagnostics/models.py` and `src/loom/diagnostics/preflight.py` | Current source exposes `ArtifactBackendPreflightTarget`, artifact backend registry/handler/capability check IDs, and cheap default preflight behavior. | current source boundary | Stage 16 preflight additions should remain explicit and opt-in for expensive materialization probes. |
| `src/loom/pipeline/stores/materialization_read_models.py` | Authoritative read models can include local materialized refs and optional verification warnings without mutating authority. | current source boundary | Useful precedent for derived materialization records and checksum verification semantics. |
| `src/loom/runs/bundles.py` and `src/loom/runs/imports.py` | Bundle export reads completed-run metadata with materialized refs; imports stage payloads before committing target run metadata and can run metadata-only or complete import policies. | current bundle behavior | Stage 16 must extend this carefully for external/remote refs without default downloads or credential requirements. |
| `docs/structure.md` and `docs/GLOSSARY.md` | Keep `loom` domain-neutral; distinguish `ArtifactRef`, `ArtifactAddress`, artifact store, run store, authority, run catalog, checksum, fingerprint, and materialized ref. | vocabulary and architecture | Prevents materialization from becoming domain cache policy or authority truth. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and workflow docs | `.codex/workflows/roadmap-stage-planning.md`, `.codex/templates/roadmap-stage-planning.md`, `docs/roadmap.md` v15-v18 | Workflow requires startup briefing before capability triage. V16 is explicitly a post-contract payload movement stage with a backend-selection decision. | None for startup. |
| Feature docs | `remote-stores.md`, `artifacts.md`, `io.md`, `plugins.md`, `preflight.md`, `run-catalog.md`, `testing.md`, plus `docs/loom.md`, `docs/structure.md`, `docs/GLOSSARY.md` | Feature docs support fake-backend-first behavior, optional dependencies, explicit staging/cache records, checksum verification, metadata-only defaults, and opt-in network/credential checks. | Need later design pass to recheck reliability and cleanup docs for operation-result handoff. |
| Source and tests | `src/loom/artifacts.py`, `src/loom/pipeline/stores/artifact_backends.py`, `src/loom/pipeline/stores/immutable_artifacts.py`, `src/loom/diagnostics/models.py`, `src/loom/diagnostics/preflight.py`, `src/loom/runs/models.py`, `src/loom/runs/bundles.py`, `src/loom/runs/imports.py`, targeted Stage 15 tests | Stage 15 backend handler, capability, preflight, immutable lookup, and exchange contracts are landed. Focused contract/unit checks passed: 59 tests. | No Stage 15 landed-contract gap remains for implementation-plan drafting. |
| Prior or adjacent plans | Stage 15 planning and implementation plan; Stage 12 run-bundle excerpts; Stage 17 roadmap | Stage 15 is complete; Stage 12 exchange preserves metadata-only bundle semantics; Stage 17/18 may consume local staging/cache behavior. | None for implementation-plan drafting. |

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
  them to move. The stage covers local copy behavior, external publish,
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
- It is relevant to offline import and controller migration workflows, but it
  does not own lifecycle import itself. V10 owns importing offline execution
  evidence into authority truth. V12 owns portable run bundles and import/export
  result semantics. Stage 16 supplies the payload-movement layer those workflows
  need when a run references payloads outside the local bundle or local run
  directory.

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
- The optional backend decision is resolved for this planning pass: skip a
  real backend unless a concrete downstream need appears before
  implementation-plan drafting. This keeps Stage 16 generic but means no
  first-party cloud/tracking adapter ships yet.
- Publish semantics are locked narrowly: publishing an immutable output should
  create durable evidence and fail closed on unsupported capabilities, but it
  should not create automatic global cache lookup, partial-stage reuse, remote
  catalog behavior, or credential lifecycle management.
- Bundle materialization must remain opt-in. Import should be able to preserve
  external/remote refs without credentials.
- Credential lifecycle management, distributed locking, retry policy, deletion,
  retention, and cleanup remain later scope.

User clarification questions and resolved answers:

- The user confirmed the stage briefing and recommended defaults on
  2026-05-15. No clarifying questions were raised before moving to intent
  discovery.
- The user asked how Stage 16 relates to offline run imports into the
  controller and migrating bundles between controllers. Planning answer: Stage
  16 is relevant because it lets export/import workflows explicitly materialize
  external or remote payloads when requested, but v10 remains the owner of
  offline evidence import into authority and v12 remains the owner of portable
  bundle exchange/import semantics. Stage 16 should not implement live
  controller-to-controller migration, authority merge/fork policy, or migrated
  resume.
- The user raised concern that artifact payload materialization, run exchange,
  transfer evidence, diagnostics, offline import, and state-source/read-model
  modules appear to duplicate functionality. Planning answer: some separation
  is intentional because authority lifecycle truth, portable exchange,
  diagnostics, and payload movement have different ownership and failure
  semantics. Stage 16 should still pressure-test whether shared base protocols
  or value objects can reduce repeated adapter identity, operation status,
  diagnostic, and unsupported-operation shapes without collapsing those
  ownership boundaries.
- The user asked whether Stage 16 should consider a structure-refinement
  refactor for stronger guarantees and easier extension. Planning answer:
  yes, a bounded refactor is recommended if it extracts small shared operation
  contracts and adapters before adding new materialization behavior. The
  refactor should not merge authority import, portable-run exchange, preflight,
  and payload movement into one subsystem.

## User Intent

Target audience:

- Adapter authors and Loom users who need explicit artifact payload movement
  without making every metadata workflow depend on remote credentials or
  optional SDKs.

User-visible outcome:

- Users can explicitly materialize, publish, upload, download, verify, export,
  or import payloads when backend capabilities allow it, while metadata-only
  workflows continue to work without credentials.
- The primary user-visible example should be bundle export/import with
  requested payload materialization for external or remote refs.

Success criteria:

- No implicit payload movement, fake-backend-first core tests, stable
  operation records, Stage 15 compatibility, optional dependencies isolated,
  no real backend family in the default Stage 16 plan, and clear
  bundle/export/import behavior.

Non-goals:

- No broad provider parity, no remote tracking service, no default network
  probes, no automatic global cache lookup, no distributed cache/locking, no
  credential manager, no GC/deletion policy, and no domain-specific artifact
  semantics.

Constraints:

- Keep `loom` domain-neutral, import-light, dependency-light, explicit,
  redacted, and fake-testable by default.
- Include CLI only for narrow, frequent, expected user workflows. Otherwise
  expose public API surfaces and explicit NotImplemented/unsupported handles so
  future CLI or backend work has stable integration points without pretending
  unsupported payload movement works.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- Stage 16 is confirmed as an explicit payload-operation stage layered on Stage
  15 contracts. The startup baseline preserves metadata-only defaults, keeps
  optional dependencies isolated, uses fake-backend-first validation, skips a
  real backend family unless a concrete need appears, and uses copy-only local
  materialization for Stage 16 while keeping policy handles open for future
  link/cache/staging strategies.

Intent discovery locked decisions:

- Confirmed on 2026-05-15:
  - Skip a real optional backend family for Stage 16 unless a concrete need is
    supplied before phase implementation begins.
  - Use bundle export/import with requested payload materialization as the
    primary example and validation storyline.
  - Include CLI only for narrow, frequent, expected user workflows; otherwise
    focus on API-level handles and structured NotImplemented/unsupported
    results.
  - Implement local materialization as copy-only in Stage 16. Do not implement
    hardlink, symlink, reflink, move, or cache-promote policies yet, but shape
    request/result interfaces so future policies can be added explicitly.

Capability triage and candidate-functional-requirement readback:

- Confirmed triage includes the bounded shared operation/evidence refinement,
  copy-only local materialization with future policy handles, bundle/export/import
  as the primary workflow, metadata-only defaults, explicit immutable publish
  semantics, cheap-by-default materialization preflight with opt-in expensive
  probes, no real backend family by default, and narrow CLI only when the
  workflow is frequent and expected.

Functionality-agreement readback:

- Confirmed. FRQ-1 through FRQ-7 are locked with no remaining unresolved
  functionality-agreement decisions.

Functionality and behavior confirmation readback:

- Confirmed on 2026-05-15. The user agreed to the complete behavior baseline:
  bundle/export/import as the primary workflow, metadata-only defaults,
  fake-backend-first core behavior, no real backend family, copy-only local
  materialization with future policy handles, explicit immutable publish,
  cheap-by-default preflight with opt-in expensive probes, and narrow CLI only
  for frequent expected workflows.

Design-agreement follow-up:

- Completed on 2026-05-15. The user confirmed `loom.operations` as the
  import-light public home for shared operation/evidence primitives. The
  remaining design decisions are recorded recommendations or auto-approved
  candidates for design-safety review, with no unresolved design questions.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Stage 16 consumes Stage 15 contracts; no implicit payload movement; fake-backend-first default; optional backend skipped unless a concrete need appears | Metadata-only remains default; optional dependencies stay isolated; local materialization copies payloads | None for roadmap framing | Intent discovery |
| Intent discovery | Skip real backend by default; bundle export/import is the primary example; CLI only for frequent expected workflows, otherwise API and NotImplemented/unsupported handles; local materialization is copy-only with future policy handles | Optimize for bundle portability over concrete backend coverage | None for intent discovery | Capability triage |
| Capability triage and candidate functional requirements | Shared operation/evidence refinement, copy-only local materialization, fake-backend-first remote operations, checksum evidence, derived staging records, explicit bundle materialization, metadata-only import preservation, explicit immutable publish semantics, cheap-by-default preflight, no real backend family by default | Metadata-only by default; fake backend in core; copy-only local materialization | None | Functionality agreement |
| Functionality agreement review | FRQ-1 through FRQ-7 confirmed | Bundle export/import primary; no real backend; copy-only local materialization; explicit immutable publish; cheap-by-default preflight; narrow CLI policy | None | Behavior baseline confirmation |
| Functionality and behavior confirmation | Behavior baseline confirmed by user on 2026-05-15 | Metadata-only workflows remain unchanged unless materialization is requested | None | Context checkpoint before design agreement |
| Context compaction/reset checkpoint | Checkpoint recorded in this planning artifact | Resume from `docs/roadmap/stage-16/planning.md` plus roadmap-stage workflow and design-agreement prompt | None | Design agreement review |
| Design agreement review | DAQ-1 through DAQ-9 resolved; `loom.operations` confirmed as shared primitive placement | Store-owned materialization protocol; derived staging/cache records; bundle/preflight consume generic operation evidence | None | Design safety review |
| Design safety review | DAQ-1 through DAQ-9 pressure-tested; DAQ-5 and DAQ-7 upheld as auto-approved; no design-safety blocker remains | Stage 15 landed-contract recheck was a downstream readiness gate and is now complete | None for design safety | Examples and validation strategy |
| Examples and validation strategy | Examples and validation matrix updated after design-safety review | Fake-backend-first, no-network default, package/import-boundary, metadata-only bundle, copy-only local, and structured unsupported-result validation | None | Phase shaping |
| Phase shaping | Five-phase sketch confirmed with shared operation/evidence contracts first and bundle/preflight integration after materialization records and fake backend behavior | Stage 15 landed-contract recheck complete; phase boundaries remain valid | None | Implementation readiness |
| Implementation readiness | Ready for implementation-plan drafting after Stage 15 backend/capability/preflight/exchange contracts landed and passed focused checks | Draft implementation plan from this artifact and rechecked source contracts | None | Implementation-plan drafting |
| Handoff | Handoff facts recorded; Stage 15 blocker resolved | Implementation-plan drafting may proceed from this planning artifact | None | Draft implementation plan |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Shared operation/evidence structure refinement | include, confirmed | Reduces duplicate adapter identity, operation status, diagnostic, and unsupported-operation shapes before Stage 16 adds more of them. | Must stay bounded and preserve subsystem ownership boundaries. |
| Local payload materialization | include, confirmed | Required by roadmap and useful for local bundle/container/HPC workflows. | Copy-only in Stage 16; keep explicit policy handles for future link/cache/staging strategies. |
| External publish for immutable outputs | include, confirmed | Required by roadmap and Stage 15 published immutable output records. | Explicit, immutable, capability-checked, checksum-verified when possible, and does not imply automatic global cache lookup, partial-stage reuse, or remote catalog behavior. |
| Remote upload/download operations | recommended default | Required by roadmap when backend capabilities support them. | Fake backend in core; no real backend family selected. |
| Checksum verification | recommended default | Required by roadmap and remote-store feature spec. | Must distinguish byte checksum from semantic fingerprint. |
| Staging lifecycle records | recommended default | Required by roadmap and future cleanup/reliability stages. | Derived/non-authoritative records by default. |
| Bundle export explicit materialization | recommended default | Required by roadmap; Stage 12/15 exchange should preserve metadata and support requested payload materialization. | Must remain opt-in. |
| Import metadata-only preservation | recommended default | Required by roadmap exit criteria. | Import should not require credentials for metadata-only refs. |
| Optional real backend adapter family | defer, confirmed | Roadmap permits at most one family only if a concrete downstream need selects it; user agreed to skip for now. | Keep fake backend as the core proof path. |
| Plugin packaging for optional backend | defer, confirmed | Required only if a real backend family is selected. | Keep API/unsupported handles ready for future plugin-backed adapters. |
| Network/credential preflight probes | include, confirmed | Useful for selected materialization operations but should remain opt-in. | Cheap by default; network, credential, payload-read, and checksum probes only run when explicitly requested for a selected operation. |
| Retry/timeout policy | defer | Stage 19 owns reliability policy. | Stage 16 may record retry-ready operation diagnostics only. |
| Cleanup/retention/GC | defer | Stage 20 owns cleanup and retention. | Stage 16 should record derived staging/cache facts for later cleanup. |
| Distributed locking or global cache | out of scope | Explicitly deferred by roadmap. | Do not include in Stage 16. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Confirm primary planning priority for Stage 16. | none | 1 | Optimize around bundle export/import with requested payload materialization, backed by generic fake-backend contracts and metadata-only defaults. | Sets the center of gravity for API, CLI, examples, and phase boundaries. | User confirmed bundle export/import as the primary example. | confirmed |
| FRQ-2 | Decide whether Stage 16 selects one optional real backend family or explicitly skips real backend implementation. | FRQ-1 | 2 | Skip real backend by default unless the user names a concrete required backend family. | This is an exit-criteria decision and affects dependencies, integration tests, packaging, and CI. | User agreed to skip a real backend for now. | confirmed |
| FRQ-3 | Lock default materialization behavior for bundle export/import. | FRQ-1 | 3 | Metadata-only by default; explicit flags/options required for payload movement. | Prevents surprise downloads/uploads and preserves credential-free exchange. | User selected bundle export/import as the primary workflow; metadata-only default remains from roadmap framing. | confirmed |
| FRQ-4 | Lock local materialization semantics. | FRQ-1 | 4 | Always copy in Stage 16, with request/result handles reserved for future policies. | Copy is safest across filesystems, bundles, containers, and later controller migration workflows. Future handles avoid closing the door on hardlink, symlink, reflink, cache-promote, or move policies. | User confirmed copy-only now with future policy handles. | confirmed |
| FRQ-5 | Lock publish semantics for immutable outputs. | FRQ-1 | 5 | Publish is explicit, immutable, capability-checked, checksum-verified when possible, and does not trigger planner global cache reuse, partial-stage reuse, remote catalog behavior, or credential lifecycle management. | Prevents publish from smuggling in Stage 19/20 or cache/reuse behavior. | User confirmed the recommended narrow publish semantics. | confirmed |
| FRQ-6 | Lock CLI surface policy. | FRQ-1 | 6 | Add narrow CLI only when the command is useful and expected to be run relatively frequently; otherwise expose public API and NotImplemented/unsupported handles. | Prevents low-frequency backend operations from bloating CLI while preserving future extension points. | User confirmed this policy. | confirmed |
| FRQ-7 | Lock materialization preflight probe behavior. | FRQ-1 | 7 | Keep preflight cheap by default; run network, credential, payload-read, and checksum probes only when explicitly requested for a selected materialization operation. | Prevents readiness checks from becoming surprising remote I/O while still giving users a way to verify expensive operations before running them. | User confirmed the recommended cheap-by-default, opt-in-expensive-probe policy. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Explicit materialization operation surface | none | Provide APIs for requested local/external/remote payload movement over Stage 15 refs and backend capabilities. | Users need payload bytes only when explicitly requested. | Core operation records and fake backend. | Calls return structured success/failure/unsupported results. | Backend handler checks capabilities and records redacted diagnostics. Local materialization copies payloads in Stage 16 and reserves explicit policy fields for future non-copy behavior. | Materialize, publish, upload, download. | Contract tests with fake backend. | recommended default |
| FR-2 | Metadata-only default preservation | FR-1 | Preserve external/remote refs through inspect/catalog/export/import without credentials or downloads. | Keeps existing workflows cheap, safe, and reviewable. | Run catalog and bundle/import behavior. | Metadata operations do not require backend credentials. | Payload operations are skipped unless explicitly requested. | Safe exchange and review workflows. | No-download assertions and metadata round trips. | recommended default |
| FR-3 | Checksum verification and mismatch diagnostics | FR-1 | Verify byte checksums where provided and supported; report unsupported or mismatch states. | Payload movement needs integrity evidence. | Local and fake remote behavior; selected real backend if any. | Users see clear checksum status. | Operation results separate checksum from fingerprint evidence. | Trustworthy materialization. | Fake mismatch tests. | recommended default |
| FR-4 | Staging and derived materialized-ref records | FR-1 | Record staging/cache/materialized paths, lifecycle status, and cleanup-relevant facts as derived data. | Later reliability and cleanup need facts without making cache authoritative. | Store/run metadata records, not authority lifecycle truth. | Inspection can show derived materialization evidence. | Staging failures are visible and do not corrupt authoritative refs. | Safe publish/download staging. | Failure injection tests. | recommended default |
| FR-5 | Bundle/export/import explicit payload materialization | FR-1, FR-2 | Add options for requested external/remote payload materialization during export/import where supported. | Portable run workflows need a safe path to include payloads when intentionally requested. | Existing `loom.runs` exchange APIs; CLI only for frequent expected workflows. | Metadata-only remains default; explicit payload requests report unsupported refs. | Bundle code consumes Stage 15 summaries and Stage 16 operation results. | Portable payload transfer. | Bundle export/import fake-backend tests. | confirmed as primary example |
| FR-6 | Optional backend adapter selection | FR-1 | Explicitly skip real backend implementation for Stage 16 unless a concrete downstream need appears before phase implementation begins. | Roadmap exit criteria require selecting or skipping a backend family. | No real backend family in the default Stage 16 plan. | Users get generic API/unsupported handles and fake-backend-proven behavior, not first-party cloud/tracking integration. | Optional dependencies remain outside default install. | Future backend integration path without current dependency cost. | Package/import tests prove no optional SDKs are loaded. | confirmed defer |
| FR-7 | Materialization preflight checks | FR-1 | Add explicit checks for selected materialization operations, capabilities, credentials, and network probes where requested. | Users need clear readiness diagnostics before expensive payload operations. | Cheap default checks plus opt-in expensive probes. | Missing capability or credentials appear as structured checks. | Preflight does not upload/download by default and expensive probes run only when explicitly requested. | Operational readiness. | Preflight check-ID tests. | confirmed |
| FR-8 | Narrow user-facing CLI and unsupported handles | FR-5 | Add CLI only for frequent expected bundle/materialization workflows; otherwise expose Python APIs and structured unsupported/NotImplemented handles. | Keeps CLI usable and avoids pretending rare backend paths are implemented. | CLI surface and public API behavior. | Frequent workflows get command support; unsupported paths fail clearly. | API results preserve future backend/CLI extension points. | Clear user experience without CLI sprawl. | CLI contract tests only for included commands; API tests for unsupported handles. | confirmed |
| FR-9 | Shared operation/evidence primitives | FR-1 | Extract or define a small shared plain-data contract for adapter identity, operation status, diagnostics, evidence checks, and unsupported-operation results before adding new materialization behavior. | Avoids adding another parallel result vocabulary and makes future backend/materialization/transfer/preflight extension cleaner. | Bounded structural refinement only; no mega-protocol and no authority lifecycle merge. | Users see more consistent diagnostics and unsupported results across APIs and CLI. | Existing exchange/diagnostic code can adopt shared projection helpers where dependency direction remains clean. | Maintainable operation vocabulary. | Package/import tests plus unit/contract tests for shared primitives and adapted callers. | confirmed |

## Behavior Baseline

Included functionality:

- Bundle/export/import is the primary Stage 16 workflow. Core materialization
  behavior remains fake-backend-first with no real backend family selected.
  Narrow CLI is included only when a command is likely to be frequent and
  expected; otherwise public APIs return structured unsupported or
  NotImplemented-style results.
- Local materialization always copies payloads in Stage 16. The interface may
  expose an explicit policy field or equivalent reserved handle, but non-copy
  policies must return unsupported/not implemented until a later stage selects
  them.
- Publish is an explicit immutable payload operation. It records capability
  admission, staging facts, selected target, and checksum evidence when
  possible, but it does not participate in planner global-cache lookup,
  partial-stage reuse, remote catalog behavior, or credential lifecycle
  management.

User-visible behavior:

- Explicit APIs and optional narrow CLI flags/commands for requested
  materialization; metadata-only workflows remain unchanged by default.
  Bundle export/import is the main user-visible demonstration.

Default behavior:

- No implicit payload upload, download, publish, or remote checksum probe.
- Local materialization uses copy semantics only.
- Materialization readiness checks stay cheap by default; network,
  credential, payload-read, and checksum probes run only when explicitly
  requested for a selected operation.

Failure behavior and diagnostics:

- Unsupported capability, missing backend, missing credentials, checksum
  mismatch, unsafe path, partial staging, and backend failure return structured
  diagnostics with redacted details.

Explicit deferrals:

- Retries/timeouts/events to Stage 19; cleanup/retention/GC to Stage 20;
  broad backend parity and credential lifecycle management out of scope.

Out-of-scope behavior:

- Automatic global cache lookup, distributed cache, provider parity, signed
  manifests, remote catalog services, and domain-specific artifact semantics.
- Live controller-to-controller migration, authority merge/fork policy, and
  migrated resume remain out of scope. Stage 16 supports the payload side of
  future migration workflows; it does not decide lifecycle truth.

Context compaction/reset checkpoint:

- Checkpoint status: completed
- Notes path: `docs/roadmap/stage-16/planning.md`
- Resume instruction: reload this planning artifact and
  `.codex/workflows/roadmap-stage-planning.md`, then use
  `.codex/prompts/roadmap-stage-design-agreement.md`. Treat the functionality
  and behavior baseline above as binding unless the user explicitly reopens a
  decision or design review exposes a real contradiction.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Likely modules or packages:

- Recommended shape for design review:
  - A small import-light shared operation/evidence layer owns generic
    operation vocabulary: adapter identity, operation status, diagnostics,
    evidence checks, unsupported-operation records, redaction-safe detail, and
    projection helpers. Proposed placement is a new top-level
    `loom.operations` module or package; this is the only design item that
    still needs user agreement because it creates a reusable public import
    path.
  - `loom.artifacts` remains the owner of artifact identity and metadata
    records such as `ArtifactRef`, `ArtifactAddress`, `ArtifactStoreRef`,
    `ArtifactLocationSummary`, `ExternalArtifactDeclaration`, and
    `PublishedArtifactRecord`. It should not own transfer handlers, backend
    clients, local copy behavior, run bundle policy, preflight checks, or
    plugin loading.
  - `loom.pipeline.stores` owns artifact payload materialization protocols,
    materialization request/result records, local copy execution, fake backend
    publish/upload/download/verify handlers, capability admission, checksum
    evidence, staging lifecycle records, and derived materialized/published
    refs.
  - `loom.runs` owns bundle/export/import options and result integration. It
    consumes public artifact and store materialization results, preserving
    metadata-only defaults and projecting payload-operation evidence into run
    exchange results without provider-specific schema.
  - `loom.diagnostics` owns preflight presentation over public store/artifact
    contracts. It may call materialization readiness helpers and optional probe
    APIs, but lower store/artifact modules must not import diagnostics.
  - `loom.plugins` remains explicit discovery/loading coordination only. Stage
    16 skips real backend loading but preserves handler/unsupported surfaces
    for future plugin-backed adapters.

Likely public classes, functions, or protocols:

- Candidate names are intentionally provisional until Stage 15 contracts are
  rechecked:
  - Shared operation/evidence: `OperationAdapterIdentity`, `OperationStatus`,
    `OperationDiagnostic`, `EvidenceCheck`, `UnsupportedOperation`,
    `OperationResultSummary`, and projection helpers that produce plain data
    without importing `loom.runs`, `loom.diagnostics`, `loom.authority`, CLI,
    plugins, or optional SDKs.
  - Store/materialization: `ArtifactPayloadOperationKind`,
    `ArtifactMaterializationPolicy`, `ArtifactMaterializationRequest`,
    `ArtifactMaterializationResult`, `ArtifactMaterializationHandler`, and
    fake/local helper entrypoints for copy, publish, upload, download, and
    verify.
  - Bundle/preflight integration: run-exchange option/result fields and
    preflight request/probe selectors that consume the shared operation records
    rather than defining new independent status/diagnostic shapes.

Likely internal helpers:

- Local copy helper that rejects non-copy policies with structured unsupported
  results.
- Checksum evidence helpers that keep byte checksums distinct from
  fingerprints.
- Staging record helpers that mark staging/cache/materialized refs as derived
  and cleanup-relevant, never authoritative truth.
- Fake backend handlers for successful, unsupported, failed, and checksum
  mismatch paths.
- Redaction helpers for backend URI/config details and exception summaries.
- Projection helpers in consuming modules: run exchange converts shared
  operation records to run-exchange diagnostics/results; diagnostics converts
  them to preflight checks.

Data flow:

- Stage 15 artifact summary/store ref plus explicit materialization request ->
  operation/capability admission -> local copy or fake backend handler ->
  staging/download/upload/publish action -> checksum verification where
  available -> shared operation/evidence result -> derived
  materialized/published location record -> bundle/import/catalog/preflight
  projection.
- Metadata-only catalog, inspect, export, and import paths bypass payload
  handlers and preserve external/remote refs without credentials.

Dependency direction:

- Shared operation/evidence records depend only on foundational modules such
  as serialization/plain-data helpers and root errors.
- `loom.artifacts` stays import-light and does not import `loom.io`,
  `loom.pipeline.stores`, `loom.runs`, `loom.diagnostics`, plugin discovery,
  or optional backends.
- `loom.pipeline.stores` consumes artifact records, neutral URI helpers, and
  shared operation/evidence records; it does not import diagnostics, runs,
  CLI, plugins, authority lifecycle import, or project code.
- `loom.runs` and `loom.diagnostics` consume public artifact/store/operation
  contracts and own their local projections.
- CLI remains presentation over public APIs.

Extension points and flexibility boundaries:

- Future non-copy local policies are represented in request/result types but
  return unsupported/not implemented in Stage 16.
- Future real backends plug into the same handler/capability/materialization
  shape; core does not encode S3/GCS/Azure/MLflow/DVC-specific methods.
- Future Stage 19 reliability can wrap operation results with retry/timeout
  policy. Stage 16 records enough status and diagnostic detail, but does not
  implement retry policy.
- Future Stage 20 cleanup can consume derived staging/cache/materialized facts,
  but Stage 16 does not implement deletion or retention policy.
- Authority import, portable exchange, preflight diagnostics, and payload
  materialization remain separate protocols. Shared primitives are value
  objects and projection helpers, not a single lifecycle protocol.

Generic interface, adapter, or protocol shape:

- Generic operation records should model:
  - adapter identity: backend/fake/local/bundle/provider identity without
    importing provider clients;
  - operation kind and status: success, failure, blocked, unsupported, and
    skipped/probe states where needed;
  - diagnostics: machine-readable code, severity, message, redacted details;
  - evidence checks: checksum/capability/staging/probe evidence with proven,
    unproven, unsupported, or failed outcomes;
  - unsupported operations: stable reason/detail records for API, bundle, CLI,
    and preflight consumers.
- Artifact materialization handlers should be store-owned protocols that
  accept import-light artifact/store refs and return strict plain-data results.
  They should not expose backend client objects or provider SDK exceptions in
  public records.

Future-roadmap impact:

- Stage 17 Docker and Stage 18 HPC can rely on copy-only local materialization
  and derived staging records to prepare payloads for container mounts or
  shared filesystems.
- Stage 19 can add retry/timeout/event policy around operation results without
  rewriting materialization request/result records.
- Stage 20 can use derived materialization and staging records as cleanup
  candidates without treating them as authoritative artifact truth.
- A future real backend adapter can implement the same handler and operation
  result surface without changing bundle/import/preflight behavior.

Compatibility constraints:

- Existing `ArtifactRef`, local artifact-store behavior, run catalog summaries,
  and bundle metadata-only defaults remain compatible.
- Existing run-exchange result schemas should be extended through clear
  operation-result fields or a narrow schema revision only if Stage 15 landed
  summaries cannot be represented safely through existing extension points.
- No default import path may discover plugins, import optional backend SDKs, or
  perform network or credential probes.
- Persisted operation records must be strict, plain-data-compatible, redacted,
  and resilient to unsupported backends.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Shared operation/evidence primitive ownership and public import path. | FR-9 | 1 | recorded recommendation | Create a small import-light top-level `loom.operations` module/package for generic operation value objects and projection helpers. | This creates a reusable public contract across materialization, run exchange, diagnostics, and future adapters. Putting it in the wrong subsystem either preserves duplication or couples lower layers to higher ones. | User confirmed `loom.operations` as the shared primitive placement. | confirmed |
| DAQ-2 | Materialization protocol ownership and public API placement. | DAQ-1, FR-1 | 2 | recorded recommendation | Store-owned materialization protocol under `loom.pipeline.stores`, using import-light artifact records and shared operation/evidence results; expose stable public imports through `loom.pipeline.stores`, not `loom.__init__`. | Keeps payload movement near artifact store policy while avoiding artifact value objects, run exchange, diagnostics, or CLI owning transfer semantics. | Repo evidence is strong and DAQ-1 is confirmed. | confirmed |
| DAQ-3 | Optional real backend family shape, if any. | FRQ-2 | 3 | recorded recommendation | Skip real backend unless a concrete need selects one; preserve API/unsupported handles for future adapters. | Controls dependency and CI complexity. | User confirmed no real backend for now. | confirmed |
| DAQ-4 | Local materialization policy and future policy handles. | FRQ-4 | 4 | recorded recommendation | Copy-only in Stage 16; reserve explicit policy handles for future hardlink, symlink, reflink, move, cache-promote, or staging policies. | Copy behavior is portable and predictable for bundles, containers, shared filesystems, and controller migration. Future handles avoid an incompatible API revision when non-copy policies become useful. | User confirmed copy-only now with future policy handles. | confirmed |
| DAQ-5 | Staging/cache authority boundary. | FR-4 | 5 | auto-approved | Derived records only; never authoritative artifact truth. | Prevents cache/staging paths from corrupting run state semantics. | Design-safety review upheld this because glossary/read-model boundaries are strong and validation is straightforward. | confirmed |
| DAQ-6 | Bundle materialization schema compatibility. | FR-5 | 6 | recorded recommendation | Extend Stage 15 run-exchange summaries with explicit operation results or a narrow schema revision only if existing extension fields are insufficient; never add provider-specific schema. | Durable bundle artifacts must remain portable and metadata-only by default. | Stage 15 exchange rework is landed; implementation planning should choose the narrowest projection over the landed exchange records. | confirmed |
| DAQ-7 | Preflight probe policy and API placement. | FR-7 | 7 | auto-approved | Diagnostics owns preflight presentation; materialization readiness remains cheap by default and expensive probes are explicit request fields or options. | Avoids surprising side effects and lower-layer imports of diagnostics. | Design-safety review upheld this because behavior is confirmed, feature docs require cheap defaults, and import-boundary tests can validate it. | confirmed |
| DAQ-8 | Cross-module unification boundary for operation/result/diagnostic shapes. | DAQ-1, FR-9 | 8 | recorded recommendation | Share only adapter identity, operation status, diagnostics, evidence checks, unsupported-operation, redacted details, and plain-data projection helpers; do not unify authority import, portable exchange, preflight, and payload materialization into one protocol. | Reduces duplicate code and vocabulary drift while preserving distinct ownership of lifecycle truth, run exchange, diagnostics, and payload movement. | DAQ-1 placement is resolved. | confirmed |
| DAQ-9 | Bounded structure-refinement phase before new materialization behavior. | DAQ-1, DAQ-8 | 9 | recorded recommendation | Include Phase 1 to extract shared operation/evidence primitives and update existing exchange/diagnostic code only where dependency direction remains clean. | Prevents Stage 16 from adding another parallel result/diagnostic vocabulary. | User requested this early phase; design pass must keep scope and stop conditions explicit. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Shared operation/evidence primitive ownership and public import path | New import-light top-level `loom.operations` module/package for generic operation value objects and projection helpers | User confirmed on 2026-05-15 | Keeping primitives duplicated in `loom.runs`, `loom.diagnostics`, and `loom.pipeline.stores`; putting them in diagnostics; putting them in authority; putting them in `loom.protocols` as if they were structural protocols | The primitives are plain value objects, not lifecycle truth or diagnostics presentation. A top-level import-light module keeps dependency direction clean. | Reduces repeated status/diagnostic/unsupported shapes while avoiding a broad refactor. | Gives future materialization, exchange, preflight, and backend adapters a shared vocabulary without forcing a single operation protocol. | Stage 19/20 can consume operation records; future adapters can reuse the vocabulary. | Creates a small public import path and projection-helper contract. | Package import-boundary tests, unit serialization/redaction tests, and contract tests for adopted projections. | Revisit if the shared module grows beyond generic operation/evidence primitives or starts importing subsystem code. | confirmed |
| DAQ-2 | Materialization protocol ownership and public API placement | Store-owned protocol and records under `loom.pipeline.stores`, with public store imports and no root `loom.__init__` export in Stage 16 | DAQ-1 confirmed | Artifact-owned payload movement; run-exchange-owned transfer; diagnostics-owned operation APIs; CLI/provider-owned behavior | Store policy already owns artifact persistence/materialization surfaces; artifacts should remain metadata value objects. | Keeps transfer behavior close to store policy and fake backend tests. | Future real backends can implement the same handler without changing runs/diagnostics. | Docker/HPC/reliability/cleanup stages can consume store-owned materialization facts. | Adds materialization request/result/handler protocol and fake backend contract. | Store contract/unit tests and package import-boundary tests. | Revisit if Stage 15 handler contracts land in a different namespace. | confirmed |
| DAQ-3 | Optional real backend family shape | Skip real backend for Stage 16; preserve unsupported handles | User confirmed | Selecting S3/GCS/Azure/MLflow/DVC now; adding provider SDKs to core | No concrete downstream backend need exists and roadmap permits explicit skip. | Keeps default install and CI lean. | Future backend can be added through same handler/plugin shape. | Avoids overfitting before Stage 17-20 consumers validate needs. | Unsupported operation results become part of the adapter contract. | Package tests proving no optional SDK imports; fake-backend contract tests. | Revisit when a concrete backend need is supplied. | confirmed |
| DAQ-4 | Local materialization policy and future policy handles | Copy-only in Stage 16 with explicit unsupported/not-implemented results for other policies | User confirmed | Hardlink/symlink/reflink/move/cache-promote implementation now; silent fallback from requested non-copy to copy | Copy is portable across bundles, containers, shared filesystems, and controller-migration-adjacent workflows. | Reduces filesystem-specific edge cases. | Request/result policy fields leave room for future efficient strategies. | Supports Docker/HPC staging without link semantics. | Materialization request/result carries a policy field or equivalent reserved handle. | Unit/integration tests for copy success, checksum, and unsupported non-copy policies. | Revisit when a later stage selects a non-copy policy. | confirmed |
| DAQ-5 | Staging/cache authority boundary | Derived records only; never authoritative artifact truth | Design-safety review upheld this as auto-approved with validation obligations | Treating downloaded/staged paths as canonical artifact records; mutating authority lifecycle truth from materialization | Glossary and read-model code distinguish authority from materialized refs. | Prevents state corruption and keeps cleanup separable. | Stage 20 can use derived records for cleanup without deleting external truth. | Critical for Docker/HPC/reliability/cleanup compatibility. | Materialized/published refs include derived authority metadata and cleanup hints. | Failure injection tests and read-model/catalog assertions. | Revisit if a future authority feature intentionally records durable materialization refs. | confirmed |
| DAQ-6 | Bundle materialization schema compatibility | Project shared operation results into run exchange summaries or use a narrow schema revision only if landed Stage 15 summaries cannot fit; avoid provider-specific fields | Stage 15 source recheck completed on 2026-05-15 | Provider-specific manifest fields; implicit downloads; putting backend clients/config into bundles | Bundle artifacts must remain portable, inspectable, and metadata-only by default. | Keeps bundle code as a consumer of materialization results. | Future backends can appear as operation evidence, not schema families. | Preserves v12 exchange semantics and future migration optionality. | Bundle result schema gains generic operation evidence only. | Contract tests for metadata-only refs and explicit fake-backend materialization. | Revisit if Stage 16 implementation proves existing exchange result fields cannot carry generic operation evidence clearly. | confirmed |
| DAQ-7 | Preflight probe policy and API placement | Diagnostics owns preflight presentation; expensive probes are opt-in request fields/options | User confirmed behavior | Default network/credential probes; lower stores importing diagnostics; preflight that uploads/downloads by default | Feature docs and Stage 15 planning require cheap defaults and side-effect-light checks. | Keeps default preflight deterministic. | Probe selectors can grow without changing defaults. | Stage 19 can add retry policy later without changing probe defaults. | Preflight consumes operation/capability summaries and emits check IDs. | Diagnostics unit/integration tests with fake handlers and no-network default assertions. | Revisit if named preflight profiles become necessary. | auto-approved |
| DAQ-8 | Cross-module unification boundary | Share plain primitives and projection helpers only; keep subsystem protocols separate | DAQ-1 confirmed | One mega-protocol for authority import, exchange, diagnostics, and payload movement; no shared vocabulary at all | User concern about duplication is valid, but subsystem ownership and failure semantics differ. | Reduces duplication without collapsing boundaries. | Future consumers can adopt projections incrementally. | Avoids expensive later refactors while preserving authority/exchange/preflight boundaries. | Shared primitives are value records, not a protocol every subsystem must implement. | Package tests for import direction plus compatibility tests for adopted projections. | Revisit if repeated wrappers remain after Stage 16 and prove unnecessary. | confirmed |
| DAQ-9 | Bounded structure-refinement phase before materialization | Include as Phase 1 with strict stop conditions | User requested this phase | Refactor after materialization; broad module reshuffling; authority lifecycle import changes | Establishes stable vocabulary before new operations multiply result types. | Improves consistency while keeping diff reviewable. | Gives later phases a shared contract. | Makes Stage 19/20 consumption easier. | Phase 1 creates/exports shared operation/evidence primitives only. | Unit/contract/package tests; no behavior-changing integration unless an adopted projection needs it. | Revisit if Phase 1 starts moving subsystem ownership instead of extracting plain primitives. | confirmed |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Top-level public module is the cleanest dependency boundary, and the user confirmed `loom.operations`. | FR-9 | Record confirmed. | confirmed |
| DAQ-2 | recorded recommendation | Store ownership follows existing artifact-store/materialization boundaries and avoids importing diagnostics/runs into stores. | FR-1, FR-5 | Record confirmed. | confirmed |
| DAQ-3 | recorded recommendation | Backend skip is already confirmed and satisfies roadmap exit criteria. | FR-6 | Keep confirmed. | confirmed |
| DAQ-4 | recorded recommendation | Copy-only is already confirmed and safest across target future consumers. | FR-1 | Keep confirmed. | confirmed |
| DAQ-5 | auto-approved | Derived/non-authoritative staging follows glossary and read-model precedent; design-safety review upheld this only with validation that partial staging cannot mutate authority truth. | FR-4 | Keep confirmed with validation obligations in design-safety findings. | confirmed |
| DAQ-6 | recorded recommendation | Bundle schema must remain generic, but exact extension/schema decision depends on landed Stage 15 exchange contracts. | FR-5 | Record recommendation and Stage 15 recheck obligation. | confirmed |
| DAQ-7 | auto-approved | Behavior is confirmed, feature docs support cheap defaults, and design-safety review upheld the diagnostics/store import boundary. | FR-7 | Keep confirmed with no-network default assertions. | confirmed |
| DAQ-8 | recorded recommendation | Narrow shared primitives address duplication without a mega-protocol. | FR-9 | Record confirmed after DAQ-1 placement. | confirmed |
| DAQ-9 | recorded recommendation | User requested early refactor; scope and stop conditions are already narrow. | FR-9 | Keep as first phase candidate. | confirmed |

## Design Safety Review

| Finding | Affected decision or requirement | Future-roadmap or compatibility risk | Interface, adapter, or protocol reuse risk | Recommended planning revision | Status |
| --- | --- | --- | --- | --- | --- |
| DSR-1: Stage 15 landed-contract dependency required source recheck before implementation planning. Current source now includes Stage 15 artifact records, backend handler/capability contracts, preflight checks, and exchange preservation. | FR-1, FR-5, DAQ-2, DAQ-6 | Drafting against stale or partial names would force Stage 16 to invent missing backend or exchange contracts. | Materialization handlers and bundle projections must consume the final Stage 15 public contracts instead of names inferred from the earlier plan. | Recheck completed on 2026-05-15: focused Stage 15 contract/unit tests passed, and implementation-plan drafting can use the landed names as the baseline. | resolved |
| DSR-2: `loom.operations` is a new public import path, so it is only safe if it remains a small plain-data vocabulary. | DAQ-1, DAQ-8, DAQ-9, FR-9 | A broad shared operation layer could become a de facto lifecycle protocol and constrain authority, exchange, diagnostics, materialization, Stage 19 reliability, and Stage 20 cleanup. | Public value objects are reusable; a universal operation protocol is not. | Implementation planning must scope Phase 1 to adapter identity, operation status, diagnostics, evidence checks, unsupported-operation records, redacted detail, and projection helpers only. No root `loom.__init__` export, no subsystem imports, and no behavior-changing unification. | recorded recommendation |
| DSR-3: Store-owned materialization is the right boundary, but persisted operation records need explicit authority and failure semantics. | FR-1, FR-3, FR-4, DAQ-2, DAQ-5 | Stage 17/18 staging, Stage 19 retries, and Stage 20 cleanup all depend on distinguishing partial staging, derived materialized refs, published external truth, and authoritative lifecycle state. | Handler results can be reused if they are plain, redacted, checksum-aware, and scoped to payload operations rather than run/stage lifecycle. | Keep materialization request/result records under `loom.pipeline.stores`; require structured outcomes for unsupported capability, missing backend, missing credentials, unsafe path, partial staging, checksum mismatch, and backend failure. Derived staging/cache records must not mutate authority truth. | auto-approved upheld for DAQ-5 with validation obligation |
| DSR-4: Bundle materialization schema must stay generic over the landed Stage 15 exchange records. | FR-2, FR-5, DAQ-6 | Provider-specific bundle fields or implicit downloads would break v12 portability, metadata-only imports, future controller migration work, and credential-free inspection. | Bundle/export/import should project shared operation evidence instead of owning provider transfer semantics. | Phase shaping must keep bundle integration after materialization records and fake backend operations. The implementation plan should prefer extension-field projection and choose a narrow schema revision only if the landed Stage 15 exchange records cannot represent generic operation evidence clearly. | recorded recommendation |
| DSR-5: Preflight probe policy is safe only if request selectors make expensive probes explicit and lower layers do not import diagnostics. | FR-7, DAQ-7 | Default network, credential, payload-read, or checksum probes would violate cheap preflight expectations and make CI/backend availability brittle. | Readiness helpers can be shared; preflight presentation remains diagnostics-owned. | Uphold DAQ-7 as auto-approved. Add validation obligations for no-network defaults, explicit expensive-probe selectors, stable check IDs, and import-boundary tests proving stores/artifacts do not import diagnostics. | auto-approved upheld |
| DSR-6: Copy-only local materialization is safe, but future policy handles must fail closed. | FR-1, DAQ-4 | Silent fallback from requested hardlink/symlink/reflink/move/cache-promote to copy could hide reproducibility and filesystem-boundary differences needed by containers and HPC. | The request/result policy field is reusable only if unsupported policies are represented as stable operation evidence. | Keep copy-only Stage 16 behavior. Require tests that unsupported non-copy policies return structured unsupported/not-implemented results and do not copy unless the caller explicitly requested copy. | recorded recommendation |
| DSR-7: Fake-backend-first validation leaves real-provider genericity unproven, but that risk is acceptable with stronger fake shapes. | FR-6, DAQ-3 | The first real backend may later expose missing consistency, credential, streaming, or commit-policy fields. | Generic adapter contracts are still reusable if fake coverage includes object-store-style and tracking-system-style behavior instead of one happy-path fake. | Accept no real backend for Stage 16. Require fake backend contract tests for at least two backend personalities or scenarios that exercise read-only, writable, unsupported, failed, checksum-mismatch, and redacted-diagnostic paths. | accepted risk |

Gate result:

- Status: passed for design-safety review; Stage 15 landed-contract recheck
  is complete and implementation-plan drafting may proceed.
- Reviewer: Codex `loom_design_safety_reviewer` pass on 2026-05-15.
- Blockers: none in the Stage 16 design shape or implementation readiness.
- Recorded recommendations:
  - Keep `loom.operations` narrow, import-light, plain-data-only, and below
    runs, diagnostics, CLI, plugins, optional backends, and authority-specific
    lifecycle code.
  - Keep materialization protocols and records store-owned, with no
    diagnostics, runs, CLI, plugin discovery, project-code, or optional SDK
    imports from store/artifact modules.
  - Keep bundle/export/import schema generic and metadata-only by default;
    prefer extension-field projection over the landed Stage 15 exchange
    records, and choose a narrow schema revision only if that representation
    is unclear.
  - Keep expensive preflight probes explicit and selected; default preflight
    must remain side-effect-light and network-free.
  - Use fake backend contracts to pressure-test at least object-store-like and
    tracking-system-like behavior before claiming the adapter shape is generic.
- Future-roadmap impact summary: Stage 17/18 can consume copy materialization
  and derived staging records for container/HPC payload placement. Stage 19 can
  wrap operation results with retry/timeout/event policy without changing
  materialization records. Stage 20 can consume derived cleanup facts without
  treating materialized refs as authoritative artifact truth. Future real
  backends can reuse the handler/result shape but may trigger a revisit if they
  need missing consistency, streaming, credential, or commit-policy fields.
- Generic interface, adapter, and protocol assessment: adequate for
  implementation planning after the completed Stage 15 source recheck. Shared
  primitives are generic enough only as value objects and projection helpers; authority
  lifecycle import, portable exchange, preflight diagnostics, and payload
  materialization must remain separate protocols.
- Planning revisions completed:
  - Readiness now records the completed Stage 15 backend/capability/preflight
    and exchange recheck.
  - DAQ-5 and DAQ-7 are recorded as auto-approved with validation
    obligations.
  - Fake-backend genericity obligations are carried into examples, validation,
    and phase shaping.
- Accepted risks:
  - Stage 16 skips a real backend family, so first-provider integration may
    reveal missing adapter fields later.
  - `loom.operations` creates a public import path before all future consumers
    exist; this is acceptable only while it remains narrow and import-light.
  - Stage 15 is now complete, but Stage 16 may still need a narrow exchange
    projection adaptation if landed fields cannot carry operation evidence
    clearly.
- Revisit triggers:
  - Stage 16 implementation finds that landed Stage 15 exchange fields cannot
    represent generic operation evidence without ambiguity.
  - A concrete backend need appears before phase implementation begins.
  - Fake backend tests cannot represent both object-store-style and
    tracking-system-style behavior with the same handler/result shape.
  - Phase 1 starts moving authority import, run exchange, diagnostics, or
    materialization protocols into one shared subsystem.

## Practical Design Notes

Public Python API surface:

- Confirmed recommendation:
  - shared generic operation/evidence primitives in a new import-light
    `loom.operations` module/package;
  - materialization request/result/handler records exported from
    `loom.pipeline.stores`;
  - bundle/export/import and preflight consume those records through their own
    public option/result surfaces;
  - no root `loom.__init__` re-export in Stage 16.

CLI surface:

- Confirmed behavior is to prefer narrow options under existing artifact/run
  command families only for frequent expected workflows over a broad
  provider-management CLI.

Persisted records and file layout:

- Strict plain operation records with redacted backend details, checksum
  evidence, capability admission facts, and derived
  staging/cache/materialized refs. No provider SDK client, credential, raw
  exception, or non-plain object may enter persisted records.

Import boundaries and dependencies:

- No optional backend SDK in default imports, no plugin discovery on
  `import loom`, no diagnostics imports from stores/artifacts, and no
  `loom.runs` import from stores or execution. Shared operation/evidence
  records must stay below runs, diagnostics, CLI, plugins, and optional
  backends.

Failure modes and diagnostics:

- Unsupported capability, missing backend, missing credentials, checksum
  mismatch, unsafe path, partial staging, backend failure, unavailable probe,
  and unsupported future local policy return structured diagnostics with
  redacted details.

Extension points and flexibility boundaries:

- Explicit future handles: non-copy local materialization policies,
  backend-provided publish/upload/download/verify operations, operation
  evidence projections, opt-in preflight probes, and plugin-backed adapter
  loading. Explicit non-goals: global cache lookup, controller migration,
  authority merge/fork/resume policy, retry/timeout policy, cleanup/retention,
  credential lifecycle, and provider-specific schema in core.

Generic interfaces, adapters, and protocols:

- Confirmed design: share small plain-data primitives in `loom.operations`,
  including adapter identity, operation status, diagnostic detail,
  evidence-check, unsupported-operation, redacted-detail, and projection
  helpers. Keep separate protocols for authority lifecycle import, portable
  run exchange, preflight diagnostics, and artifact payload materialization.

Future-roadmap compatibility:

- Stage 17/18 can consume local copy materialization and derived staging facts.
  Stage 19 can wrap operation records with reliability policy. Stage 20 can
  consume derived cleanup facts without deleting authoritative external
  artifacts. Future backend adapters should conform to the same handler/result
  shape.

Maintainability assessment:

- Current assessment: recommended, provided DAQ-1 keeps the shared primitive
  layer narrow and import-light. The refactor reduces duplicated statuses and
  diagnostics without merging subsystem ownership.

Extensibility assessment:

- Current assessment: stronger than local-only shapes because future backend,
  reliability, cleanup, and bundle consumers can reuse generic operation
  evidence. The main risk is over-widening the shared primitive layer.

Flexibility and expansion assessment:

- Current assessment: future local policies and real backends have explicit
  handles while Stage 16 behavior remains copy-only and fake-backend-first.

Scalability and future compatibility:

- Current assessment: operation records should be cheap, metadata-first, and
  projection-oriented. Large payload reads, network probes, checksum scans, and
  backend transfers remain explicit operations rather than default catalog or
  preflight work.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Stage 16 may need a narrow exchange projection adaptation | Landed Stage 15 exchange records are the baseline, but Stage 16 operation evidence must remain generic and readable in bundles | Implementation finds existing extension/result fields cannot represent operation evidence clearly |
| No real backend family is selected for Stage 16 | Keeps core dependency-light and fake-testable while no concrete downstream backend need exists | A concrete backend need appears, or fake object-store-style and tracking-system-style tests cannot share one generic handler/result shape |
| New public `loom.operations` import path is introduced before all future consumers exist | Shared value objects reduce duplicated result/diagnostic shapes, but the surface must stay narrow to avoid public API overreach | The module starts importing subsystem code, exposing lifecycle protocols, or requiring root `loom.__init__` exports |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Shared unsupported operation | Existing transfer, preflight, and materialization-facing code can report unsupported operations through one plain-data shape | Cross-module operation contract | Unit/contract tests | confirmed |
| Fake remote download | Explicit download materializes a payload through fake backend with checksum verification | Core materialization contract | Unit/contract tests | confirmed |
| Fake publish immutable output | Publish records immutable output evidence and fails closed on unsupported backend capability | Stage 15 published artifact records | Unit/contract tests | confirmed |
| Fake backend shape pressure test | Object-store-style and tracking-system-style fake handlers use the same generic operation records without provider-specific bundle schema | Backend adapter contract | Unit/contract tests | confirmed |
| Metadata-only bundle export with remote ref | Export preserves remote ref and unsupported-materialization diagnostics without download | Run bundle exchange | Contract/integration tests | confirmed |
| Explicit bundle export with payload materialization | Export includes requested payloads when backend supports download | Run bundle exchange | Integration tests with fake backend | confirmed |
| NotImplemented/unsupported backend handle | Unsupported real-backend materialization reports structured diagnostics without optional SDKs | API and future plugin boundary | Unit/contract tests | confirmed |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/import boundaries | Default import does not load optional backend SDKs or plugin targets; `loom.operations` stays import-light; stores/artifacts do not import diagnostics, runs, CLI, plugin discovery, or optional SDKs | Package tests | Package | `tests/package` | confirmed |
| Shared operation/evidence primitives | Adapter identity, operation status, diagnostics, evidence checks, unsupported-operation projection, and dependency direction | Unit/contract/package | Unit, contract, package | `tests/unit/loom`, `tests/contracts`, `tests/package` | confirmed |
| Operation records | Materialization/publish/upload/download records serialize strictly with redaction, checksum evidence, capability admission facts, partial-staging diagnostics, and unsupported-operation results | Unit/contract | Unit, contract | `tests/unit/loom`, `tests/contracts` | confirmed |
| Fake backend behavior | Supported, unsupported, failed, checksum mismatch, missing credential-like states, read-only object-store-style behavior, and tracking-system-style indirection | Unit/contract | Unit, contract | fake backend tests | confirmed |
| Bundle/export/import | Metadata-only default, explicit payload materialization, unsupported external/remote refs, no implicit downloads, and generic operation-evidence projection | Integration/contract | Integration, contract | `tests/unit/loom/runs`, `tests/integration` | confirmed |
| Preflight | Cheap defaults, stable check IDs, no-network default assertions, and opt-in expensive materialization probes | Unit/integration/package | Unit, integration, package | `tests/unit/loom/diagnostics`, `tests/integration/diagnostics`, `tests/package` | confirmed |
| Real backend skipped | No optional SDK is required; unsupported handles remain structured and future-backend-ready | Package/contract | Package, contract | package/import and unsupported-operation tests | confirmed |
| Full PR gate | Repository validation | PR gate | Local check | `make validate-pr` | pending implementation planning |
| Suite evidence | PR body evidence | Summary | Local check | `make test-summary` | pending PR preparation |

## Phase Sketch

### Phase 1 - Shared Operation And Evidence Contracts

Goal:

- Extract or define the bounded shared operation/evidence primitives that Stage
  16 materialization, v12 transfer evidence, preflight diagnostics, and future
  backend adapters can reuse without collapsing subsystem ownership.

Scope:

- Public strict plain-data records for adapter identity, operation status,
  operation diagnostics, evidence checks, unsupported-operation results,
  redacted details, and result projection helpers.
- Narrow adoption in existing exchange/diagnostic code only where import
  direction stays clean and behavior does not change.
- Public placement is `loom.operations`; no root `loom.__init__` re-export is
  required in Stage 16.

Out of scope:

- Local copy materialization, fake remote payload movement, bundle
  materialization, real backend adapters, authority lifecycle import changes,
  retries, cleanup, and broad module reshuffling.

Acceptance criteria:

- Existing run exchange, transfer evidence, and diagnostics behavior retains
  its current user-visible semantics while sharing a small common operation
  vocabulary where practical.
- The shared layer is import-light and does not import `loom.runs`,
  `loom.diagnostics`, `loom.authority`, CLI modules, plugin discovery, or
  optional backend SDKs.
- The phase records clear stop conditions for what remains intentionally
  separate.
- Phase 1 does not create a universal operation protocol and does not move
  authority import, run exchange, preflight, or materialization ownership into
  `loom.operations`.

Test expectations:

- Package: import-light public records and no optional backend imports.
- Unit: strict serialization, redaction, status aggregation/projection, and
  unsupported-operation helpers.
- Contract: shared operation/evidence result schema and compatibility adapters
  for existing transfer/diagnostic shapes where adopted.
- Integration: not required unless an existing cross-module caller is adapted.
- E2E: not required.
- Opt-in: none.

Design impact:

- Creates the durable vocabulary that later materialization phases must reuse.

Future compatibility:

- Records must be generic enough for artifact materialization, run transfer,
  preflight/readiness, future backend adapters, and Stage 19/20 policies
  without becoming a lifecycle-state protocol.

Alternatives rejected:

- A single mega-protocol covering authority import, run exchange, preflight,
  and payload movement.
- Leaving every subsystem to add another local status/diagnostic/result shape.

Debt introduced:

- Existing modules may still carry compatibility wrapper names after the
  refactor. Revisit after Stage 16 lands and repeated local wrappers are proven
  unnecessary.

Reviewability:

- This phase is structure-first and behavior-neutral. Review should focus on
  import direction, vocabulary, serialization strictness, and whether the
  extraction is truly bounded.

### Phase 2 - Local Materialization Records And Copy Semantics

Goal:

- Add Stage 16 materialization request/result records and local copy
  materialization semantics over landed Stage 15 artifact summaries using the
  shared Phase 1 operation/evidence primitives.

Scope:

- Materialization records, redaction, checksum evidence, local copy behavior,
  explicit future policy handles that return unsupported/not implemented for
  non-copy policies, derived materialized-ref records, and fake/local tests.

Out of scope:

- Fake remote backend payload movement, bundle integration, preflight
  integration, retries, cleanup, and real backend adapters.

Acceptance criteria:

- Local materialization succeeds or fails with structured diagnostics and does
  not mutate authoritative lifecycle truth incorrectly.
- Unsupported or not-implemented materialization paths use the shared operation
  vocabulary from Phase 1.
- Hardlink, symlink, reflink, move, and cache-promote policy requests do not
  silently fall back to copy unless the caller selected copy.

Test expectations:

- Package: import-light materialization records.
- Unit: local operation records, copy policy, unsupported future policies, and
  checksum behavior.
- Contract: materialization result schema.
- Integration: local temp-directory materialization.
- E2E: not required unless existing CLI/API path is confirmed.
- Opt-in: none.

Design impact:

- Creates durable materialization records consumed by later phases.

Future compatibility:

- Records must be generic enough for fake remote operations, real backend
  adapters, and Stage 19/20 policies.

Alternatives rejected:

- Implementing hardlink, symlink, reflink, move, or cache-promote local
  policies in Stage 16.
- Silently treating requested non-copy policies as copy.

Debt introduced:

- Request/result fields reserve future policy space before those policies are
  implemented. This is accepted because unsupported policies fail closed and
  avoid later incompatible API changes.

Reviewability:

- Keep local behavior and records separate from remote handler and bundle
  integration.

### Phase 3 - Backend Handler Materialization And Fake Remote Operations

Goal:

- Add backend handler methods/capability admission for publish, upload,
  download, and verify behavior using fake remote backends.

Scope:

- Store-owned protocol additions, fake backend implementation, unsupported
  capability handling, staging lifecycle records, redacted diagnostics.

Out of scope:

- Real backend SDKs and bundle export/import integration.

Acceptance criteria:

- Fake backends prove successful, unsupported, failed, checksum-mismatch,
  missing credential-like, read-only object-store-style, writable
  object-store-style, and tracking-system-style indirection operation paths.
- Fake backend records use the same generic operation/result shape without
  provider-specific bundle schema.

Test expectations:

- Package: no optional imports.
- Unit: backend handler and capability admission.
- Contract: fake backend materialization contract across at least two backend
  personalities or scenarios.
- Integration: staging failure behavior where practical.
- E2E: not required.
- Opt-in: none unless backend selected later.

Design impact:

- Extends Stage 15 backend contracts from metadata/check/lookup into payload
  operations.

Future compatibility:

- Must not overfit to one provider shape; fake coverage must pressure-test
  both object-store-like and tracking-system-like behavior.

Alternatives rejected:

- Implementing a real provider to prove genericity before a concrete backend
  need exists.
- Provider-specific handler methods or bundle fields in core.

Debt introduced:

- Fake-only validation may miss first-provider needs. Revisit when a concrete
  backend is selected or fake scenarios cannot share one handler/result shape.

Reviewability:

- Keep fake remote behavior isolated from bundle and CLI changes.

### Phase 4 - Bundle, Import, Catalog, And Preflight Integration

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
- Bundle schema remains provider-neutral. If landed Stage 15 exchange records
  cannot carry operation evidence clearly through extension fields, the
  implementation plan must choose a narrow schema revision after the Stage 15
  recheck.

Test expectations:

- Package: no import side effects.
- Unit: run exchange and diagnostics.
- Contract: bundle/export/import compatibility, metadata-only default,
  unsupported-materialization diagnostics, and operation-evidence projection.
- Integration: fake-backend explicit materialization workflow.
- E2E: CLI only if confirmed.
- Opt-in: none unless backend selected later.

Design impact:

- Changes user-visible exchange and diagnostics behavior.

Future compatibility:

- Stage 17/18 can consume local materialization facts; Stage 19/20 can consume
  operation/staging records.

Alternatives rejected:

- Implicit downloads during export/import.
- Provider-specific bundle schema.
- Moving backend transfer semantics into `loom.runs`.

Debt introduced:

- Exact extension-field versus narrow schema revision choice remains a Phase 4
  implementation decision over the landed Stage 15 exchange records.

Reviewability:

- Keep metadata-only compatibility tests central.

### Phase 5 - No-Backend Finalization And User-Facing Handles

Goal:

- Finalize docs/examples proving the fake-backend-first contract, explicitly
  record the no-backend decision, and add public API or narrow CLI handles for
  frequent user workflows plus structured unsupported/NotImplemented results
  for unimplemented backend paths.

Scope:

- No-backend docs, validation hardening, package/import checks, API-level
  unsupported handles, and narrow CLI only for frequent expected workflows.

Out of scope:

- Additional backend families or broad provider parity.

Acceptance criteria:

- Default install remains dependency-light. The implementation plan explicitly
  skips real backend implementation until a concrete need exists. Unsupported
  real-backend paths fail clearly through stable public results.

Test expectations:

- Package: optional dependency isolation.
- Unit: unsupported/no-backend handles and docs/examples helpers.
- Contract: fake backend contract, unsupported real-backend handle behavior,
  and no optional SDK imports.
- Integration: no real backend integration unless a concrete backend is later
  selected before phase implementation begins.
- E2E: not default.
- Opt-in: selected backend only, if any.

Design impact:

- Satisfies the roadmap backend-selection exit criterion.

Future compatibility:

- First real backend should pressure-test genericity without becoming a
  template for all providers; current Stage 16 records the no-backend decision
  and the revisit trigger.

Alternatives rejected:

- Selecting S3, GCS, Azure, MLflow, DVC, W&B, HTTP, or another concrete
  provider without a downstream need.
- Adding provider SDKs or plugin target imports to the default install.

Debt introduced:

- No real-provider proof exists in Stage 16. Accepted because fake backend
  shape pressure tests are required and optional dependencies remain isolated.

Reviewability:

- Keep provider-specific behavior isolated from core fake backend contract.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | V16 roadmap bullets map to confirmed FR-1 through FR-9 and confirmed behavior baseline | pass | Carry into implementation-plan drafting |
| Requirement-to-design traceability | Proposed implementation shape and confirmed DAQ-1 through DAQ-9 map confirmed requirements to design decisions | pass | Carry design-safety guardrails into examples, validation, and phase shaping |
| Design-safety review completed | Review passed on 2026-05-15 with DSR-1 through DSR-7 recorded | pass | No return-to-planning discussion required unless a revisit trigger fires |
| Future-roadmap impact considered | Design-safety review records v17/v18 staging, v19 reliability, v20 cleanup, and future backend adapter touchpoints | pass | Preserve derived/non-authoritative staging boundary in phase plans |
| Generic interface, adapter, and protocol flexibility considered | Design-safety review confirms `loom.operations` shared value objects plus store-owned materialization handlers, with protocols kept separate; Stage 15 source contracts are rechecked | pass | Carry landed Stage 15 names into implementation-plan drafting |
| Example-to-validation traceability | Examples and validation matrix finalized after design-safety review, including fake-backend shape pressure tests, no-network defaults, import-boundary checks, copy-only behavior, metadata-only bundle defaults, and structured unsupported results | pass | Carry validation obligations into implementation-plan quality gate |
| Phase-shaping readiness | Five-phase sketch confirmed with shared operation/evidence contracts first, local copy records second, fake backend materialization third, bundle/preflight integration fourth, and no-backend/user-facing handles fifth | pass | Carry phase boundaries into implementation-plan drafting |
| Unresolved blocked or needs-discussion functionality or design decisions | No unresolved functionality or design decisions remain after design-safety review and Stage 15 landed-contract recheck | pass | Reopen only if implementation finds a real conflict or a concrete backend need appears |

Readiness result:

- Status: ready for implementation-plan drafting
- Implementation-plan drafting blockers: none
- Accepted risks:
  - Stage 16 skips a real backend family, so genericity depends on strong fake
    backend pressure tests until a concrete backend need appears.
  - `loom.operations` becomes a public import path and must stay narrow,
    import-light, plain-data-only, and free of subsystem ownership.
  - No-backend unsupported handles must stay explicit and future-backend-ready.
- Assumptions to carry forward:
  - Metadata-only defaults remain mandatory unless explicitly reopened.
  - Fake-backend-first core coverage is the default validation strategy.
  - Stage 15 landed names and exchange fields are the implementation-plan
    baseline after the 2026-05-15 recheck.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions about the Stage 16 briefing before capability triage starts? | Roadmap framing | User confirmed briefing and defaults without clarifying questions on 2026-05-15 | closed |
| What should Stage 16 optimize for: generic materialization contracts, a concrete backend need, bundle portability, local container/HPC staging, or another priority? | User intent and phase shape | Bundle export/import with requested payload materialization is the primary example | closed |
| Should Stage 16 select one optional real backend family, or explicitly skip real backend implementation until a concrete need appears? | Scope, dependencies, testing, packaging | Skip real backend by default | closed |
| Should local materialization default to copy-only, or allow an explicit link mode in the first implementation plan? | Local behavior and provenance | Copy-only in Stage 16 with future policy handles | closed |
| Should user-facing CLI work be included in Stage 16, or should this stage expose Python/API behavior plus preflight/bundle options first? | Public surface and phase shape | Narrow CLI only for frequent expected workflows; otherwise public API plus NotImplemented/unsupported handles | closed |
| Should publish of immutable outputs be treated as an explicit operation that records evidence but does not participate in global planner cache/reuse? | Publish semantics, operation records, and future cache/reuse boundaries | Explicit, immutable, capability-checked publish with checksum evidence when possible; no automatic planner global-cache lookup, partial-stage reuse, remote catalog behavior, or credential lifecycle management | closed |
| Should materialization readiness checks stay cheap by default with opt-in network, credential, payload-read, and checksum probes? | Preflight behavior and validation scope | Cheap by default; expensive probes only when requested for a selected materialization operation | closed |
| Should shared operation/evidence primitives live in a new import-light top-level `loom.operations` module/package? | Public API placement, import boundaries, shared protocol reuse, and Phase 1 scope | Yes: use `loom.operations` for generic value objects and projection helpers; keep subsystem protocols separate | closed |

## Handoff Notes

Implementation-plan draft inputs:

- Ready. Design-safety review, examples/validation strategy, phase shaping,
  and the Stage 15 backend/capability/preflight/exchange landed-contract
  recheck are complete.

Design-safety review result:

- Passed on 2026-05-15 with DSR-1 through DSR-7 recorded. No Stage 16
  design-shape blocker remains, and the Stage 15 landed-contract readiness
  blocker has been resolved.

Validation and phase-shaping inputs:

- Confirmed after design-safety review. Validation must include no-network
  defaults, import-boundary checks, structured unsupported results, copy-only
  local materialization, metadata-only bundle defaults, and fake backend shape
  pressure tests. Phase shaping must keep shared operation primitives before
  materialization, and bundle/preflight integration after materialization
  records and fake backend behavior.

Plan-quality-gate risks:

- Stage 15 dependency may still need narrow adaptation if implementation finds
  an exchange field cannot represent generic operation evidence clearly.
- Backend implementation is currently skipped, but a late concrete backend
  selection would expand packaging and validation scope.
- Bundle/import/export materialization could accidentally become implicit
  payload movement if defaults are not locked.
- Staging/cache records could be mistaken for authoritative artifact truth if
  not modeled carefully.
- `loom.operations` could become too broad if Phase 1 moves subsystem
  protocols rather than only shared value objects and projections.
- Fake-backend-only validation could miss real-provider needs unless fake
  handlers pressure-test both object-store-style and tracking-system-style
  behavior.

Assumptions to carry forward:

- Keep Loom domain-neutral.
- Preserve metadata-only defaults.
- Keep optional dependencies isolated.
- Use fake backend coverage by default.
- Use the landed Stage 15 backend, capability, preflight, and exchange
  contracts as the baseline for implementation planning.

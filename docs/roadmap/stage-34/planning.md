# Roadmap Stage 34 Planning: Singular Run Inspection

Status: approved
Roadmap stage: 34
Evidence tree: `/home/can134/work/active/loom` at
`fd5543b1dd75dd3e78a2b7b5bb9ebc73535fac6b`; relevant dirty paths:
`docs/roadmap/stage-34/` and the Stage 32 dependency-alignment plan files
Planning route: expanded; this stage introduces a public serialized read model,
an authenticated remote trust boundary, and a non-atomic join across coordinator,
authority, scheduler, and filesystem owners
Current gate: passed; planning approved 2026-08-30
Planning blockers: none
Implementation prerequisite: Stage 32 Phase 2 merged

This file is current authoritative planning state, not an implementation
transcript. The complete packet was approved on 2026-08-30. Product
implementation begins only through the phase workflow after Stage 32 Phase 2
is remotely merged.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Existing authority, diagnostics, targeted managed-status, Unix, and mTLS seams are sufficient inputs; Stage 32 supplies service-less queue/Slurm facts. | None. | Reuse their owners. |
| Functionality | One known `run_uri`; one typed, bounded, owner-labelled result; metadata/locations only; dedicated read-only mTLS role; fixed allowlist; additive `loom inspect-run` command and Python query API. | None. | Preserve FQ-1 through FQ-6. |
| Design | Diagnostics owns one strict projection shared by direct, owner-only Unix, and authenticated HTTP. Bounds, authorization, source selection, imports, and exact Stage 32 lookup are locked. | None. | Preserve DQ-1 through DQ-5. |
| Validation | Source mode, owner availability, authorization, projection safety, and bounds are the causal dimensions. | None. | Use the focused matrix below. |
| Detailed plan | The manifest links two vertical phase plans: core projection/local paths, then authenticated HTTP. | None. | Preserve phase contracts. |
| Approval | Complete planning packet approved 2026-08-30. | None. | Begin Phase 1 only after Stage 32 Phase 2 merges. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| Stage 32 plans | Record Stage 34 as a one-run local/Unix/HTTP follow-up returning status, freshness, and locations, not bytes. Queue, authority, and Slurm manifests retain ownership. | Candidate boundary and prerequisite. | FR-1..FR-6, FR-10, FR-11 |
| Stage 29 Phase 12 | Supplies bounded summary/list and targeted revision-aware detail/wait instead of unbounded global detail. | Exact managed read and sequencing. | FR-1, FR-3, FR-8 |
| Diagnostics, store read models, and feature docs | Local commands expose authority lifecycle, artifact refs, and log paths, but their rich messages, metadata, and separate result types are not a safe remote contract. Authority remains lifecycle truth; locations do not imply reachability. | Strict projection and ownership. | FR-2..FR-5, FR-9, FR-10 |
| Local daemon and Unix transport | Managed status already joins operational owners; the socket authenticates the peer UID. Current detailed status remains global and mapping-shaped. | Join reuse and direct/Unix paths. | FR-2, FR-3, FR-6, FR-8 |
| Agent-session HTTP transport and policy | Existing TLS 1.2+ mTLS, fingerprint policy, role checks, bounded JSON, and safe errors can be reused. Existing `client` credentials can mutate. | Dedicated read-only authorization. | FR-6..FR-9 |

- Outcome: inspect one known run through Python/direct, owner-only Unix, or
  authenticated HTTP and receive the same safe machine model. Service-less HPC
  users may invoke JSON through site-owned SSH; Loom does not implement SSH.
- Included: a fixed typed projection, partial owner facts, bounded locations,
  human/JSON CLI output, a read-only HTTP operation, and local/fake validation.
- Excluded: listing/search/history, dashboards, streaming, mutation, SSH,
  content transfer, remote stores, URL signing, filesystem browsing, HA,
  identity federation, and tenancy.
- New durable surfaces are limited to the public query types/API, shared v1 wire
  shape, protected client/policy configuration, and CLI v1 envelope. No existing
  owner or run-directory schema changes except Stage 32's accepted item reference.

## Minimum Useful Change

- Query one exact `run_uri` for safe lifecycle/operation axes, freshness, stage
  progress, and artifact/log locations in one bounded typed response.
- Project existing authority, Stage 29 targeted admission, Stage 32 queue/Slurm,
  and local materialization facts through the existing socket and mTLS stack.
- A new surface is necessary because local diagnostics omit managed execution
  axes while current coordinator detail is global, mapping-shaped, and not a
  least-privilege public contract.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Accept one canonical non-empty `run_uri` and inspect only that run. Return its queue/admission identities when present. | No enumeration, query language, wildcard, or filesystem search. | Stage 29 exact admission read; Stage 32 durable run-to-item reference. | Known, missing, malformed, and mismatched identities. | locked |
| FR-2 | Return one frozen typed result with strict plain-data serialization and an independently versioned wire/CLI schema. Direct, Unix, and HTTP adapters deserialize the same model. | Do not expose raw owner rows or make CLI tables the machine contract. | Existing serialization and typed transport patterns. | Round trip, unknown-field rejection, adapter parity, package import. | locked |
| FR-3 | Preserve distinct admission, authoritative lifecycle, scheduling/route, assignment/execution, external-scheduler, transfer/result, cancellation, materialization, and service-health facts where applicable. Each present axis identifies its owner, revision, observation time, freshness, and safe code; the result has a join `as_of`. | Missing axes are explicit; no globally atomic claim and no scheduler-to-lifecycle inference. | Stage 29 joined status; Stage 32 owner contracts. | Managed, service-less, direct-only, unavailable-owner, and disagreement fixtures. | locked |
| FR-4 | Project authoritative run and per-stage lifecycle status, current attempt where available, and stable reason codes. Authority terminal truth wins the summary precedence. | Exclude arbitrary exception text, traceback, config, provenance payloads, commands, environments, fences, receipts, and provider-private evidence. | `AuthoritativeRunSnapshot`. | Safe-field allowlist and terminal/disagreement tests. | locked |
| FR-5 | Return bounded artifact and log location records with logical identity, URI/path representation, source/availability, and checksum/type facts where safe. | No payload bytes, log content/tail/follow, codec loading, checksum scan, directory listing, presigned URL, or claim that a remote client can reach a coordinator-local path. | `ArtifactRef`; local materialization path helpers. | No-read fake stores, bounded cardinality, redaction, local/external URI cases. | locked |
| FR-6 | Support direct construction, owner-only Unix socket, and authenticated HTTP with identical observable result semantics. Document SSH only as an operator invocation of the local JSON CLI for service-less deployments. | No second HTTP server framework, SSH library/client, or compute-node callback. | Stage 29 transports and Stage 32 CLI. | Direct/Unix/HTTP contract tests and documented SSH command seam. | locked |
| FR-7 | Make remote query authorization read-only and independent of submit, cancel, recovery, agent, bootstrap, and authority credentials. Recheck current policy on every request. | No bearer token shortcut, request-body principal, or broad authority client exposure. | Stage 29 mTLS policy/authorizer. | Wrong role/cert/service/run operation and revocation tests with zero mutation. | locked |
| FR-8 | Bound request size, response cardinality, query work, and serialization. Managed queries use exact Stage 29 reads; service-less queries follow Stage 32's durable run-to-item reference to an exact item read. | Never load global history or scan queue rows. | Stage 29 Phase 12; Stage 32 Phase 2. | Thousands-of-runs fixture, caps, and truncation counts. | locked |
| FR-9 | Return typed not-found, unauthorized, invalid, unavailable, degraded, and truncated outcomes with safe diagnostics. A known run may return partial owner axes; an unavailable owner must not be silently omitted or upgraded. | No internal path/exception leakage in errors and no local fallback that bypasses the selected coordinator boundary. | Existing safe transport errors and state-source vocabulary. | Failure matrix and secret-bearing fake exceptions. | locked |
| FR-10 | Add `loom inspect-run RUN_URI` with concise text and `loom.cli.inspect_run.v1` JSON. Require exactly one of direct, Unix endpoint, or protected HTTP config; never fall back. Existing commands remain unchanged. | No project-code import, inferred endpoint, secrets in argv/output, or `loom status.v3` change. | Existing CLI/config patterns. | Parser, envelope, subprocess, and import-safety tests. | locked |
| FR-11 | Preserve status, queue, authority, artifact, and log owners and start only after Stage 32 Phase 2. | No new database/service or owner-schema rewrite. | Predecessor merge and durable run-to-item reference. | Diff/contract review and full gates. | locked |
| FR-12 | Document managed local, authenticated remote, and service-less SSH journeys, including freshness, non-atomicity, inaccessible locations, and content-transfer limits. | Examples use abstract hosts and no real credentials. | Feature and deployment docs. | Documentation assertions and manual setup review. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-5, FR-6, FR-12 | Return refs/locations and availability, never artifact/log bytes. | Preserves `ArtifactRef` semantics and avoids a relay owner. | Content needs a shared mount, site tooling, or later capability. | locked; maintainer approved 2026-08-30 |
| FQ-2 | FR-6, FR-7, FR-9 | Reuse mTLS with a dedicated read-only `query` role for runs admitted to that coordinator. | Existing client credentials can mutate. | Adds one policy role and hard-cut capability. | locked; maintainer approved 2026-08-30 |
| FQ-3 | FR-3..FR-5, FR-9 | Use fixed axes and allowlisted stage/location records; label paths coordinator-local/shared-unknown and exclude arbitrary messages/metadata. | Prevents leakage and false reachability claims. | Less detail than local forensic commands. | locked; maintainer approved 2026-08-30 |
| FQ-4 | FR-2, FR-6, FR-10 | Add `loom inspect-run RUN_URI` and typed Python API; preserve existing commands. | A separate `loom.cli.inspect_run.v1` avoids schema drift. | One additional documented command. | locked; maintainer approved 2026-08-30 |
| FQ-5 | FR-1 | `run_uri` is the sole input identity; return queue/admission IDs as context. | Existing public and authority identity. | Queue-only callers first resolve their receipt. | repo-resolved |
| FQ-6 | FR-1, FR-8 | Exclude list/search/history. | Stage 29 owns bounded admission listing. | No remote discovery UI. | repo-resolved |

## Behavior Baseline

- One run URI and one explicit source yield an observation boundary, summary,
  owner axes, stages, and bounded locations. Text projects the typed result;
  JSON is its versioned serialization.
- Not-found is typed; denial returns no run facts; unreadable owners remain
  explicit; truncation reports counts; selected coordinators never fall back.
- Queries write no owner or cursor state. Revisions and `as_of` describe the
  non-atomic snapshot, which may change as owners progress.

## Minimum Design

- Modules and ownership: `loom.diagnostics.run_inspection` owns immutable result,
  axis, stage, location, truncation, and safe-failure models plus the projection
  service. Queue and store modules keep their existing facts and expose only
  exact read seams. Socket/HTTP infrastructure receives an injected plain-data
  query callable, so lower layers never import diagnostics. `loom.cli` only
  selects a source and formats the typed result; `loom.diagnostics` lazily
  exports the public values and `inspect_run` API.
- Data flow: validate one canonical absolute `file:///` run URI, select exactly
  one source, resolve the managed admission or Stage 32 durable run-to-item
  reference, read only that run's owners, project the fixed allowlist, sort and
  cap repeated records, then serialize. Unix and HTTP never fall back to local
  files. Direct service-less mode may receive an existing queue config; without
  one, its queue axis is explicitly unavailable rather than discovered.
- Fixed result contract: schema version 1 contains `run_uri`, join `as_of`, a
  derived summary, named admission/lifecycle/scheduling/assignment/external-
  scheduler/transfer-result/cancellation/materialization/service-health axes,
  bounded stage and location records, and truncation counts. Every present axis
  has owner, availability, state, revision, observed time, freshness, and safe
  code; there is no free-form facts field. Locations contain logical identity,
  URI, kind, recorded availability, safe type/checksum facts, and reachability
  (`coordinator_local`, `shared_unknown`, or `external`).
- Bounds and failures: a request URI is at most 4 KiB, every repeated collection
  returns at most 256 deterministically ordered records, and encoded success is
  at most 1 MiB. Omitted records report exact total/returned counts. Invalid,
  not-found, unauthorized, unavailable, and internal failures use closed codes;
  authorization denial contains no run facts. Degraded/truncated known runs are
  successful typed results. Projection may stat an owner-derived path but never
  read payload/log bytes, load codecs, compute checksums, or enumerate a
  directory.
- Trust and compatibility: HTTP adds policy role `query`, capability
  `run-inspection-v1`, and `/v1/query/inspect_run` on the existing mTLS server.
  Policy is checked before owner access and on every request; only runs admitted
  to that coordinator are in scope. `loom inspect-run` requires exactly one of
  `--direct`, `--endpoint SOCKET`, or `--remote-config CONFIG`; `--queue-config`
  is direct-only. The protected `loom.run-inspection-client` v1 config carries
  HTTPS URL and CA/certificate/key paths. CLI JSON uses
  `loom.cli.inspect_run.v1`; existing commands and schemas are unchanged.
- Private discretion: concrete helper/class names, query SQL, callback wiring,
  text layout, and truncation implementation may simplify while preserving the
  fixed field set, limits, source behavior, and import direction. No new
  persistence, service process, optional dependency, plugin activation, or
  project-stage import is allowed.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| One typed singular-run projection | Current direct/CLI diagnostics and managed status do not share a safe public model. | Return the current raw daemon mapping. | keep |
| Targeted direct/Unix/HTTP adapters | Current consumer needs same-host and authenticated remote inspection. | Parse separate commands. | keep |
| Read-only authorization capability | Existing remote client role can mutate. | Share client credentials. | keep; dedicated mTLS query role |
| Location records | Current consumer needs to find artifacts/logs without byte relay. | Return counts only. | keep; typed allowlist |
| New persistence, remote store, byte relay, list/search, streaming, UI | No current requirement. | Several new owners/protocols. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-2..FR-5 | Diagnostics owns one strict typed projection; lower owners expose targeted facts and transports accept an injected plain-data callable. | Preserves documented import direction and one projection owner. | Composition adds one explicit callback. | repo-resolved |
| DQ-2 | FR-2, FR-8, FR-9 | Use the closed v1 result/error shapes and fixed 4-KiB/256-record/1-MiB limits above. | Existing socket limit is 1 MiB; explicit counts keep truncation truthful. | Very large runs require local forensic commands. | repo-resolved |
| DQ-3 | FR-1, FR-3, FR-8, FR-11 | Retain the canonical `queue_item_id` in Stage 32's run-local operation/manifest, verify it against the dispatch handle, then read the row by primary key. | Avoids queue scans and another index/schema cut. | Adds one durable cross-owner reference that must agree. | locked; maintainer approved 2026-08-30 |
| DQ-4 | FR-6, FR-7, FR-9 | Add only the `query` role/operation to the existing socket/mTLS application composition and authorize before reads. | Reuses peer-UID/TLS/current-policy controls. | Old servers report the capability unsupported; no fallback. | locked by FQ-2 |
| DQ-5 | FR-6, FR-10, FR-12 | Use the exact CLI selectors, protected HTTP client config, API, and schema named above. | Explicit source choice prevents trust-boundary fallback and preserves current commands. | Adds one protected config kind. | locked by FQ-4 |

## Expanded Design Review

Manager-local removal-first review rejected raw mappings, mutation credentials,
global scans, content relay, another server, and upward imports. The allowlist,
query role, exact references, injected callable, and existing transports close
those risks. Phase 2 retains expanded implementation/review treatment.

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Managed mixed owners | Scheduler facts could overwrite lifecycle truth. | Authority plus coordinator join. | Disagreement, unavailable owner, revisions, summary precedence. | planned |
| Service-less Slurm | Query could invent managed facts or lose queue identity. | Stage 32 run reference, queue item, authority, manifest. | Direct query after driver exit for both Slurm modes. | planned |
| Source parity | Adapters could drift or fall back. | Projection model and selected adapter. | Same fixture through direct/Unix/HTTP plus unavailable selected source. | planned |
| Remote query credential | Read credential could mutate or enumerate. | mTLS/current authorizer. | Query success; client/operator/cert/capability/revocation denial before read. | planned |
| Location-only allowlist | Projection could read bytes or leak private data. | Projection boundary. | Read-spy stores, secret-bearing fakes, no-content/unknown-field checks. | planned |
| Population and response bounds | One query could scan history or overfill transport. | Exact owner reads and serializer. | 2,000 unrelated runs, query-count sentinel, 257-record truncation, 1-MiB cap. | planned |
| CLI compatibility | New surface could alter existing commands/imports. | CLI presentation. | Direct/Unix/HTTP subprocess JSON v1; unchanged status/log/artifact schemas. | planned |

Causal interactions requiring combined coverage:

- Authorization and projection interact because denial must occur before any
  owner read and safe fields must remain safe over HTTP.
- Owner availability and summary precedence interact because a scheduler fact
  cannot become lifecycle truth when authority is unavailable.
- Source mode and location labelling interact because the same `file://`
  location may be locally usable, shared, or remote-inaccessible without
  changing artifact identity.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Singular run inspection core | Python API and `loom inspect-run` work through direct and owner-only Unix sources for managed and service-less runs. | Typed projection, exact reads, socket operation, direct/Unix CLI; no HTTP policy/client. | Stage 32 Phase 2 merged with the approved run-to-item reference. | Allowlist/bounds, mixed-owner and service-less journeys, socket parity, CLI compatibility. | pending |
| 2. Authenticated run inspection | The same command/model works through a dedicated read-only mTLS query credential and documented remote journey. | Query policy/dispatch/client config, HTTP adapter, security/parity tests and final docs; no mutation or bytes. | Phase 1 merged. | Auth-before-read, role/revocation/capability failures, three-source parity, full gates. | pending |

Two phases isolate the stable projection and useful local/SSH path from the
remote trust boundary without creating a model-only or transport-only PR.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FQ-1 through FQ-6 are locked. | pass |
| Minimum design justified | Projection, bounds, adapters, auth, compatibility, and exact Stage 32 lookup are locked. | pass |
| Complexity delta proportionate | New model/role/config reuse existing owners and transports; data transfer and new services remain deferred. | pass |
| Contracts and private discretion clear | Fixed schemas, limits, trust/source behavior, ownership, and private wiring discretion are explicit. | pass |
| Invariant ownership and validation proportionate | Focused cases cover each boundary and only three causal interactions combine dimensions. | pass |
| Phases vertical and reviewable | Two consumer-visible verticals isolate the remote trust change. | pass |
| No unresolved blocker | No product or design blocker remains. | pass |

Gate result: all planning gates pass; the maintainer approved the complete
packet on 2026-08-30.
Accepted risks: snapshots are non-atomic, huge runs truncate without paging,
location reachability is labelled rather than proven, and real site TLS/Slurm
policy remains operator-validated. Revisit on a paging, payload, tenant, or
unresolvable Stage 32 reference requirement.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Canonical query identity | `run_uri`; queue/admission identities are returned context. | Existing public and authority identity. | A supported run exists without a stable run URI. |
| Run listing/search | Deferred. | No current consumer; Stage 29 already owns bounded admission listing. | A concrete remote discovery consumer. |
| Artifact/log content | Deferred; locations only. | Retrieval adds authorization, I/O limits, and delivery ownership. | Accepted retrieval consumer and boundary. |
| Remote query credential | Dedicated read-only mTLS role for coordinator-admitted runs. | Least privilege; current client credentials mutate. | Cross-coordinator or tenant consumer. |
| SSH | Loom supplies no SSH client or tunnel. | Site tooling already owns host authentication and command execution. | A concrete supported deployment cannot invoke the local CLI through site tools. |
| Public projection/paths | Fixed allowlist and typed reachability; no arbitrary metadata, messages, or translation. | Prevent leakage and false claims. | Concrete safe-field or mapping need. |
| Streaming/dashboard/metrics | Deferred. | Singular snapshot is sufficient. | Live consumer and retention/delivery contract. |

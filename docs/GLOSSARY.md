# Loom glossary and vocabulary guide

This file standardizes repository language across code, docs, tests, examples,
and contributor guidance.

It is both descriptive and normative:

- Descriptive: it summarizes vocabulary that is already backed by the public
  package surface, feature specs, and contract tests.
- Normative: it states the preferred wording for new changes when nearby terms
  could be conflated.

This guide is written for contributors first, but maintainers and downstream
users can also use it as a quick map to stable repository terms.

## How to use this file

- When a row names a concrete exported API such as `ArtifactRef` or `RunStore`,
  use that exact spelling when documenting, reviewing, or testing the contract.
- Uncapitalized prose is fine when it preserves the same distinction as the
  canonical term.
- If a feature spec, public type, or contract test disagrees with this file,
  treat the code-backed contract as authoritative and update this glossary.
- The "Distinguish from / avoid" column calls out discouraged aliases,
  overloaded wording, or terms that need qualification.

## Repository and workflow terms

| Term | Preferred meaning in this repository | Distinguish from / avoid |
| --- | --- | --- |
| feature spec | A contract-focused design document under `docs/features/` that defines subsystem behavior and long-lived vocabulary. | Do not treat feature specs as disposable notes when they define public terms. |
| implementation plan | A roadmap-level plan under `docs/roadmap/stage-<id>/` that sequences and scopes phases. | Not the same as a phase execution plan. |
| phase execution plan | A scoped implementation artifact under `docs/roadmap/stage-<id>/phases/` for one phase of work. | Not a product spec or public API reference. |
| contract test | A test under `tests/contracts/` that locks public or cross-subsystem behavior. | Distinguish from unit tests and package-surface import tests. |

## Core model and identity terms

| Term | Preferred meaning in this repository | Distinguish from / avoid |
| --- | --- | --- |
| `ResourceRef` | A serializable handle to an input or external resource, identified by `uri` and `resource_type`, with optional `codec_key`, `checksum`, and metadata. | Use for resources that exist independently of a run. Do not describe produced stage outputs as `ResourceRef`s when they are `ArtifactRef`s. |
| `ArtifactRef` | Serializable metadata for a produced pipeline output, including `artifact_id`, `uri`, `artifact_type`, optional `codec_key`, optional `checksum`, optional `fingerprint`, optional `producer_stage`, and metadata. | Use for stage outputs and persisted artifact indexes. Avoid using "artifact" when you mean the bytes on disk or a local path only. |
| `ArtifactAddress` | The cross-run identity pair `(run_uri, artifact_id)`. | Prefer this when one artifact must be named within one run. Do not overload `ArtifactRef` for that role. |
| record | A generic indexed unit of data in the core model. | Keep domain meaning out of the noun in generic `loom` code. Qualify it in downstream packages if needed. |
| manifest | A collection-oriented record surface in the core model or a manifest-like metadata bundle. | Qualify the exact kind when multiple manifests are in scope: `recipe manifest`, `composition manifest`, `offline evidence manifest`, `ManifestView`, or `InMemoryManifest`. |
| `ManifestView` | A lightweight filtered or projection-oriented view over manifest contents. | Distinguish from persisted manifest storage or manifest-like config artifacts. |
| checksum | A digest of persisted bytes or text used for integrity and corruption checks. | Prefer for content verification. Avoid using it as a synonym for stage identity or reuse policy. |
| fingerprint | A stable digest over structured inputs or metadata used for identity, comparison, resume, and provenance. | Prefer for structured identity and reuse. Avoid using it as a synonym for a raw file hash. |
| `run_uri` | The public, protocol, and persisted identifier for a run. | Prefer `run_uri` across code, docs, tests, and examples. Avoid `run_id` except when discussing the historical migration away from it. |

## Configuration and composition terms

| Term | Preferred meaning in this repository | Distinguish from / avoid |
| --- | --- | --- |
| authored config | Trusted project configuration as written by users, examples, or fixtures. | Distinguish from resolved/composed config and from untrusted input. `loom` treats authored config as trusted project code. |
| `ComposedConfig` / composed config | The resolved result returned by `weave.compose_config(...)`. | Do not call this a plan, manifest, or pipeline run. It is configuration output. |
| `ConfigCompositionInspection` / config composition inspection | A richer composition result that retains unresolved, resolved, and redacted views plus provenance, recipe manifest, source artifacts, fingerprint records, and raw source snapshot metadata. | Prefer this when docs or tests discuss composition analysis rather than only the final composed config. |
| `_target_` block | The low-level importlib construction shape used to instantiate configured Python objects. | Do not call `_target_` blocks recipes. Recipes expand into `_target_` graphs. |
| recipe | A named config expansion mechanism that rewrites authored config into explicit object graphs. | Use for configuration reuse and authoring convenience. It is not a stage, executor, plugin, or runtime backend. |
| recipe manifest | The persisted record of recipe expansion steps. | Distinguish from generic manifests, provenance documents, and artifact indexes. |
| target check | An opt-in readiness/import check for `_target_` blocks after static validation succeeds. | Do not imply this is a sandbox or a safe path for untrusted config. |

## Pipeline, execution, and storage terms

| Term | Preferred meaning in this repository | Distinguish from / avoid |
| --- | --- | --- |
| pipeline | A validated, artifact-based execution graph derived from config. | Distinguish from authored config and from one concrete run. |
| stage | A named node in the pipeline graph with declared inputs, outputs, runtime/resource requests, and behavior implemented by project code. | Avoid using "task" or "job" as the generic top-level noun unless backend-specific semantics are intended. |
| planner action | A planned decision such as `RUN`, `REUSE`, `SKIP`, or `BLOCKED`. | Distinguish from persisted lifecycle status. |
| status | A persisted run or stage lifecycle state such as `CREATED`, `PLANNED`, `RUNNING`, `SUBMITTED`, `SUCCEEDED`, `FAILED`, `BLOCKED`, `SKIPPED`, `STALE`, `CANCELLED`, or `INTERRUPTED`. | Do not use status names to mean planner actions. |
| run | One execution or planned execution instance of a pipeline, identified by `run_uri`. | Distinguish from a run collection and from the run catalog. |
| executor | The component that runs one stage through a backend such as local Python, subprocess, or a future scheduler adapter. | Distinguish from `PipelineRunner`, which coordinates the whole run. |
| backend | A concrete execution or authority implementation detail behind a public contract. | Use when discussing capability or deployment shape. Avoid using it as a synonym for the whole public API surface. |
| `RunStore` | The current public authority-backed run lifecycle surface exported from `loom.pipeline.stores`. | Prefer when referring to the public run lifecycle contract. Do not use it for the older path-shaped local aggregate by default. |
| `StageStore` | The run-scoped stage lifecycle surface obtained from `RunStore.stage_store(...)`. | Distinguish from run-level APIs and from artifact materialization helpers. |
| `LocalRunStore` | The local filesystem implementation and materialization surface. | Use only when local path-based behavior matters. It is not the public authority `RunStore` contract. |
| `LegacyRunStore` | The older path-shaped aggregate retained during the store naming transition. | Use only for migration or compatibility discussion. Avoid using plain `RunStore` when this older surface is actually meant. |
| authority | The authoritative, backend-neutral source of run and stage lifecycle truth. | Distinguish from local materialized files, projections, and catalogs. |
| authority reference | The portable reference or configuration summary that lets commands and workers reconnect to the selected authority. | Distinguish from endpoint-only prose and from raw local state paths. |
| run collection | A directory containing many runs. | Distinguish from an individual run and from the derived catalog index. |
| run catalog | A rebuildable, derived index over a run collection. | Never describe it as the source of truth. The run store and authority remain authoritative. |
| provenance | Factual metadata about config, code, environment, command, inputs, outputs, fingerprints, and executor context. | Distinguish from policy. Provenance records facts; planner and resume logic decide how those facts are used. |
| authoritative read model | A backend-neutral materialized snapshot used to inspect authoritative run state. | Distinguish from raw backend implementation details and from the derived run catalog. |
| materialized ref | A file- or path-backed materialization observed on disk for an authoritative snapshot. | Use for projection or readback terminology, not as a synonym for authoritative lifecycle state. |

## Queue, scheduling, and agent terms

| Term | Preferred meaning in this repository | Distinguish from / avoid |
| --- | --- | --- |
| queue item / `queue_item_id` | One durable whole-run submission and its stable queue identity. | Not a pipeline stage, run URI, dispatch attempt, assignment, or operating-system process. |
| managed run admission | The coordinator's unique digest-bound record for one `(coordinator_id, run_uri)` and one execution owner. The durable root's stable `coordinator_id` is the namespace. It may be `PENDING_AUTHORITY` until exact owner/intent/operation-receipt reconciliation promotes it to `ACTIVE`. | Exact replay returns its current state; resume targets it. It is not a second run attempt, and changed intent/managed-versus-delegated ownership conflicts. Pending admission exposes no stage work. |
| resolved stage placement | The schema-versioned, immutable per-stage-attempt combination of an authored `ResourceRequest`, exact-stage refinements, hard constraints, soft preferences, target, and fallback policy used by managed scheduling. | Not a whole-run resource sum, coordinator assignment, or physical binding. |
| stage work / `stage_work_id` | The coordinator's identity-stable rebuildable scheduling projection for one exact prepared `(admission, run_uri, stage_name, attempt, readiness_generation)`, including readiness evidence and a resolved-placement fingerprint. | Not authority-owned stage lifecycle truth and not a queue item. Rebuild may change projection revision, never its referenced identity. |
| managed pool | A named scheduling, admission-policy, and authorization domain whose current capacity is contributed by authenticated agent offers. | Not a duplicated fixed coordinator capacity counter and not an external delegated scheduler partition. |
| coordinator | The application role that durably owns run admission, dependency reconciliation, scheduling snapshots, stage-work projections, assignments and grants, cancellation requests/control fan-out, reconciliation acknowledgements, and guarded recovery decisions. | It does not own effective authority cancellation, authoritative stage success/output truth, physical hardware binding, child processes, or agent-local configuration. |
| coordinator ID / process epoch | The stable coordinator-owner identity stored with one durable state root, and the rotating identity of one active process incarnation. | An assignment retains its issuer epoch. Do not use a fresh epoch as ownership transfer, HA leadership, or evidence that old work stopped. |
| agent | The durable configured machine-side logical participant that owns inventory/availability projection, request/input staging, local admission/binding, process supervision/containment, result retention, cleanup, and its journal/outbox. | Distinguish from one daemon process, durable agent session, network connection, or machine hostname. |
| agent session | One coordinator-issued durable incarnation of an agent. The agent persists its registration operation before send and the returned session before its first offer; it resumes only under its fencing and reconciliation rules. Clean rollover needs cooperative proof that the complete session-reference set is empty; non-empty/lost state needs guarded replacement. | Not a transient connection, credential, offer, or coordinator epoch. A new session cannot silently replace unresolved work. |
| assignment event sequence | The monotonic journal order of critical events for one assignment, each with a stable event ID and acknowledged only after contiguous durable coordinator persistence. | Not transport delivery order, HTTP success, or a global order across assignments. |
| agent offer | An expiring safe scheduling contribution bound to agent/session/configuration, inventory and availability revisions, pool, profile/capabilities, and coordinator-accepted receipt-time expiry. | Expiry removes future schedulability only; it is not process-death or job-failure evidence. A coordinator restart requires current-epoch reconciliation/re-offer before new delivery. |
| resource inventory | The versioned configured resources and attributes that trusted local agent policy and its enforcing/accounting provider permit Loom to manage. | Distinguish from current availability, best-effort host telemetry, and hardware merely detected but not safely allocated to Loom. It does not guarantee authored peak usage or prevent application OOM. |
| resource availability | The exact versioned net subset of inventory currently assignable for a new claim, including summaries of live claims already reflected in that baseline. | Not historical usage, a second subtraction of coordinator logical ownership, physical process truth, or capacity that remains valid after its revision changes. |
| capacity atom | One bounded agent-local capacity key and exact quantity exposed by a resource claim for generic coordinator reservation. | Not provider-private binding data, a host path/token, or a cluster-global resource without its own transaction owner. |
| resource claim | A deterministic, versioned, safe description of the resources selected from one agent for a candidate/assignment, including exact generic capacity atoms and separate bounded provider data. | Not an execution grant, physical device binding, authority lease, hidden provider-only consumption, or claim that combines several agents. |
| resource claim contract | The versioned inventory/claim data agreement negotiated between one planner implementation and one agent provider implementation for a resource kind. | Not either implementation's identity or permission for a compatible replacement to adopt old provider state. |
| placement candidate | One complete proposed managed-agent mapping of a ready stage work item's resolved resources and placement policy to resource claims on one agent. | Not a partial resource match, SLURM route, DAG-readiness decision, or committed assignment. |
| distributed pipeline execution | Different pipeline stages or independent branches execute on different agents while each individual stage remains wholly placed on one agent. | Not a distributed stage or gang scheduling. Stage 29 supports this form. |
| distributed stage | One logical stage attempt whose processes/resources span several agents or nodes. | Requires multi-agent identity, rendezvous, launch, failure, and result semantics; Stage 29 does not satisfy it by placing adjacent stages on different agents. |
| gang scheduling | All-or-none admission and coordinated launch of every resource participant required by one distributed stage. | Not a series of independent one-agent assignments or ordinary per-run concurrency. |
| preemption | Checkpointing/stopping or destructively terminating already-running work so its proven-released resources can serve other work. | Not priority or cancellation of unstarted work; a preference scorer cannot own it. |
| fair-share scheduling | Selection influenced by durable user/project/pool usage and entitlement accounting over time. | Not a machine/GPU preference, FIFO priority, or guaranteed by Stage 29 safe bypass. |
| general constraint solver | A placement engine that models variables, constraints, and an objective across several work items/resources and commonly returns a snapshot-bound batch. | Not Stage 29's complete bounded one-work candidate search and selection of one existing pair. Solver timeout must not be called infeasibility. |
| resource planner | A trusted explicitly composed pure scheduling implementation for one resource kind that resolves its request and proposes/validates bounded exact claims from safe availability data. | It does not observe or acquire physical hardware, mutate coordinator state, or own a stage lifecycle. |
| agent resource provider | A trusted machine-side implementation that observes one resource kind and prepares, reconciles, activates, aborts, and releases assignment-scoped physical claims. | Distinguish from the pure resource planner and from a wire claim; provider live tokens never leave the agent. |
| hard constraint | A built-in or explicitly registered versioned additive rule that may make a placement candidate ineligible after mandatory kernel checks. | It can only remove candidates; never use a soft score to override it or let it weaken security/resource truth. |
| soft preference | A built-in or explicitly registered versioned rule that gives a bounded integer score to candidates already proven feasible. | It cannot make a candidate invalid or valid; waiting for preference needs an explicit fallback policy. |
| scheduling kernel | The fixed pure placement owner that validates component manifests, generates bounded candidates, applies mandatory and additive hard checks, computes scores, validates a policy proposal, and returns data without mutation. | Not DAG orchestration, a replaceable lifecycle scheduler, coordinator assignment commit, or agent binding. |
| scheduling policy | A trusted explicitly composed pure strategy that selects one existing kernel-validated candidate ID or a typed wait from an immutable policy view. | It cannot create claims, bypass constraints, reserve resources, bind attempts, or launch work. |
| scheduling component descriptor | The stable component/contract/implementation identity, non-secret canonical configuration fingerprint, and supported data versions used to compose and reconstruct a planner, rule, scorer, policy, or agent provider. | Not a serialized callable, cryptographic attestation, secret hash, or substitute for a separately negotiated resource claim contract. |
| scheduling decision | The pure managed-agent scheduler result selecting at most one ready stage work item, one agent opportunity, and one complete candidate from an immutable snapshot. | Not DAG readiness, explicit SLURM route admission, or durable ownership; coordinator and authority must still revalidate and bind it. |
| assignment | The coordinator-owned durable handoff joining one exact prepared stage attempt to a closed target: either one agent/session/resource claim or one explicit SLURM profile/submission operation. | An offer, submission, or external job is not execution authority; distinguish assignment from queue dispatch, stage attempt, and process execution. |
| execution grant | The coordinator's durable authorization for one accepted assignment and process-execution identity to pass the agent start fence. | It is not a promise of exactly-once external effects. |
| execution fence | The authority-owned durable binding that permits results only from the current granted assignment until terminal commit or explicit fencing. | Not an expiring liveness lease; coordinator outage alone does not invalidate it. |
| coordinator authority view | The narrow authenticated least-privilege adapter through which the coordinator invokes per-run authority expected-state operations after durably recording intent and verifying service/workspace/generation, stable run-owner binding and, on generation change, one consistent receipt-aware authority-relevant continuity cut. | Not direct database access, a broad authority client handed to agents/workers, or trust in loopback location. A pristine empty authority is valid only when the coordinator has no authority-relevant retained admission/tombstone. |
| authority-relevant retained set | Every retained managed admission or safety tombstone that asserts or may still assert a per-run authority owner binding. | Delegated-only or historical records with no such binding are not included merely because they share coordinator storage. Age alone never removes safety evidence; removal needs a future acknowledged cross-owner run-forget contract. |
| work request | One outbound agent request for work bound to one exact current availability revision. | Not a daemon-local queue or prefetched backlog; at most one admission remains unresolved for that revision, but a fresh revision may expose disjoint remaining capacity while prior work executes. |
| transfer identity / authorization | The stable assignment-scoped identity and exact progress of one transfer, and the separate renewable short-lived permission ID/revision that gates byte operations. | Authorization expiry or coordinator restart must not erase transfer progress, release work, or create a second transfer. Exact replay resumes; conflicting content fails. |
| joined managed status | The coordinator-built non-atomic read model that preserves coordinator, authority, agent or bootstrap, external-scheduler, transfer/result, control, and health axes with each owner's revision, accepted receipt time, freshness, and a top-level join `as_of`. | Not one globally atomic lifecycle row. Remote clocks and external scheduler state are informational and never establish Loom lifecycle truth by themselves. |
| production role-state initialization | The explicit first-use operation that verifies an absent/empty local target and durably creates one coordinator or agent schema and stable role identity. Later starts are open-only. | Never treat a missing, corrupt, or identity-mismatched expected root as a fresh install; that is lost-state recovery. |
| coordinator accepted time | The coordinator-owned nondecreasing time, backed by a durable high-water, used for offer receipt/expiry, scheduling `as_of`, fallback, and status freshness. | Not an agent/authority timestamp or a policy extension. Detected local regression/out-of-policy jump degrades and pauses scheduling rather than extending stale capacity. |
| embedded managed composition | The command-lifetime composition of the same coordinator and local-agent application owners used by the daemon, backed by retained production role state. | Not an ephemeral/in-memory production owner. It routes to a compatible active owner or takes the same locks; it cannot mint a new identity around a held/conflicting root. |
| ready-stage delegation | The Stage 29 explicit handoff of one exact authority-ready attempt to one named SLURM profile, which retains node placement and allocation ownership while Loom retains run, fence, result, and dependency truth. | Not managed agent capacity, historical whole-run delegation, automatic fallback, or permission to submit before readiness. |
| SLURM profile | Protected site-owned configuration that authorizes and fingerprints one ready-stage SLURM route, including allowlisted resource/directive mapping, admission bounds, command/identity reconciliation, resident bootstrap, credential delivery, and data-path capabilities. | Authored work may name an allowed alias but cannot provide raw directives, commands, implementation code, or secrets. |
| SLURM submission operation | The stable coordinator-owned identity whose immutable intent and `SUBMITTING` state precede at most one automatic `sbatch` invocation and whose accepted/definitely-rejected/unknown outcome is durably reconciled. | Not the scheduler job ID, assignment, bootstrap incarnation, or execution fence. Unknown never licenses blind resubmission. |
| SLURM bootstrap | The restricted assignment-scoped process started by a ready-stage batch script to authenticate/reconcile the exact job, stage inputs, obtain the authority grant, invoke at most one execution-only worker root, and replay fenced result/output facts. | Not an agent, arbitrary worker queue, authored stage command, service credential holder, or direct authority client. |
| allocation-fed agent | A possible future Loom agent running inside an already-granted external allocation and publishing only that allocation's exact resources for its fenced lifetime. | Not permission to advertise unallocated scheduler nodes or double-publish a standalone machine resource. |

## Naming heuristics

- Prefer exact exported names when referring to a contract that appears in code
  or package tests.
- Use `run_uri` for run identity everywhere new work is written.
- Use checksum for persisted content integrity and fingerprint for structured
  identity or reuse.
- Use action for planner decisions and status for persisted lifecycle state.
- Use constraint for feasibility, preference for ranking, claim for selected
  scheduling resources, binding for agent-local physical acquisition, and grant
  for execution authority.
- Qualify agent identity, session, connection, offer/availability revision,
  assignment, dispatch attempt, and process execution; never collapse them into
  an ambiguous "job id" or "daemon id".
- Prefer `RunStore` and `StageStore` for public lifecycle APIs; spell
  `LocalRunStore` or `LegacyRunStore` explicitly when local-file or migration
  behavior is intended.
- Qualify overloaded nouns such as manifest, backend, service, snapshot, and
  reference with the owning subsystem when ambiguity is possible.
- Describe authority, run-store state, and authoritative read models as
  authoritative; describe catalogs, materialized files, and local projections as
  derived or projected.
- Keep domain-specific nouns such as dataset, model, metric, report, or
  checkpoint out of generic `loom` APIs unless they are clearly confined to
  downstream examples or project code.

## See also

- [README](../README.md)
- [`loom` specification](loom.md)
- [source-tree structure](structure.md)
- [core model spec](features/core-model.md)
- [config spec](features/config.md)
- [pipeline spec](features/pipeline.md)
- [state vocabulary spec](features/state.md)
- [artifact spec](features/artifacts.md)
- [run-store spec](features/run-store.md)
- [run-catalog spec](features/run-catalog.md)
- [public root API tests](../tests/package/test_public_api.py)
- [pipeline package API tests](../tests/package/test_pipeline_api.py)
- [config package API tests](../tests/package/test_config_api.py)
- [runs package API tests](../tests/package/test_runs_api.py)
- [recipe contract tests](../tests/contracts/test_recipe_contract.py)
- [authority run-store contract tests](../tests/contracts/test_run_store_authority_contract.py)
- [run-catalog contract tests](../tests/contracts/test_run_catalog_contract.py)
- [authority resolution contract tests](../tests/contracts/test_authority_resolution_contract.py)
- [authoritative read-model contract tests](../tests/contracts/test_authoritative_read_model_contract.py)

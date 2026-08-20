# Roadmap Stage 26 Planning: Operational Correctness And Lifecycle Guidance

Status: confirmed; removal-first cross-stage correction and manager quality gate passed
Roadmap stage: v26
Evidence tree: `/home/can134/work/active/loom` at
`2c05906c15791a025ff2cae90633d77efdc89aac`; unrelated concurrent Stage 25 and
Stage 29 roadmap edits are preserved
Planning route: lean cross-stage correction because the maintainer removed a
not-yet-implemented public notification layer; the earlier expanded review is
retained as evidence but no new public or durable decision was added
Current gate: ready for Phase 1 after Stage 25 remotely merges
Blockers: Stage 25 remote merge only

Stage 26 makes existing Loom behavior easier to use correctly. It gives stage
authors one clear guide for artifacts, workspace, logs, and lifecycle facts and
fixes demonstrated mismatches between documented and implemented behavior. It
does not add a notification abstraction, provider client, event subscription,
plugin activation path, scheduler, resource sampler, resume semantics, or new
validation gate.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | `StageContext`, executors, logs, lifecycle emitters, event sinks, examples, tests, and adjacent plans were inspected at the evidence revision. | Refresh after Stage 25 merges. | Preserve existing owners and durable formats. |
| Functionality | The stage is limited to operational guidance and demonstrated compatibility corrections. | None. | Implement one vertical phase. |
| Design | Existing context, artifact, log, lifecycle, event, and observer contracts remain authoritative; no public type is added. | None. | Keep documentation and corrections at their current owners. |
| Validation | Hermetic unit, contract, integration, and runnable-example coverage is sufficient. | None. | Use existing gates. |
| Approval | The maintainer approved removal of the overlapping notification phase and assigned generic observer filtering/activation to Stage 28. | Stage 25 sequencing only. | Advance after predecessor merge. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `StageContext`, artifacts, and stores | Narrow load/save/register/path helpers already support the intended stage-author path. Workspace files are not outputs until explicitly registered and returned. | Downstream operations guide. | FR-1, FR-3 |
| Local, subprocess, container, SLURM, and managed queue execution | Stream capture and log ownership differ deliberately by executor and process owner. | Truthful logging table and examples. | FR-2, FR-3 |
| Runtime events and lifecycle emitters | Current event names exceed older prose. A fresh `run.preparation_failed` is emitted before the run reads as `FAILED`, contrary to the existing post-commit event contract. | Event catalog and smallest source correction. | FR-3, FR-4 |
| `EventSinkRegistry` and `RuntimeEventDispatcher` | Ordered, synchronous, best-effort observation, failure capture, observer links, and append-before-dispatch already exist. | Document the observer boundary without a second notification layer. | FR-4 |
| Stage 28 plans | Exact subscriptions, sink registration values, plugin/CLI activation, provenance, and lifecycle-owner reconstruction form one coherent later extension path. | Cross-stage ownership. | FR-4, FR-5 |

- User-visible outcome: a stage author can answer where to read inputs, place
  temporary files, publish managed or file-backed outputs, find the logs owned
  by each executor, and interpret committed lifecycle facts.
- Existing end-to-end path: stage code uses `StageContext`; executors capture
  the streams they own; the runner validates and commits artifacts/status; the
  event path records the corresponding fact; explicit sinks may observe it.
- Included scope: one downstream operations guide, small examples, corrected
  artifact/log/event documentation, and the smallest source/test correction for
  the demonstrated preparation-failure ordering mismatch.
- Non-goals and deferrals: notification values or policy, service adapters,
  event subscriptions, plugin activation, async delivery, scheduling, resource
  sampling, resume/reuse changes, new external profiles, and validation policy.
- Public or durable surfaces affected: none. Existing context, artifact, log,
  event, observer, run, and stage shapes remain unchanged.

## Minimum Useful Change

- Smallest useful behavior: publish one copyable, evidence-backed operational
  path and ensure every documented lifecycle event follows its corresponding
  committed fact where such a fact exists.
- Closest existing capability and reuse decision: use `StageContext`, executor
  log paths, current status writers, runtime event helpers, and existing
  examples rather than creating facades or new records.
- Why source work is required: fresh preparation failure is a reachable
  exception to the already documented post-commit observation rule.
- Explicitly deferred behavior: a raw event sink is already sufficient for
  downstream notification code. Stage 28 will add generic exact filtering and
  explicit activation; common message/severity projection waits for repeated
  real provider consumers.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Show managed save, local-file registration, workspace use, input loading, and direct `ArtifactRef` returns. | No mutable store exposure, implicit output, remote writer, or domain schema. | Existing `StageContext` and artifact stores. | Runnable snippets and context contracts. | locked |
| FR-2 | Explain stdout/stderr, project file logging, tracebacks, queue-attempt logs, stage logs, and SLURM wrapper logs by executor. | No aggregation, streaming, structured logging framework, or new log-path API. | Existing executors, stores, CLI, and examples. | Truth-table review plus focused execution tests. | locked |
| FR-3 | Align canonical docs/examples with implemented public behavior and fix only demonstrated mismatches at their authoritative owner. | Documentation symmetry cannot justify new behavior. | Source, tests, feature docs, glossary. | One focused regression for each source correction. | locked |
| FR-4 | Publish the exact lifecycle-event catalog and commit-before-observe rule; fresh preparation failure commits `FAILED` before `run.preparation_failed`, while an already-terminal opened run remains unchanged. | No new event, sink, subscription, message, notifier, or provider contract. | Runner/lifecycle/store/event owners. | Exact event sequence and observer reads committed `FAILED`. | locked |
| FR-5 | Keep validation hermetic and preserve scheduling, resources, resume, queue, plugin activation, and adjacent-stage ownership. | No new Make/CI/profile/network/runtime requirement. | Existing harness and Stage 25/27/28 plans. | Diff/import review and existing final gates. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1 through FR-3 | Stage purpose | Treat correctness as alignment of existing behavior, examples, tests, and docs rather than a bucket for new operational features. | Attractive conveniences remain deferred. | locked |
| FQ-2 | FR-2 | Log ownership | Loom owns executor-captured streams and paths; project code owns its logger configuration and separate files. | Loom does not discover or aggregate arbitrary files. | locked |
| FQ-3 | FR-3, FR-4 | Lifecycle truth | Commit authoritative state before publishing the corresponding observer fact. | The correction is deliberately limited to the demonstrated fresh-run path. | locked |
| FQ-4 | FR-4 | Notification boundary | Do not add `NotificationMessage`, `NotificationSeverity`, `Notifier`, or `register_lifecycle_notifier`. Direct event sinks remain available; Stage 28 owns generic filtering and activation. | Initial providers format their own small messages. | locked |
| FQ-5 | FR-5 | Adjacent ownership | Stage 25 owns queue selection, Stage 27 GPU setup, Stage 28 extensions, and Stage 29 daemon/agent work. | Stage 26 remains intentionally narrow. | locked |

## Behavior Baseline

- Included and default behavior: existing stage and executor behavior remains
  unchanged except that a fresh preparation failure records `FAILED` before its
  event becomes observable.
- Failure and unsupported behavior: already-terminal opened runs are not
  rewritten; unprovable documentation claims are narrowed rather than made true
  through speculative APIs.
- Reproducibility and durable behavior: examples use supported public imports
  and temporary run roots. No schema, fingerprint, provenance, or import-cost
  change is introduced.
- Explicit deferrals: common notification presentation, severity policy,
  provider clients, event filtering/activation, delivery guarantees, mutable
  hooks, scheduling, sampling, and new resume behavior.

## Minimum Design

- Modules and ownership: `StageContext` owns stage-facing artifact/workspace
  helpers; executors/store/SLURM/queue owners define their log paths;
  runner/lifecycle/store code owns status commits; event code owns event facts;
  Stage 28 owns new observer extension mechanics.
- Data and control flow: stage returns declared refs -> executor captures owned
  streams -> runner commits status/artifacts -> event helper appends the fact ->
  any explicitly supplied observer runs.
- Fixed contracts: no new public or durable shape. Preparation failure changes
  ordering only, not status/event schemas or already-terminal behavior.
- Private discretion: guide organization, exact concise wording, whether a
  small example extends an existing workflow, and helper/test names.
- Import direction: documentation/examples may import public Loom APIs; core
  Loom never imports project/provider packages.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Downstream operations guide | Scattered current behavior causes incorrect usage. | Keep relying on several feature specs. | keep |
| Preparation-failure ordering correction | Reachable observer sees stale state. | Document the exception. | keep smallest source fix |
| Logging facade or uniform capture | No demonstrated generic owner. | Document actual executor differences. | defer |
| Generic notification values/protocol/helper | No source or real provider consumer; overlaps Stage 28 filtering/registration. | Direct downstream event sink and provider-owned formatting. | remove/defer |
| Public event-name validator | Stage 26 has no remaining caller. | Add it with Stage 28 subscriptions. | defer to Stage 28 |
| Provider SDK, outbox, retry, delivery record | No accepted reliability requirement. | Downstream adapter or external relay. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1, FR-2 | Reuse current stage/executor surfaces. | Each invariant already has an implementation owner. | Documentation remains backend-specific where behavior differs. | locked |
| DQ-2 | FR-3, FR-4 | Correct only reachable mismatches. | The preparation path violates the existing event-order rule; other source work requires comparable evidence. | Some prose may be narrowed instead of code changed. | locked |
| DQ-3 | FR-4 | Keep event observation generic. | Current `EventSinkRegistry` already supports Python notification side effects; Stage 28 supplies the missing generic selection/activation layer. | Core supplies no default severity or message text. | locked |
| DQ-4 | FR-5 | Preserve adjacent-stage contracts. | This correction removes cross-stage machinery rather than moving it earlier. | Common notification projection may arrive later. | locked |

## Prior Expanded Review Disposition

The earlier expanded design review evaluated the now-removed public
notification boundary. Its findings that remain relevant are retained: fix
fresh preparation-failure ordering, treat event/observer evidence as
best-effort, avoid provider dependencies, and keep event validation with the
event owner. Removing the message/severity/notifier/helper surface eliminates
the external-side-effect public-contract risk and requires no second spawned
review. The manager verified the corrected Stage 26 and Stage 28 artifacts
together.

## Examples And Validation

### Stage-Author Journey

The downstream guide presents one operational path rather than another API
reference. The intended mental model is:

```text
load declared input -> use private workspace -> save or register output
                    -> return declared ArtifactRef values
```

`save_artifact()` is the managed-object path: Loom serializes the value through
the named codec and returns its reference. `local_output_path()` plus
`register_local_artifact()` is the file-backed path: project code writes the
file, then explicitly publishes it. `local_workspace_path()` allocates private
intermediate space; neither creating a workspace file nor leaving it on disk
makes it an output. Local path helpers may be unavailable with non-local store
implementations, and the guide must describe that boundary rather than imply a
remote writer API.

This representative snippet records the accepted usage and distinction. The
implementation may shorten names or split it across examples, but it must keep
the same public calls and explicit returned-output contract.

```python
from collections.abc import Mapping

from loom.artifacts import ArtifactRef
from loom.pipeline import StageContext


class BuildReportStage:
    def run(
        self,
        context: StageContext,
        inputs: Mapping[str, ArtifactRef],
    ) -> Mapping[str, ArtifactRef]:
        _ = inputs
        records = context.load_input("records", expected_type="json")
        if not isinstance(records, list):
            raise ValueError("records artifact must decode to a list")

        scratch = context.local_workspace_path("tmp", "draft.txt")
        scratch.write_text(f"Processed {len(records)} records\n")

        report_path = context.local_output_path("report", suffix=".txt")
        report_path.write_text(scratch.read_text())
        report_ref = context.register_local_artifact(
            "report",
            report_path,
            artifact_type="text",
            codec_key="text.v1",
        )

        summary_ref = context.save_artifact(
            "summary",
            {"count": len(records)},
            artifact_type="json",
            codec_key="json.v1",
        )
        return {"report": report_ref, "summary": summary_ref}
```

Project code remains responsible for the meaning and compatibility of
`records`, reports, checkpoints, and other domain content. Loom owns only the
declared artifact contract, serialization/registration boundary, and returned
references.

### Logging Mental Model

The guide includes one source-backed table because there is no single logging
owner to normalize. It distinguishes what Loom captures from what project code
writes:

| Execution path | Planned guidance |
| --- | --- |
| Local, capture disabled | Python stdout/stderr pass through to the current process and terminal by default. |
| Local, capture enabled | Loom redirects Python streams to stage log paths; this is not a promise to capture native file descriptors, and bounded parallel local execution rejects this mode. |
| Subprocess, Docker, and Apptainer | Child stdout/stderr are written to the stage request paths, with failure/result evidence retaining those paths. |
| SLURM | Scheduler-wrapper stdout/stderr may be separate from the Loom stage streams and must be identified separately. |
| Managed queue | Queue-owned attempt logs are separate from the run's ordinary stage log paths. |
| Project `FileHandler` or direct file write | The file is owned by project configuration, is not automatically read by `loom logs`, and becomes an artifact only when explicitly registered and returned. |

`loom logs RUN_URI STAGE` is therefore documented as an inspection path for
Loom-owned stage streams, not arbitrary project files, queue-attempt logs, or
SLURM wrapper logs. Handlers configured before a captured in-process stage may
retain their original stream; handlers created inside the captured process
normally follow that process's redirected Python streams. Tests cover the
existing capture/pass-through and path behavior without adding a cross-backend
normalization contract.

### Lifecycle Catalog And Ordering

At the evidence revision, the lifecycle catalog to refresh against source and
publish consists of:

```text
run.created              stage.planned
run.opened               stage.started
run.planned              stage.completed
run.started              stage.failed
run.completed            stage.cancelled
run.failed               stage.skipped
run.cancelled            stage.reused
run.preparation_failed   stage.blocked
```

The catalog is descriptive rather than a new event-name API. Implementation
must refresh it after Stage 25 merges and document the exact names actually
emitted at that source revision.

The one accepted runtime correction is an ordering change in the fresh-run
preparation-failure path. The current mismatch is approximately:

```python
emit("run.preparation_failed")
if prior_status is RunStatus.CREATED:
    write_status(RunStatus.FAILED)
```

The corrected order is:

```python
if prior_status is RunStatus.CREATED:
    write_status(RunStatus.FAILED)
emit("run.preparation_failed")
```

This ensures that an observer reacting to `run.preparation_failed` reads
`FAILED`, not stale `CREATED`. It does not change event/status schemas or reset
an already-terminal opened run. Event observation remains synchronous and
best-effort, so an observer failure must not replace the original preparation
error or alter run correctness.

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Managed and file-backed outputs | Workspace confused with publication. | `StageContext` and artifact store. | Copyable snippets plus existing contracts. | planned |
| Executor logging table | Uniform wording hides different owners. | Executor/store/SLURM/queue. | Source-backed table and focused tests. | planned |
| Fresh preparation failure | Observer reads `CREATED`. | Runner status writer then event dispatcher. | Callback reads `FAILED`; terminal-run regression. | planned |
| Lifecycle catalog | Docs omit emitted names. | Event/lifecycle source. | Exact documented/source sequence. | planned |

Causal interactions requiring combined coverage are limited to fresh
preparation failure plus committed-state observation. Other documentation and
example cases remain focused.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Stage-author correctness and logging | One downstream guide plus truthful artifact/log/event behavior and the demonstrated preparation-order correction. | Context/docs/examples/runner tests only; no notification, subscription, plugin, scheduler, sampler, resume, or gate API. | Stage 25 merged. | Copyable guide, exact log/event claims, `FAILED` visible before event, full gates. | pending |

One phase is sufficient because the removed notification feature was the only
independent second vertical outcome.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR-1 through FR-5 and FQ-1 through FQ-5 reflect the maintainer-approved split. | pass |
| Minimum design justified | Existing public surfaces and one ordering fix suffice. | pass |
| Complexity delta proportionate | Four proposed notification contracts and their phase were removed. | pass |
| Contracts and private discretion clear | No public/durable addition; exact ordering behavior fixed. | pass |
| Invariant ownership and validation proportionate | Only preparation failure needs combined state/event proof. | pass |
| Phases vertical and reviewable | One independently useful phase remains. | pass |
| No unresolved blocker | Stage 25 is sequencing, not a design blocker. | pass |

Gate result: ready for Phase 1 after Stage 25 remotely merges. Maintainer
approval for the cross-stage correction was recorded on 2026-08-20.

Accepted risks and revisit triggers: executor logging remains heterogeneous.
Add a common notification projection only after at least two concrete provider
consumers or another accepted requirement demonstrates stable shared semantics.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Artifacts/workspace | Use current `StageContext`; outputs remain explicit refs. | Existing facade is sufficient. | Demonstrated non-local writer need. |
| Logging | Document executor differences. | No common runtime owner exists. | Demonstrated correctness failure requiring one. |
| Lifecycle events | Correct catalog and commit ordering. | Observers require authoritative facts. | New reachable mismatch. |
| Notification API | Removed from Stage 26. | No real core consumer and it duplicated Stage 28 selection/registration. | Two concrete providers need one stable projection. |
| Event subscriptions/activation | Stage 28. | They are generic extension mechanics. | Implement under Stage 28 Phase 3. |
| Provider delivery | Project/plugin code. | Credentials, payloads, and network policy are destination-specific. | Explicit first-party provider decision. |
| Scheduling/sampling/resume/gates | Deferred. | No accepted Stage 26 consumer. | Dedicated planning request. |

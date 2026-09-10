# Roadmap Stage 40 Planning: Coordinator Client, Agent Preparation, And MCP

Status: approved; ready for implementation
Roadmap stage: 40
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-85-control` at
`382065646608f4f19fed17a6fc0ecc9fce4a6e3f`, branch `agent/loom-mcp-plan`.
Relevant dirty paths on entry: `README.md` and the untracked
`docs/briefs/mcp-implementation-plan.md`, both earlier work for this request.
Planning route: expanded, for a public client, durable preparation, authenticated
filesystem access, publication/cancellation races, and retained-root migration.
Current gate: four-phase planning and startup review complete; implementation not started
Blockers: none.
Maintainer approval: Stage 40 behavior and four-phase delivery approved on 2026-09-10.

This is the current design authority. The implementation manifest indexes
phase-specific execution contracts. The brief is an explanatory entrypoint,
not a second implementation contract. No runtime implementation is authorized by
this planning request.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence / functionality | Existing coordinator submission and agreed direct-client workflow | None | Preserve current owners |
| Minimum design | Expanded review passed; finite preparation scope and native publisher retained | None | Preserve agreed design |
| Validation / phase shape | Four complete cards; independent review confirmed all accepted coverage has an owner | None | Preserve phase obligations |
| Quality / approval | Four-phase delivery approved and startup review passed on 2026-09-10 | None | Phase 1 coordinator-client is next; await execution instruction |

## Evidence And Scope

All paths below are relative to the evidence tree. Source and tests outrank
historical plans; the inspected revision includes later Stage 39 changes.

| Source or area | Current finding | Used for / related requirements |
| --- | --- | --- |
| `docs/roadmap.md`, `docs/structure.md`, `docs/GLOSSARY.md` | Managed admissions, authority and stage scheduling have separate owners; diagnostics sits above runtime | FR-40-01/02/06; import direction |
| `queue/local_daemon.py::LocalDaemonClientView` and `LocalDaemonOperation` under `src/loom` | Typed control, reads and passive waits exist; no preparation operation | FR-40-01/05/08 |
| `queue/local_daemon_transport.py` | Most Unix client operations exist; no socket I/O deadlines; legacy signatures and errors differ | FR-40-02/08/09 |
| `queue/agent_session_transport.py::_dispatch_application` | HTTPS client submit/status/cancel already exist; other client operations are missing; worker HTTP client mixes connection and worker lifecycle | FR-40-01/02; extract mechanics, retain worker owner |
| `queue/managed_local_preparation.py::prepare_managed_run` | Publishes supplied composition and exact stage requirements; complete replay is read-only; partial target conflicts | FR-40-05/06; authoritative finalizer |
| `diagnostics/preflight.py::_Context.config`, `run_preflight` | Composes and checks one cached object but returns only diagnostics | FR-40-06; supplied-composition entrypoint needed |
| `queue/_remote_stage_execution.py` | Assignment fencing, regular-file relay and committed results exist; 64 MiB aggregate inputs; host paths forbidden in ordinary semantic payload | FR-40-04/07 |
| `queue/deployment.py`, `resident_readiness.py`, `_agent_process_supervisor.py` | Protected installed profiles and observed software identity exist; no provisioning; coordinator-only deployments supported | FR-40-03/07 |
| `local_daemon.py::_open_root`, HTTP agent journal reader | Both currently demand root schema 12 and reject other versions; no upgrade path | FR-40-09; coordinator-only upgrade required |
| `diagnostics/run_inspection.py`, its contract tests | Versioned success/failure, ownership, freshness and bounded evidence exist | FR-40-02/08/10 |
| Existing daemon, transport, preparation, deployment and preflight tests; `tests/README.md` | Native parity/replay/authentication fixtures and optional dependency lanes exist | FR-40-12 |
| Stage 29, Stage 39 and `docs/roadmap/stage-81/implementation-plan.md` | Scheduling/resource/failure ownership already addressed | Preserve published contracts; no dependency on unfinished unrelated phases |

User-visible outcome: author an experiment on the coordinator's project storage,
request preparation on an eligible worker in a specified existing environment,
receive the coordinator's prepared-run receipt, submit, observe and cancel through
the same Python, CLI or MCP client. A local worker and a fleet use the same flow.

Existing path: a caller composes locally, calls managed preparation, submits its
run URI through the coordinator, and agents execute ready stages. The new work
moves composition/checks to a scheduled worker while retaining final publication.

Non-goals: scientific experiment design, environment/package installation,
automatic code deployment, Git checkout/pull, arbitrary shell/file tools, agent
client relays, a second scheduler, operator recovery through MCP, hosted MCP,
per-project ACLs, large dataset transfer and multi-environment preparation.

## Minimum Useful Change

Deliver complete native control, then scheduled worker preparation/native
publication, then optional MCP and skills. Agent preparation is included in the
accepted outcome. Python, CLI and MCP justify one client; requester loss and
coordinator restart justify durable preparation linkage. Reuse the existing
scheduler, publisher, transfer and diagnostics instead of adding parallel owners.

## Functional Requirements

| ID | Required behavior | Scope / dependencies | Validation | Status |
| --- | --- | --- | --- | --- |
| FR-40-01 | Every client request addresses the coordinator over Unix or authenticated HTTPS | Existing client policy; no worker forwarding | Transport and topology parity | agreed |
| FR-40-02 | One native client supplies typed operations/results to Python, CLI and MCP | Existing admission/agent/diagnostic owners | Native and legacy contract cases | agreed |
| FR-40-03 | Coordinator schedules preparation in a named, already installed environment | Protected profile; no interpreter/shell/install arguments | Actual selected interpreter and unavailable-profile cases | agreed |
| FR-40-04 | Shared roots and explicit staged inputs use one finite request | Immutable captured closure; existing relay | Shared and disjoint-root input cases | agreed |
| FR-40-05 | Coordinator owns asynchronous preparation, replay, cancellation and publication | Existing child execution and managed finalizer | Restart, lost reply, publication race | agreed |
| FR-40-06 | Publish exactly the composition checked on the worker | Diagnostics checks plus native serialized evidence | Stateful composition counter and received-data comparison | agreed |
| FR-40-07 | Preparation host does not imply execution affinity | Per-stage software/resources/input eligibility | Prepare B, execute C; incompatible C rejected | agreed |
| FR-40-08 | Bounded observations preserve uncertainty, errors and worker progress | Transport budgets, native failure models | Deadline, saturation and lost mutation reply | agreed |
| FR-40-09 | Migrate shared client consumers and preserve existing retained work | Thin legacy adapter; additive coordinator migration | Old entrypoints and populated-root upgrade | agreed |
| FR-40-10 | Optional stdio MCP exposes the full journey and survives session replacement | FR-40-01 through 09 | SDK integration and Codex trial | agreed |
| FR-40-11 | Loom skills remain portable across projects | Native tools/receipts; project supplies science | Two unrelated synthetic project journeys | agreed |
| FR-40-12 | Required checks distinguish automated proof from live deployment acceptance | Existing local harness; optional SDK lane added | Phase coverage and separate live receipts | agreed |

## Functionality Agreement

| ID | Requirement IDs | Decision and basis | Tradeoff | State |
| --- | --- | --- | --- | --- |
| FQ-40-01 | 01/02/10 | Direct coordinator client; user explicitly confirmed topology | Remote clients need their own client credential | locked |
| FQ-40-02 | 03/06/07 | Author on coordinator; prepare on selected eligible worker in existing environment | Preparation does not install newly edited code | locked |
| FQ-40-03 | 04 | Shared NAS primary, explicit staging also included | Staging initially inherits finite relay limits | locked |
| FQ-40-04 | 05/08 | Preparation/submission independent of assistant lifetime; stable IDs | Lost replies require reconciliation | locked |
| FQ-40-05 | 09/11 | Reuse current owners and project-neutral skills | No public legacy removals for naming cleanup | repo-resolved |
| FQ-40-06 | 03/04/05/09/10/12 | Four delivery phases approved: control, complete shared preparation, staged inputs, MCP/skills | One extra PR isolates archive/transfer risk; each phase includes smaller validated steps | locked |

Requirement suffixes in agreement tables refer to FR-40-xx.

## Behavior Baseline

Codex starts a local stdio adapter using the coordinator socket or direct mTLS
HTTPS. It needs no worker daemon. Deployment credentials, existing environment
profiles and trusted project configuration are separate inputs.

Preparation selects an operation ID, target run name, source closure, config path
and protected profile alias. Acceptance may precede capture; no child executes
before an immutable input receipt exists. Identical retries preserve the original
capture; changed explicit intent conflicts.

The coordinator schedules a fixed preparation child in the selected installed
environment, then publishes the returned checked composition with its native
publisher. No eligible offer leaves ordinary pending placement; invalid profiles
or unsupported service families fail before dispatch. Worker-local URIs do not
become canonical target receipts.

Preparation never auto-submits. Prepare-only stops at an applied receipt;
prepare-and-run authority permits submission without another per-step approval.
A later eligible worker may execute portable resolved intent.

## Minimum Design

**Client and transport.** Use `loom.coordinator.CoordinatorClient`, an integration
facade above queue and diagnostics. Shared control codecs/transport sit below it;
diagnostic decoding and injected runtime composition sit above queue. The legacy
socket facade delegates to the same lower-level owners without importing the
high-level facade back into queue. Native results and `LocalDaemon*` names stay.
Share matching client dispatch while retaining transport authentication/framing,
POST `/v1/client/<op>`, existing envelopes and distinct client/query/operator roles.

[Phase 1](phases/coordinator-client.md) fixes the method table, protected
`loom.coordinator-client` schema, additive capabilities, error detail and budgets.
Constructors select connections without starting daemons or registering workers.
Report safe aliases and observed coordinator identity, never private credentials.
Saved receipts carry coordinator identity; the native expectation guard rejects
a different coordinator before lookup/mutation. Capabilities do not grant authority.

**Preparation ownership.** Queue owns durable operation linkage. A higher
integration module owns the fixed preparation stage and diagnostics handoff;
existing service composition supplies the wiring. Runtime/scheduling/transport
do not import diagnostics or project modules. Bootstrap the ordinary child from
a fixed Loom stage definition and the selected native profile requirement; this
does not require composing the experiment first.

The worker composes once. Diagnostics gains a supplied-composition entrypoint
sharing existing checks; path-based preflight remains compatible. Check graph,
selectors and runtime on B, store/publication facts on A, and actual eligibility
at target launch. Never check A's store through B's scratch directory.

The committed child report carries existing resolved/redacted configuration,
manifests, recipe/provenance evidence, native per-stage requirements, input/profile
identities and PreflightResult. Decode data without pickle, recipe execution or
recomposition. Normalize the pinned Weave dependency's recipe mappings and the
existing object form once in the publisher, for writes and replay. Failed or
unavailable required checks prevent publication; WARN/inapplicable SKIP retain
their meanings. A successful report-producing child may therefore yield failed
preparation. Only the existing managed publisher creates the canonical target.

**Durability and cancellation.** Keep LocalDaemonOperation's outer fields and add
kind prepare_run. Pending covers capture and child activity; applying means
finalization was claimed; applied means complete publication. Other terminal
outcomes are failed, cancelled and conflict. Child admissions retain detailed
execution truth. [Phase 2](phases/agent-preparation.md) fixes the request/result,
input/report schemas and native receipt serialization.

Persist request/caller intent, selected protected configuration, reserved child/
target identity, capture, cancellation request, finalization claim and receipt at
the coordinator. Publish complete files before exposing ready references.
Identical retries return the originally accepted intent/capture; changed intent
conflicts. Restart rejoins the same child and finalizes/replays the same target.
Complete target replay is read-only; partial/corrupt/changed targets remain native
conflicts without deletion. No exactly-once execution claim is added.

Cancel before finalization claim suppresses publication and reconciles the child.
After claim, finish/reconcile publication and report its actual outcome. Terminal
cancelled needs no-dispatch or native termination/release proof, not an ACK.
Only preparation-kind operations accept this cancellation. It cannot cancel an
operator recovery or delete a published run. Preparation never submits the target.

**Inputs and existing installations.** Protected aliases map source roots on each
host. Shared mode captures selected mutable authoring files once on shared storage;
workers verify and use that snapshot without per-agent project copying. Staged
mode relays a bounded regular-file archive and extracts beneath assignment
ownership. Missing mappings, content mismatch, traversal, links, special files,
duplicate destinations and excessive size produce explicit failures. Capture/
extraction own those real boundaries; existing relay owns transfer integrity.

This finite input binding serves only preparation. It does not weaken ordinary
remote semantic path rejection or create a general ResourceRef scheme. Publish
portable resolved values and reject B scratch paths in executable intent.
Target code/data use compatible installations and existing supported artifact/
data bindings; arbitrary configured paths are not rewritten. A captured directory
is an exact record of consumed bytes, not a promise of atomic Git revision capture.

Staging does not install code or retarget a live installed checkout. New executable
changes need a compatible qualified installation/profile. Existing readiness and
launch identity observations bound this guarantee; they are not continuous
filesystem attestation. The first workflow uses one preparation environment.
Target placement still follows native per-stage software/resource/data requirements.

Preparation retains the existing embedded-authority/no-configured-SLURM-profile
family and rejects unsupported services before child dispatch. Retain operation
records and pinned input/report evidence so restart/replay remain possible;
assignment scratch uses current terminal cleanup. No new GC or operation-delete
API is introduced. Retained evidence consumption is an explicit limit.

**Migration.** Phase 1 migrates CLI client construction and extracts duplicate
codecs/dispatch. Preserve endpoint invocations, output and legacy defaults/errors;
add the mutually exclusive HTTPS connection option. Keep QueueClient/QueueService
and operator/worker lifecycle contracts separate.

Phase 2 upgrades coordinator root schema 12 to 13 explicitly offline, under the
existing exclusive lock, with a protected backup and one transaction. Split
role-version checks so worker roots/journals remain untouched. Preserve stable
identities and old runs/admissions; reject unsupported/corrupt roots. Old binaries
cannot reopen upgraded coordinator state; no automatic downgrade is offered.
Optional preparation settings preserve omitted-config identity and snapshot
accepted settings against reload.

**Mode rollout.** Phase 2 delivers the complete shared preparation lifecycle,
including publication, restart/replay, cancellation, bounded results and its
coordinator upgrade. It advertises only effective shared support and refuses
staged requests as unsupported/not_applied before reservation, capture or
dispatch. [Phase 3](phases/staged-preparation-inputs.md) adds archive/relay/extraction
through the same request, operation, report and publisher. Enabled modes always
intersect implementation support with protected policy. Qualify actual staged
handling in the selected installation; earlier shared-only workers are not
implicitly eligible. Existing shared operations reopen under schema 13 without
a second migration. Final Stage 40 acceptance still requires both source modes.

**MCP and limits.** [Phase 4](phases/mcp-skills.md) owns the optional SDK adapter,
13 tools and four portable product skills. Native reads default to 25-second
observations and pages of 20, maximum 100. Finite requests have a 30-second budget
under a 60-second Codex timeout, with bounded transport slices/concurrency and
reserved non-wait capacity. Native errors preserve uncertainty and evidence.
Legacy explicit terminal waits keep their existing unbounded option and
TimeoutError behavior. EOF or observation timeout never becomes cancellation.

Private helper/class names, SQL layout, packing library and bounded-executor
mechanics remain implementation choices. Public shapes, replay/state meaning,
trust boundaries, finite source scope and upgrade behavior are fixed.

## Complexity Delta

| Addition | Current necessity | Simpler alternative / decision |
| --- | --- | --- |
| Native client and shared dispatch | Python/CLI/MCP need transport parity | Keep matching control once; preserve thin compatibility adapters |
| Preparation operation | Requester/restart can outlive child/publication | Keep minimal coordinator linkage; no generic operation framework |
| Managed preparation child | Work needs the selected environment and lifecycle | Reuse scheduler/resources/fencing; no SSH or new queue |
| Finite capture/binding | Shared and disjoint preparation roots | Keep preparation-only inputs; no target-source deployment |
| Supplied-composition checks | Check and publish identical data | Share checks; no second composition |
| Recipe normalization | Pinned Weave mappings reach the existing publisher | Normalize there; no new composition model |
| Coordinator upgrade | Existing version checks otherwise require fresh roots | Narrow offline upgrade; leave workers untouched |
| Optional MCP/four skills | Current assistant workflow | Keep generic; no SDK dependency in runtime |
| Catalogs, registries, environment builder, alternate scheduler | No accepted consumer | Defer |

## Design Agreement

| ID | Requirement IDs | Decision / tradeoff | State |
| --- | --- | --- | --- |
| DQ-40-01 | 01/02/09 | Facade above queue/diagnostics; shared codecs; thin legacy wrappers remain | repo-resolved |
| DQ-40-02 | 03/05 | Managed child plus native publication; embedded-authority/no-configured-SLURM family | review-resolved |
| DQ-40-03 | 04/06/07 | Captured preparation inputs, checked data and normalized recipes; target uses installed code/existing data bindings | review-resolved |
| DQ-40-04 | 05/08 | Stable intent/child; cancellation competes with publication claim; partial target conflicts | repo-resolved |
| DQ-40-05 | 08/10 | Finite I/O/concurrency; qualified mutation errors and native evidence | repo-resolved |
| DQ-40-06 | 09 | Offline additive coordinator upgrade; worker state unchanged, no downgrade | repo-resolved |
| DQ-40-07 | 10/11 | Optional stdio adapter/four skills; no service/database in MCP | repo-resolved |

## Expanded Design Review

Result: **pass; no unresolved design blocker**. One removal-first review confirmed
the existing client/execution/publication owners and resolved these material items.
Their decisions are integrated into Minimum Design and Phase 2.

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| General target-source delivery exceeded scope | DQ-40-03; FR-40-04/07 | Existing relay handles explicit inputs; arbitrary path rewriting could retain B scratch paths on C | Bind captured files only for preparation; target uses portable values and existing installed-code/data contracts | resolved |
| Finalizer has a narrower service family | DQ-40-02; FR-40-03/05 | _validate_preparation_service rejects non-embedded authority and configured SLURM profiles | Reject unsupported preparation before dispatch | resolved |
| Nonempty recipe evidence mismatches publisher | DQ-40-03; FR-40-06/12 | Pinned Weave emits mappings; publisher/replay assumes to_dict() | Normalize at existing publisher and test real nonempty recipe publication/replay | resolved |
| Client layering and root migration justified | DQ-40-01/06 | Three client consumers; shared root-version constant would unnecessarily affect workers | Preserve lower-level ownership and prove coordinator-only upgrade | pass |

## Examples And Validation

| Invariant / example | Authoritative owner and boundary | Minimal coverage |
| --- | --- | --- |
| Same control across hosts | Client view and TLS/Unix | Local-only worker; rootless remote client; parity and wrong-role rejection |
| Publish checked composition | Diagnostics handoff and publisher | Stateful recipe runs once; nonempty evidence replays; failed checks create no target |
| Captured preparation inputs | Capture and relay/access | Shared/disjoint roots, digest mismatch, traversal/size rejection |
| Execution can move from B to C | Readiness and runtime binding | Compatible C consumes portable resolved values; mismatch/scratch paths fail |
| Stable preparation lifecycle and namespace | Operation/admission/finalizer | Lost replies/restart; changed intent or coordinator rejected before lookup/mutation |
| Truthful cancellation | Finalization claim and native containment | Both race orderings; unresolved child is not cancelled |
| Retained state upgrade | Root lock/schema owner | Populated coordinator upgrade, worker unchanged, unsupported/locked refusal |
| Evidence survives cleanup | Operation reference and cleanup owners | Pinned capture/child/result cannot disappear before replay |
| Bounded observation | Transport and SDK scheduling | Stalled reads/saturated waits while ordinary and worker calls progress |
| Observable preparation receipt | Operation projection owner | Large report keeps state/receipt readable; oversized receipt fails before target publication |
| Project-neutral workflow | Tools and skills | Build/checksum and transform/report journeys |

Required causal combinations: lost reply with restart/replay; cancellation with
publication/child release; captured input with later placement; saturated waits
with worker traffic. Avoid an all-dimensions Cartesian matrix.

All coverage is planned. Loopback/disjoint-root tests do not prove physical NAS
visibility or a real Codex session. Separate synthetic two-machine and Codex
receipts govern those release claims. No scientific/GPU/SLURM run is needed.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance | Status |
| --- | --- | --- | --- | --- | --- |
| 1 | Python/CLI direct coordinator control on either transport | Client, compatible transport/CLI migration; preparation excluded | Published develop | Parity, roles, waits, legacy behavior | pending |
| 2 | Complete native preparation through shared storage and target execution | Common operation/report, shared capture, diagnostics, profiles, upgrade/publication and cancellation; staged delivery excluded | Phase 1 merged | Local/remote shared workers, restart/cancel, retained roots, target consumption, staged refused before mutation | pending |
| 3 | Same preparation lifecycle with transferred inputs | Archive capture, native relay/extraction, staged support and boundary validation; shared lifecycle reused | Phase 2 merged | Disjoint-root worker, archive/transfer limits, staged recovery/cancel, unchanged shared state | pending |
| 4 | Codex tools and portable skills over both native modes | Optional adapter, skills, docs, SDK lane | Phase 3 merged | Real stdio workflow and distinct live acceptance | pending |

The approved four-phase shape isolates archive/relay/extraction as a complete
second input mode after shared-NAS preparation works. This justifies one phase
beyond the usual one-to-three preference. Phase 2 retains its complete operation,
publication, recovery/cancellation and migration consumer; no schema-only or
partial-lifecycle phase is introduced. Each card has four or five implementation
steps, each with focused tests, inside its single PR.

Coverage ownership: Phase 2 owns common request/report/lifecycle/publication,
shared capture, mode refusal and root-upgrade obligations. Phase 3 owns staged
archives, disjoint-root delivery, extraction bounds, transfer-related recovery/
cancellation and shared-state compatibility across that addition. Unchanged
common evidence is reused; no accepted coverage is postponed to optional
hardening. Phase 4 owns SDK/skills and separate live Codex/physical NAS acceptance.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior/agreement | Confirmed user direction and FQ rows | pass |
| Minimum design/complexity | Existing owners; expanded review and removals | pass |
| Fixed contracts/private discretion | Minimum Design plus reviewed cards | pass |
| Invariants/proportional validation | Native owners and causal examples | pass |
| Vertical phase shape | Control, shared preparation, staged inputs, then MCP; reviewed allocation and handoff | pass |
| No design blocker | Three material findings resolved | pass |

Gate result: design review and independent plan review passed after one bounded
correction: coordinator identity is guarded on recovery; large reports cannot
hide operation state or the prepared receipt. Manager verification confirmed the
correction and manifest/card consistency. The maintainer approved the final
Stage 40 behavior and four-phase delivery on 2026-09-10. The revised delivery
boundaries passed focused independent plan/startup review with no blockers,
optional concerns or required correction. The manifest records the verified base,
documentation checks and next pending phase; common architecture remains intact.
Implementation awaits a separate execution instruction.
Accepted risks: finite installation observations/input closure, retained evidence
space, partial-publication conflicts and deployment-wide client policy.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Existing public clients and native record names | Preserve via shared owners | No user benefit from a broad breaking rename | Explicit separate compatibility decision |
| Newly authored executable code | Require compatible qualified installation | File transfer is not software installation | Accepted code-deployment workflow |
| Large projects/datasets and mixed preparation environments | Deferred | Current relay/profile contracts are finite | Concrete unsupported project need |
| Local laptop authoring upload | Deferred; author on coordinator or shared storage | Direct connection is not a file editor/uploader | Accepted remote authoring requirement |
| Hosted MCP, plugin bundle, per-project ACLs | Deferred | Initial stdio/native authorization meets current workflow | Distribution/security requirement |
| Runtime implementation | Plan approved; await execution instruction | This workflow is planning-only | Implementation request |

# Roadmap Stage 35 Planning: Configurable Run Roots And GPU Container Admission

Status: complete
Roadmap stage: 35
Evidence tree: `/nas/home/can134/work/loom-worktrees/stage-35-planning` at
`fd5543b1dd75dd3e78a2b7b5bb9ebc73535fac6b`; relevant dirty paths: none before
this planning packet
Planning route: expanded; an optional public runtime field participates in
resume-store bootstrap, while GPU visibility crosses host, scheduler, shell,
and container boundaries
Current gate: implementation complete; Phases 1 and 2 passed expanded review,
their corrected pre-submit gates, and verified squash merges
Blockers: none

This file records a current downstream requirement without adding
domain-specific experiment behavior to Loom. The maintainer requested
implementation after reviewing the required run-store and single-GPU behavior
on 2026-08-30.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Evidence | Loom now validates generic resources, accepts a configured CLI run-store root, maps GPU counts to Slurm, derives container passthrough, and validates operator/scheduler visibility at the correct execution boundary. | None. | Downstream consumers may pin the merged revision. |
| Functionality | A composed config may select one absolute run root; an exclusive GPU count drives NVIDIA passthrough and exact local/allocation-time CUDA visibility. | None. | Complete in PRs #258 and #259. |
| Design | One optional run-store option and one Loom-owned GPU admission module are wired through existing factories and executors. | None after expanded review. | Revisit only for a documented deferred capability. |
| Validation | Fake and public CLI paths prove config, profile, store, local command, executable Slurm script, and failure behavior; real container/GPU/Slurm checks remain opt-in. | None. | Use opt-in live checks when matching infrastructure is available. |
| Detailed plan | Two merged phases separate storage bootstrap from executor/scheduler admission. | None. | Complete. |
| Approval | The maintainer explicitly requested implementation; planning and implementation quality gates passed. | None. | Complete. |

## Evidence And Scope

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| `pipeline/runtime/options.py`, `profiles.py`, and `config.py` | `RunOptions` is the canonical merged invocation policy, but `run_store` is an unknown field. Profiles already provide base/profile/explicit precedence. | Configured root model and merging. | FR-1..FR-4 |
| `cli/run.py`, `plan.py`, and authority-backed store factories | Run, resume, Slurm planning, and plan views construct stores through existing authority/offline factories. Resume opens the store before plugin activation validation. | Store bootstrap and use. | FR-3..FR-5 |
| `pipeline/resources.py` and runtime metadata | Canonical exclusive GPU entries already require a positive integer count and resolved metadata already preserves resource kind, amount, and unit. | Avoid a second resource schema. | FR-6, FR-10 |
| Apptainer/Singularity executor and command builder | `ApptainerExecOptions` already models `nv`, `rocm`, `cleanenv`, and `no_home`; container environment projection already emits redacted `--env` values. Generic GPU resources do not currently select `nv`. | Direct container admission. | FR-6..FR-8 |
| Slurm resources, planning, wrapping, and rendering | Slurm already renders `--gres=gpu:N` and wraps stage commands in Apptainer, but the wrapper does not receive the resource request and the generated script does not validate allocation-time CUDA visibility. | Scheduler/container handoff. | FR-7..FR-9 |
| Downstream rphys reference recipe at `83fc06cc` | One maintained recipe selects an absolute run root, one exclusive GPU, local Singularity or Slurm, and clean environment execution. Its locked suite currently fails because the pinned Loom revision lacks the agreed GPU module. | Current consumer and demonstrated failure. | FR-1..FR-10 |

- User-visible outcome: one ordinary composed pipeline config can be validated,
  planned, and run with a project-selected run collection and one generic GPU
  request, without project-owned launcher or device-selection wiring.
- Existing end-to-end path: Weave composition produces `runtime` and
  `runtime_profiles`; Loom merges `RunOptions`, creates an authority-backed run
  store, resolves one stage runtime, and selects direct Singularity or Slurm
  container execution. The additions close two missing projections in that
  path.
- Included scope: optional configured run-store root; profile and CLI use;
  resume-safe bootstrap; exclusive GPU-count extraction; opaque CUDA visibility
  parsing; resource-derived `--nv`; local explicit environment projection;
  Slurm allocation-time validation and clean-container propagation; preflight,
  docs, and hermetic tests.
- Non-goals and deferrals: CPU or memory container flags, new timeout
  enforcement, GPU inventory/discovery, physical device selection, fractional
  or shared GPU modes, distributed or rank launch, Torch integration, a new
  store backend, remote storage, migration machinery, and mandatory live
  container/GPU/Slurm tests.
- Public or durable surfaces affected: `RunOptions` gains optional
  `RunStoreOptions`; the executor package gains the intentionally importable
  GPU projection/visibility functions requested by the current consumer.
  Existing runtime and executor metadata remain compatible and no new durable
  schema version is required for an omitted optional field.

## Minimum Useful Change

- Accept `runtime.run_store.root` as an absolute path, preserve it through the
  existing merge order, and pass it to every CLI-created store that opens or
  persists the selected run.
- Treat absence as Loom's existing `runs` default. Keep the existing
  authority-backed/offline factory; do not replace it with a second local-only
  execution path.
- Read the canonical exclusive GPU count from `ResourceRequest`, derive
  Apptainer/Singularity NVIDIA passthrough, and validate exactly that many
  opaque visibility tokens at the boundary where visibility exists.
- For direct execution that boundary is host process setup. For Slurm it is the
  generated allocation script immediately before the wrapped container command.
- Defer broader executor resource enforcement and GPU allocation policies;
  Slurm or the local operator remains the physical allocation owner.

## Functional Requirements

| ID | Required behavior | Scope and non-goals | Dependencies | Validation | Status |
| --- | --- | --- | --- | --- | --- |
| FR-1 | Accept `runtime.run_store.root` and expose it as `options.run_store.root`. | No backend selector or second run URI. | Existing runtime config and option models. | Model/config round trip and public merge tests. | locked |
| FR-2 | Omission preserves the current `runs` default; explicit roots are non-empty absolute canonical strings and invalid values fail clearly. | Do not create directories during parsing. | Path validation only. | Invalid type/empty/relative/noncanonical cases. | locked |
| FR-3 | Base, selected profile, and explicit runtime sources merge `run_store` with existing precedence. | No independent profile system. | Current profile merge. | Base/profile/explicit integration tests. | locked |
| FR-4 | `loom run`, resume, plan/resume, Slurm dry-run/live, and offline-first store creation use the configured root consistently. | Direct Python callers that inject a store retain ownership of that store. | Existing authority/offline factories. | CLI factory spies and one persisted-root journey. | locked |
| FR-5 | Resume locates its store before validating persisted plugin activation without importing untrusted/unvalidated plugins first, and the final merged root cannot differ from the bootstrap root. | No weakening of resume activation trust ordering. | Existing composed config and profile selection. | Resume ordering and mismatch tests. | locked |
| FR-6 | Extract only a bare canonical exclusive GPU count: positive integer amount, absent or `count` unit, and no attributes; no entry means zero and richer selectors/share modes fail rather than being interpreted as counts. | No fractional/share or selector enforcement design. | Existing `ResourceRequest` validation. | Pure projection tests. | locked |
| FR-7 | GPU count greater than zero derives `nv=True`, preserves unrelated Apptainer options, preserves an already-authored `nv=True`, and conflicts with `rocm=True`; with no GPU request the authored options remain unchanged, so the default stays `nv=False`. | Resources automatically enable access but do not remove the existing manual passthrough option. | Existing immutable exec options. | Pure option tests and command argv tests. | locked |
| FR-8 | Direct Apptainer/Singularity setup requires exactly the requested number of opaque `CUDA_VISIBLE_DEVICES` tokens and explicitly carries them through `cleanenv`. | Tokens are not ordinals; zero-GPU execution does not promise isolation. | Container environment projection. | Missing/mismatch/invalid/duplicate/success executor tests. | locked |
| FR-9 | Per-stage Slurm `afterok` execution continues to render `--gres=gpu:N`, derives container `--nv`, validates scheduler visibility inside the allocation, and carries it through Apptainer and Singularity clean environments. | Planning never selects or observes the physical device; single-job GPU aggregation is deferred because that mode has no aggregate resource input. | Current Slurm afterok planner/wrapper/script. | Planned command/script and public dry-run tests. | locked |
| FR-10 | Resolved GPU resources remain stage runtime evidence; physical tokens remain invocation/environment evidence and do not enter scientific identity. | No new project-specific metadata or fingerprint field. | Current resolved-runtime metadata. | Existing metadata contract plus redaction assertions. | locked |

## Functionality Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| FQ-1 | FR-1..FR-5 | The root is optional runtime invocation policy, not a new store backend. | It changes where existing factories operate and naturally controls run, artifact, and mount paths. | Python callers supplying their own store do not receive implicit construction. | locked |
| FQ-2 | FR-5 | Preserve resume-before-plugin-activation ordering with a narrow bootstrap projection and final equality check. | The store must be found before persisted activation can be trusted; parsing every plugin-owned resource first reverses that trust boundary. | One bounded bootstrap projection shares profile-selection rules with full merge. | locked |
| FQ-3 | FR-6..FR-9 | A bare exclusive GPU resource automatically enables passthrough; existing authored `nv` remains compatible when no resource request exists. | The accepted recipe gains one resource authority without silently disabling an existing public option. | Authored `nv` alone does not claim allocation or trigger visibility admission. | locked |
| FQ-4 | FR-8, FR-9 | Validate where visibility exists: direct host setup or Slurm allocation script. | Plan-time Slurm validation would inspect the wrong environment. | Shell rendering mirrors the pure token/count contract. | locked |
| FQ-5 | FR-10 | Keep raw device tokens out of persisted safe command metadata. | The child environment may observe them, while Loom persists counts/redacted command evidence. | Operators use allocation logs or project evidence for exact device diagnosis. | locked |

## Behavior Baseline

- `RunStoreOptions.root=None` means the historical default. An explicit root is
  normalized and validated without filesystem mutation, then passed to the
  existing selected authority/offline store factory.
- The CLI composes configuration before store bootstrap. Resume uses the same
  selected profile as the final merge and fails if full validation would change
  the root.
- `CUDA_VISIBLE_DEVICES` values such as `0`, `GPU-abc`, `device-7`, and MIG
  identifiers are opaque comma-separated tokens. Missing, empty, or `-1` means
  no visible device. Empty tokens, whitespace, malformed tokens, duplicates,
  and count mismatch fail before worker launch.
- A zero-GPU request does not inject visibility and does not claim that an
  otherwise exposed host GPU is isolated.
- Slurm selects physical devices. The rendered job validates and forwards the
  scheduler value; project code sees logical device numbering only.

## Minimum Design

- Runtime options own `RunStoreOptions`; profiles own ordinary nested merge;
  CLI bootstrap code owns pre-activation root resolution; existing store
  factories remain storage/authority owners.
- One executor-owned GPU module owns count extraction, passthrough projection,
  and Python visibility parsing. Direct executor setup and Slurm planning call
  it rather than reimplementing resource semantics.
- Slurm rendering owns the unavoidable allocation-time shell validation and
  environment export. The renderer mirrors the Python token/count rules and
  records no raw token in durable command metadata.
- Public contracts fixed here are the optional `RunOptions.run_store` shape and
  `loom.pipeline.executors.gpu_visibility` functions/evidence shape. Helper
  placement, local metadata summaries, and bootstrap helper names remain
  private discretion.
- Import direction remains runtime options -> generic stores at CLI composition,
  and executor-specific GPU helpers -> resource/Apptainer models. Core resource
  and store packages do not import CLI or downstream projects.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Optional run-store options value | Current config consumer must select a machine-specific root. | Continue forcing process working directory or private launcher wiring. | keep minimal |
| Resume bootstrap root projection | Store identity is needed before persisted plugin activation validation. | Fully load plugins before opening the run. | keep bounded |
| GPU visibility/projection module | Direct and Slurm paths need one count/token contract and current downstream imports it. | Author `nv` and device values independently in YAML. | keep executor-owned |
| Slurm shell admission block | Visibility exists only after allocation. | Validate submission-host environment. | keep generated and tested |
| CPU/memory flags, timeout enforcement, GPU discovery/share modes | Not required for the accepted downstream closure. | Broaden the old prototype patch. | defer |

## Design Agreement

| ID | Requirement IDs | Decision | Recommendation and evidence | Tradeoff | State |
| --- | --- | --- | --- | --- | --- |
| DQ-1 | FR-1..FR-4 | Use `root: str | None`, omit the field from serialized options when unset, and use existing factory defaults. | Avoids changing every current persisted options document while making explicit config recoverable. | Consumers inspect the typed default rather than expecting an always-present plain-data key. | locked |
| DQ-2 | FR-2 | Require explicit roots to be absolute canonical paths. | Container path parity and multi-process reopening require one stable spelling. | Symlink/relative convenience must be resolved by composition before Loom. | locked |
| DQ-3 | FR-5 | Bootstrap only the selected run-store field and verify it against the full plugin-aware merge. | One early trust dependency justifies the narrow projection; a second general parser does not. | Bootstrap and full merge need shared profile-selection tests. | locked |
| DQ-4 | FR-6, FR-7 | Count only bare exclusive GPU requests and project options as `nv = authored.nv or requires_gpu`. | Current resource attributes include selectors and non-count modes that must not be silently misread, while preserving authored `nv` avoids an unrelated compatibility break. | Attribute-bearing GPU requests fail on these executors until separately designed. | locked |
| DQ-5 | FR-8, FR-9 | Reject authored container `CUDA_VISIBLE_DEVICES` when a managed GPU request exists. | Operator/scheduler allocation is the one physical binding owner. | Users migrate manual device selection to host or scheduler configuration. | locked |
| DQ-6 | FR-8..FR-10 | Persist requested/visible counts and redacted command evidence, not raw physical tokens. | Maintains operational evidence without turning bindings into durable identity. | Exact token diagnosis remains environment/project evidence. | locked |

## Expanded Design Review

| Finding | Related IDs | Evidence and consequence | Required action | Status |
| --- | --- | --- | --- | --- |
| Slurm single-job mode has no aggregate GPU resource source. | FR-9 | Current CLI passes no resources to single-job planning, while afterok receives each stage's request. Inventing an aggregation rule would expand scheduling semantics. | Scope production Slurm GPU admission to afterok and defer single-job aggregation. | resolved |
| Canonical exclusive GPU entries can carry selectors that these executors do not enforce. | FR-6, DQ-4 | Silently reducing model, VRAM, feature, or fabric requirements to a count would overstate admission. | Accept only an attribute-free exclusive count and fail path-aware on every richer shape. | resolved |
| Authored `ApptainerExecOptions.nv` compatibility was ambiguous. | FR-7, FQ-3, DQ-4 | Clearing or rejecting an existing public option was not required by the current resource-driven behavior. | Preserve authored options and OR only the derived positive resource decision. | resolved |
| Resume bootstrap and executor/rendering ownership are proportionate. | FR-1..FR-10 | The store must be found before plugin activation, local visibility exists before direct launch, and Slurm visibility exists only in the allocation. | Keep the narrow bootstrap/equality guard and one shared Python contract plus renderer-owned shell admission. | accepted |

## Examples And Validation

| Example or invariant | Behavior or risk | Authoritative owner and boundary | Minimal coverage | Status |
| --- | --- | --- | --- | --- |
| Configured fresh and resumed run root | CLI silently continues under `./runs` or opens the wrong prior run. | Runtime merge plus CLI store bootstrap. | Factory-spy tests and one persisted run/resume root. | verified |
| Profile root override | Bootstrap and full merge select different roots. | Shared profile selection/precedence. | Base/profile/CLI profile cases plus equality guard. | verified |
| Direct one-GPU clean container | `--nv` is absent or visibility is lost under `cleanenv`. | Direct executor setup. | Fake runner command and worker-environment proof. | verified |
| Slurm one-GPU container | Submit host is mistaken for allocation or scheduler token is lost. | Slurm resource mapper and generated script. | `--gres`, `--nv`, runtime shell check, and environment exports. | verified |
| Invalid visibility | Worker starts with missing/mismatched/duplicate binding. | GPU admission owner at external boundary. | Pure and executor/script failure cases. | verified |

Causal interactions requiring combined coverage:

- Resume, selected profile, and plugin activation order interact because the
  configured root determines which persisted activation record is authoritative.
- Slurm resource count, generated `--gres`, container `--nv`, allocation-time
  visibility, and `cleanenv` interact because all five must agree for one
  physical allocation to become one logical container device.

## Phase Shaping

| Phase | Vertical outcome | Ownership and exclusions | Dependencies | Acceptance and tests | Status |
| --- | --- | --- | --- | --- | --- |
| 1. Configurable run-store root | Config, profile, fresh/resume/plan/Slurm CLI paths consistently use one explicit run collection through existing authority/offline factories. | Runtime options/profile/bootstrap/CLI/docs/tests; no executor or GPU work. | Approved planning packet. | Model, precedence, ordering, CLI and persisted-root tests plus full gates. | merged (#258) |
| 2. GPU container admission | One exclusive GPU request produces scheduler/container access and exact local/allocation visibility without physical-device selection in project config. | GPU helper, direct executor, Slurm wrapper/rendering, preflight/docs/tests; no run-store, distributed, CPU/memory, timeout, discovery, or share-mode work. | Phase 1 remotely merged. | Pure/direct/Slurm/public dry-run coverage plus full gates. | merged (#259) |

Two phases isolate a public storage/bootstrap change from an external
executor/scheduler boundary and let each PR remain vertically reviewable.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and agreements locked | FR-1..FR-10 and maintainer implementation request. | pass |
| Minimum design justified | Existing runtime, factory, resource, executor, and Slurm seams own every major step. | pass |
| Complexity delta proportionate | Backend, migration, discovery, distributed launch, resource flags, and timeout additions are deferred. | pass |
| Contracts and private discretion clear | Public shapes, trust ordering, physical allocation owner, failures, and deferrals are fixed. | pass |
| Invariant ownership and validation proportionate | Store bootstrap and GPU allocation boundaries have causal coverage; internal helpers remain discretionary. | pass |
| Phases vertical and reviewable | Storage then GPU admission, each ending in an observable CLI/runtime outcome. | pass |
| No unresolved blocker | The three concrete review findings are resolved above. | pass |

Gate result: pass. Both phase plans were implemented, independently reviewed,
validated, and merged.

Accepted risks and revisit triggers: explicit roots require canonical absolute
spelling; direct execution validates operator-provided visibility but cannot
allocate hardware; default tests fake external runtimes. Revisit for a second
store-location backend, GPU share-mode executor support, distributed/gang
launch, or a requirement for mandatory live GPU validation.

## Decisions And Deferrals

| Item | Decision or deferral | Rationale | Revisit trigger |
| --- | --- | --- | --- |
| Store backend selection | Defer; configure only the existing local collection root. | Current consumer needs location, not a new authority. | A concrete non-local CLI store consumer. |
| Authored `nv` without resources | Preserve the authored option and do not infer allocation or visibility admission. | Maintains the existing public container option while resources add automatic projection. | A future unified allocation contract with migration evidence. |
| Slurm single-job GPU aggregation | Defer. | Current single-job planning receives no aggregate resource request, and max/sum/per-stage semantics are a separate scheduler decision. | A current single-job GPU consumer and an agreed aggregation rule. |
| Zero-GPU isolation | Not promised. | Direct Apptainer is not a hardware allocation sandbox. | A managed isolation contract. |
| GPU share modes | Reject on this projection. | Visibility count is not equivalent to a VRAM/provider share. | Executor-specific share enforcement. |
| CPU/memory and outer timeout | Defer. | Not required by the accepted closure; rphys retains its documented child supervisor. | Separate current consumer and acceptance contract. |
| Real GPU/Slurm gate | Opt-in/manual. | Default validation remains hermetic. | Stable available hardware in the validation environment. |

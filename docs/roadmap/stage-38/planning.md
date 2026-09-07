# Roadmap Stage 38 Planning: Selective Container Port And Correctness Review

Status: first-phase implementation complete; validation correction in progress
Roadmap stage: 38
Evidence revision: `f4b1ae76f63d33f2d481916bf36147f372e6225d`
Planning route: expanded for container process ownership; independent baseline
and implementation correctness reviews explicitly required by the maintainer.
Current gate: Phase 1 local validation; upstream audit independently accepted.
Blockers: Phase 1 gate exposed A-11 test race; timeout design and runtime evidence remain open.

## Current State

| Gate | Locked result | Open decisions or blockers | Next action |
| --- | --- | --- | --- |
| Authority | Maintainer requested execution of the selective-port draft, including review and merges to develop | No authority to retire the original dirty checkout | Preserve it throughout |
| Evidence | Published develop verified; isolated locked Python 3.12 environment; 236 tests passed and independent audit accepted | A-9 and A-10 need later bounded corrections | Preserve retained upstream behavior |
| Functionality | Stage-owned validation, direct CPU/memory mapping, lifecycle-safe timeouts; retain corrected upstream behavior | No scientific or remote submission changes | Trace each requirement to an owner |
| Design | Reuse existing configuration, resource, worker, and failure surfaces | Timeout ownership must be resolved before enabling policy | Review the smallest end-to-end design |
| Implementation | Phase 1 CLI guard and public regression implemented; 24 targeted tests passed | Full gate exposed A-11; Phase 3 retains its explicit design gate | Correct the bounded test race, rerun gates, independently review |

## Evidence And Scope

The source checkout is `/nas/home/can134/work/loom`, on dirty `develop` at
`a6bd1ef54523ac394b6a875c7486f9d8d7f68b95`. It contains 36 modified tracked
files (15 source, 18 tests, three feature docs), plus the untracked historical
concurrency brief and GPU visibility helper. None is an implementation base.
The selected worktree root is `/nas/home/can134/work/loom-worktrees`; current
audit/first-phase tree is `stage-38-p1-stage-target-validation`, branch
`agent/stage-38-p1-stage-target-validation`. The older Stage 81 worktree remains
untouched and is not repurposed.

Preservation receipts, SHA-256 at intake:

- Tracked `git diff --binary`: `99d00f0ee2f74a204e76ad80c070a25c7abe2693b7a4f9c3b2269121301c9861`.
- `docs/briefs/managed-local-concurrency-and-resource-assignment.md`:
  `621f48ea97e753dd37d3d7d545ef4df8ab6bb94780bf2ecfb85e109918e4a297`.
- `src/loom/pipeline/executors/gpu_visibility.py`:
  `f59cbe323cc492982a590244ca8950b366ab2007952f286bcdad9274b0bcb819`.

The changed tracked areas are CLI run/plan/validate, preflight, runtime options/
profiles/capabilities and exports, direct Apptainer, SLURM composition/rendering,
and plain serialization, with corresponding tests and feature documentation.
There is no dirty queue implementation. Do not apply the complete historical
diff: upstream has 145 intervening commits and intentional semantic differences.

| Source or area | Current finding | Used for | Related IDs |
| --- | --- | --- | --- |
| Stage 35 plan; runtime options/profiles, CLI run/plan | Run-store selection and GPU admission already merged; CPU/memory flags and timeouts were explicitly deferred | Selective disposition, compatibility | FR-2, FR-4 |
| CLI validate; pipeline stage factory; locked Weave target checker | Stage checker constructs only the outer factory, but generic traversal still enters stage-owned mappings | Validation defect | FR-1 |
| Apptainer commands/executor and runtime capabilities | Resource intent is already projected into the container record, but direct CPU/memory flags are absent | Extend current command owner | FR-2 |
| Stage 37 plan, stage context, ordinary and resident worker reconstruction | Ordinary workers are STAGE-owned; resident agent and SLURM entries are OUTER_BOUNDARY-owned | Timeout design constraint | FR-3 |
| Queue assignments, local daemon execution, agent process supervisor | Capacity/ownership mechanisms exist; root exit is distinguished from containment | Retain current ownership, reconcile historical brief | FR-4 |
| Plain serialization helpers and round-trip tests | Mapping-based conversion and refreezing already implemented | Avoid duplicate port | FR-4 |

User-visible outcome: trusted configuration keeps its stage-owned data intact;
direct containers receive supported limits; timeout results tell the truth
about supported-process cleanup. Existing managed execution remains compatible.

Non-goals: rphys stages or scientific operations, PURE products, determinism,
network submission APIs, Stage 81 domain-failure transport, new schedulers,
physical GPU selection, general process-supervisor frameworks, or cleanup of
the original checkout. Test data is synthetic. Do not inspect or publish private
environment files, credentials, real experiment logs, or dataset contents.

## Upstream Correctness Audit

The audit traces public inputs through source, persistence, tests, and docs.
Passing old-checkout tests are not an upstream receipt. The isolated environment
was created with `uv sync --locked --all-groups`, using Python 3.12.3 and locked
Weave revision `6a99a4d7e6f008748c0761e6ab1c359d62aacbbd`.

| ID / classification | Evidence and supported path | Consequence / disposition |
| --- | --- | --- |
| A-1 confirmed defect | `cli/validate.py:handle` sends the complete composed config to generic target checking after checking stage factories; the skipped factory path does not stop recursive traversal into its children | Nested stage config, factory init, and pipeline metadata targets can be constructed independently. Port the ownership guard and add a real public CLI regression. |
| A-2 intentional compatibility difference | `RunStoreOptions` normalizes lexically with `normpath`; profiles support sparse merging and explicit null clearing; CLI bootstraps and checks the selected root before/after runtime validation | Retain upstream. The older filesystem-resolving, non-null-only implementation would regress supported behavior. |
| A-3 intentional compatibility difference | GPU helper preserves explicit `nv`, ignores visibility for zero requested GPUs, validates positive allocations, and keeps raw tokens out of persisted executor evidence | Retain upstream. Old local code clears explicit passthrough and exposes allocation tokens. |
| A-4 intentional compatibility difference | AFTEROK rendering rejects empty/trailing/comma-separated invalid tokens and initial punctuation; whole-run mode is a distinct owner | Retain those corrections and executable Bash tests, while correcting the separate A-9 newline gap. Do not restore raw visibility printing or apply per-stage rules indiscriminately. |
| A-5 already implemented | Plain conversion accepts Mapping recursively; refreeze/thaw returns detached mutable values and rejects unsupported nested values | Retain upstream; no second serialization mechanism or schema change. |
| A-6 existing capability to retain | Static-slot provider distinguishes deferred capacity from failure; current resident daemon has independent ownership/terminal/physical-release paths; its supervisor requires group containment | Retain current daemon behavior. This does not certify legacy LocalQueueDispatchAdapter; see A-10. |
| A-7 missing capability / design risk | Apptainer executor does not pass reliability timeout; its runner uses `subprocess.run(timeout=...)`; ordinary subprocess timeout kills the immediate worker only | Neither runner is evidence of complete descendant cleanup. Resolve ownership and prove cleanup before enabling container timeouts. The ordinary subprocess executor redesign is not automatically included. |
| A-8 missing capability | `_with_runtime_resources` provides typed container intent, but `build_apptainer_exec_command` emits no CPU/memory flags | Add mappings at the existing command boundary with truthful host-dependent enforcement claims. |
| A-9 confirmed defect | AFTEROK `_gpu_allocation_lines` parses the environment with line-oriented Bash `read`; a valid first line followed by a newline is accepted, although Python rejects the complete value | A malformed allocation environment reaches the stage and is forwarded to container variables. Reject the invalid complete value before `read`, retain redaction, and extend the executable grammar test during the resource phase. |
| A-10 confirmed defect / missing coverage | Legacy `local.py` starts a process group but `inspect` releases assignment/scalar leases after immediate-root `poll`; an inherited-group child can still be alive | Conflicts with Stage 23 descendant ownership. Requires a bounded legacy process-group settlement observation and real root-first-exit regression, separate from the validation guard. Resolve its composition within the timeout design gate before changing lifecycle behavior. |
| A-11 confirmed validation defect | The unchanged upstream `test_slurm_ready_stage.py:_exercise_mixed_route_run` compares entire submission records around rejected registration while live `reconcile_once` can refresh `scheduler_observed_at` through `slurm_submissions.observe` | Full Phase 1 gate: 2,793 passed, one failure solely from a one-second timestamp refresh. A bounded test-only correction will hold the existing daemon `_cycle_lock` across the before/request/after no-mutation assertion. Keep complete record comparisons and concurrent-registration coverage; no production queue change. Independent phase review must include this correction. |

### Historical Brief Reconciliation

The original brief describes whole-run controller cycles and static assignment,
not the newer per-stage scheduler contract. Relevant outcomes are concurrent
progress, temporary-capacity deferral, exclusive bindings, fenced ownership,
cleanup/release, and restart conservatism. Current `assignments.py`, queue
controller/adapters, and daemon/agent execution own those outcomes. Preserve
the newer distinction between logical terminal state and physical settlement:
the brief's shorthand "process exits -> release everything" is not a sufficient
release rule for a descendant-owning managed route. Its proposed type names,
default concurrency choices, and implementation slices are historical evidence,
not new acceptance criteria.

### Baseline Validation And Independent Disposition

Fresh targeted baseline run covers runtime options/profiles, CLI run/plan/
validate, plain serialization, direct Apptainer, executable SLURM rendering,
runtime-profile and SLURM planning integration, CLI dry-run E2E, assignments,
agent supervisor, daemon production, and queue lifecycle. Result: **236 passed
in 344.84 seconds** at the unchanged source revision above, using the worktree's
locked `.venv/bin/python -m pytest -q`. This is targeted baseline evidence, not
the final implementation gate or a live-container receipt.

Independent reviewer: **pass for baseline dispositions and Phase 1 port**, with
A-1, A-9, and A-10 confirmed and assigned to bounded owners. The reviewer
independently checked source, tests, and docs, and reproduced legacy root-exit
with a live inherited-group child. It distinguished the current resident daemon
from the legacy adapter rather than certifying all managed routes together.
The manager accepted these findings and verified the referenced owner paths.
Each finding must name a supported producer,
violated accepted contract, consequence, and smallest correction. Optional
hardening and unrelated upstream defects remain explicitly separate.

A synthetic in-memory composed-config probe through public `main(["validate",
..., "--check-targets", "--format", "json"])` reproduced A-1 with the locked
dependency: the outer stage plus generic service, pipeline metadata, factory-init
target, and stage-config target were all constructed; exit 0, target count 5.
Only the outer stage and generic service should be independently constructed
(count 2). The outer factory receives frozen mapping data under the existing
stage-spec contract, not necessarily a mutable `dict`; regression fixtures must
check mapping contents and construction events, not change that contract.
Composition was replaced with an in-memory fixture in this diagnostic only;
the implemented regression must also exercise authored config composition.

A separate real-Bash probe of `render_slurm_script` at the baseline revision
confirmed A-9 without submitting a job: request two GPUs; `0,1` passes both
validators; `0,1\n` and `0,1\ninvalid` fail Python validation but the generated
script exits 0 and reaches a harmless `/usr/bin/true` launcher. `0,1\r` already
fails both. The reachable producer is an inherited or prelude-authored
allocation environment. Add a bounded complete-value rejection rather than a
new GPU parser/registry or new allocation semantics.

A fresh real-process probe of `SubprocessApptainerExecRunner` reproduced A-7:
an owned Python parent launched a non-detached child, then exceeded a 0.2-second
deadline. The runner returned `timed_out=True` while the child remained alive.
The fixture used a process-local Linux subreaper and reaped that child after its
bounded 0.8-second lifetime; no fixture process remained. This proves a runner
gap, not that every actual Apptainer invocation leaks children.

## Minimum Useful Change

The first independent increment is a validation-only projection that omits
stage-owned subtrees from generic target construction. The second extends
existing container resource intent into runtime flags. Neither needs a public
registry, durable record, extra config namespace, new dependency, or queue
change. Timeout support is the third increment and cannot inherit an unproven
process-cleanup guarantee from either existing command runner.

## Functional Requirements

| ID | Required behavior | Scope / dependencies | Validation | Status |
| --- | --- | --- | --- | --- |
| FR-1 | Check outer factories and unrelated generic targets, keeping stage config, factory init data, and pipeline metadata inert for generic traversal | Preserve opt-in warning, counts, static default, and input immutability | Public CLI constructor markers; invalid factories and generic targets | approved intent |
| FR-2 | Map supported direct-container CPU/memory requests without changing GPU or SLURM ownership | Current resource contracts; no implicit physical allocation | Conversion/rejection, capabilities/preflight, runtime acceptance | approved intent |
| FR-3 | Deadline, bounded termination/escalation, observation/reaping, primary and cleanup context; no success after timeout or unresolved containment | Resolve stage versus outer cleanup owner; no capacity release solely on launcher exit | Real child-process fixtures and suitable container check | design investigation |
| FR-4 | Preserve run roots, GPU redaction/grammar, serialization, managed deferral/exclusivity/release/restart | Current published behavior, not old patch parity | Baseline audit and regression suites | baseline audit accepted; bounded corrections assigned |
| FR-5 | Independent baseline and implementation reviews; local validation; ordered PRs and merges to develop; final integrated review | Preserve original checkout, refresh base between phases | Exact revision receipts and remote merge evidence | required |

## Functionality Agreement

| ID | Requirement IDs | Decision | Evidence / tradeoff | State |
| --- | --- | --- | --- | --- |
| FQ-1 | FR-1 | Stage factory checking owns factory construction; generic checking cannot interpret stage-owned data | Trusted targets outside those areas still run on explicit consent | locked |
| FQ-2 | FR-2 | Preserve current positive integer CPU/count and positive memory binary-unit contracts | Runtime support for fractional CPUs does not broaden Loom's resource contract | repo-resolved |
| FQ-3 | FR-3 | Supported children obey containment ownership; arbitrary detaching/malicious processes are not a sandbox guarantee | Stop for a materially broader ownership redesign; earlier increments may land | locked |
| FQ-4 | FR-4, FR-5 | Retain corrected upstream behavior and independently review new changes | More evidence than a patch copy, no upstream overwrite | locked |

## Behavior Baseline

Default validation remains static. `--check-targets` remains permission to import
and construct trusted outer factories and other applicable generic targets; it
is not globally side-effect-free. Stage constructors themselves can execute
project code. Filtering must not mutate the composed config or alter the
factory check's argument semantics.

Resource requests are logical requirements, not resource allocation. Direct
CPU/memory options request host-runtime enforcement; generation alone proves no
cgroup enforcement. Unsupported mappings must fail explicitly. SLURM-owned
limits stay separate. A successful process exit cannot override timeout or
unresolved cleanup evidence.

## Minimum Design

- Validation: build a detached generic-check view in the CLI adapter, omitting
  the pipeline-owned mapping (including metadata, stage config, and factory init);
  retain the existing stage checker and unrelated generic checking. The Phase 1
  card records the source-backed ownership rationale. No Weave change or
  alternate instantiation mechanism.
- Resources: extend direct Apptainer command construction over existing
  `ContainerResourceIntent`. Reuse `ResourceRequest` semantic validation;
  conversion owns exact representability in runtime units. Preserve independent
  GPU projection and metadata redaction. Update current capability/preflight
  owners and docs, not a new registry.
- Timeouts: investigation must identify the launch containment mechanism, worker
  owner propagation, supported child obligations, and positive-cleanup proof.
  Agent/SLURM supervision is evidence of needed ordering, not permission to
  import queue internals into the low-level container runner.
- The direct worker command currently enters `cli/stage.py`, then
  `run_stage_worker`, `execute_stage_worker_request`, and
  `reconstruct_stage_execution_request`, which explicitly constructs a
  stage-owned context. A process-group-only redesign must not leave that fact
  unchanged while assuming stages no longer establish their own groups.
  Conversely, merely labelling the worker outer-owned creates no containment.
  Investigate runtime PID-namespace supervision and/or a narrowly propagated
  launcher-owned context together with the actual runtime's process topology.
- Check composition with historical `LocalQueueDispatchAdapter` as well as the
  newer resident supervisor: introducing a new session beneath an existing
  enclosing group can escape its cancellation boundary. A material cross-owner
  redesign must pause the timeout phase for a separate maintainer decision.
- No changes to scientific fingerprints, run-root defaults, serialized worker
  schemas, remote submission, or public ownership enum are assumed.

## Complexity Delta

| Addition | Current necessity | Simpler alternative | Decision |
| --- | --- | --- | --- |
| Detached validation projection | Generic traversal constructs stage-owned nested targets | Skip only outer path, which does not stop traversal | keep |
| CPU/memory argv mapping | Typed intent currently produces no runtime options | Advisory intent only does not meet approved behavior | keep |
| Container lifecycle boundary | Launcher-only timeout does not prove descendant cleanup | Reuse existing immediate-child kill, which is insufficient | design required |
| New registry, daemon supervisor import, durable cleanup ledger | No demonstrated need for these particular mechanisms | Extend existing owner at its boundary | defer |

## Design Agreement

| ID | Requirement IDs | Decision | State |
| --- | --- | --- | --- |
| DQ-1 | FR-1 | CLI owns validation projection; source config and stage constructor semantics stay unchanged | locked |
| DQ-2 | FR-2 | Positive integer CPUs; memory converts exactly to integer bytes; no silent rounding, zero-as-unlimited, or attribute reinterpretation | repo-resolved |
| DQ-3 | FR-3 | Close ownership and mechanism investigation before enabling timeouts or advertising enforcement | open investigation |
| DQ-4 | FR-5 | One phase worktree/PR each; independent correctness review and exact-tree local gates; final integrated review | locked |

## Expanded Design Review

Pending after the minimum timeout design is supported by source and runtime
evidence. A new ownership framework or materially broader public contract must
be presented to the maintainer separately, as required by the approved draft.

## Examples And Validation

| Invariant | Authoritative owner / boundary | Minimal coverage |
| --- | --- | --- |
| Outer checked, nested data inert | CLI adapter / trusted constructor boundary | Harmless marker constructors through public CLI, invalid outer and unrelated targets, exact counts/warnings, no mutation |
| Two CPUs and 512 MiB become `--cpus 2 --memory 536870912` | Resource validator and direct argv conversion | Units, positive/integer constraints, unrepresentable bytes, flags before image, no-request path |
| Flags do not prove host enforcement | Runtime CLI/cgroups and preflight docs | Unsupported runtime fails clearly; small real-runtime receipt or explicit unavailable prerequisite |
| No successful admission following timeout | Executor's outcome and cleanup boundary | Result written before deadline, root-first exit, children, TERM resistance, interruption, cleanup uncertainty, normal success |
| No upstream regression | Existing serialization/runtime/GPU/managed owners | Targeted baseline plus phase-relevant and final integrated suites |

Combined tests are required where outcomes interact: timeout and early result,
parent exit and surviving child, cleanup failure and original timeout, or GPU
projection and protected metadata. No speculative Cartesian matrix is required.
Final commands for each implementation phase are `make validate-pr` and
`make test-summary`, with evidence invalidated by relevant tree changes.

## Phase Shaping

Approved ordering is audit, validation guard, CPU/memory mapping (including
A-9), lifecycle-safe timeouts, then integrated review. The compact manifest
links three phase cards. Phase 1 has a complete bounded executor packet and its
startup gate is ready. Phase 2 awaits its predecessor and runtime prerequisites.
Phase 3's card explicitly forbids execution until its lifecycle design is
reviewed, including the separately identified legacy A-10 correction. This
staged readiness follows the maintainer's explicit instruction that earlier
increments may land while a broader timeout design is presented separately.
The full objective remains incomplete until all accepted outcomes are achieved.

## Quality Gate

| Check | Evidence | Result |
| --- | --- | --- |
| Behavior and scope authorized | Maintainer-supplied selective-port objective | pass |
| Dirty checkout preserved and fresh locked baseline | Revision and preservation receipts above | pass |
| Upstream audit independently accepted | Independent source/contract review; 236 passing baseline tests; A-1/A-9/A-10 dispositions recorded | pass |
| Minimum timeout design justified | Ownership investigation in progress | pending |
| Detailed phase traceability and startup readiness | FR-1 maps to a complete Phase 1 card; later phases retain explicit gates | pass for Phase 1 only |
| Required reviews and final checks defined | FR-5 and validation table | pass |

Gate result: ready to implement Phase 1. Phase 3 remains unapproved for product
execution pending its expanded design review; this is not a complete-stage gate.

## Decisions And Deferrals

The host has SingularityCE 3.10.4; availability/version alone is not a real
container acceptance receipt. The official
[SingularityCE 3.10 resource guide](https://docs.sylabs.io/guides/3.10/user-guide/cgroups.html)
and [Apptainer resource guide](https://apptainer.org/docs/user/latest/cgroups.html)
document CPU/memory flags and host cgroup requirements. Non-root enforcement
depends on delegated unified cgroups v2 with compatible systemd/runtime setup.
Do not change host administration or claim runtime enforcement from help output.
Unavailable runtime checks remain visible limitations, not passing results.

Superseded dirty source retirement, the old rphys Stage 81 goal, and unrelated
roadmap work remain outside this stage. Refresh published develop and reassess
overlapping source owners before every implementation phase.

# Phase 6 Execution Plan: GPU, VRAM, And Preference Placement

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 6
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p6-gpu-preference-placement`
- Worktree root and path: `/home/can134/work/active/loom-worktrees` and
  `/home/can134/work/active/loom-worktrees/stage-29-p6-gpu-preference-placement`
- Base revision: clean `origin/develop`
  `34acb214b8c9e09a442637021742fbc7b4104257`
- PR target: `develop`
- PR title: `feat(scheduling): add GPU and preference placement`
- Dependencies: Phase 5A [PR #240](https://github.com/samcantrill/loom/pull/240)
  squash-merged as `5116f18` with authenticated multi-agent CPU/memory
  scheduling, remote assignment/data execution, exact capacity accounting, and
  crash-replay closure; Phase 1 provides generic resource/rule/policy contracts
- Workflow path: expanded because exact device/provider accounting and
  wait-then-fallback preference ranking interact at the production assignment
  boundary; use one bounded phase-planner refinement and one independent review
- Blockers: none. Opt-in hardware evidence is optional and must not block
  simulated/default CI.

## Objective And Context

- Vertical outcome: a stage may request exact GPU behavior and VRAM capacity;
  Loom excludes incapable agents/devices, binds exact eligible devices or
  enforceable share atoms, and then ranks feasible placements using stage-
  relevant GPU/model/agent/packing preferences. CPU-only stages are unaffected.
- Earlier dependency: Phase 5 proves remote execution without GPU-specific
  behavior. This phase must demonstrate that the Phase 1 generic interfaces can
  add a real discrete/provider-bound resource without changing kernel,
  coordinator lifecycle, transport, or authority ownership.
- Later work explicitly out of scope: Phase 7 maps an explicitly routed stage's
  already-canonical hard requirements to one named SLURM profile; Phase 8 owns
  controls/reconfiguration and Phase 9 owns recovery. This phase may expose safe
  GPU diagnostics but cannot submit SLURM work or mutate live providers/
  configurations remotely.

## Current Source And Harness

- Stage 27 ownership is isolated in `src/loom/queue/gpu/local.py`: inventory and
  deterministic layout values, `_LocalGpuAssignmentProvider` device leasing,
  and `CUDA_VISIBLE_DEVICES` binding are reusable evidence, not the production
  Phase 6 provider seam. `src/loom/queue/gpu/nvidia.py` remains optional.
- Reuse `src/loom/pipeline/runtime/scheduling_resources.py` and the Phase 1
  `ResourcePlanner`, exact quantity, capacity atom, descriptor, claim-contract,
  registry, and conformance seams. `src/loom/scheduling/kernel.py` already owns
  hard-before-soft evaluation, checked tier vectors, quality-band fallback from
  immutable `ready_at`/`as_of`, stable ties, and output validation; Phase 6 must
  not reproduce those algorithms.
- Extend the current production seam in
  `src/loom/queue/local_daemon_execution.py`: `LocalDaemonExecution.__init__`
  composes only CPU/memory planners/providers and `_remote_candidates` projects
  only CPU/memory `AgentOffer` capacity. Selected composite claims already flow
  through `_execute`, `ClaimCommand`, and
  `SQLiteAgentJournal.prepare_composite` for local and remote execution.
- `src/loom/queue/agent_sessions.py`,
  `src/loom/queue/agent_session_transport.py`, and
  `src/loom/queue/_remote_stage_execution.py` own the offer, physical admission,
  resident profile, request/claim, and worker-launch boundaries. Remote launch
  currently carries claims but applies no GPU-specific local binding.
- Real GPU/vendor calls remain optional adapters. Deterministic fake inventory
  and providers own required CI coverage; do not add a heavyweight vendor SDK
  without a demonstrated current need.

## Scope

In scope:

- Add safe GPU inventory projection containing only configured manageable
  device identities, model/category, total usable VRAM bytes, supported
  allocation mode/provider, exact granularity where relevant, optional bounded
  topology attributes, health/eligibility state, and planner/provider/
  claim-contract identities. Exclude raw vendor handles, device paths, commands,
  live tokens, serials not required for stable local binding, and unsafe errors.
- Validate and canonicalize the whole GPU inventory/availability opportunity
  once per offer revision through the GPU planner before claim search. Invalid
  device IDs, duplicate capacity, contradictory mode/attributes, bad units/
  granularity, or malformed topology produce a typed ineligible opportunity and
  never reach partial candidate generation.
- Keep configured inventory distinct from current availability. Exclusive
  devices are discrete capacity atoms. Share-capable providers expose exact
  provider-defined VRAM/fraction atoms and live claims already reflected in net
  availability. Provider observation may conservatively withdraw unhealthy or
  externally occupied capacity; raw free-memory sampling never creates a share.
- Add a built-in GPU resource planner and corresponding agent provider adapters
  for explicit modes only:
  - `exclusive`: request a positive integer device count; select exact device
    IDs; per-device minimum VRAM/model/features are eligibility attributes; the
    full selected device atom is consumed;
  - `vram_share`: request exact integer VRAM bytes on one or more explicitly
    described devices only when a named provider advertises enforceable
    isolation, accounting, granularity, preparation, binding, and release;
  - provider-defined fractional mode: accept an exact normalized rational value
    only for a named compatible provider and advertised granularity. Preserve
    the existing numeric `ResourceEntry` shape by using the positive integer
    numerator in `amount`, `unit: share`, and a bounded positive integer
    `share_denominator` attribute; reduce it canonically before matching.
- Never infer sharing from observed free VRAM. Never satisfy one device's 64 GiB
  minimum by summing several 12 GiB devices. A multi-GPU request must state its
  device count and per-device/relationship requirements explicitly.
- Define the guarantee honestly: the planner proves advertised capacity and
  claim feasibility for the declared request, while the provider proves the
  selected binding/isolation mode. Loom does not infer the workload's true peak
  VRAM or guarantee against an under-declared job OOM. Exclusive allocation
  grants the device, not a VRAM usage cap; share/fraction modes may claim caps
  only when the named provider enforces them.
- Normalize all VRAM to integer bytes. Reject binary floating point, implicit
  fractional GPU, unsupported mode, invalid granularity, incompatible planner/
  provider contract, and ambiguous count-versus-capacity requests at admission.
  The `provider` field is a site-allowlisted semantic capability alias; it cannot
  name/import/activate implementation code.
- Bind exact selected device/share identities in the claim, assignment, agent
  journal, worker environment/binding plan, output provenance where already
  appropriate, and release operation. Do not expose unsafe device details to
  unrelated clients.
- Negotiate planner and provider via `ResourceClaimContractDescriptor` while
  retaining their separate component/configuration descriptors. The coordinator
  rejects an offer or candidate when contract/data versions or fingerprints are
  unavailable/incompatible. A restarted/reconfigured provider cannot adopt an
  old live token under a different identity.
- Keep intrinsic GPU requirements in the GPU planner: device count, allocation
  mode, per-device minimum VRAM/model/features, and relationships among the
  selected GPU instances (for example same advertised fabric group). Do not
  duplicate these semantics as built-in hard evaluators. Built-in additive hard
  constraints are for the complete placement: exact agent target,
  allowed/prohibited agent or site attributes, and genuine cross-resource
  relationships.
- Keep hard target distinct from preference:
  - a stage/run hard target makes every other agent infeasible;
  - an ordered preferred-agent rule ranks feasible agents and may fall back;
  - a target that is offline/unsupported remains pending with a specific safe
    reason rather than silently falling back.
- Add built-in soft preferences for ordered GPU model categories, ordered
  agents, resource attributes, and pack/fill behavior. Default is equal agents/
  resources plus deterministic stable tie-breaking. Preferences are attached to
  resolved stage placement, so a training-stage GPU preference does not affect
  preprocess/evaluate stages that do not request that resource.
- Keep pack/fill and agent/model preference distinct from cluster policy.
  They rank feasible placements for one ready stage; they do not account for
  historical user shares, preempt a running assignment, jointly optimize a
  batch, or combine several agents for one distributed/gang stage.
- Separate preference score from waiting behavior. Each resolved preference has
  an immutable ID, site-owned tier/weight, bounded utility range, and declared
  `PREFERRED`/`FALLBACK`/optional `NEUTRAL` quality-band schema. The kernel uses
  checked integer arithmetic to form one total per ordered tier and compares
  vectors lexicographically before a stable identity tie-break; registration
  order and a large lower-tier score cannot change higher-tier precedence.
- An explicit bounded wait-then-fallback gate names one guarded preference. Its
  deadline is `stage_work.ready_at + wait_duration`, and eligibility is
  evaluated from the immutable snapshot `as_of`: only the `PREFERRED` band may
  be selected before the deadline, while declared `FALLBACK` candidates re-enter
  afterward. Restart does not reset the wait. Site policy owns allowed tiers,
  weight bounds, maximum wait, band schemas, and whether a client may request
  them; clients cannot submit raw tiers or weights.
- Preserve default scheduler work ordering across runs. Preferences rank only
  complete feasible candidates for the same stage; their vectors are not
  comparable across unrelated work, do not reorder DAG readiness, and cannot
  make an infeasible candidate valid. An earlier proven-infeasible or exhausted
  work item may be bypassed for later complete feasible work, but partial GPU
  search output is never assignable and exhaustion is never infeasibility.
- Extend public conformance coverage with GPU and a synthetic downstream
  resource/provider demonstrating exact custom capacity atoms and contract
  negotiation. Prove the kernel itself required no resource-specific branch.
- Add safe pending/placement explanations: insufficient device count, per-device
  VRAM too small, model/mode/provider/contract mismatch, target unavailable,
  waiting for preferred, fallback enabled, search exhausted, or local bind drift.
- Add deterministic loopback multi-agent and optional real-GPU receipts using
  abstract `machine-A`/`machine-B` configuration. Required validation must not
  assume hardware exists.

Out of scope:

- Automatic GPU partitioning, sharing without provider enforcement, best-effort
  free-VRAM guessing, combining VRAM across devices for one-device minima,
  arbitrary topology graph optimization, multi-agent/gang stages, preemption,
  fair-share, power/cost policy, or a general solver.
- SLURM directive mapping, external queue capacity, automatic agent/SLURM
  fallback, or pretending managed-agent GPU/model preferences influence SLURM's
  eventual node choice. Phase 7 must map every applicable hard semantic or
  reject its explicit route; soft agent/device preferences are not silently
  transferred.
- Floating licences or globally consumed resources without one explicit
  transactional owner. Future resource kinds may use the generic interfaces but
  are not Stage 29 deliverables.
- Vendor provisioning, driver installation, automatic hardware discovery into
  policy, remote provider loading, or claiming performance/health beyond the
  configured provider evidence.
- General host telemetry/load prediction or treating unaccounted external GPU
  processes as schedulable capacity. Sites must withhold capacity a provider
  cannot safely observe/control.

Assumptions:

- An exclusive provider can bind stable local device identities for the lifetime
  of an inventory revision and assignment.
- Authored resource estimates and project code are trusted workload input; the
  scheduler prevents known impossible placement but does not infer peak usage.
- VRAM-share/fractional support is enabled only when a real selected provider can
  enforce its advertised semantics; otherwise those modes fail closed.
- Site configuration defines any default model/agent order. Loom ships neutral
  deterministic behavior rather than assuming H200/H100/A100 policy globally.

## Fixed Contracts And Private Discretion

### Request semantics

Examples remain explicit:

```yaml
# One exclusive device with at least 64 GiB on that device.
resources:
  entries:
    gpu:
      kind: gpu
      amount: 1
      unit: count
      attributes:
        allocation_mode: exclusive
        minimum_vram: {amount: 64, unit: GiB}
```

```yaml
# Ten GiB of an enforceable share from one named provider.
resources:
  entries:
    gpu:
      kind: gpu
      amount: 10
      unit: GiB
      attributes:
        allocation_mode: vram_share
        provider: configured-share-provider
```

The second request is invalid unless the selected agent/provider advertises the
matching contract and exact granularity. It is not treated as 0.125 of an 80 GiB
device by generic arithmetic.

```yaml
# One half of a provider-defined enforceable share; never authored as 0.5.
resources:
  entries:
    gpu:
      kind: gpu
      amount: 1
      unit: share
      attributes:
        allocation_mode: provider_fraction
        share_denominator: 2
        provider: configured-fraction-provider
```

Here `amount / share_denominator` is the exact requested rational. Numerator and
denominator must be bounded positive integers, reduced to canonical form, and a
multiple of the provider's advertised rational granularity. A different unit,
missing provider, zero/negative denominator, binary float, or an equivalent but
off-granularity encoding is rejected during resource validation/resolution
before admission; a reducible rational is persisted in canonical reduced form.
This encoding is local to the named GPU mode; it does not widen CPU or every
`ResourceEntry` into an unrestricted fractional quantity language.

### Hard then soft

```python
search = kernel.generate_complete_candidates(stage, snapshot, budget)
if search.outcome is COMPLETE:
    feasible = kernel.apply_mandatory_and_hard_rules(search.candidates)
    scored = kernel.apply_checked_tier_preferences(feasible)
    eligible = kernel.apply_fallback_gate(scored, as_of=snapshot.as_of)
    work_evaluation = kernel.group_work(stage, eligible)
```

The policy later selects only an existing work/candidate pair from grouped work
evaluations. The kernel validates that every scored/selected ID came from the
same complete current candidate set and that all required evaluators ran.
Preferences contribute bounded utility/band evidence only after feasibility;
the kernel owns weights, tier totals, fallback eligibility, and stable ties.

### Example placement

```text
machine-A: gpu0 = 12 GiB
machine-B: gpu0 = 80 GiB
request:   one exclusive GPU, minimum_vram = 64 GiB

machine-A -> hard REJECT (per-device VRAM)
machine-B -> feasible
```

If both are feasible, stage-specific model/agent preferences rank them. A CPU-
only preprocess stage evaluates no GPU-model preference and remains eligible on
either CPU/memory-capable agent.

### Exact capacity and bind

Exclusive claims reserve the full exact device atom. Share claims reserve exact
provider-defined atoms. The agent revalidates device state and contract before
acceptance; drift causes definitive decline or indeterminate reconciliation,
never substitution with an unrecorded device.

### Private discretion

Candidate enumeration heuristics, private GPU inventory adapter layout, score
normalization helpers, and topology data representation remain changeable within
the bounded schemas. The executor may not add implicit sharing, resource-specific
kernel branches, or allow preferences to change feasibility.

## Proportionality

- Reuses Stage 27 GPU seams and the generic Stage 29 planner/provider contracts.
- Adds only GPU as the current concrete discrete/share resource and the accepted
  target/preference behaviors. Generic future resources remain possible through
  protocols rather than implemented speculatively.
- Separating this phase from initial remote execution lets reviewers verify that
  the generic core remains generic and isolates hardware-specific failure modes.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Per-device VRAM is not aggregate VRAM | GPU planner | Ambiguous request/inventory | Placement known not to satisfy the declared minimum | 12/80 GiB and multi-device tests; no broader OOM claim |
| Offered capacity is provider-accounted manageable capacity | Agent configuration + provider observation | Unaccounted external occupancy or best-effort telemetry | Overcommit beside non-Loom use | External occupancy withdrawal, withheld-capacity, and raw-free-memory negative tests |
| GPU intrinsic semantics have one owner | GPU planner | Duplicate hard evaluator or malformed opportunity | Planner/rule disagreement about count, mode, model, or topology | Opportunity validation and no-duplicate-rule tests |
| Sharing requires enforceable named provider | Validator/planner/provider negotiation | Free-VRAM observation, float, malformed rational, or request text | Unsafe oversubscription | Unsupported/mismatch/canonical-rational/granularity tests |
| Exact selected devices/shares conserve | Coordinator atoms + agent provider | Concurrent assignments/pool views | Device collision | Barrier/property/release tests |
| Planner/provider/contract identities agree | Composition and assignment validation | Restart/config drift | Wrong binding semantics | Version/fingerprint/restart tests |
| Complete intrinsic feasibility and hard rules precede preferences | GPU planner + scheduling kernel | Exhausted search, scorer, or policy | Omitted/bad device or preference bypasses feasibility | Exhaustion, invalid-output, and scoring mutation tests |
| Preference precedence and fallback are restart-stable | Kernel tier aggregation and durable-time gate | Client weights, registration order, overflow, or restart clock | Wrong device/agent or premature fallback | Tier/weight overflow, band, stable-tie, and restart-`as_of` tests |
| Preference applies only to relevant stage/resource | Placement resolver/scorer | Run-wide default | CPU work unnecessarily constrained | CPU preprocess/GPU train tests |
| Target and preference are distinct | Hard evaluator versus scorer/policy | User config | Silent fallback or unnecessary pending | Offline target/preferred fallback tests |
| Kernel remains resource-neutral | Scheduling package boundary | GPU implementation | Core coupling | Import/source contract plus synthetic resource test |

## Implementation Slices

1. Add GPU request/inventory/availability/claim schemas, exact exclusive and
   provider-gated share/fraction semantics including the integer numerator/
   denominator encoding, safe offer projection, claim-contract negotiation, and
   validation/unit/conformance coverage.
2. Implement GPU planner and agent provider adapters with exact device/share
   bind/reconcile/activate/release, composite CPU/memory/GPU admission, and
   concurrency/drift/crash tests.
3. Keep GPU-intrinsic requirements in the planner; add only the concrete
   complete-placement target/agent/cross-resource rules and stage-relevant
   agent/model/attribute/packing scorers and registrations. Reuse the kernel's
   existing checked site-tier vectors, quality bands, durable-time fallback,
   validation, and stable ties; add focused integration and permutation tests.
4. Integrate multi-agent GPU stage execution, synthetic downstream resource,
   status/docs/config examples, simulated E2E, and optional real-GPU receipt.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | GPU adapters do not pollute generic imports | Scheduling core remains vendor/driver free |
| Unit | Required | Request modes, exact units, complete candidate feasibility/scoring | Count/bytes/rational boundaries; malformed opportunity; per-device VRAM; tier dominance/overflow; target/preference/band/fallback restart |
| Contract | Required | Planner/provider and custom resource behavior | Negotiated contract, stable namespaced atoms, complete/exhausted search, validated claims, partial prepare, malformed/unknown versions |
| Integration | Required | Global capacity and exact bind | Concurrent device claims, pool overlap, external occupancy withdrawal, drift decline, release and retry |
| E2E / opt-in | Required simulated; optional GPU | Stage-specific placement | CPU preprocess/GPU train across logical agents; optional configured hardware receipt |

Targeted commands:

    .venv/bin/pytest -q tests/unit/loom/pipeline/test_runtime_resources.py tests/unit/loom/scheduling/test_kernel.py
    .venv/bin/pytest -q tests/unit/loom/queue/gpu/test_local.py tests/contracts/test_local_gpu_assignment_provider.py tests/contracts/test_local_gpu_inventory_provider.py
    .venv/bin/pytest -q tests/unit/loom/queue/test_remote_stage_execution.py tests/integration/queue/test_agent_session_transport.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: treating total VRAM as per-device, inferring isolation from free
  VRAM, hidden provider consumption, duplicating planner semantics in hard
  rules, assigning from incomplete search, score overflow/client policy abuse,
  restart-relative fallback, preference leakage to unrelated stages, or
  provider identity drift; or implying that a declared request guarantees actual
  peak use or prevents OOM.
- Review focus: exact mode semantics, atom conservation, final binding,
  planner/provider/contract separation, hard-before-soft, and generic core
  independence.
- Stop if: a requested share mode lacks enforceable provider semantics; Stage 27
  device identity cannot be made stable for one inventory revision; a resource
  needs hidden capacity outside atoms; or implementing GPU requires database/
  provider logic inside `loom.scheduling`.
- Accepted debt: complete bounded heuristics may report `EXHAUSTED` rather than
  assign from an unproven partial prefix, and default FIFO can starve large
  jobs. Revisit proof contracts or fairness only with measured demand.

## Executor Handoff

- Read this file from `Current Source And Harness` through `Risks, Review, And
  Stops`, the Phase 5A completion record, and the manifest resource/security
  constraints cited here.
- Prove exact simulated behavior before optional hardware tests. Do not make
  default CI depend on a GPU or vendor library.
- Decisions not to revisit: integer CPU, byte-exact VRAM, explicit GPU modes,
  per-device minima, planner-owned intrinsic GPU feasibility, complete-only
  search, generic kernel, hard-before-soft, site-tier/band/fallback algebra,
  target/preference separation, and provider-gated sharing.
- Escalate any need for implicit sharing, aggregated per-device minima, a new
  global resource owner, general solver, or heavyweight dependency.

## Workflow State

- Manager preparation: complete at clean `origin/develop` `34acb21`; dedicated
  branch/worktree, repository `samcantrill/loom`, verified Phase 5A merge,
  current Stage 27 and Phase 5A source owners, target/title, tests, and stop
  conditions recorded
- Expanded planning: one bounded refinement pending for the exact provider/
  offer/binding composition and already-owned preference algebra
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: required after the manager gate because GPU claims cross
  configured inventory, coordinator selection, agent physical binding, and
  worker environment boundaries
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | pending |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | pending |
| PR, review, and merge | pending |
| Residual risk and cleanup | pending |

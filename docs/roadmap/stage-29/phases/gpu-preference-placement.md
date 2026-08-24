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
- Blockers: none. Opt-in hardware evidence is optional and does not block the
  simulated/default validation gate.

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
  currently carries `ResourceClaim` values unchanged into journalled
  `ClaimCommand`s but applies no GPU-specific local binding. The existing claim
  fingerprint covers its contract, exact atoms, provider-data version, and
  provider data; reuse that identity rather than introducing a second GPU lease
  or assignment identity.
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
- Preserve one exact opportunity-to-release identity chain. The offered GPU
  opportunity is tied to the agent/session and config/inventory/availability
  revisions plus the planner, provider, and claim-contract descriptors. The
  selected claim names its safe configured device/share identity through exact
  atom keys and bounded versioned provider data. The coordinator persists and
  delivers that claim unchanged with its descriptor evidence; the agent
  journals the same claim fingerprint before provider preparation, maps only
  that configured identity to its local worker binding, and releases using the
  same assignment-scoped claim. Missing, stale, or mismatched identity declines
  or becomes indeterminate; no layer may substitute another feasible GPU.
- Keep local binding values, vendor handles, live provider tokens, device paths,
  and daemon credentials agent-local. They do not become capacity keys,
  provider data, decision evidence, work-request metadata, status, or output
  provenance. The concrete way an activated provider contributes its binding
  to the already-sanitized worker environment remains private, provided the
  launcher receives only the binding derived from the journalled selected claim.
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
- Each concrete agent/model/attribute/packing scorer implements the existing
  `PreferenceScorer` boundary and returns only its bounded integer utility and
  declared quality band for a complete feasible candidate. It does not combine
  scorers, apply a site weight or tier, decide fallback eligibility, compare
  candidates, or break ties. Do not add a GPU preference engine, composite
  scorer, score-normalization layer, or packing policy beside the kernel.
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

The cross-owner equality is the `ResourceClaim` fingerprint together with the
assignment's planner/provider/claim-contract descriptor evidence and offer
revisions. Safe configured device/share IDs appear in the claim's atom keys or
bounded provider data; an agent-local mapping may translate those IDs to worker
binding values only after exact descriptor/config matching. Prepare, activate,
reconcile, and release reuse the journalled claim and assignment identity.
Binding values and provider live tokens are deliberately not part of the
coordinator-visible identity.

### Concrete scorer composition

Agent, GPU-model, resource-attribute, and pack/fill scorers independently read
the existing complete `Candidate` and selected claims plus their one resolved
`PreferenceSpec`. Each emits only a `PreferenceResult` containing bounded
`PreferenceScore(utility, quality_band)` evidence.
The existing kernel remains the sole owner of utility bounds, checked
weighting/addition, ordered tier vectors, durable-time band eligibility,
candidate comparison, and stable tie-breaking. Packing is therefore a
placement-local preference over currently advertised feasible capacity, not a
new capacity owner or cross-work batching algorithm.

### Private discretion

Candidate enumeration heuristics, private GPU inventory adapter layout, the
agent-local configured-ID-to-binding mapping, individual scorer utility
formulas, and topology data representation remain changeable within the bounded
schemas. The executor may not add implicit sharing, a second durable GPU claim/
lease record, resource-specific kernel branches, or allow preferences to change
feasibility.

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
| Selected GPU/provider identity survives selection through release | Coordinator assignment plus agent journal/provider | Offer/request codec, provider preparation, local binding mapping, or replay/release substitutes or drops the selected safe identity | The worker uses or releases a different GPU/share than the coordinator reserved | One simulated decision-to-worker-to-release trace with distinct safe IDs and local bindings; descriptor/config drift negative |
| Planner/provider/contract identities agree | Composition and assignment validation | Restart/config drift | Wrong binding semantics | Version/fingerprint/restart tests with no adoption or substitution |
| Complete intrinsic feasibility and hard rules precede preferences | GPU planner + scheduling kernel | Exhausted search, scorer, or policy | Omitted/bad device or preference bypasses feasibility | Exhaustion, invalid-output, and scoring mutation tests |
| Concrete scorers contribute only bounded utility/band evidence | Concrete scorer; kernel owns composition | Agent/model/attribute/packing scorer reimplements tiers, weighting, fallback, or ties | Scorer order or duplicated algebra changes the selected feasible placement | One causal pair per scorer plus mixed-scorer tier/weight/band and permutation tests through the real kernel |
| Preference precedence and fallback are restart-stable | Kernel tier aggregation and durable-time gate | Client weights, registration order, overflow, or restart clock | Wrong device/agent or premature fallback | Existing kernel tier/weight overflow, band, stable-tie, and restart-`as_of` coverage plus concrete-scorer integration |
| Preference applies only to relevant stage/resource | Placement resolver/scorer | Run-wide default | CPU work unnecessarily constrained | CPU preprocess/GPU train tests |
| Target and preference are distinct | Hard evaluator versus scorer/policy | User config | Silent fallback or unnecessary pending | Offline target/preferred fallback tests |
| Kernel remains resource-neutral | Scheduling package boundary | GPU implementation | Core coupling | Import/source contract plus synthetic resource test |

## Implementation Slices

1. Carry GPU-specific validated data in the existing resource request,
   inventory/availability opportunity, and `ResourceClaim` envelopes; add exact
   exclusive and provider-gated share/fraction semantics including the integer
   numerator/denominator encoding, safe offer projection, claim-contract
   negotiation, and validation/unit/conformance coverage. Do not introduce a
   parallel authored or durable GPU schema.
2. Implement GPU planner and agent provider adapters with exact device/share
   bind/reconcile/activate/release. Preserve the selected claim fingerprint and
   descriptor/config evidence through delivery and the agent journal, derive
   the worker binding from that exact safe configured identity, and reuse it for
   release; add composite CPU/memory/GPU concurrency/drift/replay tests.
3. Keep GPU-intrinsic requirements in the planner; add only the concrete
   complete-placement target/agent/cross-resource rules and stage-relevant
   agent/model/attribute/packing scorers and registrations. Each scorer returns
   only bounded utility/band evidence and reuses the kernel's checked site-tier
   vectors, durable-time fallback, validation, and stable ties; add focused
   causal integration and permutation tests without a Cartesian scorer matrix.
4. Integrate multi-agent GPU stage execution, synthetic downstream resource,
   status/docs/config examples, simulated E2E, and optional real-GPU receipt.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | GPU adapters do not pollute generic imports | Scheduling core remains vendor/driver free |
| Unit | Required | Request modes, exact units, complete candidate feasibility and concrete scorer composition | Count/bytes/rational boundaries; malformed opportunity; per-device VRAM; for each agent/model/attribute/packing scorer, candidates differ only in that input and reversing the resolved preference reverses their ranking; an infeasible candidate remains rejected |
| Contract | Required | Planner/provider identity and custom resource behavior | Negotiated descriptors and contract, stable namespaced atoms, unchanged claim codec/fingerprint, complete/exhausted search, validated claims, partial prepare, malformed/unknown versions; a changed provider/config/contract cannot adopt or substitute the claim |
| Integration | Required | Global capacity and exact physical bind/release | Concurrent device claims and pool overlap; use different safe configured IDs and local binding values, assert the selected claim fingerprint is journalled, the worker receives only its mapped binding, and release receives the same claim after replay; external occupancy and mapping/descriptor drift fail closed without launch or substitution, using the exact decline/indeterminate outcome supported by evidence |
| E2E / opt-in | Required simulated; optional GPU | Stage-specific placement across the real selection and launch path | On abstract agents with multiple feasible models, a GPU preference causally selects the expected claim, its exact local binding reaches the GPU-train worker, and the same claim releases; changing only the model preference changes selection. CPU preprocess carries no GPU claim/binding. Optional configured hardware receipt |

Required scorer composition coverage uses the concrete registered scorers
through `SchedulingKernel`, not direct scorer-output assertions alone. One mixed
case proves a higher tier dominates every allowed lower-tier total, weights are
applied once, fallback bands use the existing immutable `ready_at`/`as_of`
gate, and registration/candidate permutation preserves the stable decision.
These dimensions share the kernel composition path; the independent scorer
formula cases remain focused pairs rather than a Cartesian matrix.

The required simulated identity trace starts from an offered opportunity and
records the coordinator decision, delivered/decoded claim, journalled
`ClaimCommand`, provider prepare/activate input, launched worker environment,
and release input. Assert equality of claim fingerprint, exact atoms, contract,
provider-data version/data, and retained component descriptors at every
applicable boundary. Give safe configured IDs and agent-local binding values
deliberately different strings so accidental use, recomputation, or substitution
cannot pass. Optional real-GPU evidence supplements but never replaces this
trace.

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
  rules, dropping or substituting the selected safe GPU/provider identity at
  delivery/binding/release, assigning from incomplete search, letting a
  concrete scorer duplicate tier/weight/fallback/tie algebra, score overflow/
  client policy abuse, restart-relative fallback, preference leakage to
  unrelated stages, or provider identity drift; or implying that a declared
  request guarantees actual peak use or prevents OOM.
- Review focus: exact mode semantics, atom conservation, equality of the
  opportunity/claim/descriptors across coordinator selection and agent
  journal/binding/release, absence of coordinator-visible local bindings,
  planner/provider/contract separation, scorer-only utility/band contribution,
  hard-before-soft, and generic core independence.
- Stop if: a requested share mode lacks enforceable provider semantics; Stage 27
  device identity cannot be made stable for one inventory revision; a resource
  needs hidden capacity outside atoms; exact binding/release would require
  exposing a local binding/live token to the coordinator or adding a second
  durable GPU claim/lease owner; the existing descriptor/claim/assignment/
  journal contracts cannot retain the selected safe identity without a new
  public or compatibility decision; or implementing GPU requires database/
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
- The required end-to-end proof must distinguish safe configured GPU/share IDs
  from agent-local binding values and show the same selected claim and component
  identities at coordinator decision, delivery, durable agent preparation,
  worker binding, and release. A collection of isolated codec/provider tests is
  insufficient.
- Exercise each concrete scorer through the existing kernel with causal input
  changes. Scorers stop at bounded utility/band evidence; do not add another
  tier aggregator, fallback gate, stable tie, or packing scheduler.
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
- Expanded planning: complete in this plan revision; the selected safe GPU/
  provider claim is preserved through offer, assignment, journalled physical
  binding, worker environment, and release, while concrete scorers contribute
  only utility/band evidence to the kernel-owned preference algebra
- Implementation: complete at `75cd70a`; the final manager correction separates
  planner and provider identity, fences private GPU binding drift, preserves
  complete configured inventory when availability is withdrawn, carries
  bounded fabric groups through protocol v3, and retains the prior strict offer,
  authored placement, accepted-time fallback, private child-worker environment,
  exact local/remote bind, and CPU-with-GPU-inventory paths
- Refiner: completed one qualified production-wiring correction
- Pre-submit gate: complete; `make validate-pr` passed and `make test-summary`
  wrote the current evidence receipt
- Independent review: complete. It found three reachable blockers: planner and
  provider descriptors were collapsed so retained work could adopt a changed
  private binding; remote inventory was reconstructed from net availability;
  and protocol GPU descriptors could not represent authored fabric groups. It
  also found one stale protocol-version diagnostic. Final correction `75cd70a`
  closes all four findings, and manager verification found no residual blocker.
- Blocker corrections: 3/3; no further correction or review pass is available
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | `fd03da0` adds the GPU primitives, `847e302` wires the first production path, `40e9332` completes the initial hard cut-over, and final correction `75cd70a` closes the independent-review findings. Planner descriptors now remain coordinator scheduling evidence while distinct provider descriptors use a non-secret configuration fingerprint derived from exact manageable atoms and private bindings. Provider identity crosses offer, decision, delivery, journal, prepare/activate/reconcile/release, and retained restoration. Remote GPU inventory uses every configured descriptor while availability uses only offered atoms; unhealthy devices remain inventory facts but cannot be offered. Strict GPU descriptors carry optional bounded `fabric_group`. Share/fraction descriptors remain exact but production configuration rejects those modes until an enforceable provider adapter exists. |
| Tests added or updated | Unit coverage proves exact GPU modes, canonical rationals, strict offer/policy codecs, scorer causality, tier dominance, fallback deadlines, unhealthy-device withdrawal, and binding-drift rejection. Production integration proves positive and negative multi-device fabric placement. The loopback trace withholds one busy configured remote GPU while selecting another, reverses only model preference to select distinct local/remote devices and private bindings, proves CPU stages receive no CUDA binding, checks child-process isolation, and asserts distinct planner/provider identity is unchanged across coordinator receipt, delivered request, journalled command, release, and protected-store redaction. Valid-path configs/examples omit zero GPU entries; rejection coverage owns the hard-cut behavior. |
| Validated revision/tree state and evidence | Clean source/test revision `75cd70a`: `make validate-pr` passed Ruff, Pyright, 2,456 default tests, 141 configuration-extra tests with 3 environment skips, and sdist/wheel build. `make test-summary` passed package 118, unit 1,749, contract 295, integration 237, E2E 57, and config-extra 141 with 3 skips; receipt at `build/test-summary.md`. |
| Validation-relevant changes after evidence | None. The phase-plan evidence update changes documentation only. |
| PR, review, and merge | Independent review completed with all findings resolved by final correction `75cd70a`; PR and merge pending. |
| Residual risk and cleanup | This is an intentional hard cut-over. Protocol-v3 offers now require provider descriptors and the complete GPU descriptor shape; remote execution requires schema/capability v3; retained claim commands require provider identity. Old offers, deliveries, and retained claim rows are rejected rather than migrated, so operators must deploy coordinator and agents together and drain or explicitly discard pre-cutover retained work. No GPU hardware/vendor dependency was introduced. Required behavior is simulated and deterministic; real hardware evidence remains optional. Non-exclusive production modes fail closed until a provider can enforce observation, isolation, binding, accounting, and release. Worktree and branch remain for PR completion. |

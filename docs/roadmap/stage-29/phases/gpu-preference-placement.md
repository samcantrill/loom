# Phase 6 Execution Plan: GPU, VRAM, And Preference Placement

## Metadata

- Status: pending
- Roadmap stage and phase: Stage 29, Phase 6
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p6-gpu-preference-placement`
- Worktree root and path: record during phase preparation
- Base revision: current `origin/develop` after Phase 5 remotely merges
- PR target: `develop`
- PR title: `feat(scheduling): add GPU and preference placement`
- Dependencies: Phase 5 merged with authenticated multi-agent CPU/memory
  scheduling, remote assignment/data execution, exact capacity accounting, and
  reconnect behavior; Phase 1 provides generic resource/rule/policy contracts
- Workflow path: expanded because discrete devices, optional sharing, global
  capacity, hard feasibility, and soft ranking interact causally
- Blockers: Phase 5 remote merge; opt-in hardware evidence is optional and must
  not block simulated/default CI

## Objective And Context

- Vertical outcome: a stage may request exact GPU behavior and VRAM capacity;
  Loom excludes incapable agents/devices, binds exact eligible devices or
  enforceable share atoms, and then ranks feasible placements using stage-
  relevant GPU/model/agent/packing preferences. CPU-only stages are unaffected.
- Earlier dependency: Phase 5 proves remote execution without GPU-specific
  behavior. This phase must demonstrate that the Phase 1 generic interfaces can
  add a real discrete/provider-bound resource without changing kernel,
  coordinator lifecycle, transport, or authority ownership.
- Later work explicitly out of scope: Phase 7 controls/reconfiguration and Phase
  8 recovery. This phase may expose safe GPU diagnostics but cannot mutate live
  providers/configurations remotely.

## Current Source And Harness

- Reuse Stage 27 local GPU discovery, assignment plans/providers, capability and
  acceptance tests where their current contracts remain valid.
- Reuse Phase 1 `ResourcePlanner`, rule/scorer/policy, exact quantity, capacity
  atom, descriptor, claim-contract, registry, and conformance seams.
- Reuse Phase 5 global snapshots, offers, assignments, transfer/execution loop,
  availability reconciliation, and loopback multi-agent harness.
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
- Keep configured inventory distinct from current availability. Exclusive
  devices are discrete capacity atoms. Share-capable providers expose exact
  provider-defined VRAM/fraction atoms and live claims already reflected in net
  availability.
- Add a built-in GPU resource planner and corresponding agent provider adapters
  for explicit modes only:
  - `exclusive`: request a positive integer device count; select exact device
    IDs; per-device minimum VRAM/model/features are eligibility attributes; the
    full selected device atom is consumed;
  - `vram_share`: request exact integer VRAM bytes on one or more explicitly
    described devices only when a named provider advertises enforceable
    isolation, accounting, granularity, preparation, binding, and release;
  - provider-defined fractional mode: accept an exact normalized rational value
    only for a named compatible provider and advertised granularity.
- Never infer sharing from observed free VRAM. Never satisfy one device's 64 GiB
  minimum by summing several 12 GiB devices. A multi-GPU request must state its
  device count and per-device/relationship requirements explicitly.
- Normalize all VRAM to integer bytes. Reject binary floating point, implicit
  fractional GPU, unsupported mode, invalid granularity, incompatible planner/
  provider contract, and ambiguous count-versus-capacity requests at admission.
- Bind exact selected device/share identities in the claim, assignment, agent
  journal, worker environment/binding plan, output provenance where already
  appropriate, and release operation. Do not expose unsafe device details to
  unrelated clients.
- Negotiate planner and provider via `ResourceClaimContractDescriptor` while
  retaining their separate component/configuration descriptors. The coordinator
  rejects an offer or candidate when contract/data versions or fingerprints are
  unavailable/incompatible. A restarted/reconfigured provider cannot adopt an
  old live token under a different identity.
- Add built-in hard constraint specs for exact target, allowed/prohibited agent
  attributes, GPU count, allocation mode, per-device minimum VRAM, model/
  feature requirements, and the bounded topology relationships currently
  consumed by Stage 29 (for example same advertised fabric group when supported).
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
- Separate preference score from waiting behavior. An explicit bounded
  wait-then-fallback policy may keep a stage pending for a preferred placement,
  then allow lower-ranked feasible candidates. Site policy owns allowed tiers,
  weight bounds, maximum wait, and whether a client may request them.
- Apply preference precedence deterministically. Site-defined mandatory
  preference tiers/weights are not overridden by arbitrary client numbers;
  client values are normalized and bounded at admission. Scores use exact
  bounded integers and reasons are safe/structured.
- Preserve default scheduler work ordering across runs. Preferences rank only
  candidates for the selected stage; they do not reorder DAG readiness or make
  an infeasible candidate valid. An earlier proven-infeasible stage may still be
  bypassed for other usable capacity.
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
- Floating licences or globally consumed resources without one explicit
  transactional owner. Future resource kinds may use the generic interfaces but
  are not Stage 29 deliverables.
- Vendor provisioning, driver installation, automatic hardware discovery into
  policy, remote provider loading, or claiming performance/health beyond the
  configured provider evidence.

Assumptions:

- An exclusive provider can bind stable local device identities for the lifetime
  of an inventory revision and assignment.
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

### Hard then soft

```python
candidates = kernel.generate_candidates(stage, snapshot, budget)
feasible = kernel.apply_mandatory_and_hard_rules(candidates)
scored = kernel.apply_preferences(feasible)
selection = policy.select(scored)
```

The kernel validates that every scored/selected ID came from the current
candidate set and that all required evaluators ran. Preferences can add bounded
scores only after feasibility. `wait_for_preferred` is a policy result with a
deadline/fallback state, not an infinite score.

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
| Per-device VRAM is not aggregate VRAM | GPU planner | Ambiguous request/inventory | OOM placement | 12/80 GiB and multi-device tests |
| Sharing requires enforceable named provider | Validator/planner/provider negotiation | Free-VRAM observation or request text | Unsafe oversubscription | Unsupported/mismatch/granularity tests |
| Exact selected devices/shares conserve | Coordinator atoms + agent provider | Concurrent assignments/pool views | Device collision | Barrier/property/release tests |
| Planner/provider/contract identities agree | Composition and assignment validation | Restart/config drift | Wrong binding semantics | Version/fingerprint/restart tests |
| Hard rules precede preferences | Scheduling kernel | Scorer/policy | Preference bypasses feasibility | Invalid/scoring mutation tests |
| Preference applies only to relevant stage/resource | Placement resolver/scorer | Run-wide default | CPU work unnecessarily constrained | CPU preprocess/GPU train tests |
| Target and preference are distinct | Hard evaluator versus scorer/policy | User config | Silent fallback or unnecessary pending | Offline target/preferred fallback tests |
| Kernel remains resource-neutral | Scheduling package boundary | GPU implementation | Core coupling | Import/source contract plus synthetic resource test |

## Implementation Slices

1. Add GPU request/inventory/availability/claim schemas, exact exclusive and
   provider-gated share/fraction semantics, safe offer projection, claim-contract
   negotiation, and validation/unit/conformance coverage.
2. Implement GPU planner and agent provider adapters with exact device/share
   bind/reconcile/activate/release, composite CPU/memory/GPU admission, and
   concurrency/drift/crash tests.
3. Add hard GPU/target rules, stage-relevant agent/model/attribute/packing
   preferences, bounded site/client precedence, wait/fallback policy, safe
   explanations, and deterministic permutation tests.
4. Integrate multi-agent GPU stage execution, synthetic downstream resource,
   status/docs/config examples, simulated E2E, and optional real-GPU receipt.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | Required | GPU adapters do not pollute generic imports | Scheduling core remains vendor/driver free |
| Unit | Required | Request modes, exact units, candidate feasibility/scoring | Count/bytes/rational boundaries; per-device VRAM; target/preference/fallback |
| Contract | Required | Planner/provider and custom resource behavior | Negotiated contract, stable atoms, partial prepare, malformed/unknown versions |
| Integration | Required | Global capacity and exact bind | Concurrent device claims, pool overlap, drift decline, release and retry |
| E2E / opt-in | Required simulated; optional GPU | Stage-specific placement | CPU preprocess/GPU train across logical agents; optional configured hardware receipt |

Targeted commands are fixed during phase preparation. Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: treating total VRAM as per-device, inferring isolation from free
  VRAM, hidden provider consumption, score overflow/client policy abuse,
  preference leakage to unrelated stages, or provider identity drift.
- Review focus: exact mode semantics, atom conservation, final binding,
  planner/provider/contract separation, hard-before-soft, and generic core
  independence.
- Stop if: a requested share mode lacks enforceable provider semantics; Stage 27
  device identity cannot be made stable for one inventory revision; a resource
  needs hidden capacity outside atoms; or implementing GPU requires database/
  provider logic inside `loom.scheduling`.
- Accepted debt: bounded heuristics may not find globally optimal packing and
  default FIFO can starve large jobs. Revisit with measured demand.

## Executor Handoff

- Read this file, Phase 5 completion record, manifest resource constraints, and
  planning FR-5–FR-8, FR-11, FR-19, FR-22–FR-24, and FR-26.
- Prove exact simulated behavior before optional hardware tests. Do not make
  default CI depend on a GPU or vendor library.
- Decisions not to revisit: integer CPU, byte-exact VRAM, explicit GPU modes,
  per-device minima, generic kernel, hard-before-soft, target/preference
  separation, and provider-gated sharing.
- Escalate any need for implicit sharing, aggregated per-device minima, a new
  global resource owner, general solver, or heavyweight dependency.

## Workflow State

- Manager preparation: pending Phase 5 merge, worktree/base recording, and
  exact Stage 27/provider/test rediscovery
- Expanded planning: required by resource/provider/global accounting interaction;
  phase plan finalized
- Implementation: pending
- Refiner: not used
- Pre-submit gate: pending
- Independent review: decide during preparation from concrete provider and
  accounting risk
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

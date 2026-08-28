# Phase 11 Execution Plan: Resident Agent Correctness And Security

## Metadata

- Status: in_progress
- Roadmap stage and phase: Stage 29, Phase 11
- Manifest: `docs/roadmap/stage-29/implementation-plan.md`
- Branch: `agent/stage-29-p11-resident-agent-correctness-security`
- Worktree root and path: `/home/can134/work/active/loom-worktrees`; phase path is `<root>/stage-29-p11-resident-agent-correctness-security`
- Base revision: `860c5182ceacbb8e7145dd1fe52849699b404152`
- PR target: `develop`
- PR title: `feat(agent): require exact resident execution profiles`
- Dependencies: Phase 10 remotely merged as `c2dab20`
- Workflow path: fast; the identity and environment contracts are fixed
- Blockers: none; the maintainer approved the mandatory exact per-stage
  preparation mapping on 2026-08-29

## Objective And Context

- Vertical outcome: every managed work item carries one exact execution
  requirement, every offered resident profile is evaluated as its own candidate,
  the assignment pins the exact selected profile, and the worker starts in a new
  explicitly constructed environment backed by a validated provider composition.
- Earlier dependency: Phase 10 global scheduling and assignment-scoped launch is
  the only scheduling/execution composition.
- Later work explicitly out of scope: public status/poll bounds, accepted-time
  recovery, root initialization, and deployment commands remain Phase 12.

## Current Source And Harness

- Relevant files and symbols: `ResidentProfileDescriptor`,
  `ResidentExecutionProfile`, `ResidentWorkerLaunchProfile`, `AgentOffer`,
  `LocalDaemonExecution._remote_candidates`, `_RemoteCandidateTarget`,
  `StageWorkRecord`/resolved placement, managed runtime record preparation/load,
  `AgentResourceProvider`, built-in CPU/memory/GPU providers,
  `run_managed_local_assignment`, and `loom.testing.checks`.
- Existing tests and seams: two-profile supervisor/restart evidence; remote offer
  serialization; provider lifecycle contract tests; GPU/environment bindings;
  local and remote resident execution integrations.
- Import, dependency, or harness constraints: execution-requirement values must
  remain import-light and serializable; coordinator components do not own agent
  physical providers; durable/wire values contain identities/descriptors, never
  provider callables or secret paths.

## Scope

In scope:

- Add immutable `ExecutionRequirement(project_fingerprint,
  environment_fingerprint, executor_fingerprint)` and persist it in the
  protected managed runtime/stage placement record for every managed stage.
  `prepare_managed_local_runtime_record` requires an explicit mapping keyed by
  every prepared stage name; its keys must exactly cover the plan and no
  authored-field, run-wide, daemon-profile, agent-profile, or other default is
  inferred. Missing, extra, or malformed requirements reject before admission;
  bump the runtime record and dependent wire/durable identities with no
  compatibility.
- Materialize one scheduling candidate per `(agent_id, session_id, profile_id)`.
  Candidate identity is stable and profile-qualified; capacity/resource atoms
  remain correctly namespaced and cannot be double-counted between profiles.
- Exact compatibility is mandatory before ordinary resource feasibility. An
  incompatible profile receives no assignment. The assignment target persists
  agent, session, profile ID, and profile fingerprint/revision and the agent
  verifies all fields before delivery/launch.
- Replace ambient worker inheritance with a new allowlisted environment. Its
  baseline contains only the selected profile's worker path, stable locale,
  `PYTHONNOUSERSITE=1`, assignment workspace `TMPDIR`, profile-declared explicit
  variables, and explicit provider claim contributions. Never call
  `os.environ.copy()` or iterate ambient daemon environment into the launch.
- Split coordinator composition (planners, constraints, preferences, policy)
  from agent composition (physical providers). Agent capacity/availability is
  observed through configured `AgentResourceProvider` instances. For every
  `(resource_kind, provider)` in an agent composition, require the coordinator's
  active planner for that same resource kind and a nonempty exact intersection
  between their claim-contract descriptors before accepting the offer. A
  provider for an unknown kind or with no contract intersection rejects that
  agent composition; an absent provider merely advertises no capacity for that
  kind. Multiple providers for one kind are each checked independently, never
  Cartesian-checked against planners for other kinds.
- Add public `check_agent_resource_provider_contract(provider, sample_claim=...)`
  to `loom.testing` and cover a custom provider through actual offer,
  reservation, activation, worker environment contribution, and release.

Out of scope:

- Environment sandboxing, containers, secrets managers, automatic profile
  discovery, profile guessing/fallback, cross-profile capacity duplication, or
  arbitrary plugin discovery/loading.
- Changing resource planner semantics, agent trust/session authentication, or
  the Phase 10 global ordering algorithm.

Assumptions:

- Authored protected profile configuration is trusted project/site code.
- A provider may expose only declared claim-derived worker variables; values are
  still treated as secrets in status/diagnostics and never persisted in the
  coordinator database.

## Fixed Contracts And Private Discretion

- Observable behavior: two compatible profiles are simultaneously offered as
  separate candidates; exactly one is selected/pinned; incompatible profiles
  receive no delivery; daemon-only credentials such as `DATABASE_URL`,
  `SSH_AUTH_SOCK`, and `KUBECONFIG` are absent from launch and supervisor bytes;
  a custom provider executes end-to-end.
- Public or durable shapes: new execution requirement, profile-qualified
  candidate/assignment target, agent provider composition, and testing helper.
  The preparation API accepts one mandatory exact per-stage requirement mapping.
  Managed-runtime and agent-session/assignment schema identities hard-cut.
- Trust and failure boundaries: coordinator compares inert exact fingerprints;
  agent verifies the pinned live profile and owns provider/environment effects;
  no daemon ambient state crosses into the worker implicitly.
- Cross-phase contracts: Phase 12 deployment configuration must construct these
  coordinator/agent compositions and profiles without adding another path.
- Reproducibility and compatibility: selected execution identity and provider
  descriptors are durable; previous managed runtime records, offers, poll
  protocol values, and assignment targets are rejected.
- Private choices the executor may simplify: precise module location of the
  import-light requirement value, environment builder helper structure, and
  provider registry implementation, provided public imports remain intentional.

## Proportionality

- Existing seam reused: resident profile descriptors, profile-set supervisor,
  scheduling candidate attributes, provider protocols/claim contracts, and
  supervisor launch environment.
- Material additions and current justification: exact required identity,
  profile-qualified candidates/targets, allowlist construction, agent
  composition, and conformance helper close reachable wrong-code and ambient
  credential exposure paths.
- Optional hardening and future capability deferred: OS-level isolation,
  encrypted environment transport, dynamic provider loading, and profile
  negotiation.

## Invariant Ownership

| Invariant | Owner | Reachable invalid producer or boundary | Consequence | Coverage |
| --- | --- | --- | --- | --- |
| Managed work names one exact execution identity | protected managed runtime record | absent/changed project, environment, or executor identity | wrong code/environment executes | serialization and changed-runtime rejection tests |
| Each candidate/assignment pins one offered profile | coordinator target plus agent verification | multi-profile offer collapsed or target drift | wrong resident worker selected | two-profile selection and mismatch tests |
| Worker receives no ambient daemon environment | agent environment builder | inherited service process environment | credential/config leakage | sentinel env and supervisor-byte tests |
| Physical capacity/effects come from configured providers | agent composition | hardcoded built-in construction or same-kind planner/provider contract mismatch | false capacity or unenforceable claim | custom provider E2E plus unknown-kind, no-intersection, and multi-provider coverage tests |
| Provider conformance helper exercises lifecycle shape | `loom.testing` | malformed downstream provider | late unsafe production failure | public contract-helper tests |

## Implementation Slices

1. Add/persist exact execution requirement and hard-cut runtime/assignment/wire
   schemas.
2. Emit profile-qualified candidates and pin/verify the selected target without
   capacity duplication.
3. Add explicit agent provider composition and planner/provider startup contract
   validation; adapt local and remote offer paths.
4. Replace worker environment inheritance with allowlist plus explicit profile
   and provider contributions.
5. Add the public provider conformance helper, custom-provider integration, and
   security/identity causal tests; update docs.

## Test And Validation Plan

| Suite | Required or deferred | Behavior or risk | Minimal assertions or reason |
| --- | --- | --- | --- |
| Package | required | public requirement/composition/testing imports | imports typed, intentional, and cheap |
| Unit | required | exact compatibility, target pinning, allowlist | two profiles visible, mismatch rejected, sentinel env absent |
| Contract | required | provider helper and serialization hard cuts | built-in/custom reports and old record rejection |
| Integration | required | custom provider and resident launch | actual provider lifecycle/environment and correct profile launch |
| E2E / opt-in | required in existing local harness | production daemon path | selected profile executes; no ambient credentials persisted |

Targeted commands:

    pytest -q tests/unit/loom/queue/test_agent_process_supervisor.py tests/unit/loom/queue/test_agent_sessions.py tests/unit/loom/queue/test_remote_stage_execution.py tests/unit/loom/queue/test_managed_local.py
    pytest -q tests/contracts/test_agent_resource_provider_contract.py tests/unit/loom/testing/test_contracts.py
    pytest -q tests/integration/queue/test_agent_session_transport.py tests/integration/queue/test_local_daemon_production.py

Final commands:

    make validate-pr
    make test-summary

## Risks, Review, And Stops

- Main risks: accidentally duplicating one agent's atoms across profile
  candidates, persisting provider-supplied secrets, or accepting a descriptor
  match that does not pin the actual supervisor launch profile.
- Review focus: exact identity from runtime record through candidate, assignment,
  delivery, supervisor, and result; environment bytes at every persistence seam;
  provider contract and capacity ownership.
- Stop if: compatibility requires guessing/defaulting a profile, a provider
  cannot express its physical claim with the accepted exact contract, or the
  supported custom-provider path requires untrusted plugin discovery.
- Accepted debt and revisit trigger: worker process isolation is not a security
  sandbox; revisit if project code becomes untrusted.

## Executor Handoff

- Read section range: this complete phase plan, especially Scope through Risks.
- Safe implementation slices: the five numbered slices in order.
- Decisions not to revisit: exact identity equality; one profile per candidate;
  mandatory exact per-stage preparation mapping with complete plan coverage and
  no inference/default; selected profile pinned; new allowlisted environment;
  providers are agent-owned; old formats unsupported.
- Conditions requiring manager action: any ambiguity in durable/public shape not
  resolved by this plan, capacity duplication across profiles, or qualified
  lifecycle/security blocker.

## Workflow State

- Manager preparation: complete; manifest status, merged predecessor, exact
  `origin/develop` base, branch/worktree, source seams, fast-path risk decision,
  and validation commands verified at `860c518`
- Expanded planning: not needed; correction contracts are maintainer-supplied
- Implementation: the first executor turn stopped before edits at the public
  input boundary; the maintainer approved a required exact per-stage mapping on
  2026-08-29, so the same executor may resume the directly related task
- Refiner: not needed
- Pre-submit gate: pending
- Independent review: not needed unless a material residual risk remains
- Blocker corrections: 0/3
- PR and merge: pending

## Completion Record

| Item | Result |
| --- | --- |
| Implementation and changed paths | The initial executor turn made no source or test changes. The maintainer then approved the required exact per-stage preparation mapping; implementation resumed. |
| Tests added or updated | pending |
| Validated revision/tree state and evidence | pending |
| Validation-relevant changes after evidence | none |
| PR, review, and merge | pending |
| Residual risk and cleanup | No unresolved product decision. The phase branch/worktree remain dedicated and clean while implementation resumes. |

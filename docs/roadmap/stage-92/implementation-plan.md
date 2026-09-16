# Native Project Contracts And Result Resolution

Status: in_progress
Stage descriptor: Native Project Contracts And Result Resolution
Target: develop

This manifest maps the two approved Loom dependency packages for rphys Stage 92
onto Loom's phase workflow. The identifier tracks that external delivery; it does
not allocate or renumber an independent Loom roadmap stage. Scientific reference
integration remains in rphys phases 7–9.

## Accepted Contract And Authorization

The authoritative approved protocol is the rphys
[native project contract](https://github.com/samcantrill/rphys/blob/ae494e19e593f2b72cfef20d1b0b01c0421272b6/docs/roadmap/stage-92/planning/native-project-contract.md).
Its Preparation Protocol, Native Execution Identity And Selection, Delivery
Packages And Source Ownership, and Example And Validation Contract sections own
U1/U2 behavior, durable formats, failure semantics and scope. Do not copy the
rphys-specific checked-action schema into Loom. Local evidence is available at
`/nas/home/can134/work/rphys-worktrees/stage-92/docs/roadmap/stage-92/planning/native-project-contract.md`.

The maintainer explicitly authorized implementing, validating, independently
reviewing and merging U1 and U2 in Loom using isolated worktrees and Loom's
workflow, followed by rphys Stage 92 integration. This subsequent authorization
supersedes the earlier packet's statement that sibling implementation was not
yet authorized. It does not relax any protocol, qualification or review gate.

## Execution Context

- Clean control: `/nas/home/can134/work/loom-worktrees/control-stage-40` on develop.
- Worktree root: `/nas/home/can134/work/loom-worktrees`.
- Persistent stage worktree: `/nas/home/can134/work/loom-worktrees/stage-92`.
- Coordination branch: `agent/stage-92`.
- Initial source: `c8f23852af2018109c318d17d03186ba9e49893f`.
- Workflow: `.codex/workflows/roadmap-stage-implementation.md` and
  `.codex/prompts/phase-loop-management.md`.
- The original `/nas/home/can134/work/loom` checkout has unrelated dirty work;
  preserve it and use the clean control/stage paths above.

## Phase Order

| Phase | Package | Card | Branch | Status | Dependency / bounded outcome |
| --- | --- | --- | --- | --- | --- |
| 1 | U1 | [Installed Node Contracts](phases/installed-node-contracts.md) | `agent/stage-92-p1-installed-node-contracts` | in_progress | Approved protocol; persist checked opaque node contracts, forward authoritative context, preserve v1/v2 and v3 whole-target lifecycle |
| 2 | U2 | [Verified Action Result Resolution And Fresh Execution](phases/verified-action-result-resolution.md) | `agent/stage-92-p2-verified-action-result-resolution` | pending | U1 merged, metadata published and synchronized; native verified result selection, demand ownership and idempotent fresh generation |

U1 may merge independently without cross-graph reuse. U2 is one coherent result
lifecycle: identity, claims, verification, binding, retention, cancellation and
fresh replay ship together. No reference cache, copied commits, project imports
on the coordinator, hook registry, new configuration resolver or scientific
dispatch belongs in either phase. Existing public and legacy behavior remains.

## Implementation Plan Review

Reuse the passed independent generic-boundary review and B1/B2 confirmation in
the published rphys
[readiness receipt](https://github.com/samcantrill/rphys/blob/ae494e19e593f2b72cfef20d1b0b01c0421272b6/docs/roadmap/stage-92/implementation-plan.md#generic-boundary-refinement-review).
That review covered the exact U1/U2 contracts, generic metadata transport,
opaque rejection codes, whole-target migration and generic fixture. This local
mapping changes only repository execution facts and phase identities.

Startup compared eleven relevant Loom preparation/request/context/prepared-run/
fingerprint/resume/shared-publication files between reviewed source `e028797f`,
the reference pin `2f32bc77` and initial source `c8f23852`: those files are
unchanged. New fleet/reboot/enrollment/coordinator-only publication behavior
remains supported. U1/U2 capabilities are absent at this base. Reuse current
review evidence; reopen only an incompatible accepted protocol or material
source-boundary finding, not private wiring decisions.

## Validation And Delivery

Each phase owns exact selectors and results in its card. The required generic
installed text fixture is standard-library-only and exercises the real native
path without rphys. Each phase runs `make validate-pr` once its relevant tree is
stable because preparation, durable metadata, worker and authority changes span
multiple public boundaries. No extra `make test-summary` run is prescribed;
reuse the actual gate reports. Native local fixtures do not qualify physical
containers, GPUs, fleets or SLURM; rphys owns its final installation acceptance.

Each phase requires independent review of its actual PR head, merge to develop,
published metadata and shared Git synchronization before the next phase starts.
Keep current completion evidence in the phase cards; no lifecycle sidecars.

## Current Delivery State

Initial shared setup/preflight passed at `c8f23852` on the Phase 1 branch.
No code, runtime qualification, PR or merge is claimed yet. U1 is the current
delivery; U2 and rphys integration remain pending their predecessor gates.

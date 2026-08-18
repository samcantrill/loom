# Roadmap Stage Planning

## Goal

Create or refresh:

- docs/roadmap/stage-<N>/planning.md
- docs/roadmap/stage-<N>/implementation-plan.md
- one docs/roadmap/stage-<N>/phases/<phase-slug>.md per accepted phase

The manager owns the workflow and user discussion. No subagent is required on
the lean path.

## Read

- AGENTS.md
- docs/roadmap.md and directly linked feature/architecture docs
- relevant source, tests, config, and adjacent plans
- the current planning, manifest, and phase templates

Record the evidence root, revision, and relevant dirty paths. Treat source,
tests, config, and canonical docs as authoritative.

## Route

Use lean by default. Use expanded only for a novel or unresolved public,
durable, trust-boundary, cross-owner, irreversible migration, or causally
interacting validation decision with material consequences.

## Gates

1. Evidence and minimum useful outcome.
2. Capability triage, requirements, functionality agreement, and behavior.
3. Minimum design, complexity delta, design agreement, and examples.
4. Validation, invariant ownership, vertical phase shaping, and readiness.
5. Compact manifest and linked phase execution plans.
6. Manager quality gate and maintainer approval.

The manager performs every gate locally on the lean path.

On the expanded path, use at most one loom_design_safety_reviewer after the
minimum design is recorded and at most one loom_plan_reviewer after the manifest
and phase plans exist. Use .codex/prompts/subagent-lifecycle.md. A bounded
correction is allowed only for concrete findings.

## Operating Rules

- Update planning.md in place. It is current state, not a transcript.
- Start from the existing end-to-end path and record what fails without each
  material addition.
- Future reuse alone is a reason to keep private seams changeable, not to add
  current machinery.
- Ask one material maintainer question at a time. Resolve repository-backed
  defaults locally.
- Give each invariant one owner and test only demonstrated boundaries and causal
  interactions.
- Prefer one to three vertical phases and justify exceptions.
- Keep fixed contracts explicit and private implementation open.
- Do not draft phases while an agreement item or quality gate is blocked.
- Do not start product implementation from this workflow.

## Exit

Planning is ready when the current state, agreements, complexity delta,
validation, phase shape, manifest, linked phase plans, risks, and maintainer
approval are coherent with no unresolved blocker.

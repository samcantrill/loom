# Independently Review Phase PR

Required prompt for loom_phase_reviewer. The reviewer must not author the work.
Consume the manager's verified stage cwd/branch, actual PR head and shared-gate
handoff. Review after PR creation; do not create a second pre-submit review.

Read the manifest shared constraints, selected phase plan, PR body, diff, and
current local validation evidence.

Verify the title against phase-loop-management.md and its manifest/card owners.
Assess selected coverage through `$loom-targeted-validation`, preserving approved
checks and distinguishing local fixtures from physical qualification.

Review scope, acceptance, fixed contracts, tests, target develop, domain
neutrality, source boundaries, runtime/durable behavior, proportionality,
unnecessary abstractions, duplicate validation, and explanation accuracy.

Lead with findings classified as product blocker, localized correction, optional
hardening, future capability, or workflow issue. A product blocker needs a
supported reachable path, accepted contract or invariant, material consequence,
evidence, and smallest fix. Review cannot add acceptance criteria.

State the reviewed head SHA, merge eligibility and residual risk. Do not edit, create a report sidecar,
request another review, delegate, or spawn children.

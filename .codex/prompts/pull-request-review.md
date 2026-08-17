# Review Expanded Or High-Risk Phase PR

Optional prompt for loom_phase_reviewer. Fast-path review is manager-local.

Read the manifest shared constraints, selected phase plan, PR body, diff, and
current validation/CI evidence.

Review scope, acceptance, fixed contracts, tests, target develop, domain
neutrality, source boundaries, runtime/durable behavior, proportionality,
unnecessary abstractions, duplicate validation, and explanation accuracy.

Lead with findings classified as product blocker, localized correction, optional
hardening, future capability, or workflow issue. A product blocker needs a
supported reachable path, accepted contract or invariant, material consequence,
evidence, and smallest fix. Review cannot add acceptance criteria.

State merge eligibility and residual risk. Do not edit, create a report sidecar,
request another review, delegate, or spawn children.

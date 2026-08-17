# Implementation Manifest And Phase Plans

Manager-local planning pass after planning.md quality gates are clear.

Create or update:

- one compact implementation-plan.md using
  .codex/templates/roadmap-stage-implementation-plan.md;
- one phase execution plan per accepted phase using
  .codex/templates/phase-execution-plan.md.

Use artifact layout manifest-and-phase-plans-v1.

Keep shared constraints and the phase index in the manifest. Put phase-specific
scope, fixed contracts, ownership, implementation slices, tests, validation,
risks, discretion, and stop conditions only in the linked phase plan. Reference
requirement and decision IDs instead of copying planning prose.

Prefer one to three vertical phases. Each phase must deliver or independently
de-risk an end-to-end outcome. Do not split only by module or layer.

Do not create phases if an agreement or quality gate is blocked. Do not prescribe
private helpers, local wiring, or intermediate representations.

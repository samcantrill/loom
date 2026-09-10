---
name: loom-targeted-validation
description: Select and run Loom checks for behavior changes, regression fixes, executable configuration, and validation planning. Use when defining coverage or assessing evidence; prose-only edits normally need diff and affected documentation checks.
---

# Loom Targeted Validation

`AGENTS.md` owns proportionality; the applicable workflow and approved phase
card own required gates. This skill never silently relaxes approved obligations.

## Select Coverage

Reuse existing discovery and phase rationale. Read relevant assertions and
fixtures, not just test names. Use exact paths and `rg` for definitions,
consumers, configuration targets, and dynamic references.

- Describe the observable change, affected contracts, and supported consumers.
  File count and unchanged signatures do not establish isolation.
- Follow effects through graph planning, lifecycle, identity, configuration,
  serialization, authority/store ownership, provenance, resume, diagnostics,
  failure behavior, imports, and dependencies as applicable. Stop where an
  unchanged supported contract contains the effect.
- Select concrete files or pytest node IDs and required dependency environments.
  Broaden to affected suites or full validation when explicit selection cannot
  confidently cover the impact.
- Add assertions for material gaps: a regression reproducer, a documented edge
  case, or a supported boundary with a discriminating expected result. Do not
  mirror private implementation or test hypothetical forged internal states.

Record changed behavior, contracts/consumers, selected checks, and expansion
triggers in existing task notes or the phase card. Refine selectors when actual
dependencies become clear without changing accepted coverage obligations.

## Execute And Assess

Use [tests/README.md](../../../tests/README.md#targeted-validation) for commands,
markers, dependency isolation, and summary behavior. Finish relevant edits
before collecting final evidence. Record revision/tree, selections, results,
skips, unavailable cases, and relevant subsequent changes.

Subset results are not full-suite evidence. Local fixtures do not qualify a
physical container, fleet, or Slurm deployment. A required unavailable case
remains a gap until corrected or explicitly accepted with its risk.

Reuse fresh evidence across implementer, manager, and reviewer. Run affected
checks again only when changes invalidate them; broaden for failures, newly
affected consumers, missing assertions, or unresolved risk. A successful
focused run does not automatically require a full suite or a summary rerun.
Once required evidence is complete, proceed to delivery.

## Examples

- Coordinator error decoding: exercise Unix/HTTPS boundary contracts and the
  consuming CLI/client behavior; expand if shared response schemas change.
- Shared run identity: cover producers, durable encoding, replay, and consumers;
  a constructor unit test alone does not establish recovery correctness.
- Documentation edit: inspect links and diff, plus any actual documentation
  consumer. Do not start runtime acceptance jobs for prose changes.

# Implementation Plan Review

Optional expanded-path prompt for loom_plan_reviewer.

Treat the compact manifest and all linked phase execution plans as one plan.
Read planning.md only to verify a concrete traceability question.

Review:

- current necessity and removable complexity;
- behavior/design/phase traceability;
- one-to-one manifest and phase-plan consistency;
- bounded ownership and acyclic dependencies;
- vertical phase shape and early end-to-end value;
- fixed contracts versus private discretion;
- invariant ownership and proportional validation;
- domain neutrality, imports, durability, compatibility, and reproducibility;
- acceptance criteria, risks, debt, and stop conditions.

Lead with findings. A blocker needs a reachable path, accepted contract or
invariant, material consequence, evidence, and smallest remedy. Classify the
rest as simplification, concern, or optional hardening.

In review mode do not edit. State whether implementation is ready and stop after
one pass.

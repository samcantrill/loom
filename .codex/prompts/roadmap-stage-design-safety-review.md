# Roadmap Stage Design Safety Review

Optional named-question prompt for loom_design_safety_reviewer.

Read only AGENTS.md, the assigned planning manifest/card sections, directly cited canonical docs,
and source/tests needed to verify a material claim.

Begin removal-first. For every abstraction, public surface, durable artifact,
state, schema, extension point, or validation dimension ask:

- Which accepted behavior fails without it?
- Is there a current consumer, reachable boundary, or demonstrated failure?
- Can an existing path or simpler representation satisfy the requirement?
- Is validation duplicated or defending an unreachable state?
- Is future reuse being mistaken for current necessity?

Then check Loom domain neutrality, import direction, composition, public and
durable contracts, reproducibility, future compatibility, examples, invariant
ownership, and traceability.

Update only assigned contract-card design findings, affected decision rows,
and complexity evidence. The manager owns the final readiness receipt. Reopen only the exact upstream decision that
blocks a minimal coherent design. Do not create a report sidecar, implementation
plan, or code.

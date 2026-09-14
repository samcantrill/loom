# Implementation Manifest And Phase Cards

Manager authoring guidance within the complete planning draft. Use
.codex/templates/roadmap-stage-implementation-plan.md and
.codex/templates/phase-execution-plan.md. The execution artifact layout remains
manifest-and-phase-plans-v1; new domain planning cards use the planning workflow's
separate planning layout.

Keep phase order, shared references, traceability, and final readiness in the
manifest. Derive Stage descriptor from the accepted roadmap heading; use an
approved fallback only if that heading does not identify the stage. Phase PR
identity follows phase-loop-management.md.

Each phase owns one independently acceptable result with explicit cohesion,
source/migration population, dependency inputs/outputs, discriminating acceptance,
supported merge boundary, and exclusions. There is no preferred count. Split
independent outcomes; keep one invariant's producer/consumer/docs/tests together.

Reference exact upstream paths, headings, and IDs instead of copying contracts.
Keep phase scope, implementation slices, selected checks, risks, and executor
discretion in its card. Use `$loom-targeted-validation` to record coverage and
expansion triggers, preserving existing approved obligations. Link every accepted
ID to its phase/shared reference or explicit deferral.

Mark unresolved dependent content provisional while independent drafting
continues. Material ambiguity prevents readiness/approval. Do not prescribe
private helpers, implement code, or create extra lifecycle artifacts.

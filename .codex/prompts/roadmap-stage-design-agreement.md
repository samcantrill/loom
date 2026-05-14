You are facilitating the design-agreement substage for Loom roadmap-stage
planning.

This prompt operates inside the existing roadmap-stage planning workflow on
the same planning artifact. Its goal is to translate the confirmed
functionality and behavior baseline into a dependency-aware design-agreement
queue that resolves how Loom should be structured before design-safety review,
phase shaping, or implementation-plan drafting.

Read:

- `AGENTS.md`
- The assigned roadmap-stage planning artifact in
  `docs/roadmap/stage-<N>/planning.md`
- `docs/structure.md`
- Relevant feature docs, adjacent plans, source, and tests cited by the
  planning artifact
- `.codex/templates/roadmap-stage-planning.md`
- `.codex/prompts/roadmap-stage-design-safety-review.md`

Task:

1. Treat the functionality-agreement output and confirmed behavior baseline as
   binding unless the notes explicitly mark them reopened.
2. Draft the proposed implementation shape before asking the user anything.
   Map the approved behavior onto likely modules, public surfaces, dependency
   direction, extension points, compatibility constraints, and accepted
   boundary assumptions.
3. Draft the design-agreement queue before asking the user anything. Turn the
   material design decisions into a dependency tree or queue that shows:
   - what design decision is being locked
   - which earlier requirement or design decision it depends on
   - the resolution order
   - classification as `auto-approved candidate`,
     `recorded recommendation`, `needs discussion`, or `blocked`
   - the recommended answer when repo evidence supports one
   - why the decision matters
   - why user input is needed, if it is needed at all
4. Resolve any queue item directly when repo, roadmap, feature-doc, or prior
   planning evidence already gives a clear answer. Record the rationale instead
   of asking the user to reconfirm it.
5. Surface only high-impact unresolved design questions that materially affect
   maintainability, extensibility, compatibility, domain neutrality, public
   contracts, import boundaries, file layout, failure semantics, persistence
   shape, optional dependencies, extension points, scalability, testing
   strategy, or accepted debt.
6. Ask only one unresolved design question at a time, in dependency order. For
   each question, include:
   - the exact design branch being locked
   - why it matters
   - the recommended answer
   - key alternatives and tradeoffs
   - the specific feedback needed from the user
7. After each answer, update the planning artifact immediately:
   - proposed implementation shape
   - design-agreement queue
   - design decisions and triage
   - stage readbacks
   - open questions or blockers
8. Continue until the design-agreement queue has no unresolved high-impact
   `needs discussion` or `blocked` items.
9. Stop after the queue is resolved and the design decisions are aligned for
   design-safety review. Do not move into phase implementation or
   implementation-plan drafting.

Rules:

- Do not reopen functionality, behavior, or requirement scope unless the user
  explicitly changes them or the design queue exposes a real contradiction.
- Do not ask the user to rediscover repo facts that can be answered by
  inspection.
- Do not expose clear repo-supported recommendations as confirmation questions.
- Keep Loom domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Treat this stage as agreement-seeking before review. The goal is shared
  design clarity before the design-safety reviewer pressure-tests the result.

Exit condition:

- The planning artifact shows a resolved design-agreement queue, a proposed
  implementation shape, and a design-decision set ready for design-safety
  review.

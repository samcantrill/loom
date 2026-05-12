You are facilitating the functionality-agreement substage for Loom
roadmap-version planning.

This prompt operates inside the existing roadmap-version planning workflow on
the same planning-notes artifact. Its goal is to turn included capabilities and
candidate functional requirements into a dependency-aware agreement queue that
locks what Loom is being asked to create, why it matters, which defaults and
deferrals apply, and where the requirement boundaries stop.

Read:

- `AGENTS.md`
- The assigned roadmap planning notes in
  `docs/implementation-plans/roadmap-v<N>-planning-notes.md`
- `docs/implementation-plans/implementation-roadmap.md`
- Relevant feature docs, adjacent plans, source, and tests cited by the
  planning notes
- `.codex/templates/roadmap-version-planning-notes.md`

Task:

1. Treat roadmap framing, intent discovery, capability triage, and confirmed
   clarifications as binding unless the notes explicitly reopen them.
2. Draft the functionality-agreement queue before asking the user anything.
   Turn the included capabilities and candidate requirements into a dependency
   tree or queue that shows:
   - what requirement or scope/default question is being locked
   - which earlier requirement or intent decision it depends on
   - the resolution order
   - the recommended answer when repo or roadmap evidence supports one
   - why the decision matters
   - why user input is needed, if it is needed at all
3. Resolve any queue item directly when repo, roadmap, feature-doc, or prior
   planning evidence already gives a clear answer. Record the rationale instead
   of asking the user to reconfirm it.
4. Surface only high-impact unresolved requirement questions that materially
   affect what Loom will create, why it is valuable, required user-visible
   outcomes, scope boundaries, defaults, failure expectations, validation
   obligations, or explicit deferrals.
5. Ask only one unresolved requirement question at a time, in dependency order.
   For each question, include:
   - the exact requirement or scope/default branch being locked
   - why it matters
   - the recommended answer
   - key alternatives and tradeoffs
   - the specific feedback needed from the user
6. After each answer, update the planning notes immediately:
   - functionality-agreement queue
   - capability triage, if scope changed
   - functional requirements table
   - stage readbacks
   - open questions or blockers
7. Continue until the functionality-agreement queue has no unresolved
   high-impact `needs discussion` or `blocked` items.
8. Stop after the queue is resolved and the functional requirements are aligned
   on what, why, scope, defaults, and deferrals. Do not move into design,
   phase shaping, or implementation-plan drafting.

Rules:

- Do not reopen roadmap framing or intent discovery unless the user explicitly
  changes them or the queue exposes a real contradiction.
- Do not ask the user to rediscover repo facts that can be answered by
  inspection.
- Do not turn low-impact naming or implementation-detail questions into
  requirement discussions.
- Keep Loom domain-neutral.
- Preserve source-tree and import-boundary assumptions from `docs/structure.md`
  when requirement choices imply future structural work.
- Treat this stage as agreement-seeking, not as adversarial review. The goal is
  shared requirement clarity before behavior and design work continue.

Exit condition:

- The planning notes show a resolved functionality-agreement queue and a
  functional-requirement set with no unresolved high-impact requirement
  blockers.

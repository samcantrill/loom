# Roadmap-Version Planning

Use this entrypoint when the user wants an interactive design discussion for one
roadmap version before drafting an implementation plan. When the planning
discussion is complete and the user explicitly confirms they are happy with the
roadmap-version notes, continue into implementation-plan drafting from the
confirmed notes.

Canonical prompts:

- `.codex/prompts/roadmap-version-planning-notes-facilitate.md`
- `.codex/prompts/implementation-plan-draft.md`, after final planning
  confirmation

Primary template:

- `.codex/templates/roadmap-version-planning-notes.md`
- `.codex/templates/implementation-plan.md`, after final planning confirmation

Typical artifacts:

- `docs/implementation-plans/roadmap-v<N>-planning-notes.md`
- `docs/implementation-plans/implementation-plan-v<N>.md`

User request shape:

```text
Use .codex/workflows/roadmap-version-planning.md for v<N>.
Facilitate the discussion and update the roadmap planning notes as decisions
are confirmed.
```

Expected flow:

1. Roadmap framing, starting with a comprehensive version briefing and user
   clarification window.
2. Intent discovery.
3. Feature brainstorming.
4. Functionality and behavior confirmation.
5. Context compaction/reset checkpoint.
6. Maintainability/extensibility design decision review.
7. Phase shaping.
8. Final planning confirmation.
9. Implementation-plan draft from the confirmed planning notes.

At workflow startup, read the roadmap, linked feature docs, adjacent plans, and
current architecture notes before asking the user to confirm functionality or
behavior. First provide a comprehensive version briefing that explains what the
version is, why it exists, what current or future work it impacts or links to,
which public surfaces or durable artifacts it is likely to affect, why the
planning structure appears appropriate, and which assumptions or risks are
already visible. Then explicitly invite the user to ask clarifying questions and
answer them before moving on to functionality and behavior confirmation.

Ask small batches of high-impact questions and update the planning notes after
each confirmed stage. When asking about functionality, behavior, design
principles, or design decisions, include enough context for the user to make a
real choice: what the question is deciding, why it matters, expected impact,
relevant considerations or tradeoffs, and a recommended default when the repo
evidence supports one. After functionality and behavior are confirmed, record a
complete checkpoint in the planning notes and compact or reset context before
starting the design decision review. The resumed design pass should reload the
planning notes, identify the necessary design decisions, and classify them
before asking the user anything. Do not ask the user whether more design
decisions should be reviewed. The facilitator owns that triage and should not
turn every behavior or implementation detail into a user question.

Classify each candidate design decision before discussing it:

- If the decision is low impact for maintainability and extensibility, omit it
  from the review queue or record it as an implementation detail in the notes.
- If the decision affects maintainability or extensibility and repo evidence
  gives a clear recommendation, record the recommendation, rationale, rejected
  alternatives, and revisit trigger in the notes without asking the user.
- If the decision has high maintainability or extensibility impact and there is
  no strong recommendation, discuss it with the user before marking it
  confirmed.

Each user-facing decision discussion should be presented independently with
concrete options, maintainability impact, extensibility and expansion impact,
accepted debt, rejected alternatives, and the specific user feedback needed.
Do not expose clear-recommendation decisions as confirmation questions. Do not
start phase implementation from this entrypoint; the drafted implementation plan
still needs the normal plan quality gate before phase work begins.

When the user gives feedback about the workflow itself, treat that as a
first-class workflow refinement signal. Decide whether the feedback should
change reusable workflow behavior or only the current planning session. For
reusable feedback, update the relevant `.codex/workflows/`, `.codex/prompts/`,
or `.codex/templates/` file generically, without encoding
roadmap-version-specific or phase-specific examples. For current-session
preferences, record a short planning-process note in the roadmap planning notes
and continue.

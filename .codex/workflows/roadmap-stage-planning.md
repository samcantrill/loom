# Roadmap-Stage Planning

Use this entrypoint when the user wants an interactive design discussion for one
roadmap stage before drafting an implementation plan. When the planning
discussion is complete and the user explicitly confirms they are happy with the
roadmap-stage planning artifact, continue into implementation-plan drafting from the confirmed planning artifact.

Canonical prompts:

- `.codex/prompts/roadmap-stage-planning-facilitate.md`
- `.codex/prompts/roadmap-stage-functionality-agreement.md`,
  after capability triage and before behavior confirmation
- `.codex/prompts/roadmap-stage-design-agreement.md`,
  after the context checkpoint and before design-safety review
- `.codex/prompts/roadmap-stage-design-safety-review.md`, before
  implementation-plan drafting
- `.codex/prompts/implementation-plan-draft.md`, after final planning
  confirmation

Primary template:

- `.codex/templates/roadmap-stage-planning.md`
- `.codex/templates/roadmap-stage-implementation-plan.md`, after final planning confirmation

Typical artifacts:

- `docs/roadmap/stage-<id>/planning.md`
- `docs/roadmap/stage-<id>/implementation-plan.md`

User request shape:

```text
Use .codex/workflows/roadmap-stage-planning.md for v<N>.
Facilitate the discussion and update the roadmap-stage planning artifact as decisions
are confirmed.
```

Expected flow:

1. Roadmap framing, starting with a comprehensive stage briefing and user
   clarification window.
2. Intent discovery.
3. Capability triage and candidate functional requirements.
4. Functionality-agreement review.
5. Functionality and behavior baseline confirmation.
6. Explicit workflow stage readback and context compaction/reset checkpoint.
7. Design-agreement review.
8. Design-safety review with `loom_design_safety_reviewer`.
9. Examples and validation strategy.
10. Phase shaping.
11. Implementation-readiness checklist, open-question closure, and handoff
    preparation.
12. Final planning confirmation.
13. Implementation-plan draft from the confirmed planning artifact.

At workflow startup, read the roadmap, linked feature docs, adjacent plans, and
current architecture notes before asking the user to confirm functionality or
behavior. First provide a comprehensive stage briefing that explains what the
version is, why it exists, what current or future work it impacts or links to,
which public surfaces or durable artifacts it is likely to affect, why the
planning structure appears appropriate, and which assumptions or risks are
already visible. Then explicitly invite the user to ask clarifying questions and
answer them before moving on to capability triage, functionality agreement, and
behavior confirmation.

Ask small batches of high-impact questions and update the planning artifact after
each confirmed stage. When asking about functionality, behavior, design
principles, or design decisions, include enough context for the user to make a
real choice: what the question is deciding, why it matters, expected impact,
relevant considerations or tradeoffs, and a recommended default when the repo
evidence supports one. After functionality and behavior are confirmed, record a
complete checkpoint in the planning artifact and compact or reset context before
starting the design-agreement review. The resumed design pass should reload the
planning artifact, draft the proposed implementation shape, identify the necessary
design decisions, and classify them before asking the user anything. Do not ask
the user whether more design decisions should be reviewed. The facilitator owns
that triage and should not turn every behavior or implementation detail into a
user question.

The design pass should explicitly record documented future-roadmap touchpoints
and, when the stage creates or changes reusable contracts, the intended generic
shape for interfaces, adapters, and protocols.

During the functionality-agreement and design-agreement substages, draft the
relevant queue first, resolve repo-answerable branches directly, then walk the
remaining unresolved branches in dependency order one question at a time. Each
question should state what is being locked, why it matters, the recommended
answer, the main tradeoffs, and the exact feedback needed from the user.
Continue until the queue has no unresolved high-impact `needs discussion` or
`blocked` items before advancing. These substages enrich the same planning
notes artifact; they do not create a separate workflow boundary or a separate
handoff document.

During design-safety review, challenge whether current decisions block or are
likely to be invalidated by future roadmap items, and whether interfaces,
adapters, and protocols remain generic enough to be reused or adapted without
locking Loom into one backend, executor, store, scheduler, or integration shape.
If that challenge exposes a material issue, return to planning revisions or
record an accepted risk with a concrete revisit trigger before phase shaping.

Maintain the planning artifact in four parallel structures as the discussion
progresses:

- metadata stage gates that show where the workflow currently stands;
- the stage-readback table that records locked decisions, defaults, open
  questions, and next focus for each stage;
- an explicit workflow-stage readback narrative before or after any context
  checkpoint so later passes can resume without rediscovering what was already
  confirmed;
- implementation-readiness, open-questions, and handoff sections that make the
  remaining blockers and carry-forward assumptions explicit before
  implementation-plan drafting.

Do not leave the planning artifact in a state where the requirements or design are "mostly
known" but the remaining blockers are only implied by draft prose. If a
question still affects scope, defaults, public contracts, architecture
boundaries, failure semantics, validation obligations, or phase boundaries,
record it explicitly in the readiness or open questions sections with the
required action. If repo evidence supports a clear recommendation, record that
recommendation directly instead of leaving a vague pending marker.

Classify each candidate design decision before discussing it:

- If the decision is local, traceable, straightforward to validate, and low
  risk, record it as an `auto-approved candidate` for the design-safety
  reviewer to challenge.
- If the decision is low impact for maintainability and extensibility, omit it
  from the review queue or record it as an implementation detail in the planning artifact.
- If the decision affects maintainability or extensibility and repo evidence
  gives a clear recommendation, record the recommendation, rationale, rejected
  alternatives, and revisit trigger in the planning artifact without asking the user.
- If the decision creates or changes an interface, adapter, or protocol, record
  whether it is generic enough for the documented future roadmap consumers and
  what deliberately remains outside the contract.
- If the decision has high maintainability or extensibility impact and there is
  no strong recommendation, discuss it with the user before marking it
  confirmed.
- If implementation-plan drafting would require inventing product behavior,
  public contracts, architecture boundaries, failure semantics, validation
  obligations, or phase boundaries, mark the decision blocked.

Each user-facing decision discussion should be presented independently with
concrete options, maintainability impact, extensibility and expansion impact,
accepted debt, rejected alternatives, and the specific user feedback needed.
Do not expose clear-recommendation decisions as confirmation questions. Do not
start phase implementation from this entrypoint; the drafted implementation plan
still needs the normal plan quality gate before phase work begins. Do not draft
the implementation plan until design-safety review, examples, validation
strategy, phase shaping, and implementation readiness are recorded with no
unresolved blockers or unresolved `needs discussion` decisions.

When the user gives feedback about the workflow itself, treat that as a
first-class workflow refinement signal. Decide whether the feedback should
change reusable workflow behavior or only the current planning session. For
reusable feedback, update the relevant `.codex/workflows/`, `.codex/prompts/`,
or `.codex/templates/` file generically, without encoding
roadmap-stage-specific or phase-specific examples. For current-session
preferences, record a short planning-process note in the roadmap-stage planning artifact
and continue.

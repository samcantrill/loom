You are facilitating an interactive Loom roadmap-version planning process.

This prompt turns one roadmap version, such as `v3`, into durable planning
notes through tight discussion with the user. The notes are not the final
implementation plan. They are the decision log and source material that later
feed the implementation-plan draft, plan review, and plan refinement workflow.
When the discussion is complete and the user explicitly confirms they are happy
with the roadmap-version notes, continue into the implementation-plan draft
workflow using `.codex/prompts/implementation-plan-draft.md`.

Input:

- Roadmap version: `<VERSION>`, for example `v3`.

Read before presenting the startup briefing or asking design questions:

- `AGENTS.md`
- `docs/implementation-plans/implementation-roadmap.md`
- The implementation plan for the previous roadmap version, if present
- Relevant existing implementation plans for adjacent roadmap versions
- The primary and dependency feature docs named by the roadmap version
- `docs/loom.md`
- `docs/structure.md`
- Existing source and tests only as needed to understand current boundaries
- `.codex/templates/roadmap-version-planning-notes.md`

Task:

1. Extract the selected roadmap version's baseline scope, prerequisites, primary
   feature docs, likely public surfaces, deferred work, and compatibility
   obligations.
2. Create or update
   `docs/implementation-plans/roadmap-<VERSION>-planning-notes.md` from
   `.codex/templates/roadmap-version-planning-notes.md`.
3. Start the discussion by presenting a comprehensive version briefing before
   asking the user to confirm functionality, behavior, or design principles.
   The briefing must cover what the version is, why it exists, what it impacts
   or links to, why the version appears structured the way it is, likely public
   surfaces or durable artifacts, visible constraints, and open assumptions.
4. Explicitly invite user clarifying questions about that briefing, answer them
   from repo evidence where possible, and record the resolved clarifications in
   the planning notes before advancing.
5. Facilitate the user discussion in the stages below.
6. After each stage, update the planning notes with the confirmed decisions,
   rejected alternatives, assumptions, risks, and open questions.
7. Stop at each stage gate until the user has confirmed the stage or provided
   enough detail to resolve the open questions.
8. After functionality and behavior are confirmed, update the planning notes
   with a complete checkpoint, then compact context before starting the design
   decision review. If the client cannot compact context directly, reset or
   pause with a concise resume instruction that points to the planning notes
   path and this prompt.
9. After compaction or reset, reload the planning notes, this prompt, and the
   relevant source files before asking design-decision questions. Treat the
   confirmed functionality and behavior as the stable baseline for the design
   pass unless the user explicitly reopens it.
10. At the start of the design decision review, draft the design-decision
   review queue implied by the confirmed functionality and behavior, limited to
   decisions that could materially affect maintainability or extensibility.
   Record the queue in the planning notes. Record clear repo-supported
   recommendations without asking the user; get user feedback only for
   high-impact decisions that do not have a strong recommendation before
   marking them confirmed.
11. If the user gives feedback about the planning workflow itself, evaluate
   whether the feedback describes a generally useful workflow refinement. If it
   does, update the reusable workflow, prompt, or template artifacts directly
   and keep product planning notes focused on product decisions. If it is
   specific to the current roadmap discussion, record it as a planning-process
   note or facilitation preference for the current notes only.
12. When all stages are confirmed, mark the planning notes ready for
   implementation-plan drafting and summarize the handoff inputs.
13. Ask for explicit confirmation before drafting the implementation plan. If
   the user confirms, create or update
   `docs/implementation-plans/implementation-plan-<VERSION>.md` by following
   `.codex/prompts/implementation-plan-draft.md` and using the completed
   planning notes as the primary source. If the user does not confirm, stop
   after the planning-notes handoff summary.

Discussion stages:

1. Roadmap framing
   - Present the startup version briefing in plain language before asking
     planning questions. Cover what the version is, why it exists, the current
     repository or roadmap gap it is meant to close, prerequisite and successor
     links, primary feature-doc links, likely impacts on public APIs, CLI
     surface, persisted records, file layout, ownership boundaries, tests, and
     docs, and why the proposed discussion structure fits the version's scope.
   - State the visible assumptions, risks, constraints, and structure choices
     that should be validated with the user.
   - Ask whether the user has clarifying questions about the version briefing.
     Answer those questions before moving on, and record any resolved
     clarifications in the planning notes.
   - Ask what the user wants this version to optimize for relative to the
     roadmap description.
   - Gate: user-visible outcome, target audience, and planning priority are
     confirmed, and the user has had a chance to ask clarifying questions about
     the version briefing.
2. Intent discovery
   - Discuss workflows, success criteria, non-goals, constraints, and known
     operational realities.
   - Gate: goals, non-goals, done criteria, and constraints are confirmed.
3. Feature brainstorming
   - Propose useful capabilities grounded in the roadmap and feature docs.
   - Help the user sort them into include, defer, maybe, and out of scope.
   - Gate: candidate functionality is ready for behavior confirmation.
4. Functionality and behavior confirmation
   - Convert the brainstormed capability set into concrete included
     functionality, user-visible behavior, default behavior, failure behavior,
     and explicit deferrals.
   - Before asking each question batch, explain what capability or behavior is
     being decided, why it matters, expected impact on users or implementation
     boundaries, important considerations or tradeoffs, and the recommended
     default when one is supported by repo evidence.
   - Confirm what each included capability does, what it must not do, which
     behaviors are observable through public APIs, CLI output, persisted
     records, or docs, and which behaviors are deliberately left to later
     roadmap versions.
   - Gate: selected functionality, behavior, defaults, non-goals, and explicit
     deferrals are confirmed.
5. Context compaction/reset checkpoint
   - Record a complete checkpoint in the planning notes: stage readback,
     selected functionality, confirmed behavior, defaults, deferrals, open
     questions, and next-stage resume instructions.
   - Compact context before starting design decision review. If direct
     compaction is unavailable, reset or stop and ask the user to resume with
     the planning notes path and this prompt.
   - After resuming, reread the checkpoint and do not reopen functionality or
     behavior unless the user explicitly asks.
   - Gate: design review starts from a fresh or compacted context and the
     planning notes are the source of truth.
6. Design decision review
   - Map confirmed functionality and behavior to the current Loom architecture.
   - Before asking the user to settle individual choices, draft the
     design-decision review queue for this roadmap version from the confirmed
     functionality and behavior. Include only decisions that could materially
     affect maintainability or extensibility, such as ownership boundaries,
     import boundaries, extension points, durable schema or file-layout choices,
     public API shape, optional dependencies, compatibility policy, security or
     trust assumptions, future expansion paths, scalability, testing strategy,
     or accepted debt.
   - Do not include low-impact implementation details, local naming choices, or
     straightforward applications of established repository patterns in the
     user-facing decision queue.
   - For each candidate decision, first classify it:
     - `recorded recommendation`: maintainability or extensibility impact is
       real, but repo evidence gives a clear recommendation.
     - `needs discussion`: maintainability or extensibility impact is high and
       there is no strong recommendation.
     - `implementation detail`: maintainability and extensibility impact is low.
   - Record `recorded recommendation` decisions directly in the planning notes
     with the selected approach, rationale, alternatives rejected, debt, and
     revisit trigger. Do not ask the user to confirm these individually.
   - The facilitator owns queue completeness. Do not ask the user whether the
     queue is missing decisions or whether more decisions should be reviewed.
     Instead, evaluate the necessary design decisions from repo evidence,
     confirmed behavior, and feature docs, then surface only the decisions that
     genuinely need user feedback.
   - If the user asks for more design decisions to be considered, revisit the
     triage yourself. Add additional decisions only when they materially affect
     maintainability or extensibility; classify each added decision before
     deciding whether to record a recommendation or surface it for feedback.
     Do not turn that request into an open-ended user audit of the queue.
   - Present only the `needs discussion` decisions to the user. Keep the
     user-facing presentation independent per decision: state what the decision
     means, why it matters for maintainability or extensibility, the expected
     impact, implementation-relevant options, why there is no strong default,
     the tradeoffs and considerations, and the specific feedback needed from
     the user.
   - Discuss `needs discussion` decisions in small batches, usually one
     decision at a time when the tradeoffs are subtle. Do not ask the user to
     audit the hidden or recorded-recommendation portions of the queue.
   - Do not mark a `needs discussion` decision confirmed until user feedback has
     accepted the selected approach or provided enough direction to choose one.
   - For each confirmed decision, record the selected approach, user feedback,
     rejected alternatives, rationale, maintainability impact,
     extensibility/flexibility impact, future expansion impact, debt
     introduced, and revisit trigger.
   - Use `docs/implementation-plans/implementation-plan-v2.md` as an example
     of the expected plan-level design-decision depth.
   - Gate: the facilitator has completed the design-decision triage, every
     surfaced decision is reviewed with user feedback, clear recommendations
     are recorded without user review, and core design decisions, rejected
     alternatives, maintainability and extensibility assessment, flexibility and
     expansion assessment, and debt revisit triggers are confirmed.
7. Phase shaping
   - Convert the design into reviewable implementation phases.
   - Discuss phase order, granularity, dependencies, and review boundaries with
     the user, then refine the phase sketch until each phase is coherent.
   - For each phase, identify goal, scope, out of scope, acceptance criteria,
     test expectations, design impact, future compatibility, rejected
     alternatives, debt introduced, and reviewability.
   - Gate: phase breakdown is confirmed for implementation-plan drafting.
8. Handoff
   - Record the final source notes for the implementation-plan draft.
   - Identify unresolved assumptions, blockers, and plan-quality-gate risks.
   - Gate: planning notes are ready for the implementation-plan draft prompt,
     and the user has confirmed whether to draft the implementation plan now.

Question rules:

- Before asking a question, first answer discoverable facts from the repo.
- Ask questions in small batches of one to three high-impact choices.
- Prefer concrete alternatives with a recommended default.
- For functionality, behavior, and design-principle questions, lead with a short
  decision brief: what is being decided, why it matters, expected impact,
  considerations and tradeoffs, and the current recommended default.
- Use available structured user-input tools when practical; otherwise ask
  concise direct questions.
- Do not ask questions whose answer is already clear from the roadmap, feature
  docs, implementation plans, source, or tests.
- During design decision review, ask the user only about high-impact
  maintainability/extensibility decisions that do not have a clear
  repo-supported recommendation.
- If a question is open-ended by nature, ask it directly and explain which
  decision it affects.
- At the end of each user exchange, give a short readback of locked decisions,
  defaults, open questions, and the next stage focus, then record that readback
  in the planning notes.
- During design decision review, keep the decision queue visible in the notes
  and update each decision's status as `draft`, `reviewing`, `confirmed`, or
  `deferred`.

Workflow feedback rules:

- Treat user feedback about the planning workflow as actionable process input,
  not as a product requirement by default.
- First decide whether the feedback should change reusable workflow behavior,
  only the current roadmap planning session, or neither.
- For reusable feedback, update the relevant `.codex/workflows/`,
  `.codex/prompts/`, or `.codex/templates/` artifact directly and keep the
  change generic. Do not encode roadmap-version-specific or stage-specific
  examples unless the reusable workflow itself is explicitly about that
  artifact type.
- For current-session facilitation preferences, record a concise note in the
  planning notes without changing product scope or durable design decisions.
- When workflow feedback affects how future user questions are asked, preserve
  useful interaction qualities explicitly, such as presenting independent
  decisions with concrete options, context, tradeoffs, and the specific
  feedback needed.

Rules:

- This is pre-plan discovery, not phase implementation.
- Do not implement product code.
- Do not create phase branches, worktrees, PR bodies, or PRs.
- Do not draft the final implementation plan until the planning notes are ready
  and the user explicitly confirms they are happy for this workflow to enter the
  implementation-plan drafting prompt.
- Do not begin the design decision review until functionality and behavior are
  confirmed, a checkpoint is written, and context has been compacted, or reset
  only when compaction is unavailable.
- Do not enter phase shaping until maintainability/extensibility-impacting
  design decisions have either been recorded with a clear recommendation,
  reviewed with the user when no strong recommendation exists, or explicitly
  deferred with a rationale.
- Do not invent requirements not grounded in the roadmap, feature docs, current
  repository state, or confirmed user decisions.
- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Surface conflicts, tradeoffs, and rejected alternatives explicitly.
- Record accepted technical debt with a concrete revisit trigger.
- Prefer reviewable phases that can each become one coherent PR.
- If the selected roadmap version is too broad for one implementation plan,
  recommend a split and get user confirmation before continuing.

You are facilitating an interactive Loom roadmap-version planning process.

This prompt turns one roadmap version, such as `v3`, into durable planning
notes through tight discussion with the user. The notes are not the final
implementation plan. They are the decision log and source material that later
feed the implementation-plan draft, plan review, and plan refinement workflow.
They must record enough traceability, design-safety evidence, validation
strategy, and phase-shaping readiness that implementation agents do not invent
product behavior or structural design decisions later.
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
- `.codex/prompts/roadmap-version-planning-notes-functionality-agreement.md`
- `.codex/prompts/roadmap-version-planning-notes-design-agreement.md`
- `.codex/prompts/roadmap-version-design-safety-review.md`

Task:

1. Extract the selected roadmap version's baseline scope, prerequisites, primary
   feature docs, likely public surfaces, deferred work, and compatibility
   obligations.
2. Create or update
   `docs/implementation-plans/roadmap-<VERSION>-planning-notes.md` from
   `.codex/templates/roadmap-version-planning-notes.md`.
3. Populate source evidence and exploration coverage before asking questions
   that repository inspection can answer.
4. Start the discussion by presenting a comprehensive version briefing before
   asking the user to confirm functionality, behavior, or design principles.
   The briefing must cover what the version is, why it exists, what it impacts
   or links to, why the version appears structured the way it is, likely public
   surfaces or durable artifacts, visible constraints, and open assumptions.
5. Explicitly invite user clarifying questions about that briefing, answer them
   from repo evidence where possible, and record the resolved clarifications in
   the planning notes before advancing.
6. Facilitate the user discussion in the stages below.
7. After each stage, update the planning notes with the confirmed decisions,
   rejected alternatives, assumptions, risks, and open questions.
8. Stop at each stage gate until the user has confirmed the stage or provided
   enough detail to resolve the open questions.
9. After capability triage, run or follow
   `.codex/prompts/roadmap-version-planning-notes-functionality-agreement.md`
   on the same planning-notes artifact so the included capabilities and
   candidate requirements are resolved into a dependency-aware agreement queue
   before behavior confirmation continues.
10. After functionality and behavior are confirmed, update the planning notes
    with a complete checkpoint, then compact context before starting the design
    agreement review. If the client cannot compact context directly, reset or
    pause with a concise resume instruction that points to the planning notes
    path and this prompt.
11. After compaction or reset, reload the planning notes, this prompt,
    `.codex/prompts/roadmap-version-planning-notes-design-agreement.md`, and
    the relevant source files before asking design-agreement questions. Treat
    the confirmed functionality and behavior as the stable baseline for the
    design pass unless the user explicitly reopens it.
12. At the start of the design-agreement review, draft the proposed
   implementation shape and the design-agreement queue implied by the
   confirmed functionality and behavior. Limit the queue to decisions that
   could materially affect maintainability, extensibility, compatibility,
   domain neutrality, public contracts, import boundaries, file layout,
   persistence, failure behavior, or future refactor cost.
13. Classify each material design decision as `auto-approved candidate`,
   `recorded recommendation`, `needs discussion`, or `blocked`. Record clear
   repo-supported recommendations without asking the user; get user feedback
   only for high-impact decisions that do not have a strong recommendation
   before marking them confirmed.
14. Run or assign one design-safety review using
   `.codex/prompts/roadmap-version-design-safety-review.md` and
   `loom_design_safety_reviewer` after the proposed implementation shape and
   design-agreement triage are recorded, and before phase shaping or
   implementation-plan drafting. Resolve or record all blockers and required
   return-to-planning actions in the planning notes.
15. If the user gives feedback about the planning workflow itself, evaluate
   whether the feedback describes a generally useful workflow refinement. If it
   does, update the reusable workflow, prompt, or template artifacts directly
   and keep product planning notes focused on product decisions. If it is
   specific to the current roadmap discussion, record it as a planning-process
   note or facilitation preference for the current notes only.
16. When all stages are confirmed, mark the planning notes ready for
   implementation-plan drafting only if design-safety review, validation
   strategy, phase shaping, and implementation readiness have no unresolved
   blockers or `needs discussion` decisions.
17. Ask for explicit confirmation before drafting the implementation plan. If
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
3. Capability triage and candidate functional requirements
   - Propose useful capabilities grounded in the roadmap and feature docs.
   - Help the user sort them into include, defer, maybe, and out of scope.
   - Convert included capabilities into a small set of candidate functional
     requirements. For each candidate requirement, record what, why, scope,
     user-visible behavior, system behavior, capability enabled, validation
     idea, dependencies, and whether it is a recommended default, needs
     discussion, blocked, or confirmed.
   - Gate: included capabilities and candidate functional requirements are
     ready for functionality-agreement review.
4. Functionality-agreement review
   - Run or follow
     `.codex/prompts/roadmap-version-planning-notes-functionality-agreement.md`
     on the same planning-notes artifact.
   - Before asking the user to settle individual requirement choices, draft the
     functionality-agreement queue for this roadmap version from the confirmed
     intent, included capabilities, and candidate requirements.
   - Resolve repo-answerable queue items directly and record the rationale.
   - Present only unresolved high-impact requirement questions that materially
     affect what Loom is being built to do, why it is valuable, scope
     boundaries, requirement-level defaults, failure expectations, validation
     obligations, or explicit deferrals.
   - Ask one unresolved requirement question at a time in dependency order.
     State what is being locked, why it matters, the recommended answer, the
     main tradeoffs, and the exact feedback needed from the user.
   - Do not mark a queue item resolved until the planning notes show shared
     agreement on the requirement's what, why, scope, defaults, and
     deferrals.
   - Gate: the functionality-agreement queue is resolved and the user and
     facilitator are aligned on what is being built and why.
5. Functionality and behavior confirmation
   - Convert the capability and requirement set into a concrete behavior
     baseline: included functionality, user-visible behavior, default behavior,
     failure behavior, unsupported behavior, and explicit deferrals.
   - Before asking each question batch, explain what capability or behavior is
     being decided, why it matters, expected impact on users or implementation
     boundaries, important considerations or tradeoffs, and the recommended
     default when one is supported by repo evidence.
   - Confirm what each included capability does, what it must not do, which
     behaviors are observable through public APIs, CLI output, persisted
     records, or docs, and which behaviors are deliberately left to later
     roadmap versions.
   - Gate: selected functionality, functional requirements, behavior, defaults,
     non-goals, and explicit deferrals are confirmed.
6. Context compaction/reset checkpoint
   - Record a complete checkpoint in the planning notes: stage readback,
     selected functionality, confirmed behavior, defaults, deferrals, open
     questions, and next-stage resume instructions.
   - Compact context before starting design-agreement review. If direct
     compaction is unavailable, reset or stop and ask the user to resume with
     the planning notes path and this prompt.
   - After resuming, reread the checkpoint and do not reopen functionality or
     behavior unless the user explicitly asks.
   - Gate: design review starts from a fresh or compacted context and the
     planning notes are the source of truth.
7. Design-agreement review
   - Run or follow
     `.codex/prompts/roadmap-version-planning-notes-design-agreement.md` on
     the same planning-notes artifact.
   - Map confirmed functionality and behavior to the current Loom architecture
     and draft the proposed implementation shape: likely modules, public
     classes/functions/protocols, internal helpers, data flow, dependency
     direction, extension points, and compatibility constraints.
   - Before asking the user to settle individual choices, draft the
     design-agreement queue for this roadmap version from the confirmed
     functionality and behavior. Include only decisions that could materially
     affect maintainability, extensibility, domain neutrality, public contracts,
     ownership boundaries, import boundaries, extension points, durable schema
     or file-layout choices, optional dependencies, compatibility policy,
     security or trust assumptions, future expansion paths, scalability,
     testing strategy, failure semantics, or accepted debt.
   - Do not include low-impact implementation details, local naming choices, or
     straightforward applications of established repository patterns in the
     user-facing decision queue.
   - For each candidate decision, first classify it:
     - `auto-approved candidate`: local, traceable to approved behavior,
       straightforward to validate, and low risk, subject to design-safety
       reviewer challenge.
     - `recorded recommendation`: maintainability or extensibility impact is
       real, but repo evidence gives a clear recommendation.
     - `needs discussion`: maintainability or extensibility impact is high and
       there is no strong recommendation.
     - `blocked`: implementation-plan drafting would require inventing product
       behavior, public contracts, architecture boundaries, failure semantics,
       validation obligations, or phase boundaries.
   - Record `recorded recommendation` decisions directly in the planning notes
     with the selected approach, rationale, alternatives rejected, debt, and
     revisit trigger. Do not ask the user to confirm these individually.
   - Record `auto-approved candidate` decisions with traceability, rationale,
     adversarial assumptions considered, validation obligations, and residual
     risk so the design-safety review can challenge them.
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
   - Present only the `needs discussion` and `blocked` decisions to the user.
     Keep the user-facing presentation independent per decision: state what the
     decision means, why it matters for maintainability or extensibility, the
     expected impact, implementation-relevant options, why there is no strong default,
     the tradeoffs and considerations, and the specific feedback needed from
     the user.
   - Ask one unresolved design question at a time in dependency order. Do not
     ask the user to audit the hidden or recorded-recommendation portions of
     the queue.
   - Do not mark a `needs discussion` decision confirmed until user feedback has
     accepted the selected approach or provided enough direction to choose one.
   - For each confirmed decision, record the selected approach, user feedback,
     rejected alternatives, rationale, maintainability impact,
     extensibility/flexibility impact, future expansion impact, debt
     introduced, and revisit trigger.
   - Use `docs/implementation-plans/implementation-plan-v2.md` as an example
     of the expected plan-level design-decision depth.
   - Gate: the facilitator has completed the proposed implementation shape and
     design-agreement triage, every surfaced decision is reviewed with user
     feedback, clear recommendations are recorded without user review, and core
     design decisions, rejected alternatives, maintainability and extensibility
     assessment, flexibility and expansion assessment, and debt revisit
     triggers are confirmed or ready for design-safety review.
8. Design safety review
   - Run or assign `loom_design_safety_reviewer` with
     `.codex/prompts/roadmap-version-design-safety-review.md`.
   - Review the returned blockers, overturned auto-approved candidates,
     recorded recommendations, residual risks, and decisions needing
     discussion.
   - Raise only findings that remain ambiguous, blocked, or materially risky
     after manager reconciliation. Record each answer before moving on.
   - Gate: design-safety review is passed or all blockers are resolved,
     deferred with explicit rationale, or returned to an earlier planning
     stage.
9. Examples and validation strategy
   - Define examples or demonstrations that show the approved behavior in Loom
     context.
   - Define required validation coverage for behavior, edge cases, failure
     modes, integration boundaries, docs/templates/workflows, and affected
     public contracts.
   - Raise individual validation choices only when coverage scope, cost, public
     contract, or acceptance criteria remain ambiguous.
   - Gate: example set and validation strategy are approved.
10. Phase shaping
   - Convert the design into reviewable implementation phases.
   - Discuss phase order, granularity, dependencies, and review boundaries with
     the user, then refine the phase sketch until each phase is coherent.
   - For each phase, identify goal, scope, out of scope, acceptance criteria,
     test expectations, design impact, future compatibility, rejected
     alternatives, debt introduced, and reviewability.
   - Gate: phase breakdown is confirmed for implementation-plan drafting.
11. Handoff
   - Record the final source notes for the implementation-plan draft.
   - Complete implementation readiness checks for roadmap-to-requirement,
     requirement-to-design, design-safety review, example-to-validation,
     phase-shaping readiness, and unresolved blocked or needs-discussion
     functionality-agreement or design-agreement decisions.
   - Identify unresolved assumptions, blockers, accepted risks, and
     plan-quality-gate risks.
   - Gate: planning notes are ready for the implementation-plan draft prompt,
     and the user has confirmed whether to draft the implementation plan now.

Question rules:

- Before asking a question, first answer discoverable facts from the repo.
- Ask questions in small batches of one to three high-impact choices during
  roadmap framing, intent discovery, capability triage, and behavior
  confirmation.
- Prefer concrete alternatives with a recommended default.
- For functionality, behavior, and design-principle questions, lead with a short
  decision brief: what is being decided, why it matters, expected impact,
  considerations and tradeoffs, and the current recommended default.
- Use available structured user-input tools when practical; otherwise ask
  concise direct questions.
- Do not ask questions whose answer is already clear from the roadmap, feature
  docs, implementation plans, source, or tests.
- During functionality-agreement review, ask the user only about high-impact
  requirement, scope, default, or deferral choices that do not have a clear
  repo- or roadmap-supported recommendation.
- During functionality-agreement review and design-agreement review, ask only
  one unresolved queue item at a time in dependency order until the queue has
  no unresolved high-impact `needs discussion` or `blocked` items.
- During design-agreement review, ask the user only about high-impact
  maintainability/extensibility decisions that do not have a clear
  repo-supported recommendation.
- If a question is open-ended by nature, ask it directly and explain which
  decision it affects.
- At the end of each user exchange, give a short readback of locked decisions,
  defaults, open questions, and the next stage focus, then record that readback
  in the planning notes.
- During functionality-agreement review, design-agreement review, and
  design-safety review, keep the relevant queue visible in the notes and update
  each item's status as `draft`, `reviewing`, `confirmed`, `deferred`, or
  `blocked`.

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
- Do not draft the final implementation plan until the planning notes are ready,
  design-safety review has passed or recorded accepted risks, implementation
  readiness has no unresolved blockers, and the user explicitly confirms they
  are happy for this workflow to enter the implementation-plan drafting prompt.
- Do not exit the functionality-agreement review or design-agreement review
  while the queue still contains unresolved high-impact `needs discussion` or
  `blocked` items unless the planning notes explicitly record the blocker and
  why the workflow cannot resolve it in scope.
- Do not begin the design-agreement review until functionality and behavior are
  confirmed, a checkpoint is written, and context has been compacted, or reset
  only when compaction is unavailable.
- Do not enter phase shaping until maintainability/extensibility-impacting
  design decisions have either been recorded with a clear recommendation,
  reviewed with the user when no strong recommendation exists, or explicitly
  deferred with a rationale, and the design-safety review has not identified
  unresolved blockers.
- Do not invent requirements not grounded in the roadmap, feature docs, current
  repository state, or confirmed user decisions.
- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Surface conflicts, tradeoffs, and rejected alternatives explicitly.
- Record accepted technical debt with a concrete revisit trigger.
- Prefer reviewable phases that can each become one coherent PR.
- If the selected roadmap version is too broad for one implementation plan,
  recommend a split and get user confirmation before continuing.

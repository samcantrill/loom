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

Read before asking design questions:

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
3. Facilitate the user discussion in the stages below.
4. After each stage, update the planning notes with the confirmed decisions,
   rejected alternatives, assumptions, risks, and open questions.
5. Stop at each stage gate until the user has confirmed the stage or provided
   enough detail to resolve the open questions.
6. After functionality and behavior are confirmed, update the planning notes
   with a complete checkpoint, then compact context before starting the design
   decision review. If the client cannot compact context directly, reset or
   pause with a concise resume instruction that points to the planning notes
   path and this prompt.
7. After compaction or reset, reload the planning notes, this prompt, and the
   relevant source files before asking design-decision questions. Treat the
   confirmed functionality and behavior as the stable baseline for the design
   pass unless the user explicitly reopens it.
8. When all stages are confirmed, mark the planning notes ready for
   implementation-plan drafting and summarize the handoff inputs.
9. Ask for explicit confirmation before drafting the implementation plan. If
   the user confirms, create or update
   `docs/implementation-plans/implementation-plan-<VERSION>.md` by following
   `.codex/prompts/implementation-plan-draft.md` and using the completed
   planning notes as the primary source. If the user does not confirm, stop
   after the planning-notes handoff summary.

Discussion stages:

1. Roadmap framing
   - Summarize the roadmap version in plain language.
   - Ask what the user wants this version to optimize for relative to the
     roadmap description.
   - Gate: user-visible outcome, target audience, and planning priority are
     confirmed.
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
   - Step through the core design decisions before phase shaping. Cover public
     Python APIs, CLI surface, persisted records and schemas, file layout,
     ownership boundaries, import boundaries, optional dependencies, security
     and trust assumptions, failure modes, compatibility, extension points,
     flexibility boundaries, future expansion paths, maintainability,
     extensibility, scalability, and accepted debt.
   - For each core decision, record the selected approach, rejected
     alternatives, rationale, maintainability impact, extensibility/flexibility
     impact, future expansion impact, debt introduced, and revisit trigger.
   - Use `docs/implementation-plans/implementation-plan-v2.md` as an example
     of the expected plan-level design-decision depth.
   - Gate: core design decisions, rejected alternatives, maintainability and
     extensibility assessment, flexibility and expansion assessment, and debt
     revisit triggers are confirmed.
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
- Use available structured user-input tools when practical; otherwise ask
  concise direct questions.
- Do not ask questions whose answer is already clear from the roadmap, feature
  docs, implementation plans, source, or tests.
- If a question is open-ended by nature, ask it directly and explain which
  decision it affects.
- At the end of each user exchange, give a short readback of locked decisions,
  defaults, open questions, and the next stage focus, then record that readback
  in the planning notes.

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
- Do not invent requirements not grounded in the roadmap, feature docs, current
  repository state, or confirmed user decisions.
- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Surface conflicts, tradeoffs, and rejected alternatives explicitly.
- Record accepted technical debt with a concrete revisit trigger.
- Prefer reviewable phases that can each become one coherent PR.
- If the selected roadmap version is too broad for one implementation plan,
  recommend a split and get user confirmation before continuing.

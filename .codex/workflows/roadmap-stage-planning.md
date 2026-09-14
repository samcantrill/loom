# Roadmap Stage Planning

## Goal And Ownership

Create one complete planning packet, a compact implementation manifest, and one
ready execution card per accepted phase. The default is manager authorship,
one independent final plan review, then maintainer approval and landing.
Use `$loom-roadmap-planning` as the entrypoint. Planning does not execute a stage.

Read AGENTS.md, .codex/prompts/subagent-lifecycle.md, the selected roadmap entry,
current templates, and directly relevant source/tests/configuration. Record the
root, branch, revision, and relevant dirty paths. Preserve unrelated work and
use an ordinary task branch/worktree for planning; never edit local develop.
Use `$loom-targeted-validation` for coverage and inspect relevant active entries
in docs/improvement-log.md.

## Evidence And Artifact Ownership

- New packets use planning layout `planning-manifest-and-cards-v1`.
  planning.md owns the outcome, card index, material decisions, and approval.
- Domain cards under planning/<domain-slug>.md own detailed requirements,
  evidence, behavior, public/durable contracts, examples, and validation IDs.
  Each detailed ID has one authoritative indexed card. Split by coherent
  contract, not drafting pass or word count; one card is sufficient when cohesive.
- implementation-plan.md owns phase order/dependencies/status, shared contract
  references, traceability, and the authoritative final readiness receipt.
  Its execution layout remains `manifest-and-phase-plans-v1`.
- Each phases/<phase-slug>.md owns one bounded implementation result, exact
  upstream references, selected checks, and execution/completion facts.
- Keep current scope, identities, decision matrices, and evidence recoverable.
  Remove duplicated definitions, logs, and routine history. No numerical word,
  phase, or slice target applies; never shorten unique contract detail for size.

Existing single-file planning packets remain valid, including approved Stages
40 and 41. Their planning.md still owns detailed contracts and their manifest
Quality Gate is the grandfathered readiness receipt. Do not rewrite completed
history or invalidate recorded approval/review merely to change layout. Audit
unfinished legacy packets on resumption; correct missing/conflicting contracts
or relevant drift, not formatting differences. Preserve approved validation
obligations unless deliberately revised with rationale at their owner.

## Minimum Design And Phase Boundaries

Start with the minimum operator-visible outcome and existing end-to-end path.
Find adjacent/equivalent behavior and decide whether to reuse, extend, share a
primitive for current consumers, or remain separate. Every material abstraction,
public surface, durable artifact/state, and validation dimension needs a current
consumer, requirement, boundary, or demonstrated failure. Future reuse alone is
reason to defer machinery. Private helpers and local wiring remain discretionary.

Each phase is a small independently mergeable result. Record in its card:

| Boundary | Required evidence |
| --- | --- |
| Observable result | One usable capability, correction, or coherent migration after merge |
| Cohesion | Why the edits ship together; independently useful outcomes excluded |
| Ownership | Modules, symbols, configuration, or exact migration population |
| Dependencies | Available contracts consumed and the contract supplied |
| Acceptance | A local check distinguishing correctness from a plausible wrong result |
| Merge boundary | Supported state even if later phases never run |
| Exclusions | Adjacent work assigned elsewhere |

Split independently acceptable outcomes. Keep producer, consumer, docs, and
tests together when one invariant requires atomic delivery. Do not manufacture
independence with placeholder APIs or layer-only scaffolding. Before approval,
update the index and cards together. During implementation the manager may split
unstarted work within accepted behavior with explicit ownership, dependency,
validation, and rationale updates. Preserve merged identity and do not silently
repartition an open PR. Changed behavior, durable shapes, or trust boundaries
return to the affected planning decision.

## Draft, Review, Approval, And Landing

1. Author evidence, requirements, minimum design, examples, validation, and the
   manifest/cards as one complete draft. Existing functionality/design prompts
   guide authoring; they are not serial approval gates. Resolve repository-backed
   mechanics locally. Raise material product/public/durable/compatibility choices
   early with recommendations and tradeoffs; batch independent related questions
   and handle dependent questions sequentially. Continue independent drafting.
2. Verify ID ownership and traceability: every accepted ID maps to a phase,
   shared reference, or explicit deferral. Finite execution matrices name values,
   executable owners, lifecycle effects, and discriminating result/state oracles.
   Material ambiguity blocks readiness; private discretion does not.
3. Use one independent loom_plan_reviewer for the complete packet, following
   .codex/prompts/implementation-plan-review.md. It must not be the author.
   It checks necessity, contracts, traceability, examples, phase boundaries,
   proportional validation, and readiness.
4. The manager fixes qualified findings using implementation-plan-refinement.md.
   The same reviewer may confirm affected substantive corrections once (one
   replacement if its runtime is unavailable). Do not restart full design/review
   loops. Remaining blockers return to their owning decision; optional hardening
   does not expand acceptance criteria.
5. Record the final passed receipt in the implementation manifest: reviewed
   packet revision/tree and paths, source assumptions, findings disposition,
   reviewer result, accepted risks, post-review changes, and reopen triggers.
   planning.md links to this receipt instead of maintaining another verdict.
6. Obtain maintainer approval of the concrete scope, complexity, risks, and
   deferrals, reusing existing approval when still applicable. List the exact
   roadmap and packet paths and land them on develop under AGENTS.md's local
   validation and review policy. Verify they are tracked, path-clean, and present
   on the selected implementation base. Record landing facts without creating a
   self-referential commit SHA. Do not create a stage worktree before this handoff.

## Bounded Help

The manager uses functionality/design agreement and implementation-plan-draft
prompts locally. One named unresolved design question may use
loom_design_safety_reviewer with exact card paths and its design-safety prompt;
one specific codebase question may use loom_architecture_explorer. Use one
assignment and at most one targeted repair per question. Complexity alone does
not activate a chain of specialists. Optional help does not replace the required
independent final review. Follow subagent-lifecycle.md and verify returned work.

## Stops And Terminal Records

Do not claim readiness with missing/conflicting cards, unowned IDs, unresolved
material decisions, unreviewed substantive changes, unjustified complexity, or
insufficient validation. Missing required independent review needs an explicit
recorded maintainer override with accepted risk. Use `$loom-process-improvement`
for qualifying reusable weaknesses; logging adds no product scope.

Optional terminal compaction is planning-owned and uses
.codex/templates/roadmap-stage-completion.md only after implementation provides
verified outcomes, terminal phase dispositions, exact validation revision/tree
and subsequent delta, current owner links, and cleanup facts. It is not another
product-completion gate. If requested, create a revision-bound candidate list,
disposition every incoming reference to planning.md, implementation-plan.md, and
nested packet files, and retain anything still instructing live work or whose
removal is uncertain. Preserve unique contract/evidence owners before removal.
Compaction selected during active implementation stays in its stage worktree
and uses the same publication/synchronization gate before worktree removal.

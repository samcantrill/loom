# Codex Workflow Templates

Current durable artifacts:

| Artifact | Template | Destination |
| --- | --- | --- |
| Planning manifest | roadmap-stage-planning.md | docs/roadmap/stage-<N>/planning.md |
| Coherent domain contract card | roadmap-stage-planning-card.md | docs/roadmap/stage-<N>/planning/<domain-slug>.md |
| Compact implementation manifest | roadmap-stage-implementation-plan.md | docs/roadmap/stage-<N>/implementation-plan.md |
| One phase execution plan | phase-execution-plan.md | docs/roadmap/stage-<N>/phases/<phase-slug>.md |
| Compact implementation completion fields | phase-implementation-handoff.md | The phase execution plan completion section |
| Required plan review and affected correction | plan-review-report.md and plan-refinement-summary.md | Implementation manifest readiness receipt |
| Optional terminal completion | roadmap-stage-completion.md | Planning-owned completion record after verified implementation |

Skills route intent, workflows define sequencing, prompts define procedures,
agents define runtime authority, and templates define current durable state.
Existing single-file planning packets remain valid under the planning workflow.

Do not create new assignment, PR-body, PR-review, refinement-report, or
merge-record sidecars. The corresponding templates are retained only for legacy
history. Git and GitHub retain detailed lifecycle evidence.

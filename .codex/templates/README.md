# Codex Workflow Templates

Current durable artifacts:

| Artifact | Template | Destination |
| --- | --- | --- |
| Current roadmap planning | roadmap-stage-planning.md | docs/roadmap/stage-<N>/planning.md |
| Compact implementation manifest | roadmap-stage-implementation-plan.md | docs/roadmap/stage-<N>/implementation-plan.md |
| One phase execution plan | phase-execution-plan.md | docs/roadmap/stage-<N>/phases/<phase-slug>.md |
| Compact implementation completion fields | phase-implementation-handoff.md | The phase execution plan completion section |
| Optional plan review/correction | plan-review-report.md and plan-refinement-summary.md | Manager thread or manifest quality-gate section |

Workflows define sequencing, prompts define procedures, agents define optional
role authority, and templates define current durable state.

Do not create new assignment, PR-body, PR-review, refinement-report, or
merge-record sidecars. The corresponding templates are retained only for legacy
history. Git and GitHub retain detailed lifecycle evidence.

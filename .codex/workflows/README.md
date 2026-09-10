# Codex Workflow Entrypoints

| Entrypoint | Purpose |
| --- | --- |
| roadmap-stage-planning.md | Produce approved current-state planning, a compact implementation manifest, and linked phase execution plans |
| roadmap-stage-implementation.md | Execute an approved manifest through one persistent stage worktree, phase PRs, independent review, verified merge, metadata, synchronization and cleanup |

Workflows own sequencing and gates. Prompts own bounded procedures. Agents own
model and authority. Templates own durable artifact shape.

Lean planning is manager-local. Implementation normally uses manager authorship
and one independent phase reviewer. Execution delegation, plan refinement and
blocker repair are bounded optional roles. The manager prompt owns the shared
Git procedure; tools/phase_workflow.py owns its mechanical checks.

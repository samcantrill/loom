# Loom Workflow Entrypoints

For repository development, start with a skill and the stage:

```text
Use $loom-roadmap-planning to plan Stage <N>.
Use $loom-roadmap-implementation to implement Stage 40 through completion.
```

Start from the Loom control checkout. The implementation manifest and manager
workflow supply stage paths and lifecycle mechanics; the user need not repeat
branch names, commands, phase cards, or merge steps. Explicit stage execution
uses recorded approval and proceeds through that stage only. Explanation and
read-only review requests remain read-only.

| Skill | Canonical owner / purpose |
| --- | --- |
| loom-roadmap-planning | roadmap-stage-planning.md: complete draft, independent final review, approval and landing |
| loom-roadmap-implementation | roadmap-stage-implementation.md: stage worktree, phase PRs, validation/review, verified merge, synchronization and cleanup |
| loom-targeted-validation | AGENTS.md and tests/README.md: select sufficient checks and reuse current evidence |
| loom-process-improvement | docs/improvement-log.md: reusable pattern evidence and promotion |

Repository skills live in `.agents/skills/`. If the current session does not
list them, start a session scoped to this Loom checkout; the explicit SKILL.md
path is also a usable instruction entrypoint. Static metadata validation does
not prove that a host has refreshed its skill list.

These are Loom development workflows. The portable prepare/run/monitor/diagnose
skills planned in Stage 40 operate experiments and remain separate.

Skills route intent; workflows own gates; prompts own bounded procedures;
agents own runtime configuration/authority; templates own artifact shape.
Planning and implementation use manager authorship with their required independent
review. Named specialist help and execution delegation remain bounded options.
The manager prompt owns Git sequencing; tools/phase_workflow.py owns mechanics.
Existing approved packets keep their contracts, approval, and required checks.

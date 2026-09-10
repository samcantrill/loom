---
name: loom-roadmap-planning
description: Plan, replan, review, or explain one Loom roadmap stage, including its behavior, design, validation, implementation manifest, and phase cards. Do not use for executing an approved stage or ordinary feature planning.
---

# Loom Roadmap Planning

Route the requested stage to `.codex/workflows/roadmap-stage-planning.md`.
The workflow owns drafting, independent review, approval, and landing.

1. Identify the stage and read `AGENTS.md` and the planning workflow completely.
2. Read the selected `docs/roadmap.md` entry and existing stage artifacts.
   Load only the templates, prompts, and source/test evidence needed for that
   stage. Preserve existing approved contracts and supported legacy layouts.
3. Scan the index in `docs/improvement-log.md`; read active entries only when
   their scope or promotion owner intersects this task.
4. For planning or continuation, follow the complete-draft workflow and its
   required independent final review. Named uncertainty may receive bounded
   specialist help; it does not create serial approval gates.

An explanation or read-only review request does not authorize edits, specialist
execution, publication, or implementation. Keep answers within that intent.
Ask about material product choices; resolve repository-backed mechanics locally.

Use `$loom-targeted-validation` for coverage and `$loom-process-improvement` for
qualifying reusable problems. Keep product decisions at their stage owner.
After explicit execution instruction for an approved, landed packet, hand off
to `$loom-roadmap-implementation`.

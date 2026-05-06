# Phase 2 Execution Plan: CLI Foundation And Shared Output

## Metadata

- Status: final phase execution plan; implementation pending
- Feature focus: CLI Core
- PR title: `CLI Core - Phase 2: Foundation and Shared Output`
- Branch: `codex/add-cli-foundation`
- Worktree: `/home/samcantrill/work/loom-worktrees/add-cli-foundation`
- Phase execution plan path: `docs/phases/add-cli-foundation.md`
- Full plan: `docs/implementation-plans/implementation-plan-v2.md`
- Source phase: Phase 2 - CLI Foundation And Shared Infrastructure
- Stack predecessor: none; Phase 1 is merged.
- Base branch: local `develop` at `8fcf084` (`docs: enable codex-managed phase merges`)
- Target branch: `develop`
- Merge eligibility: root phase PR is merge-eligible after automated review and CI because the target is `develop`.
- Workflow path: expanded path, selected because this phase introduces the public console script, shared CLI error/JSON output contracts, and import-boundary policy used by later command phases.
- Plan quality gate: passed in `docs/implementation-plans/implementation-plan-v2.md`; no blocking plan-review findings remain.
- Draft/refine status: scope-complete plan drafted in this artifact; no separate refinement pass needed unless validation or review exposes a blocker.
- Phase implementation refinement budget: unused.
- PR review budget: unused.
- Blockers: none known.

## Objective

Add the command-neutral v2 CLI foundation: console entry point, import-light parser, version/help behavior, return-code preserving `main(argv)`, shared output format parsing, JSON envelopes with top-level warnings, and text/JSON error formatting.

## Scope

- Create or complete `src/loom/cli/main.py`, `errors.py`, `options.py`, `formatting.py`, and `results.py`.
- Add a `[project.scripts]` entry for `loom`.
- Register v2 command names without implementing validate/plan/run behavior.
- Keep top-level parser construction and help/version import-light.
- Provide reusable output and error helpers for later command phases:
  - `OutputFormat` with `text` and `json`;
  - warning payload dataclass or helper;
  - JSON success/error envelopes with `schema_version`, `ok`, top-level `warnings`, and `result` or `error`;
  - structured error payload normalization when a known exception exposes structured data;
  - `--traceback` handling for text and JSON modes.

## Out Of Scope

- Functional `loom validate`, `loom plan`, or `loom run` behavior.
- Config composition, target construction, planning, execution, stores, plugins, optional backends, shell completion, rich terminal tables, or runtime option models.
- Importing command modules that need optional dependencies or project targets at top-level help time.

## Acceptance Criteria

- `loom --help` and `loom --version` work through `main(argv)` and the installed console script metadata.
- `main(argv)` returns integer exit codes rather than raising `SystemExit`.
- Argparse usage errors return `2` as text on stderr.
- `KeyboardInterrupt` returns `130`.
- Known and unknown errors are concise by default and honor `--traceback`.
- JSON envelopes are stable and include top-level `warnings`.
- JSON errors preserve structured error fields when parsing has reached a known `--format json` command context.
- Package/import tests prove `import loom` does not import `loom.cli`, and CLI help does not import config, pipeline, stores, project code, plugins, or optional backends.

## Design Notes

- Later behavior-bearing command modules should register their parser through a small `register_subparser(...)` seam. In this phase, placeholder commands may be registered with import-light handlers that fail with a structured unsupported-command error.
- Argparse usage errors remain text because command format may be unavailable or invalid.
- A parsed `--format json` command should receive JSON error envelopes for command-handler failures.
- Top-level `--traceback` should be accepted before or after the command only where argparse can support it without complicated parsing; tests should lock whichever grammar is implemented.
- Use only standard library modules in the CLI foundation.

## Test Plan

- Package:
  - console script metadata exists;
  - root import remains CLI-free;
  - `loom --help` subprocess remains import-light.
- Unit:
  - parser construction, top-level help/version;
  - `main(argv)` exit codes for success/help/version/usage/interruption;
  - output format parsing;
  - warning payload and JSON envelope shape;
  - text and JSON error rendering, including structured error payloads and traceback details.
- E2E:
  - console entry point or module invocation for `--help`/`--version` if cheap through the installed project environment.
- Contract/integration/opt-in:
  - none required for this command-neutral phase.

## Validation Commands

Targeted:

```sh
uv run pytest tests/unit/loom/cli tests/package/test_import_boundaries.py tests/package/test_public_api.py -q
```

Final gate:

```sh
make validate-pr
make test-summary
```

## Reviewability

- Review CLI package files, `pyproject.toml`, package/import tests, unit CLI tests, and the Phase 2 execution plan.
- Confirm the diff does not implement validate/plan/run behavior early.
- Confirm parser/help paths do not load optional config dependencies, stores, plugins, project target modules, or runtime backends.

## Completion Notes

- Draft plan: completed in this commit.
- Implementation summary:
- Implementation validation:
- PR preparation:
- Merge notes:
- Remaining blockers:

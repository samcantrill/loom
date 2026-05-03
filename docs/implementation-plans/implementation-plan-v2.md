# Implementation Plan v2

## Goal

Implement `loom` v2 as the first functional command-line layer over the v0
local runtime kernel and v1 config composition.

The v2 target is a thin, domain-neutral `argparse` CLI that lets users validate,
plan, and run v0 pipelines from scripts and terminals without duplicating config,
pipeline, planning, store, resume, or execution logic in CLI modules.

## Context

The roadmap defines v2 as "CLI core":

- Functional `loom` entry point using the standard library.
- `loom --help`, `loom --version`, top-level exception handling, and exit-code
  mapping.
- `loom validate CONFIG` over v0 config composition and pipeline validation.
- `loom plan CONFIG` over v0 planning, selectors, resume, and dry-run
  explanations.
- `loom run CONFIG` over the v0 local executor and `PipelineRunner`.
- Shared CLI parsing helpers that convert arguments into public Python API
  objects.
- CLI tests and small end-to-end tests using synthetic local pipelines.

V2 should be planned and implemented only after v0 has landed and v1 config
composition behavior has landed, or after the public APIs named below are
otherwise available. V2 is intentionally narrow: it is a presentation and
invocation layer, not a new runtime model.

## Desired Outcome

After v2 is complete:

- Installing `loom` exposes a `loom` console command.
- `loom --help` and command help are import-safe and do not load project stage
  modules, plugins, optional executor backends, or heavy operational adapters.
- `loom validate CONFIG` composes config, validates the pipeline, and reports
  success or structured errors.
- `loom plan CONFIG` shows ordered stage decisions and reasons without executing
  stages.
- `loom run CONFIG` executes through the v0 local runner and prints a concise
  summary.
- Commands intended for automation support JSON output from structured result
  objects.
- CLI modules remain the outermost layer and are not imported by config,
  pipeline, stores, artifacts, provenance, or execution internals.

## Non-Goals

- No `loom status`, `loom logs`, or `loom artifacts` commands. Those belong to
  v3 diagnostics and preflight.
- No `loom stage run` worker command. That belongs to v5 subprocess execution.
- No typed `RunOptions`, `ResumeOptions`, `ExecutionOptions`,
  `ResourceRequest`, or runtime profile model. Those belong to v4.
- No subprocess, SLURM, Docker, Apptainer, remote store, plugin, sweep, catalog,
  bundle, retry, timeout, cleanup, dashboard, shell completion, or rich progress
  behavior.
- No new config composition, pipeline validation, planning, resume, or runner
  algorithms inside `loom.cli`.
- No new heavyweight runtime dependency such as Click, Typer, Rich, or Pydantic
  beyond whatever earlier versions already introduced.
- No domain-specific commands, schemas, stages, codecs, reports, datasets, or
  project import assumptions.

## Prerequisites

V2 depends on v0/v1 public Python APIs or equivalent stable facades:

- `loom.config.compose_config`
- config include, replacement, copy, and source snapshot behavior as part of
  composition
- pipeline spec parsing and validation from resolved config
- stage selector construction or normalized selector inputs
- execution planning and same-run-directory resume decisions
- local run/artifact store opening where planning and running need existing
  state
- `PipelineRunner` local execution
- shared `LoomError` roots and broad subsystem errors
- result/status/plan models that can be converted to plain data

If v0 exposes the behavior but not a small CLI-friendly facade, v2 may add the
minimal facade in the owning package. For example, pipeline validation helpers
belong in `loom.pipeline`, not `loom.cli`; runner request helpers belong in
`loom.pipeline.execution`, not `loom.cli`.

## Constraints

- Preserve the source-tree boundaries in `docs/structure.md`.
- Keep `loom` domain-neutral.
- Keep `loom.__init__` cheap and safe. It must not import `loom.cli`.
- Use `argparse` from the standard library.
- Do not add runtime dependencies for CLI ergonomics in v2.
- CLI JSON output must be generated from structured data, not by parsing human
  text.
- CLI errors must use shared `LoomError` context where available.
- Commands must be testable through `main(argv)` without shelling out.
- Run validation commands before PR review:

```sh
make validate-pr
make test-summary
```

## Design Principles

- The CLI parses arguments, calls Python APIs, formats results, and returns exit
  codes.
- Business logic remains in config, pipeline, planning, execution, stores, and
  artifacts.
- Human output should be concise and stable.
- Machine output should be explicit, versioned, and structured.
- Parser options should use names that can later map cleanly to v4 runtime
  option objects, even though v2 does not implement those objects.
- Future commands should reuse common parser, error, option, and formatting
  helpers rather than inventing a separate CLI style per feature.

## Key Design Choices

- `argparse` is the v2 CLI framework. It is enough for validate/plan/run and
  avoids adding dependencies before the command surface proves it needs them.
- V2 adds a console script:

```toml
[project.scripts]
loom = "loom.cli.main:main"
```

- `main(argv: Sequence[str] | None = None) -> int` is the testable entry point.
  The console script exits with its return code.
- CLI option dataclasses are adapters only. They preserve parsed command-line
  intent and convert to existing v0 API inputs. They do not define canonical
  runtime semantics.
- `--executor` is accepted by `loom run` to establish the future shape, but v2
  supports only `local`. Unsupported executors fail clearly without importing
  optional backends.
- `--dry-run` on `loom run` delegates to the same planning path as
  `loom plan`.
- JSON result envelopes include a CLI schema version. These schemas are
  automation-facing output contracts, not persisted run-store schemas.
- CLI import-boundary tests are part of the acceptance criteria because later
  roadmap stages add plugin discovery and optional backends that must not become
  import-time side effects.

## Public CLI Surface

### Top Level

```text
loom --help
loom --version
loom [--traceback] COMMAND ...
```

Top-level options:

- `--version`: print the installed `loom` version and exit 0.
- `--traceback`: show full tracebacks for unexpected errors and for known errors
  when debugging.

### `loom validate`

Command:

```text
loom validate CONFIG
```

Options:

- `--overlay PATH`, repeatable.
- `--set KEY=VALUE`, repeatable.
- `--format text|json`, default `text`.
- `--strict`, accepted only if a v0 validation API already defines strict
  behavior; otherwise omit it from the implemented parser rather than inventing
  semantics.

Behavior:

- Compose the config through `loom.config`.
- Build and validate the pipeline through public `loom.pipeline` APIs.
- Print success with the config path and stage count.
- On failure, return the matching config or pipeline exit code.
- Do not execute stages.
- Do not write run state.
- Do not directly instantiate stage targets unless v0 validation explicitly
  requires that.

### `loom plan`

Command:

```text
loom plan CONFIG
```

Options:

- `--overlay PATH`, repeatable.
- `--set KEY=VALUE`, repeatable.
- `--run-dir RUN_DIR`.
- `--resume`.
- `--from-stage STAGE`.
- `--only-stage STAGE`, repeatable.
- `--force-stage STAGE`, repeatable.
- `--skip-stage STAGE`, repeatable.
- `--explain STAGE`.
- `--format text|json`, default `text`.

Behavior:

- Compose config and build the pipeline spec through v0 APIs.
- Convert selector flags into the v0 selector model or equivalent planner
  inputs.
- Open existing run state read-only when resume planning needs it.
- Compute stage decisions through public planning APIs.
- Print ordered stage actions and reasons.
- If `--explain STAGE` is supplied, include the available explanation details
  for that stage.
- Do not execute stages.
- Do not mutate prior run state unless v0 already has an explicit non-execution
  plan persistence option. V1 should default to read-only planning.

### `loom run`

Command:

```text
loom run CONFIG
```

Options:

- `--overlay PATH`, repeatable.
- `--set KEY=VALUE`, repeatable.
- `--run-dir RUN_DIR`.
- `--run-id RUN_ID`.
- `--executor local`, default `local`.
- `--resume`.
- `--dry-run`.
- `--from-stage STAGE`.
- `--only-stage STAGE`, repeatable.
- `--force-stage STAGE`, repeatable.
- `--skip-stage STAGE`, repeatable.
- `--format text|json`, default `text`.

Behavior:

- Reject non-`local` executor values with a clear unsupported-executor error.
- For `--dry-run`, call the same planning path as `loom plan` and return the
  planning exit code.
- For execution, compose config, build runner inputs, call `PipelineRunner`, and
  format the run result.
- Return nonzero if the run fails.
- Do not write status files directly from CLI modules.
- Do not compute fingerprints, resume, graph binding, or artifact validation in
  CLI modules.

## Result And JSON Output

Text output should be concise and stable. JSON output should use plain data
objects shaped like this:

```json
{
  "schema_version": "loom.cli.plan.v2",
  "ok": true,
  "result": {}
}
```

Errors should use:

```json
{
  "schema_version": "loom.cli.error.v2",
  "ok": false,
  "error": {
    "type": "PipelineError",
    "message": "unknown stage",
    "path": "pipeline.stages[1].depends_on[0]",
    "context": {}
  }
}
```

Recommended result payloads:

- `ValidationCliResult`: config path, pipeline name if available, stage count,
  warnings if v0 exposes them.
- `PlanCliResult`: config path, run directory if selected, resume enabled,
  ordered stage actions, reasons, and optional stage explanation.
- `RunCliResult`: run ID, run directory, final run status, stage summaries,
  failure summary if present, and plan summary.

If v0 already exposes result dataclasses with plain-data conversion, CLI result
dataclasses may wrap or directly format those instead of creating a parallel
model.

## Error And Exit-Code Policy

Use small conventional exit codes:

```text
0    success
1    command completed but requested operation failed
2    CLI usage error or argument parse error
3    config validation or composition error
4    pipeline validation or planning error
5    run execution failed
6    run state or inspection error, reserved for v3
7    executor or scheduler error
130  interrupted by Ctrl-C
```

Known `LoomError` values should print concise messages by default. Unknown
exceptions should print a concise internal-error message and mention
`--traceback`. With `--traceback`, print the full traceback.

Warnings and errors go to stderr. Normal command output and machine JSON go to
stdout.

## Source Structure

V1 should complete the CLI package with this structure:

```text
src/loom/cli/
  __init__.py
  main.py
  errors.py
  options.py
  formatting.py
  results.py
  validate.py
  plan.py
  run.py
```

Deferred command modules such as `stage.py`, `sweep.py`, `status.py`, `logs.py`,
or `artifacts.py` should not be added unless an import-safe unsupported stub is
already present from v0 and needed for public import compatibility.

### `main.py`

Responsibilities:

- Build the top-level parser.
- Register v2 subcommands.
- Handle `--version`.
- Handle top-level `--traceback`.
- Dispatch to command handlers.
- Convert `argparse` exits into return codes for `main(argv)` tests.
- Catch `KeyboardInterrupt`, `LoomError`, and unknown exceptions.

Core functions:

```python
def build_parser() -> argparse.ArgumentParser: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

### `errors.py`

Responsibilities:

- Define CLI exit-code constants.
- Map known exceptions to exit codes.
- Render text and JSON error output.
- Preserve traceback behavior without moving subsystem error semantics into the
  CLI.

Core objects:

```python
class ExitCode(IntEnum): ...

def exit_code_for(error: BaseException) -> ExitCode: ...

def format_error(
    error: BaseException,
    *,
    traceback_enabled: bool,
    output_format: OutputFormat,
) -> str: ...
```

### `options.py`

Responsibilities:

- Parse command argument namespaces into small typed adapter objects.
- Normalize repeated flags into tuples or frozensets.
- Preserve raw `--set` strings for config override parsing by `loom.config`.
- Convert selector flags into the v0 selector model or planner input shape.

Core objects:

```python
@dataclass(frozen=True)
class ConfigCliOptions:
    config_path: Path
    overlays: tuple[Path, ...]
    overrides: tuple[str, ...]

@dataclass(frozen=True)
class SelectorCliOptions:
    from_stage: str | None
    only_stages: frozenset[str]
    force_stages: frozenset[str]
    skip_stages: frozenset[str]

@dataclass(frozen=True)
class RunCliOptions:
    run_dir: Path | None
    run_id: str | None
    executor: str
    resume: bool
    dry_run: bool

class OutputFormat(StrEnum): ...
```

### `formatting.py`

Responsibilities:

- Format validation, plan, and run results as stable text.
- Format JSON envelopes.
- Keep table/string formatting separate from command handlers.

Core functions:

```python
def format_validation_text(result: ValidationCliResult) -> str: ...

def format_plan_text(result: PlanCliResult) -> str: ...

def format_run_text(result: RunCliResult) -> str: ...

def format_json_envelope(
    *,
    schema_version: str,
    ok: bool,
    payload: Mapping[str, object],
) -> str: ...
```

### `results.py`

Responsibilities:

- Define CLI-facing result wrappers only when existing v0 result types are not
  directly suitable for presentation.
- Provide plain-data conversion for JSON output.

Core objects:

```python
@dataclass(frozen=True)
class ValidationCliResult: ...

@dataclass(frozen=True)
class PlanCliResult: ...

@dataclass(frozen=True)
class RunCliResult: ...
```

### Command Modules

Each command module owns only command registration and orchestration:

```python
def register_subparser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None: ...

def handle(args: argparse.Namespace) -> int: ...
```

Command modules may import public config, pipeline, planning, execution, and
store APIs. They must not import downstream project packages, optional
executor-specific modules, plugin discovery, or private run-layout constants
when public APIs exist.

## Integration With V0

V2 should integrate with v0 and v1 by using public API seams:

- Config: pass `CONFIG`, overlays, and raw override strings to
  `compose_config`; include, replacement, copy, and source snapshot behavior is
  handled by the config package, not CLI modules.
- Pipeline validation: use public pipeline spec parsing and graph validation
  helpers. If v0 lacks a single validation facade, add one in `loom.pipeline`.
- Selectors: convert CLI stage selector flags into the v0 selector model:
  `from_stage`, `only_stages`, `force_stages`, and `skip_stages`.
- Planning: call the v0 planner to compute stage actions, resume decisions,
  invalidation, and explanations.
- Run store: let v0 planner/runner open or create run state. CLI modules should
  not hard-code run layout paths.
- Execution: call `PipelineRunner`; do not invoke stages directly.
- Errors: catch shared `LoomError` roots and use structured context where
  available.
- Serialization: use v0 plain-data helpers if available for JSON output.

V2 may expose small public helper functions in owning packages if that improves
the CLI without coupling it to internals. Examples:

- `loom.pipeline.validate_pipeline_config(resolved: Mapping[str, object])`
- `loom.pipeline.planning.plan_pipeline(...)`
- `loom.pipeline.execution.run_pipeline(...)`

Those helpers should be added only if the corresponding v0 classes already
exist but are awkward to use directly from CLI code.

## Future Compatibility

V2 decisions must preserve the later roadmap:

- V3 diagnostics should reuse CLI error formatting, JSON envelopes, parser
  conventions, and output format handling for `preflight`, `status`, `logs`,
  and `artifacts`.
- V4 runtime options should be able to replace CLI adapter-to-v0 conversions
  with adapter-to-`RunOptions` conversions without changing user-facing flag
  names.
- V5 stage-worker support should add `loom stage run` as a new command group
  using the same parser and exit-code policy.
- V6 and v7 SLURM support should add executor-specific commands and output
  through executor APIs, not by parsing scheduler behavior in CLI modules.
- V8 and v9 run catalog and bundle commands should reuse JSON envelope and
  formatting helpers.
- V10 sweeps should reuse config options and selector conventions.
- V11 plugin discovery must remain explicit. The v2 CLI must not load plugins
  during `loom --help` or top-level import.
- V12 and v13 remote stores must remain optional adapters. V2 should not bake
  local-path assumptions into formatting except when reporting v0 local-run
  results supplied by stores.
- V14 and v15 container executors should integrate through executor selection
  and later runtime options, not through special-case v2 command logic.
- V16 and v17 reliability and cleanup commands should build on shared error,
  event, and deletion-intent policies rather than ad hoc CLI behavior.

## Conflicts And Tradeoffs

- Immediate CLI usefulness vs future runtime options: v2 accepts familiar flags
  but keeps their canonical semantics in v0 planner/runner inputs until v4
  introduces typed runtime models.
- Human readability vs automation stability: v2 supports compact text output
  and versioned JSON output rather than rich terminal rendering.
- Thin CLI vs convenient helper APIs: if command modules need internal details,
  add small public facades in owning packages instead of duplicating logic in
  `loom.cli`.
- Early executor flag vs unsupported backends: v2 accepts `--executor local`
  and rejects other executor names so scripts have a future-compatible option
  shape without pretending subprocess/SLURM exist.

## Technical Debt Ledger

- CLI option adapter dataclasses are accepted as a bridge until v4 runtime
  option models exist. Revisit in v4 and convert them to runtime model
  constructors.
- JSON envelopes are v2 output contracts but not a full diagnostics schema.
  Revisit in v3 when preflight/status/log/artifact inspection adds richer
  machine-readable outputs.
- Unsupported executor handling is intentionally minimal. Revisit in v4/v5 when
  executor registries and stage-worker contracts land.
- `argparse` is sufficient for v2. Revisit only if the command tree becomes
  large enough to justify a CLI framework dependency.

## Phased Implementation

### Phase 1 - CLI Foundation

Status: pending
Branch: `codex/add-cli-foundation`
PR: pending

Goal:

- Add the console script, top-level parser, version/help behavior, exit codes,
  traceback handling, and import-boundary guardrails.

Scope:

- Add or complete `src/loom/cli/main.py`, `src/loom/cli/errors.py`, and shared
  parser registration.
- Add `[project.scripts]` entry for `loom`.
- Keep `import loom` free of `loom.cli`.

Acceptance criteria:

- `loom --help` and `loom --version` work.
- `main(argv)` returns integer exit codes.
- Usage errors return 2.
- `KeyboardInterrupt` returns 130.
- Known and unknown errors are formatted according to `--traceback`.
- Import-boundary tests prove top-level import does not load CLI or project
  code.

### Phase 2 - Shared Options, Formatting, And Validate

Status: pending
Branch: `codex/add-cli-validate`
PR: pending

Goal:

- Add shared CLI option adapters, result formatting, JSON envelopes, and
  `loom validate`.

Scope:

- Add `options.py`, `formatting.py`, `results.py`, and `validate.py`.
- Wire validate to public config and pipeline validation APIs.
- Add parser and command tests for config options and validation output.

Acceptance criteria:

- Repeated `--overlay` and `--set` values are preserved in order.
- Validate succeeds for a synthetic valid v0 pipeline config.
- Validate fails with config or pipeline exit codes for invalid inputs.
- Text and JSON outputs are stable and tested.
- Validate does not execute stages or write run state.

### Phase 3 - Plan Command

Status: pending
Branch: `codex/add-cli-plan`
PR: pending

Goal:

- Add `loom plan` over v0 planning, selector, and resume APIs.

Scope:

- Add `plan.py`.
- Convert selector flags into v0 selector inputs.
- Format ordered stage actions, reasons, and optional explanation output.
- Support JSON output.

Acceptance criteria:

- Planning a fresh synthetic pipeline reports runnable stages in deterministic
  order.
- Resume planning against an existing run directory reports `REUSE` or rerun
  decisions from v0 planner output.
- Selector flags affect plan decisions through v0 planner APIs.
- `--explain STAGE` reports available explanation details.
- Plan command does not execute stages and does not mutate run state.

### Phase 4 - Run Command

Status: pending
Branch: `codex/add-cli-run`
PR: pending

Goal:

- Add `loom run` for v0 local execution.

Scope:

- Add `run.py`.
- Wire config, selectors, run directory, run ID, resume, and local executor
  selection into `PipelineRunner`.
- Implement `--dry-run` by delegating to the plan path.
- Reject unsupported executors clearly.

Acceptance criteria:

- A synthetic v0 pipeline can run from the command line.
- The command prints run directory, final run status, and stage summary.
- Failed runs return execution failure exit code and concise failure output.
- `--dry-run` produces a plan and does not execute stages.
- Non-local executor names return executor error without optional backend import.

### Phase 5 - Hardening, Docs, And E2E Coverage

Status: pending
Branch: `codex/harden-cli-core`
PR: pending

Goal:

- Harden v2 behavior, document validate/plan/run, and add end-to-end coverage.

Scope:

- Update README and CLI docs for v2 commands only.
- Add stable examples for validate, plan, run, resume, selectors, text output,
  and JSON output.
- Add e2e tests through `main(argv)` or the console entry point.
- Confirm import boundaries after all command modules exist.

Acceptance criteria:

- Docs describe only v2-supported commands and clearly defer later commands.
- E2E tests cover validate, plan, run, failed run, dry-run, and JSON output.
- `make validate-pr` passes.
- `make test-summary` records suite-level evidence.

## Overall Test Plan

Package tests:

- `import loom` remains cheap and does not import `loom.cli`.
- `import loom.cli` does not load project code, plugin discovery, optional
  backends, or heavy executor modules.
- Console script metadata exists after build.

Unit tests:

- Parser construction, help, version, subcommand registration, and invalid
  commands.
- Config, selector, run, executor, and output-format option adapters.
- Exit-code mapping.
- Text and JSON formatting for validation, plan, run, and known errors.

Command tests:

- Validate calls config and pipeline validation APIs.
- Plan calls planner APIs and never calls executor or runner execution methods.
- Run calls `PipelineRunner` and does not write run state directly.
- `--dry-run` uses planning behavior.
- Unsupported executor handling is clear and import-safe.

End-to-end tests:

- Validate a synthetic local pipeline config.
- Plan a synthetic local pipeline config.
- Run a synthetic local pipeline config with the local executor.
- Resume or plan against an existing run directory when v0 fixtures support it.
- Return nonzero and print useful output for failed synthetic stages.
- Produce parseable JSON for validate, plan, and run.

Validation gates:

```sh
make validate-pr
make test-summary
```

## Plan Quality Gate

Status: pending

Before implementation starts, review this v2 plan for:

- maintainability;
- extensibility;
- future roadmap compatibility;
- conflicting design choices;
- accepted technical debt;
- test strategy; and
- reviewability as one coherent v2 project plan.

If blocking findings remain after the bounded review/refinement process, mark
the plan or first phase `blocked` rather than starting implementation.

## Assumptions And Defaults

- V2 begins after v0 local runtime APIs and v1 config composition APIs are
  available.
- Python remains `>=3.12`.
- `argparse` is the only CLI framework in v2.
- No new runtime dependencies are required for v2.
- `--format text` is the default for all v2 commands.
- JSON output is newline-terminated UTF-8 written to stdout.
- `--set` values stay raw until passed to the config override parser.
- Repeated stage selector flags are normalized deterministically.
- `local` is the only supported executor in v2.
- Non-local executor names fail explicitly and are not silently ignored.
- CLI modules may import public v0 APIs, but v0 internals may not import CLI
  modules.
- Later roadmap commands must extend the CLI package without changing the v2
  command contracts unless a separate compatibility plan approves it.

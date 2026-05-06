# Implementation Plan v2

## Goal

Implement `loom` v2 as the first functional command-line layer over the v0
local runtime kernel and v1 config composition.

The v2 target is a thin, domain-neutral `argparse` CLI that lets users validate,
plan, and run v0 pipelines from scripts and terminals without duplicating config,
pipeline, planning, store, resume, or execution logic in CLI modules.

V2 also performs the breaking migration from `run_id` as the public run
identifier to `run_uri` as the logical run address. This migration is planned as
an owning-runtime/store change before command behavior is layered on top.

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
  modules, plugins, optional executor backends, stores, or heavy operational
  adapters.
- `run_uri` is the public/protocol/persisted run identifier. User-facing v2
  APIs, CLI output, run records, status records, event records, locks,
  provenance records, execution plans, and `ArtifactAddress` use `run_uri`
  instead of `run_id`.
- Local v2 run URIs support only strict `file://` forms. Relative accepted forms
  resolve against the current working directory and are persisted/displayed as
  absolute `file:///...` URIs.
- `loom validate CONFIG` composes config, performs static validation by default,
  optionally constructs all `_target_` blocks with `--check-targets`, and
  reports success, warnings, or structured errors without writing run state.
- `loom plan CONFIG` shows ordered stage decisions and reasons without executing
  stages, allocating a default run URI, or mutating run state.
- `loom run CONFIG` executes through the v0 local runner and prints a concise
  summary. If no `--run-uri` is supplied, the store/runtime facade allocates a
  collision-free timestamped local run URI under its default root.
- Commands intended for automation support JSON output from structured result
  objects. JSON envelopes have consistent top-level `warnings`.
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
- No remote run URI support in v2. Non-local schemes such as `s3://` must fail
  loudly.
- No compatibility path for old v0 run directories or persisted documents that
  only contain `run_id`. V2 is a hard schema/API swap to `run_uri`.
- No `--run-dir`, `--run-id`, or `--strict` CLI options in v2.
- No new config composition, pipeline validation, planning, resume, or runner
  algorithms inside `loom.cli`.
- No new heavyweight runtime dependency such as Click, Typer, Rich, or Pydantic
  beyond whatever earlier versions already introduced.
- No domain-specific commands, schemas, stages, codecs, reports, datasets, or
  project import assumptions.

## Prerequisites

V2 is blocked until v0/v1 public Python APIs or equivalent stable facades are
available. A v2 phase may add a missing facade only in the package that owns the
behavior; it must not fill the gap with CLI-local business logic.

API readiness checklist:

- `loom.config.compose_config`, including v1 include, replacement, copy, and
  source snapshot behavior as part of composition.
- Config-owned target instantiation APIs capable of constructing all `_target_`
  blocks for `loom validate --check-targets`.
- Pipeline spec parsing and validation from a resolved config mapping, exposed
  through `loom.pipeline` rather than `loom.cli`.
- Stage selector construction or normalized selector inputs exposed by
  `loom.pipeline` or `loom.pipeline.planning`.
- Execution planning and strict same-run-URI resume decisions exposed by
  `loom.pipeline.planning`, including action reasons and optional stage
  explanations.
- Run URI parsing, validation, allocation, create/open, and read-only planning
  facades exposed by `loom.pipeline.stores`, `loom.pipeline.execution`, or the
  owning package that controls run-store interaction.
- `PipelineRunner`, `RunRequest` or an equivalent public run facade, and local
  executor wiring exposed by `loom.pipeline.execution` and
  `loom.pipeline.executors`.
- Structured validation, plan, and run result models, or plain-data conversion
  helpers suitable for CLI JSON output.
- Shared `LoomError` roots and broad subsystem errors, with `to_dict()` or an
  equivalent structured error helper when machine output is requested.

If an implementation phase discovers that CLI code would otherwise parse
pipeline config, inspect run-layout paths, compute selectors, compute resume
decisions, construct fingerprints, bind artifacts, normalize run URIs, allocate
default run locations, or build runner internals manually, that phase must add
the minimal public facade in the owning package and use it from the CLI.
Examples:

- pipeline validation helpers belong in `loom.pipeline`, not `loom.cli`;
- planning helpers belong in `loom.pipeline.planning`, not `loom.cli`;
- run URI and local path helpers belong in `loom.pipeline.stores` or the
  execution facade that owns store interaction, not `loom.cli`;
- runner request helpers belong in `loom.pipeline.execution`, not `loom.cli`.

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
- `run_uri` values accepted by v2 must use explicit local `file://` syntax:
  `file:///absolute/run`, `file://./relative/run`, or
  `file://../relative/run`.
- V2 must reject plain paths, `file://localhost/...`, any other `file://`
  authority, query strings, fragments, and non-local URI schemes.
- Relative run URIs resolve against the current working directory before use.
  Persisted records and CLI output use the resolved absolute `file:///...` URI.
- `run_uri` is excluded from semantic stage fingerprints by default. Hidden
  stochastic behavior must be made explicit through config, seeds, runtime
  inputs, or stage-authored provenance rather than ambient run identity.
- Resume behavior is strict in v2. Missing or stale reusable stage state may
  produce `RUN` decisions when safe, but corrupt, ambiguous, unsupported, or
  unsafe prior run state must fail loudly.
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
- Run addressing is owned by runtime/store APIs. The CLI never derives local
  roots, run path components, or default run locations.
- Human output should be concise and stable.
- Machine output should be explicit, versioned, and structured.
- Parser options should use names that can later map cleanly to v4 runtime
  option objects, even though v2 does not implement those objects.
- Future commands should reuse common parser, error, option, warning, and
  formatting helpers rather than inventing a separate CLI style per feature.

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
- V2 performs a hard migration from public/protocol/persisted `run_id` fields to
  `run_uri`. Old v0 run directories are not supported after the migration.
- `ArtifactAddress` migrates from `run_id + artifact_id` to
  `run_uri + artifact_id`. `ArtifactRef` does not gain `run_uri`; it remains
  physical artifact metadata with `artifact_id`, `uri`, type, codec, checksums,
  fingerprint, producer, and metadata.
- `--run-uri RUN_URI` is the only run-addressing CLI option. It replaces
  `--run-dir` and `--run-id`.
- `loom plan` is read-only. It does not allocate default run URIs, create run
  directories, acquire locks, persist plans, or mutate prior run state. When
  `--resume` is supplied, `--run-uri` is required and the selected run state is
  opened read-only.
- `loom run` allocates a store-owned default local run URI when `--run-uri` is
  omitted. The local store may define the default root as cwd-relative `./runs`,
  but the CLI must only use the facade result.
- `--executor` is accepted by `loom run` to establish the future shape, but v2
  supports only `local`. Unsupported executors fail clearly without importing
  optional backends. The parser should accept a string and the run handler
  should reject non-`local` values so unsupported executors return the executor
  exit code rather than an argparse usage error.
- `--dry-run` on `loom run` delegates to the same planning path as
  `loom plan`. JSON dry-run output uses the plan result schema, not a run result
  schema, because no run occurred.
- `loom validate` is static by default. `--check-targets` is the explicit
  consent boundary for importing and constructing all `_target_` blocks, then
  discarding the constructed objects. Static validation runs before target
  checks.
- `--format text|json` is the v2 output format surface for validate, plan, and
  run. Text output is compact; successful validate output is one line unless
  warnings exist. `loom run --format json` emits final-result JSON only, not
  streaming progress.
- JSON result and error envelopes include a CLI schema version and top-level
  `warnings`. These schemas are automation-facing output contracts, not
  persisted run-store schemas.
- If a command parses successfully and `--format json` is known, JSON error
  envelopes go to stdout and exit nonzero. Argparse usage errors remain text on
  stderr because the command and format may not be known.
- `--traceback` does not change JSON envelope shape. When requested, structured
  traceback/debug details may be included under `error.details`, and full
  traceback text may be written to stderr.
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

Top-level help and subcommand help must remain import-light. Parser registration
must not compose configs, import project target modules, load plugins, inspect
stores, instantiate executors, or contact optional backends.

### `loom validate`

Command:

```text
loom validate CONFIG
```

Options:

- `--overlay PATH`, repeatable.
- `--set KEY=VALUE`, repeatable.
- `--check-targets`.
- `--format text|json`, default `text`.

Behavior:

- Compose the config through `loom.config`.
- Build and validate the pipeline through public `loom.pipeline` APIs.
- Default validation is static: no target construction and no stage execution.
- If `--check-targets` is supplied, run static validation first, then use
  config-owned APIs to import and construct every `_target_` block, including
  target blocks outside the pipeline. Constructed objects are discarded.
- `--check-targets` may run trusted project constructors. It must be documented
  in help/docs, and text output should warn on stderr before target checks.
- Validate protocol conformance only where an owning package already exposes
  the check, such as pipeline stage target protocol checks. Arbitrary `_target_`
  blocks only need construction success.
- Print compact success with the config path and stage count.
- Include warnings only when surfaced by underlying APIs or by
  `--check-targets`; do not invent silent warning behavior.
- On failure, return the matching config or pipeline exit code.
- Do not execute stages.
- Do not write run state or validation reports.

### `loom plan`

Command:

```text
loom plan CONFIG
```

Options:

- `--overlay PATH`, repeatable.
- `--set KEY=VALUE`, repeatable.
- `--run-uri RUN_URI`.
- `--resume`.
- `--from-stage STAGE`.
- `--only-stage STAGE`, repeatable.
- `--force-stage STAGE`, repeatable.
- `--skip-stage STAGE`, repeatable.
- `--explain STAGE`.
- `--format text|json`, default `text`.

Behavior:

- Compose config and build the pipeline spec through public APIs.
- Convert selector flags into the v0 selector model or equivalent planner
  inputs. Graph-dependent selector validation belongs to planner APIs, not
  CLI-local logic.
- Validate `--run-uri` as an explicit local v2 run URI and pass it through
  owning planner/store facades. The CLI must not split paths, derive roots, or
  inspect private run layouts.
- If `--run-uri` is omitted, produce a fresh hypothetical plan with no run URI
  allocation and no run state reads.
- If `--resume` is supplied, require `--run-uri`, open the existing valid run
  state read-only, and compute strict resume decisions.
- If `--run-uri` is supplied without `--resume`, allow planning for a
  non-existing target URI without creating it, but fail if the run URI already
  exists. A non-resume operation must not silently target existing state.
- If `--resume` points at a missing or invalid run URI, fail clearly. Missing
  prior status for an individual stage inside a valid run may become a planner
  `RUN` decision with a reason such as `NO_PRIOR_STATUS`.
- Compute stage decisions through public planning APIs.
- Print ordered stage actions and reasons.
- If `--explain STAGE` is supplied, include the available explanation details
  for that stage.
- Do not execute stages.
- Do not create run directories, allocate default run URIs, acquire locks,
  persist `plan.json`, or mutate prior run state.

### `loom run`

Command:

```text
loom run CONFIG
```

Options:

- `--overlay PATH`, repeatable.
- `--set KEY=VALUE`, repeatable.
- `--run-uri RUN_URI`.
- `--executor EXECUTOR`, default `local`.
- `--resume`.
- `--dry-run`.
- `--from-stage STAGE`.
- `--only-stage STAGE`, repeatable.
- `--force-stage STAGE`, repeatable.
- `--skip-stage STAGE`, repeatable.
- `--format text|json`, default `text`.

Behavior:

- Reject non-`local` executor values with a clear unsupported-executor error.
- Validate an explicit `--run-uri` through owning run URI APIs. If omitted,
  request a default local run URI from the store/runtime facade.
- For non-resume execution, fail if the target run URI already exists.
- For `--resume`, require the target run URI to exist and be valid, then run
  strict resume planning.
- For `--dry-run`, call the same planning path as `loom plan`, return the
  planning exit code, and do not allocate a default run URI when `--run-uri` is
  omitted. JSON dry-run output is plan JSON.
- For execution, compose config, build runner inputs, call `PipelineRunner` or
  an equivalent public run facade, and format the run result.
- Return nonzero if the run fails.
- Text output should print the resolved absolute run URI early enough for users
  to find the run directory.
- JSON output should emit one final result envelope with resolved `run_uri`,
  final run status, stage summaries, failure summary if present, and plan
  summary.
- Do not write status files directly from CLI modules.
- Do not compute fingerprints, resume, graph binding, artifact validation, run
  locks, run URI allocation, or run layout paths in CLI modules.

## Result And JSON Output

Text output should be concise and stable. Successful validate output should be
one line by default:

```text
OK validate config.yaml: 4 stages
```

Warnings and errors go to stderr in text mode. Normal command output and
machine JSON go to stdout.

JSON output should use plain data envelopes shaped like this:

```json
{
  "schema_version": "loom.cli.plan.v2",
  "ok": true,
  "warnings": [],
  "result": {}
}
```

Errors should use:

```json
{
  "schema_version": "loom.cli.error.v2",
  "ok": false,
  "warnings": [],
  "error": {
    "type": "PipelineError",
    "message": "unknown stage",
    "code": "pipeline.unknown_stage",
    "context": {
      "config_path": "pipeline.stages[1].depends_on[0]"
    },
    "hint": null,
    "details": {}
  }
}
```

When a caught `LoomError` exposes `to_dict()` or an equivalent structured
helper, JSON error envelopes should use that payload. The CLI may normalize the
payload to plain data, but it should not parse human error strings or invent a
parallel error schema.

Recommended result payloads:

- `ValidationCliResult`: config path, pipeline name if available, stage count,
  check-targets enabled flag, target count if exposed, and warnings.
- `PlanCliResult`: config path, resolved run URI when supplied, resume enabled,
  ordered stage actions, reasons, selectors, plan summary, pending inputs,
  reusable outputs when exposed, and optional stage explanation. This is a
  CLI-specific view built from structured planner objects, not the raw internal
  `ExecutionPlan` schema.
- `RunCliResult`: resolved run URI, final run status, stage summaries, failure
  summary if present, and plan summary.

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

Argparse usage errors remain text on stderr. When a command parses successfully
and `--format json` is known, JSON error envelopes go to stdout and the command
returns the mapped nonzero exit code.

## Source Structure

V2 should complete the CLI package with this structure:

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
- Preserve `--run-uri` as a raw explicit URI string until the owning run URI
  facade validates and resolves it.
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
class ValidateCliOptions:
    check_targets: bool

@dataclass(frozen=True)
class PlanCliOptions:
    run_uri: str | None
    resume: bool
    explain_stage: str | None

@dataclass(frozen=True)
class RunCliOptions:
    run_uri: str | None
    executor: str
    resume: bool
    dry_run: bool

class OutputFormat(StrEnum): ...  # text, json
```

### `formatting.py`

Responsibilities:

- Format validation, plan, and run results as stable text.
- Format JSON envelopes with top-level `warnings`.
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
    warnings: Sequence[Mapping[str, object]],
    payload_name: str,
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

## Integration With V0 And V1

V2 should integrate with v0 and v1 by using public API seams:

- Config: pass `CONFIG`, overlays, and raw override strings to
  `compose_config`; include, replacement, copy, and source snapshot behavior is
  handled by the config package, not CLI modules.
- Target checks: `loom validate --check-targets` uses config-owned
  instantiation APIs for all `_target_` blocks. The CLI must not implement
  target import or constructor policy itself.
- Pipeline validation: use public pipeline spec parsing and graph validation
  helpers. If v0 lacks a single validation facade from resolved config, add one
  in `loom.pipeline`.
- Selectors: convert CLI stage selector flags into the v0 selector model:
  `from_stage`, `only_stages`, `force_stages`, and `skip_stages`. Unknown stage
  and graph-dependent conflict validation belongs to planner APIs.
- Planning: call the v0 planner to compute stage actions, resume decisions,
  invalidation, and explanations. Resume is strict in v2; no CLI `--strict`
  toggle exists.
- Run URI/store: let owning store/execution facades validate, resolve, allocate,
  create, open, and inspect local `file://` run URIs. CLI modules should not
  hard-code run layout paths or invent run URI normalization.
- Execution: build `RunRequest` through public execution APIs where possible and
  call `PipelineRunner`; do not invoke stages directly.
- Errors: catch shared `LoomError` roots and use structured context where
  available.
- Serialization: use v0 plain-data helpers if available for JSON output.

V2 may expose small public helper functions in owning packages if that improves
the CLI without coupling it to internals. Examples:

- `loom.pipeline.validate_pipeline_config(resolved: Mapping[str, object])`
- `loom.pipeline.planning.plan_pipeline(...)`
- `loom.pipeline.stores.resolve_run_uri(...)`
- `loom.pipeline.execution.run_pipeline(...)`

Those helpers should be added only if the corresponding v0 classes already
exist but are awkward to use directly from CLI code.

## Future Compatibility

V2 decisions must preserve the later roadmap:

- V3 diagnostics should reuse CLI error formatting, JSON envelopes, parser
  conventions, output format handling, warning formatting, and `run_uri`
  parsing for `preflight`, `status`, `logs`, and `artifacts`.
- V4 runtime options should be able to replace CLI adapter-to-v0 conversions
  with adapter-to-`RunOptions` conversions without changing user-facing flag
  names such as `--run-uri`.
- V5 stage-worker support should add `loom stage run` as a new command group
  using the same parser and exit-code policy.
- V6 and v7 SLURM support should add executor-specific commands and output
  through executor APIs, not by parsing scheduler behavior in CLI modules.
- V8 and v9 run catalog and bundle commands should use `run_uri` and
  `ArtifactAddress(run_uri, artifact_id)` for cross-run identity.
- V10 sweeps should reuse config options and selector conventions.
- V11 plugin discovery must remain explicit. The v2 CLI must not load plugins
  during `loom --help` or top-level import.
- V12 and v13 remote stores may extend run URI support beyond local `file://`
  through store-owned adapters. V2 deliberately rejects those schemes.
- V14 and v15 container executors should integrate through executor selection
  and later runtime options, not through special-case v2 command logic.
- V16 and v17 reliability and cleanup commands should build on shared error,
  event, and deletion-intent policies rather than ad hoc CLI behavior.

## Conflicts And Tradeoffs

- Immediate CLI usefulness vs breaking run identity migration: v2 absorbs the
  `run_uri` hard swap up front so CLI contracts do not expose soon-obsolete
  `run_id`/`run_dir` flags.
- Local convenience vs future remote stores: v2 supports only strict local
  `file://` run URIs, but the public contract is URI-shaped so later store
  adapters can extend it.
- Run portability vs reuse identity: `run_uri` is excluded from semantic stage
  fingerprints. This keeps fingerprints focused on semantic inputs, but hidden
  stochastic behavior remains project responsibility through explicit seeds,
  config, runtime inputs, or provenance.
- Human readability vs automation stability: v2 supports compact text output
  and versioned JSON output rather than rich terminal rendering.
- Thin CLI vs convenient helper APIs: if command modules need internal details,
  add small public facades in owning packages instead of duplicating logic in
  `loom.cli`.
- Static validation safety vs target-check completeness: default validate is
  safe and static; `--check-targets` is the consent boundary for importing and
  constructing trusted project code.
- Early executor flag vs unsupported backends: v2 accepts `--executor EXECUTOR`
  with `local` as the only supported value and rejects other executor names so
  scripts have a future-compatible option shape without pretending
  subprocess/SLURM exist.

## Technical Debt Ledger

- V2 hard-swaps persisted run identity to `run_uri` and intentionally does not
  support old v0 run documents. Revisit only if a later migration plan requires
  importing historical v0 runs.
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

## Maintainability Assessment

The plan keeps CLI maintainability centered on boundaries: CLI code parses,
formats, and dispatches, while run addressing, planning, resume, target
instantiation, execution, and store mutations stay in owning packages. Splitting
the run URI migration, shared CLI infrastructure, validate, plan, run, and
hardening phases keeps the most disruptive schema/API work separate from command
presentation.

## Extensibility Assessment

The v2 CLI surface intentionally uses future-compatible names (`--run-uri`,
`--executor`, selector flags, `--format`) without implementing later runtime
option models, remote stores, scheduler adapters, diagnostics, or catalogs.
`run_uri` and `ArtifactAddress(run_uri, artifact_id)` are the main extension
points for v3 inspection, v8 catalogs, v9 bundles, and v12/v13 remote stores.

## Phased Implementation

### Phase 1 - Run URI Runtime Addressing

Status: merged
Branch: `codex/add-run-uri-addressing`
PR: https://github.com/samcantrill/loom/pull/59

Goal:

- Replace public/protocol/persisted `run_id` identity with `run_uri` before the
  CLI exposes run-addressing behavior.

Scope:

- Add owning-package run URI validation/resolution helpers for v2 local
  `file://` run URIs.
- Accept only `file:///absolute/run`, `file://./relative/run`, and
  `file://../relative/run`; reject plain paths, authorities including
  `localhost`, query strings, fragments, and non-local schemes.
- Resolve relative run URIs against cwd and persist/display absolute
  `file:///...` URIs.
- Replace public/protocol/persisted `run_id` fields with `run_uri` in runner,
  planner, run-store protocols, local store persisted wrappers, statuses,
  events, locks, provenance records, execution plans, and result models.
- Migrate `ArtifactAddress` to `run_uri + artifact_id` and keep `ArtifactRef`
  unchanged.
- Add store/runtime facade behavior for default local run URI allocation under
  the store-owned default root with collision handling.
- Exclude `run_uri` from semantic stage fingerprints.
- Update owning feature docs that would otherwise contradict v2 run URI
  behavior.

Out of scope:

- Backward compatibility with old v0 `run_id` run directories.
- Remote run stores or remote run URI schemes.
- CLI command implementation beyond any small tests needed to prove public
  helpers are usable.
- Cross-run cache reuse or portable run migration.

Acceptance criteria:

- Public/protocol/persisted run identity uses `run_uri`, not `run_id`.
- V2 local run URI parsing accepts and rejects the documented forms.
- Relative run URIs persist and serialize as resolved absolute `file:///...`
  URIs.
- Local run creation/open/read/write behavior uses the resolved target
  directory exactly.
- Default local run URI allocation is store-owned and collision-safe.
- `ArtifactAddress` round-trips with `run_uri` and `artifact_id`.
- `ArtifactRef` serialization remains unchanged and does not include
  `run_uri`.
- Stage fingerprints do not include ambient `run_uri`.

Test expectations:

- Package: public imports remain cheap and expose migrated `ArtifactAddress`.
- Unit: run URI parser/resolver, rejected URI forms, local store create/open,
  default allocation collision handling, statuses/events/locks/provenance
  serialization, `ArtifactAddress`, and fingerprint exclusion.
- Contract: run-store protocol methods use `run_uri`; artifact index and stage
  state contracts round-trip with `run_uri`.
- Integration: local planning/resume and local execution still work through
  resolved absolute run URIs.
- E2E: not required until command phases, unless existing local-run e2e tests
  need migration for coverage continuity.
- Opt-in: none.

Design impact:

- This is a breaking schema/API migration and the largest v2 compatibility
  decision.

Future compatibility:

- Establishes the address model needed by diagnostics, catalogs, bundles,
  remote stores, and future executor adapters.

Alternatives rejected:

- Compatibility bridge writing both `run_id` and `run_uri`: rejected to avoid
  carrying two public identities.
- CLI-only `--run-dir`/`--run-id`: rejected because it would bake local layout
  into the v2 CLI.
- Adding `run_uri` to `ArtifactRef`: rejected to avoid duplicating physical
  artifact location with run-scoped identity.

Debt introduced:

- Old v0 run directories are unsupported. Revisit only if a later import/migrate
  command is explicitly planned.

Reviewability:

- Review as one focused runtime/store schema migration with broad tests before
  command behavior begins.

Notes:

- PR feature focus: `CLI Core`
- Intended PR title: `CLI Core - Phase 1: Run URI Runtime Addressing`

Completion summary:

- PR opened and merged into `develop`: https://github.com/samcantrill/loom/pull/59
- Merge commit: `4b775510835a0725c59065cd2ced6916ca220981`.
- Implementation commits migrate public/protocol/persisted run identity to
  `run_uri`, add strict local `file://` run URI helpers, preserve run-agnostic
  `ArtifactRef`, and update the owning docs/tests.
- Validation passed with `make validate-pr`, `make test-summary`, and GitHub CI.

### Phase 2 - CLI Foundation And Shared Infrastructure

Status: pr_open
Branch: `codex/add-cli-foundation`
PR: https://github.com/samcantrill/loom/pull/60

Goal:

- Add the console script, top-level parser, version/help behavior, exit codes,
  traceback handling, shared output formatting, JSON envelopes, and
  import-boundary guardrails.

Scope:

- Add or complete `src/loom/cli/main.py`, `src/loom/cli/errors.py`,
  `src/loom/cli/options.py`, `src/loom/cli/formatting.py`, and
  `src/loom/cli/results.py`.
- Add `[project.scripts]` entry for `loom`.
- Define `OutputFormat`, warning payload shape, JSON envelope helpers, and JSON
  error rendering.
- Register v2 command parsers without importing project targets, plugins,
  stores, or optional backends at help time.
- Keep `import loom` free of `loom.cli`.

Out of scope:

- Functional validate/plan/run command behavior.
- Product runtime/store changes beyond depending on Phase 1 surfaces.
- Rich terminal rendering or shell completion.

Acceptance criteria:

- `loom --help` and `loom --version` work.
- `main(argv)` returns integer exit codes.
- Usage errors return 2 as text on stderr.
- `KeyboardInterrupt` returns 130.
- Known and unknown errors are formatted according to `--traceback`.
- JSON envelopes include `schema_version`, `ok`, top-level `warnings`, and
  either `result` or `error`.
- JSON errors preserve structured error fields when available after command
  parsing succeeds.
- Import-boundary tests prove top-level import/help does not load CLI internals,
  project code, stores, plugins, or optional backends unexpectedly.

Test expectations:

- Package: import boundary and console script metadata.
- Unit: parser construction, version/help, argparse exit conversion, output
  format parsing, warnings, JSON envelopes, JSON/text error formatting,
  traceback details, exit-code mapping.
- Contract: none required unless shared error payload helpers expose a contract.
- Integration: none required.
- E2E: command help through `main(argv)` or console entry point.
- Opt-in: none.

Design impact:

- Establishes CLI conventions reused by all later command and diagnostics
  phases.

Future compatibility:

- V3+ commands should reuse the same parser, warning, error, and JSON envelope
  helpers.

Alternatives rejected:

- Delaying JSON error rendering until validate: rejected because all commands
  need one policy.

Debt introduced:

- CLI option adapters are temporary until v4 runtime option models exist.

Reviewability:

- Review as command-neutral CLI scaffolding and output policy only.

Notes:

- PR feature focus: `CLI Core`
- Intended PR title: `CLI Core - Phase 2: Foundation and Shared Output`

Completion summary:

- PR opened against `develop`: https://github.com/samcantrill/loom/pull/60
- Implementation adds the import-light CLI foundation and shared output/error
  helpers without implementing command behavior early.
- Local validation passed with `make validate-pr` and `make test-summary`.

### Phase 3 - Validate Command

Status: pending
Branch: `codex/add-cli-validate`
PR: pending

Goal:

- Add `loom validate` with static validation by default and explicit target
  construction under `--check-targets`.

Scope:

- Add `src/loom/cli/validate.py`.
- Wire validate to public config and pipeline validation APIs.
- Add a minimal `loom.pipeline` validation facade if validate would otherwise
  need to parse resolved pipeline config or validate DAG details directly.
- Add config-owned target-check facade if the CLI would otherwise import or
  instantiate targets itself.
- Run static validation before target construction.
- Format compact text and JSON validation results with top-level warnings.

Out of scope:

- Stage execution, run URI allocation, run-state writes, validation report
  files, or preflight checks.
- Interactive confirmation for target checks. `--check-targets` is the consent
  boundary.

Acceptance criteria:

- Repeated `--overlay` and `--set` values are preserved in order.
- Validate succeeds for a synthetic valid v0/v1 pipeline config.
- Validate fails with config or pipeline exit codes for invalid inputs.
- Default validate does not import/construct `_target_` objects beyond what
  static APIs require.
- `--check-targets` constructs all `_target_` blocks after static validation and
  warns that trusted project constructors may run.
- Text and JSON outputs are stable and tested.
- JSON success/error envelopes include top-level `warnings`.
- Validate does not execute stages or write run state.

Test expectations:

- Package: validate imports remain appropriately bounded.
- Unit: validate parser/options, static success/failure formatting,
  `--check-targets` warning behavior, target-check facade invocation, JSON
  warnings.
- Contract: validation facade contract if one is introduced.
- Integration: config composition plus pipeline validation; target construction
  across all `_target_` blocks using synthetic safe targets.
- E2E: deferred to Phase 6 unless cheap through `main(argv)`.
- Opt-in: none.

Design impact:

- First behavior-bearing command; locks the static-by-default safety posture.

Future compatibility:

- Preflight can later build richer diagnostics without changing validate's
  no-write/static default.

Alternatives rejected:

- Always instantiate targets: rejected because default validate should be cheap
  and avoid running trusted project constructors.
- Import-only target checks: rejected for `--check-targets` because constructor
  argument mismatches are important.

Debt introduced:

- Warning payloads are intentionally simple until v3 diagnostics.

Reviewability:

- Review as one command plus narrow owning-package validation/target-check
  facades.

Notes:

- PR feature focus: `CLI Core`
- Intended PR title: `CLI Core - Phase 3: Validate Command`

Completion summary:

- Pending.

### Phase 4 - Plan Command

Status: pending
Branch: `codex/add-cli-plan`
PR: pending

Goal:

- Add `loom plan` over v0 planning, selector, strict resume, and explanation
  APIs.

Scope:

- Add `src/loom/cli/plan.py`.
- Convert run URI, resume, and selector flags into owning planner/store inputs.
- Use public store/planner APIs for read-only resume planning; add owning
  package helpers if CLI code would otherwise inspect run-layout paths.
- Format ordered stage actions, reasons, and optional explanation output.
- Support a CLI-specific JSON plan view built from structured planner objects.

Out of scope:

- Run URI allocation when omitted.
- Run directory creation, lock acquisition, plan persistence, execution, or
  mutation of prior run state.
- CLI-local selector conflict logic beyond syntax-level parsing.

Acceptance criteria:

- Planning a fresh synthetic pipeline without `--run-uri` reports runnable
  stages in deterministic order and does not allocate a run URI.
- Planning with a new explicit local `--run-uri` is allowed and remains
  read-only.
- Planning with an existing `--run-uri` without `--resume` fails clearly.
- `--resume` requires `--run-uri`; missing or invalid run state fails clearly.
- Resume planning against an existing valid run URI reports `REUSE` or rerun
  decisions from planner output under strict resume behavior.
- Selector flags affect plan decisions through planner APIs.
- `--explain STAGE` reports available explanation details.
- Plan command does not execute stages and does not mutate run state.

Test expectations:

- Package: plan imports do not load executors or project targets.
- Unit: plan parser/options, run URI argument forwarding, resume requirement,
  no-allocation behavior, selector adapter behavior, text and JSON formatting.
- Contract: planner/store facade contract if added.
- Integration: fresh plan, new explicit run URI plan, existing target failure,
  strict resume against valid run URI, selector behavior, explain output.
- E2E: deferred to Phase 6 unless cheap through `main(argv)`.
- Opt-in: none.

Design impact:

- Establishes preview semantics: read-only and no default run URI allocation.

Future compatibility:

- V3 preflight and diagnostics can reuse the same CLI-specific plan view.

Alternatives rejected:

- Raw `ExecutionPlan.to_dict()` as CLI JSON: rejected to avoid tying automation
  output to internal/persisted planning schema.
- Lenient resume flag: rejected because v2 resume is always strict.

Debt introduced:

- CLI-specific plan JSON may omit advanced planner details until diagnostics
  need them.

Reviewability:

- Review as one read-only command with focused planning/store facades.

Notes:

- PR feature focus: `CLI Core`
- Intended PR title: `CLI Core - Phase 4: Plan Command`

Completion summary:

- Pending.

### Phase 5 - Run Command

Status: pending
Branch: `codex/add-cli-run`
PR: pending

Goal:

- Add `loom run` for v0 local execution.

Scope:

- Add `src/loom/cli/run.py`.
- Wire config, selectors, explicit/default run URI, strict resume, and local
  executor selection into `RunRequest` or the equivalent public execution
  facade.
- Request default local run URI allocation from the owning store/runtime facade
  when `--run-uri` is omitted for actual execution.
- Implement `--dry-run` by delegating to the plan path without default run URI
  allocation and producing plan JSON for `--format json`.
- Reject unsupported executors in command handling, not argparse choices, so
  they return executor exit code 7 without optional backend imports.
- Emit final-result JSON only for `--format json`.

Out of scope:

- Rich progress UI, streaming JSON progress, status/log/artifact commands,
  remote stores, subprocess execution, or scheduler behavior.

Acceptance criteria:

- A synthetic v0 pipeline can run from the command line.
- Without `--run-uri`, run uses a store-owned default local resolved absolute
  run URI and prints it.
- With explicit `--run-uri`, run uses the exact resolved target directory.
- Non-resume run fails if the target run URI already exists.
- Resume run requires an existing valid run URI and uses strict resume behavior.
- The command prints resolved run URI, final run status, and stage summary.
- Failed runs return execution failure exit code and concise failure output.
- `--dry-run` produces a plan and does not execute stages.
- Non-local executor names return executor error code 7 without optional backend
  import and without being treated as usage errors.
- JSON output is a single final envelope with resolved run URI, stage summaries,
  failure summary if any, and plan summary.

Test expectations:

- Package: run imports do not load optional backends unless execution requires
  the local executor.
- Unit: run parser/options, default URI facade invocation, explicit run URI
  forwarding, existing target checks, dry-run delegation, executor rejection,
  text and JSON formatting.
- Contract: execution/run facade contract if added.
- Integration: successful local run, failed local run, resume run, dry-run,
  explicit run URI, default run URI.
- E2E: at least one successful and one failed synthetic run through `main(argv)`
  or console entry point by Phase 6.
- Opt-in: none.

Design impact:

- First mutating CLI command; must prove mutation is owned by runtime/store
  facades rather than CLI path logic.

Future compatibility:

- Later runtime options and executor registries can replace the v2 adapter
  without changing the `loom run` command shape.

Alternatives rejected:

- Streaming JSON progress in v2: rejected to keep stdout valid final-result
  JSON and defer progress design.

Debt introduced:

- Only the local executor is supported. Revisit in v4/v5 executor registry and
  stage-worker work.

Reviewability:

- Review as one command over already-migrated run URI and existing local
  execution APIs.

Notes:

- PR feature focus: `CLI Core`
- Intended PR title: `CLI Core - Phase 5: Run Command`

Completion summary:

- Pending.

### Phase 6 - Hardening, Docs, And E2E Coverage

Status: pending
Branch: `codex/harden-cli-core`
PR: pending

Goal:

- Harden v2 behavior, document validate/plan/run, and add end-to-end coverage.

Scope:

- Update README and CLI docs for v2 commands only.
- Add stable examples for validate, validate `--check-targets`, plan, run,
  resume, selectors, text output, JSON output, explicit run URI, and default
  run URI behavior.
- Clearly identify `status`, `logs`, `artifacts`, `stage run`, subprocess,
  SLURM, sweep, catalog, bundle, plugin, remote store, container, reliability,
  and cleanup commands as deferred outside v2.
- Add e2e tests through `main(argv)` or the console entry point.
- Confirm import boundaries after all command modules exist.

Out of scope:

- New command behavior, new schemas beyond docs/examples, or broad runtime
  refactors.

Acceptance criteria:

- Docs describe only v2-supported commands and clearly defer later commands.
- Docs state strict local `file://` run URI rules and rejected forms.
- Docs explain that `--check-targets` imports and constructs trusted project
  targets.
- E2E tests cover validate, validate `--check-targets`, plan, run, failed run,
  dry-run, resume, explicit run URI, default run URI, and JSON output.
- `make validate-pr` passes.
- `make test-summary` records suite-level evidence.

Test expectations:

- Package: final import-boundary checks.
- Unit: any missed formatting/options edge cases discovered during docs/e2e.
- Contract: final suite evidence for run URI and CLI contracts.
- Integration: final validate/plan/run command integration.
- E2E: required.
- Opt-in: none.

Design impact:

- Low design impact; this phase verifies and documents the whole v2 surface.

Future compatibility:

- Documentation should point users toward future v3+ commands without promising
  unsupported behavior.

Alternatives rejected:

- Documentation-only PR without e2e: rejected because v2 is the first functional
  CLI layer.

Debt introduced:

- None expected beyond explicitly documented future command deferrals.

Reviewability:

- Review as final hardening, docs, and suite evidence.

Notes:

- PR feature focus: `CLI Core`
- Intended PR title: `CLI Core - Phase 6: Hardening and E2E`

Completion summary:

- Pending.

## Overall Test Plan

Package tests:

- `import loom` remains cheap and does not import `loom.cli`.
- `import loom.cli` does not load project code, plugin discovery, optional
  backends, stores, or heavy executor modules at help/import time.
- Console script metadata exists after build.
- Public migrated primitives such as `ArtifactAddress(run_uri, artifact_id)`
  import and round-trip.

Unit tests:

- Run URI parser/resolver/allocation behavior and rejected forms.
- Parser construction, help, version, subcommand registration, and invalid
  commands.
- Config, validate, plan, selector, run URI, run, executor, warning, and
  output-format option adapters.
- Exit-code mapping.
- Text and JSON formatting for validation, plan, run, warnings, and known
  errors.
- `--traceback` text and JSON behavior.

Command tests:

- Validate calls config and pipeline validation APIs.
- Validate `--check-targets` calls config-owned target construction after
  static validation.
- Plan calls planner APIs and never calls executor or runner execution methods.
- Plan maps `--run-uri` and selectors through planner/store APIs without
  CLI-local resume or run-layout logic.
- Run calls `PipelineRunner` or a public run facade and does not write run state
  directly.
- `--dry-run` uses planning behavior and returns plan JSON.
- Unsupported executor handling is clear, import-safe, and returns exit code 7
  rather than argparse usage code 2.

End-to-end tests:

- Validate a synthetic local pipeline config.
- Validate target checks with synthetic safe `_target_` blocks.
- Plan a synthetic local pipeline config.
- Plan with explicit local run URI and resume against existing run state.
- Run a synthetic local pipeline config with the local executor and default run
  URI.
- Run with explicit local run URI.
- Return nonzero and print useful output for failed synthetic stages.
- Produce parseable JSON for validate, plan, run, errors, and dry-run.

Validation gates:

```sh
make validate-pr
make test-summary
```

## Plan Quality Gate

Status: passed on 2026-05-06 by managing-agent review.

The v2 plan was reviewed against the quality gate for maintainability,
extensibility, future roadmap compatibility, conflicting design choices,
accepted technical debt, test strategy, and reviewability as one coherent v2
project plan.

Findings:

- No blocking findings remain.
- The largest accepted risk is Phase 1's hard schema/API migration from
  `run_id` to `run_uri`. The risk is contained by making Phase 1 a dedicated
  runtime/store migration with contract, integration, and fingerprint tests
  before command behavior begins.

Loop budget:

- Initial plan review: used.
- Plan refinement: already completed through the v2 refinement discussion and
  committed before phase implementation began.
- Confirmation review: not needed because the final review found no blocking
  findings after the refinement pass.

## Assumptions And Defaults

- V2 begins after v0 local runtime APIs and v1 config composition APIs are
  available.
- Python remains `>=3.12`.
- `argparse` is the only CLI framework in v2.
- No new runtime dependencies are required for v2.
- `--format text` is the default for all v2 commands.
- JSON output is newline-terminated UTF-8 written to stdout.
- Text warnings and errors are written to stderr.
- JSON envelopes include top-level `warnings`.
- `--set` values stay raw until passed to the config override parser.
- Repeated stage selector flags are normalized deterministically.
- `--run-uri` is the only v2 run-addressing CLI option.
- Explicit `--run-uri` values must use strict local `file://` syntax.
- Relative run URIs resolve against cwd and persist/output as absolute
  `file:///...` URIs.
- `loom plan` without `--run-uri` is hypothetical and read-only.
- `loom run` without `--run-uri` asks the owning store/runtime facade to
  allocate a default local run URI.
- Resume is always strict in v2. There is no `--strict` flag.
- `run_uri` is excluded from semantic stage fingerprints unless explicitly
  authored into config/stage inputs.
- `local` is the only supported executor in v2.
- Non-local executor names fail explicitly and are not silently ignored.
- Non-local executor names are rejected in command handling, not argparse
  choices, so they map to executor exit code 7.
- CLI modules may import public v0/v1 APIs, but v0/v1 internals may not import
  CLI modules.
- Later roadmap commands must extend the CLI package without changing the v2
  command contracts unless a separate compatibility plan approves it.

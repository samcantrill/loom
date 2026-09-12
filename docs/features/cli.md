# `loom.cli` Specification

## 1. Purpose

`loom.cli` is the command-line interface for `loom`.

Ordinary execution uses `loom run CONFIG --deployment PATH`, the CLI wrapper
around the lazy `loom.run` facade and native durable run operation. CONFIG and
overlays are relative to the selected preparation source. The deployment owns
connection/identity, permitted local startup, preparation profile and service
lifetime. See [configured startup](../downstream-operations.md#configured-startup-and-ordinary-run).

Validation, hypothetical planning, inspection and prepared-worker commands retain
their own library owners. Existing scheduler inspection and cancellation remain
available for already-submitted work. The retained Slurm and container library
demonstrations do not establish a complete managed backend journey or live-site
qualification; their native delivery remains with the backend phases.

V11 adds a narrow queue operations group: `loom queue preflight`,
`loom queue start`, `loom queue status`, `loom queue cancel`, and
`loom queue drain-foreground`. These commands are operational wrappers over the
Python queue service and configured repository; enqueue remains Python-first.
See [queue.md](queue.md) for the queue service ownership model and examples.

V23 adds `loom queue status CONFIG --pool POOL`, which renders a safe selected
pool summary through the existing queue-status envelope. CLI formatting does
not inspect dispatch evidence or make scheduling decisions.

V29 adds the protected persistent-role surface. `loom queue daemon-init CONFIG`
and `daemon-serve CONFIG` own one coordinator/embedded-agent deployment bundle;
`loom queue agent-init CONFIG` and `agent-serve CONFIG` own one outbound-agent
root. The same explicit owner-protected versioned YAML is required for init and
serve, with no discovery or environment override. Former daemon root/profile
setup flags are a hard cut. Operator commands retain their endpoint-based
surface, including the guarded `daemon-time-recover` operation.

Coordinator client commands (`daemon-prepare`, `daemon-cancel-preparation`,
`daemon-submit`, `daemon-status`,
`daemon-admissions`, `daemon-admission`, `daemon-agents`, `daemon-agent`,
`daemon-operation`, `daemon-operation-wait`, `daemon-wait` and `daemon-cancel`)
use the native `CoordinatorClient`. Select exactly one of `--endpoint PATH`
for the Unix socket or `--connection PATH` for a protected HTTPS client file.
Optional `--expected-coordinator-id ID` guards every request at the coordinator
before lookup or mutation. Existing positional arguments, output fields, exits,
page defaults and legacy overall wait durations remain supported. The
[native client guide](coordinator-client.md) documents the connection schema,
bounded calls, native results and reconciliation after an uncertain mutation.

`loom queue daemon-prepare --request PATH` reads the exact native JSON preparation
request and returns an operation; it does not wait for publication or submit the
target. `daemon-operation` and `daemon-operation-wait` observe it, and
`daemon-cancel-preparation OPERATION_ID` requests its native cancellation.
See [agent preparation](agent-preparation.md) for request fields, the specified
existing environment, shared snapshots, result states and replay semantics.

`loom queue daemon-upgrade CONFIG --env-file ENV_FILE` is the separate local
administrative upgrade for a retained coordinator root from schema 12 to 13.
It requires the stopped coordinator's exclusive lock and preserves worker roots
at schema 12. See the [upgrade procedure](../downstream-operations.md#upgrade-a-retained-coordinator-root).

V12 adds portable run exchange commands under the existing `loom runs` group:
`loom runs export`, `loom runs inspect`, and `loom runs import`. These commands
are thin wrappers over public `loom.runs` bundle APIs. They do not parse archive
members in CLI code, load provider plugins, dispatch remote exporters, or claim
live migrated resume support.

V21 adds conservative cleanup commands: `loom clean RUN_URI` for per-run
candidate cleanup and `loom gc COLLECTION` for candidate-level collection GC.
Both commands default to dry-run output, require `--delete` plus confirmation or
`--yes` for mutation, and call public cleanup APIs instead of deleting paths in
CLI code.

Roadmap commands for remote stores, additional container executors, and other
future operational surfaces remain intentionally deferred. The later-command
sections in this document distinguish current support from future shape.

V34 adds `loom inspect-run RUN_URI --direct` for bounded metadata-only
inspection of one canonical local run URI. `--endpoint SOCKET` instead selects
the owner-only local daemon socket and never falls back to a direct read.
`--remote-config CONFIG` selects the authenticated existing coordinator over
mTLS; it is mutually exclusive with the local selectors and also never falls
back. Its owner-protected `loom.run-inspection-client` v1 YAML names only the
HTTPS service URL and CA, certificate, and private-key paths. Relative paths
resolve beside that file; key material never appears in command arguments or
output. `--queue-config CONFIG` is direct-only. JSON output uses the separate
`loom.cli.inspect_run.v1` envelope; locations report recorded availability but
the command never reads artifact or log bytes.

For a managed local deployment, use `--endpoint` on the coordinator host or
`--remote-config` from a host that can reach that coordinator and its TLS name.
The remote credential must be a distinct protected `query` certificate mapped
by the coordinator's current policy; `client`, `operator`, and `agent`
credentials cannot use that query route, and a query credential cannot mutate.
The separate native coordinator client's `inspect_run()` uses client
authorization and the same managed-admission restriction over Unix and HTTPS;
it does not change this query command's credential policy. The
observation is a non-atomic owner join: `as_of`, per-axis revisions, and
freshness describe what was observed, not one global instant. A returned
`file://` location can be coordinator-local, shared-but-unknown, or external;
it is not a content-transfer capability.

For a service-less SLURM deployment, run the direct or owner-only command where
the run and its configured queue are available, optionally through site-owned
SSH. Loom supplies no SSH client, certificate issuance, endpoint discovery, or
artifact/log relay. The inspection command returns metadata and locations only;
use site transfer tooling or an accessible shared mount for content.

The v2 CLI should answer:

```text
How do I validate this config?
What would this run do?
How do I run this pipeline?
```

Future CLI phases should answer:

```text
What is the current status of a run?
Where are the logs for a failed stage?
Which artifacts did the run produce?
Why did resume choose RUN or REUSE?
```

It should not answer those questions by reimplementing config, planning,
execution, store, artifact, or scheduler logic.

The core rule is:

```text
The CLI parses arguments, calls Python APIs, formats results, and returns exit
codes.
```

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) treats the CLI as a thin wrapper over the Python API. This
document refines that into command groups and presentation rules while keeping
config composition, planning, execution, stores, artifacts, resume, and
provenance logic inside their owning modules.

---

## 2. Core Position

The CLI is the outermost layer of `loom`.

Recommended dependency shape:

```text
core model / serialization / io / config / pipeline / stores / provenance
        |
        v
cli
```

The CLI may import public APIs from:

```text
weave
loom.pipeline
loom.pipeline.execution
loom.pipeline.planning
loom.pipeline.stores
loom.pipeline.executors
loom.provenance
loom.artifacts
```

The CLI should not be imported by those packages.

Bad dependency shape:

```text
pipeline.runner imports cli.run
run_store imports cli.status
config.compose imports cli.main
```

Good dependency shape:

```text
cli.run imports PipelineRunner
cli.plan imports PipelinePlanner
cli.status imports RunStore inspection APIs
```

This keeps Python APIs usable in tests, notebooks, project wrappers, and
downstream package CLIs without shelling out to `loom`.

---

## 3. Package Boundary

### 3.1 `loom.cli`

Owns command-line presentation.

Responsibilities:

```text
argument parsing
subcommand registration
input path normalization for CLI arguments
human-readable output formatting
machine-readable output formatting
exit code selection
top-level exception handling
terminal color policy, if any
```

### 3.2 `weave`

Owns config composition and instantiation.

CLI responsibilities:

```text
pass config path, overlay paths, and dot-path overrides to config APIs
print validation and composition errors clearly
show resolved config path when requested
```

CLI non-responsibilities:

```text
implement merge logic
expand recipes manually
instantiate `_target_` objects directly outside config APIs
own redaction policy
```

### 3.3 `loom.pipeline`

Owns pipeline specs, planning, selectors, resume decisions, and execution APIs.

CLI responsibilities:

```text
parse selector flags into structured selector options
call planner and runner APIs
format stage action tables
return non-zero when run fails
```

CLI non-responsibilities:

```text
validate DAGs directly
bind stage inputs directly
compute stage fingerprints directly
apply resume policy directly
```

### 3.4 `loom.pipeline.execution`

Owns runner lifecycle and worker entry points.

CLI responsibilities:

```text
construct the native RunRequest or a worker StageExecutionRequest
call the shared managed run facade for ordinary execution
call stage-worker API for `loom stage run`
print concise summaries
```

### 3.5 `loom.pipeline.stores`

Owns run and artifact persistence.

CLI responsibilities:

```text
open run stores through public APIs
read status, logs, artifacts, plans, and provenance through store APIs
display summaries
```

CLI non-responsibilities:

```text
duplicate run directory path logic
read arbitrary JSON files by hard-coded paths when store APIs exist
write status or artifact indexes manually
```

### 3.6 `loom.pipeline.executors.slurm`

Owns SLURM dry-run planning in v6 and live submission mechanics in v7/later.

CLI responsibilities:

```text
retain the existing planning/submission library APIs for mapped consumers
keep ordinary run selection in the configured deployment
report generated/submitted evidence through the owning backend consumers
call scheduler-aware status and cancellation APIs for --jobs
```

CLI non-responsibilities:

```text
generate sbatch scripts directly
parse scheduler command output directly
build dependency graphs directly
```

---

## 4. Current Scope

### 4.1 Must Support in v2

```text
loom --help
loom --version
loom validate CONFIG
loom plan CONFIG
loom run CONFIG --deployment PATH
loom run CONFIG --deployment PATH --operation-id ID --detach
loom status RUN_URI
loom status RUN_URI --jobs
loom cancel RUN_URI --jobs
loom runs index COLLECTION
loom runs list COLLECTION
loom runs diff COLLECTION RUN_A RUN_B
loom runs export RUN_URI BUNDLE
loom runs inspect BUNDLE
loom runs import BUNDLE TARGET_COLLECTION
loom stage run --run-uri RUN_URI --stage STAGE [--attempt N]
loom prepared-run continue --run-uri RUN_URI --executor local
loom stage-job run --run-uri RUN_URI --stage STAGE --executor local
basic top-level exception formatting
non-zero exit codes for failures
config overlays and CLI overrides
resume selector flags shared by plan and run
configured native execution and retained library executor demonstrations
machine-readable JSON output for validate, plan, run, stage run, prepared-run,
stage-job, scheduler status/cancel, run catalog and bundle
exchange commands, and structured errors
loom plan CONFIG --resume --explain STAGE
```

### 4.2 Run Exchange Commands

`loom runs export RUN_URI BUNDLE` exports a completed local run into a local
bundle archive. Metadata-only export is the default. Users opt into copied refs
with `--include-payloads`, `--include-logs`, and `--include-workspace`; checksum
verification is explicit with `--verify-checksums`.

`loom runs inspect BUNDLE` reads bundle metadata and diagnostics without
extracting archive members. It can verify member checksums when requested.

`loom runs import BUNDLE TARGET_COLLECTION` imports into a local target
collection with target-local identity and historical-only readiness. Source run
identity and bundle evidence are preserved as provenance. The CLI returns JSON
result envelopes with the same public result records used by Python callers.

The run exchange CLI does not:

```text
implement archive safety itself
mutate target run stores directly
load exporter plugins
contact remote services
perform provider-specific transfer
enable live migrated resume
```

### 4.3 Must Not Support in v2

```text
interactive TUI
web dashboard
remote run service
database-backed search
complex artifact query language
automatic config wizard
domain-specific commands
rich progress UI requiring heavyweight dependencies
shelling out to `loom` from inside Python APIs
Docker or Apptainer execution
remote run URI schemes
sweep, plugin, cleanup, reliability, or provider-specific bundle commands
--run-dir, --run-id, or --strict options
```

Domain packages can expose their own CLIs that call `loom` Python APIs.

### 4.4 Deferred Command Families

```text
loom sweep plan ...
loom sweep run ...
loom slurm status RUN_URI
loom slurm cancel RUN_URI
shell completion
```

These command families require later sweep, executor, or remote-store APIs. V2
should fail clearly rather than partially implement them.

---

## 5. CLI Framework

### 5.1 Recommended Default

Use `argparse` from the standard library for the v2 command surface.

Reasons:

```text
no runtime dependency
easy to test
available everywhere
enough for the initial command set
keeps CLI import lightweight
```

### 5.2 Deferred Alternatives

Possible later options:

```text
click
typer
rich
```

Do not add these unless the command surface becomes large enough to justify the
dependency.

### 5.3 Entry Point

Recommended `pyproject.toml` script:

```toml
[project.scripts]
loom = "loom.cli.main:main"
```

`main` should accept an optional argv for tests:

```python
def main(argv: Sequence[str] | None = None) -> int: ...
```

The console entry point should call `raise SystemExit(main())`.

---

## 6. Command Style

### 6.1 General Shape

Prefer:

```text
loom COMMAND [ARGS] [OPTIONS]
```

Examples:

```bash
loom validate experiment.yaml
loom plan experiment.yaml --run-uri file:///abs/project/runs/example --resume
loom run experiment.yaml --deployment deployment.yaml
loom status file:///abs/project/runs/example
```

### 6.2 Subcommand Groups

Use groups when a concept has multiple operations:

```text
loom stage run ...
loom artifacts list ...
loom artifacts show ...
loom slurm status ...
loom slurm cancel ...
```

Avoid too many top-level verbs once related commands grow.

### 6.3 Path Arguments

Use explicit names:

```text
CONFIG
RUN_URI
STAGE
ARTIFACT_ID
```

When functional CLI behavior is added, do not infer a config path from the
current directory.

### 6.4 Option Names

Use long, readable options:

```text
--run-uri
--overlay
--set
--executor
--resume
--from-stage
--only-stage
--force-stage
--skip-stage
--format
```

Short aliases can be added later for common options, but they are not required.

### 6.5 Repeated Options

Allow repeated options where natural:

```bash
loom run experiment.yaml --deployment deployment.yaml \
  --overlay local.yaml \
  --overlay debug.yaml \
  --set run.seed=1 \
  --set model.hidden=32 \
  --force-stage train \
  --force-stage evaluate
```

The CLI should preserve option order when order is semantically meaningful.

---

## 7. Shared Options

### 7.1 Config Composition Options

Shared by:

```text
validate
plan
run
sweep, later
```

Recommended:

```text
CONFIG
--overlay PATH, repeatable
--set KEY=VALUE, repeatable
--config-root PATH, optional later
--print-resolved, optional
```

`--set` should pass raw dot-path override strings to `weave`. The CLI
should not reimplement override parsing beyond collecting strings.

### 7.2 Run Identity and Planning

Ordinary run selects `--deployment PATH`, an optional stable `--operation-id ID`,
and optional `--queue-item-id ID` and `--run-name NAME`. Exact replay observes the
same native intent; it does not authorize failed-admission retry. The coordinator
owns target allocation and publication.

`loom plan` retains its read-only `--run-uri RUN_URI` and `--resume` options.
Those options are not accepted by ordinary managed run.

### 7.3 Stage Selector Options

Shared by:

```text
plan
run
```

Recommended:

```text
--from-stage STAGE
--only-stage STAGE
--force-stage STAGE, repeatable
--skip-stage STAGE, repeatable
```

The CLI should convert these into structured selector options, then pass them to
planner/runner APIs.

### 7.4 Execution Profile

Ordinary run uses the deployment's authorized preparation/execution profile.
Executor, authority and plugin selection are not ordinary-run CLI overrides.
Existing worker, preflight and library APIs retain their separately documented
options for their current consumers.

### 7.5 Output Format Options

Shared by inspection commands:

```text
--format text|json
--verbose
--quiet
--no-color
```

V2 defaults to text and supports JSON for validate, plan, run, and structured
errors. `--verbose`, `--quiet`, and `--no-color` are deferred.

### 7.6 Logging Options

Recommended:

```text
--log-level debug|info|warning|error
--traceback
```

Default errors should be concise. `--traceback` can show full Python tracebacks
for debugging.

---

## 8. Output Policy

### 8.1 Human Output

Human output should be concise and stable.

Good:

```text
Run: file:///abs/project/runs/example
Status: FAILED

Stage           Status     Action  Reason
build_manifest  SUCCEEDED  REUSE   fingerprint match
train           FAILED     RUN     error in attempt 1
```

Avoid:

```text
large raw JSON dumps by default
Python repr of internal objects
stack traces unless requested
```

### 8.2 Machine Output

V2 supports JSON for automation-facing commands:

```bash
loom plan experiment.yaml --format json
loom validate experiment.yaml --format json
loom run experiment.yaml --deployment deployment.yaml --format json
```

Machine output should come from structured API results, not by parsing human
tables.

V2 JSON output is always a versioned envelope with top-level `warnings`:

```json
{"schema_version":"loom.cli.plan.v2","ok":true,"warnings":[],"result":{}}
```

Ordinary run emits `loom.cli.run.v3` with native operation, admission and
inspection facts, connection identity and separate per-role cleanup evidence.
Use `loom plan` for hypothetical planning. Retained Slurm planning examples
report the existing library planner's artifacts; they are not ordinary-run dry
runs. Parsed command errors use the error envelope on stdout when JSON is known;
argparse usage errors remain text on stderr.

### 8.3 Color

Color is optional.

V2 omits color entirely. If added later:

```text
auto-detect terminal
disable when --format json
support --no-color
do not require rich as a hard dependency
```

### 8.4 Standard Output and Error

Recommended:

```text
normal command output -> stdout
warnings and errors -> stderr
machine JSON -> stdout
```

This makes shell scripting predictable.

---

## 9. Exit Codes

### 9.1 Recommended Codes

Use small, conventional exit codes:

```text
0:
  success

1:
  command completed but requested operation failed

2:
  CLI usage error or argument parse error

3:
  config validation or composition error

4:
  pipeline validation or planning error

5:
  run execution failed

6:
  run state or inspection error

7:
  executor or scheduler submission error

130:
  interrupted by Ctrl-C
```

Exact values can be adjusted, but they should be documented and tested.

### 9.2 Python Exceptions

Top-level CLI should catch known `loom` errors and print concise messages.

Unknown exceptions:

```text
without --traceback:
  print concise internal error message and suggest --traceback

with --traceback:
  print full traceback
```

### 9.3 Partial Success

Some commands can partly succeed:

```text
SLURM afterok submission submitted some jobs then failed
status read run state but scheduler state unavailable
logs found stdout but not stderr
```

These should return non-zero when the requested operation could not be completed,
and the output should identify what succeeded.

---

## 10. `cli/main.py`

### 10.1 Purpose

`main.py` registers commands and owns top-level error handling.

Responsibilities:

```text
build parser
register subcommands
dispatch to command modules
handle --version
handle top-level --traceback
return exit code
```

### 10.2 Recommended Shape

```python
def build_parser() -> argparse.ArgumentParser: ...

def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
```

### 10.3 Import Policy

Avoid importing heavy subcommands before they are needed if possible.

V2 can keep this simple, but the parser should not import project packages during
`loom --help`.

---

## 11. `loom validate`

### 11.1 Purpose

Validate config and pipeline structure without running stages.

Command:

```bash
loom validate CONFIG
```

### 11.2 Options

Recommended:

```text
--overlay PATH, repeatable
--set KEY=VALUE, repeatable
--format text|json
```

### 11.3 Behavior

Should:

```text
compose config
expand recipes
resolve interpolation
validate top-level config shape
build PipelineSpec
validate stage specs and DAG
print success or errors
```

Validation stays static: it checks Loom-owned pipeline structure and
runtime/resource settings. Project owners perform construction and readiness
checks for their `_target_` objects during execution. Pipeline metadata, each
stage's `config`, and `factory.init` remain project-owned data at this boundary.

Should not:

```text
run stages
submit jobs
write a run directory, unless explicit validation output is requested later
instantiate arbitrary project objects
```

### 11.4 Output

Success:

```text
OK  experiment.yaml
Stages: 4
```

Failure:

```text
Config validation failed.

Path: pipeline.stages[2].depends_on[0]
Error: unknown stage "preprocess"
```

---

## 12. `loom plan`

### 12.1 Purpose

Show what `loom run` would do without executing stages.

Command:

```bash
loom plan CONFIG
```

### 12.2 Options

Recommended:

```text
--overlay PATH, repeatable
--set KEY=VALUE, repeatable
--run-uri RUN_URI
--resume
--from-stage STAGE
--only-stage STAGE
--force-stage STAGE, repeatable
--skip-stage STAGE, repeatable
--explain STAGE
--format text|json
```

### 12.3 Behavior

Should:

```text
compose config
build PipelineSpec
open prior run state read-only when --resume requires --run-uri
compute stage actions through planner APIs
show action reasons
not execute stages
not submit jobs
not allocate default run URIs
not mutate prior run state
```

Without `--run-uri`, `loom plan` is a fresh hypothetical plan. With
`--run-uri` and no `--resume`, planning is still read-only and should fail if
the target already exists. With `--resume`, the run URI must identify an
existing valid run and strict resume behavior applies.

### 12.4 Human Output

Example:

```text
Stage           Action  Reason
build_manifest  REUSE   fingerprint match
train           RUN     fingerprint changed
evaluate        RUN     upstream changed: train
report          RUN     upstream changed: evaluate
```

### 12.5 Explanation Output

Example:

```bash
loom plan experiment.yaml --resume --explain train
```

Should show:

```text
stage action
prior fingerprint
current fingerprint
changed fingerprint inputs, when available
missing artifacts
upstream invalidation chain
```

Detailed diffing belongs to planning APIs. The CLI formats the result.

---

## 13. `loom run`

The ordinary command starts or reuses explicitly selected services, accepts one
native RunRequest, and observes its durable operation/admission.

```bash
loom run pipeline.yaml --deployment deployment.yaml
loom run pipeline.yaml --deployment deployment.yaml --operation-id experiment-001 --detach
loom run pipeline.yaml --deployment deployment.yaml --operation-id experiment-001 --timeout-seconds 30 --format json
```

CONFIG and repeated `--overlay` paths must be contained in the deployment's
selected preparation project and source closure. Repeated `--set` overrides,
`--profile`, stage selectors, `--max-parallel-stages`, `--failure-policy`, tags
and notes become the native preparation intent. `--operation-id` supports exact
replay; `--queue-item-id` and `--run-name` select the corresponding native names.

Default wait returns native terminal facts. `--detach`, bounded observation and
interruption preserve accepted identities without cancellation. Retry and
cancellation remain explicit native controls. Cleanup reports stopped,
persistent/borrowed, retained-for-other-work or cleanup-blocked independently of
scientific success/failure. A cleanup refusal never authorizes killing unresolved
work.

The deployment owns expected coordinator identity, bound local creation/opening,
per-role persistent/run lifetime and startup/observation policy. Executor,
run-URI/resume, dry-run, authority and plugin bypass flags were removed from this
command. See [configured startup](../downstream-operations.md#configured-startup-and-ordinary-run)
for the protected selection schema, mixed roles and qualification limits.

The command does not execute stages, allocate run stores, generate scheduler
scripts or recompute resume decisions in its own handler. The native coordinator
and existing worker/backend owners perform those operations.

---

## 14. `loom stage run`

### 14.1 Purpose

Run exactly one stage attempt from an existing run URI.

This command is the stable parent-managed worker entry point for:

```text
SubprocessExecutor
future parent-managed workers
```

Command:

```bash
loom stage run --run-uri RUN_URI --stage STAGE
```

### 14.2 Options

Recommended:

```text
--run-uri RUN_URI, required
--stage STAGE, required
--attempt ATTEMPT, optional exact prepared attempt
--format {text,json}
--traceback
```

### 14.3 Behavior

Should:

```text
open existing run directory
load resolved config and prepared stage request metadata
load pipeline spec or stage execution request
load prepared inputs for the selected stage
run exactly one stage attempt through execution API
write logs and structured worker result handoff
exit with meaningful code
```

Should not:

```text
perform whole-pipeline planning
modify unrelated stages
submit scheduler jobs
finalize the whole run
create a new run directory from scratch
accept a normal --config input instead of durable run metadata
```

### 14.4 Worker Contract

The command should be reconstructible from durable state:

```text
run directory
stage name
attempt number
resolved config
plan/stage request files
```

It should not require pickled Python objects passed over the command line.

Submitted afterok jobs use the separate `loom stage-job run` command so each
job can finalize one planned stage from durable run-store state without a live
parent process.

Exit codes:

```text
0  successful worker result handoff
1  failed stage result handoff
2  usage error
3  missing, invalid, or ambiguous prepared worker state
130 interrupted
```

### 14.5 Example

```bash
loom stage run --run-uri file:///abs/project/runs/example --stage train --attempt 1
```

---

## 15. `loom status`

### 15.1 Purpose

Show current or final run state without importing project stage code.

Command:

```bash
loom status RUN_URI
```

### 15.2 Options

Recommended:

```text
--format text|json
--jobs
--verbose
```

### 15.3 Behavior

Should read through run-store APIs:

```text
run metadata
run status
plan
stage statuses
artifact index
failure summaries
log paths
provenance summaries
reliability policy and outcome summaries
```

Should not:

```text
compose config
instantiate stages
import project stage modules
query scheduler unless --jobs or executor-specific status is requested
```

### 15.4 Output

Example:

```text
Run: file:///abs/project/runs/example
Status: FAILED
Started: 2026-05-02T00:00:00Z
Finished: 2026-05-02T00:10:00Z

Stage           Status     Attempts  Last Reason
build_manifest  SUCCEEDED  1         -
train           FAILED     1         process exited 1
evaluate        PENDING    0         blocked: train
```

When reliability facts exist, status output may include compact per-stage
policy, transaction, retry, timeout, and unsupported-timeout summaries. JSON
output carries the same information under each stage reliability summary.
Detailed raw reliability records remain available through backend inspection
JSON.

---

## 16. `loom logs`

### 16.1 Purpose

Show or locate logs for a stage.

Command:

```bash
loom logs RUN_URI STAGE
```

### 16.2 Options

Recommended:

```text
--stream stdout|stderr|both
--tail N
--follow
--paths
```

### 16.3 Behavior

Should:

```text
resolve log paths through run-store APIs
print selected log content
handle missing logs clearly
support path display for users who want to open files themselves
```

Should not:

```text
hard-code log path strings when store APIs exist
contact scheduler unless a future executor-specific mode requires it
```

The first logs phase can start with `--paths` and simple file printing.
`--follow` can be deferred.

---

## 17. `loom artifacts`

### 17.1 Purpose

Inspect artifacts recorded for a run.

Initial commands:

```bash
loom artifacts list RUN_URI
loom artifacts show RUN_URI ARTIFACT_ID
```

### 17.2 `artifacts list`

Should show:

```text
artifact ID
producer stage
artifact type
codec key
checksum presence
URI
```

### 17.3 `artifacts show`

Should show one artifact ref and selected provenance.

Options:

```text
--format text|json
--verify-checksum, later
```

### 17.4 Boundary

Artifact commands inspect refs and metadata by default.

They should not load arbitrary artifact contents unless an explicit command is
added:

```bash
loom artifacts cat RUN_URI ARTIFACT_ID
```

Loading artifact contents requires codec resolution and can execute project
codec code, so it should be explicit.

---

## 18. `loom runs`

### 18.1 Purpose

Inspect local run collections through the public `loom.runs` API.

Implemented commands:

```bash
loom runs index COLLECTION
loom runs list COLLECTION
loom runs diff COLLECTION LEFT_RUN_URI RIGHT_RUN_URI
```

### 18.2 `runs index`

Rebuilds the derived local catalog sidecar from authoritative run directories.
It reports indexed and skipped counts plus warnings for invalid, unreadable, or
partial runs.

Options:

```text
--format text|json
```

### 18.3 `runs list`

Lists current run summaries after refresh-on-read catalog reconciliation.

Supported exact-match filters:

```text
--status STATUS
--tag KEY=VALUE
--config-fingerprint VALUE
--pipeline-fingerprint VALUE
--commit VALUE
--stage-status [STAGE=]STATUS
--artifact [NAME=]ARTIFACT_ID
--artifact-checksum [NAME=]CHECKSUM
--executor VALUE
--backend VALUE
```

Options:

```text
--format text|json
```

### 18.4 `runs diff`

Compares two runs from a local collection using persisted metadata only.

```bash
loom runs diff runs/ file:///abs/runs/a file:///abs/runs/b
```

The command formats `RunCatalog.compare()` output and does not load artifact
payloads, import project code, or apply domain metric semantics.

### 18.5 Boundary

The CLI may parse filter flags and format public result models. It must not
scan run directories directly, query the private SQLite sidecar directly,
duplicate comparison logic, load artifact payloads, or infer a collection from
arbitrary run selectors.

JSON output uses command-specific schema versions:

```text
loom.cli.runs.index.v1
loom.cli.runs.list.v1
loom.cli.runs.diff.v1
```

---

## 19. Scheduler-Aware Status and Cancellation

### 19.1 Purpose

Expose submitted-job status and cancellation without mixing scheduler parsing
logic into CLI modules.

Implemented commands:

```bash
loom status RUN_URI --jobs
loom cancel RUN_URI --jobs
```

### 19.2 Behavior

Default status reads persisted run-store state only:

```bash
loom status RUN_URI
```

Scheduler-aware status is explicit:

```bash
loom status RUN_URI --jobs
```

It discovers the latest submitted backend from run-store records, delegates to
the backend status API, records safe scheduler snapshots, and reports
uncertainty when neither run-store final state nor scheduler data can prove a
final outcome.

Submitted-job cancellation is also explicit:

```bash
loom cancel RUN_URI --jobs
```

It targets the latest active submitted operation by default, records per-job
cancellation attempts, and returns nonzero for partial cancellation. Exact
submission selectors, cleanup commands, retries, and `loom slurm ...` aliases
remain deferred.

### 19.3 Boundary

The CLI calls executor or generic submitted-operation APIs:

```text
SlurmExecutor.status(...)
SlurmExecutor.cancel(...)
submitted-operation discovery helpers
```

or a scheduler client abstraction.

It should not parse `sacct`, `squeue`, or `scancel` output directly inside CLI
modules.

---

## 20. `loom sweep`

### 20.1 Purpose

Run or inspect experiment sweeps.

Command:

```bash
loom sweep SWEEP_CONFIG
```

### 20.2 Boundary

Sweep behavior should be specified in `docs/features/sweeps.md`.

The CLI should eventually support:

```text
loom sweep plan SWEEP_CONFIG
loom sweep run SWEEP_CONFIG
loom sweep status SWEEP_RUN_URI
```

Defer sweep commands until the sweep planning API exists.

---

## 21. Operational Commands

### 21.1 Cleanup And GC

Current cleanup commands:

```bash
loom clean RUN_URI
loom clean RUN_URI --older-than 7d --delete --yes
loom gc RUNS_DIR --older-than 30d
loom gc RUNS_DIR --retention-mode temporary --delete --yes
```

`loom clean` and `loom gc` parse bounded selector flags into
`CleanupSelector`, call `plan_cleanup` or `plan_collection_gc`, and format text
or JSON output from public cleanup report/result records. Mutating commands
build `CleanupDeleteIntent` records and delegate deletion to cleanup execution
APIs so result facts and audit events remain the correctness evidence.

The CLI must not:

```text
delete files directly
treat collection paths as managed roots
load provider SDKs or credentials for cleanup
authorize deletion through event sinks
offer whole-run deletion flags in the Stage 21 command surface
parse arbitrary cleanup query expressions
```

### 21.2 Still Deferred

Several useful operational commands should stay out of the CLI unless the
underlying Python APIs exist:

```text
loom graph CONFIG --format dot
loom diff RUN_A RUN_B
loom events RUN_URI
```

`graph` should format pipeline graph APIs, `diff` should format planning and
provenance summaries, and a future `events` command should read runtime event
records, callback failures, and observer links without mutating run state or
loading event sink plugins. The CLI should not load domain artifact payloads or
implement file deletion policy directly.

---

## 22. Error Formatting

### 22.1 Known Errors

Known `loom` errors should print:

```text
short title
path or command context
specific message
hint when available
```

Example:

```text
Pipeline validation failed.

Path: pipeline.stages[1].depends_on[0]
Error: unknown stage "load"
```

### 22.2 Tracebacks

Default:

```text
hide traceback for known errors
hide traceback for unknown errors but mention --traceback
```

With `--traceback`:

```text
print full traceback
```

### 22.3 Error JSON

For `--format json`, errors should be structured where practical:

```json
{
  "ok": false,
  "error": {
    "type": "PipelineValidationError",
    "message": "unknown stage",
    "path": "pipeline.stages[1].depends_on[0]"
  }
}
```

V2 supports JSON error envelopes once the command and requested format parse
successfully. Future commands should reuse the same envelope shape.

---

## 23. Result Models

### 23.1 Purpose

CLI modules should format structured result objects returned by Python APIs.

Examples:

```text
ValidationResult
PlanResult
RunResult
StageWorkerResult
StatusSummary
ArtifactListResult
LogLocationResult
```

The CLI should not need to inspect internal dataclasses deeply.

### 23.2 Formatting Helpers

Recommended modules:

```text
cli/formatting.py
cli/errors.py
```

Responsibilities:

```text
stage action table
status table
artifact table
JSON output
error output
```

Keep formatting helpers independent from business logic.

---

## 24. Configuration and Environment

### 24.1 CLI Environment Variables

V2 avoids CLI-specific environment variables.

Possible later variables:

```text
LOOM_LOG_LEVEL
LOOM_NO_COLOR
LOOM_CONFIG_ROOT
```

Do not add environment variables unless scripts need them.

### 24.2 Working Directory

CLI commands should pass the current working directory to provenance capture
where appropriate.

Path resolution policy belongs to config/run-store APIs.

### 24.3 Secrets

The CLI should avoid printing:

```text
unredacted resolved config values
secret-like override values
environment variable values
remote URLs with credentials
```

Use redacted config/provenance views by default.

---

## 25. Testing Strategy

### 25.1 Parser Tests

Test:

```text
top-level help
version output
validate args
plan args
run args
stage run args
status args
repeated --overlay
repeated --set
repeated --force-stage and --skip-stage
invalid command returns usage error
```

### 25.2 Command Unit Tests

Use fake APIs where possible.

Test:

```text
validate calls config and pipeline validation APIs
plan calls planner API and formats actions
run calls PipelineRunner
stage run calls stage worker API
status calls run-store inspection API
logs calls run-store log path API
artifacts list calls artifact index API
```

### 25.3 Exit Code Tests

Test:

```text
success returns 0
argparse usage error returns 2
config error returns documented config code
pipeline validation error returns documented planning code
run failure returns documented execution code
KeyboardInterrupt returns 130
```

### 25.4 Golden Output Tests

Use small stable text snapshots for:

```text
plan table
status table
artifact list table
known error message
```

Avoid brittle snapshots for timestamps or full paths unless normalized.

### 25.5 Integration Tests

For v2, test through the console entry point or `main(argv)`:

```text
loom validate example config
loom plan example config
configured native run
loom validate leaves project targets as data; loom run reports construction failures
hypothetical planning through loom plan
exact native operation replay and explicit retry controls
JSON output and JSON error envelopes
```

### 25.6 Import Boundary Tests

Test:

```text
import loom does not import loom.cli
loom --help does not import project packages
loom --help does not import project stage code
loom.cli modules do not get imported by pipeline/config/stores
```

---

## 26. Implementation Roadmap

V2 implements the entry point, validate, plan, and run phases. Later command
families remain roadmap guidance and should be implemented only after their
owning APIs are stable.

### 26.1 Phase 1: Entry Point and Parser

Create:

```text
src/loom/cli/__init__.py
src/loom/cli/main.py
```

Implement:

```text
main(argv=None)
build_parser
--help
--version
top-level --traceback
exit code constants
```

### 26.2 Phase 2: Validate and Plan

Create:

```text
src/loom/cli/validate.py
src/loom/cli/plan.py
src/loom/cli/formatting.py
```

Implement:

```text
loom validate
loom plan
shared config option parsing
selector option parsing
plan table formatting
```

### 26.3 Phase 3: Run

Create:

```text
src/loom/cli/run.py
```

Implement:

```text
loom run
executor option parsing
RunRequest construction
PipelineRunner integration
run summary formatting
```

### 26.4 Later Phase: Stage Worker

Create:

```text
src/loom/cli/stage.py
```

Implement:

```text
loom stage run
run-uri/stage/attempt args
stage worker API integration
worker result exit codes
```

### 26.5 Later Phase: Status and Logs

Create:

```text
src/loom/cli/status.py
src/loom/cli/logs.py
```

Implement:

```text
loom status
status table
JSON status output
loom logs, at least path display or simple content display
```

### 26.6 Later Phase: Artifacts

Create:

```text
src/loom/cli/artifacts.py
```

Implement:

```text
loom artifacts list
loom artifacts show
text and JSON output
```

### 26.7 Later Phase: Run Catalog Commands

Implemented:

```text
loom runs index COLLECTION
loom runs list COLLECTION
loom runs diff COLLECTION LEFT_RUN_URI RIGHT_RUN_URI
```

These commands are thin wrappers over `loom.runs.RunCatalog`.

### 26.8 Phase 7: Submitted-Job Commands

Implemented:

```text
loom status RUN_URI --jobs
loom cancel RUN_URI --jobs
```

Executor-specific `loom slurm ...` aliases are deferred until a diagnostic
cannot fit the general command model.

### 26.9 Phase 8: Sweep Commands

Add after sweep design and APIs exist:

```text
loom sweep plan
loom sweep run
loom sweep status
```

### 26.10 Stage 29 Persistent And Explicit Ready-Stage Operations

Stage 29 keeps CLI commands thin over separately scoped coordinator client,
operator, agent, and internal bootstrap application views. Exact command names
are finalized with their implementation phase; the required conceptual surface
is:

```text
initialize/open/start coordinator role state
initialize/open/start an agent role and connect it outbound
submit, inspect, wait for, and cancel a run through the coordinator
drain/resume/reload an agent
reload protected coordinator scheduling and SLURM-profile configuration
inspect owner-labelled stage assignment/SLURM/bootstrap/result axes
perform separately authorized positive-containment recovery
```

Stage routing belongs to exact-stage configuration, not an opportunistic CLI
fallback flag:

```yaml
runtime:
  stages:
    train:
      placement:
        execution_route:
          kind: slurm
          profile: training
```

The user still submits the run once. Loom sends `train` to only the named
profile after its dependencies commit. There is no `--use-slurm-if-agents-busy`
behavior, and status/cancel use the run identity rather than requiring users to
control raw scheduler job IDs. Machine-readable status retains admission,
authority lifecycle, scheduling route, assignment/execution, SLURM dispatch/
observation, bootstrap, transfer/result, cancellation, and health axes.

The scheduler-started Loom bootstrap command is an internal generated worker
entry point. Users do not invoke it to choose an assignment, and its arguments
contain only safe opaque identities/references. Profile and service secrets do
not appear in CLI examples, generated command output, or status.

After explicit first initialization, no correctness-required service start
order exists. Authority then coordinator then agents is the quiet operational
order; other orders produce typed pending/degraded state and reconnect. An
unavailable SLURM profile leaves its explicitly routed stages waiting without
changing route.

---

## 27. Open Questions

### 27.1 Should the CLI Use `argparse` or `typer`?

Recommended answer when functional CLI behavior is added:

```text
argparse
```

The initial command set does not justify a new hard runtime dependency.

### 27.2 Should `loom submit` Exist?

Recommended answer:

```text
not initially
```

Use:

```bash
loom run CONFIG --deployment PATH
```

Add `loom submit` later only if submission semantics diverge clearly from run
semantics.

### 27.3 Should `loom inspect` Be a Group?

Recommended answer:

```text
prefer concrete commands first: status, logs, artifacts
```

An `inspect` group can be added later if inspection commands become numerous.

### 27.4 Should `loom status` Query SLURM by Default?

Recommended answer:

```text
no
```

Default status should read persisted run state. Use `--jobs` for scheduler
state. A `loom slurm status` alias remains deferred.

### 27.5 Should Artifact Commands Load Artifact Contents?

Recommended answer:

```text
not by default
```

Inspect refs first. Loading content through project codecs should be explicit.

---

## 28. Summary

`loom.cli` should be a thin, stable command-line shell over the Python APIs.

Its main jobs are:

```text
parse arguments
call config, planning, execution, store, artifact, provenance, and executor APIs
format human and machine output
return documented exit codes
provide worker entry points for subprocess and SLURM execution
keep status/log/artifact inspection convenient
```

It should not become:

```text
a workflow engine
a config composer
a DAG validator
a run store implementation
a SLURM script generator
a domain-specific CLI
a dashboard
```

Keeping the CLI thin makes behavior consistent between Python callers, local
commands, subprocess workers, SLURM jobs, tests, and downstream project wrappers.

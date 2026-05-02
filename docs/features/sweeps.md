# `loom.pipeline.sweep` Specification

## 1. Purpose

`loom.pipeline.sweep` expands one base experiment into many ordinary `loom`
pipeline runs.

It exists so users can run repeatable ablations and small hyperparameter
explorations without copying whole config files or writing project-specific loop
scripts for every experiment.

The sweep layer should answer:

```text
Which trial configs should be produced from this base config?
What override set belongs to each trial?
What run directory belongs to each trial?
Which trials are planned, running, succeeded, failed, or reused?
How can trial results be summarized and collected?
```

It should not answer:

```text
How should one pipeline stage execute?
How should configs be merged?
How should a stage fingerprint be computed?
How should a scheduler submit one run?
Which hyperparameters are meaningful for a domain?
How should Bayesian optimization select the next trial?
```

The core rule is:

```text
A sweep is a deterministic collection of normal pipeline runs.
```

### 1.1 Alignment With `loom.md`

[loom.md](../loom.md) lists sweep orchestration as a generic runtime goal. This
document constrains that goal to deterministic expansion of normal `loom` runs:
config composition, planning, execution, stores, provenance, and resume remain
the same mechanisms used outside sweeps.

---

## 2. Core Position

The sweep package sits above config composition and pipeline execution.

Recommended dependency shape:

```text
config / pipeline specs / planning / execution / run stores
        |
        v
pipeline.sweep
        |
        v
cli.sweep
```

`pipeline.sweep` may use:

```text
loom.config.compose_config
loom.pipeline.PipelineSpec
loom.pipeline.planning
loom.pipeline.execution.PipelineRunner
loom.pipeline.stores
loom.serialization
loom.fingerprints
loom.provenance
```

It should not import:

```text
project packages directly
domain-specific metrics code
CLI modules
optional optimization libraries
SLURM command wrappers directly, except through executor APIs
```

This keeps sweeps generic and lets project code provide metrics and codecs
without becoming part of the sweep core.

---

## 3. Package Boundary

### 3.1 `loom.pipeline.sweep`

Owns sweep specs, expansion, trial records, and sweep orchestration.

Responsibilities:

```text
parse sweep specifications
validate sweep axes and manual trials
expand grid sweeps deterministically
expand manually authored trial lists
create trial specs
assign stable trial IDs
derive trial run directories
create per-trial config overrides
delegate each trial to PipelineRunner
summarize trial status
collect artifact references or simple result metadata
```

### 3.2 `loom.config`

Owns config loading, overlays, CLI overrides, recipe expansion, interpolation,
validation, and object construction.

Sweep responsibilities:

```text
produce additional override lists for trials
call config APIs for each trial or pass override sets to runner APIs
persist sweep/trial config provenance
```

Sweep non-responsibilities:

```text
implement dot-path parsing
implement merge semantics
expand recipes directly
instantiate project objects directly
```

### 3.3 `loom.pipeline.execution`

Owns execution of one pipeline run.

Sweep responsibilities:

```text
construct one RunRequest per trial
call PipelineRunner.run for each selected trial
collect RunResult objects
```

Sweep should not execute stages directly.

### 3.4 `loom.pipeline.stores`

Owns run directory persistence.

Sweep responsibilities:

```text
choose sweep-level directory layout through public APIs or documented paths
record sweep manifest
reference trial run directories
read trial status through run-store APIs
```

Run stores own per-run status, artifacts, fingerprints, logs, and provenance.

### 3.5 `loom.pipeline.executors`

Own execution backends.

Sweep responsibilities:

```text
pass executor choices into each trial run
optionally limit trial concurrency
optionally submit multiple trial runs through executor APIs
```

Sweep should not build SLURM scripts directly.

### 3.6 `loom.cli`

Owns command-line presentation.

CLI can expose:

```text
loom sweep plan
loom sweep run
loom sweep status
loom sweep collect
```

The CLI should call sweep APIs and format results.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
SweepSpec value object
TrialSpec value object
grid sweep expansion
manual/list trial expansion
stable trial IDs
stable trial ordering
trial override generation
sweep manifest document
trial manifest document or trials.csv/json
sweep directory layout
sequential local trial execution through PipelineRunner
plan-only mode
basic status aggregation from run stores
clear sweep-specific errors
```

### 4.2 Should Support Soon

```text
bounded local concurrency
subprocess trial execution
SLURM per-trial submission through executor APIs
result collection from artifact refs
trial filtering and resume
failed-trial rerun
machine-readable sweep status
sweep-level provenance
```

### 4.3 Should Not Support in v0

```text
random search
Bayesian optimization
population-based training
early stopping across trials
conditional search spaces
adaptive trial generation
distributed sweep controller
database-backed sweep state
complex metric query language
domain-specific result aggregation
```

Advanced search strategies can be external tools that generate manual trial
lists or call `loom` Python APIs.

---

## 5. Terminology

### 5.1 Sweep

A sweep is a named collection of trials derived from a base experiment config.

### 5.2 Base Config

The config that all trials start from before trial-specific overrides are
applied.

### 5.3 Axis

An axis is a named dot-path with multiple candidate values.

Example:

```yaml
axes:
  model.hidden_channels: [32, 64]
  optimizer.lr: [0.0001, 0.0003]
```

### 5.4 Grid Sweep

A grid sweep expands the cartesian product of all axes.

For two axes with sizes 2 and 3, the grid has 6 trials.

### 5.5 Manual Trial

A manual trial is an explicitly authored override set.

Example:

```yaml
trials:
  - name: small_fast
    overrides:
      model.hidden_channels: 32
      optimizer.lr: 0.0003
  - name: large_slow
    overrides:
      model.hidden_channels: 128
      optimizer.lr: 0.0001
```

### 5.6 Trial

A trial is one concrete pipeline run generated by the sweep.

It has:

```text
trial ID
trial name, optional
override list
run directory
metadata
status
result summary
```

### 5.7 Sweep Directory

The directory containing sweep-level manifests and trial run directories.

Example:

```text
sweeps/example/
  sweep.yaml
  sweep.json
  trials.json
  trial_0001/
  trial_0002/
```

---

## 6. Guiding Design Principles

### 6.1 Sweeps Are Ordinary Runs

Each trial should be runnable as a normal `loom run` with a deterministic set of
overrides.

This keeps:

```text
resume behavior unchanged
artifact storage unchanged
provenance unchanged
executor behavior unchanged
CLI status inspection unchanged
```

### 6.2 Expansion Must Be Deterministic

The same sweep spec should produce the same ordered trial list.

Deterministic trial order matters for:

```text
stable trial IDs
repeatable run directories
reproducible status summaries
SLURM submission order
tests
```

### 6.3 Keep Sweep Specs Small

Sweep specs should reference a base config rather than duplicating it.

Good:

```yaml
base_config: experiment.yaml
axes:
  optimizer.lr: [0.0001, 0.0003]
```

Avoid:

```text
copying the entire experiment config into every trial
```

### 6.4 Use Config Overrides, Not Custom Merge Logic

Trial expansion should create the same kind of dot-path overrides accepted by
`loom.config`.

The sweep layer should not implement a separate merge language.

### 6.5 Make Trial Identity Explicit

Trial IDs should be stable path-safe strings.

Recommended default:

```text
trial_0001
trial_0002
trial_0003
```

Manual trials may also have human names, but the stable ID remains the primary
directory key.

### 6.6 Do Not Hide Failures

Sweep runs should make individual trial failures visible.

Recommended behavior:

```text
record failed trial
continue or stop according to policy
return non-zero if any required trial failed
```

### 6.7 Keep Result Collection Generic

The generic sweep layer can collect artifact refs and simple plain-data values.

It should not understand domain metrics unless project code exposes them as
plain-data artifacts.

---

## 7. Sweep Spec Shape

### 7.1 Grid Sweep Example

```yaml
name: lr_hidden_seed
base_config: experiment.yaml
mode: grid
run_root: sweeps/lr_hidden_seed

axes:
  model.hidden_channels: [32, 64, 96]
  optimizer.lr: [0.0001, 0.0003]
  run.seed: [1, 2, 3]

metadata:
  purpose: hidden-size learning-rate sweep
```

### 7.2 Manual Sweep Example

```yaml
name: ablations
base_config: experiment.yaml
mode: manual
run_root: sweeps/ablations

trials:
  - name: baseline
    overrides: {}
  - name: no_dropout
    overrides:
      model.dropout: 0.0
  - name: small_model
    overrides:
      model.hidden_channels: 32
      optimizer.lr: 0.0003
```

### 7.3 Common Fields

Recommended fields:

```text
schema_version
name
base_config
mode
run_root
overlays
base_overrides
axes
trials
trial_naming
execution
collection
metadata
```

### 7.4 `base_config`

Path to the base experiment config.

Relative paths should be resolved relative to the sweep spec file unless a
caller provides a different base directory.

### 7.5 `overlays`

Optional overlay files applied to every trial.

Example:

```yaml
overlays:
  - overlays/local.yaml
```

### 7.6 `base_overrides`

Overrides applied to every trial before trial-specific overrides.

Example:

```yaml
base_overrides:
  run.tags: ["sweep", "debug"]
```

### 7.7 `metadata`

Plain-data metadata for the sweep.

`loom` validates shape but does not interpret domain-specific keys.

---

## 8. `SweepSpec`

### 8.1 Purpose

`SweepSpec` is the typed representation of a sweep config.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class SweepSpec:
    schema_version: int
    name: str
    base_config: str
    mode: str
    run_root: str
    overlays: tuple[str, ...] = ()
    base_overrides: Mapping[str, PlainData] = field(default_factory=dict)
    axes: Mapping[str, tuple[PlainData, ...]] = field(default_factory=dict)
    trials: tuple[ManualTrialSpec, ...] = ()
    execution: Mapping[str, PlainData] = field(default_factory=dict)
    collection: Mapping[str, PlainData] = field(default_factory=dict)
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 8.2 Validation

Validate:

```text
name is path-safe or can be normalized
base_config is non-empty
mode is supported
run_root is non-empty
axes are present for grid mode
trials are present for manual mode
axis paths are non-empty strings
axis values are non-empty sequences
trial names are unique when provided
metadata is plain-data compatible
```

### 8.3 Mode Values

V0 modes:

```text
grid
manual
```

Future modes:

```text
random
external
adaptive
```

Do not reserve behavior for future modes beyond clear error messages.

---

## 9. Grid Expansion

### 9.1 Purpose

Grid expansion creates a cartesian product of axis values.

Input:

```yaml
axes:
  a: [1, 2]
  b: [x, y]
```

Output:

```text
trial_0001: a=1, b=x
trial_0002: a=1, b=y
trial_0003: a=2, b=x
trial_0004: a=2, b=y
```

### 9.2 Axis Ordering

Use authored mapping order if the parser preserves it.

If not guaranteed, sort axis names lexicographically and document that policy.

Recommended v0:

```text
preserve authored order
```

YAML mappings preserve order in modern Python parsers. Tests should enforce the
chosen behavior.

### 9.3 Value Ordering

Preserve value list order exactly.

Do not sort values. Users may intentionally order trials from cheap to expensive.

### 9.4 Trial Count Limit

Grid sweeps can grow accidentally.

Recommended option:

```yaml
max_trials: 1000
```

or runner argument:

```text
--max-trials
```

V0 should at least detect and report trial count before execution.

### 9.5 Implementation Helpers

Recommended functions:

```text
expand_grid
cartesian_product_axes
count_grid_trials
```

These functions should be pure and easy to unit test.

---

## 10. Manual Trial Expansion

### 10.1 Purpose

Manual expansion turns explicitly authored trials into `TrialSpec` values.

Manual mode is useful for:

```text
non-cartesian ablations
hand-picked hyperparameters
named baselines
debug configurations
external search tools that generate trial lists
```

### 10.2 Manual Trial Shape

Recommended:

```yaml
trials:
  - name: baseline
    overrides: {}
    metadata:
      group: baseline
  - name: high_lr
    overrides:
      optimizer.lr: 0.001
```

### 10.3 Validation

Validate:

```text
each trial has overrides mapping
trial names are unique when provided
override paths are non-empty strings
override values are plain-data compatible
metadata is plain-data compatible
```

### 10.4 Implementation Helper

Recommended:

```text
expand_manual_trials
```

This should not call `PipelineRunner`; it only returns trial specs.

---

## 11. Trial Specs

### 11.1 Purpose

`TrialSpec` is the immutable description of one generated run.

Representative structure:

```python
@dataclass(frozen=True, slots=True)
class TrialSpec:
    trial_id: str
    index: int
    name: str | None
    run_dir: str
    overrides: tuple[str, ...]
    override_values: Mapping[str, PlainData]
    metadata: Mapping[str, PlainData] = field(default_factory=dict)
```

### 11.2 Override Representation

The config API accepts CLI-style override strings.

The sweep layer may keep both:

```text
override_values:
  structured mapping for inspection and JSON manifests

overrides:
  ordered strings for compose_config
```

Example:

```text
override_values = {"optimizer.lr": 0.0003}
overrides = ("optimizer.lr=0.0003",)
```

Use config helper functions to format/parse override values when available.

### 11.3 Trial ID

Recommended default:

```text
trial_0001
```

The width can be based on trial count:

```text
1..9       -> trial_1 or trial_01
1..9999    -> trial_0001
```

Recommended v0:

```text
always use four digits until trial_9999
```

### 11.4 Trial Name

Manual trials may provide human names.

Grid trials can derive names later, but v0 can leave `name` as `None` or use a
safe compact name.

Do not use long override strings as directory names by default.

### 11.5 Run Directory

Default:

```text
{run_root}/{trial_id}
```

Example:

```text
sweeps/lr_hidden_seed/trial_0001
```

---

## 12. Sweep Manifests

### 12.1 Purpose

Sweep manifests make expansion inspectable and reproducible.

Recommended files:

```text
sweep.json
trials.json
trials.csv, optional human-readable summary
```

### 12.2 `sweep.json`

Recommended shape:

```json
{
  "schema_version": 1,
  "kind": "loom.sweep",
  "name": "lr_hidden_seed",
  "mode": "grid",
  "base_config": "experiment.yaml",
  "run_root": "sweeps/lr_hidden_seed",
  "trial_count": 18,
  "created_at": "2026-05-02T00:00:00Z",
  "metadata": {}
}
```

### 12.3 `trials.json`

Recommended shape:

```json
{
  "schema_version": 1,
  "kind": "loom.sweep_trials",
  "sweep_name": "lr_hidden_seed",
  "trials": [
    {
      "trial_id": "trial_0001",
      "index": 1,
      "name": null,
      "run_dir": "sweeps/lr_hidden_seed/trial_0001",
      "override_values": {
        "model.hidden_channels": 32,
        "optimizer.lr": 0.0001,
        "run.seed": 1
      },
      "metadata": {}
    }
  ]
}
```

### 12.4 `trials.csv`

Optional CSV is useful for quick inspection.

Suggested columns:

```text
trial_id
index
name
run_dir
status
axis/value columns
```

CSV is a view, not the authoritative manifest.

---

## 13. Sweep Directory Layout

Recommended layout:

```text
sweeps/<sweep_name>/
  sweep.yaml
  sweep.json
  trials.json
  trials.csv
  trial_0001/
    run.json
    status.json
    config/
    stages/
    artifacts/
  trial_0002/
    ...
```

### 13.1 Authored Spec Copy

Copy the authored sweep spec into the sweep directory:

```text
sweep.yaml
```

This preserves what the user requested.

### 13.2 Generated Manifests

Generated files:

```text
sweep.json
trials.json
trials.csv
```

These preserve what `loom` expanded.

### 13.3 Trial Run Directories

Each trial directory is a normal run directory.

This lets existing commands work:

```bash
loom status sweeps/example/trial_0001
loom logs sweeps/example/trial_0001 train
```

---

## 14. Sweep Planning

### 14.1 Purpose

Sweep planning expands trials without executing them.

Recommended API:

```python
plan = sweep_runner.plan(sweep_spec)
```

### 14.2 Plan Output

Plan should include:

```text
sweep name
mode
trial count
trial specs
warnings
estimated run directories
existing trial status when run_root exists
```

### 14.3 Existing Sweep Directory

If `run_root` exists:

```text
compare existing trials.json with current expansion
warn or fail if expansion changed
allow --resume to reuse compatible existing trials
```

Do not silently overwrite incompatible sweep manifests.

### 14.4 CLI Output

Example:

```text
Sweep: lr_hidden_seed
Mode: grid
Trials: 18

Trial       Status   Overrides
trial_0001  NEW      model.hidden_channels=32 optimizer.lr=0.0001 run.seed=1
trial_0002  NEW      model.hidden_channels=32 optimizer.lr=0.0001 run.seed=2
```

---

## 15. Sweep Execution

### 15.1 Purpose

Sweep execution runs selected trials by delegating to `PipelineRunner`.

Recommended API:

```python
result = sweep_runner.run(sweep_spec)
```

### 15.2 Sequential V0

V0 should support sequential execution:

```text
for trial in trials:
  compose trial config
  create trial run request
  run PipelineRunner
  record trial result
```

This is simple, testable, and enough for early ablations.

### 15.3 Failure Policy

Recommended options:

```text
stop_on_failure:
  stop after first failed trial

continue_on_failure:
  run remaining trials and return failed sweep result
```

Default:

```text
continue_on_failure for plan/sweep status visibility,
or stop_on_failure for local expensive runs
```

Choose one during implementation and document it. Recommended v0:

```text
continue_on_failure
```

### 15.4 Resume

Sweep resume should reuse normal run resume.

For each trial:

```text
if trial run directory exists and --resume:
  run trial with resume=True
else:
  create new trial run
```

Sweep-level resume should not invent a second reuse mechanism.

### 15.5 Trial Filtering

Future options:

```text
--trial trial_0003
--from-trial trial_0010
--failed-only
--status FAILED
```

V0 can defer filtering unless needed.

---

## 16. Concurrency and Executors

### 16.1 Local Concurrency

Bounded local concurrency can be added after sequential execution.

Important constraints:

```text
each trial has independent run directory
run-store locking prevents duplicate execution
output formatting remains understandable
KeyboardInterrupt handling is clear
```

### 16.2 Subprocess Trials

Subprocess execution can run each trial through normal `loom run` or through the
execution API.

Do not build a separate trial worker protocol if normal run execution works.

### 16.3 SLURM Trials

Two possible models:

```text
each trial submits a whole pipeline run
each trial pipeline internally submits per-stage jobs
```

V0 should prefer:

```text
each trial delegates to existing executor configuration
```

The sweep layer should not generate SBATCH scripts directly.

### 16.4 Controller Mode

A long-running controller that submits trials adaptively is deferred.

It is needed for:

```text
adaptive search
retry logic
large cluster queues
centralized progress tracking
```

It is not required for deterministic grid/manual sweeps.

---

## 17. Status Aggregation

### 17.1 Purpose

Sweep status summarizes many trial run directories.

Recommended API:

```python
status = sweep_runner.status(sweep_dir)
```

### 17.2 Status Inputs

Read:

```text
sweep.json
trials.json
each trial run status through RunStore APIs
optional artifact index summaries
```

### 17.3 Status Output

Should include:

```text
sweep name
trial count
counts by status
failed trials
running trials
latest update time
```

Example:

```text
Sweep: lr_hidden_seed
Trials: 18
SUCCEEDED: 14
FAILED: 2
RUNNING: 1
PENDING: 1
```

### 17.4 No Project Imports

Sweep status should not import project stage code.

It should inspect persisted run-state files through run-store APIs.

---

## 18. Result Collection

### 18.1 Purpose

Result collection gathers selected outputs across trials.

Possible command:

```bash
loom sweep collect SWEEP_DIR --artifact metrics
```

### 18.2 V0 Scope

Start with artifact references, not arbitrary metric parsing.

Collect:

```text
trial ID
trial name
override values
run status
artifact ID
artifact URI
artifact type
checksum
fingerprint
```

### 18.3 Plain Data Artifacts

Later, collection can load plain-data artifacts through registered codecs:

```text
json.v1 metrics artifact
text report summary
```

Loading project artifacts should be explicit because it may import project
codecs.

### 18.4 Output Formats

Recommended:

```text
JSON for complete structured output
CSV for tabular trial summaries
table for human display
```

---

## 19. Provenance

### 19.1 Sweep Provenance

Sweep manifests should record:

```text
sweep spec path
base config path
overlays
base overrides
trial generation mode
trial count
loom version
created_at
command provenance
metadata
```

### 19.2 Trial Provenance

Each trial's normal run provenance should include:

```text
sweep name
trial ID
trial index
trial overrides
trial metadata
```

This can be passed as run metadata when creating the trial run.

### 19.3 Fingerprints

Trial overrides affect resolved configs and therefore stage fingerprints through
normal pipeline planning.

The sweep layer should not compute stage fingerprints directly.

---

## 20. CLI Integration

### 20.1 Commands

Recommended eventual commands:

```bash
loom sweep plan SWEEP_CONFIG
loom sweep run SWEEP_CONFIG
loom sweep status SWEEP_DIR
loom sweep collect SWEEP_DIR --artifact metrics
```

### 20.2 `loom sweep plan`

Should:

```text
load sweep spec
expand trials
show trial count and overrides
detect existing sweep directory compatibility
not execute trials
```

### 20.3 `loom sweep run`

Should:

```text
load sweep spec
expand trials
write sweep manifests
execute or submit trials through SweepRunner
print summary
return non-zero if any required trial failed
```

### 20.4 `loom sweep status`

Should:

```text
read sweep manifests
aggregate trial statuses
not import project code
support --format json
```

### 20.5 `loom sweep collect`

Should:

```text
collect selected artifact refs or plain-data artifacts
include trial override columns
write JSON or CSV when requested
```

---

## 21. Error Model

### 21.1 Error Types

Recommended hierarchy:

```python
class SweepError(PipelineError): ...
class SweepConfigError(SweepError): ...
class SweepExpansionError(SweepError): ...
class SweepManifestError(SweepError): ...
class TrialExecutionError(SweepError): ...
class SweepCollectionError(SweepError): ...
```

If `PipelineError` does not exist yet, start with a local base and move under the
pipeline hierarchy later.

### 21.2 Error Context

Errors should include:

```text
sweep path
field path
trial ID
axis name
run directory
underlying config/run error
```

Example:

```text
Could not expand sweep axis optimizer.lr.
Path: axes.optimizer.lr
Reason: axis values must be a non-empty list.
```

### 21.3 Trial Failures

A failed trial is usually data in the sweep result, not an immediate exception
that erases all other trial results.

Use exceptions for:

```text
cannot parse sweep spec
cannot create sweep directory
cannot create trial run request
internal invariant failure
```

Use trial result statuses for:

```text
trial pipeline failed
trial stage failed
trial was interrupted
```

---

## 22. Testing Strategy

### 22.1 Spec Tests

Test:

```text
valid grid spec parses
valid manual spec parses
missing base_config rejected
unsupported mode rejected
empty axes rejected for grid
empty trials rejected for manual
metadata must be plain data
duplicate manual names rejected
```

### 22.2 Grid Tests

Test:

```text
cartesian product count
axis order preserved
value order preserved
stable trial IDs
override values correct
large trial count warning or limit
```

### 22.3 Manual Tests

Test:

```text
manual trials preserve order
manual names preserved
override mappings converted correctly
metadata preserved
invalid override paths rejected
```

### 22.4 Manifest Tests

Test:

```text
sweep.json shape
trials.json shape
trials.csv optional output
existing compatible manifest accepted for resume
existing incompatible manifest rejected
```

### 22.5 Runner Tests

Use fake `PipelineRunner`.

Test:

```text
sequential trials call runner in order
trial run directories are correct
base overlays and trial overrides are combined
continue_on_failure records failed trial and continues
resume passes resume flag to trial runs
```

### 22.6 Status and Collection Tests

Test:

```text
status aggregates trial run statuses
failed trials listed
status does not import project code
collection returns artifact refs
collection includes override values
JSON and CSV output are stable
```

### 22.7 CLI Tests

Test:

```text
loom sweep plan
loom sweep run with fake runner
loom sweep status
loom sweep collect
JSON output modes
exit codes for failed trials
```

---

## 23. Implementation Plan

### 23.1 Phase 1: Spec and Errors

Create:

```text
src/loom/pipeline/sweep/__init__.py
src/loom/pipeline/sweep/spec.py
src/loom/pipeline/sweep/errors.py
```

Implement:

```text
SweepSpec
ManualTrialSpec
parse_sweep_spec
validate_sweep_spec
sweep-specific errors
```

### 23.2 Phase 2: Trial Structures

Create:

```text
src/loom/pipeline/sweep/trials.py
```

Implement:

```text
TrialSpec
TrialResult
make_trial_id
format_trial_overrides
trial manifest conversion
```

### 23.3 Phase 3: Expansion

Create:

```text
src/loom/pipeline/sweep/grid.py
src/loom/pipeline/sweep/manual.py
```

Implement:

```text
expand_grid
cartesian_product_axes
expand_manual_trials
count_grid_trials
```

### 23.4 Phase 4: Manifests

Implement:

```text
write_sweep_manifest
write_trials_manifest
read_sweep_manifest
read_trials_manifest
compatibility checks
```

Use serialization helpers. Keep atomic writes in a store/helper layer if one
exists.

### 23.5 Phase 5: Runner

Create:

```text
src/loom/pipeline/sweep/runner.py
```

Implement:

```text
SweepRunner.plan
SweepRunner.run
SweepRunner.status
SweepRunner.collect
```

Delegate trial execution to `PipelineRunner`.

### 23.6 Phase 6: CLI

Create:

```text
src/loom/cli/sweep.py
```

Implement:

```text
loom sweep plan
loom sweep run
loom sweep status
loom sweep collect
```

### 23.7 Phase 7: Executor Integration

Add:

```text
bounded local concurrency
subprocess trial execution
SLURM submission through existing executor APIs
```

Only after sequential local sweeps are stable.

---

## 24. Open Questions

### 24.1 Should Sweep Specs Be YAML or Python?

Recommended v0 answer:

```text
YAML, loaded through config/serialization helpers
```

Python APIs can construct `SweepSpec` directly for advanced use.

### 24.2 Should Trial IDs Include Axis Values?

Recommended answer:

```text
no by default
```

Axis values can be long, sensitive, or path-unsafe. Keep IDs compact and store
values in manifests.

### 24.3 Should Grid Axis Order Be Authored or Sorted?

Recommended answer:

```text
preserve authored order
```

If a future parser cannot preserve order, switch to explicit sorted order with a
documented version change.

### 24.4 Should Failed Trials Stop the Sweep?

Recommended v0 answer:

```text
continue_on_failure, with non-zero final result if any trial failed
```

Add `stop_on_failure` as an option if users need it.

### 24.5 Should Sweeps Load Metrics Directly?

Recommended answer:

```text
not by default
```

Collect artifact refs first. Loading plain-data metrics through explicit codecs
can be added later.

### 24.6 Should Random Search Be Built In?

Recommended answer:

```text
not initially
```

External tools can generate manual trial lists. Add built-in random search only
after deterministic sweeps are stable.

---

## 25. Summary

`loom.pipeline.sweep` should be a deterministic expansion and orchestration
layer for many ordinary pipeline runs.

Its main jobs are:

```text
parse sweep specs
expand grid axes
expand manual trials
assign stable trial IDs
write sweep and trial manifests
delegate each trial to PipelineRunner
aggregate trial status
collect artifact refs or simple plain-data results
provide CLI support through loom sweep commands
```

It should not become:

```text
a config merge engine
a stage executor
a scheduler-specific submission layer
a Bayesian optimizer
a domain-specific metrics collector
a database-backed experiment tracker
```

Keeping sweeps as collections of ordinary runs preserves the existing config,
pipeline, artifact, provenance, fingerprint, resume, executor, and run-store
semantics for every trial.

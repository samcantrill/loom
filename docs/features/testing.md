# `loom` Testing Strategy Specification

## 1. Purpose

`loom` must remain useful and testable without any downstream domain package.

The testing strategy exists to make that practical. It defines how tests are
organized, which behaviors each test layer owns, how synthetic pipelines replace
domain workflows, how extension-point contracts are tested, and how local checks
should be run before implementation work is considered complete.

Queue pool-status coverage verifies a single SQLite snapshot, fixed lifecycle
counts, allowlisted evidence redaction, and text/JSON parity. Managed-local
concurrency evidence uses controlled process or SQLite barriers rather than
fixed sleeps when proving capacity release and refill.

The testing strategy should answer:

```text
Which tests belong in unit, package, integration, end-to-end, and contract suites?
How do tests stay domain-neutral?
Which dummy stages, codecs, sources, and stores should exist for tests?
How should import boundaries be tested?
How should CLI behavior be tested?
How should executor and SLURM behavior be tested without requiring a cluster?
Which checks should run locally and in CI?
```

It should not answer:

```text
How each subsystem works internally.
How a domain package validates domain-specific behavior.
How to test large real datasets.
How to run expensive cluster acceptance tests by default.
```

The core rule is:

```text
Test loom as a generic workflow runtime, not as a domain application.
```

### 1.1 Operational lifecycle acceptance

Lifecycle behavior needs a small number of real-process integration tests in
addition to unit and store-contract coverage. These tests use only
fixture-owned processes and deterministic authority time. They prove the
observable sequence, not private helper calls:

```text
hard loss:
  start a real controller and worker -> wait for authoritative RUNNING state
  -> kill both without cleanup -> refuse resume while ownership is live
  -> expire authority time -> resume as attempt 2 -> run downstream

authority loss:
  stop the real local authority while a stage is active -> let the stage finish
  -> reject output commit -> exit nonzero -> publish no artifact index or dependent

artifact corruption:
  complete a branched run -> corrupt one checksummed payload -> public resume
  -> rerun only producer and consumers -> reuse the independent branch
```

Each test should assert several independent oracles together: process exit,
authority status and attempts, event order, output commits, payload bytes,
artifact index, and downstream start. Timing belongs behind markers, lease
expiry controls, or process identity checks; fixed sleeps are not an ownership
or lifecycle oracle.

### 1.2 Alignment With `loom.md`

[loom.md](../loom.md) requires `loom` to remain useful and testable on its own. This
document turns that into a test layout and strategy built around synthetic
pipelines, dummy generic stages/codecs/sources, import-boundary checks, and local
validation commands rather than downstream domain fixtures.

---

## 2. Core Position

Testing cuts across every subsystem.

Recommended dependency shape:

```text
tests/support
  provides dummy generic objects

tests/unit
  validates one module or small package at a time

tests/integration
  validates component collaboration

tests/e2e
  validates complete user-visible workflows

tests/contracts
  validates extension-point behavior and fake backend contracts

tests/package
  validates import and distribution surface, including optional dependency
  boundaries
```

Tests should reinforce the architecture:

```text
loom does not import domain packages
CLI stays thin
serialization does not import I/O
core primitives do not import pipeline
status commands do not import project stage code
plugins do not load automatically on import
```

---

## 3. Package Boundary

### 3.1 `tests/unit`

Owns focused tests for individual modules and packages.

Responsibilities:

```text
fast execution
direct Python imports
small fixtures
temporary directories only where needed
precise failure localization
```

### 3.2 `tests/package`

Owns import and distribution tests.

Responsibilities:

```text
public import stability
cheap imports
py.typed marker
distribution metadata
optional dependency behavior
```

### 3.3 `tests/integration`

Owns cross-component tests below full workflows.

Responsibilities:

```text
config plus pipeline construction
planner plus run store
runner plus artifact store
resume plus fingerprints
executor plus failure persistence
```

### 3.4 `tests/e2e`

Owns user-visible full workflows.

Responsibilities:

```text
synthetic complete pipeline
public Python API workflow path
future CLI run path
status/log/artifact inspection
read-only reliability inspection
resume behavior
failure behavior
```

V1 config-composition e2e coverage uses public Python APIs. Functional CLI e2e
coverage remains future work until CLI behavior exists.

### 3.5 `tests/contracts`

Owns reusable extension-point behavior.

Responsibilities:

```text
Codec contract
DataSource contract
Stage contract
ArtifactStore contract
RunStore contract
Executor contract
Artifact-store backend and payload operation contracts
```

### 3.6 `tests/support`

Owns shared test-only helpers.

Responsibilities:

```text
dummy stages
dummy codecs
temporary project factories
small manifest factories
run directory assertions
fake entry points
fake scheduler clients
```

Support code must remain domain-neutral.

---

## 4. Initial Scope

### 4.1 Must Support in v0

```text
unit test layout mirroring src/loom
package import tests
dummy stages
synthetic pipeline fixtures
contract tests for core extension points
local executor tests
run-store and artifact-store tests
resume/fingerprint tests
import-safe CLI stub tests
import-boundary tests
ruff, pyright, pytest, and build checks
make targets for suite-specific test runs and PR summaries
```

### 4.2 Should Support Soon

```text
CLI golden-output tests
CLI main(argv) tests
subprocess executor tests
stage-worker invocation tests
SLURM fake-command tests
Docker fake-command tests
plugin fake-entry-point tests
sweep runner tests with fake PipelineRunner
failure injection helpers
test markers for slow/integration/e2e/slurm/network/optional dependencies
coverage thresholds for critical packages
```

## Container Executor Testing

Default container executor tests should use fake commands and fake command
runners. Stage 17 Docker validation exercises command construction, selected
executor preflight, CLI `loom run --executor docker`, failure inspection, and
example scripts without a real Docker daemon.

Live Docker acceptance should stay opt-in because it can depend on daemon
availability, image contents, local path parity, registry access, and network
policy. It must not be required by `make validate-pr` unless a future roadmap
stage explicitly changes that validation contract.

### 4.3 Should Not Support by Default

```text
real cluster tests
network service tests
large datasets
real model training
remote cloud storage
heavy optional dependency tests without opt-in markers
domain-specific downstream package tests
```

Those can exist as explicitly marked acceptance suites later.

Stage 16 remote-like artifact coverage stays in this default-safe model. Core
tests use fake object-store and tracking-system handlers to prove payload
operation contracts, bundle materialization evidence, unsupported real-backend
handles, and redaction. They must not import provider SDKs, require credentials,
or perform network operations. Package tests should keep asserting that default
artifact, store, run, preflight, and materialization imports do not load plugins
or optional backend dependencies.

---

## 5. Test Layout

Recommended layout:

```text
tests/
  unit/
    loom/
      test_ids.py
      test_refs.py
      test_records.py
      test_artifacts.py
      test_provenance.py
      test_fingerprints.py
      test_protocols.py
      test_errors.py
      test_timestamps.py

      serialization/
        test_plain.py
        test_dataclasses.py
        test_json.py
        test_schema.py

      io/
        test_uris.py
        sources/
          test_local.py
          test_registry.py
        codecs/
          test_json_codec.py
          test_text_codec.py
          test_bytes_codec.py
          test_registry.py

      config/
        test_load.py
        test_merge.py
        test_overrides.py
        test_compose.py
        test_validation.py
        test_redaction.py
        recipes/
          test_catalog.py
          test_expansion.py
        instantiate/
          test_targets.py
          test_recursive.py
          test_injection.py

      pipeline/
        test_specs.py
        test_stage.py
        test_context.py
        test_status.py
        test_validation.py
        test_selectors.py
        graph/
          test_dag.py
          test_topology.py
          test_bindings.py
        planning/
          test_plan.py
          test_planner.py
          test_resume.py
          test_invalidation.py
        execution/
          test_runner.py
          test_lifecycle.py
          test_atomic.py
          test_logs.py
        executors/
          test_local.py
        stores/
          test_artifact_store.py
          test_run_store.py
          test_indexes.py
          test_local_artifacts.py
          test_local_runs.py
          test_atomic.py

      cli/
        test_import_safe.py
        test_unsupported_stubs.py

  package/
    test_import.py
    test_public_api.py
    test_distribution_metadata.py
    test_typing_marker.py

  integration/
    test_pipeline_parses_config_specs.py
    test_planner_uses_graph_and_stores.py
    test_runner_writes_store_state.py
    test_resume_uses_artifact_fingerprints.py

  e2e/
    test_synthetic_pipeline.py
    test_cli_run_synthetic_pipeline.py

  contracts/
    test_codec_contract.py
    test_source_contract.py
    test_stage_contract.py
    test_artifact_store_contract.py
    test_run_store_contract.py
    test_executor_contract.py

  support/
    factories.py
    stages.py
    codecs.py
    stores.py
    sources.py
    entrypoints.py
    schedulers.py
    assertions.py
```

---

## 6. Unit Tests

### 6.1 Purpose

Unit tests validate behavior owned by one module or package.

They should be:

```text
fast
deterministic
isolated
directly targeted
domain-neutral
```

### 6.2 Mirroring Source Layout

For source-owned behavior, mirror the path below `src/loom` under
`tests/unit/loom`.

Examples:

```text
src/loom/refs.py                         -> tests/unit/loom/test_refs.py
src/loom/serialization/plain.py          -> tests/unit/loom/serialization/test_plain.py
src/loom/io/codecs/json_codec.py         -> tests/unit/loom/io/codecs/test_json_codec.py
src/loom/pipeline/planning/planner.py    -> tests/unit/loom/pipeline/planning/test_planner.py
src/loom/cli/run.py                      -> tests/unit/loom/cli/test_run.py, post-v0
```

### 6.3 Unit Test Boundaries

Unit tests should usually avoid:

```text
full pipeline execution
subprocess CLI execution
network access
real SLURM commands
domain packages
large files
time-sensitive sleeps
```

Use direct APIs and fake collaborators.

---

## 7. Package Tests

### 7.1 Purpose

Package tests validate the distribution and import surface.

Test:

```text
import loom is cheap
public imports are stable
__version__ is available
py.typed is included
distribution metadata is readable
optional extras do not import eagerly
loom import does not trigger plugin discovery
```

### 7.2 Public API Tests

Use only documented public imports:

```python
from loom.refs import ResourceRef
from loom.records import Record
from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
```

Do not make package tests depend on deep internal modules unless testing a
documented deep import.

### 7.3 Import Cost and Side Effects

Test that importing the top-level package does not:

```text
load project code
discover plugins
import optional remote backends
create files
start subprocesses
```

---

## 8. Integration Tests

### 8.1 Purpose

Integration tests combine multiple `loom` components while remaining smaller
than a full user workflow.

Mark them:

```python
pytestmark = pytest.mark.integration
```

or with per-test markers.

### 8.2 Recommended Integration Tests

Examples:

```text
config composition -> target instantiation
pipeline graph validation -> planner output
runner -> local run store -> status files
artifact store -> fingerprints -> resume decisions
executor -> lifecycle hooks -> failure status writes
sweep expansion -> trial run requests
plugin loading -> registry population
event sink plugin loading -> scratch EventSinkRegistry population
```

### 8.3 Boundaries

Integration tests should still avoid:

```text
real domain packages
real cluster submission
network services
large datasets
```

Use dummy stages, temporary directories, fake entry points, and local stores.

---

## 9. End-to-End Tests

### 9.1 Purpose

End-to-end tests validate complete behavior through the same entry points a user
would use.

Mark them:

```python
pytestmark = pytest.mark.e2e
```

### 9.2 Synthetic Pipeline

Use a small domain-neutral pipeline:

```text
WriteNumberStage
AddNumberStage
MultiplyNumberStage
ReportStage

write -> add -> multiply -> report
```

### 9.3 Observable Assertions

An end-to-end test should create an isolated project/run directory, execute the
workflow through the public Python API, and verify:

```text
final artifacts exist
artifact contents are correct
status files are written
provenance is persisted
fingerprints are persisted
resume skips unchanged stages
forced reruns invalidate downstream outputs
failure metadata is written
```

Functional CLI exit checks are post-v0. V0 CLI coverage is limited to
import-safe modules and unsupported-stub failures.

### 9.4 Opt-In Heavy E2E Tests

If future end-to-end tests need:

```text
cluster
network service
remote storage
heavy optional dependency
real Docker
real Apptainer/Singularity
real SIF build
```

mark them explicitly and skip unless the environment opts in.

Stage 18 real container smoke hooks are acceptance tests, not default CI
evidence. The repository provides skipped-by-default tests under
`tests/container_acceptance/` for Docker command availability,
Apptainer/Singularity command availability, and configured Apptainer SIF build.
They require explicit environment variables:

```text
LOOM_RUN_DOCKER_ACCEPTANCE=1
LOOM_RUN_APPTAINER_ACCEPTANCE=1
LOOM_RUN_APPTAINER_BUILD_ACCEPTANCE=1
LOOM_APPTAINER_BUILD_DEFINITION=/path/to/definition.def
```

The existing real SLURM acceptance suite remains under `tests/slurm_acceptance/`
and is enabled with `LOOM_RUN_SLURM_ACCEPTANCE=1` plus a shared
`LOOM_SLURM_ACCEPTANCE_ROOT`. Default `make validate-pr` and
`make test-summary` do not require these runtimes, clusters, registries, or
network access.

---

## 10. Contract Tests

### 10.1 Purpose

Contract tests define reusable behavior for extension points.

They make protocols concrete enough that downstream packages can validate their
own implementations against `loom` expectations.

### 10.2 Initial Contracts

Recommended:

```text
Codec contract
DataSource contract
Stage contract
ArtifactStore contract
RunStore contract
Executor contract
```

### 10.3 Codec Contract

Test:

```text
roundtrip behavior
stable key
clear encode errors
clear decode errors
plain-data metadata handling
```

### 10.4 DataSource Contract

Test:

```text
open existing resource
exists true/false
stat returns plain data
glob/list is deterministic when supported
missing resource error
unsupported operation error
```

### 10.5 Stage Contract

Test:

```text
declared inputs are available
declared outputs are returned or registered
undeclared outputs fail validation
exceptions become failed execution results
metadata is plain-data compatible
```

### 10.6 Store Contracts

Test artifact stores:

```text
save/load/register/list
checksum behavior
missing artifact errors
path safety
```

Test run stores:

```text
run creation
status transitions
stage status read/write
fingerprint read/write
artifact index read/write
corrupt state errors
```

### 10.7 Reusable Helpers

Where useful, expose helper functions that downstream packages can import from a
test-support package or copy.

Do not make runtime `loom` depend on test helpers.

---

## 11. Shared Test Support

### 11.1 Dummy Stages

Required dummy stages:

```text
WriteArtifactStage
ReadArtifactStage
FailingStage
MissingOutputStage
SleepStage
WriteNumberStage
AddNumberStage
MultiplyNumberStage
ReportStage
```

### 11.2 Dummy Codecs

Required dummy codecs:

```text
JSON roundtrip codec
text codec
bytes codec
failing decode codec
failing encode codec
```

### 11.3 Fake Stores and Executors

Useful fakes:

```text
InMemoryRunStore
RecordingArtifactStore
FakeExecutor
FailingExecutor
FakeSlurmCommandRunner
```

### 11.4 Factories

Factories should build:

```text
ResourceRef
ArtifactRef
Record
InMemoryManifest
PipelineSpec
StageSpec
RunRequest
StageExecutionRequest
SweepSpec
```

Factories should keep defaults minimal and explicit.

### 11.5 Assertions

Useful assertion helpers:

```text
assert_run_succeeded
assert_stage_status
assert_artifact_exists
assert_fingerprint_written
assert_provenance_written
assert_no_domain_imports
```

---

## 12. Import Boundary Tests

### 12.1 Purpose

Import boundary tests protect architecture.

They should verify:

```text
core primitives do not import config/pipeline/io
serialization does not import io
io does not import pipeline
config does not import domain packages
pipeline does not import cli
cli is not imported by lower layers
plugins are not discovered on import
status commands do not import project stage code
```

### 12.2 Implementation Options

V0 can use custom tests with `sys.modules` inspection.

Later options:

```text
import-linter
grimp
custom dependency graph script
```

Do not add a new dependency until custom tests become too brittle.

### 12.3 Public Import Tests

Test stable public imports:

```python
from loom.refs import ResourceRef
from loom.records import Record, InMemoryManifest, ManifestView
from loom.artifacts import ArtifactRef
from loom.fingerprints import hash_mapping
from loom.provenance import RunProvenance, StageProvenance
```

---

## 13. CLI Tests

Functional CLI tests are post-v0. V0 should test only import-safe CLI modules
and clear unsupported-stub failures.

### 13.1 Parser Tests

When functional CLI behavior is added, test `main(argv)` directly for:

```text
--help
--version
validate args
plan args
run args
stage run args
status args
repeated --overlay
repeated --set
selector flags
usage errors
```

### 13.2 Command Tests

CLI command tests should assert behavior through:

```text
structured API calls, using fakes
stdout/stderr output
exit codes
files created under temporary run directories
```

Do not assert internal implementation details.

### 13.3 Golden Output Tests

Use small stable snapshots for:

```text
plan table
status table
artifact list table
known error message
```

Normalize:

```text
timestamps
absolute temporary paths
platform-specific path separators
```

### 13.4 CLI E2E

CLI E2E tests are post-v0. When functional CLI behavior is added, at least one
e2e test should call the real console path or `main(argv)` for:

```text
loom run synthetic config
loom status run dir
loom logs failed stage
loom plan --resume
```

---

## 14. Executor Tests

### 14.1 Local Executor

Test:

```text
successful stage
stage exception capture
traceback file writing
stdout/stderr handling when supported
output validation
metadata recording
```

### 14.2 Subprocess Executor

Subprocess executor tests are active in v5 and should remain local,
deterministic, and synthetic. They should not require a scheduler, container
runtime, network, or downstream project.

Test:

```text
command construction
stage worker invocation
exit code interpretation
signal interpretation
result file read
stdout/stderr log paths
missing result file error
invalid result file error
mismatched run_uri/stage/attempt identity
structured-success/process-failure conflict
structured worker failure wrapping
redacted command/process metadata
local/subprocess equivalence for synthetic pipelines
status/log diagnostics compatibility for subprocess failures
reliability policy, transaction, retry, and timeout inspection compatibility
```

Use synthetic stage workers and temporary run directories.

### 14.3 SLURM Executor

SLURM tests should not require a real cluster by default.

Use fake command runners to test:

```text
SBATCH script generation
sbatch command construction
dependency flags
submission manifest
squeue/sacct parsing
cancel command construction
unavailable command errors
partial submission handling
status snapshot recording
cancellation attempt recording
artifact-safe scheduler metadata
```

Real cluster acceptance tests are separately marked:

```python
pytest.mark.slurm
pytest.mark.slow
```

and skipped unless explicitly enabled. The acceptance suite lives under
`tests/slurm_acceptance/` and requires all of:

```text
LOOM_RUN_SLURM_ACCEPTANCE=1
LOOM_SLURM_ACCEPTANCE_ROOT=/shared/filesystem/path
```

Optional environment variables let maintainers adapt to site policy:

```text
LOOM_SLURM_ACCEPTANCE_PARTITION
LOOM_SLURM_ACCEPTANCE_ACCOUNT
LOOM_SLURM_ACCEPTANCE_QOS
LOOM_SLURM_ACCEPTANCE_TIME
LOOM_SLURM_ACCEPTANCE_TIMEOUT
LOOM_SLURM_ACCEPTANCE_POLL
```

Run it explicitly:

```bash
uv run pytest tests/slurm_acceptance -m slurm
```

Default local validation must stay cluster-free and must not submit a real
SLURM job.

---

## 15. Store and Filesystem Tests

### 15.1 Temporary Directories

Use pytest `tmp_path` for all filesystem tests.

Tests should not write outside their temporary directory.

### 15.2 Atomic Write Tests

Test:

```text
successful atomic write
failed write leaves previous file intact
temporary files are cleaned or recoverable
corrupt partial files are detected
```

### 15.3 Post-v0 Locking Tests

V0 does not include a lock manager by default. Add these tests only if
atomic/interruption tests prove a lock is required or after locking is planned.

Test:

```text
lock acquisition
lock release
double acquisition fails
stale lock behavior, if supported
owner metadata
```

Avoid tests that depend on process timing unless necessary.

---

## 16. Markers and Selection

### 16.1 Recommended Markers

```text
unit
integration
e2e
contract
slow
slurm
network
optional_dependency
```

### 16.2 Default Test Run

The default local test target should run:

```text
unit
package
contract
most integration tests
small e2e tests
```

Default should skip:

```text
real SLURM
network
large slow tests
missing optional dependency tests
```

The raw command is:

```bash
uv run pytest tests -m "not slow and not slurm and not network and not optional_dependency"
```

### 16.3 Opt-In Commands

Examples:

```bash
uv run pytest -m slurm
uv run pytest tests/slurm_acceptance -m slurm
uv run pytest -m network
uv run pytest -m "e2e and not slow"
```

---

## 17. Local Checks

### 17.1 Required Checks Before Implementation Commits

Use:

```bash
make validate-pr
```

This is the repository-level gate from `AGENTS.md`. It wraps Ruff, Pyright, the
default Pytest suite, and the package build.

### 17.2 Docs-Only Changes

For docs-only changes, lightweight checks are usually enough:

```text
heading scan
ASCII scan, if the repo uses ASCII docs
link/path sanity
git status review
```

Full Python checks are not necessary for pure documentation edits unless the docs
include generated examples or code that should be validated.

### 17.3 Targeted Development Checks

During implementation, run the narrowest useful test first:

```bash
uv run pytest tests/unit/loom/serialization/test_plain.py
```

Then broaden:

```bash
uv run pytest tests/unit/loom/serialization
uv run pytest tests/integration
uv run pytest
```

Finish with full local checks before commit.

### 17.4 Phase Workflow Timing

Testing is planned and implemented throughout the phase workflow rather than as
a separate late-stage agent handoff.

Phase planning and plan expansion should define the expected test evidence by
suite:

```text
package tests for public import, distribution, or typing-surface changes
unit tests for new or changed module behavior
contract tests for extension points and reusable implementations
integration tests for collaboration across implemented components
e2e tests for complete synthetic user-visible workflows
opt-in tests for slow, SLURM, network, or optional dependency behavior
```

The phase execution plan should state which suites are required, which test paths
are expected, what behavior they must assert, and which suites are explicitly
deferred because the phase does not expose that layer yet.

Phase execution should implement the phase-scoped tests with the code change.
Start with the narrowest useful unit or package tests, then broaden to contract,
integration, or e2e tests only when the phase wires enough behavior together to
make those suites meaningful.

The bounded refinement pass should fix failing validation and missing
phase-scoped coverage. It should not add broad future-phase tests or redesign
the test strategy.

PR preparation should not create new coverage. It should run the suite harness,
capture the resulting summary, and make any unavailable checks explicit in the
PR body.

### 17.5 Make Harness And PR Summary

The Makefile should expose stable suite targets:

```bash
make test
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
make test-all
make test-summary
make validate-pr
```

`make test` runs the default local suite and excludes opt-in heavy tests.
Suite-specific targets run their corresponding `tests/` directory and report
`not present` when a future suite directory has no tests yet. Once tests exist
in a suite, failures must fail the target.

`make test-all` runs all non-external local tests, including tests marked
`slow`, but still excludes `slurm`, `network`, and `optional_dependency`.

`make validate-pr` runs the local PR gate:

```text
ruff
pyright
default pytest suite
config-extra pytest suite
build
```

`make test-summary` writes a Markdown test-suite summary under `build/` for PR
inclusion. The summary should list each suite, command, status, duration, and a
short output tail for the root Loom suites. If any executed suite fails, the
command should still write the summary and then exit non-zero.

---

## 18. CI Strategy

### 18.1 Baseline CI

Run:

```text
ruff
pyright
pytest default suite
build
```

### 18.2 Matrix

Possible matrix dimensions:

```text
Python versions
minimal dependencies
config-extra opt-in suite
dev extras
OS, if Windows support becomes required
```

### 18.3 Optional Jobs

Optional jobs:

```text
SLURM fake-command tests
slow e2e
network tests
coverage
docs link checks
```

Real cluster jobs should not block ordinary PRs unless the project later has a
reliable cluster CI environment.

---

## 19. Data and Fixtures

### 19.1 Small Fixtures Only

Keep committed fixtures small.

Use:

```text
tiny JSON files
small text files
small binary blobs only when necessary
synthetic manifests
```

Avoid:

```text
real datasets
large media files
model checkpoints
private data
domain-specific samples
```

### 19.2 Generated Test Data

Prefer generating data in tests when simple.

Reason:

```text
less fixture churn
clearer test intent
no licensing surprises
```

### 19.3 Snapshot Data

Snapshots are acceptable for stable CLI output and persisted document shapes.

Keep snapshots:

```text
small
normalized
easy to review
```

---

## 20. Failure Injection

### 20.1 Purpose

Robust workflow software needs failure tests.

Test failures for:

```text
stage exceptions
missing outputs
invalid output types
corrupt status files
missing artifacts
checksum mismatch
subprocess non-zero exit, post-v0
SLURM submission failure, post-v0
plugin load failure
codec decode failure
```

### 20.2 Test Helpers

Provide helpers for:

```text
failing stage
failing codec
corrupt run store file
missing artifact ref
fake command failure
```

### 20.3 Assertions

Failure tests should assert:

```text
clear error type
path-aware message
durable failure metadata
non-zero CLI exit code, when applicable
prior successful state is not corrupted
```

---

## 21. Downstream Reuse

### 21.1 Purpose

Downstream packages should be able to reuse some test helpers or contracts for
their own implementations.

Reusable candidates:

```text
codec contract helpers
source contract helpers
stage contract helpers
artifact store contract helpers
run store contract helpers
```

### 21.2 Packaging Test Helpers

Do not expose test helpers from the main runtime API.

Options later:

```text
loom.testing extra
tests/contracts documented copy-paste helpers
separate package, if needed
```

Keep v0 simple: helpers can live under `tests/support` and `tests/contracts`.

---

## 22. Implementation Plan

### 22.1 Phase 1: Test Scaffolding

Create:

```text
tests/unit/loom
tests/package
tests/integration
tests/e2e
tests/contracts
tests/support
```

Add pytest markers in project configuration.

### 22.2 Phase 2: Core and Serialization Tests

Implement:

```text
core model tests
errors tests
timestamps tests
serialization tests
fingerprints tests
```

### 22.3 Phase 3: I/O, Config, and Artifacts

Implement:

```text
URI/source/codec tests
config load/compose/override tests
artifact ref/store tests
run store tests
```

### 22.4 Phase 4: Pipeline and Execution

Implement:

```text
pipeline spec tests
DAG tests
planner/resume tests
runner lifecycle tests
local executor tests
```

### 22.5 Phase 5: E2E and Future CLI

Implement:

```text
import-safe CLI stub tests
synthetic pipeline e2e
resume e2e
failure e2e
```

Functional CLI command coverage is future work. Current e2e coverage should
prefer public Python APIs, including config composition through `compose_config`
or `inspect_config_composition`.

### 22.6 Phase 6: Plugins, Sweeps, SLURM

Implement:

```text
fake entry point tests
sweep expansion and runner tests
fake SLURM command tests
contract tests for extension points
```

---

## 23. Open Questions

### 23.1 Should Contract Tests Be Public API?

Recommended v0 answer:

```text
not as runtime API
```

Keep them in tests. Promote reusable helpers later if downstream packages need
them.

### 23.2 Should CI Enforce Coverage?

Recommended v0 answer:

```text
defer strict coverage thresholds
```

Add coverage once implementation stabilizes. Prioritize meaningful behavior
tests over early percentage targets.

### 23.3 Should Real SLURM Tests Exist?

Recommended answer:

```text
yes eventually, but never in the default suite
```

Fake command tests cover script generation and parsing. Real cluster tests should
be opt-in.

### 23.4 Should E2E Tests Use CLI or Python API?

Recommended answer:

```text
Python API for v0; add CLI e2e after functional CLI behavior exists
```

Use Python API e2e for faster failure localization. CLI e2e should cover
user-visible behavior after the functional CLI is implemented.

### 23.5 Should Tests Use Domain Examples?

Recommended answer:

```text
no for loom core
```

Domain examples belong in downstream packages or separate examples that are not
required for core tests.

---

## 24. Summary

`loom` testing should prove that the package is a domain-neutral, reproducible
workflow runtime with stable extension points.

Its main jobs are:

```text
mirror source modules with fast unit tests
validate public imports and packaging
exercise component collaboration in integration tests
run complete synthetic workflows in e2e tests
provide contract tests for extension points
protect import boundaries
exercise failure and resume behavior
keep optional heavy environments out of the default suite
```

It should not become:

```text
a domain test suite
a real cluster requirement
a large fixture repository
a brittle snapshot-only suite
a substitute for downstream package tests
```

Keeping tests layered, synthetic, and contract-focused lets `loom` evolve without
breaking the core boundary: generic workflow mechanics in `loom`, domain
semantics in project code.

# Tests

Tests are grouped by intent.

```text
tests/
  unit/         source-mirrored tests for code under src/loom
  package/      package import, metadata, public API, and typing-marker tests
  integration/  tests that combine multiple loom components
  e2e/          full behavior tests through public APIs or CLI
  contracts/    reusable extension-point behavior tests
  support/      generic test helpers, fixtures, and dummy implementations
```

Unit tests should mirror `src/loom` below `tests/unit/loom`. For example,
`src/loom/pipeline/planning/planner.py` is tested by
`tests/unit/loom/pipeline/planning/test_planner.py`.

Integration and e2e tests must remain domain-neutral. Use dummy stages, local
temporary directories, and public APIs unless a test explicitly needs CLI
execution.

Use the Makefile harness for suite runs:

```sh
make test
make test-help
make test-package
make test-unit
make test-contract
make test-integration
make test-e2e
make test-unit-summary
make test-summary
make validate-pr
```

Summary targets run the selected suite with JUnit XML and coverage artifacts
under `build/test-summary/`, then write Markdown tables with pass, failure,
error, skip, deselection, duration, and informational coverage totals. Use
`make test-<suite>-summary` for a focused report or `make test-summary` for all
groups.

Contract tests are executable compatibility checks for Loom extension points.
They should cover protocol and behavior expectations for codecs, sources,
stages, executors, stores, recipes, and future plugin-style extension surfaces.
Support modules are not a runnable suite; `tests/support` holds trusted
test-only helpers and synthetic implementations that are validated through the
package, unit, contract, integration, and e2e suites that consume them.

Empty future suite directories are reported as `not present` by suite-specific
targets. Once a suite contains tests, target failures should be treated as phase
blockers unless the phase plan or PR body explicitly justifies the limitation.

## Targeted validation

Use `$loom-targeted-validation` to select by changed behavior, affected contracts,
and consumers. Record the rationale, exact selectors, required environments, and
expansion triggers in existing task notes or the phase card. Keep explicitly
approved checks binding; broader workflow defaults do not remove them.

Use Python 3.12 and locked dependency environments. Direct pytest selections
are supported; the suite harness does not accept arbitrary file/node selectors.
For example, the Git helper's isolated integration contract is:

```sh
uv run --python 3.12 --isolated --locked --group dev pytest \
  tests/integration/tools/test_phase_workflow.py \
  -m 'not slow and not slurm and not network and not optional_dependency'
```

Replace the test path with affected files or node IDs. For selected config-backed
checks, use a separate environment with `--extra config` and the appropriate
markers. Do not exclude `optional_dependency` when that behavior is the selected
obligation. Tests may have build, runtime, or installation prerequisites; inspect
the selected fixtures and assertions. Default/no-extra evidence must come from
the isolated baseline environment, not an environment retaining optional extras.

Use existing `make test-<suite>` targets for affected suites. Broad/unbounded
impact and explicitly approved final gates use `make validate-pr`, which runs
Ruff, Pyright, baseline, config-extra and MCP-extra tests, and distribution builds. Do not
repeat its included checks without new evidence. Run `git diff --check` for the
affected diff. Documentation/skill edits normally need only affected link,
metadata, routing, and diff checks.

Summary targets execute tests with reporting enabled; they do not merely render
existing results. Reuse fresh output in phase/PR evidence when a new report is
unnecessary. If a card explicitly requires `make test-summary`, that remains a
separate obligation until deliberately revised with replacement coverage and
rationale. Stages 40 and 41 retain both approved full commands.

Finish relevant edits before final runs and record the validated revision/tree,
selectors, results, skips/unavailable cases, and subsequent relevant changes.
Subset results never establish full-suite coverage. A required unavailable case
remains a gap requiring correction or explicit risk acceptance. Physical runtime
qualification follows the opt-in hooks below and cannot be inferred from fixtures.
Reuse evidence across handoffs; broaden or repeat only for a concrete failure,
affected consumer, missing assertion, or change invalidating the previous result.

## Opt-in runtime acceptance hooks

Real container and cluster smoke tests are skipped by default. Use them only in
an environment that intentionally provides the selected runtime:

```sh
LOOM_RUN_DOCKER_ACCEPTANCE=1 uv run pytest tests/container_acceptance
LOOM_RUN_APPTAINER_ACCEPTANCE=1 uv run pytest tests/container_acceptance
LOOM_RUN_APPTAINER_TIMEOUT_ACCEPTANCE=1 \
  LOOM_APPTAINER_RESOURCE_IMAGE=/path/to/approved-local.sif \
  LOOM_APPTAINER_COMMAND=singularity \
  uv run pytest tests/container_acceptance/test_apptainer_timeout_lifecycle.py
LOOM_RUN_APPTAINER_BUILD_ACCEPTANCE=1 \
  LOOM_APPTAINER_BUILD_DEFINITION=/path/to/definition.def \
  uv run pytest tests/container_acceptance
LOOM_RUN_SLURM_ACCEPTANCE=1 \
  LOOM_SLURM_ACCEPTANCE_ROOT=/shared/path \
  uv run pytest tests/slurm_acceptance
```

These hooks are marked `slow` and/or `optional_dependency`. They are manual
acceptance evidence and are not required by `make validate-pr` or
`make test-summary`.

## Validation split for optional dependencies

Validation separates three install surfaces:

- `test-no-extra` (default target): run baseline checks without `loom[config]`
  extras in an isolated environment.
- `test-config-extra`: run config-marked package/unit/integration/docs tests with
  `--extra config` in a separate isolated environment, excluding `mcp_extra`.
- `test-mcp-extra`: run tests marked `mcp_extra` with both `--extra mcp` and
  `--extra config` in an isolated locked environment. Mark these tests with
  `optional_dependency` too; defer SDK imports until the selected test/fixture.
  The required lane imports the SDK normally so a missing install fails, rather
  than reporting skipped SDK tests as success.

`make test-summary` includes the MCP-extra row alongside the other suites and
documents the separate dependency rows so reviewers can see executed config
evidence versus default no-extra evidence. Use `make test-mcp-extra-summary`
only when an additional execution/report is required. The summary e2e row runs with
`loom[config]` when the public workflow under test is config-backed.

The timeout acceptance image needs `sh`, `setsid`, and `sleep`; the supplied path
must already exist. Tests use temporary bind-mounted readiness files, fixture-owned
pidfds, and the selected Linux/SingularityCE 3.10.4 or 4.1.1 foreground namespace path.
They exercise direct timeout/startup/interruption, root-first exit, TERM-resistant
descendants, uncertain cleanup, ordinary results, and both managed group owners.
They neither pull/build an image nor request CPU/RAM cgroups or GPUs.

`test_completed_container_recovery.py` additionally requires
`LOOM_APPTAINER_WORKER_PYTHON` naming the image's absolute installed Python path.
It runs a synthetic project with the image's installed Loom worker, then observes
and publishes its result after the original fixture input becomes unavailable.
It does not update a fleet or qualify compatibility with an existing live owner.

## Stage workflow tooling

`tests/integration/tools/test_phase_workflow.py` exercises the repository Git
helper with disposable real repositories, a local bare origin and a fake GitHub
boundary. It covers isolation, reviewed-head delivery, interrupted merges,
leased branch retirement, metadata publication and two phases in one stage
worktree. Run it with `uv run --locked pytest tests/integration/tools/test_phase_workflow.py`.
The existing integration and full validation lanes collect it. It never operates
on real GitHub branches or starts Loom services.

## Installed Fleet checks

`tests/fleet_acceptance/test_self_tests.py` is the explicit installed SIF/GPU
owner. It does not discover hosts, install images, start services or cancel work.
Run without marker exclusions in the locked config/Fleet environment:

```sh
LOOM_RUN_FLEET_ACCEPTANCE=1 \
LOOM_FLEET_ACCEPTANCE_CONFIG=/PRIVATE/disposable-acceptance.json \
uv run --python 3.12 --isolated --locked --group dev --extra config --extra fleet \
  pytest tests/fleet_acceptance/test_self_tests.py
```

For an existing waiting self-test, also set
`LOOM_FLEET_ACCEPTANCE_OPERATION_ID` to its exact printed check ID and select a
new protected evidence `report` path. This continues the retained intent through
the same native API and verifies the installed identity, bytes, UUID and release
oracles again; it creates no replacement request. Both disposable-selection
opt-ins remain required. An unknown ID refuses; a retained failed check stays
failed. Use the explicit Fleet `--retry-of` command only after correcting the
observed failure, then validate that chosen successor ID through this hook.

The owner-protected JSON selection must contain `schema_version: 1`,
`disposable: true`, paths `fleet`, `deployment`, `operator_connection`, `image`,
and a new `report`; explicit `agent_id`, source-relative `config`,
`coordinator_id`, `agent_root_id`, `gpu_uuids` (the explicit nonempty UUID list
matching the selected profile), complete expected native `profile`
descriptor, and `image_sha256`. Paths resolve relative to the selection file.
The selected agent role must declare that Apptainer image. The operator supplies
an existing disposable fleet, immutable SIF containing Loom probes and Torch,
and a real declared GPU. The test compares image bytes and selected identities
before requests, then records native operation/source/profile identity, complete
results, Torch/Python versions and provider-release/owned-work cleanup evidence.
Failure or waiting retains operation IDs; services stay borrowed.

Absent opt-ins are unavailable installed evidence, not qualification. The ordinary
integration owner tests safe refusal and native temporary CPU/storage execution;
mock CUDA checks do not substitute for this installed gate.

The bounded GPU job claims one native device from that declared set. Its exact
observed/claimed UUID is recorded; it does not qualify every GPU in the set.


### Installed managed-service lifetimes

Use `tests/fleet_acceptance/test_managed_services.py` without marker exclusions,
with `LOOM_RUN_FLEET_ACCEPTANCE=1` and a protected
`LOOM_FLEET_ACCEPTANCE_CONFIG`. The selection is JSON with `schema_version: 1`,
`disposable: true`, `kind: managed-services`, and a `cases` mapping. Case keys are
`ssh_disconnect`, `logout`, `resident_agent_restart`, `sif_agent_restart`,
`idle_reboot`, and `in_job_reboot`. An absent selection is unavailable evidence,
not a pass of that case or the full matrix.

Each selected case supplies `fleet`, `agent_id`, `agent_root_id`,
`coordinator_id`, `session_id`, absolute installed `agent_python` and
`coordinator_python`, protected `operator_connection`, a new protected `report`,
and `timeout_seconds` (1..900). Optional `agent_env_file` and
`coordinator_env_file` name the protected role environments. Paths `fleet`,
`operator_connection`, and `report` resolve relative to the selection. The fleet
must explicitly use systemd-user and separate agent/coordinator SSH hosts.
Except for idle reboot, supply `assignment_id` for an already submitted bounded
synthetic native job. Submit it through ordinary native APIs, with enough time
remaining for the selected event and cleanup. Use separate assignments/case
runs, and a disposable supervisor with no unrelated workers. SIF restart also
requires the exact absolute `image` and its `image_sha256`; the actual launch
must use that image. The harness borrows services and waits for bounded work to
settle, proving worker process exit via owned pidfds and an empty worker cgroup.
On failure it retains evidence and native owners for inspection; it terminates
only its own SSH observer.

Actual reboot additionally requires `LOOM_ALLOW_FLEET_REBOOT=1` and the exact
agent SSH alias in top-level `reboot_authorized_hosts`. Never supply these opt-ins
without permission to reboot that host. Tests retain pre/post Linux boot identity,
native root/session identity, interrupted assignment containment and provider
release. Idle and in-job reboot remain separately unavailable without this
permission. SSH logout records whether the site's PAM integration created a
logind session; it cannot claim last-logind-session evidence when none existed.

### Installed runtime upgrades

Run `tests/fleet_acceptance/test_runtime_upgrade.py` without marker exclusions,
using the same locked dev/config/fleet environment and
`LOOM_RUN_FLEET_ACCEPTANCE=1`, with `LOOM_FLEET_ACCEPTANCE_CONFIG` naming a
protected JSON selection. It must contain `schema_version: 1`,
`disposable: true`, `kind: runtime-upgrade`, and `cases` entries `upgrade` and
`interruption`. An absent case is unavailable evidence, never a pass.

Each case supplies `fleet`, `runtime_release`, `deployment`,
`operator_connection`, source-relative `config`, a new `operation_id`,
`roots` (inventory-entry to exact native root-ID map), `source_releases`
(entry to installed descriptor-SHA256 map), a new `report`, and
`timeout_seconds` (1..900). Optional `env_file` selects the protected native role
environment. File paths resolve relative to the selection. Exactly two distinct
SSH hosts are required. Both installed source and target must support the gate
and conditional controls; retain the explicit bridge receipt separately.

The test invokes real CLI subprocesses, replaces only the selected native
services, checks exact before/after identities and releases, and verifies every
required native check and resource acknowledgement/release. The interruption
case terminates only its owned controller/SSH process group after observing the
accepted maintenance gate, then resumes the same operation. Native service
ownership survives. Cases borrow services and retain incomplete receipts on
failure; they never reboot hosts, cancel work or forcibly clear claims. Prepare
separate immutable targets and fresh operation/report identities for successive
cases. Passing this file qualifies the selected same-boot upgrade only.

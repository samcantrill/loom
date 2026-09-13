# Deterministic sweeps

`loom.pipeline.sweep` expands manual or grid specifications into ordered ordinary
runs. Trial identity, parameter values, provider identity, authored spec and
provenance remain in `sweep.json`, `trials.json` and `sweep-spec.json`. Planning
performs no preparation, service startup or execution. `write_sweep_plan` writes
those artifacts and rejects incompatible existing plans.

## Trial specification

A manual specification preserves authored trial order:

```json
{
  "schema_version": 1,
  "mode": "manual",
  "sweep_id": "comparison",
  "run_uri_root": "file:///absolute/protected/runs",
  "trials": [
    {"name": "first", "overrides": {"pipeline.name": "first"}},
    {"name": "second", "overrides": {"pipeline.name": "second"}}
  ]
}
```

For grid expansion, replace `mode` with `grid` and `trials` with a `grid` mapping
from override paths to lists of values. Axis order and value order are authored
order; the rightmost axis varies fastest. Canonical trial IDs are `trial-0001`,
`trial-0002`, and so on. `max_generated_trials` bounds expansion before dispatch.
Provider trial IDs, override expressions and trial metadata remain in the plan;
no metric ranking or automatic scientific selection is performed.

## Run and inspect

```sh
loom sweep plan sweep.json --sweep-dir sweep-state
loom sweep run sweep.json --config pipeline.yaml --deployment deployment.json \
  --sweep-dir sweep-state
loom sweep status sweep-state --deployment deployment.json
loom sweep collect sweep-state
```

Config and overlay paths are relative to the deployment's selected project
source, whose closure must include them. Preparation uses the exact selected
source and preparation profile, including an explicitly configured local policy;
portable preparation remains the default. Stages must be importable project
objects and parameters must be serializable. Each planned trial URI must equal
the selected protected run-store root plus its trial ID. Conflicting roots fail
preparation; the adapter never silently relocates existing experiments.

The run CLI supports ordered `--overlay` and `--set` inputs, then applies the
trial's overrides. Preparation, composition, selectors, reuse, resource and
reliability policies retain their native owners. A failed trial does not prevent
later trials from being selected. A stage's explicit early-stop signal is
reported as `early_stopped` and counts toward successful aggregate completion;
ordinary cancellation remains `cancelled`.

`--no-wait` submits selected trials without waiting for their workers. `--timeout`
bounds each native call. Closing the client does not cancel accepted work.
Interrupting selection leaves later unsent trials unaccepted. Explicit
cancellation uses the native operation reference. Status without a deployment
reads retained observations and available local run projections; supply the same
deployment to refresh operations. Collection reopens the retained native deployment for a read of committed
artifact facts, including reused outputs, without submitting work or requiring a
legacy artifact index. It selects no best trial and reads no artifact payloads.

## Python

```python
from loom.coordinator import RunRequest
from loom.deployment import load_deployment
from loom.queue.preparation import PrepareRunRequest
from loom.pipeline.sweep import plan_sweep_from_file, run_sweep

selection = load_deployment("deployment.json")
plan = plan_sweep_from_file("sweep.json")
template = RunRequest(PrepareRunRequest(
    "template", "template", selection.source, "pipeline.yaml",
    selection.preparation_profile,
    run_options={"selectors": {"only": ["train"]}},
), "template")
summary = run_sweep(plan, request_template=template,
                    deployment="deployment.json", sweep_dir="sweep-state")
```

Templates require native `mode="exact"`; reconciled submissions are rejected
before sweep state is written or work is sent because they derive their target
instead of using the sweep's planned trial URI. Their retry policy is never
silently replaced. Template operation, admission and run-name identifiers are
replaced per trial.
The exact resulting native request is stored under the existing sweep manifest's
`metadata.native_runs` before transmission, with the deployment reference.
Responses retain operation/admission references and separate cleanup evidence.
Replaying the same sweep reuses the exact IDs even if the acceptance response
was lost. Changed invocation intent conflicts; a failed admission is observed
without requesting another attempt. Rewriting a compatible plan preserves these
references. The coordinator owns readiness, placement, workers and finalization.

`observe_sweep(plan, client=client, sweep_dir=...)` refreshes only selected native
operations. `cancel_sweep_trial(sweep_dir, trial_id, client=client)` delegates to
native run cancellation and returns its independent control operation.
`retry_sweep_trial(..., retry_failed_revision=revision, client=client)` durably
retains and submits explicit failed-revision authorization through the native
capability. This is available only for authorities supporting that capability;
ordinary replay and observer reconnect never infer it. Retrying the same revision
uses the native replay contract and does not create another experiment.

The old direct runner, whole-run queue dispatcher, factory callbacks,
`--queue-config` and `--queue-name` inputs have been removed. Use serializable
project configuration and native deployment selection.

The complete synthetic example is
[deterministic-sweep](../../examples/experiments/deterministic-sweep/README.md):

```sh
uv run --extra config python examples/experiments/deterministic-sweep/run_sweep.py
```

Bayesian optimization, domain-specific metrics and a separate sweep scheduler
are outside this module's scope.

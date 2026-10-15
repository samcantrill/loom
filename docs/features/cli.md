# Loom CLI

`loom run CONFIG --deployment PATH` wraps the native run session. Configuration
paths and overlays are relative to the selected preparation source. The
protected deployment owns coordinator connection, installed preparation profile,
permitted local startup and service lifetime. See
[configured startup](../downstream-operations.md#configured-startup-and-ordinary-run)
and [native client operations](coordinator-client.md).

Validation and hypothetical planning use their existing pure library owners.
Status, logs, artifact inspection, run catalogs and bundles are read-only
consumers. Native admission and operation commands control existing services;
closing an observation does not cancel a run. Explicit cancellation reports its
operation separately from eventual worker settlement.

`loom run pipeline.yaml --deployment deployment.yaml --context context.json`
accepts an explicit JSON object with optional `description`, `tags` and `metadata`.
Existing `--tag` invocation values must agree with any duplicate explicit context
tag. Inspect without starting services using
`loom runs context RUN_URI --connection client.yaml --format json`, or select a
local socket with `--endpoint PATH`. The result joins immutable submission intent,
current annotations and native inspection, with bounded submission links and
explicit unavailable evidence. See [context semantics](coordinator-client.md#submission-context).

Edit through the same native owner with
`loom runs annotate RUN_URI --mutation-id review-17 --patch '{"expected_revision":1,"set_tags":{"review":"ready"}}' --endpoint PATH --format json`.
Append an observation using
`loom runs notes RUN_URI --mutation-id note-17 --text 'Evaluation pending' --endpoint PATH --format json`.
Omit `--text` and `--mutation-id` to list notes, optionally with `--limit` (1–50)
and `--cursor`. All three commands also accept `--connection` and
`--expected-coordinator-id`. Mutation IDs are explicit and scoped to the run and
authenticated caller; repeat the same request after an uncertain reply. Conflict
output retains the mutation ID and, for stale patches, the current revision.
See [patch and note semantics](coordinator-client.md#editing-annotations-and-appending-notes).

## Supported command groups

- `validate`, `plan`, `preflight`: inspect configuration, graph and capability
  requirements without executing authored stage code.
- `run`: prepare and execute through the native owner with explicit deployment.
- `status`, `logs`, `artifacts`, `backend`: inspect retained authority and local
  materialization, with truthful unavailable content and bounded log tails.
- `runs`: index, list, compare, export and import retained run evidence.
- `sweep`: deterministic trial admission and collection through native runs.
- `queue daemon-*`, `queue agent-*`, `queue role-check`: explicit native service,
  operation and installed-role controls. Use `--help` for the exact current
  operation arguments; root/profile discovery is not a fallback.
  `queue agent-retire` and `queue daemon-retire` provide
  [native retirement proofs](role-retirement.md), not file deletion.
- `authority`: explicit service lifecycle and historical offline evidence import.
- `plugins`: inspect installed extension descriptors and selected activation.

There is no independent pipeline runner, whole-run queue controller, direct
stage CLI or generated scheduler continuation command. Old whole-run scheduler
status/cancel commands are removed. Inspect current scheduler observations in
native admission detail and request cancellation through the native owner.

## Output and errors

Commands retain their versioned JSON envelopes, explicit exit codes and
structured error context. JSON output goes to stdout; diagnostic text uses
stderr. CLI modules keep library imports lazy. A caller can request paths-only
log evidence when content is unavailable. Explicit selected-authority failures
remain visible and do not trigger fallback to an unrelated store.

The same run and operation IDs reconnect after a lost acceptance response.
Changed payload with the same identity conflicts. Successful observation and
service cleanup are distinct outcomes. The [execution lifecycle](execution.md)
describes cold local, persistent local, connected fleet and mixed deployments,
restart, cancellation and the incompatible-version cutover.

## Retaining Submission Identity And Following Work

```sh
loom run configs/train.yaml --deployment clients/vision.yaml --operation-id fit-42 --detach
loom runs follow --operation-id fit-42 --deployment clients/vision.yaml
loom runs cancel --operation-id fit-42 --deployment clients/vision.yaml --format json
```

If `--operation-id` is omitted, `run` generates it once. After local argument and
source-closure validation, it writes and flushes an `operation reference` to
stderr before service availability or preparation/submission. This reference
contains the chosen ID and selected deployment/connection configuration paths;
it contains no credentials and does not prove admission. The following `observe`
line gives the exact follow command. JSON stdout remains one final
`loom.cli.run.v3` document; capture stderr too when running unattended.

An uncertain acceptance reply reports the original ID, native `unknown` outcome
and follow command. Follow that ID first. An exact replay with the same ID and
intent retains native identity; changed configuration, source, profile, retry or
fresh intent conflicts. Reconnecting never implicitly retries work. Maintenance
refusal preserves `maintenance_in_progress`, `not_applied`, and the maintenance
owner ID; it creates no acceptance receipt.

`runs follow` and `runs cancel` load a protected `loom.deployment` selection and
connect to its existing native owner. They never initialize roots or start
services. A raw `loom.coordinator-client` file is a different format; Python
clients load it with `CoordinatorClient.from_connection_file`.

Follow renders native changes until logical work succeeds, fails, is cancelled,
or is BLOCKED with its native diagnostic state. It keeps publication, resource
release and observer cleanup facts separate; success with pending cleanup stays
success. The observer borrows the coordinator and never stops it. Native waits
are bounded to 25 seconds per request. `--timeout-seconds` accepts positive
finite seconds and bounds the overall observation. Timeout or Ctrl-C/EOF
prints a detach receipt and closes only this connection. Missing IDs report
`not_found`; disconnected services remain explicit errors. There is no automatic
resubmission or cancellation. Follow returns 0 for success or detachment and 5
for native failed/cancelled/BLOCKED logical outcomes. JSON mode uses one final
`loom.cli.runs.follow.v1` document with `operation_id`, `detached` and the latest
native `observation`; progress text goes to stderr.

Cancel first flushes the known resolved target and possible shared-target scope
to stderr, then asks the native owner to cancel. Reconciled submissions may
share a target: cancellation after binding affects that target and its observers.
An unresolved target can bind while the request is in flight, so the scope
message also states this possibility. The receipt retains the native
`cancellation_operation_id`, original operation ID, native control and scope.
Acknowledgement does not prove worker containment or resource release. Observe
that cancellation operation with the existing native operation commands, or
follow the original run; repeat only the same native-supported cancellation
intent after uncertainty. JSON uses `loom.cli.runs.cancel.v1` and keeps the
scope message off stdout. Successful acknowledgement exits 0; control or
connection failures exit 6.

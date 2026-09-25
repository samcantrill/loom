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

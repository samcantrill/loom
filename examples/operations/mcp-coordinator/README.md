# A coordinator workflow from Codex

This example assumes an existing coordinator, qualified worker profiles, and a
client registered using the [MCP guide](../../../docs/features/mcp.md). All names
below are examples to replace with project/user choices. It is a conversation
recipe; copying it does not submit work.

The project authors `pipeline.yaml` and any selected `config/` files on the
coordinator under its allowed `projects` alias. A build/checksum project defines
its own build and checksum stages. A transform/report project instead defines
its transformation and report. Loom receives the same native preparation shape;
it does not invent either project's parameters, targets or resource budget.

1. Ask Codex: "Prepare `example/pipeline.yaml` from the coordinator's `projects`
   root, including `pipeline.yaml` and `config`, using `existing-project`. Use
   shared mode and run name `example-01`. Stop when it is prepared."
   Codex reads `loom_status`, saves the coordinator identity, sends one stable
   `loom_prepare_run` intent and observes its operation. It returns the prepared
   receipt and report evidence without submitting a target.
2. If the project is not on shared storage, request staged mode explicitly.
   Only `source.mode` changes; the selected authored files still originate on
   the coordinator. Loom captures and transfers those finite preparation inputs.
   The eventual target's code/data must already be available to eligible workers.
3. Ask: "Submit that prepared receipt as queue item `execute-example-01`, then
   monitor it to completion." Codex sends `loom_submit_run`, retains the admission
   ID and uses bounded `loom_wait_for_change` observations with current revisions.
   Admission is not completion. A TIMEOUT ends one observation window and the
   authorized monitoring can continue. Preparation on B can execute on compatible C.
4. After closing and reopening Codex, provide the saved coordinator and operation
   or job IDs. Codex passes `expected_coordinator_id` and retrieves the original
   operation or job. It does not fabricate a replacement admission. On a lost
   mutation reply, the same IDs reconcile whether the original request applied.
5. Ask a one-off status question to get one update. Ask for diagnosis to inspect
   native stage/preflight evidence. Complete inline checks can be read directly;
   an omitted large preflight remains at `report_ref` and requires existing
   authorized artifact tooling. A report reference alone is not downloaded evidence.
6. If desired, explicitly ask to cancel the job. Codex uses `loom_cancel_job` and
   observes the native outcome. To stop preparation instead, use its operation ID
   with `loom_cancel_preparation`. EOF, a timeout and a diagnosis do not cancel work.

"Prepare and run" in one request covers both steps without another approval.
Specify the existing profile and intended observation scope. Preparation currently
requires embedded authority and cannot use a SLURM preparation profile. Installing
the optional client does not modify worker environments.

The automated tests use disposable loopback daemons and synthetic project stages.
They establish native/MCP behavior; live Codex and physical NAS deployment trials
remain separately reported acceptance evidence.

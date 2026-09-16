# Phase 1: Installed Node Contracts

## Metadata

- Status: in_progress; U1 implementation and local validation passed; independent review pending.
- Branch: `agent/stage-92-p1-installed-node-contracts`.
- Base: `c8f23852af2018109c318d17d03186ba9e49893f`.
- PR title: `Stage 92 Native Project Contracts And Result Resolution - Phase 1: Installed Node Contracts`.
- Target: develop. Paths and coordination branch: [manifest](../implementation-plan.md#execution-context).
- Acceptance owner: approved native contract linked by the manifest, sections
  Preparation Protocol, Delivery Packages And Source Ownership (U1), and Example
  And Validation Contract (U1 rows and Genericity Fixture And Acceptance).

## Boundary And Fixed Behavior

Implement protected processor v3 without changing v1/v2. Accept exact captured
node coverage, optional semantic keys and opaque finite payloads while preserving
the submitted composition. Create and validate native per-node envelopes in
the existing preparation report. Persist only its native committed ArtifactRef
in typed prepared-run metadata. Forward exactly the selected node's validated
contract through worker request to context, without application config injection,
opaque location rewriting or arbitrary metadata forwarding.

Provide the exact native execution-binding context from admitted producer/attempt/
installation/storage authority. A machine-local supported binding names a durable
agent-visible state root; unavailable remote roots remain null. Do not infer a
path from resident `loom-agent:` run URIs or introduce checkpoint semantics.
Reject reserved metadata overrides at the actual public admission boundaries.

Preserve v3 whole-target verify_candidate, running observation, completed target
reuse and one-observed-failure retry before U2 exists. Candidate descriptors
project validated node contracts from the retained original preparation report.
Normal no-processor stages receive no attachment. Null keys remain valid opt-out
records; U1 does not implement cross-target result lookup.

## Source And Ownership

Primary current owners are `src/loom/preparation.py`, `queue/preparation.py`,
`queue/_preparation_operations.py`, prepared-run models/stores, worker request
models/context construction, coordinator assignments and resident remote-stage
execution. Extend adjacent native admission/report/retention consumers only when
necessary to carry this same contract end to end. Document at existing installed
preparation/queue extension-point owners and add the generic fixture under
`tests/support`.

Current registration only admits versions 1/2; reconciliation and its verification
request hardcode version 2. The wrapper currently injects scientific evidence and
single-stage recovery configuration. Isolate that legacy path. Worker context
currently reconstructs factory/runtime metadata and drops project attachments.
Typed prepared metadata already has a safety boundary; do not embed opaque
payloads there or weaken that validator. Reuse the existing native ArtifactRef
and committed preparation report rather than adding a parallel evidence artifact.

## Named Startup Source Question

Trace the existing authoritative route from admitted run/attempt and protected
machine-local storage to the resident worker. Identify where the worker request
can obtain the durable run-state root and original run/node/attempt/environment
identity without sending a coordinator-private path or trusting project data.
Return concrete producer/codec/consumer paths and selected existing tests; this
is source clarification under the accepted execution-binding contract, not a new
public API decision. Read-only architectural assistance may answer this question.

Source clarification completed: `local_daemon_execution.py` builds requests from
authoritative stage-work run URI, node and attempt; `_managed_local.py` joins
that request, protected local placement, LocalRunStore and launch profile before
`_ResidentAssignmentBundle` serialization. The bundle and workspace currently
drop original run identity and reconstruct `loom-agent:` request URIs. The
binding must survive both explicit projections. Use the admitted native run name
as origin_run_id within the retained authority/store, validated through the
existing native run-name/containment owner. Never use the assignment ID instead.

`ResidentProfileDescriptor.environment_fingerprint` supplies the environment.
Host-local execution can use its authorized contained run directory. For a
container, derive visibility from the protected installed container mounts (and
their read/write mode and source/target mapping); a profile match alone is not
proof of mount visibility. `_container_worker.build_container_worker` owns the
effective mount construction. Return null where no authorized writable mapping
exists, rather than relying on implicit home/host mounts. No new profile field
or coordinator-private remote root is required by this contract.

The bounded read-only architecture pass is complete; manager verified the
container-mount owner and the selected current tests. No public contract change
or additional plan review is required for these source-backed wiring choices.

## Implementation And Validation

1. Extend exact protected v3 registration/request/result/report codecs, keeping
   old wire versions readable and separating legacy mutation rules.
2. Build checked envelopes and bind the committed report reference at native
   publication. Retain and reload it through existing prepared-run/ArtifactRef
   owners, including whole-target candidate capture and retry.
3. Extend native assignment/request/context paths with authenticated node
   selection and execution binding; validate each actual trust boundary before
   constructing an action. Keep opaque payload and application config distinct.
4. Add the installed generate_text/count_lines fixture and meaningful regressions
   for report reload, exact one-node transport, strict app config, location-like
   payload preservation, null-key/no-processor behavior, and reachable override,
   altered composition, wrong binding and unsupported version rejection.
5. Prove v3 whole-target success resubmission, already-owned observation and
   failed-run retry on the actual native path. Preserve v1/v2 consumers.
6. Document protocol, metadata ownership, state-root availability and failure
   behavior; collect final validation and independent actual-head review.

Initial selected owners: `tests/unit/loom/queue/test_preparation.py`,
`tests/integration/queue/test_preparation_operations.py`,
`tests/unit/loom/pipeline/execution/test_stage_worker.py`, current prepared-run
store tests, `tests/integration/queue/test_reconciled_runs.py`, and existing
resident/shared publication tests affected by request transport. Add a focused
native installed-project integration file when needed; reuse current harnesses.
Include `tests/unit/loom/queue/test_remote_stage_execution.py` and
`test_agent_process_supervisor.py` for original/local/remote binding, durable
grant and container launch retention. The existing local graph and installed
project recovery cases in `test_preparation_operations.py` cover admission
through execution. Assert writable container mapping and null when unavailable.

Use Python 3.12 locked baseline/config-extra environments per `tests/README.md`.
Direct selection uses `uv run --python 3.12 --isolated --locked --group dev
--extra config pytest <selected paths>` for the config-backed native journey.
Final gate: `make validate-pr` and `git diff --check`; retain reports and skipped
case dispositions. Expand selectors for actual codec/admission consumers or
new failures. Do not claim physical SIF/fleet/SLURM qualification from local tests.

## Execution Handoff And Record

Implementation covers the native v3 vertical path, including registration,
preparation input/report envelope 7, unchanged captured composition, exact node
coverage and opaque finite data, committed report references, per-node worker
transport, explicit context projection and authoritative execution binding.
V1/v2 wire and legacy injection remain separate. Whole-target verification uses
the selected processor version and projects the original report's attachments.

Changed owners: preparation and protected codecs; native prepared-run, local-run
and SQLite admission metadata; stage-attempt/request/context construction;
managed publication/runtime intent and local/remote/Slurm delivery; installed
container mount projection. Private shared helpers live in
`pipeline/_project_contracts.py` and `queue/_execution_binding.py`. Native runtime
record version 4 binds the typed report-reference digest for v3 runs: removing or
replacing that reference cannot silently become an ordinary no-processor run.
Earlier runtime record version 3 remains unchanged. The worker's private capture
digest is only a decoder witness; admitted report selection and native assignment
authority remain the authorization owners.

The standard-library installed text fixture has strict ordinary configurations,
two distinct payloads, a location-like opaque value and a null-key option. Its
actual resident workers produce `alpha\nbeta\n` and `2`, inspect their own native
identity/root and exercise one observed failed-attempt retry. Native integration
also covers retained-report reload, original candidate projection, completed reuse,
running observation and removal/alteration rejection. Unit additions cover finite
payload/version/registration boundaries, pre-construction worker binding,
reserved admission overrides and protected writable/read-only/unavailable
container state-root mapping. Existing preparation, worker, resident transport,
prepared-store, authority and reconciliation suites preserve legacy behavior.

Validation selection follows the approved cross-boundary impact: report codecs,
metadata safety, native admission, request replay and resident publication affect
multiple public/durable consumers. Focused new-path and affected tests are diagnostic
checks; the required stable-tree final gate is `make validate-pr` plus
`git diff --check`. Expand only for a concrete gate failure or affected consumer.
Final gates passed against implementation commit
`fd97d00bbeb16ffd494ff66209b3ed793d183086`, Git tree
`f431a4bcd507ac0b70948aa7228199de5080c272`. The only subsequent tracked change is
this completion receipt; `git diff --check` also passed on that prose update.

- `make validate-pr`: exit 0. Ruff passed; Pyright reported 0 errors/warnings.
  Locked Python 3.12.3 baseline: 3024 passed, 2 skipped, 331 deselected.
  Config-extra: 285 passed, 15 skipped, 3074 deselected. MCP-extra: 44 passed,
  3313 deselected. Source distribution and wheel both built successfully.
- The final config-extra lane executed all four installed-node integration cases,
  the existing 61 preparation-operation cases and 17 reconciliation cases. The
  baseline lane covered the selected request/context, prepared-run/store,
  authority, resident transport, supervisor and Slurm-delivery owners.
- Focused native integration command:
  `uv run --python 3.12 --isolated --locked --group dev --extra config pytest tests/integration/queue/test_installed_node_contracts.py -xq`:
  4 passed (104.23s); the final full gate subsequently reconfirmed those cases.
- Skip dispositions: two existing unmarked queue CLI journey tests require
  `python-dotenv`, absent from the isolated baseline. Fifteen config-extra skips
  are the ten opt-in Apptainer timeout cases and five opt-in real-container
  smoke/build/resource cases. None of the four U1 integration cases was skipped.
  These pre-existing optional/physical omissions are not U1 acceptance gaps.
- Retained local evidence:
  `build/validation/installed-node-contracts/validate-pr.log` and
  `build/validation/installed-node-contracts/native-integration.log`.
  No extra summary rerun was needed. No implementation blocker remains.
Physical SIF/fleet/Slurm qualification is not claimed by these local fixtures.

Manager retains manifest, cross-repository authorization, PR/delivery and independent
review ownership. Independent phase review and merge remain pending.

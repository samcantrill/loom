# Current-contract cutover execution

Approved scope: one current API and format at each boundary, without migration,
compatibility aliases, historical readers or conversion commands. Preserve
scientific/project evidence ownership, current recovery, containment, integrity
and current fleet lifecycle. The cross-repository checklist is maintained in
rphys `docs/fleet-context-and-idle-integration-plan.md`, under
“Current-contract cutover implementation”. This file records Loom's actual
implementation evidence; it is not another planning or approval packet.

Initial base: `25cb93c853da0e58646ff405be081b237f5b5147`. Isolated worktree
`../loom-worktrees/current-contract-cutover`. The first branch
`refactor/current-contract-cutover` merged through PR #408 as
`0d860c47d30e8bfbe01023f3fc6260b91ba60e85`; its merged tree matches the reviewed
head. The authority slice `refactor/current-authority-formats` merged through #409 as
`7cd73071cadcf6d11f6d3c9ff7cec963f15c16f3`. Its tree matches reviewed source plus
evidence notes at `097a793f`. The next branch `refactor/current-coordinator-formats`
starts from that exact merge. No active installation is modified by local
tests. Current-format bytes remain unchanged unless a later row changes shape.

## Persistence slice

| Producer → consumer | Contract / change | Evidence status |
| --- | --- | --- |
| Current record writers → `serialization.load_versioned_document` | Exact owner-declared version, strict integer and fields; removed `DocumentMigration`, export, argument and conversion loop | merged #408 |
| Supervisor initialization/launch → reopen and retained role guard | Journal 6 and launch 2 only; removed schema 2–5 upgrades/schema-less launches; current DDL retained; read-only refusal before owner contact or repair | merged #408 |
| Coordinator/agent roots → service startup | Current 19/12 only, remove offline schema upgrade and older reconstruction | merged #410 |
| Authority/coordination → current stores and inspection | Current 11, complete fresh DDL, no automatic upgrades; preserve WAL-aware inspection | merged #409 |
| Authority-service repository → admission/read/write | Repository 12; remove v3–11 upgrade functions and audit-table conversion; fresh DDL and strict existing-root checks | merged #409 |

Discovery before edits: `DocumentMigration` and `migrations=` have no production
callers; only schema helper tests pass conversions. Current callers include
manifest, queue record, status, lock, resource, submitted, execution, prepared,
deferred-finalization, Docker and Slurm models. Their current bytes and domain
error wrapping remain unchanged. `ResidentWorkerLaunch` production callers
already emit 2; only tests request schema-less output. Supervisor journal upgrades
ran during `_open`; the stopped-role replacement guard also admitted v5. Both
now refuse old state. Existing current containment/exit/rejection/reboot and
temporary-cleanup assertions remain; migration-success tests are removed.

Selected validation (locked Python 3.12):

- Schema helper and affected model round trips/refusals: unit schema, records,
  status, execution models, prepared run, runtime resources, locks, submitted,
  deferred finalization, queue models, Docker commands, Slurm options/manifest/
  commands, and integration Slurm live models.
- Supervisor: unit `test_agent_process_supervisor.py` and
  `test_temporary_storage.py`, integration `test_reboot_recovery.py`; current
  receipt reload, exact replay, fencing, containment, successful exit, durable
  rejection and restart cleanup. Retired v2–5 journal fixtures assert identical
  files after refusal; schema-less launch refusal retains current resource-control
  digest assertions.
- Fleet consumer: `test_service_lifecycle.py::test_quiesced_migration_preserves_native_identity_and_refuses_live_owner`
  in config/fleet environment. Current schema retains owner and clean cut;
  predecessor schema is refused unchanged. Historical backend migration itself
  remains subject to the fleet slice inventory.
- Static checks: changed-file Ruff, affected type checks, diff check; imports
  and package API checks for removed exports. Collection precedes execution.

Expand only for a changed/reached consumer, failure, missing assertion or
fixture/dependency/configuration change. These selections do not qualify a
deployed runtime or rphys paired pin. Delivery status is recorded in the PR;
all later boundaries below remain outstanding.

Initial checks: 270 collected; execution 269 passed, one retired-v3 reboot fixture
failed because reopen now correctly refuses it. Its obsolete success branch is
removed; current host/root boot refusals remain. Config/fleet current/old guard
and package import checks: 5 passed. Ruff and affected Pyright: passed.

Independent review identified two bounded corrections: preserve current recovery
from a hot SQLite rollback journal, and reject old process-free roots before
creating `service.lock`. Read-only admission now recovers an abandoned journal
in a temporary private copy when SQLite reports `SQLITE_READONLY_ROLLBACK`;
it rejects changing snapshots and old schemas without touching originals. Startup
repeats validation under its owner lock, then ordinary current-state recovery
continues. This is SQLite transaction recovery, not schema conversion. Focused
real interrupted-write/current recovery, hot-old-root byte preservation,
service-entrypoint refusal and host/root checks: 9 passed, included in the final
affected selection below.

Final reconciliation (2026-10-16): 277 distinct selected cases pass, no required
skips, failures or errors remain in this delivery. This is a bounded selection,
not full-repository or deployed-runtime qualification.

| Scope | Tested state and receipt | Result / reuse |
| --- | --- | --- |
| Schema helper and model consumers | Base above + source/test diff SHA-256 `425a8e702067adc82133f53c7e4583d4d89a25c48a42189f92f350a86b56beb8`; `build/current-contract-cutover/schema-supervisor.xml` | 194 applicable passes; exclude its supervisor population, including the failed removed v3 success case |
| Final supervisor/temp/reboot | Same base + source/test diff SHA-256 `18cbe324e8f009ca099ac39cb34aeacf8b50762b6957e305ae5e59aa6b69652e`; `build/current-contract-cutover/supervisor-final.xml` | 78 passed, 106.98 s |
| Final fleet guard/import consumers | Same final state; `build/current-contract-cutover/fleet-imports-final.xml` | 5 passed, 3.96 s |
| Static checks | Same final state | Changed-file Ruff passed; affected Pyright 0 errors/warnings; diff check passed |
| Independent actual-diff review | Initial review plus one bounded correction confirmation | Both recovery/refusal findings resolved; no remaining blocker in this delivery |

Reused 194-case scope: subsequent runtime differences are confined to private
supervisor inspection/startup and its tests; document loading and the record
consumers, their fixtures, dependencies (`uv.lock`), configuration and scientific
behavior are unchanged. The final supervisor/fleet rechecks cover the changed
consumers. Later edits to these notes only record evidence. No broad reference,
distributed-training, STMap or scaling workload is claimed by these receipts.

## Remaining Loom boundaries

### Authority storage

Discovery on the #408 merge identifies three reached owners:
`pipeline/stores/sqlite_authority.py` (current 11),
`pipeline/stores/sqlite_coordination.py` (current 11), and
`authority/_repository.py` (current 12). Implemented current-only admission and
complete fresh creation for all three; local checks and independent review passed.

- Removed embedded authority read/write migrations, private retained-v10 upgrade,
  coordination v1 migration, repository v3–11 upgrades and audit-table repair.
  Fresh DDL already contains current columns and per-run audit primary keys.
- Removed the service repository constructor's historical version selector; its
  only override consumer was an older-schema rejection test.
- Existing roots undergo read-only, WAL-aware admission before writable open or
  journal-mode changes. Missing metadata or tables never select fresh creation.
  One shared private SQLite inspector retains the established supervisor hot
  rollback-journal copy recovery, with each owner's previous lock timeout. WAL
  inspection uses a stable private copy of the main database and committed WAL,
  because even SQLite mode=ro can create sidecars and alter shared-memory read
  marks. Concurrent changes retry within that timeout; snapshots never ignore
  WAL frames. This adds temporary copy I/O for WAL inspection; deployment and
  scaling qualification remain separate obligations for downstream adoption.
  Current writers revalidate within their transaction. Retained checkpoint-only
  memory inspection remains read-only and now also requires schema 11.
- Authority start/restart preflight precedes lifecycle locks and process effects;
  locked start repeats admission. Current service-generation preservation,
  restart, transactional recovery and containment remain required.

Selected coverage uses locked Python 3.12. Collection precedes execution. Exact
baseline selectors (exclude `optional_dependency`, covered separately below):

```text
tests/unit/loom/pipeline/stores/test_sqlite_authority.py
tests/unit/loom/pipeline/stores/test_sqlite_coordination.py
tests/unit/loom/pipeline/stores/test_authoritative_run_timing.py
tests/unit/loom/authority/test_supervisor.py
tests/integration/authority/test_repository.py
tests/integration/authority/test_repository_run_lifecycle.py
tests/integration/authority/test_repository_stage_lifecycle.py
tests/integration/authority/test_run_annotations.py
tests/integration/authority/test_action_result_binding.py
tests/integration/authority/test_action_producer_cancellation.py
tests/integration/authority/test_mutation_api.py
tests/integration/authority/test_coordinator_authority_api.py
tests/integration/authority/test_supervisor_lifecycle.py
tests/integration/pipeline/test_sqlite_authority_backend.py
tests/integration/pipeline/test_service_authority_backend.py
tests/integration/pipeline/test_workspace_coordination.py
tests/contracts/test_authority_store_contract.py
tests/contracts/test_authority_repository_contract.py
tests/contracts/test_run_store_authority_contract.py
tests/contracts/test_workspace_coordination_contract.py
tests/contracts/test_managed_authority_contract.py
tests/contracts/test_attempt_input_lineage_contract.py
tests/contracts/test_run_context_contract.py
tests/unit/loom/queue/test_agent_process_supervisor.py::test_retired_supervisor_journal_is_rejected_unchanged
tests/unit/loom/queue/test_agent_process_supervisor.py::test_interrupted_write_recovers_only_current_supervisor
tests/unit/loom/queue/test_agent_process_supervisor.py::test_service_start_refuses_retired_process_free_root_without_creating_lock
```

The config-extra environment additionally selects
`tests/integration/authority/test_coordinator_authority_api.py::test_selected_authority_publisher_reconciles_unknown_reply`.
These cover current commits, lineage, annotations, preparation grants,
lease/cancellation fencing, timing, output replacement, concurrent snapshots,
WAL reads, retained inspection and current service start/restart/stop. Old-schema
and incomplete-current fixtures assert refusal without file changes. The three
supervisor selectors recheck the moved inspection helper's actual interrupted
write and before-lock behavior. Changed-file Ruff, affected Pyright and diff
checks complete the local gate. Expand for a newly reached consumer, failure or
missing assertion. Existing serialization/model evidence remains applicable:
its source, dependencies, fixtures and configuration are unchanged. No broad
reference, distributed-training or physical fleet rerun is claimed or required
by this isolated storage delivery; paired downstream qualification remains open.

Initial authority execution: 258 baseline cases passed, six failed; the separate
config selection passed both cases. Four failures exposed WAL sidecar mutation
during rejected admission; stable private WAL snapshots address that boundary.
Two tests still required lineage migration; their retired fixtures now assert
unchanged refusal, while current lineage/acknowledgement/retry assertions remain.
Added live-WAL cases prove both latest committed state and schema rejection come
from the WAL without changing the source. Because this correction affects shared
inspection, rerun the full selected authority population and both config cases,
not unrelated runtime/scientific suites.

Final authority validation (2026-10-16), source/test head
`837209c7476f7b0943986e91d9b052ce749d7115` on the #408 merge:

| Scope | Receipt | Result |
| --- | --- | --- |
| Baseline selectors above | `build/current-contract-cutover/authority-final.xml` | 266 passed, 36.77 s; two config cases selected separately |
| Config preparation/reconciliation | `build/current-contract-cutover/authority-config-final.xml` | 2 passed, 6.40 s |
| Static checks | `authority-ruff-final.log`, `authority-types-final.log` in the same receipt directory | Ruff passed; affected Pyright 0 errors/warnings; diff check passed |

All 268 selected cases pass; no required skip, failure or error remains. The
pre-commit source/test diff fingerprint (including the new helper) is
`33b4ef6807f1a7224e17d7fe23ab45cf9d10705e8c6b3474f7d47a5fa8aa6567`.
Evidence-note changes after that head do not change runtime source, dependencies,
configuration or fixtures. The earlier serialization/model results are reused as
explained above; supervisor extraction is freshly covered by its exact selectors.
Independent review of base `0d860c47` through PR #409 head `bcd00c56` passed
with no accepted-contract blocker. It verified that changes after tested source
head `837209c7` were documentation only. Review retained the documented WAL-copy
temporary-space/I/O and sustained-churn timeout risks for downstream scaling
qualification; fresh service and coordination stores use rollback journals.
Subsequent edits to this receipt only record that review. PR #409 is remotely merged; base develop, final head and matching merged tree
were verified before the next branch started.

Next coordinator census: `_coordinator_upgrade.py` and `daemon-upgrade` have
live consumers in fleet `_upgrade_host.py` and `_adoption_host.py`, as well as
preparation/reconciliation tests. Removal must update current fleet upgrade and
separately delete predecessor adoption; deleting the CLI alone would strand
current runtime replacement. Coordinator `_open_root` accepts a historical
schema selector and reconstructs earlier preparation layouts; agent session
initialization also retains inline-delivery reconstruction. Inspect those
producer/consumer contracts before changing them. No coordinator source changes
are part of this authority delivery.

Current coordinator transport and mandatory control waiting; event v2 APIs;
runtime narrow-service adoption and aggregate removal; unified preparation
context and processor v3; historical offline/import/annotation/lineage/Slurm
projections; fleet predecessor adoption and schema-upgrade CLI removal. Each
requires producer/consumer and dynamic-reference inventory before modification.
No row can be closed solely by assigning it to another stage.


### Coordinator, agent and fleet consumer reconciliation

Base `7cd73071cadcf6d11f6d3c9ff7cec963f15c16f3`. Discovery
finds the following coupled owners, beyond the earlier coordinator upgrade CLI:

| Boundary | Existing producer/consumer and required disposition |
| --- | --- |
| Coordinator 19 / agent 12 roots | `local_daemon._open_root` has a historical selector and earlier-shape reconstruction; remove the selector, old preparation flags and offline upgrader. Preserve full current initialization and pre-owner-lock refusal. |
| Assignment delivery schema | `LocalDaemon.start` and `_RemoteAgentJournal` add `reference_json` on reopen; current `initialize_agent_session_schema` already creates it, while `validate_agent_session_schema` omits it. Require the complete current columns and remove repairs/backfill. Inspect nullable current inline/reference semantics before tightening row admission. |
| Agent retained poll/delivery | `_agent_session_journal` backfills missing inline request evidence; protocol/journal also recover legacy unconfirmed fences and absent sequence predecessors. These reach `agent_session_transport` restart barriers. Remove only historical construction/recovery after checking current lost-reply, rejection and restart producers; preserve exact request/digest/containment proofs. |
| Candidate runtime probe | `operations.probe_upgrade_compatibility` admits coordinator 12/15–18 and emits migration-direction fields. It must report only current-storage compatibility and preserve capability qualification and truthful refusal. Update all consumers and inspection fixtures together. |
| Current runtime replacement | `fleet._upgrade_host.replace` invokes `daemon-upgrade`; `inspect` permits schema 18. Replace that dependency with current-schema verification before replacement, retaining native settlement/owner locks, exact candidate binding and workload checks. |
| Predecessor installation adoption | `fleet/adoption.py`, `_adoption_host.py`, `queue.service_upgrade.inspect_adoption_service`, CLI `fleet adopt`, host dispatch and operation resume expose historical adoption. Remove this reachable command/API set, not just its coordinator-upgrade call. |
| Service-manager migration | `fleet._services.migrate`, `ssh_operations.migrate_services`, CLI `migrate-services` and retained operation dispatch convert existing tmux bindings. Remove migration entrypoints; keep current explicit service-manager modes and current create/start/stop/replacement. The shared native guard still has a current replacement consumer and should use current replacement terminology without an alias. |
| Rphys wrapper | `tools/loom-fleet/adoption.py`, `rphys-fleet` migration dispatch and `operate.py` instructions emit/import predecessor inventory. Remove when adopting the paired Loom pin, so maintained runtime selections never invoke a removed command. |

Relevant existing checks include coordinator schema/refusal and preparation
operations, reconciliation and action results; agent-session current delivery and
restart/recovery tests; operator observation compatibility/refusal; fleet runtime
upgrade interruption/resume/native settlement, service lifecycle and command
parsing. Migration/adoption-success-only tests are obsolete; any current ownership,
cancellation, replay and containment assertions must survive at their current
owners. Do not claim the coordinator/agent inventory complete while protocol
fallbacks remain open. Physical current-runtime replacement remains part of the
later paired image/deployment qualification, not these local test receipts.

Implemented in this delivery: current-only coordinator/agent schema reopening,
complete delivery-column validation, no startup DDL/backfill, no coordinator
schema upgrader/API/CLI, no Fleet installation adoption or backend-migration
commands/host steps, current-only candidate compatibility, and current native
replacement guard naming without an alias. Current explicit tmux/systemd modes
remain supported. Retired host actions and retained operation kinds are refused
before lock/receipt creation. Paired rphys wrapper removal remains pending with
its dependency adoption; its existing pinned runtime still owns its old API.

Discovery/validation correction: a real interrupted coordinator write passed
schema admission but failed at `retirement_receipt`, whose read-only connection
required rollback on the original. That read now uses the same established
private inspector; normal current startup performs recovery afterward. The first
core execution was 91 passes and one such failure. No failed case counts as pass.
The affected retirement consumer joins this delivery's selected checks.

Validation selection (locked Python 3.12, collect before execution):

- Baseline: `tests/unit/loom/queue/test_current_storage.py` and
  `tests/unit/loom/queue/test_agent_sessions.py`. Fresh reopen, before-lock refusal,
  missing-column refusal, hot-write recovery, removed command parsing, current
  delivery publication/replay/reconciliation and resource handling.
- Config/Fleet environment (`--extra config --extra fleet`), exact selectors:

```text
tests/integration/queue/test_operator_observations.py
tests/integration/queue/test_role_retirement.py
tests/integration/queue/test_reconciled_runs.py
tests/integration/queue/test_preparation_operations.py::test_restart_reopens_real_nonterminal_admission_and_retained_worker_journal
tests/integration/queue/test_preparation_operations.py::test_native_unix_prepare_publish_submit_and_reconnect
tests/integration/queue/test_preparation_operations.py::test_running_preparation_cancellation_waits_for_native_resource_release
tests/integration/queue/test_preparation_operations.py::test_restart_reuses_capture_and_replays_a_claimed_complete_target
tests/integration/queue/test_agent_session_transport.py::test_agent_restart_joins_one_supervisor_and_replays_durable_remote_result
tests/integration/fleet/test_runtime_upgrade.py
tests/integration/fleet/test_service_lifecycle.py
tests/integration/fleet/test_configuration.py
tests/integration/fleet/test_ssh_operations.py
tests/unit/loom/fleet/test_upgrades.py
```

The integration population covers real current preparation/admission restart,
exact intent/cancellation replay, current supervisor and durable result recovery,
operator observations, retirement/release, current runtime replacement and setup
interruption/replay. Migration-only tests are removed; mixed tests retain their
current identity, work, cleanup and replay assertions. Retired delivery-backfill
fixtures no longer claim a supported restart path. No retired-case assertion is
changed into a pass for current behavior. Agent protocol legacy fencing/resource
fallbacks remain an explicit later transport/API inventory item and are not
claimed removed by this storage/command delivery.

Changed-file Ruff, affected source Pyright in the config/Fleet environment, and
diff checks also apply. No new dependency, scientific producer, report writer or
fixture input format changes; earlier unaffected serialization/authority evidence
is reused, except reached service-lifecycle guard checks are fresh here. Expand
for newly reached consumers or failures; physical fleet/image qualification and
the final scientific/size/scaling/archive gates remain outstanding.

Core final receipt: 92 passed in 33.21 s, no failures or skips
(`build/current-contract-cutover/coordinator-core-final.xml`). Changed-file Ruff
and affected Pyright passed. Source/test diff plus the new current-storage test
SHA-256 is `60f0914ed64072a31634b334fc68a14cc2a8427cf7890683074aa801157d394b`.
The config/Fleet selection completed on the same source/test tree: 169 passed in
2170.47 s, with zero failures, errors, skips or deselections
(`build/current-contract-cutover/coordinator-config.xml`). These include disposable
SSH installation/runtime-replacement fixtures; they do not claim qualification
of an external physical fleet. Together the two selections cover 261 distinct
cases. No selected coverage gap remains.

Independent actual-diff review passed. Its one finding, a stale downstream guide
claim that a schema-12 upgrade remained available, was corrected to the
current-root procedure and confirmed resolved. Source/test hash remains the one
above; subsequent differences are documentation only and leave runtime source,
dependencies, configurations and fixtures unchanged. Earlier authority and
serialization receipts therefore remain applicable within their stated scopes.
The paired rphys pin/wrapper and physical qualification remain open. The delivery
PR owns the exact commit, remote merge and tree-synchronization receipt.


### Current agent control contract

Base is coordinator/fleet merge `7639ac3a90ea768cc78849b53422c4e680e9f1d9`
(Loom #410); merged and reviewed head trees matched, and the PR owns the
synchronization receipt. This delivery requires `agent-control-wait-v1` during
agent handshake and removes the optional-capability state and old-peer polling
branch. Current service progress always uses bounded control waits; explicit
synchronous control polling and the full-population oversize-request fallback
remain current operations.

Owners: `_agent_session_protocol.handshake`,
`LocalDaemonAgentHttpClient.poll_control` / `_receive_service_controls`, and
`_RemoteAgentJournal.received_control_ids`. Current `AgentSessionView.handshake`
already advertises the capability. The outbound service handshakes before
registration/offering; missing capability must fail there without a retained
session. Reached consumers are control receipt/replay, reconnect, cancellation
while transfers are held, notification/wait capacity and exact transport retry.
No storage or wire format changes and no new dependency.

Remove only the predecessor-capability success variants from reconnect tests;
retain before/after-close lost-reply assertions. Add refusal to the existing
before-offer handshake test and explicit current suppression-envelope checks:
real retained receipts use bounded polling when count/byte limits are exceeded,
without truncation or acknowledgment. Select control-wait unit and transport
checks, retry checks, and exact reached concurrent-agent cases. Collect first;
record execution and independent review below. Reuse #410's storage/Fleet
results because schema admission, runtime replacement, dependencies/configs and
fixtures do not change here. The wider transport adapter and historical journal
fallback census remains open.

Selected locked Python 3.12 config-environment checks:

```text
tests/unit/loom/queue/test_agent_control_waiting.py
tests/unit/loom/queue/test_transport_retry.py
tests/integration/queue/test_control_wait_transport.py
tests/integration/queue/test_agent_session_transport.py::test_agent_client_rejects_an_old_protocol_without_compatibility
tests/integration/queue/test_agent_session_transport.py::test_outbound_service_rejects_missing_current_capability_before_offering
tests/integration/queue/test_concurrent_outbound_agent.py::test_control_receipts_survive_lost_reply_from_reconnecting_client
tests/integration/queue/test_concurrent_outbound_agent.py::test_serial_service_retains_cancel_while_real_transfer_is_held
tests/integration/queue/test_concurrent_outbound_agent.py::test_two_bulk_holds_preserve_exact_stop_and_unrelated_observation
```

Changed-file Ruff, affected source Pyright and diff checks also apply.

Final receipt: all 48 collected cases passed in 159.15 s, with zero failures,
errors, skips or deselections (`build/current-contract-cutover/agent-control.xml`).
Source/test diff SHA-256:
`aeee50cfc1637fc5eda81fd78c8df5af210466a07534ef8c77252904a281b2f6`.
Changed-file Ruff and affected Pyright passed; diff checks passed. The selection
covers notification wakeup, independent wait capacity, exact retries, refusal
before registration/offering, preserved oversize fallback, lost replies across
reconnect/close and cancellation while real bulk operations are held. Existing
bounded response/settlement assertions remain unchanged; receipt wall duration
is not presented as measured cancellation latency.

Independent actual-diff review passed after correcting the public queue guide's
stale optional-capability promise. Only documentation changed during/after the
selected execution; the source/test fingerprint is unchanged. No dependency,
configuration, storage fixture or scientific behavior changed. #410's current
storage/Fleet results remain applicable within their recorded scope; physical
qualification and downstream paired adoption remain pending. The delivery PR
owns exact commit, merge and matching-tree synchronization metadata.


### Current coordinator application and operator API

Base `9ca511b16258b82882bbc9f03b49f36663340138` (Loom #411). This delivery
removes the compatibility socket adapter, legacy control switches, old HTTP
client/operator entrypoints and unrestricted local inspection. Public callers
use `CoordinatorClient` and `CoordinatorOperatorClient`. Existing retirement,
scheduling, time/assignment recovery, session replacement and reconciliation
owners are exposed through guarded current operator requests before the old
wire dispatch is removed. Current Unix/HTTPS, query, agent and Slurm roles remain.

Reached consumers: CLI, Fleet enrollment/credential binding, native preparation,
Discord reporting, owned inspection, scope/retirement, waits/cancellation and
remote guarded recovery. Current terminal wait renewal, bounded observations,
pre-dispatch capacity refusal, exact operation replay and unknown post-dispatch
outcomes remain. An unstarted fake-service recovery test now exercises its
existing durable operation owner directly; fresh real remote recovery covers
the wire boundary. The inspection model contract now uses a real prepared run
and admission instead of an unrestricted fake socket owner.

Selection: cheap static/import and collection checks first; native client and
operator unit/contracts, affected CLI and daemon checks, role retirement and
operator observations; exact Unix/HTTPS authentication, deadline/lost-reply,
wait saturation, remote guarded recovery, current query and Slurm consumers;
real owned inspection; reached preparation restart/reload and cancellation;
Fleet enrollment/credential binding and service reload; Discord consumers.
Exact selectors and receipts are retained under
`build/current-contract-cutover/coordinator-api-*`. Initial collection before
new refusal tests: 159 cases collected. Initial Pyright found an accidental
extra type argument in an existing `cast`; corrected before execution. Neither
collection nor the failed static run is counted as behavior evidence.

Earlier persistence and agent-wait receipts remain applicable to unchanged
schema/recovery and wait-capability owners. New transport/role consumers require
fresh checks here. No scientific producer, dataset codec, dependency pin or
image changed; paired rphys adoption, scientific size/scaling/archive closure
and affected physical deployment qualification remain pending. Remaining
historical agent-row and preparation/event/runtime-store inventory is not closed
by this application API removal. Final results and independent review follow.

Bounded correction scope: the current inspection fixture now uses the generated
admission ID; the previously failed supervisor-start case passed unchanged.
Full static inspection also found the reboot-recovery test's remaining old
operator client and a supervisor-launch fixture still constructing removed
schema-less records. Port the real reboot consumer and retain both current
success/failure launch-control assertions, removing only the retired-format
success variants. This adds three reboot cases and two current launch cases.

Administrative error review found that a guarded recovery can commit intent and
containment evidence before a later conflict. Only the recovery owner's explicit
pre-admission refusal may claim `not_applied`; other post-dispatch administrative
conflicts retain `unknown`. The existing durable recovery test now covers both
storage and conflict failures after evidence commit through native dispatch,
preserving exact evidence, restart and replay assertions. Fresh checks include
that owner, current operator unit contracts, real remote guarded recovery,
reboot/containment, refused socket requests and redacted failures. Collection of
this bounded selection passed: 44 cases. Passing unaffected results are retained;
final coverage reconciliation follows after execution.

Final selected coverage: **299 distinct current cases passed**, with no remaining
failures, errors, skips or missing cases. Current collection is retained in
`coordinator-api-final-nodes.json`; the exact selection is in
`coordinator-api-final-selectors.txt`. `coordinator-api-coverage.json` reconciles
each current node against its latest applicable JUnit result rather than adding
overlapping runs. All receipts remain under `build/current-contract-cutover/`.

| Receipt suffix | Recorded execution | Current cases supplied |
| --- | --- | ---: |
| `imports` | 66 passed in the isolated base environment | 66 |
| `core` | 166 passed, four failed; retained failures superseded below | 104 |
| `core-recheck` | 27 passed, one inspection-fixture failure | 27 |
| `integration` | 57 passed in 419.79 s | 55 |
| `inspection-final` | Three passed after using the actual returned admission ID | 3 |
| `correction` | 44 passed in 36.21 s, including both post-commit failure kinds | 44 |

The first core/import source-test patch at base `9ca511b1` was
`21af62053fd699b8b6848582bb9f7b1b88bc3eb4dc159d3abc1fefdb7fa06c57`.
The core recheck and 57-case integration tree used patch
`da52f53172f5e7e8b27f1932cd0aef08fa9ae1a8c26b14c89329fd9c027b6193`:
the delta restores the required agent-retirement CLI identity flag and completes
the read/inspection fixtures. The three-case inspection receipt adds only its
generated admission-ID fixture correction to that source/test state.
Final source/test diff SHA-256 is
`c4aed5839ed159843069aab5de3f301180adbac3ea3a371f877c383ce99109c4`.

Reuse rationale: final production differences from the integration tree are the
recovery owner's explicit pre-admission conflict type and administrative
post-dispatch error classification. Fresh checks cover those changes, real
remote recovery and reboot containment. CLI identity was already covered by the
full affected CLI unit file and retirement recheck. Other corrections change
test fixtures/type narrowing, the missed reboot client and obsolete launch
success variants; the fresh selection covers those consumers. No dependency,
configuration, shared fixture, science, format or transport success-path changes
invalidate the retained import, control, inspection, preparation, reload, query,
Slurm and Fleet results. The unmodified supervisor-start case passed on recheck;
its original failure remains in the receipt, not relabelled as a pass.

Final full Pyright: zero errors/warnings. Changed-file Ruff and diff checks pass.
Static inspection's missed reboot consumer and schema-less launch fixture are
corrected, with their actual current behavior executed. Documentation now states
current complete schemas and no startup request backfill; historical delivery
notes no longer promise those removed behaviors. Independent final-diff review
and the delivery PR own merge eligibility and synchronization metadata.

## Current event records

Base `70fb8861ca3fcbbe44abe66588e3edd2ed2ffe67` (merged coordinator API #412),
branch `refactor/current-pipeline-events`. Rphys public-client consumers and the
detailed cross-repository plan subsequently merged in rphys #891; newer paired
dependency/image adoption remains open.

`PipelineEventRecord` admits/writes only current v2, with `occurred_at`, primary/
related resources, retained identity and optional causal reference. Remove v1
read/write helpers, compatibility identity reconstruction and timestamp/scope
constructor/property aliases. Current append requests (`PipelineEvent`) still
express run/stage scope and an optional timestamp: these are current intent
fields, before the store allocates the durable sequence. Shared `from_event`
construction preserves the producer identity/time; `matches_event` owns replay
equality for local, SQLite, service and repository stores. New records without
an explicit ID receive an opaque ID; current stored IDs remain unchanged.

Producer/consumer census: local and per-run SQLite stores, service authority,
authority repository and execution adapter; native lifecycle projection; offline
export/import; observer sinks and Discord; test store implementations and public
import boundaries. Database readers now require their retained current event
JSON, refusing the historical column-only reconstruction. Current database DDL
and its existing columns remain unchanged. Native local projection reuses its
original append request after authority acceptance; it does not reconstruct an
intent through a retired record alias. Offline imports retain the original v2
event in their audit payload and derive current run/stage intent explicitly.

Selected core checks cover model round trips/refusal/causality, append replay,
ordered/concurrent local events, observer sidecars, current SQLite/service/
repository consumers, cleanup event dispatch, offline evidence and lightweight
imports. Exact selectors: `build/current-contract-cutover/events-core-selectors.txt`.
New refusal cases prove retired logs cannot be read/appended, column-only rows
cannot be read/replayed with database bytes unchanged, and a retired event
cannot be admitted through the offline-import API. Existing sequence-gap,
ownership, revision, idempotency and callback-failure assertions are retained.

The config-enabled integration selection in
`build/current-contract-cutover/events-integration-selectors.txt` covers offline
API import/refusal, native observer routes and real lifecycle execution/failure/
cancellation, plus the Discord sink/CLI consumers. Collect both selections
before execution; use isolated locked Python 3.12 environments, with config
enabled for integration. Run full Pyright and affected Ruff/diff checks. Expand
only for an affected consumer or actual failure; no scientific kernels, rphys
dependencies, preparation wire families or payload writers change here.
Validation passed with 115 distinct cases and no failures, errors, skips or
deselections:

| Scope | Receipt | Result |
| --- | --- | --- |
| Core models/stores/consumers and import boundary | `build/current-contract-cutover/events-core.xml` and `.log` | 93 passed, 5.54 s |
| Config-enabled offline/native/Discord integration | `build/current-contract-cutover/events-integration.xml` and `.log` | 21 passed, 72.83 s |
| Reached HTTP execution adapter's identity/time/local projection | `build/current-contract-cutover/events-adapter.xml` and `.log` | 1 passed, 2.88 s |

Both initial selections collected successfully before execution. Their tested
source/test/feature-doc patch from the base above has SHA-256
`f95526405bdcdac7348439df3ad9d27071631dc461a14676dba8ca19cfab38e5`.
The final patch is
`1a1f1b0f65d4fa0b9a01b44eca8207c4c4a999b0b4b891533d0575c98ab16e6d`:
the sole additional change is a test for the HTTP adapter's reached append
path, proving its returned record and local projection retain the producer ID
and occurrence time. Its selector is in `events-adapter-selectors.txt`. This
test would fail under the removed historical-ID default. The initial 114 passes
remain applicable because production source, dependencies, config and fixtures
are unchanged; only that new test and these evidence notes followed them.

Full Pyright passed before the added test; focused Pyright of that final file
also passed, both with zero errors/warnings. Affected Ruff and diff checks pass.
No remaining selected coverage gaps. No physical or rphys dependency/image
qualification is claimed. Independent actual-diff review passed at
`0d684eda15a84a0122dc20603991631254f04872`, with no findings and merge
eligibility confirmed. Only this review receipt follows that reviewed head;
runtime source, tests, fixtures, configuration and dependencies are unchanged.
[Loom #413](https://github.com/samcantrill/loom/pull/413) owns remote merge and
matching-tree synchronization metadata. The remaining cutover inventory and
paired downstream adoption remain open.

## Current planning service dependencies

Base `9e2d667e994174880282cf5b799a9fb0f2687af9`, branch
`refactor/current-planning-services`. This delivery moves planning, resume and
CLI planning off `LegacyRunStore`, with all reached current callers. The full
aggregate removal remains open until lifecycle, stage-attempt preparation,
reliability and status consumers have also moved. Then delete the aggregate and
`RuntimeServices.from_legacy`, preserving the public explicit runtime-service
executor-factory contract. No replacement aggregate or compatibility adapter is
introduced by this planning API.

Planning consumes plan, stage-state, artifact-index and artifact-store owners;
dry planning has no store access and no fake unavailable-store objects. Resume
requires explicit stage-state/index/artifact owners; persistence separately
requires the plan owner. Required missing dependencies fail before planning
reads or writes. Fingerprint, artifact checksum/type, reuse, invalidation and
plan-document semantics are unchanged. Concrete local storage can implement
several protocols without becoming managed lifecycle authority.

Next runtime work retains the observed transitive dependencies: reliability
needs an explicit authoritative run status; lifecycle preserves transition
intent and event order; stage-attempt preparation preserves authority attempts,
protected report metadata and current standalone preparation. Current planning
also still admits old fingerprint versions; that distinct durable-format row
must be removed with its producers/readers and cannot be closed by this API
change. These remaining paths are not claimed complete.

Downstream census identifies the routine-native-context fixture in rphys
`test_routine_observations.py`; update it with paired dependency adoption, not
against the currently pinned earlier Loom API. No production rphys callsite of
the changed planning function was found. Examples, tests, the managed
preparation caller and active planning documentation move together here.

Validation will collect focused planning/resume, reached lifecycle/stage-attempt/
authority-adapter and CLI plan cases first, then execute them in locked Python
3.12 environments. Select real current managed preparation/execution, resume,
retry/cancellation and CLI consumers;
retain all existing scientific, persistence and physical obligations for paired
adoption. Add exact checks for distinct narrow owners, non-mutating dry planning
and missing required dependencies. Run
affected Ruff, Pyright and diff checks. Expand for reached consumers or failures;
no unrelated scientific/DDP/STMap/scaling workload is required by this API-only
delivery. Independent actual-diff review remains required before merge.

Selected scope is recorded in
`build/current-contract-cutover/planning-core-selectors.txt` (12 paths, 91
collected cases) and `planning-config-selectors.txt` (seven collected cases).
Core covers planner/resume refusal and integrity, distinct owner injection,
read-only CLI planning, reached stage-attempt/worker/lifecycle/local-executor
fixtures, authority adapters, stage-worker contract and plan persistence.
The config selection covers actual prepared retry before/after restart,
reuse-only completion, sibling cancellation, one successful contained output
commit/release, lineage inspection and CLI validate/plan/JSON. The clean managed
assignment variant is sufficient for its changed planner construction; unrelated
child-failure/containment variants retain their unchanged scientific/runtime
owners and are not repeated. No result is claimed until its receipt passes.

Initial full Pyright found a shadowed plan-owner variable and fixture typing
issues before execution. Corrected those without changing assertions; the plan
write-failure fixture now implements only the actual plan protocol and plans
with resume disabled. Full Pyright then passed with zero errors/warnings.

Validation completed with 98 distinct passing cases and no failures, errors,
skips or deselections:

| Scope | Receipt | Result |
| --- | --- | --- |
| Core planning/resume and reached consumers | `build/current-contract-cutover/planning-core.xml` / `.log` | 91 passed, 5.54 s |
| Config-enabled native retry/restart/reuse/cancel/commit, lineage and CLI | `build/current-contract-cutover/planning-config.xml` / `.log` | 7 passed, 43.85 s |
| Changed-test collection | `planning-changed-collection.log` in the same directory | 419 cases collected; this is collection evidence, not 419 passes |
| Static checks | `planning-types-final.log`, `planning-ruff-final.log` | Full Pyright 0 errors/warnings; affected Ruff and diff checks passed |

Both test selections ran on one stable source/test/example/feature-doc patch
from the base above, SHA-256
`8fd065788f54168c584a9290867300167e07298a99989e180505b5e573c4a670`.
Final patch SHA-256 is
`0ac1602ca79f9a961bd955e4a2e4428c7b9a16f90657567861ac0d17e313e594`:
the only subsequent source change clarifies the planner docstring that its
plan owner performs persistence; the planner itself issues no lifecycle
mutation. Executable behavior, tests, fixtures, dependencies and configuration
are unchanged, so all 98 passes and static checks remain applicable. These
evidence notes are excluded from both patch hashes. No required selected gap
remains. Independent actual-diff review passed at
`84dd163356c9fcfed94a8d996e7e0e98a2cb5150`, with no findings or required
corrections and merge eligibility confirmed. Only this receipt follows the
reviewed head. [Loom #414](https://github.com/samcantrill/loom/pull/414) owns
remote merge and matching-tree synchronization metadata. The remaining
aggregate consumers and downstream paired adoption remain open.

## Current execution service dependencies

Base `d29da7150a1123d091a1873a8b0f4e430c38d94d`, branch
`refactor/current-execution-services`. Lifecycle, reliability, attempt preparation
and CLI status now name their existing owners; the aggregate `LegacyRunStore`
and `RuntimeServices.from_legacy` are removed. Explicit `RuntimeServices`
construction remains the executor-factory contract. No replacement aggregate,
forwarding constructor or compatibility keyword is introduced.

Reliability receives authoritative run status explicitly and refuses missing
persistence capabilities. Lifecycle preserves failure/timeout ordering,
transaction chains, output/index/provenance commit and terminal event order.
Status writing has one explicit transition-intent API: authority applies its
existing guards, while local evidence refuses non-normal intent before effects.
Managed local and Slurm preparation pass the admitted snapshot status and exact
attempt/input bindings; standalone preparation retains local allocation.
Protected report helpers use prepared-run/config/path owners with existing
native companion, checksum, namespace, declaration and attachment verification.
Current no-project preparation still requires no project metadata.

Reached consumers include native preparation/candidate capture, action-result
resolution, installed project execution/reuse, guarded recovery and catalog
resume. The rphys routine fixture moves with paired dependency adoption. No
wire format, dependency, numerical operation or scientific fixture changed.
Historical fingerprint admission, input-lineage compatibility, event sink
capability discovery and remaining preparation wire consolidation retain their
separate inventory owners; this delivery does not claim those rows closed.

Validation selects lifecycle, timeout, attempt/worker, authority-adapter,
store/import contracts and local-store checks, plus exact managed local/Slurm,
protected installed project, retry/restart/recovery/cancellation and current
catalog consumers. New assertions distinguish owners, refuse missing services
before writes, preserve finalization-time timeout status, and prove commit/failure
order. Collection/static checks precede execution in locked Python 3.12 baseline
and config environments. Expand only for reached failures or uncovered current
contracts. Existing planning/event/persistence evidence is reusable where source,
dependencies, configuration and fixtures are unchanged; no physical/scientific
qualification is inferred from this runtime selection. Final results and the
independent actual-diff review are reconciled below.

Validation reconciliation:

| Scope | Tested revision and receipt | Result |
| --- | --- | --- |
| Baseline execution/store/API/CLI selection, 12 files | `9c8a49a857395d2aa006fa0acfbf4a07d2cc7bef`; `build/current-contract-cutover/execution-core-selectors.txt`, `execution-core.log` and `execution-core.xml` | 143 passed; two new causal-order assertions failed and were corrected below |
| Config-backed installed project, guarded recovery, cancellation, retry, managed local/Slurm handoff and catalog selection | Same stable source revision; `execution-config-selectors.txt`, `execution-config.log` and `execution-config.xml` in that directory | 22 passed in 238.09 seconds; no skips |
| Two commit-order cases | `a543844af047cf1e7e6c7e34c42af7c12764371f`; `execution-commit-recheck.log` and `execution-commit-recheck.xml` | 2 passed |
| Collection and static checks | `execution-core-collection.log`, `execution-api-collection.log`, `execution-config-collection.log`, `execution-types.log`, `execution-ruff.log`; corrected test rechecked in `execution-types-recheck.log` and `execution-ruff-recheck.log` | 145 baseline and 22 config cases collected; full Pyright and affected-file Ruff passed, including the corrected test |

The first run's two failures were test assumptions about transaction listing
order: opaque transaction IDs do not encode causality. The correction verifies
the exact two states, root/parent links and the existing `read_transaction_chain`
result. It preserves success/publication-failure, durable output/index/provenance,
terminal status and event assertions. No production correction was needed.

The 143 unaffected baseline passes and 22 integration passes remain applicable:
the only subsequent executable diff is those two assertions in
`tests/unit/loom/pipeline/execution/test_lifecycle.py`. Runtime source, dependency
selection, configuration, fixtures and setup are identical. The final union is
**167 distinct passing cases**, with no unresolved selected failures, errors or
skips. Reconciliation uses `(classname, name)` from the three JUnit receipts;
the initial failed outcomes are retained, not counted as passes.

The source/test/feature-doc/glossary patch from the base to `a543844a` has SHA-256
`e904b88287bbe857c5ad8fe1f91826f44991bf7a5e6956dd4f7f3eb09f03abf5`.
Subsequent execution-note edits do not change that patch. Complete base-to-head
`git diff --check` passes. Independent review of PR #416 at
`66baa9b572128c7d95b36727fe23ef1e517f2cf8` against the recorded base passed with no
qualified findings or required corrections. The reviewer verified the actual
diff, patch hash, receipts and scope. Only this review receipt changes afterward.
Downstream paired pins and physical qualification remain open at their existing
inventory owners.


## Current stage fingerprint admission

Base `6d6496f1d15c42de29a25fb7f8443ab8f522383f` (execution service removal,
PR #416), branch `refactor/current-stage-fingerprints`. Before review, the branch
also merged current `develop` at `52ae966b251132840a604024f809224c2b7eea61`
(artifact inspection, PR #415); this is the review base. The fingerprint payload
and record now accept only their existing schema 2, using the shared exact-version
validator. Payload decoding requires the current writer's complete field set;
`target_path` projection and synthesized empty factory fields are removed. Current
empty mappings, policy revision, hash inputs, digest verification and immutable
payload behavior remain unchanged. There is no new format or migration path.

The reached owners are deterministic fingerprint production, persisted plan and
resume decoding, worker requests, and resident/Slurm assignment admission. Retired
persisted evidence fails with the existing `ResumeStateError` before plan writes;
retired assignment fingerprints fail before durable retention. Current policy
changes still invalidate reuse, covered with a current-format policy fixture
instead of decoding schema 1. The redundant cross-schema comparison disappears
because admitted record and payload versions are each exactly 2.

Validation selects planning model/fingerprint/planner/resume policies, persisted
plans and materialization read models, worker model/contracts, resident request
round-trip and refusal, plus one current managed local and one mixed local/Slurm
execution. New assertions cover retired versions, alias/missing factory fields,
byte-unchanged refusal at persistence boundaries and current policy invalidation.
Collection, changed-file Ruff and full Pyright precede selected locked Python
3.12 baseline/config execution. Expand only for a reached failure or newly exposed
consumer. Writer bytes, dependencies, scientific code and fixtures, and wire
families are unchanged; full scientific/scaling/physical qualification stays at
the paired adoption gate. Previous execution/recovery results remain applicable
to unchanged current fingerprints; focused fresh checks exercise the tightened
admission boundary.

The first selection exposed a reached ordering defect: resident assignment
decoding inspected `factory_target` for shared scope before admitting the typed
fingerprint. A retired target alias therefore raised raw `KeyError` instead of
the intended `QueueServiceError`. The correction constructs and validates the
request first, then compares its selected schema with the received schema.
Current shared/non-shared wire disagreement is still rejected; no scope or
fingerprint validation is skipped, and neither operation performs IO.

| Scope | Stable tested revision and receipt | Result |
| --- | --- | --- |
| Planning/models/resume, persistence/read models, worker and assignment selection | `6407903e633c0d55e434cecb77f5b38fb584038d`; `build/current-contract-cutover/fingerprint-core-selectors.txt`, `fingerprint-core.log` and `.xml` | 117 passed; one new retired-alias refusal case exposed the defect above |
| Managed local and mixed local/Slurm execution | Same revision; `fingerprint-config-selectors.txt`, `fingerprint-config.log` and `.xml` | 2 passed; both repeated after the correction because they traverse assignment decoding |
| Affected assignment decoding and Slurm wire checks | `42dd565b5706dde0eb95bf69bedf12f1546f1e6c`; `fingerprint-affected-selectors.txt`, `fingerprint-affected.log` and `.xml` | 10 passed: current round-trip, retired refusal, shared scope disagreement, exact replay, local container, staged preparation, and Slurm framing |
| Fresh current execution after correction | Same final source revision; `fingerprint-config-recheck.log` and `.xml` | 2 passed in 15.24 seconds |

The pre-synchronization union is **125 distinct passing cases**: 113 unaffected original core
cases, 10 affected rechecks/additions, and two fresh integration cases. There are
no unresolved selected failures, errors or skips. Initial failures remain in the
receipts. Only `_ResidentAssignmentBundle.from_dict` changes between the two
tested revisions; the unaffected planning/model/store/worker owners, dependency
selection, configuration and fixtures are identical. All reached assignment
consumers in the original selection were rechecked, with additional scope cases.

The develop synchronization changes local artifact inspection and extracts shared
receipt metadata validation while retaining full closure verification for native
loads. At stable combined tree `93c422c283e87dcfaf37d6950f95c286298fa906`, the 32
cases in `fingerprint-sync-selectors.txt` pass (`fingerprint-sync.log`/`.xml`),
covering the full shared-artifact unit file and current shared assignment/replay.
Both managed local/mixed local-Slurm cases also pass freshly in
`fingerprint-sync-config.log`/`.xml` (15.78 seconds). Collection of the 32 cases
passes in `fingerprint-sync-collection.log`. This expands the final reconciled
union to **155 distinct passing cases**, with no required gaps. The upstream
change does not touch fingerprint/planning/worker semantics, dependencies or
their fixtures; affected shared publication and execution consumers were
rechecked on the combined tree. Other existing passes remain applicable.

Collection admitted 118 core, two config and 10 affected cases. Changed-file Ruff
passed; full Pyright's two test-edit diagnostics were corrected before execution,
and that test plus the subsequently changed assignment source passed targeted
Pyright and Ruff. Receipts are `fingerprint-*-collection.log`,
`fingerprint-types.log`, `fingerprint-types-recheck.log`,
`fingerprint-boundary-types.log`, `fingerprint-ruff.log` and
`fingerprint-boundary-ruff.log`. The changed documentation Python example parses,
and complete base-to-head `git diff --check` passes.

Final source/test/feature-documentation patch SHA-256:
`80c7cebc3e934032dd44fb0e2cfa4ef98610f65f673e744a39e664e25d955354`.
Independent review of PR #417 at `b80379f947d630cc0ce576d2365cd23f4a318c6e`
against current develop `52ae966b251132840a604024f809224c2b7eea61` passed with no
qualified findings or required corrections. The reviewer verified the actual
diff, patch hash and 155-case receipt reconciliation. Only this review receipt
changes afterward. The adjacent `ExecutionPlan` envelope
still accepts arbitrary positive versions despite its current version 1; that
remaining document-admission row is part of the full inventory, not closed by
the fingerprint cutover. Preparation wire families, lineage and downstream
dependency/image qualification likewise remain open.

## Current preparation input and processor contracts

Base `74076641e326e2de010f33d2e96b239694f99799` (PR #417), branch
`refactor/current-preparation-contracts`. This delivery closes child input,
private worker context, composition report admission and installed processor
policy/request/result. Resident assignment and worker-result consolidation remain
separate open wire-family rows; their current launch/publication consumers are
exercised here because they transport the changed preparation contracts.

| Boundary | Producer and consumer | Current disposition |
| --- | --- | --- |
| Child input | `queue/preparation.py`, native assignment decoding and `PreparationStage` | Schema 10 only; explicit scope/purpose, optional generations and candidate |
| Private context | Retained workspace `preparation_context`, `PreparationStage` | Schema 6 only; explicit input/scope/purpose; original artifact/report bindings |
| Composition report | `PreparationStage`, `_preparation_report`, coordinator decoder, native project-contract readers | Schema 10 only; same checksum-bound companion format; reject obsolete schemas before companion reads/writes |
| Installed processor | Protected policy, worker invocation/result, reconciliation admission | Processor 3 only; immutable captured composition and exact per-node contract coverage |
| Verification responses | Existing candidate/action verifiers | Independent response schema 1 and action-report schema 9 remain current |

No dependency, lock, scientific algorithm, input-capture receipt or public run
request contract changes. Retired composition mutation, `recovery_stage` policy
and v1/v2 processors are removed. Existing tests move their effective-invocation,
privacy, target/installation binding, reuse and retry assertions to current
node contracts and `loom.execution_binding`. Shared execution now publishes its
original report through the current shared-artifact owner so the remote worker
can verify the original contract. Negative cases refuse retired requests before
composition and obsolete reports before companion publication.

Validation selection: isolated locked Python 3.12 baseline covers child/capture,
staged inputs, report persistence/relocation, action verification, protected
processor policy, resident wire/workspace and Slurm framing. Config-extra coverage
executes the complete preparation-child, preparation-operation, reconciled-run,
installed-node and shared-execution test files, plus shared publication with
project context, current shared retry/recovery and actual Slurm report-pair
handoff. The separate supervisor's shared-container preparation cases cover
container path mapping. These are causal producer/consumer paths, not a Cartesian
backend matrix. Cheap collection, changed-file Ruff and complete Pyright precede
execution. Exact selectors and receipts use `build/current-contract-cutover/`
with `preparation-` prefixes. Failures, errors or required skips remain gaps.

Expand only for a newly reached consumer or failing contract. Previous authority,
control/event and runtime-service receipts remain evidence for unchanged owners;
this delivery does not claim full-suite or physical fleet/Slurm qualification.
Paired rphys dependency/image adoption and scientific writer/scaling acceptance
remain open at their existing downstream owners.

### Preparation validation evidence

| Scope | Tested revision and receipt prefix | Result |
| --- | --- | --- |
| Initial baseline selection | `1059a6513b0d669bf577cc1ec7beb82c3c6aeab3`; `preparation-core` | 190 passed, 6 failed; retained as diagnostic evidence |
| Complete selected config-extra paths | Same revision; `preparation-config` | 102 passed, 6 failed in 1168.67 s |
| Corrected report/action/recovery cases | `ac6082f9672b890a38fc5c903da423fe96c09072`; `preparation-affected` | 9 passed in 0.97 s |
| First shared-execution assertion recheck | Same revision; `preparation-affected-config` | 6 failed; exposed the fixture's transport/publication-root conflation |
| Shared execution with separate report publication | `5980ed5d56ffe250f39e3efb4bfa0962b2f177b4`; `preparation-shared` | 6 passed, 2 readiness-probe timeouts in 129.22 s |
| Exact readiness-failed cases, unchanged tree/settings | Same revision; `preparation-shared-readiness-recheck` | 2 passed in 28.28 s |

Each receipt prefix has a `.log` and JUnit `.xml` under the recorded build
directory. Final collection contains **196 baseline and 108 config cases**.
`preparation-coverage.json` reconciles their node IDs against the latest relevant
receipts: **304 distinct required cases pass, with zero gaps, errors or skips**.
Removed historical-success variants are excluded from the final population,
never counted as passes. All failed receipts remain available.

The baseline corrections supply the current schema to the companion-write fault
fixture and action-child assertion. Shared-container completion still verifies
original launch identity, resource-control evidence, publication and replay when
the source input disappears. Its retired schema-less success variant is removed.
Journal recovery keeps current unresolved-reference restart/replay assertions;
the former automatic-column-repair fixture now requires refusal with byte-for-byte
unchanged retained files. No runtime fallback was restored.

Shared execution now checks the original `loom_project_report` as its sole
transport input, its checksum and shared publication root; the application still
has no declared artifact inputs and the byte-relay trap remains. Report publication
has a separate root from assignment transport. The original assertion that
transport-control roots do not enter action fingerprints is preserved, together
with cancellation, unresolved delivery, restart and completed-result replay.
The final two failures occurred during five-second package-import readiness
probes before those assertions, while host load was elevated. Their exact rerun
passed without changing the timeout, source, lock, configuration or fixtures.

Evidence reuse is source- and consumer-based. All three tested revisions have
the identical `src` tree `d3dedc35d0776f354df6b378e1551f77f65bf9cc` and unchanged
dependency, lock and runtime configuration files. The 100 config cases outside
`test_shared_execution.py` have identical fixtures and setup to the initial run;
all eight shared cases have fresh final-fixture coverage. Of the baseline's
initial passes, 189 retain final node IDs. The shared-publication helper only
loses its unused retired-launch argument/branch; all surviving consumers used
the unchanged current branch. Fresh affected cases cover its current container
and publication behavior. The final union also includes seven newly passing
current cases; the two publication replay rechecks overlap existing passes.

Initial and final collections pass. Complete config-extra Pyright and changed-file
Ruff pass (`preparation-final-types.log`, `preparation-final-ruff.log`); the final
one-file fixture correction additionally passes its targeted type/Ruff checks
(`preparation-shared-types.log`, `preparation-shared-ruff.log`). The initial full
type check also found an existing shared-artifact test concatenating a plain-data
digest without narrowing; its explicit string assertion preserves the checksum
oracle and its selected case passes. Seven documentation Python examples parse,
six local links resolve, and `git diff --check` passes.

The source/test/feature-doc patch from the base to `5980ed5d` has SHA-256
`be45483e4c46f2cb671538840b66834e4e09a718de6b700f1ff6f5f54f27b0de`.
Only execution-note evidence changes after these receipts. Independent review of
[PR #418](https://github.com/samcantrill/loom/pull/418) at
`e006d2575423ed658acfa90cf8eca12ecf2462f9` against the recorded base passed with
no product blockers, localized corrections or workflow issues. The reviewer
verified the actual diff, patch hash, identical runtime source trees and complete
304-case receipt reconciliation. Only this review receipt changes afterward.


## Current assignment and result contracts

Base `532b893da24f819fa65d00d7f228804d027523fe` (PR #418), branch
`refactor/current-assignment-result-contracts`. This delivery closes the resident
assignment and result rows left open by preparation. Both are schema 6 only;
remote capability becomes `remote-stage-execution-v4` so an obsolete peer cannot
qualify for current execution. Existing deployment examples and fleet fixtures
advertise the current capability. Rphys pin/image adoption remains downstream.

| Boundary | Current producer/consumer | Disposition |
| --- | --- | --- |
| Assignment | Resident delivery/workspace, agent poll, Slurm ready stage | Schema 6; scope validated at its existing fingerprint owner, no duplicate binding |
| Terminal report | Resident retention and Slurm retention; local/remote publication and replay | Schema 6 with `output_kind` = relay/shared/preparation_report; full current evidence |
| Wire budgets | Agent JSON and authenticated Slurm relay | Current assignment body budget and report failure/route subtrees; existing byte/depth/collection limits |
| Remote compatibility | Handshake/candidate capability and maintained deployment declarations | Require v4 capability; obsolete assignments/results are refused |

Shared publication failures retain their mode despite having no outputs. Native
report-pair mode requires success, one named report and its original transfer
header. Existing role, profile, fence, checksum, closure and replay checks remain
with their owners. No dependency, lock, scientific algorithm, artifact receipt
or preparation report/companion changes. The independent StageWorkerResult
schema 1 and ExecutionFailure schema 1 remain current.

Validation selects full resident-wire/workspace, Slurm framing/result transport
and agent-Slurm unit owners; exact failure-codec/budget/capability and loopback
report routes; current remote restart/result replay; Slurm success, native
failure, guarded recovery, terminal crash reconciliation and output-ack replay;
current local/HTTPS preparation and report-pair refusal, shared execution,
prepared retry and cancellation. Capability consumer checks cover candidate
selection and fresh fleet setup. These paths exercise changed wire admission and
publication; no full backend matrix is required. Cheap collection, changed Ruff
and complete config-extra Pyright precede execution. Exact selections and
receipts live under `build/current-contract-cutover/assignment-*`.

Unchanged authority, planner, event and processor/composition contracts retain
prior passing receipts because their implementations, dependency/configuration
inputs and fixtures are unchanged. This does not reuse prior wire-path passes
as proof of the new representation. Expand for reached consumers, failure or
missing acceptance; required skips remain gaps. Physical fleet/Slurm and paired
rphys scientific/size/scaling qualification remain open at their original owners.

### Assignment/result validation evidence

| Scope | Tested revision and receipt prefix | Result |
| --- | --- | --- |
| Resident wire/workspace, failure budgets, current capability and transport consumers | `91a2fb4157bd086a7659ac1c9d231937ccc79ed7`; `assignment-core` | 149 passed, 2 new refusal-message expectations failed in 22.42 s |
| Current remote restart and Slurm success/failure/recovery/ack replay | `9ac31e03c4f94affbe514e15584105030ae0ddba`; `assignment-runtime` | 15 passed in 137.83 s |
| Local/HTTPS preparation, shared execution, native Slurm pair and fresh fleet setup | Same revision; `assignment-config` | 21 passed, 1 retired-version negative fixture failed in 773.09 s |
| Current capability refusal before registration | Same revision; `assignment-affected` | 2 passed in 2.92 s |
| Actual native Slurm pair, missing transfer mode and acknowledgement replay | `deabb4e20f5e6cc3ef76cb90ede1cca034826764`; `assignment-config-affected` | 1 passed in 3.97 s |

Receipts and exact selectors are under `build/current-contract-cutover/` with
these prefixes. `assignment-coverage.json` reconciles the final 151 baseline,
15 runtime and 22 config-extra cases: **188 distinct required cases pass**, with
no missing cases, failures, errors or required skips. Initial failed receipts
remain diagnostic evidence. The first baseline collection excluded two fleet
cases because they require the config extra; both were moved into the config
selection before execution and passed there.

Both corrections are test-only. The capability test now distinguishes the
existing protocol-refusal category from optional-capability refusal, advertises
the retired v3 capability explicitly, and still proves no registration or work
offering. The Slurm negative fixture uses a current report with relay mode and
no transfer header; its unchanged assertion requires refusal before native
publication. The completed test retains checksums, complete companion transfer,
missing-byte refusal and lost-acknowledgement replay. No assertion or timeout
was weakened and no runtime compatibility was restored.

All tested revisions have identical runtime source tree
`82dae2a084577ad43c25fe5a8a7bebff86491424`, with unchanged dependencies, lock,
configuration and maintained examples. The two capability cases are the only
changed fixture branch between the first two revisions. The final change is
confined to the failed Slurm pair's negative fixture. The other 149 baseline,
15 runtime and 21 config passing cases therefore retain equivalent runtime,
setup and consumer behavior; their results are reused rather than repeated.

Cheap collection passed in each required environment. Complete config-extra
Pyright and changed-file Ruff passed on the implementation tree; each later
changed test file passed its affected type/Ruff checks (`assignment-affected-*`
and `assignment-slurm-*`). Seven feature-guide Python examples parse and
base-to-head diff checks pass. Source/test/example/feature-doc patch SHA-256:
`cf7d465563c3fe6fccf326befd31da208d25f112b76d95400852e24e66004bf3`.
Subsequent edits record evidence only.

This does not close the separate managed-run intent boundary:
`queue/local_daemon_runtime.py` still selects schemas 3–6 by composition and
project-contract presence. That family and strict `ExecutionPlan` admission
remain inventory obligations, along with agent/fleet, offline evidence and rphys
scientific/product cleanup. The native-pair test uses real preparation output
through Slurm storage/transport helpers; it does not claim physical Slurm
preparation scheduling or deployed fleet compatibility.


Independent actual-diff review of PR #419 at
`2ddc8a6b366e8f7c22081997b0c89b4814cb21c4` against the recorded base passed with
no product blockers, localized corrections or workflow issues. The reviewer
verified all 188 cases, source-tree equivalence, static/collection receipts and
merge eligibility. The final maintained-document census also replaces one stale
`report-v3` label in the container guide with the current terminal-report owner;
no runtime, test, dependency or fixture changes follow validation. The final
patch hash above includes both affected feature guides.


## Current execution intent and plan admission

Base `7aa7af4fcf27df3196f51110e1a9bda67b94afb5` (PR #419), branch
`refactor/current-execution-intent`. Managed runtime intent moves from mode-based
schemas 3–6 to schema 7 with optional current composition/project bindings.
ExecutionPlan keeps its schema 1 bytes and now refuses other versions at
construction and decoding. The native writer, loader and replay comparison move
together; old-schema composition opt-out is removed. Retired intent fails before
binding inspection, admission or mutation. Current placement, installation,
options, concurrency, plan/pipeline digests and protected reference checks remain.

The obsolete inline-authorship success variant is removed from managed replay
coverage; the current reference variant retains logical metadata, exact replay
and byte/mtime preservation assertions. General logical user metadata and
inline/reference composition persistence have a separate owner in `local_runs`;
that remaining representation inventory is not declared closed by this delivery.

Validation covers strict plan admission and current planner/resume behavior,
fresh managed preparation, exact nonmutating replay, obsolete intent refusal,
protected composition/project binding changes, current generic runs without a
project processor, and representative resident/remote/Slurm execution and
candidate reuse. Collection/static checks precede execution; exact selectors and
receipts use `build/current-contract-cutover/intent-*`. Prior wire/authority
receipts remain valid where their inputs are unchanged, but fresh current intent
consumers are required. No blanket reference/fleet/physical rerun is authorized
by this bounded shape change alone; widen only for affected contracts or gaps.


### Execution intent validation evidence

All checks use the unchanged implementation revision
`947134ad01bcffbdc1e79d219c56c67a0bdd4e0f`, source tree
`f6eebeec31ba3a803d0ac4d3c79c743d65ea3210`.

| Scope | Receipt prefix | Result |
| --- | --- | --- |
| Current plans, planner/resume and programmatic runtime intent | `intent-core` | 37 passed in 1.11 s |
| Complete managed-preparation unit owner, obsolete intent, composed local/HTTPS preparation, protected candidate reuse/refusal and mixed Slurm execution | `intent-config` | 44 passed in 204.17 s |

Exact selections, collection logs, execution logs and JUnit XML are retained
under `build/current-contract-cutover/`. `intent-coverage.json` matches all
**81 distinct required cases** to passing receipts: no failures, errors, skips,
missing cases or post-validation source/test corrections. Obsolete intent tests
exercise direct loading and public preparation replay, preserving every retained
file's bytes, modification time and change time. The current authored path keeps
its reference/digest and complete logical metadata; generic programmatic intent
uses the same version without either optional protected binding.

Complete config-extra Pyright and changed-file Ruff pass (`intent-types.log`,
`intent-ruff.log`). Seven feature-guide Python examples parse; base-to-head diff
checks pass. Source/test/feature-doc patch SHA-256:
`982f82476b8e09f265e8a8f5db82074af7660a25065454ada142717cbdd9eebc`.
Only this evidence note changes after validation.

Earlier assignment/result validation remains evidence for the unchanged schema-6
codecs, capability-v4 handshake, failure bounds, publication framing and replay
owners; dependencies, fixtures and those owner modules did not change. Fresh
checks above cover the changed plan/intent producer and its downstream consumers.
Authority/event, scientific algorithms and deployment contracts likewise did not
change. No full-suite, scientific writer/scaling, image or physical qualification
is claimed by this bounded delivery.

Independent actual-diff review of PR #420 at
`bf2be978cad0d70991981472983f6739cf5cc704` against the recorded base passed with
no product blockers, localized corrections or workflow issues. The reviewer
verified the current contract paths, exact 81-case collection/receipt coverage,
patch hash, unchanged source/test trees, static checks, documentation examples
and merge eligibility. Only this review receipt changes afterward.

## Current agent offers and poll recovery

Implementation base: `22e0f09f4ef07d39a0e0b7046f427308180f2f82`.

| Boundary | Producers and consumers | Selected contract / deletion |
| --- | --- | --- |
| Agent offer | `AgentOffer.value`, authenticated offer dispatch, local journal reload, scheduling and inspection | Require current `resource_status` and `external_slurm_profiles`; delete missing-field synthesis, GPU-atom removal and inferred unavailable observations. Current writer bytes remain unchanged. |
| Coordinator/agent projections | Native status/agent/list writers and control clients | Require the resource-status fields already emitted by current writers; remove historical missing-field defaults. |
| Retained work-poll recovery | Coordinator `recover_poll`, agent replay and retirement | Explicit immediate-predecessor proof for an absent next request, including across restart; reject historical sequence gaps and remove inferred predecessor fallback. Preserve exact request/delivery checksums and retained ownership. |
| Local poll settlement | Journal, control application, cooperative agent service | Coordinator-confirmed `fence_poll` has one behavior. Current drain/reload fences remain unresolved until their outcome is proved; they cannot advance to another poll. Retain committed-delivery recovery across that control race. |

The omitted assignment ceiling of one is the current writer's canonical compact
default and stays supported, alongside explicit current ceilings. Likewise,
`FENCED` is produced by current control and retirement operations; deleting its
recovery would break a live cancellation/reload race. These are current contract
semantics, not historical adapters. Definite offer-renewal rejection and
indeterminate-response replay remain supported for current expiry and restart.
Workspace/result and other remaining inventory rows are not closed by this slice.

Validation selects the agent-session owner (including offers, GPU observations,
strict codecs, retained deliveries and control/recovery), current status/control
consumers, exact outbound rejection/restart and cancellation/concurrency cases,
and the affected retirement acceptance. Retired missing-field offers must fail
before coordinator mutation; historical sequence-gap refusals preserve owner
rows. Current delivery-racing-control fixtures use the real control producer.
Collection, lock and changed-file static checks precede execution. Expand for a
new affected consumer, changed wire ownership, missing current mode or failed
recovery assertion. Dependencies, scientific algorithms, reference writer and
scaling behavior are unchanged; those passing receipts remain applicable and
are not rerun by this bounded agent change.

### Agent offer/recovery validation evidence

Final source tree: `5ec2babb968ccf492645a3c4c9a019d5b37bdccf`.
`build/current-contract-cutover/agent-coverage.json` reconciles every collected
case to its latest receipt: **104 distinct passes**, no unresolved failures,
errors, skips or missing cases. Exact selectors, collection/execution commands,
logs, tested revisions and XML receipts share the `agent-` prefix there.

| Scope | Tested revision | Result |
| --- | --- | --- |
| No-extra agent-session owner and reached control/status consumers | `475e97e6752c79c90d22bdd111d5d156efc9f830` | 82 passed, 34.60 s |
| Config-backed outbound concurrency, rejection/restart, exact replay, late-delivery drain and GPU admission | same `475e97e6` | 12 passed, one fixture assertion failed, 132.11 s; affected restart cases replaced below |
| Lost-poll retirement, unresolved refusal, retained delivered work and rejected-next-poll retirement | same `475e97e6` | Nine passed, 97.94 s |
| Corrected same-epoch replay and cross-epoch recovery | `1ea20b4da1637f5ffbe289c345fca1c195000197` | Two passed, 21.81 s |

The failed fixture assumed every restart must use `recover_poll`. A current
same-epoch request instead replays directly when its offer is usable again;
the work completed with exactly one admission and release. The corrected test
records and compares the exact first replayed request, retains the cross-epoch
predecessor-proof assertion and preserves the single-admission/completion checks.
Both modes pass freshly. This is the only post-validation source/test difference;
runtime, dependencies, configuration and shared fixtures are unchanged, so all
other passing cases remain applicable. The optional assignment ceiling still
uses identical current writer bytes; `AgentOffer.value` is AST-identical to base.

Lock check, changed-file Ruff, config-extra Pyright and diff checks pass. Affected
test-file Pyright and Ruff also pass after the fixture correction. Final
source/test/feature-guide patch SHA-256:
`79968b5ede8041a06afbf6f3400192756a276229e5db59fc82d7a137ac76d404`.
Only evidence notes change after these checks. No image/physical qualification,
paired rphys adoption or repository-wide completion is claimed. Independent
actual-final-diff review and merge remain this delivery's closeout gate.

Independent actual-final-diff review of PR #421 at
`71ada31e3ae4775a09801461d0076f1777695b4a` against the recorded base passed with
no product blockers, localized corrections or workflow issues. The reviewer
confirmed all 104 collected cases against their latest XML receipts, unchanged
runtime trees and offer writer, the patch hash, current control-fence recovery
and exact owner/checksum preservation. The delivery is merge eligible; its PR
closeout owns merge and synchronization facts. Only this review receipt changes
afterward.

## Accepted declarations for guarded retirement

Implementation base: `edcdfdff621cb12210aea611355d48afe336d435`.
`read_agent_spec` produces protected declarations; initialization and guarded
reload bind them to native configuration revisions. `agent_declaration_guard`,
candidate verification and declaration-based retirement now require that accepted
binding. Remove the guard's unbound fallback and retirement's requalification of
missing historical evidence. Missing/conflicting evidence fails before an owner
lock, workload probe, supervisor startup or retirement mutation.

Explicitly qualified `OutboundAgentServiceConfig` remains the current
programmatic service API, with its existing owner, retained-work and shutdown
checks. The read-only binding inspector can still report absence for a current
programmatic configuration that never supplied declarations; this grants no
declaration guard or retirement authority. No new representation or state is
introduced. Current native schemas and retirement receipts remain unchanged.

Selected coverage: the complete declaration-binding unit owner, clean retirement
through explicit service and protected-spec callers, missing-binding refusal,
retirement with an unavailable old workload, lost-response replay, and the CLI's
explicit identity fences. Reuse #421's unaffected pending-poll/delivery retirement
and concurrency evidence: runtime differences here are only the missing-binding
and optional-guard branches, with unchanged bound retirement, poll recovery,
dependencies, fixtures and scientific behavior. Collect and run cheap static
checks first; expand for reached consumers or a failure. Independent review
checks the actual final diff before merge.

Validation: `build/current-contract-cutover/declaration-coverage.json` reconciles
all **20 collected cases to passing receipts**, with no unresolved failure,
error or skip. `declaration-tests.xml` records 19 passes at
`3009e2a7ff1ad91d1ff07afa5886c3a971da3cb9` and one fixture-cleanup failure
(36.87 s total). The refusal and unchanged-file assertions had passed; cleanup
then hit the same monkeypatch that prohibited workload probing during the call.
The correction restores the decoder only in cleanup, after those assertions,
and shuts down the fixture's own supervisor. Its exact recheck passes at
`038a56cb33ac9f7eeb0569984a206cd7ae2ba28b` (`declaration-refusal.xml`, 7.99 s).
The failed invocation's supervisor was also closed through its native fixture
helper. No unrelated runtime owner was changed.

Both tested commits have source tree `46bc9325cb85419f374c5b73f0c58da60964daa1`;
their only difference is the test's post-assertion cleanup. The other 19 passes
remain applicable with unchanged source, dependencies, configuration and
fixtures. Collection/execution logs are `declaration-*.log`; lock, changed-file
Ruff, affected Pyright and diff checks pass, including affected test Pyright
after cleanup correction. #421's `agent-retirement.xml` at `475e97e6` remains
valid for the nine unchanged bound pending-poll/delivery retirement cases:
the bound retirement implementation, poll codecs and recovery, shared fixtures
and dependency lock are unchanged. No scientific or physical rerun is warranted.

Independent actual-final-diff review of PR #422 at
`38cee2d99a76b868a1397c04099b24d5edb895a0` against the recorded base passed
with no findings requiring correction. The reviewer verified the 20 collected
IDs against passing XML receipts, the source/test/feature-guide patch hash,
identical tested runtime trees, the cleanup-only correction and reuse of the
nine unaffected poll/delivery cases. Current explicit-service retirement and
read-only absence remain supported; missing declarations cannot authorize
guarded ownership or retirement. The delivery is merge eligible. Its PR closeout
owns merge and synchronization facts; only this review receipt changes afterward.

## Authority-only run annotations

Implementation base: `61410ff216172809d74efd6b25250209bd848919`.
The current authority owns mutable labels, description, metadata and attributed
append-only notes. Remove runtime-file projection, first-write import, synthetic
legacy note records, and their parameters from every authority adapter and the
coordinator/query consumers. Authenticated authority requests reject obsolete
import fields before effects. Current native note bytes and database schemas
remain unchanged; old imported note records fail the current reader.

A run without annotations remains explicitly unknown on read. An explicit first
mutation starts empty at revision zero without inventing original submission
identity. Fresh preparation still combines authored tags with request context;
reused runs retain their existing annotation owner, and missing ownership stays
unknown. Authored runtime configuration remains captured evidence, not an
alternative mutable annotation store. CAS, run/principal-scoped replay, append
attribution, bounded paging, authorization and lifecycle independence are kept.

Coverage selection: run-context contracts and authority annotation tests cover
initialization, limits, atomic conflicts, rollback, replay, durable reopen, note
paging and retired note refusal. Exact query acquisition cases cover unknown
labels, no runtime import, current native metadata and notes. Configuration-backed
run-context integration covers fresh preparation, post-initialization restart,
failed preparation, reuse with/without original ownership, and Unix/HTTPS against
embedded/authenticated authority. Exact native query and MCP composed consumers
cover annotation text/search and CLI/SDK transport. Add explicit authority-route
refusal cases for old import bodies. Collect in the no-extra, config and MCP
locked Python 3.12 environments before execution; run lock, changed-file Ruff,
affected Pyright and diff checks. Expand only for a reached contract or failure.

Reuse prior pipeline execution, agent recovery and rphys scientific/size/scaling
evidence: no processing, publication, artifact, checksum, source/membership,
containment, dependency, fixture or scientific code changes in this delivery.
Paired rphys dependency adoption and final image/physical qualification remain
open. Independent actual-final-diff review and merge/synchronization are required.

Validation reconciles all **69 collected cases to passing receipts**, with no
unresolved failure, error, skip or deselection. The three isolated environments
ran against clean `29b00bd2043077643e6e646146245305937345d5`:

| Scope | Receipt | Result |
|---|---|---|
| No-extra contracts, authority annotations, route refusal and exact query acquisition | `annotations-base.xml` | 44 passed; two new fixture failures, replaced below; 5.19 s |
| Config preparation/context and native Unix/HTTPS query consumers | `annotations-config.xml` | 21 passed; 224.87 s |
| MCP SDK composed preparation, context, mutation, replay and note listing | `annotations-mcp.xml` | Two passed; 36.83 s |
| Corrected authenticated route refusal fixtures | `annotations-refusal.xml` | Two passed at `33ff980dea49f58769ab88be1b3b9341f375022c`; 2.29 s |

Artifacts and logs are under `build/current-contract-cutover/`; the case-by-case
reconciliation is `annotations-coverage.json`. The two initial failures occurred
before the request under test: the new fixture omitted the required coordinator
admission. It now establishes that admission through the existing owner before
asserting that old import bodies fail without annotation, note or lifecycle
effects. The refusal assertions were not weakened. Both tested commits have
identical production source tree `9eff54d8ee8f69214e8668c3c26163e0dca7cf33`.
Only this new fixture differs; dependencies, configuration, shared fixtures and
all other tested behavior are unchanged. The other 67 passes remain applicable.
Initial failures are retained and never counted as passes.

Lock check, changed-file Ruff, affected config-extra Pyright (zero errors or
warnings) and diff checks pass. The corrected test file also passes its own Ruff
and Pyright checks. Only these evidence notes change after final validation.
The required independent actual-final-diff review remains before merge.

Independent actual-final-diff review of PR #423 at
`30288df736d59e066cf8b4df439861fd6ab5d471` against the recorded base passed with
no product blocker or required correction. The reviewer verified all 69 unique
cases against their XML receipts, identical production source trees, current
initialization/unknown ownership, strict obsolete-input refusal and preserved
CAS/replay/authorization/attribution/lifecycle/query/preparation behavior. The PR
is merge eligible; its closeout owns merge and synchronization facts. Only this
review receipt changes afterward.


## Current Slurm assignment storage

Status: implemented, locally validated and independently reviewed in PR #424;
its remote state owns merge/synchronization facts. Approved work is in rphys #911; Loom base
`09b7e12a8a39de2f26aa959efe37f1635b5829b2`, branch
`fix/current-slurm-assignment-storage`, existing isolated cutover worktree.

Remove the confirmed `legacy_native_only` schema-3 allowance and its later
reservation-time column guard. Existing stores require the complete current
assignment and output tables, with read-only admission through the existing
SQLite inspection owner before writes and revalidation in the write transaction.
Explicit fresh initialization can populate the fresh coordinator's shared
database before any Slurm-owned table exists; an existing partial/old Slurm store
is never repaired. Current schema bytes and wire formats are unchanged.

Scope covers this store and reached daemon admission, native preparation output,
agent acknowledgement/restart and result/replay consumers. Selected no-extra
Python 3.12 checks collect first: assignment-store unit tests; new daemon old-root
refusal and current-owner reopen; agent Slurm journal tests; integration mixed
route, outage replay and actual native preparation transfer/ack. Reuse unchanged
wire-family and scientific receipts; no physical Slurm or deployed pin/image
qualification is claimed. Expand only for a reached failure or changed contract.

Implementation and validation receipts follow here; independent final-diff review
and verified upstream merge remain required.

The daemon now uses its existing complete owner-store admission before acquiring
owner locks, and retains the later admission under ownership. The new startup
refusal test exposed that the prior ordering created `owner.lock` before rejecting
unsupported Slurm storage; this bounded correction preserves the same owner proof
and current recovery, rather than weakening the unchanged-storage assertion.

Pre-review reconciliation: **34 distinct cases passed**, zero unresolved failures,
errors or required skips. Python 3.12, isolated locked no-extra/dev environment.

- Clean `507818ce` collected 24 cases and executed 23 passes plus one failure.
  The initial refusal assertion expected the inner error rather than the daemon's
  public wrapper. Test-only `110defc7` asserted both wrapper and preserved cause;
  its one-case recheck exposed the real owner-lock mutation. Both failed receipts
  remain retained and are superseded only by the affected passing case below.
- Clean `0e862af30d4b9d0b3b3acffd55095d76f5154800` collected and passed all 15 affected
  startup cases: old Slurm refusal and current root reopen; daemon initialize/
  restart, second-owner locking, missing owner stores, current-schema owner
  substitution, construction failure, prepared scheduling-reload recovery and
  once-per-operation owner admission; the three selected Slurm integration cases
  for mixed native/agent submit, outage replay and actual preparation transfer/ack.
- Reuse 19 passes from `507818ce`: the eleven assignment-store/framing cases and
  eight agent Slurm journal cases. The exact subsequent diff changes only the new
  refusal test's assertions and daemon `start` preflight. Those 19 cases neither
  start a daemon nor consume the changed test. Store/agent/transport source,
  dependencies, config and fixtures are unchanged; all reached startup consumers
  were rechecked. Source tree at the final tested commit is
  `942437a0c2fcb30aef2b70611a69c4da8ff2624d`, tests tree
  `c729352cc55e91a9fff6b9deab8dabc5b5444dfb`. Subsequent changes are evidence prose.
- Changed Python files pass Ruff; both changed source modules pass selected
  Pyright with zero errors/warnings. The three initially changed Python files
  are Ruff-formatted; the bounded new `local_daemon.py:1740-1768` block passes
  range formatting without unrelated whole-module churn. Diff whitespace passes.
  All execution used `uv run --python 3.12 --isolated --locked --group dev`.

Raw JUnit receipts are `build/current-contract-cutover/slurm-storage-507818ce.xml`,
`slurm-storage-recheck-110defc7.xml`, and `slurm-storage-startup-0e862af3.xml`.
`slurm-storage-coverage.json` in the same directory maps all 34 cases to their final
passing receipt. Collection output and static-check exit results were inspected
in the manager tool transcript; no separate full-suite claim is made.

The existing SQLite inspection helper privately copies WAL/hot-journal storage;
this delivery reuses it unchanged. Fresh current shared coordinator databases
remain valid initialization targets before any Slurm-owned table exists. Existing
partial Slurm tables are refused. Wire formats, lifecycle transitions, transfer
bytes, scientific payloads and dependency selection are unchanged. Existing
wire/scientific evidence remains applicable; physical Slurm and installed-image
qualification remain with the paired adoption owner. The next upstream census
is offline capture/import/query and lineage; these rows remain open.

Independent review of PR #424 at `cc5cdec06b67f20eb9a57f88c414a1586e59e6c8`
confirmed the 34-case reconciliation but identified one product blocker: the
shared owner proof opened other execution-store readers in writable mode before
Slurm admission, so an old Slurm database's hot journal could recover in place
before refusal. The store-only interruption tests did not cover this daemon join.
The bounded correction moves the existing read-only Slurm admission first in that
same proof and adds actual interrupted SQLite writes at daemon startup for both
current and retired schemas. Other owner checks and the locked proof remain.
The 15 affected startup cases plus these two new cases collect and rerun; the
19 store/agent passes remain applicable because their owners/fixtures/dependencies
are unchanged and they do not invoke this reordered proof. Final reconciliation
and targeted review confirmation follow; merge remains pending until they pass.

Final correction validation: clean `08aebb8f` collected and passed all 17 selected
cases in 32.63 seconds, including both new daemon hot-journal cases. Current
storage recovers and starts with its original owner identity and no uncommitted
rows; retired storage retains every file byte and mtime, including its journal,
and creates no owner lock. Selected Ruff/Pyright and range formatting for
`local_daemon_execution.py:638-673` passed. Exact candidate is committed before
testing; the only subsequent changes are this evidence prose.

Final coverage is **36 distinct passing cases**: 19 unaffected passes from
`507818ce` plus 17 passes from `08aebb8f`, with no unresolved failures/errors/skips.
The existing coverage map now selects those final receipts; the new raw receipt
is `build/current-contract-cutover/slurm-storage-owner-proof-08aebb8f.xml`.
The additional source diff only reorders the existing shared owner proof; changed
startup/recovery consumers were rerun. Original failing receipts are retained.
The independent reviewer is asked only to confirm the identified correction and
its affected evidence against the actual final head.

Targeted independent confirmation passed at
`2518a1d4480c957cebd1c98efa6faf43fc663fba`: the identified journal-ordering blocker
is resolved, with no remaining required correction. The reviewer verified the
actual reordered proof, both new daemon assertions, all 36 mapped passes and
source/test equality to the tested candidate. No additional tests ran. Only this
review receipt follows; PR #424 owns verified merge and synchronization facts.


## Current offline capture authority

Status: implemented, locally validated and independently reviewed; manager delivery
remains. Branch `fix/current-offline-evidence-authority`,
base `7ecee51a57bab3366807a033833d0494e033dfcd` (Slurm PR #424). The bounded change
removes the local-only lifecycle reader in `collect_offline_evidence_manifest`:
all current captures require the explicit or retained current authority snapshot.
Unavailable authority stays incomplete, including when `.loom` is absent; local
run/stage status files cannot supply lifecycle facts. Current configuration,
provenance and artifact capture, revision/timing labels, the current wire codec,
and explicitly historical-only non-executable imports remain supported.

Affected coverage: offline capture/codec contracts, current authoritative timing,
offline import adapter/authority/API refusal and successful historical inspection,
and the managed preparation consumer that verifies read-only evidence capture.
Add a complete native terminal capture/import check if the existing consumer does
not establish that path. Refusal covers absent and empty authority roots with
stale local success projections; original bytes/mtimes remain unchanged and the
import target has no admitted run. Select exact files/nodes after collection;
no full pipeline, fleet, physical or distributed matrix is warranted. Expand for
an actually reached changed consumer or a review finding. Query aliases, lineage,
workspace and result census rows remain open.

The first stable committed candidate `8e33eedee13684963fa1204ded826dd9cbdb3eb5`
collected 30 exact cases; 29 passed and the new actual native capture failed:
status was complete but each stage had zero artifacts because output/index reads
still used retired local projections. The native run writes current inputs and
fingerprints locally, but committed output facts belong to authority. Correct
capture to derive output refs and the artifact index from the same admitted
snapshot, retaining local input/fingerprint/config evidence and existing payload
inspection. Also preserve execution-plan order rather than sorting stage names,
so nonalphabetical dependency order passes the existing import contract. The
real two-stage test deliberately uses that order and asserts both checked payloads,
input evidence, index members and imported artifact count. No assertion was
weakened. This bounded correction remains within current capture/import closure.

Validation reconciliation:

- Cheap collection: 30 exact cases. Stable clean committed candidate
  `8e33eedee13684963fa1204ded826dd9cbdb3eb5`: 29 passed, one native-output
  omission failed, zero errors/skips. Raw JUnit/log and command/revision metadata:
  `build/current-contract-cutover/offline-capture-8e33eede{.xml,.log,-run.json}`.
- Corrected stable clean candidate `03b3123b`: collect and rerun exactly the
  capture unit file, authoritative-timing node, detached-composition import node,
  real native capture/import file and managed-preparation redaction node:
  **11 passed**, zero errors/skips, 16.83 seconds. Raw receipts use
  `offline-capture-03b3123b{.xml,.log,-run.json}` in the same directory.
- Reuse 19 unaffected passing cases from the first candidate: current offline
  codec, historical import validation/adapter and API cases construct retained
  evidence directly and never call the changed collector. Their source,
  dependencies, config and fixtures are unchanged; the Git delta changes only
  capture/output projection, its tests and docs. Latest-node reconciliation is
  **30 unique passes**, with no unresolved failed/skipped cases, in
  `offline-capture-coverage.json`; `offline-capture-after-first-run.patch`
  retains the exact source delta. This does not label the first run a full pass.
- Python 3.12, locked dev plus config-extra environment. Both collections and
  selected commands are retained in the logs/run metadata. Changed Python Ruff
  checks pass; source format is checked over changed collector/helper ranges
  because the surrounding module has existing formatting debt, test files are
  fully checked. Pyright on all three changed Python files passes; lock and
  diff checks pass. No dependency, fixture or validation configuration changed.

Current native local input/fingerprint documents and event projection are
retained: the actual two-stage run emitted both input documents, both fingerprint
documents and ten lifecycle events through current owners. The removed local
output/index readers had no corresponding native output writer; their existing
public projection APIs remain available for historical inspection/import. The
current capture wire fields/schema remain unchanged. Missing authority and stale
status/output/index projections cannot produce a complete or importable capture;
original files and modification times remain unchanged. Native output payloads,
timing/revision, plan order, import artifact count and non-resumable historical
policy are covered. Broader query/lineage/workspace rows, paired downstream pins
and physical deployment remain outside this delivery.

Independent actual-diff review passed for PR #425 at exact head
`f876c13239f6728fef44f0338b17b39585f6d64c`, base
`7ecee51a57bab3366807a033833d0494e033dfcd`: no product blocker, localized
correction or workflow issue. The reviewer independently reconciled all 30 latest
passes, verified the source delta and unchanged 19-case reuse boundary, and
confirmed GitHub merge eligibility. Only this prose receipt follows reviewed
source; no runtime evidence is invalidated. PR #425 owns merge/synchronization
facts; the broader cutover remains open.


## Current executable input evidence

Status: implemented, locally validated and independently reviewed in PR #426;
manager merge/synchronization pending. Branch `fix/current-input-evidence`, base
`c935de44808976203360b528ed4dcfb7ec2c9e1d` (offline capture PR #425).
The lineage census finds one live managed preparation producer: orchestration
captures produced/external bindings before persisting its preparation intent.
Close the remaining optional old request/transport readers around that producer:
require explicit bindings on PreparedAttemptRequest, validate missing worker
bindings before resident or Slurm delivery, and remove the unproduced
`legacy_unresolved` source kind. Preserve produced/external identity, original
commit owner, request digest, current retry/result binding and containment.

StageAttempt's current writer already emits input bindings and start-witness
members, including explicit null for genuinely unknown inspection evidence.
Require those existing wire members on read; remove missing-field reconstruction.
Keep explicit null distinct from known-empty inputs. Current generic direct
allocation and historical-only imports still produce unknown read-model evidence;
they cannot use missing evidence to pass a managed worker handoff.

Keep current producers, serialization/authority stores, orchestrator, resident and
Slurm delivery consumers and fixtures together. Existing zero-input preparation
fixtures must state empty bindings explicitly, not fabricate provenance. Add
old/missing request and wire refusal at actual boundaries, preserve the unknown
inspection and restart/start acknowledgement assertions, and select reached
orchestration/authority/lineage plus resident/Slurm and native execution checks.
Use cheap collection, committed stable candidates, raw receipts and targeted
rechecks. This is no schema/table migration, query redesign, new lineage store,
physical qualification or optional hardening. Broader query/local-run/workspace
census and paired deployment remain open. Independent final review follows.


Selection: the baseline scope covers preparation request/attempt codecs on both
authority implementations, current binding/start-witness round trips, orchestrator
intent replay, source/result ownership, resident delivery, daemon reload and the
four reached managed-local execution/retry/concurrency cases. The config scope
covers native lineage through Python/CLI/query roles, actual preparation child
publication/failure/replay, its resident-to-Slurm transport fixture, mixed
Slurm/agent execution and selected-authority publication after a lost reply.
Exact selectors are retained in
`build/current-contract-cutover/input-evidence-{base,config}-selection.txt`.
Baseline collection found 242 cases including two optional config cases; those
two run in the config environment instead. Initial config collection found 18
cases; its final scope adds the two selected-authority publisher cases. Collection
succeeded, changed-source Pyright reports zero errors, and changed-file Ruff
passes. Run each selected scope on a committed clean tree; no physical Slurm or
fleet claim follows from these local transport fixtures. Expand only for a
reached consumer failure or a concrete missing accepted assertion.


Initial stable-tree execution at `9358e1b69784cfcad71bf8ec85022522485ec09b`:
baseline 237 passed, 3 failed, 2 optional cases deselected; config 19 passed,
1 failed, no skips. Raw `input-evidence-{base,config}-9358e1b6` logs, XML and
run JSON record exact commands and unchanged source status. The three baseline
failures were fixture contract gaps: authenticated inspection cannot allocate
through its restricted client, so the real repository owner now allocates before
inspection through the client; the two replacement fixtures previously replaced
all worker metadata and now preserve the original zero-input binding/digest when
adding the predecessor. No production correction or assertion weakening was
needed. The config failure exceeded AF_UNIX path length under a long worktree
`--basetemp`; rerun its exact Unix-socket case with a short dedicated temporary
root. Existing 256 passes remain applicable: production, dependencies, configs
and unrelated fixtures are unchanged. The two changed fixture functions are
selected again; cheap collection found 22 baseline recheck cases. The delta is
retained in `input-evidence-fixture-correction.patch`.


Final selected coverage: **260 distinct passing cases**, no unresolved failures,
errors or required skips. On clean `5472172b5fbfe1bb80b65f4efbc0c62f998b7a35`,
the 22 baseline rechecks passed in 12.22 s test time (26.29 s command wall);
the exact Unix-socket query passed in 14.18 s (28.44 s command wall). Their
`input-evidence-{base,config}-5472172b` XML/log/run JSON preserve source identity,
commands and clean end state. `input-evidence-coverage.json` maps every current
case to its final passing receipt. The two baseline optional deselections ran
and passed in the config scope. The changed delta contains only the two fixture
functions and this owner document: production source, dependencies, config and
other fixtures are byte-equivalent to the first passing receipts. Thus all
unaffected passes remain applicable. Original failures remain recorded, with
replacement receipts rather than relabelled outcomes.

Changed-file Ruff and `uv lock --check` pass (`input-evidence-static.log`), as do
changed-source Pyright (zero errors; `input-evidence-pyright.log`), formatting of
changed ranges and diff checks. Existing format debt outside changed ranges is
untouched. Final changes after this tested head are documentation only. No
physical deployment or unrelated query/local-run/workspace census is closed by
this delivery. Independent actual-diff review and PR merge remain the next gates.


Independent review passed on `52bc501b15a90f4d7ace3e9f3826758217be7ac4` against
`c935de44808976203360b528ed4dcfb7ec2c9e1d`: no blocking or required correction.
The reviewer verified all 260 current outcomes against raw XML, the four
replacement receipts and source equivalence. Required current fields, unknown
inspection, produced/external ownership, start witnesses, digest transport and
current replay/containment remain preserved. PR #426 is merge-eligible under
its selected local gate. This final receipt changes only documentation; broader
census and physical/paired adoption remain separate obligations.


## Current run query and catalogue evidence

Status: implementing on `fix/current-run-query-evidence`, base
`2d91e456af7d6659f3cb7d66fb105fd5ce2ba173` (PR #426). This is the remaining
query/catalogue delivery under the approved current-contract cutover.

Producer/consumer trace: native composed-config persistence writes Weave's current
`CompositionManifest.to_dict()` with `fingerprint_records` and the
`artifact_safe_config` label. Both query acquisition and catalogue extraction
instead search retired flat aliases. Native Git provenance writes `commit` and
stage fingerprint records write `fingerprint`. ExecutionPlan has no whole-pipeline
fingerprint member: all retained `pipeline_fingerprint` producers found in Loom
are synthetic catalogue/CLI test fixtures. Rphys has no consumer of that query,
summary or filter field (its private operation-pipeline hash is unrelated).
Remove the unsupported summary/query/filter/CLI/comparison field together; keep
current config and stage fingerprint comparison. Advance list/diff response versions and the disposable derived catalogue cache
schema. Rebuild the cache from current sources without reading or converting old
rows. No run/authority product is migrated.

Current authority already retains run timing and confirmed attempt start timing.
Use those facts, preserving unknown versus known-never-started query semantics.
A stage finish requires its own successful current-attempt commit; an old reused
commit or a revision/preparation timestamp cannot become an execution instant.
Live catalogue artifacts come only from snapshot artifact facts, not uncommitted
local index entries. Retained local inspection remains a separate projection.
Authored run/runtime metadata remain their existing distinct metadata contracts;
this change does not recreate mutable annotations already owned by #423.

Affected boundaries: query acquisition and field validation, direct catalogue
scan, derived SQLite persistence/filtering, comparison and CLI formatting/parser.
Select their exact existing unit/contract/integration/CLI populations; add real
native execution assertions for current composition fingerprints, confirmed
start/finish and committed artifacts, plus old alias/CLI refusal and unchanged
source bytes. Config-backed managed-query transport is a separate selected
consumer. Cheap collection and static checks precede execution on a committed
stable tree. Reuse all unaffected execution, Slurm, offline capture, scientific
and physical receipts; this does not change their writers or dependency pins.
Expand only for a concrete failure, reached changed consumer or uncovered
accepted requirement. Independent final-diff review and merge/sync remain pending.

Cheap admission checks pass: baseline collection selects 101 cases and deselects
one config-backed native case, which the separate config selection includes
alongside both Unix/HTTPS managed-query consumers (three cases). All changed
Python files pass Ruff; changed source passes Pyright with zero errors. Changed
ranges are formatted without rewriting unrelated pre-existing format debt.
The 120-run catalogue fixture is retained in the selected population because the
changed SQLite insertion/filter schema is its affected contract; no million-row
or distributed/scientific workload is selected. Final execution receipts follow.


First stable-tree execution at `9290edb2`: baseline 95 passed, six failed,
one config case deselected; the separate config population ran all three and
failed. Raw `run-query-{base,config}-9290edb2` logs/XML/metadata retain every
outcome. Five baseline failures exposed old synthetic fixtures publishing only
local artifact indexes while expecting authoritative outputs. The fixtures now
use the existing authority allocation/commit API through the shared read-fixture
owner; failed runs retain a genuine prior commit followed by a failed retry.
Artifact identity/checksum/filter/comparison assertions remain. The sixth fixture
still asserted the retired diff response version and now requires v2.

The three new config assertions initially assumed a collection contained only
one run and no control directories; actual native preparation produces its own
run and known control directories alongside the target. Select the target URI
explicitly and retain all timing, fingerprint, uncommitted-output and unchanged
source assertions. Existing unrelated collection warnings are not hidden or
changed by this delivery. These corrections are test-only: production source,
dependencies and executable configuration remain exactly `9290edb2`. Recheck all
consumers of the changed shared fixture and all three new config cases; retain
unaffected passing baseline evidence. No failed assertion counts as a pass.


Final local reconciliation: all **104 distinct selected cases pass**. At clean
`da8edc987d49ef4f5fded5e700d0199adea48796`, all 17 affected baseline consumers and
all three config cases passed (actual native execution plus Unix and HTTPS
query transport). Together with unaffected passing `9290edb2` outcomes, there
are no unresolved failures/errors/skips. The baseline's one deselected native
case is explicitly included and passed in config. Raw XML, stable-tree metadata,
source/correction diffs and per-case reconciliation are retained under
`build/current-contract-cutover/run-query-*`; `run-query-coverage.json` owns the
104-case union. The source tree stayed unchanged during both concurrent scopes.
Final changed-file Ruff and diff checks pass; changed-source Pyright and locked
dependency checks pass. No dependency, configuration, production code or fixture
changes follow the final successful runs; only this receipt and removal of stale
public documentation references follow them. Independent PR review is next.

Independent final-diff review of PR #427 at
`809baa4302cb36b2bd62b72adc1e5b717f5ab98b` passed with no product blocker,
localized correction or workflow issue. The read-only Loom reviewer
(`current_run_query_evidence_review`, gpt-6-astra/high,
`fork_turns=none; file-backed`) verified current fingerprint extraction,
pipeline-field retirement, authoritative timing/artifacts, retained metadata,
cache regeneration and both response envelopes. The reviewer independently
reconciled all 104 passing cases against raw receipts and checked affected
fixture rechecks and static evidence; no extra execution was necessary.
The manager verified the reviewed head, clean worktree, PR target `develop`,
non-draft state and mergeability. This final addition changes only the receipt;
merge and matching-tree synchronization are published in the existing PR.
Physical Fleet/Slurm, scientific and downstream deployment qualification remain
outside this delivery.

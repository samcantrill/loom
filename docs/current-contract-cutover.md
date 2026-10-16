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

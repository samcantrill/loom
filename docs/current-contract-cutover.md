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
head. The authority slice uses `refactor/current-authority-formats` from that
exact merge. No active installation is modified by local
tests. Current-format bytes remain unchanged unless a later row changes shape.

## Persistence slice

| Producer → consumer | Contract / change | Evidence status |
| --- | --- | --- |
| Current record writers → `serialization.load_versioned_document` | Exact owner-declared version, strict integer and fields; removed `DocumentMigration`, export, argument and conversion loop | merged #408 |
| Supervisor initialization/launch → reopen and retained role guard | Journal 6 and launch 2 only; removed schema 2–5 upgrades/schema-less launches; current DDL retained; read-only refusal before owner contact or repair | merged #408 |
| Coordinator/agent roots → service startup | Current 19/12 only, remove offline schema upgrade and older reconstruction | pending |
| Authority/coordination → current stores and inspection | Current 11, complete fresh DDL, no automatic upgrades; preserve WAL-aware inspection | pending |
| Authority-service repository → admission/read/write | Repository 12; remove v3–11 upgrade functions and audit-table conversion; fresh DDL and strict existing-root checks | pending |

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

### Authority storage (in progress)

Discovery on the #408 merge identifies three reached owners:
`pipeline/stores/sqlite_authority.py` (current 11),
`pipeline/stores/sqlite_coordination.py` (current 11), and
`authority/_repository.py` (current 12). Implemented current-only admission and
complete fresh creation for all three; validation and independent review remain.

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

Current coordinator transport and mandatory control waiting; event v2 APIs;
runtime narrow-service adoption and aggregate removal; unified preparation
context and processor v3; historical offline/import/annotation/lineage/Slurm
projections; fleet predecessor adoption and schema-upgrade CLI removal. Each
requires producer/consumer and dynamic-reference inventory before modification.
No row can be closed solely by assigning it to another stage.

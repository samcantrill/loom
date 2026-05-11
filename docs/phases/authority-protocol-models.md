# Phase 2 Execution Plan: Authority Client And Server Protocol Models

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 2: Authority Client And Server Protocol Models`
- Branch: `codex/authority-protocol-models`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-protocol-models`
- Phase execution plan path: `docs/phases/authority-protocol-models.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 2 - Authority Client And Server Protocol Models
- Stack predecessor: none; Phase 1 is merged in PR #119 and recorded in the plan
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 3 adapts readiness and health models to FastAPI routes; Phase 4 maps repository compatibility errors to protocol envelopes; Phase 7 uses these request/response envelopes for real mutation routes and client behavior.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md` and roadmap v10 planning notes
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by `loom_phase_planner` on 2026-05-11
- Refine pass: completed by `loom_phase_planner` on 2026-05-11
- Setup limitations: none unresolved. `gh auth status`, `gh auth setup-git`, `git fetch origin`, and `git worktree add` required approved escalation because sandbox restrictions blocked network access, user Git config writes, and `.git` ref updates; after escalation, local `develop`, `origin/develop`, and remote `develop` all resolved to `c12bb1b2c21e8e7e3951deea820a56af2e06ff5c`.
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Define the transport-independent authority protocol value models that future `AuthorityClient` and server adapters use for readiness, capabilities, mutation requests, accepted acknowledgements, structured rejections, revision/fencing facts, snapshots, and error envelopes, without binding Loom core code to FastAPI, Pydantic, HTTP, SQLite, or repository schemas.

## Full-Plan Context

Phase 1 established side-effect-free online/offline authority resolution, typed resolver failures, and reserved `direct_database` diagnostics. Phase 2 turns the next public compatibility surface into explicit plain-data protocol models before any transport, durable repository, supervisor, registry, runner, coordination-service, resource-lease, or offline-import behavior exists. Later phases can then adapt the same protocol values to FastAPI, repository errors, runtime callers, diagnostics, workspace coordination, resource admission, and offline import without redefining the wire contract.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 1 merged to `develop` in PR #119
- Why this base branch is correct: the assignment records Phase 1 as merged and no unmerged stack predecessor; `develop` and `origin/develop` were verified at the same commit before worktree creation
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: define transport-independent authority protocol models before binding them to FastAPI or persistence.
- Required scope: request, response, acknowledgement, rejection, revision, capability, readiness, and error-envelope models; run lifecycle, stage lifecycle, operation submission, output commit, artifact fact, lease/fencing, snapshot, and read-model essentials; protocol version and schema compatibility fields; model validation and round-trip coverage; no FastAPI or private repository imports.
- Required checkpoints: stable model module and exports, standard-library value modeling, version/capability/readiness contracts, structured error categories, accepted/rejected response shapes, golden-shape tests, and package import-boundary coverage.
- Acceptance criteria: protocol modules are usable by future client and server adapters without FastAPI or SQLite; error envelopes carry resolver, validation, conflict, stale-generation, unsupported-capability, and internal-error categories; acknowledgements include enough revision and fencing data to prevent blind writes; capabilities support diagnostics and future compatibility checks.

## Current Source And Harness Findings

- `src/loom/pipeline/stores/authority_resolution.py` now provides Phase 1 resolver vocabulary with stdlib `dataclass(frozen=True, slots=True)`, `StrEnum`, explicit validation, `PlainData`, and `to_dict`/`from_dict` style serialization. Protocol models should compose with, not replace, those resolver categories.
- `src/loom/pipeline/stores/authority.py` defines `PerRunAuthorityStore`, public `RunStore` and `StageStore` protocols, plus existing acknowledgement-like records such as `StatusTransition`, `AttemptAllocation`, and `OutputCommit`.
- `src/loom/pipeline/stores/read_models.py`, `coordination.py`, `capabilities.py`, and `schema_policy.py` already expose public value records for revisions, lifecycle reasons, leases, attempts, snapshots, materialized refs, capability sets, diagnostics, and schema checks. The new protocol layer may nest those public records where they are stable value vocabulary, but should wrap them in protocol envelopes rather than making store method signatures the wire API.
- The current store protocols expose many method-level operations. Phase 2 should group those methods into representative protocol operation families and shared envelopes, not create a giant one-record-per-method public surface.
- `src/loom/pipeline/stores/service_authority.py` is the current stdlib manager-backed test service. It serializes some values with `to_dict`/`from_dict`, but it is not the v10 HTTP protocol and must not own the new public model definitions.
- `src/loom/serialization` exposes `PlainData`, `ensure_plain_data`, `to_plain_data`, `stable_json_dumps`, and dataclass helpers. Existing public models mostly use explicit `to_dict`/`from_dict` so they can coerce enums, reject unknown fields, and validate nested records.
- `pyproject.toml` has no required runtime dependencies. Pydantic exists only in the optional `config` extra, and FastAPI is not present yet. Phase 2 must not add or depend on either.
- `tests/package/test_pipeline_store_api.py` asserts stable `loom.pipeline.stores` exports and that importing the stores package does not import `fastapi`, `sqlite3`, service authority, or private SQLite modules. Phase 2 must extend this style of coverage for the protocol surface.

## In-Scope Work

- Add a stable non-transport protocol model module under `src/loom/pipeline/stores/`, preferably `authority_protocol.py`, and export only intentional public protocol vocabulary through `loom.pipeline.stores`.
- Use standard-library frozen dataclasses, `StrEnum`, existing `PlainData` helpers, and explicit `to_dict`/`from_dict` methods. Do not use FastAPI, Pydantic, HTTP clients, repository modules, or SQL-specific types.
- Define protocol version and compatibility records, readiness/health/capability summaries, operation metadata, revision/fencing acknowledgements, structured rejection/error envelopes, and success/failed response envelopes.
- Define a compact operation-kind vocabulary and request/response envelopes for representative operation families: readiness/capability/schema checks, run lifecycle and snapshots, stage lifecycle and attempts, submitted-operation access, output commits and artifact facts, run/stage lease and fencing updates, and recovery/cleanup read models.
- Use typed request or result body records only where a family needs fields beyond the shared envelope. Do not mirror every `RunStore`, `StageStore`, or `PerRunAuthorityStore` method with a bespoke top-level protocol record.
- Keep protocol coverage for workspace coordination, generic resource leases, and offline import limited to capability/readiness and unsupported/error vocabulary needed by future phases; do not implement their service methods here.
- Add package, unit, and contract tests for import boundaries, validation, enum/category coverage, round trips, version compatibility, and golden plain-data shapes.

## Out-of-Scope Work

- FastAPI application, route handlers, route tests, dependency injection, HTTP status mapping, or client transport behavior.
- Durable repository schema, SQLite connection handling, migrations, transactions, or repository conformance tests.
- Runtime factory adoption, `PipelineRunner` adoption, CLI runtime behavior changes, worker handoff changes, SLURM migration, registry persistence, or supervisor lifecycle commands.
- Workspace coordination service API behavior, resource lease accounting, scheduler admission, offline evidence manifests, offline import, or deferred-finalization changes.
- New runtime dependencies or optional dependency use for protocol validation.
- Changes to run/stage status enums unless the refine pass records source-level proof that the current enums cannot represent required protocol facts.

## Assumptions

- Phase 2 protocol values are the public compatibility surface, but they are still plain Python value objects, not generated OpenAPI/Pydantic schemas.
- Existing public value records such as `BackendRevision`, `LifecycleReason`, `LeaseRecord`, `StageAttempt`, `AuthoritativeRunSnapshot`, `ArtifactRef`, `SubmittedOperationRecord`, `BackendCapabilitySet`, and `AuthoritySchemaCheck` can be nested where they already represent stable domain-neutral facts.
- Top-level protocol envelopes need their own records for protocol version, service generation, request ids or operation ids, accepted/rejected response shape, and error categorization.
- Transport status codes, JSON media types, timeout policy, and process health behavior belong to Phase 3 or Phase 7; Phase 2 only defines the structured payloads those adapters will exchange.

## Scope Contract

Protocol models must be deterministic, side-effect-free, and plain-data serializable. Constructing, serializing, or parsing them must not start services, probe endpoints, read registry files, open SQLite databases, import FastAPI, import Pydantic, import private repository modules, or mutate runtime stores.

The new model surface should be explicit enough for a future client adapter and server adapter to agree on these public facts: protocol version, schema compatibility, service generation, workspace identity when known, capabilities, readiness, request operation kind, accepted acknowledgement revision, lease/fencing material when relevant, rejection category, diagnostics, and nested read models. Error categories must be machine-readable and include at least resolver, validation, conflict, stale generation, stale revision or fencing, unsupported capability, unavailable service, and internal error.

Public envelope field names should be stable and ordinary:

- Compatibility and service fields: `protocol_version`, `schema_version`, `service_generation`, `workspace_id`, `capabilities`, `readiness`, and `diagnostics`.
- Request identity and routing fields: `request_id`, `operation_kind`, `run_uri`, `stage_name`, `submission_id`, `lease_id`, `owner_id`, and optional `idempotency_key`.
- Mutation-safety fields: `expected_revision`, `revision`, `lease_id`, `fencing_token`, and nested lease/fencing records where existing public models already expose the stable facts.
- Response fields: an explicit `accepted` discriminator with exactly one structured `result` or `rejection`; rejection/error fields named `category`, `code`, `message`, `detail`, and `diagnostics`.

Do not alias existing store protocols as the wire contract. Store methods describe Python extension-point behavior; protocol envelopes describe serialized client/server exchange. Existing public store/read-model records may appear as nested values only when the protocol still controls versioning, operation identity, acknowledgement, and rejection semantics. Existing acknowledgement-like records such as `StatusTransition`, `AttemptAllocation`, and `OutputCommit` must not become top-level response envelopes; if their facts are reused, they belong under protocol-owned `result` payloads.

Phase 2 must not introduce fake client/server conformance behavior. A test helper may round-trip request and response value objects through plain-data serialization, but adapter behavior, route dispatch, transport status mapping, dependency injection, repository mutation, and client/server contract harnesses belong to Phase 3 or Phase 7.

## Design Impact

- Maintainability: separates stable protocol payloads from FastAPI route code, private repository code, and current stdlib manager test service behavior.
- Extensibility: leaves room for alternate transports and repositories because adapters consume plain-data protocol values instead of framework objects.
- Domain neutrality: operation names and fields stay within Loom lifecycle, artifact, lease, capability, and diagnostic concepts, with no research-domain semantics.
- Source-tree boundaries: protocol models live beside authority, resolver, capability, schema, and read-model contracts under `loom.pipeline.stores`; transport and repository phases adapt to them later.

## Future Compatibility

Protocol and schema compatibility fields should let newer clients and older services fail cleanly before mutation. The envelope structure should permit additive future operation kinds for workspace coordination, resource admission, supervisor diagnostics, and offline import without breaking Phase 2 golden shapes for existing operation families. Future route implementations may split operation families across endpoints, but they should still carry the same envelope fields and accepted/rejected semantics.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Use FastAPI or Pydantic models as the core protocol | Phase 2 must keep the compatibility layer independent from the selected transport and from optional/config dependencies. |
| Reuse private repository or SQLite dataclasses as wire models | v10 requires private persistence and public protocol separation; repository shape is Phase 4 and must remain non-public. |
| Treat existing store method signatures as the serialized API | Store protocols are Python extension points and lack protocol version, service generation, request identity, and structured rejection envelopes. Mirroring every method would also make the public surface too broad before adapters exist. |
| Return unstructured dictionaries for acknowledgements and errors | Future clients need typed revision, fencing, capability, and rejection facts rather than message matching. |
| Add generic framework abstraction before real adapters exist | Plain dataclasses and explicit helpers match current source patterns and are sufficient for Phase 2. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Some protocol operation models exist before server routes implement them | Phase 2 intentionally creates the compatibility surface ahead of FastAPI, repository, and mutation API phases. | Phase 7 wires mutation routes and finds an operation is unused, missing, or mismatched. |
| Workspace coordination/resource/offline-import protocol support is limited to compatibility and error vocabulary | Dedicated later phases own those method surfaces and accounting/import semantics. | Phase 15, Phase 16, Phase 17, or Phase 18 starts and needs additive operation models. |
| Explicit manual `to_dict`/`from_dict` validation duplicates local helper patterns | Existing public models use manual validation to control enums, unknown fields, nested records, and compatibility errors. | A shared helper can be introduced later without weakening validation or public shape stability. |
| Representative operation families may require Phase 7 endpoint adapters to choose per-route grouping | Keeping Phase 2 below one-record-per-method scope preserves reviewability and avoids freezing transport routing early. | Phase 7 cannot express a needed mutation safely with the shared envelope plus family payloads. |

## Reviewability

- Expected PR size and shape: moderate model-and-test PR with one new protocol module, package export updates, package import-boundary assertions, unit validation tests, and contract golden-shape tests.
- Files and areas to inspect: `src/loom/pipeline/stores/authority_protocol.py`, `src/loom/pipeline/stores/__init__.py`, `src/loom/pipeline/stores/authority_resolution.py`, `authority.py`, `read_models.py`, `coordination.py`, `capabilities.py`, `schema_policy.py`, `src/loom/serialization/*`, `tests/package/test_pipeline_store_api.py`, new unit tests, and new contract tests.
- Scope-control checks: no FastAPI/Pydantic imports, no `sqlite3`, no `service_authority` dependency, no private `sqlite_authority` or `sqlite_coordination` dependency, no route/client transport code, no repository schema code, and no runtime caller migration.

## Implementation Steps

1. Add the protocol model module with version, readiness, capability, request metadata, accepted response, rejection, and error-envelope records using stdlib dataclasses and explicit plain-data serialization.
2. Add a compact operation-kind enum plus family-level payload records for run lifecycle, stage lifecycle/attempts, submitted operations, output/artifact facts, lease/fencing, snapshots, recovery, and cleanup, composing existing public value records where appropriate.
3. Export the intentional public protocol surface through `loom.pipeline.stores` and update package import-boundary tests to prove the new exports remain transport and repository independent.
4. Add unit tests for model validation, unknown-field rejection, enum/category coverage, version compatibility helpers, nested public-record conversion, and round trips.
5. Add contract tests with stable golden plain-data shapes for representative readiness, accepted mutation, rejected mutation, snapshot, and unsupported-capability responses.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py` and relevant package import-boundary tests if the new module is imported elsewhere
- Required assertions or deferral reason: `loom.pipeline.stores` exports the intended protocol symbols; importing stores does not import FastAPI, Pydantic, `sqlite3`, `service_authority`, `sqlite_authority`, `sqlite_coordination`, route modules, or repository modules.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_protocol.py`
- Required assertions or deferral reason: protocol version checks, readiness/capability records, acknowledgement/rejection invariants, error category coverage, request validation, nested public-record serialization, defaulting, unknown-field rejection, and `to_dict`/`from_dict` round trips.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_protocol_contract.py`
- Required assertions or deferral reason: stable golden plain-data shapes for representative readiness responses, successful run/stage mutation acknowledgements, stale-generation or conflict rejections, unsupported-capability errors, snapshot responses, and compatibility with Phase 1 resolver failure categories where resolver diagnostics are carried through protocol errors. These tests may round-trip value objects through plain data, but must not introduce fake client/server adapter behavior.

### Integration Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: Phase 2 defines value models only. In-memory fake client/server conformance becomes useful after Phase 3 or Phase 7 introduces adapter behavior; adding such a harness here would either duplicate unit/contract round-trip tests or pull client/server behavior ahead of scope.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no CLI, runner, transport, supervisor, repository, or end-user workflow behavior changes in Phase 2.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: this phase should not require external services, network access, real process supervisors, scheduler environments, or filesystem-heavy evidence/import tests.

## Risks

- Protocol names, field names, and golden shapes become long-lived compatibility vocabulary, so ambiguous operation or error names would be expensive to change.
- Over-nesting current store/read-model records could accidentally freeze internal store behavior as the wire API.
- Under-modeling acknowledgement revision or fencing facts would make later clients prone to blind writes.
- Adding FastAPI/Pydantic validation for convenience would leak transport/framework concerns into core stores.
- Adding future workspace/resource/offline operation bodies too early would broaden Phase 2 beyond reviewable protocol foundations.
- Modeling every store method as its own protocol record would create a broad public API before route and repository adapters prove the needed granularity.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/pipeline/stores/test_authority_protocol.py
uv run pytest tests/contracts/test_authority_protocol_contract.py
uv run ruff check src/loom/pipeline/stores/authority_protocol.py src/loom/pipeline/stores/__init__.py tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/contracts/test_authority_protocol_contract.py tests/package/test_pipeline_store_api.py
uv run --extra config pyright
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: base protocol/version/envelope records, compact operation-kind and family payload records, public exports/import-boundary tests, then unit and contract golden-shape coverage.
- Tests to run with each slice: unit model tests after the new module exists, package tests after exports change, contract golden-shape tests after representative accepted/rejected responses are implemented, then Ruff and Pyright before PR preparation.
- Decisions the executor must not revisit: use stdlib dataclasses plus existing `PlainData` and explicit `to_dict`/`from_dict` helpers; keep protocol values independent from FastAPI, Pydantic, HTTP, service process internals, SQLite, and repository modules; use shared protocol envelopes and representative operation families instead of one public record per store method; keep transport, repository, registry, supervisor, runtime adoption, coordination service, resource admission, offline evidence, and import behavior out of scope.
- Conditions that require stopping for the manager: need for a new runtime dependency, need to change Phase 1 resolver categories, need to alter run/stage lifecycle enums, uncertainty about a public protocol field that would affect Phase 3 or Phase 7 compatibility, or any pressure to implement route/client/repository behavior early.
- Expanded-path refinement notes: completed on 2026-05-11. The refined plan narrows operation granularity to representative families, records stable envelope field names, limits nested public records to stable value vocabulary, and keeps adapter/conformance behavior out of Phase 2.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-11 by `loom_phase_refiner`
- PR review: used on 2026-05-11 by `loom_phase_reviewer`
- Blocker resolution: 2/3 used on 2026-05-11

## Completion Notes

- Draft plan: completed by `loom_phase_planner` on 2026-05-11.
- Final phase execution plan: completed by `loom_phase_planner` on 2026-05-11.
- Implementation summary: added transport-independent authority protocol value models, public store exports, package import-boundary coverage, unit validation/round-trip coverage, and contract golden-shape coverage.
- Implementation validation: `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/authority_protocol.py src/loom/pipeline/stores/__init__.py tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/contracts/test_authority_protocol_contract.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_store_errors.py` passed; `UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores/authority_protocol.py tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/contracts/test_authority_protocol_contract.py` passed with 0 errors; `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_store_errors.py tests/unit/loom/pipeline/stores/test_authority_protocol.py tests/contracts/test_authority_protocol_contract.py` passed with 25 tests. Final PR validation after blocker resolution: `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed; `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall 1636 passed, 12 skipped, and 1230 deselected.
- Refinement summary: tightened public envelope field names, operation-family granularity, nested-record reuse rules, and the no-adapter-conformance boundary for Phase 2. Implementation refinement added explicit `fencing_token` protocol envelope support, checked result lease/fencing consistency, expanded unit coverage for fenced envelopes, and added contract golden shapes for readiness, fenced mutation acknowledgements, snapshots, stale-generation rejections, and unsupported-capability rejections.
- Blocker-resolution summary: 2/3 used. The first pass fixed automated PR review's finding that readiness parsing accepted mismatched top-level and nested compatibility facts by rejecting conflicting `protocol_version` and `schema_version` aliases with focused unit coverage. The second pass fixed the GitHub CI blocker where concurrent local event appends could allocate duplicate event sequence numbers under parallel stage execution.
- PR preparation: PR #120 opened against `develop` from `codex/authority-protocol-models` on 2026-05-11 and verified with `gh pr view 120 --json baseRefName,headRefName,state,url`.
- Stack maintenance: not applicable yet.
- Remaining blockers: none.

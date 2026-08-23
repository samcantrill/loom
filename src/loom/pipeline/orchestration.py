"""Replay-safe ready-stage reconciliation without reservation or launch."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Iterator, Protocol, cast

from loom.pipeline.planning import ExecutionPlan, PlanAction, StagePlan
from loom.pipeline.planning.readiness import (
    AttemptReadiness,
    RetryAuthorization,
    evaluate_attempt_readiness,
)
from loom.pipeline.runtime.placement import (
    ExecutionRouteKind,
    ResolvedStagePlacement,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores.authority import (
    PreparedAttemptAuthority,
    PreparedAttemptReceipt,
    PreparedAttemptRequest,
)
from loom.pipeline.stores.read_models import (
    AuthoritativeRunSnapshot,
    BackendRevision,
    StageLifecycleSnapshot,
)
from loom.scheduling import (
    Candidate,
    SchedulingDecision,
    SchedulingKernel,
    WorkItem,
)
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data


COORDINATOR_STAGE_WORK_SCHEMA_VERSION = 1


class CoordinatorStoreError(ValueError):
    """Raised when coordinator projection state is invalid or incompatible."""


class SchedulingProjectionState(StrEnum):
    READY = "ready"
    WAIT = "wait"
    DECIDED = "decided"


@dataclass(frozen=True, slots=True)
class PreparationIntent:
    """Durable proof that the coordinator persisted before authority mutation."""

    request: PreparedAttemptRequest
    ready_at: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, PreparedAttemptRequest):
            raise CoordinatorStoreError(
                "preparation intent request must be PreparedAttemptRequest"
            )
        _integer(self.ready_at, "ready_at", minimum=0)

    def to_dict(self) -> dict[str, PlainData]:
        return {"request": self.request.to_dict(), "ready_at": self.ready_at}

    @classmethod
    def from_dict(cls, data: object) -> "PreparationIntent":
        mapping = _mapping(data, "PreparationIntent")
        _exact_fields(mapping, {"request", "ready_at"}, "PreparationIntent")
        return cls(
            request=PreparedAttemptRequest.from_dict(mapping["request"]),
            ready_at=_integer(mapping["ready_at"], "ready_at", minimum=0),
        )


@dataclass(frozen=True, slots=True)
class StageWorkRecord:
    """Rebuildable projection of one authority-confirmed ready attempt."""

    stage_work_id: str
    admission_id: str
    run_uri: str
    stage_name: str
    attempt: int
    attempt_id: str
    readiness_generation: str
    ready_at: int
    ready_order: int
    plan_fingerprint: str
    authority_revision: BackendRevision
    bound_inputs: Mapping[str, PlainData]
    upstream_commits: Mapping[str, str]
    placement: ResolvedStagePlacement
    scheduling_state: SchedulingProjectionState = SchedulingProjectionState.READY
    scheduling_diagnostics: Mapping[str, PlainData] = field(default_factory=dict)
    projection_revision: int = 1
    schema_version: int = COORDINATOR_STAGE_WORK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.stage_work_id, "stage_work_id"),
            (self.admission_id, "admission_id"),
            (self.run_uri, "run_uri"),
            (self.stage_name, "stage_name"),
            (self.attempt_id, "attempt_id"),
            (self.readiness_generation, "readiness_generation"),
            (self.plan_fingerprint, "plan_fingerprint"),
        ):
            _non_empty(value, name)
        _integer(self.attempt, "attempt", minimum=1)
        _integer(self.ready_at, "ready_at", minimum=0)
        _integer(self.ready_order, "ready_order", minimum=0)
        _integer(self.projection_revision, "projection_revision", minimum=1)
        if self.schema_version != COORDINATOR_STAGE_WORK_SCHEMA_VERSION:
            raise CoordinatorStoreError("unsupported stage-work schema version")
        if not isinstance(self.authority_revision, BackendRevision):
            raise CoordinatorStoreError("authority_revision must be a BackendRevision")
        if not isinstance(self.placement, ResolvedStagePlacement):
            raise CoordinatorStoreError("placement must be a ResolvedStagePlacement")
        object.__setattr__(
            self,
            "bound_inputs",
            _plain_mapping(self.bound_inputs, "bound_inputs"),
        )
        object.__setattr__(
            self,
            "upstream_commits",
            _string_mapping(self.upstream_commits, "upstream_commits"),
        )
        object.__setattr__(
            self,
            "scheduling_state",
            SchedulingProjectionState(self.scheduling_state),
        )
        object.__setattr__(
            self,
            "scheduling_diagnostics",
            _plain_mapping(self.scheduling_diagnostics, "scheduling_diagnostics"),
        )
        if self.stage_work_id != stage_work_identity(
            self.admission_id,
            self.stage_name,
            self.attempt_id,
            self.readiness_generation,
        ):
            raise CoordinatorStoreError(
                "stage_work_id does not match its immutable semantic key"
            )

    @property
    def placement_fingerprint(self) -> str:
        return self.placement.fingerprint

    def to_work_item(self) -> WorkItem:
        return WorkItem(
            stage_work_id=self.stage_work_id,
            ready_at=self.ready_at,
            requests=self.placement.scheduling_requests,
            hard_constraints=self.placement.hard_constraints,
            preferences=self.placement.preferences,
            enqueue_order=self.ready_order,
            topological_order=self.ready_order,
            stage_name=self.stage_name,
            attempt=self.attempt,
            pool_name=self.placement.pool_name,
            target=self.placement.target,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "stage_work_id": self.stage_work_id,
            "admission_id": self.admission_id,
            "run_uri": self.run_uri,
            "stage_name": self.stage_name,
            "attempt": self.attempt,
            "attempt_id": self.attempt_id,
            "readiness_generation": self.readiness_generation,
            "ready_at": self.ready_at,
            "ready_order": self.ready_order,
            "plan_fingerprint": self.plan_fingerprint,
            "authority_revision": self.authority_revision.to_dict(),
            "bound_inputs": thaw_plain_data(self.bound_inputs, path="bound_inputs"),
            "upstream_commits": dict(self.upstream_commits),
            "placement": self.placement.to_dict(),
            "scheduling_state": self.scheduling_state.value,
            "scheduling_diagnostics": thaw_plain_data(
                self.scheduling_diagnostics, path="scheduling_diagnostics"
            ),
            "projection_revision": self.projection_revision,
        }

    @classmethod
    def from_dict(cls, data: object) -> "StageWorkRecord":
        mapping = _mapping(data, "StageWorkRecord")
        allowed = {
            "schema_version",
            "stage_work_id",
            "admission_id",
            "run_uri",
            "stage_name",
            "attempt",
            "attempt_id",
            "readiness_generation",
            "ready_at",
            "ready_order",
            "plan_fingerprint",
            "authority_revision",
            "bound_inputs",
            "upstream_commits",
            "placement",
            "scheduling_state",
            "scheduling_diagnostics",
            "projection_revision",
        }
        _exact_fields(mapping, allowed, "StageWorkRecord")
        return cls(
            schema_version=_integer(
                mapping["schema_version"], "schema_version", minimum=1
            ),
            stage_work_id=_non_empty(mapping["stage_work_id"], "stage_work_id"),
            admission_id=_non_empty(mapping["admission_id"], "admission_id"),
            run_uri=_non_empty(mapping["run_uri"], "run_uri"),
            stage_name=_non_empty(mapping["stage_name"], "stage_name"),
            attempt=_integer(mapping["attempt"], "attempt", minimum=1),
            attempt_id=_non_empty(mapping["attempt_id"], "attempt_id"),
            readiness_generation=_non_empty(
                mapping["readiness_generation"], "readiness_generation"
            ),
            ready_at=_integer(mapping["ready_at"], "ready_at", minimum=0),
            ready_order=_integer(mapping["ready_order"], "ready_order", minimum=0),
            plan_fingerprint=_non_empty(
                mapping["plan_fingerprint"], "plan_fingerprint"
            ),
            authority_revision=BackendRevision.from_dict(mapping["authority_revision"]),
            bound_inputs=_plain_mapping(
                _mapping(mapping["bound_inputs"], "bound_inputs"), "bound_inputs"
            ),
            upstream_commits=_string_mapping(
                _mapping(mapping["upstream_commits"], "upstream_commits"),
                "upstream_commits",
            ),
            placement=ResolvedStagePlacement.from_dict(mapping["placement"]),
            scheduling_state=SchedulingProjectionState(
                _non_empty(mapping["scheduling_state"], "scheduling_state")
            ),
            scheduling_diagnostics=_plain_mapping(
                _mapping(mapping["scheduling_diagnostics"], "scheduling_diagnostics"),
                "scheduling_diagnostics",
            ),
            projection_revision=_integer(
                mapping["projection_revision"],
                "projection_revision",
                minimum=1,
            ),
        )


class CoordinatorStageWorkStore(Protocol):
    def create_or_return_intent(
        self, intent: PreparationIntent
    ) -> PreparationIntent: ...

    def find_intent(
        self, *, admission_id: str, stage_name: str, next_attempt: int
    ) -> PreparationIntent | None: ...

    def create_or_refresh(self, record: StageWorkRecord) -> StageWorkRecord: ...

    def list_stage_work(self) -> tuple[StageWorkRecord, ...]: ...


class InMemoryStageWorkStore:
    """Semantic in-memory implementation used for parity tests."""

    def __init__(self) -> None:
        self._intents: dict[str, PreparationIntent] = {}
        self._work: dict[str, StageWorkRecord] = {}

    def create_or_return_intent(self, intent: PreparationIntent) -> PreparationIntent:
        existing = self._intents.get(intent.request.operation_id)
        if existing is None:
            semantic = self.find_intent(
                admission_id=intent.request.admission_id,
                stage_name=intent.request.stage_name,
                next_attempt=intent.request.next_attempt,
            )
            if semantic is not None and semantic != intent:
                raise CoordinatorStoreError(
                    "preparation intent conflicts with its semantic attempt"
                )
            self._intents[intent.request.operation_id] = intent
            return intent
        if existing != intent:
            raise CoordinatorStoreError(
                "preparation intent conflicts with its durable request"
            )
        return existing

    def find_intent(
        self, *, admission_id: str, stage_name: str, next_attempt: int
    ) -> PreparationIntent | None:
        matches = (
            intent
            for intent in self._intents.values()
            if intent.request.admission_id == admission_id
            and intent.request.stage_name == stage_name
            and intent.request.next_attempt == next_attempt
        )
        return next(matches, None)

    def create_or_refresh(self, record: StageWorkRecord) -> StageWorkRecord:
        existing = self._work.get(record.stage_work_id)
        if existing is None:
            self._work[record.stage_work_id] = record
            return record
        _require_same_projection_identity(existing, record)
        refreshed = replace(
            record, projection_revision=existing.projection_revision + 1
        )
        self._work[record.stage_work_id] = refreshed
        return refreshed

    def list_stage_work(self) -> tuple[StageWorkRecord, ...]:
        return tuple(self._work[key] for key in sorted(self._work))


class SQLiteStageWorkStore:
    """Versioned SQLite projection store with semantic, non-CRUD operations."""

    def __init__(
        self, database_path: str | Path, *, _allow_initialize: bool = True
    ) -> None:
        self.path = Path(database_path)
        self._allow_initialize = _allow_initialize

    def _initialize(self) -> None:
        """Create this store's current schema at an explicit owner boundary."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _sqlite_connection(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_schema WHERE type = 'table' "
                    "AND name = 'coordinator_metadata'"
                ).fetchone()
                if exists is None:
                    _initialize_store(conn)
                else:
                    _raise_for_store_schema(conn)
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def _open_existing(self) -> None:
        """Verify the current schema without creating or repairing it."""

        if not self.path.is_file():
            raise CoordinatorStoreError("coordinator store is missing")
        with self._read_connection():
            pass

    def create_or_return_intent(self, intent: PreparationIntent) -> PreparationIntent:
        payload = _json_dumps(intent.to_dict())
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT intent_json FROM preparation_intents WHERE operation_id = ?",
                (intent.request.operation_id,),
            ).fetchone()
            if row is None:
                semantic_row = conn.execute(
                    """
                    SELECT intent_json FROM preparation_intents
                    WHERE admission_id = ? AND stage_name = ? AND next_attempt = ?
                    """,
                    (
                        intent.request.admission_id,
                        intent.request.stage_name,
                        intent.request.next_attempt,
                    ),
                ).fetchone()
                if semantic_row is not None:
                    semantic = PreparationIntent.from_dict(
                        _json_loads(cast(str, semantic_row["intent_json"]))
                    )
                    if semantic != intent:
                        raise CoordinatorStoreError(
                            "preparation intent conflicts with its semantic attempt"
                        )
                    return semantic
                conn.execute(
                    """
                    INSERT INTO preparation_intents (
                        operation_id, request_digest, admission_id, stage_name,
                        next_attempt, intent_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        intent.request.operation_id,
                        intent.request.request_digest,
                        intent.request.admission_id,
                        intent.request.stage_name,
                        intent.request.next_attempt,
                        payload,
                    ),
                )
                return intent
            existing = PreparationIntent.from_dict(
                _json_loads(cast(str, row["intent_json"]))
            )
            if existing != intent:
                raise CoordinatorStoreError(
                    "preparation intent conflicts with its durable request"
                )
            return existing

    def find_intent(
        self, *, admission_id: str, stage_name: str, next_attempt: int
    ) -> PreparationIntent | None:
        if not self.path.exists():
            return None
        with self._read_connection() as conn:
            row = conn.execute(
                """
                SELECT intent_json FROM preparation_intents
                WHERE admission_id = ? AND stage_name = ? AND next_attempt = ?
                """,
                (admission_id, stage_name, next_attempt),
            ).fetchone()
        return (
            None
            if row is None
            else PreparationIntent.from_dict(_json_loads(cast(str, row["intent_json"])))
        )

    def create_or_refresh(self, record: StageWorkRecord) -> StageWorkRecord:
        with self._transaction() as conn:
            row = conn.execute(
                """
                SELECT record_json FROM stage_work
                WHERE admission_id = ? AND stage_name = ? AND attempt_id = ?
                  AND readiness_generation = ?
                """,
                (
                    record.admission_id,
                    record.stage_name,
                    record.attempt_id,
                    record.readiness_generation,
                ),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO stage_work (
                        stage_work_id, admission_id, run_uri, stage_name,
                        attempt_id, readiness_generation, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.stage_work_id,
                        record.admission_id,
                        record.run_uri,
                        record.stage_name,
                        record.attempt_id,
                        record.readiness_generation,
                        _json_dumps(record.to_dict()),
                    ),
                )
                return record
            existing = StageWorkRecord.from_dict(
                _json_loads(cast(str, row["record_json"]))
            )
            if existing.stage_work_id != record.stage_work_id:
                raise CoordinatorStoreError("stage-work semantic key was re-keyed")
            _require_same_projection_identity(existing, record)
            refreshed = replace(
                record, projection_revision=existing.projection_revision + 1
            )
            conn.execute(
                "UPDATE stage_work SET record_json = ? WHERE stage_work_id = ?",
                (_json_dumps(refreshed.to_dict()), refreshed.stage_work_id),
            )
            return refreshed

    def list_stage_work(self) -> tuple[StageWorkRecord, ...]:
        if not self.path.exists():
            return ()
        with self._read_connection() as conn:
            rows = conn.execute(
                "SELECT record_json FROM stage_work ORDER BY stage_work_id"
            ).fetchall()
        return tuple(
            StageWorkRecord.from_dict(_json_loads(cast(str, row["record_json"])))
            for row in rows
        )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            if not self._allow_initialize:
                raise CoordinatorStoreError("coordinator store is missing")
            self.path.parent.mkdir(parents=True, exist_ok=True)
        initialize = not self.path.exists()
        with _sqlite_connection(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if initialize:
                    _initialize_store(conn)
                _raise_for_store_schema(conn)
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    @contextmanager
    def _read_connection(self) -> Iterator[sqlite3.Connection]:
        with _sqlite_connection(self.path) as conn:
            _raise_for_store_schema(conn)
            yield conn


class ControllerActionHandler(Protocol):
    def __call__(
        self, stage_plan: StagePlan, readiness: AttemptReadiness, /
    ) -> None: ...


class RunOrchestrator:
    """Reconcile authority truth into all ready work in one bounded window."""

    def __init__(
        self,
        *,
        authority: PreparedAttemptAuthority,
        store: CoordinatorStageWorkStore,
        owner_id: str,
    ) -> None:
        self.authority = authority
        self.store = store
        self.owner_id = _non_empty(owner_id, "owner_id")

    def reconcile(
        self,
        *,
        admission_id: str,
        plan: ExecutionPlan,
        authority_snapshot: AuthoritativeRunSnapshot,
        placements: Mapping[str, ResolvedStagePlacement],
        ready_at: int,
        max_work_items: int = 256,
        controller_action: ControllerActionHandler | None = None,
    ) -> tuple[StageWorkRecord, ...]:
        admission_id = _non_empty(admission_id, "admission_id")
        _integer(ready_at, "ready_at", minimum=0)
        _integer(max_work_items, "max_work_items", minimum=1)
        if plan.run_uri != authority_snapshot.run_uri:
            raise CoordinatorStoreError("plan and authority snapshot run differ")
        if len(plan.stage_plans) > max_work_items:
            raise CoordinatorStoreError("reconciliation work-item bound exceeded")

        stage_facts = {stage.stage_name: stage for stage in authority_snapshot.stages}
        completed = {
            name
            for name, stage in stage_facts.items()
            if stage.status in {StageStatus.SUCCEEDED, StageStatus.SKIPPED}
        }
        commits = {
            name: stage.latest_commit.commit_id
            for name, stage in stage_facts.items()
            if stage.latest_commit is not None
        }
        cancelled = authority_snapshot.status in {
            RunStatus.CANCELLED,
            RunStatus.FAILED,
            RunStatus.INTERRUPTED,
            RunStatus.SUCCEEDED,
        }
        self._refresh_projection_eligibility(
            admission_id=admission_id,
            run_uri=plan.run_uri,
            plan=plan,
            stage_facts=stage_facts,
            completed_stages=completed,
            committed_outputs=commits,
            run_cancelled=cancelled,
        )
        current_revision = authority_snapshot.revision
        projected: list[StageWorkRecord] = []
        for ready_order, stage_plan in enumerate(plan.ordered_stage_plans):
            stage = stage_facts.get(stage_plan.stage_name)
            current_attempt = (
                None
                if stage is None or not stage.attempts
                else replace(stage.attempts[-1], status=stage.status)
            )
            prior_intent = (
                None
                if current_attempt is None
                else self.store.find_intent(
                    admission_id=admission_id,
                    stage_name=stage_plan.stage_name,
                    next_attempt=current_attempt.attempt,
                )
            )
            retry = _retry_authorization(stage)
            readiness = evaluate_attempt_readiness(
                stage_plan,
                completed_stages=completed,
                committed_outputs={
                    upstream: commits[upstream]
                    for upstream in stage_plan.upstream_stages
                    if upstream in commits
                },
                current_attempt=current_attempt,
                run_cancelled=cancelled,
                retry_authorization=retry,
                prepared_generation=(
                    None
                    if prior_intent is None
                    else prior_intent.request.readiness_generation
                ),
            )
            if readiness is None:
                continue
            if prior_intent is not None and not _intent_matches_readiness(
                prior_intent, readiness
            ):
                continue
            if readiness.action is not PlanAction.RUN:
                if controller_action is not None:
                    controller_action(stage_plan, readiness)
                continue
            placement = placements.get(stage_plan.stage_name)
            if placement is None:
                raise CoordinatorStoreError(
                    f"ready stage {stage_plan.stage_name!r} has no resolved placement"
                )
            record, receipt = self._reconcile_ready(
                admission_id=admission_id,
                run_uri=plan.run_uri,
                readiness=readiness,
                placement=placement,
                ready_at=ready_at,
                ready_order=ready_order,
                expected_revision=current_revision,
                prior_intent=prior_intent,
            )
            projected.append(record)
            current_revision = _advance_revision_cursor(
                current_revision, receipt.attempt.revision
            )
        return tuple(projected)

    def decide(
        self,
        *,
        kernel: SchedulingKernel,
        candidates: Sequence[Candidate],
        as_of: int,
        admission_id: str | None = None,
    ) -> SchedulingDecision:
        """Produce pure decision data from the immutable durable projection."""

        work = tuple(
            record.to_work_item()
            for record in self.store.list_stage_work()
            if admission_id is None or record.admission_id == admission_id
            if record.scheduling_state is SchedulingProjectionState.READY
            if record.placement.route.kind is ExecutionRouteKind.MANAGED_AGENT
        )
        return kernel.decide(work=work, candidates=candidates, as_of=as_of)

    def _refresh_projection_eligibility(
        self,
        *,
        admission_id: str,
        run_uri: str,
        plan: ExecutionPlan,
        stage_facts: Mapping[str, StageLifecycleSnapshot],
        completed_stages: set[str],
        committed_outputs: Mapping[str, str],
        run_cancelled: bool,
    ) -> None:
        stage_plans = {stage.stage_name: stage for stage in plan.stage_plans}
        for record in self.store.list_stage_work():
            if record.admission_id != admission_id or record.run_uri != run_uri:
                continue
            stage = stage_facts.get(record.stage_name)
            stage_plan = stage_plans.get(record.stage_name)
            attempts = () if stage is None else stage.attempts
            status = None if stage is None else stage.status
            current_attempt = (
                None
                if stage is None or not attempts
                else replace(attempts[-1], status=stage.status)
            )
            current_attempt_id = attempts[-1].attempt_id if attempts else None
            intent = self.store.find_intent(
                admission_id=admission_id,
                stage_name=record.stage_name,
                next_attempt=record.attempt,
            )
            readiness = (
                None
                if stage_plan is None
                else evaluate_attempt_readiness(
                    stage_plan,
                    completed_stages=completed_stages,
                    committed_outputs={
                        upstream: committed_outputs[upstream]
                        for upstream in stage_plan.upstream_stages
                        if upstream in committed_outputs
                    },
                    current_attempt=current_attempt,
                    run_cancelled=run_cancelled,
                    retry_authorization=_retry_authorization(stage),
                    prepared_generation=(
                        None if intent is None else intent.request.readiness_generation
                    ),
                )
            )
            eligible = (
                status is StageStatus.PENDING
                and current_attempt_id == record.attempt_id
                and current_attempt is not None
                and current_attempt.attempt == record.attempt
                and intent is not None
                and _record_matches_intent(record, intent)
                and readiness is not None
                and readiness.action is PlanAction.RUN
                and _intent_matches_readiness(intent, readiness)
            )
            desired_state = (
                SchedulingProjectionState.READY
                if eligible
                else SchedulingProjectionState.WAIT
            )
            diagnostics: Mapping[str, PlainData] = (
                {}
                if eligible
                else {
                    "code": "authority_state_mismatch",
                    "authority_stage_status": (
                        None if status is None else cast(StageStatus, status).value
                    ),
                    "authority_attempt_id": current_attempt_id,
                }
            )
            if (
                record.scheduling_state is desired_state
                and record.scheduling_diagnostics == diagnostics
            ):
                continue
            self.store.create_or_refresh(
                replace(
                    record,
                    scheduling_state=desired_state,
                    scheduling_diagnostics=diagnostics,
                )
            )

    def _reconcile_ready(
        self,
        *,
        admission_id: str,
        run_uri: str,
        readiness: AttemptReadiness,
        placement: ResolvedStagePlacement,
        ready_at: int,
        ready_order: int,
        expected_revision: BackendRevision,
        prior_intent: PreparationIntent | None,
    ) -> tuple[StageWorkRecord, PreparedAttemptReceipt]:
        if readiness.next_attempt is None:
            raise CoordinatorStoreError("RUN readiness omitted next attempt")
        if prior_intent is None:
            request = _preparation_request(
                admission_id=admission_id,
                readiness=readiness,
                expected_revision=expected_revision,
                owner_id=self.owner_id,
            )
            intent = PreparationIntent(request=request, ready_at=ready_at)
        else:
            intent = prior_intent
            if (
                intent.request.readiness_generation != readiness.readiness_generation
                or intent.request.next_attempt != readiness.next_attempt
            ):
                raise CoordinatorStoreError(
                    "persisted preparation intent conflicts with current readiness"
                )
        intent = self.store.create_or_return_intent(intent)
        receipt = self.authority.ensure_prepared_attempt(run_uri, intent.request)
        stage_work_id = stage_work_identity(
            admission_id,
            receipt.attempt.stage_name,
            receipt.attempt.attempt_id,
            readiness.readiness_generation,
        )
        record = StageWorkRecord(
            stage_work_id=stage_work_id,
            admission_id=admission_id,
            run_uri=run_uri,
            stage_name=receipt.attempt.stage_name,
            attempt=receipt.attempt.attempt,
            attempt_id=receipt.attempt.attempt_id,
            readiness_generation=readiness.readiness_generation,
            ready_at=intent.ready_at,
            ready_order=ready_order,
            plan_fingerprint=intent.request.plan_fingerprint,
            authority_revision=receipt.attempt.revision,
            bound_inputs=intent.request.bound_inputs,
            upstream_commits=intent.request.upstream_commits,
            placement=placement,
        )
        return self.store.create_or_refresh(record), receipt


ReadyStageOrchestrator = RunOrchestrator


def stage_work_identity(
    admission_id: str,
    stage_name: str,
    attempt_id: str,
    readiness_generation: str,
) -> str:
    values = (admission_id, stage_name, attempt_id, readiness_generation)
    for value in values:
        _non_empty(value, "stage-work identity component")
    return hashlib.sha256("\0".join(values).encode()).hexdigest()


def _preparation_request(
    *,
    admission_id: str,
    readiness: AttemptReadiness,
    expected_revision: BackendRevision,
    owner_id: str,
) -> PreparedAttemptRequest:
    evidence = readiness.evidence_dict()
    digest_payload: dict[str, PlainData] = {
        "admission_id": admission_id,
        "expected_revision": expected_revision.to_dict(),
        "owner_id": owner_id,
        "readiness": evidence,
    }
    request_digest = hashlib.sha256(_json_dumps(digest_payload).encode()).hexdigest()
    return PreparedAttemptRequest(
        operation_id=f"prepare-{request_digest}",
        request_digest=request_digest,
        admission_id=admission_id,
        stage_name=readiness.stage_plan.stage_name,
        readiness_generation=readiness.readiness_generation,
        expected_revision=expected_revision,
        expected_stage_status=readiness.expected_stage_status,
        expected_attempt_id=readiness.expected_attempt_id,
        next_attempt=cast(int, readiness.next_attempt),
        owner_id=owner_id,
        plan_fingerprint=cast(str, evidence["plan_fingerprint"]),
        bound_inputs=readiness.bound_inputs,
        upstream_commits=readiness.upstream_commits,
        retry_decision_id=readiness.retry_decision_id,
    )


def _retry_authorization(stage: object) -> RetryAuthorization | None:
    if stage is None:
        return None
    decisions = getattr(stage, "retry_decisions", ())
    for decision in reversed(decisions):
        if decision.should_retry and decision.next_attempt is not None:
            return RetryAuthorization(decision.decision_id, decision.next_attempt)
    return None


def _advance_revision_cursor(
    current: BackendRevision, observed: BackendRevision
) -> BackendRevision:
    if observed.sequence > current.sequence:
        return observed
    if observed.sequence == current.sequence and observed.token != current.token:
        raise CoordinatorStoreError(
            "authority revision token changed without monotonic progress"
        )
    return current


def _record_matches_intent(record: StageWorkRecord, intent: PreparationIntent) -> bool:
    request = intent.request
    return (
        request.admission_id == record.admission_id
        and request.stage_name == record.stage_name
        and request.next_attempt == record.attempt
        and request.readiness_generation == record.readiness_generation
        and request.plan_fingerprint == record.plan_fingerprint
        and request.bound_inputs == record.bound_inputs
        and request.upstream_commits == record.upstream_commits
    )


def _intent_matches_readiness(
    intent: PreparationIntent, readiness: AttemptReadiness
) -> bool:
    request = intent.request
    evidence = readiness.evidence_dict()
    return (
        readiness.action is PlanAction.RUN
        and request.stage_name == readiness.stage_plan.stage_name
        and request.next_attempt == readiness.next_attempt
        and request.readiness_generation == readiness.readiness_generation
        and request.plan_fingerprint == evidence["plan_fingerprint"]
        and request.bound_inputs == readiness.bound_inputs
        and request.upstream_commits == readiness.upstream_commits
    )


def _require_same_projection_identity(
    existing: StageWorkRecord, incoming: StageWorkRecord
) -> None:
    existing_identity = (
        existing.stage_work_id,
        existing.admission_id,
        existing.run_uri,
        existing.stage_name,
        existing.attempt,
        existing.attempt_id,
        existing.readiness_generation,
        existing.ready_at,
        existing.ready_order,
        existing.plan_fingerprint,
        existing.authority_revision,
        existing.bound_inputs,
        existing.upstream_commits,
    )
    incoming_identity = (
        incoming.stage_work_id,
        incoming.admission_id,
        incoming.run_uri,
        incoming.stage_name,
        incoming.attempt,
        incoming.attempt_id,
        incoming.readiness_generation,
        incoming.ready_at,
        incoming.ready_order,
        incoming.plan_fingerprint,
        incoming.authority_revision,
        incoming.bound_inputs,
        incoming.upstream_commits,
    )
    if existing_identity != incoming_identity:
        raise CoordinatorStoreError(
            "stage-work refresh changed immutable readiness evidence"
        )


def _initialize_store(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE coordinator_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE preparation_intents (
            operation_id TEXT PRIMARY KEY,
            request_digest TEXT NOT NULL,
            admission_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            next_attempt INTEGER NOT NULL,
            intent_json TEXT NOT NULL,
            UNIQUE(admission_id, stage_name, next_attempt)
        );
        CREATE TABLE stage_work (
            stage_work_id TEXT PRIMARY KEY,
            admission_id TEXT NOT NULL,
            run_uri TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            readiness_generation TEXT NOT NULL,
            record_json TEXT NOT NULL,
            UNIQUE(admission_id, stage_name, attempt_id, readiness_generation)
        );
        """
    )
    conn.execute(
        "INSERT INTO coordinator_metadata(key, value) VALUES ('schema_version', ?)",
        (str(COORDINATOR_STAGE_WORK_SCHEMA_VERSION),),
    )


def _raise_for_store_schema(conn: sqlite3.Connection) -> None:
    try:
        row = conn.execute(
            "SELECT value FROM coordinator_metadata WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise CoordinatorStoreError(
            "coordinator store schema metadata is missing"
        ) from exc
    if row is None:
        raise CoordinatorStoreError("coordinator store schema metadata is missing")
    try:
        version = int(cast(str, row["value"]))
    except (TypeError, ValueError) as exc:
        raise CoordinatorStoreError(
            "coordinator store schema version is invalid"
        ) from exc
    if version != COORDINATOR_STAGE_WORK_SCHEMA_VERSION:
        raise CoordinatorStoreError(
            f"unsupported coordinator store schema version {version}"
        )
    required = {"preparation_intents", "stage_work"}
    tables = {
        cast(str, row["name"])
        for row in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
    }
    if not required.issubset(tables):
        raise CoordinatorStoreError("coordinator store schema is incomplete")


@contextmanager
def _sqlite_connection(path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise CoordinatorStoreError(f"{name} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _exact_fields(mapping: Mapping[str, object], allowed: set[str], name: str) -> None:
    missing = allowed - set(mapping)
    unknown = set(mapping) - allowed
    if missing or unknown:
        raise CoordinatorStoreError(f"{name} fields are invalid")


def _non_empty(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CoordinatorStoreError(f"{name} must be a non-empty string")
    return value


def _integer(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CoordinatorStoreError(f"{name} must be an integer >= {minimum}")
    return value


def _plain_mapping(value: Mapping[str, object], name: str) -> Mapping[str, PlainData]:
    frozen = freeze_plain_data(value, path=name)
    if not isinstance(frozen, Mapping):
        raise CoordinatorStoreError(f"{name} must be a mapping")
    return frozen


def _string_mapping(value: Mapping[str, object], name: str) -> Mapping[str, str]:
    if any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item
        for key, item in value.items()
    ):
        raise CoordinatorStoreError(f"{name} must contain non-empty string pairs")
    return dict(sorted(cast(Mapping[str, str], value).items()))


def _json_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str) -> object:
    return json.loads(value)


__all__ = [
    "COORDINATOR_STAGE_WORK_SCHEMA_VERSION",
    "CoordinatorStageWorkStore",
    "CoordinatorStoreError",
    "InMemoryStageWorkStore",
    "PreparationIntent",
    "ReadyStageOrchestrator",
    "RunOrchestrator",
    "SQLiteStageWorkStore",
    "SchedulingProjectionState",
    "StageWorkRecord",
    "stage_work_identity",
]

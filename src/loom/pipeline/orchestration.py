"""Durable ready-stage work projection; deliberately no assignment or launch."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loom.pipeline.planning import PlanAction
from loom.pipeline.planning.readiness import AttemptReadiness
from loom.pipeline.stores.authority import PreparedAttemptReceipt
from loom.serialization import PlainData


@dataclass(frozen=True, slots=True)
class StageWorkRecord:
    stage_work_id: str
    run_uri: str
    stage_name: str
    attempt_id: str
    readiness_generation: str
    placement: Mapping[str, PlainData]


class PreparedAttemptAuthority(Protocol):
    def ensure_prepared_attempt(self, run_uri: str, stage_name: str, *, operation_id: str,
        request_digest: str, readiness_generation: str, owner_id: str) -> PreparedAttemptReceipt: ...


class SQLiteStageWorkStore:
    """Small rebuildable coordinator projection store.

    It has no lifecycle or reservation columns: authority remains truth.
    """
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def create_or_return(self, record: StageWorkRecord) -> StageWorkRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS preparation_intents (operation_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS stage_work (stage_work_id TEXT PRIMARY KEY, run_uri TEXT NOT NULL, stage_name TEXT NOT NULL, attempt_id TEXT NOT NULL, readiness_generation TEXT NOT NULL, placement_json TEXT NOT NULL, UNIQUE(run_uri, stage_name, attempt_id, readiness_generation))")
            row = conn.execute("SELECT stage_work_id, run_uri, stage_name, attempt_id, readiness_generation, placement_json FROM stage_work WHERE run_uri=? AND stage_name=? AND attempt_id=? AND readiness_generation=?", (record.run_uri, record.stage_name, record.attempt_id, record.readiness_generation)).fetchone()
            if row is None:
                conn.execute("INSERT INTO stage_work VALUES (?, ?, ?, ?, ?, ?)", (record.stage_work_id, record.run_uri, record.stage_name, record.attempt_id, record.readiness_generation, json.dumps(dict(record.placement), sort_keys=True)))
                return record
            return StageWorkRecord(*row[:5], placement=json.loads(row[5]))

    def create_or_return_intent(self, *, operation_id: str, request_digest: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS preparation_intents (operation_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL)")
            row = conn.execute("SELECT request_digest FROM preparation_intents WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO preparation_intents VALUES (?, ?)", (operation_id, request_digest))
            elif row[0] != request_digest:
                raise ValueError("preparation intent conflicts with its request digest")

    def list(self) -> tuple[StageWorkRecord, ...]:
        if not self.path.exists():
            return ()
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT stage_work_id, run_uri, stage_name, attempt_id, readiness_generation, placement_json FROM stage_work ORDER BY stage_work_id").fetchall()
        return tuple(StageWorkRecord(*row[:5], placement=json.loads(row[5])) for row in rows)


class ReadyStageOrchestrator:
    """Persist intent, obtain the atomic authority receipt, then project work."""
    def __init__(self, *, authority: PreparedAttemptAuthority, store: SQLiteStageWorkStore, owner_id: str) -> None:
        self.authority, self.store, self.owner_id = authority, store, owner_id

    def reconcile(self, *, run_uri: str, readiness: AttemptReadiness, placement: Mapping[str, PlainData]) -> StageWorkRecord | None:
        if readiness.action is not PlanAction.RUN:
            return None
        digest_source = {"run_uri": run_uri, "stage_name": readiness.stage_plan.stage_name, "generation": readiness.readiness_generation, "inputs": dict(readiness.bound_inputs)}
        request_digest = hashlib.sha256(json.dumps(digest_source, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        operation_id = f"prepare-{request_digest}"
        self.store.create_or_return_intent(operation_id=operation_id, request_digest=request_digest)
        receipt = self.authority.ensure_prepared_attempt(run_uri, readiness.stage_plan.stage_name, operation_id=operation_id, request_digest=request_digest, readiness_generation=readiness.readiness_generation, owner_id=self.owner_id)
        semantic_key = f"{run_uri}\0{receipt.attempt.stage_name}\0{receipt.attempt.attempt_id}\0{readiness.readiness_generation}"
        return self.store.create_or_return(StageWorkRecord(hashlib.sha256(semantic_key.encode()).hexdigest(), run_uri, receipt.attempt.stage_name, receipt.attempt.attempt_id, readiness.readiness_generation, dict(placement)))


__all__ = ["ReadyStageOrchestrator", "SQLiteStageWorkStore", "StageWorkRecord"]

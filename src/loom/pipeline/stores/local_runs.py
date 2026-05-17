"""Local filesystem run-store implementation."""

from __future__ import annotations

import hashlib
import os
import socket
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from threading import Lock
from typing import cast

from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.pipeline.events import PipelineEvent, PipelineEventError, PipelineEventRecord
from loom.pipeline.locks import RunLockRecord, RunLockValidationError
from loom.pipeline.reliability import (
    ReliabilityStatusDetail,
    RetryDecisionRecord,
    StageAttemptTransaction,
    TimeoutOutcomeRecord,
)
from loom.pipeline.submitted import (
    SubmittedOperationError,
    SubmittedOperationRecord,
    latest_active_submitted_operation,
    latest_submitted_operation,
    sort_submitted_operations,
    validate_submission_id,
)
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.serialization import (
    PlainData,
    ensure_plain_data,
    json_loads,
    stable_json_dumps,
    thaw_plain_data,
)
from loom.serialization.errors import DeserializationError, PlainDataError
from loom.timestamps import parse_timestamp, utc_timestamp

from ._paths import (
    VALID_CONFIG_SNAPSHOTS,
    VALID_PROVENANCE_NAMES,
    ensure_subpath,
    validate_output_name,
    validate_config_snapshot_name,
    validate_log_stream,
    validate_provenance_name,
    validate_safe_relative_path,
    validate_stage_name,
)
from .atomic import atomic_write_json, atomic_write_text
from .errors import (
    ArtifactStoreError,
    CorruptStoreDocumentError,
    MissingStoreDocumentError,
    PreparedRunStorePayloadError,
    RunAlreadyExistsError,
    RunLockConflictError,
    RunLockReleaseError,
    RunNotFoundError,
    UnsafeStorePathError,
)
from .indexes import artifact_index_from_dict, artifact_index_to_dict
from .inspection import RunStageInspection, RunStateInspection, ensure_failure_payload
from .prepared_run import validate_prepared_run_document
from .read_models import ReliabilityPolicyFact
from .reliability_facts import (
    reliability_payload_matches,
    reliability_policy_fact_key,
    reliability_record_stage_name,
    reliability_status_detail_key,
    validate_policy_fact_run,
    validate_retry_decision_run,
    validate_status_detail_run,
    validate_timeout_outcome_run,
    validate_transaction_run,
)
from .run_store import RunFreshnessError, RunFreshnessRecord
from .run_uri import (
    allocate_local_run_uri,
    path_to_run_uri,
    run_uri_to_path,
    validate_run_uri,
)

_SCHEMA_VERSION = 1

_RUN_WRAPPER_FIELDS = frozenset({"schema_version", "run_uri", "created_at", "metadata"})
_PLAN_WRAPPER_FIELDS = frozenset({"schema_version", "run_uri", "updated_at", "plan"})
_RUNTIME_METADATA_WRAPPER_FIELDS = frozenset(
    {"schema_version", "run_uri", "updated_at", "runtime"}
)
_ARTIFACT_INDEX_WRAPPER_FIELDS = frozenset(
    {"schema_version", "run_uri", "updated_at", "artifacts"}
)
_COMPOSITION_MANIFEST_WRAPPER_FIELDS = frozenset(
    {"schema_version", "run_uri", "created_at", "composition_manifest"}
)
_RECIPE_MANIFEST_WRAPPER_FIELDS = frozenset(
    {"schema_version", "run_uri", "created_at", "recipe_manifest"}
)
_PROVENANCE_WRAPPER_FIELDS = frozenset(
    {"schema_version", "run_uri", "kind", "created_at", "provenance"}
)
_FRESHNESS_WRAPPER_FIELDS = frozenset(
    {"schema_version", "run_uri", "token", "updated_at", "revision", "reason"}
)


class LocalRunStore:
    """Filesystem-backed local run layout writer and reader."""

    def __init__(self, root: str | Path = "runs") -> None:
        self.root = Path(root)
        self._event_lock = Lock()

    def resolve_run_uri(self, run_uri: str) -> str:
        return validate_run_uri(run_uri)

    def allocate_run_uri(self) -> str:
        return allocate_local_run_uri(self.root)

    def create_run(
        self, run_uri: str, *, metadata: Mapping[str, PlainData] | None = None
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        run_dir = self.local_run_dir(run_uri_text)
        if run_dir.exists():
            raise RunAlreadyExistsError(f"run directory already exists: {run_dir}")

        try:
            (run_dir / "config").mkdir(parents=True, exist_ok=True)
            (run_dir / "provenance").mkdir(parents=True, exist_ok=True)
            (run_dir / "stages").mkdir(parents=True, exist_ok=True)
            (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CorruptStoreDocumentError(
                f"Unable to initialize run directory structure {run_dir}: {exc}"
            ) from exc

        self.write_run_user_metadata(run_uri_text, metadata or {})

    def open_run(self, run_uri: str) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        run_dir = self.local_run_dir(run_uri_text)
        if not run_dir.is_dir():
            raise RunNotFoundError(f"run not found: {run_uri_text}")
        run_json = run_dir / "run.json"
        if not run_json.exists():
            raise MissingStoreDocumentError(
                f"Missing required run metadata at {run_json}"
            )
        self._read_run_wrapper(run_uri_text)

    def run_uri_exists(self, run_uri: str) -> bool:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        return self.local_run_dir(run_uri_text).exists()

    def list_run_stages(self, run_uri: str) -> tuple[str, ...]:
        """Return discovered stage names for a persisted local run."""

        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        self.open_run(run_uri_text)
        stages_dir = self.local_run_dir(run_uri_text) / "stages"
        if not stages_dir.exists():
            return ()
        if not stages_dir.is_dir():
            raise CorruptStoreDocumentError(f"Expected stage directory at {stages_dir}")

        stage_names: list[str] = []
        for child in sorted(stages_dir.iterdir(), key=lambda path: path.name):
            if not child.is_dir():
                raise CorruptStoreDocumentError(f"Expected stage directory at {child}")
            stage_names.append(validate_stage_name(child.name, field="stage_name"))
        return tuple(stage_names)

    def inspect_run_state(self, run_uri: str) -> RunStateInspection:
        """Return a read-only scan of persisted local run state."""

        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        self.open_run(run_uri_text)
        stage_inspections = tuple(
            self._inspect_stage_state(run_uri_text, stage_name)
            for stage_name in self.list_run_stages(run_uri_text)
        )
        return RunStateInspection(
            run_uri=run_uri_text,
            run_status=self.read_run_status(run_uri_text),
            stage_inspections=stage_inspections,
            artifact_count=len(self.read_artifact_index(run_uri_text)),
            submitted_operations=self.list_submitted_operations(run_uri_text),
        )

    def local_run_dir(self, run_uri: str) -> Path:
        return run_uri_to_path(run_uri)

    def local_stage_dir(self, run_uri: str, stage_name: str) -> Path:
        return (
            self.local_run_dir(run_uri)
            / "stages"
            / validate_stage_name(stage_name, field="stage_name")
        )

    def local_artifact_root(self, run_uri: str) -> Path:
        return self.local_run_dir(run_uri) / "artifacts"

    def local_stage_artifact_dir(self, run_uri: str, stage_name: str) -> Path:
        return self.local_artifact_root(run_uri) / validate_stage_name(
            stage_name, field="stage_name"
        )

    def local_config_path(self, run_uri: str, name: str) -> Path:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        validated_name = validate_config_snapshot_name(name)
        return (
            self.local_run_dir(run_uri_text)
            / "config"
            / VALID_CONFIG_SNAPSHOTS[validated_name]
        )

    def local_provenance_path(self, run_uri: str, name: str) -> Path:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        validated_name = validate_provenance_name(name)
        return (
            self.local_run_dir(run_uri_text)
            / "provenance"
            / VALID_PROVENANCE_NAMES[validated_name]
        )

    def local_stage_log_path(self, run_uri: str, stage_name: str, stream: str) -> Path:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        validated_stream = validate_log_stream(stream)
        return (
            self.local_stage_dir(run_uri_text, stage_name)
            / "logs"
            / f"{validated_stream}.log"
        )

    def local_stage_worker_request_path(self, run_uri: str, stage_name: str) -> Path:
        return self.local_stage_dir(run_uri, stage_name) / "worker_request.json"

    def local_stage_worker_result_path(self, run_uri: str, stage_name: str) -> Path:
        return self.local_stage_dir(run_uri, stage_name) / "worker_result.json"

    def local_stage_workspace_dir(self, run_uri: str, stage_name: str) -> Path:
        return self.local_stage_dir(run_uri, stage_name) / "workspace"

    def local_generated_artifact_path(self, run_uri: str, relative_path: str) -> Path:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        relative = validate_safe_relative_path(relative_path, field="relative_path")
        run_dir = self.local_run_dir(run_uri_text)
        return ensure_subpath(run_dir.joinpath(*relative.parts), run_dir)

    def local_run_freshness_path(self, run_uri: str) -> Path:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        return self.local_run_dir(run_uri_text) / "freshness.json"

    def prepare_stage_workspace(self, run_uri: str, stage_name: str) -> None:
        self.local_stage_workspace_dir(run_uri, stage_name).mkdir(
            parents=True, exist_ok=True
        )

    def read_run_document(self, run_uri: str) -> dict[str, PlainData]:
        return self._read_run_wrapper(validate_run_uri(run_uri, field="run_uri"))

    def read_run_user_metadata(self, run_uri: str) -> dict[str, PlainData]:
        return cast(
            dict[str, PlainData],
            self._read_run_wrapper(validate_run_uri(run_uri, field="run_uri"))[
                "metadata"
            ],
        )

    def write_run_user_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        run_dir = self.local_run_dir(run_uri_text)
        if not run_dir.exists():
            raise RunNotFoundError(f"run not found: {run_uri_text}")
        normalized_metadata = ensure_plain_data(metadata, path="metadata")
        if not isinstance(normalized_metadata, dict):
            raise UnsafeStorePathError(
                f"run metadata must be a mapping, got {type(normalized_metadata)!r}"
            )

        if run_dir.exists() and (run_dir / "run.json").exists():
            existing = self._read_run_wrapper(run_uri_text)
            created_at = existing["created_at"]
        else:
            created_at = utc_timestamp()

        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "created_at": created_at,
            "metadata": normalized_metadata,
        }
        atomic_write_json(run_dir / "run.json", payload)
        self._touch_run_freshness(run_uri_text, reason="run_metadata")

    def read_run_freshness(self, run_uri: str) -> RunFreshnessRecord | None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        path = self.local_run_freshness_path(run_uri_text)
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(data, path, label="freshness document")
        _validate_exact_document_fields(
            payload,
            path,
            label="freshness document",
            fields=_FRESHNESS_WRAPPER_FIELDS,
        )
        _require_run_uri_field(
            payload, path, expected=run_uri_text, label="freshness document"
        )
        try:
            return RunFreshnessRecord.from_dict(payload)
        except RunFreshnessError as exc:
            raise CorruptStoreDocumentError(
                f"Malformed freshness document at {path}: {exc}"
            ) from exc

    def read_run_status(self, run_uri: str) -> RunStatusRecord | None:
        run_dir = self.local_run_dir(run_uri)
        status_path = run_dir / "status.json"
        data = self._read_optional_json(status_path)
        if data is None:
            return None
        try:
            return RunStatusRecord.from_dict(data)
        except Exception as exc:
            raise CorruptStoreDocumentError(
                f"Malformed run status at {status_path}: {exc}"
            ) from exc

    def write_run_status(self, run_uri: str, status: RunStatusRecord) -> None:
        self._validate_run_uri_for_status(run_uri, status.run_uri)
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        payload = status.to_dict()
        atomic_write_json(self.local_run_dir(run_uri_text) / "status.json", payload)
        self._touch_run_freshness(run_uri_text, reason="run_status")

    def read_plan(self, run_uri: str) -> dict[str, PlainData] | None:
        run_dir = self.local_run_dir(run_uri)
        path = run_dir / "plan.json"
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(data, path, label="plan document")
        _validate_exact_document_fields(
            payload, path, label="plan document", fields=_PLAN_WRAPPER_FIELDS
        )
        _require_schema_version(payload, path, label="plan document")
        _require_run_uri_field(payload, path, expected=run_uri, label="plan document")
        _require_timestamp_field(payload, path, "updated_at", label="plan document")
        return _require_mapping_field(payload, path, "plan", label="plan document")

    def write_plan(self, run_uri: str, plan: Mapping[str, PlainData]) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "updated_at": utc_timestamp(),
            "plan": ensure_plain_data(plan, path="plan"),
        }
        atomic_write_json(self.local_run_dir(run_uri_text) / "plan.json", payload)
        self._touch_run_freshness(run_uri_text, reason="plan")

    def read_prepared_run(self, run_uri: str) -> dict[str, PlainData] | None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        path = self.local_run_dir(run_uri_text) / "prepared_run.json"
        data = self._read_optional_json(path)
        if data is None:
            return None
        try:
            return validate_prepared_run_document(
                data, expected_run_uri=run_uri_text, field="prepared_run"
            )
        except PreparedRunStorePayloadError as exc:
            raise CorruptStoreDocumentError(
                f"Malformed prepared-run document at {path}: {exc}"
            ) from exc

    def write_prepared_run(
        self, run_uri: str, prepared_run: Mapping[str, PlainData]
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        path = self.local_run_dir(run_uri_text) / "prepared_run.json"
        payload = validate_prepared_run_document(
            prepared_run, expected_run_uri=run_uri_text, field="prepared_run"
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri_text, reason="prepared_run")

    def read_runtime_metadata(self, run_uri: str) -> dict[str, PlainData] | None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        path = self.local_run_dir(run_uri_text) / "runtime.json"
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(
            data, path, label="runtime metadata document"
        )
        _validate_exact_document_fields(
            payload,
            path,
            label="runtime metadata document",
            fields=_RUNTIME_METADATA_WRAPPER_FIELDS,
        )
        _require_schema_version(payload, path, label="runtime metadata document")
        _require_run_uri_field(
            payload,
            path,
            expected=run_uri_text,
            label="runtime metadata document",
        )
        _require_timestamp_field(
            payload, path, "updated_at", label="runtime metadata document"
        )
        return _require_mapping_field(
            payload, path, "runtime", label="runtime metadata document"
        )

    def write_runtime_metadata(
        self, run_uri: str, metadata: Mapping[str, PlainData]
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        normalized = ensure_plain_data(metadata, path="runtime")
        if not isinstance(normalized, dict):
            raise UnsafeStorePathError("runtime metadata must be a mapping")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "updated_at": utc_timestamp(),
            "runtime": normalized,
        }
        atomic_write_json(self.local_run_dir(run_uri_text) / "runtime.json", payload)
        self._touch_run_freshness(run_uri_text, reason="runtime_metadata")

    def write_submitted_operation(
        self, run_uri: str, record: SubmittedOperationRecord
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        if not isinstance(record, SubmittedOperationRecord):
            raise UnsafeStorePathError("submitted operation must be a record")
        if record.run_uri != run_uri_text:
            raise UnsafeStorePathError(
                f"run_uri mismatch for submitted operation: {record.run_uri} != {run_uri_text}"
            )
        submission_id = validate_submission_id(record.submission_id)
        path = self._submitted_operation_path(
            run_uri_text, submission_id, create_parent=True
        )
        atomic_write_json(path, record.to_dict())
        self._touch_run_freshness(run_uri_text, reason="submitted_operation")

    def read_submitted_operation(
        self, run_uri: str, submission_id: str
    ) -> SubmittedOperationRecord | None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        submission_id_text = validate_submission_id(submission_id)
        path = self._submitted_operation_path(run_uri_text, submission_id_text)
        data = self._read_optional_json(path)
        if data is None:
            return None
        return self._submitted_operation_from_payload(run_uri_text, path, data)

    def list_submitted_operations(
        self, run_uri: str
    ) -> tuple[SubmittedOperationRecord, ...]:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        self.open_run(run_uri_text)
        directory = self.local_run_dir(run_uri_text) / "submitted_operations"
        if not directory.exists():
            return ()
        if not directory.is_dir():
            raise CorruptStoreDocumentError(f"Expected directory at {directory}")
        records: list[SubmittedOperationRecord] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix != ".json":
                raise CorruptStoreDocumentError(
                    f"Expected submitted-operation JSON file at {path}"
                )
            data = self._read_optional_json(path)
            if data is None:
                continue
            records.append(
                self._submitted_operation_from_payload(run_uri_text, path, data)
            )
        return sort_submitted_operations(records)

    def latest_submitted_operation(
        self, run_uri: str
    ) -> SubmittedOperationRecord | None:
        return latest_submitted_operation(self.list_submitted_operations(run_uri))

    def latest_active_submitted_operation(
        self, run_uri: str
    ) -> SubmittedOperationRecord | None:
        return latest_active_submitted_operation(
            self.list_submitted_operations(run_uri)
        )

    def write_reliability_policy_fact(
        self, run_uri: str, fact: ReliabilityPolicyFact
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        if not isinstance(fact, ReliabilityPolicyFact):
            raise UnsafeStorePathError("reliability policy fact must be a record")
        validate_policy_fact_run(fact, run_uri_text)
        self._write_reliability_fact(
            self._reliability_family_path(
                run_uri_text,
                "policy_facts",
                reliability_policy_fact_key(fact),
                create_parent=True,
            ),
            fact.to_dict(),
            reason="reliability_policy_fact",
        )

    def list_reliability_policy_facts(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityPolicyFact, ...]:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        stage_name_text = (
            None
            if stage_name is None
            else validate_stage_name(stage_name, field="stage_name")
        )
        records = self._list_reliability_records(
            run_uri_text,
            family="policy_facts",
            parser=ReliabilityPolicyFact.from_dict,
        )
        filtered = (
            record
            for record in records
            if stage_name_text is None or record.stage_name == stage_name_text
        )
        return tuple(
            sorted(
                filtered,
                key=lambda record: (
                    record.scope.value,
                    record.stage_name or "",
                    record.attempt or 0,
                    record.recorded_at,
                ),
            )
        )

    def write_reliability_status_detail(
        self, run_uri: str, detail: ReliabilityStatusDetail
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        if not isinstance(detail, ReliabilityStatusDetail):
            raise UnsafeStorePathError("reliability status detail must be a record")
        validate_status_detail_run(detail, run_uri_text)
        self._write_reliability_fact(
            self._reliability_family_path(
                run_uri_text,
                "status_details",
                reliability_status_detail_key(detail),
                create_parent=True,
            ),
            detail.to_dict(),
            reason="reliability_status_detail",
        )

    def list_reliability_status_details(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[ReliabilityStatusDetail, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            family="status_details",
            parser=ReliabilityStatusDetail.from_dict,
            stage_name=stage_name,
            sort_key=lambda record: (
                record.stage_id,
                record.attempt,
                record.created_at,
            ),
        )

    def write_stage_attempt_transaction(
        self, run_uri: str, transaction: StageAttemptTransaction
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        if not isinstance(transaction, StageAttemptTransaction):
            raise UnsafeStorePathError("stage attempt transaction must be a record")
        validate_transaction_run(transaction, run_uri_text)
        self._write_reliability_fact(
            self._reliability_family_path(
                run_uri_text,
                "transactions",
                _reliability_id_key(transaction.transaction_id),
                create_parent=True,
            ),
            transaction.to_dict(),
            reason="reliability_transaction",
        )

    def read_transaction_chain(
        self, run_uri: str, transaction_id: str
    ) -> tuple[StageAttemptTransaction, ...]:
        if not isinstance(transaction_id, str) or not transaction_id:
            raise UnsafeStorePathError("transaction_id must be a non-empty string")
        transactions = {
            transaction.transaction_id: transaction
            for transaction in self.list_stage_attempt_transactions(run_uri)
        }
        current = transactions.get(transaction_id)
        if current is None:
            return ()
        chain: list[StageAttemptTransaction] = []
        seen: set[str] = set()
        while current is not None:
            if current.transaction_id in seen:
                raise CorruptStoreDocumentError(
                    f"reliability transaction chain contains a cycle at {transaction_id!r}"
                )
            seen.add(current.transaction_id)
            chain.append(current)
            parent_id = current.causal_parent_id
            current = None if parent_id is None else transactions.get(parent_id)
        return tuple(reversed(chain))

    def list_stage_attempt_transactions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[StageAttemptTransaction, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            family="transactions",
            parser=StageAttemptTransaction.from_dict,
            stage_name=stage_name,
            sort_key=lambda record: (
                record.stage_id,
                record.attempt,
                record.transaction_id,
            ),
        )

    def write_retry_decision(
        self, run_uri: str, decision: RetryDecisionRecord
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        if not isinstance(decision, RetryDecisionRecord):
            raise UnsafeStorePathError("retry decision must be a record")
        validate_retry_decision_run(decision, run_uri_text)
        self._write_reliability_fact(
            self._reliability_family_path(
                run_uri_text,
                "retry_decisions",
                _reliability_id_key(decision.decision_id),
                create_parent=True,
            ),
            decision.to_dict(),
            reason="retry_decision",
        )

    def list_retry_decisions(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[RetryDecisionRecord, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            family="retry_decisions",
            parser=RetryDecisionRecord.from_dict,
            stage_name=stage_name,
            sort_key=lambda record: (
                record.status.stage_id,
                record.status.attempt,
                record.decision_id,
            ),
        )

    def write_timeout_outcome(
        self, run_uri: str, outcome: TimeoutOutcomeRecord
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        if not isinstance(outcome, TimeoutOutcomeRecord):
            raise UnsafeStorePathError("timeout outcome must be a record")
        validate_timeout_outcome_run(outcome, run_uri_text)
        self._write_reliability_fact(
            self._reliability_family_path(
                run_uri_text,
                "timeout_outcomes",
                _reliability_id_key(outcome.outcome_id),
                create_parent=True,
            ),
            outcome.to_dict(),
            reason="timeout_outcome",
        )

    def list_timeout_outcomes(
        self, run_uri: str, *, stage_name: str | None = None
    ) -> tuple[TimeoutOutcomeRecord, ...]:
        return self._list_stage_reliability_records(
            run_uri,
            family="timeout_outcomes",
            parser=TimeoutOutcomeRecord.from_dict,
            stage_name=stage_name,
            sort_key=lambda record: (
                record.status.stage_id,
                record.status.attempt,
                record.outcome_id,
            ),
        )

    def read_artifact_index(self, run_uri: str) -> dict[str, ArtifactRef]:
        run_dir = self.local_run_dir(run_uri)
        path = run_dir / "artifacts.json"
        data = self._read_optional_json(path)
        if data is None:
            return {}
        payload = _require_document_object(data, path, label="artifact index document")
        _validate_exact_document_fields(
            payload,
            path,
            label="artifact index document",
            fields=_ARTIFACT_INDEX_WRAPPER_FIELDS,
        )
        _require_schema_version(payload, path, label="artifact index document")
        _require_run_uri_field(
            payload, path, expected=run_uri, label="artifact index document"
        )
        _require_timestamp_field(
            payload, path, "updated_at", label="artifact index document"
        )
        artifacts = _require_mapping_field(
            payload, path, "artifacts", label="artifact index document"
        )
        try:
            return artifact_index_from_dict(artifacts)
        except ArtifactStoreError as exc:
            raise CorruptStoreDocumentError(
                f"Malformed artifact index at {path}: {exc}"
            ) from exc

    def write_artifact_index(
        self, run_uri: str, index: Mapping[str, ArtifactRef]
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "updated_at": utc_timestamp(),
            "artifacts": artifact_index_to_dict(index),
        }
        atomic_write_json(self.local_run_dir(run_uri_text) / "artifacts.json", payload)
        self._touch_run_freshness(run_uri_text, reason="artifact_index")

    def read_config_snapshot(self, run_uri: str, name: str) -> str | None:
        path = self.local_config_path(run_uri, name)
        if not path.exists():
            return None
        if not path.is_file():
            raise CorruptStoreDocumentError(f"Expected file at {path}")
        return path.read_text(encoding="utf-8")

    def write_config_snapshot(self, run_uri: str, name: str, content: str) -> None:
        validate_run_uri(run_uri, field="run_uri")
        if not isinstance(content, str):
            raise UnsafeStorePathError(
                f"config snapshot content must be string, got {type(content)!r}"
            )
        atomic_write_text(self.local_config_path(run_uri, name), content)
        self._touch_run_freshness(run_uri, reason="config_snapshot")

    def read_composition_manifest(self, run_uri: str) -> dict[str, PlainData] | None:
        run_dir = self.local_run_dir(run_uri)
        path = run_dir / "config" / "composition_manifest.json"
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(
            data, path, label="composition manifest document"
        )
        _validate_exact_document_fields(
            payload,
            path,
            label="composition manifest document",
            fields=_COMPOSITION_MANIFEST_WRAPPER_FIELDS,
        )
        _require_schema_version(payload, path, label="composition manifest document")
        _require_run_uri_field(
            payload, path, expected=run_uri, label="composition manifest document"
        )
        _require_timestamp_field(
            payload, path, "created_at", label="composition manifest document"
        )
        return _require_mapping_field(
            payload, path, "composition_manifest", label="composition manifest document"
        )

    def write_composition_manifest(
        self, run_uri: str, manifest: Mapping[str, PlainData]
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        normalized = ensure_plain_data(manifest, path="composition_manifest")
        if not isinstance(normalized, dict):
            raise UnsafeStorePathError("composition manifest must be a mapping")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "created_at": utc_timestamp(),
            "composition_manifest": normalized,
        }
        atomic_write_json(
            self.local_run_dir(run_uri_text) / "config" / "composition_manifest.json",
            payload,
        )
        self._touch_run_freshness(run_uri_text, reason="composition_manifest")

    def read_recipe_manifest(
        self, run_uri: str
    ) -> tuple[dict[str, PlainData], ...] | None:
        run_dir = self.local_run_dir(run_uri)
        path = run_dir / "config" / "recipe_manifest.json"
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(data, path, label="recipe manifest document")
        _validate_exact_document_fields(
            payload,
            path,
            label="recipe manifest document",
            fields=_RECIPE_MANIFEST_WRAPPER_FIELDS,
        )
        _require_schema_version(payload, path, label="recipe manifest document")
        _require_run_uri_field(
            payload, path, expected=run_uri, label="recipe manifest document"
        )
        _require_timestamp_field(
            payload, path, "created_at", label="recipe manifest document"
        )
        manifest = _require_list_field(
            payload, path, "recipe_manifest", label="recipe manifest document"
        )
        for item in manifest:
            if not isinstance(item, dict):
                raise CorruptStoreDocumentError(
                    f"recipe_manifest entries in {path} must be mappings"
                )
        return tuple(dict(item) for item in manifest)  # type: ignore[arg-type]

    def write_recipe_manifest(
        self, run_uri: str, records: Sequence[Mapping[str, PlainData]]
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        normalized = ensure_plain_data(records, path="recipe_manifest")
        if not isinstance(normalized, list):
            raise UnsafeStorePathError("recipe manifest must be a list")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "created_at": utc_timestamp(),
            "recipe_manifest": normalized,
        }
        atomic_write_json(
            self.local_run_dir(run_uri_text) / "config" / "recipe_manifest.json",
            payload,
        )
        self._touch_run_freshness(run_uri_text, reason="recipe_manifest")

    def read_provenance_document(
        self, run_uri: str, name: str
    ) -> dict[str, PlainData] | None:
        path = self.local_provenance_path(run_uri, name)
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(data, path, label="provenance document")
        _validate_exact_document_fields(
            payload,
            path,
            label="provenance document",
            fields=_PROVENANCE_WRAPPER_FIELDS,
        )
        _require_schema_version(payload, path, label="provenance document")
        _require_run_uri_field(
            payload, path, expected=run_uri, label="provenance document"
        )
        _require_timestamp_field(
            payload, path, "created_at", label="provenance document"
        )
        kind = _require_string_field(payload, path, "kind", label="provenance document")
        if kind != validate_provenance_name(name):
            raise CorruptStoreDocumentError(f"provenance kind mismatch for {path}")
        return _require_mapping_field(
            payload, path, "provenance", label="provenance document"
        )

    def write_provenance_document(
        self, run_uri: str, name: str, document: Mapping[str, PlainData]
    ) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        validated_name = validate_provenance_name(name)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "kind": validated_name,
            "created_at": utc_timestamp(),
            "provenance": ensure_plain_data(
                document, path=f"provenance[{validated_name}]"
            ),
        }
        atomic_write_json(
            self.local_provenance_path(run_uri_text, validated_name), payload
        )
        self._touch_run_freshness(run_uri_text, reason="provenance_document")

    def append_event(self, run_uri: str, event: PipelineEvent) -> PipelineEventRecord:
        if not isinstance(event, PipelineEvent):
            raise CorruptStoreDocumentError("append_event requires a PipelineEvent")
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        run_dir = self.local_run_dir(run_uri_text)
        if not run_dir.is_dir():
            raise RunNotFoundError(f"run not found: {run_uri_text}")
        path = run_dir / "events.jsonl"
        with self._event_lock:
            existing = self.read_events(run_uri_text)
            sequence = existing[-1].sequence + 1 if existing else 1
            record = PipelineEventRecord(
                run_uri=run_uri_text,
                sequence=sequence,
                timestamp=event.timestamp or utc_timestamp(),
                scope=event.scope,
                event_type=event.event_type,
                payload=cast(
                    Mapping[str, PlainData],
                    thaw_plain_data(event.payload, path="event.payload"),
                ),
            )
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(stable_json_dumps(record.to_dict()))
                    handle.write("\n")
            except OSError as exc:
                raise CorruptStoreDocumentError(
                    f"Could not append event at {path}: {exc}"
                ) from exc
        # Catalog summaries do not derive facts from event logs in v8.
        return record

    def read_events(self, run_uri: str) -> tuple[PipelineEventRecord, ...]:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        path = self.local_run_dir(run_uri_text) / "events.jsonl"
        if not path.exists():
            return ()
        if not path.is_file():
            raise CorruptStoreDocumentError(f"Expected event log file at {path}")
        records: list[tuple[int, PipelineEventRecord]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                parsed = json_loads(line, path=f"{path}:{line_number}")
                record = PipelineEventRecord.from_dict(parsed)
            except (DeserializationError, PipelineEventError) as exc:
                raise CorruptStoreDocumentError(
                    f"Malformed event record at {path}:{line_number}: {exc}"
                ) from exc
            record_uri = validate_run_uri(record.run_uri, field="event.run_uri")
            if record_uri != run_uri_text:
                raise CorruptStoreDocumentError(
                    f"event record at {path}:{line_number} has run_uri {record_uri!r}, expected {run_uri_text!r}"
                )
            records.append((line_number, record))
        for expected, (line_number, record) in enumerate(records, start=1):
            if record.sequence != expected:
                raise CorruptStoreDocumentError(
                    f"event sequence gap at {path}:{line_number}: expected {expected}, got {record.sequence}"
                )
        return tuple(record for _, record in records)

    def acquire_run_lock(
        self,
        run_uri: str,
        *,
        owner: Mapping[str, PlainData] | None = None,
    ) -> RunLockRecord:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        run_dir = self.local_run_dir(run_uri_text)
        if not run_dir.is_dir():
            raise RunNotFoundError(f"run not found: {run_uri_text}")
        lock_path = run_dir / "lock.json"
        record = RunLockRecord(
            run_uri=run_uri_text,
            token=uuid.uuid4().hex,
            acquired_at=utc_timestamp(),
            owner=_normalize_lock_owner(owner),
        )
        try:
            with lock_path.open("x", encoding="utf-8") as handle:
                handle.write(stable_json_dumps(record.to_dict()))
                handle.write("\n")
        except FileExistsError as exc:
            raise RunLockConflictError(
                f"run lock already exists at {lock_path}"
            ) from exc
        except OSError as exc:
            raise CorruptStoreDocumentError(
                f"Could not acquire run lock at {lock_path}: {exc}"
            ) from exc
        return record

    def read_run_lock(self, run_uri: str) -> RunLockRecord | None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        lock_path = self.local_run_dir(run_uri_text) / "lock.json"
        if not lock_path.exists():
            return None
        return self._read_lock_record(run_uri_text, lock_path)

    def release_run_lock(self, run_uri: str, token: str) -> None:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        if not isinstance(token, str) or not token:
            raise RunLockReleaseError("run lock token must be a non-empty string")
        lock_path = self.local_run_dir(run_uri_text) / "lock.json"
        if not lock_path.exists():
            raise RunLockReleaseError(f"run lock does not exist at {lock_path}")
        try:
            record = self._read_lock_record(run_uri_text, lock_path)
        except CorruptStoreDocumentError as exc:
            raise RunLockReleaseError(
                f"Cannot release corrupt run lock at {lock_path}: {exc}"
            ) from exc
        if record.token != token:
            raise RunLockReleaseError(f"run lock token mismatch for {lock_path}")
        try:
            lock_path.unlink()
        except FileNotFoundError as exc:
            raise RunLockReleaseError(
                f"run lock disappeared before release at {lock_path}"
            ) from exc
        except OSError as exc:
            raise RunLockReleaseError(
                f"Could not release run lock at {lock_path}: {exc}"
            ) from exc

    def read_stage_status(
        self, run_uri: str, stage_name: str
    ) -> StageStatusRecord | None:
        path = self._stage_file_path(run_uri, stage_name, "status.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        try:
            return StageStatusRecord.from_dict(data)
        except Exception as exc:
            raise CorruptStoreDocumentError(
                f"Malformed stage status at {path}: {exc}",
            ) from exc

    def _inspect_stage_state(self, run_uri: str, stage_name: str) -> RunStageInspection:
        status = self.read_stage_status(run_uri, stage_name)
        failure = ensure_failure_payload(self.read_stage_failure(run_uri, stage_name))
        inputs = self.read_stage_inputs(run_uri, stage_name)
        outputs = self.read_stage_outputs(run_uri, stage_name)
        provenance = self.read_stage_provenance(run_uri, stage_name)
        stdout_path = self.local_stage_log_path(run_uri, stage_name, "stdout")
        stderr_path = self.local_stage_log_path(run_uri, stage_name, "stderr")
        self._validate_optional_log_file(stdout_path)
        self._validate_optional_log_file(stderr_path)
        return RunStageInspection(
            stage_name=stage_name,
            status=status,
            failure=failure,
            input_count=0 if inputs is None else len(inputs),
            output_count=0 if outputs is None else len(outputs),
            provenance_available=provenance is not None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_available=stdout_path.exists(),
            stderr_available=stderr_path.exists(),
        )

    def _validate_optional_log_file(self, path: Path) -> None:
        if path.exists() and not path.is_file():
            raise CorruptStoreDocumentError(f"Expected stage log file at {path}")

    def write_stage_status(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        self._validate_stage_match(run_uri, stage_name, status)
        stage_dir = self.local_stage_dir(run_uri, stage_name)
        stage_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            self._stage_file_path(run_uri, stage_name, "status.json"), status.to_dict()
        )
        self._touch_run_freshness(run_uri, reason="stage_status")

    def read_stage_inputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        path = self._stage_file_path(run_uri, stage_name, "inputs.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(data, path, label="stage inputs document")
        inputs = self._validate_stage_attempt_payload(
            payload, run_uri, stage_name, "inputs", path
        )
        return _deserialize_stage_artifact_index(inputs, path=path)

    def write_stage_inputs(
        self,
        run_uri: str,
        stage_name: str,
        inputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_uri, stage_name, "inputs.json")
        payload = self._build_stage_payload(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            field_name="inputs",
            field_value=_serialize_stage_artifact_index(inputs),
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri, reason="stage_inputs")

    def read_stage_outputs(
        self, run_uri: str, stage_name: str
    ) -> dict[str, ArtifactRef] | None:
        path = self._stage_file_path(run_uri, stage_name, "outputs.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(data, path, label="stage outputs document")
        outputs = self._validate_stage_attempt_payload(
            payload, run_uri, stage_name, "outputs", path
        )
        return _deserialize_stage_artifact_index(outputs, path=path)

    def write_stage_outputs(
        self,
        run_uri: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_uri, stage_name, "outputs.json")
        payload = self._build_stage_payload(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            field_name="outputs",
            field_value=_serialize_stage_artifact_index(outputs),
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri, reason="stage_outputs")

    def read_stage_fingerprint(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        path = self._stage_file_path(run_uri, stage_name, "fingerprint.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(
            data, path, label="stage fingerprint document"
        )
        return self._validate_stage_attempt_payload(
            payload, run_uri, stage_name, "fingerprint", path
        )

    def write_stage_fingerprint(
        self,
        run_uri: str,
        stage_name: str,
        fingerprint: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_uri, stage_name, "fingerprint.json")
        payload = self._build_stage_payload(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            field_name="fingerprint",
            field_value=ensure_plain_data(fingerprint, path="fingerprint"),
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri, reason="stage_fingerprint")

    def read_stage_failure(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        path = self._stage_file_path(run_uri, stage_name, "failure.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(data, path, label="stage failure document")
        return self._validate_stage_attempt_payload(
            payload, run_uri, stage_name, "failure", path
        )

    def write_stage_failure(
        self,
        run_uri: str,
        stage_name: str,
        failure: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_uri, stage_name, "failure.json")
        payload = self._build_stage_payload(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            field_name="failure",
            field_value=ensure_plain_data(failure, path="failure"),
            failure_timestamp_field=True,
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri, reason="stage_failure")

    def read_stage_worker_request(
        self, run_uri: str, stage_name: str, *, attempt: int
    ) -> dict[str, PlainData] | None:
        path = self.local_stage_worker_request_path(run_uri, stage_name)
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(
            data, path, label="stage worker request document"
        )
        return self._validate_stage_attempt_payload(
            payload,
            run_uri,
            stage_name,
            "worker_request",
            path,
            expected_attempt=attempt,
        )

    def write_stage_worker_request(
        self,
        run_uri: str,
        stage_name: str,
        request: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self.local_stage_worker_request_path(run_uri, stage_name)
        payload = self._build_stage_payload(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            field_name="worker_request",
            field_value=ensure_plain_data(request, path="worker_request"),
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri, reason="stage_worker_request")

    def read_stage_worker_result(
        self, run_uri: str, stage_name: str, *, attempt: int
    ) -> dict[str, PlainData] | None:
        path = self.local_stage_worker_result_path(run_uri, stage_name)
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(
            data, path, label="stage worker result document"
        )
        return self._validate_stage_attempt_payload(
            payload,
            run_uri,
            stage_name,
            "worker_result",
            path,
            expected_attempt=attempt,
        )

    def write_stage_worker_result(
        self,
        run_uri: str,
        stage_name: str,
        result: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self.local_stage_worker_result_path(run_uri, stage_name)
        payload = self._build_stage_payload(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            field_name="worker_result",
            field_value=ensure_plain_data(result, path="worker_result"),
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri, reason="stage_worker_result")

    def read_stage_provenance(
        self, run_uri: str, stage_name: str
    ) -> dict[str, PlainData] | None:
        path = self._stage_file_path(run_uri, stage_name, "provenance.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        payload = _require_document_object(
            data, path, label="stage provenance document"
        )
        return self._validate_stage_attempt_payload(
            payload, run_uri, stage_name, "provenance", path
        )

    def write_stage_provenance(
        self,
        run_uri: str,
        stage_name: str,
        provenance: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_uri, stage_name, "provenance.json")
        payload = self._build_stage_payload(
            run_uri=run_uri,
            stage_name=stage_name,
            attempt=attempt,
            field_name="provenance",
            field_value=ensure_plain_data(provenance, path="provenance"),
        )
        atomic_write_json(path, payload)
        self._touch_run_freshness(run_uri, reason="stage_provenance")

    def read_stage_log(self, run_uri: str, stage_name: str, stream: str) -> str | None:
        validated_stream = validate_log_stream(stream)
        path = self.local_stage_log_path(run_uri, stage_name, validated_stream)
        if not path.exists():
            return None
        if not path.is_file():
            raise CorruptStoreDocumentError(f"Expected stage log file at {path}")
        return path.read_text(encoding="utf-8")

    def write_stage_log(
        self, run_uri: str, stage_name: str, stream: str, content: str
    ) -> None:
        validated_stream = validate_log_stream(stream)
        if not isinstance(content, str):
            raise UnsafeStorePathError(
                f"stage log content must be text, got {type(content)!r}"
            )
        atomic_write_text(
            self.local_stage_log_path(run_uri, stage_name, validated_stream), content
        )
        # Catalog summaries intentionally exclude log contents and log availability.

    def _reliability_family_path(
        self,
        run_uri: str,
        family: str,
        record_key: str,
        *,
        create_parent: bool = False,
    ) -> Path:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        self.open_run(run_uri_text)
        directory = self.local_run_dir(run_uri_text) / "reliability" / family
        if create_parent:
            directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{record_key}.json"

    def _write_reliability_fact(
        self,
        path: Path,
        payload: Mapping[str, PlainData],
        *,
        reason: str,
    ) -> None:
        if path.exists():
            existing = self._read_optional_json(path)
            existing_payload = _require_document_object(
                existing,
                path,
                label="reliability fact document",
            )
            if reliability_payload_matches(
                cast(Mapping[str, PlainData], existing_payload),
                payload,
            ):
                return
            raise UnsafeStorePathError(
                f"conflicting reliability fact already exists at {path}"
            )
        atomic_write_json(path, payload)
        run_uri = _run_uri_from_reliability_path(path)
        self._touch_run_freshness(run_uri, reason=reason)

    def _list_reliability_records[T](
        self,
        run_uri: str,
        *,
        family: str,
        parser: Callable[[object], T],
    ) -> tuple[T, ...]:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        self.open_run(run_uri_text)
        directory = self.local_run_dir(run_uri_text) / "reliability" / family
        if not directory.exists():
            return ()
        if not directory.is_dir():
            raise CorruptStoreDocumentError(f"Expected directory at {directory}")
        records: list[T] = []
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix != ".json":
                raise CorruptStoreDocumentError(
                    f"Expected reliability fact JSON file at {path}"
                )
            data = self._read_optional_json(path)
            try:
                records.append(parser(data))
            except ValueError as exc:
                raise CorruptStoreDocumentError(
                    f"Malformed reliability fact at {path}: {exc}"
                ) from exc
        return tuple(records)

    def _list_stage_reliability_records[T](
        self,
        run_uri: str,
        *,
        family: str,
        parser: Callable[[object], T],
        stage_name: str | None,
        sort_key: Callable[[T], tuple[object, ...]],
    ) -> tuple[T, ...]:
        stage_name_text = (
            None
            if stage_name is None
            else validate_stage_name(stage_name, field="stage_name")
        )
        records = self._list_reliability_records(
            run_uri,
            family=family,
            parser=parser,
        )
        def matches_stage(record: T) -> bool:
            if stage_name_text is None:
                return True
            typed_record = cast(
                ReliabilityStatusDetail
                | StageAttemptTransaction
                | RetryDecisionRecord
                | TimeoutOutcomeRecord,
                record,
            )
            return reliability_record_stage_name(typed_record) == stage_name_text

        filtered = (
            record
            for record in records
            if matches_stage(record)
        )
        return tuple(sorted(filtered, key=sort_key))

    def _read_lock_record(self, run_uri: str, lock_path: Path) -> RunLockRecord:
        if not lock_path.is_file():
            raise CorruptStoreDocumentError(f"Expected run lock file at {lock_path}")
        try:
            data = json_loads(
                lock_path.read_text(encoding="utf-8"), path=str(lock_path)
            )
            record = RunLockRecord.from_dict(data)
        except (DeserializationError, RunLockValidationError) as exc:
            raise CorruptStoreDocumentError(
                f"Malformed run lock at {lock_path}: {exc}"
            ) from exc
        expected = validate_run_uri(run_uri, field="run_uri")
        actual = validate_run_uri(record.run_uri, field="lock.run_uri")
        if actual != expected:
            raise CorruptStoreDocumentError(
                f"run lock at {lock_path} has run_uri {actual!r}, expected {expected!r}",
            )
        return record

    def _stage_file_path(self, run_uri: str, stage_name: str, filename: str) -> Path:
        stage_dir = self.local_stage_dir(run_uri, stage_name)
        stage_dir.mkdir(parents=True, exist_ok=True)
        return stage_dir / filename

    def _submitted_operation_path(
        self, run_uri: str, submission_id: str, *, create_parent: bool = False
    ) -> Path:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        submission_id_text = validate_submission_id(submission_id)
        directory = self.local_run_dir(run_uri_text) / "submitted_operations"
        if create_parent:
            directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{submission_id_text}.json"

    def _submitted_operation_from_payload(
        self,
        run_uri: str,
        path: Path,
        data: object,
    ) -> SubmittedOperationRecord:
        try:
            record = SubmittedOperationRecord.from_dict(data)
        except SubmittedOperationError as exc:
            raise CorruptStoreDocumentError(
                f"Malformed submitted-operation record at {path}: {exc}"
            ) from exc
        expected = validate_run_uri(run_uri, field="run_uri")
        actual = validate_run_uri(record.run_uri, field="submitted_operation.run_uri")
        if actual != expected:
            raise CorruptStoreDocumentError(
                f"submitted-operation record at {path} has run_uri {actual!r}, expected {expected!r}"
            )
        expected_name = f"{record.submission_id}.json"
        if path.name != expected_name:
            raise CorruptStoreDocumentError(
                f"submitted-operation record at {path} has submission_id {record.submission_id!r}, expected filename {expected_name!r}"
            )
        return record

    def _read_optional_json(
        self, path: Path
    ) -> dict[str, object] | list[object] | None:
        if not path.exists():
            return None
        if not path.is_file():
            raise CorruptStoreDocumentError(f"Expected file at {path}")
        try:
            value = json_loads(path.read_text(encoding="utf-8"), path=str(path))
        except DeserializationError as exc:
            raise CorruptStoreDocumentError(f"Malformed JSON at {path}: {exc}") from exc
        if not isinstance(value, (dict, list)):
            raise CorruptStoreDocumentError(
                f"Store JSON at {path} must be an object or array"
            )
        return value

    def _touch_run_freshness(self, run_uri: str, *, reason: str) -> RunFreshnessRecord:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        path = self.local_run_freshness_path(run_uri_text)
        revision = 1
        try:
            current = self.read_run_freshness(run_uri_text)
        except CorruptStoreDocumentError:
            current = None
        if current is not None:
            revision = current.revision + 1
        record = RunFreshnessRecord(
            run_uri=run_uri_text,
            token=uuid.uuid4().hex,
            updated_at=utc_timestamp(),
            revision=revision,
            reason=reason,
        )
        atomic_write_json(path, record.to_dict())
        return record

    def _read_run_wrapper(self, run_uri: str) -> dict[str, PlainData]:
        path = self.local_run_dir(run_uri) / "run.json"
        if not path.is_file():
            raise MissingStoreDocumentError(f"run metadata missing at {path}")
        data = self._read_optional_json(path)
        payload = _require_document_object(data, path, label="run metadata document")
        _validate_exact_document_fields(
            payload, path, label="run metadata document", fields=_RUN_WRAPPER_FIELDS
        )
        schema_version = _require_schema_version(
            payload, path, label="run metadata document"
        )
        run_uri_text = _require_run_uri_field(
            payload, path, expected=run_uri, label="run metadata document"
        )
        created_at = _require_timestamp_field(
            payload, path, "created_at", label="run metadata document"
        )
        metadata = _require_mapping_field(
            payload, path, "metadata", label="run metadata document"
        )
        return {
            "schema_version": schema_version,
            "run_uri": run_uri_text,
            "created_at": created_at,
            "metadata": metadata,
        }

    def _build_stage_payload(
        self,
        *,
        run_uri: str,
        stage_name: str,
        attempt: int,
        field_name: str,
        field_value: PlainData,
        failure_timestamp_field: bool = False,
    ) -> dict[str, PlainData]:
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        stage_name_text = validate_stage_name(stage_name, field="stage_name")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
            raise UnsafeStorePathError("attempt must be a positive integer")
        return {
            "schema_version": _SCHEMA_VERSION,
            "run_uri": run_uri_text,
            "stage_name": stage_name_text,
            "attempt": attempt,
            "failed_at" if failure_timestamp_field else "created_at": utc_timestamp(),
            field_name: field_value,
        }

    def _validate_stage_attempt_payload(
        self,
        payload: dict[str, object],
        run_uri: str,
        stage_name: str,
        field_name: str,
        source_path: Path,
        expected_attempt: int | None = None,
    ) -> dict[str, PlainData]:
        failure_key = "failed_at" if field_name == "failure" else "created_at"
        fields = frozenset(
            {
                "schema_version",
                "run_uri",
                "stage_name",
                "attempt",
                failure_key,
                field_name,
            }
        )
        label = f"stage {field_name} document"
        _validate_exact_document_fields(
            payload, source_path, label=label, fields=fields
        )
        _require_schema_version(payload, source_path, label=label)
        run_uri_text = validate_run_uri(run_uri, field="run_uri")
        _require_run_uri_field(payload, source_path, expected=run_uri_text, label=label)
        stage_name_text = validate_stage_name(stage_name, field="stage_name")
        stored_stage = _require_string_field(
            payload, source_path, "stage_name", label=label
        )
        if stored_stage != stage_name_text:
            raise CorruptStoreDocumentError(
                f"{label} at {source_path} has stage_name {stored_stage!r}, expected {stage_name_text!r}"
            )
        attempt = _require_field(payload, source_path, "attempt", label=label)
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
            raise CorruptStoreDocumentError(
                f"{label} at {source_path} field 'attempt' must be a positive integer"
            )
        if expected_attempt is not None and attempt != expected_attempt:
            raise CorruptStoreDocumentError(
                f"{label} at {source_path} has attempt {attempt}, expected {expected_attempt}"
            )
        _require_timestamp_field(payload, source_path, failure_key, label=label)
        return _require_mapping_field(payload, source_path, field_name, label=label)

    def _validate_run_uri_for_status(self, run_uri: str, status_run_uri: str) -> None:
        expected = validate_run_uri(run_uri, field="run_uri")
        actual = validate_run_uri(status_run_uri, field="status.run_uri")
        if actual != expected:
            raise UnsafeStorePathError(
                f"run_uri mismatch for status payload: {actual} != {expected}"
            )

    def _validate_stage_match(
        self, run_uri: str, stage_name: str, status: StageStatusRecord
    ) -> None:
        expected = validate_run_uri(run_uri, field="run_uri")
        actual = validate_run_uri(status.run_uri, field="status.run_uri")
        if actual != expected:
            raise UnsafeStorePathError(
                f"run_uri mismatch for stage status: {actual} != {expected}"
            )
        if status.stage_name != stage_name:
            raise UnsafeStorePathError(
                f"stage name mismatch for stage status: {status.stage_name} != {stage_name}"
            )


def _require_document_object(
    data: object, path: Path, *, label: str
) -> dict[str, object]:
    if not isinstance(data, dict):
        raise CorruptStoreDocumentError(f"{label} at {path} must be an object")
    return data


def _validate_exact_document_fields(
    payload: Mapping[str, object],
    path: Path,
    *,
    label: str,
    fields: frozenset[str],
) -> None:
    actual_fields = set(payload)
    missing = fields - actual_fields
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise CorruptStoreDocumentError(
            f"{label} at {path} missing required field(s): {missing_list}"
        )
    unknown = actual_fields - fields
    if unknown:
        unknown_list = ", ".join(sorted(unknown))
        raise CorruptStoreDocumentError(
            f"{label} at {path} has unknown field(s): {unknown_list}"
        )


def _require_field(
    payload: Mapping[str, object], path: Path, field_name: str, *, label: str
) -> object:
    try:
        return payload[field_name]
    except KeyError as exc:
        raise CorruptStoreDocumentError(
            f"{label} at {path} missing required field {field_name!r}"
        ) from exc


def _require_schema_version(
    payload: Mapping[str, object], path: Path, *, label: str
) -> int:
    value = _require_field(payload, path, "schema_version", label=label)
    if not isinstance(value, int) or isinstance(value, bool):
        raise CorruptStoreDocumentError(
            f"{label} at {path} field 'schema_version' must be an integer"
        )
    if value != _SCHEMA_VERSION:
        raise CorruptStoreDocumentError(
            f"Unsupported {label} schema at {path}: {value!r}"
        )
    return value


def _require_run_uri_field(
    payload: Mapping[str, object], path: Path, *, expected: str, label: str
) -> str:
    value = _require_string_field(payload, path, "run_uri", label=label)
    try:
        value_text = validate_run_uri(value, field="run_uri")
    except Exception as exc:
        raise CorruptStoreDocumentError(
            f"{label} at {path} field 'run_uri' is invalid: {exc}"
        ) from exc
    expected_text = validate_run_uri(expected, field="run_uri")
    if value_text != expected_text:
        raise CorruptStoreDocumentError(
            f"{label} at {path} has run_uri {value_text!r}, expected {expected_text!r}"
        )
    return value_text


def _require_string_field(
    payload: Mapping[str, object], path: Path, field_name: str, *, label: str
) -> str:
    value = _require_field(payload, path, field_name, label=label)
    if not isinstance(value, str) or not value:
        raise CorruptStoreDocumentError(
            f"{label} at {path} field {field_name!r} must be a non-empty string"
        )
    return value


def _require_timestamp_field(
    payload: Mapping[str, object], path: Path, field_name: str, *, label: str
) -> str:
    value = _require_string_field(payload, path, field_name, label=label)
    try:
        parse_timestamp(value)
    except ValueError as exc:
        raise CorruptStoreDocumentError(
            f"{label} at {path} field {field_name!r} must be a valid UTC timestamp: {exc}"
        ) from exc
    return value


def _require_mapping_field(
    payload: Mapping[str, object],
    path: Path,
    field_name: str,
    *,
    label: str,
) -> dict[str, PlainData]:
    value = _require_field(payload, path, field_name, label=label)
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except PlainDataError as exc:
        raise CorruptStoreDocumentError(
            f"{label} at {path} field {field_name!r} must be plain data: {exc}"
        ) from exc
    if not isinstance(normalized, dict):
        raise CorruptStoreDocumentError(
            f"{label} at {path} field {field_name!r} must be an object"
        )
    return normalized


def _require_list_field(
    payload: Mapping[str, object],
    path: Path,
    field_name: str,
    *,
    label: str,
) -> list[PlainData]:
    value = _require_field(payload, path, field_name, label=label)
    try:
        normalized = ensure_plain_data(value, path=field_name)
    except PlainDataError as exc:
        raise CorruptStoreDocumentError(
            f"{label} at {path} field {field_name!r} must be plain data: {exc}"
        ) from exc
    if not isinstance(normalized, list):
        raise CorruptStoreDocumentError(
            f"{label} at {path} field {field_name!r} must be an array"
        )
    return normalized


def _serialize_stage_artifact_index(
    index: Mapping[str, ArtifactRef],
) -> dict[str, PlainData]:
    if not isinstance(index, Mapping):
        raise CorruptStoreDocumentError("stage artifact payload must be a mapping")
    payload: dict[str, PlainData] = {}
    for key, ref in index.items():
        validated_key = validate_output_name(key, field="artifact_key")
        if not isinstance(ref, ArtifactRef):
            raise CorruptStoreDocumentError(
                f"stage artifact payload entry {validated_key!r} must be an ArtifactRef"
            )
        payload[validated_key] = ensure_plain_data(
            ref.to_dict(), path=f"stage_artifact[{validated_key!r}]"
        )
    return payload


def _normalize_lock_owner(
    owner: Mapping[str, PlainData] | None,
) -> dict[str, PlainData]:
    try:
        metadata = ensure_plain_data(owner or {}, path="owner")
    except PlainDataError as exc:
        raise UnsafeStorePathError(
            f"run lock owner metadata must be plain data: {exc}"
        ) from exc
    if not isinstance(metadata, dict):
        raise UnsafeStorePathError("run lock owner metadata must be a mapping")
    return {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "metadata": metadata,
    }


def _deserialize_stage_artifact_index(
    mapping: object, *, path: Path
) -> dict[str, ArtifactRef]:
    if not isinstance(mapping, dict):
        raise CorruptStoreDocumentError(
            f"stage artifact payload at {path} must be an object"
        )

    parsed: dict[str, ArtifactRef] = {}
    for key, value in mapping.items():
        try:
            validated_key = validate_output_name(key, field="artifact_key")
        except UnsafeStorePathError as exc:
            raise CorruptStoreDocumentError(
                f"Malformed stage artifact index at {path}: invalid key {key!r}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise CorruptStoreDocumentError(
                f"stage artifact payload value for {validated_key!r} at {path} must be an object"
            )
        try:
            parsed[validated_key] = ArtifactRef.from_dict(dict(value))
        except ArtifactValidationError as exc:
            raise CorruptStoreDocumentError(
                f"invalid artifact ref for {validated_key!r} at {path}: {exc}"
            ) from exc
    return parsed


def _reliability_id_key(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise UnsafeStorePathError("reliability fact identifier must be non-empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_uri_from_reliability_path(path: Path) -> str:
    return path_to_run_uri(path.parents[2])


__all__ = ["LocalRunStore"]

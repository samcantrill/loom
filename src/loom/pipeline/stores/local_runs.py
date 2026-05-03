"""Local filesystem run-store implementation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from loom.artifacts import ArtifactRef, ArtifactValidationError
from loom.io.uris import path_to_file_uri
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.serialization import PlainData, ensure_plain_data, json_loads
from loom.serialization.errors import DeserializationError
from loom.timestamps import utc_timestamp

from ._paths import (
    VALID_CONFIG_SNAPSHOTS,
    VALID_PROVENANCE_NAMES,
    validate_output_name,
    validate_config_snapshot_name,
    validate_log_stream,
    validate_provenance_name,
    validate_run_id,
    validate_stage_name,
)
from .atomic import atomic_write_json, atomic_write_text
from .errors import (
    ArtifactStoreError,
    CorruptStoreDocumentError,
    MissingStoreDocumentError,
    RunAlreadyExistsError,
    RunNotFoundError,
    UnsafeStorePathError,
)
from .indexes import artifact_index_from_dict, artifact_index_to_dict

_SCHEMA_VERSION = 1


class LocalRunStore:
    """Filesystem-backed local run layout writer and reader."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def create_run(self, run_id: str, *, metadata: Mapping[str, PlainData] | None = None) -> Path:
        run_id_text = validate_run_id(run_id, field="run_id")
        run_dir = self.get_run_dir(run_id_text)
        if run_dir.exists():
            raise RunAlreadyExistsError(f"run directory already exists: {run_dir}")

        try:
            (run_dir / "config").mkdir(parents=True, exist_ok=True)
            (run_dir / "provenance").mkdir(parents=True, exist_ok=True)
            (run_dir / "stages").mkdir(parents=True, exist_ok=True)
            (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CorruptStoreDocumentError(f"Unable to initialize run directory structure {run_dir}: {exc}") from exc

        self.write_run_metadata(run_id_text, metadata or {})
        return run_dir

    def open_run(self, run_id: str) -> Path:
        run_id_text = validate_run_id(run_id, field="run_id")
        run_dir = self.get_run_dir(run_id_text)
        if not run_dir.is_dir():
            raise RunNotFoundError(f"run not found: {run_id_text}")
        run_json = run_dir / "run.json"
        if not run_json.exists():
            raise MissingStoreDocumentError(f"Missing required run metadata at {run_json}")
        self._read_run_wrapper(run_id_text)
        return run_dir

    def get_run_dir(self, run_id: str) -> Path:
        return self.root / validate_run_id(run_id, field="run_id")

    def get_stage_dir(self, run_id: str, stage_name: str) -> Path:
        return self.get_run_dir(run_id) / "stages" / validate_stage_name(stage_name, field="stage_name")

    def get_artifact_root(self, run_id: str) -> Path:
        return self.get_run_dir(run_id) / "artifacts"

    def get_stage_artifact_dir(self, run_id: str, stage_name: str) -> Path:
        return self.get_artifact_root(run_id) / validate_stage_name(stage_name, field="stage_name")

    def get_config_path(self, run_id: str, name: str) -> Path:
        run_id_text = validate_run_id(run_id, field="run_id")
        validated_name = validate_config_snapshot_name(name)
        return self.get_run_dir(run_id_text) / "config" / VALID_CONFIG_SNAPSHOTS[validated_name]

    def get_provenance_path(self, run_id: str, name: str) -> Path:
        run_id_text = validate_run_id(run_id, field="run_id")
        validated_name = validate_provenance_name(name)
        return self.get_run_dir(run_id_text) / "provenance" / VALID_PROVENANCE_NAMES[validated_name]

    def get_stage_log_path(self, run_id: str, stage_name: str, stream: str) -> Path:
        run_id_text = validate_run_id(run_id, field="run_id")
        validated_stream = validate_log_stream(stream)
        return self.get_stage_dir(run_id_text, stage_name) / "logs" / f"{validated_stream}.log"

    def read_run_metadata(self, run_id: str) -> dict[str, PlainData]:
        return self._read_run_wrapper(validate_run_id(run_id, field="run_id"))

    def write_run_metadata(self, run_id: str, metadata: Mapping[str, PlainData]) -> None:
        run_id_text = validate_run_id(run_id, field="run_id")
        run_dir = self.get_run_dir(run_id_text)
        if not run_dir.exists():
            raise RunNotFoundError(f"run not found: {run_id_text}")
        normalized_metadata = ensure_plain_data(metadata, path="metadata")
        if not isinstance(normalized_metadata, dict):
            raise UnsafeStorePathError(f"run metadata must be a mapping, got {type(normalized_metadata)!r}")

        if run_dir.exists() and (run_dir / "run.json").exists():
            existing = self._read_run_wrapper(run_id_text)
            created_at = existing["created_at"]
        else:
            created_at = utc_timestamp()

        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id_text,
            "created_at": created_at,
            "run_dir": path_to_file_uri(run_dir.resolve()),
            "metadata": normalized_metadata,
        }
        atomic_write_json(run_dir / "run.json", payload)

    def read_run_status(self, run_id: str) -> RunStatusRecord | None:
        run_dir = self.get_run_dir(run_id)
        status_path = run_dir / "status.json"
        data = self._read_optional_json(status_path)
        if data is None:
            return None
        try:
            return RunStatusRecord.from_dict(data)
        except Exception as exc:
            raise CorruptStoreDocumentError(f"Malformed run status at {status_path}: {exc}") from exc

    def write_run_status(self, run_id: str, status: RunStatusRecord) -> None:
        self._validate_run_identifier_for_status(run_id, status.run_id)
        run_id_text = validate_run_id(run_id, field="run_id")
        payload = status.to_dict()
        atomic_write_json(self.get_run_dir(run_id_text) / "status.json", payload)

    def read_plan(self, run_id: str) -> dict[str, PlainData] | None:
        run_dir = self.get_run_dir(run_id)
        data = self._read_optional_json(run_dir / "plan.json")
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"plan document for {run_id} must be an object")
        if data.get("run_id") != validate_run_id(run_id, field="run_id"):
            raise CorruptStoreDocumentError(f"plan run_id mismatch at {run_dir / 'plan.json'}")
        if data.get("schema_version") != _SCHEMA_VERSION:
            raise CorruptStoreDocumentError(f"Unsupported plan schema at {run_dir / 'plan.json'}")
        plan = ensure_plain_data(data.get("plan", {}), path="plan")
        if not isinstance(plan, dict):
            raise CorruptStoreDocumentError(f"plan document for {run_id} is not a mapping")
        return plan

    def write_plan(self, run_id: str, plan: Mapping[str, PlainData]) -> None:
        run_id_text = validate_run_id(run_id, field="run_id")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id_text,
            "updated_at": utc_timestamp(),
            "plan": ensure_plain_data(plan, path="plan"),
        }
        atomic_write_json(self.get_run_dir(run_id_text) / "plan.json", payload)

    def read_artifact_index(self, run_id: str) -> dict[str, ArtifactRef]:
        run_dir = self.get_run_dir(run_id)
        data = self._read_optional_json(run_dir / "artifacts.json")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"artifact index for {run_id} must be an object")
        if data.get("run_id") != validate_run_id(run_id, field="run_id"):
            raise CorruptStoreDocumentError(f"artifact index run_id mismatch at {run_dir / 'artifacts.json'}")
        if data.get("schema_version") != _SCHEMA_VERSION:
            raise CorruptStoreDocumentError(f"Unsupported artifact index schema at {run_dir / 'artifacts.json'}")
        try:
            return artifact_index_from_dict(data.get("artifacts", {}))
        except ArtifactStoreError as exc:
            raise CorruptStoreDocumentError(f"Malformed artifact index at {run_dir / 'artifacts.json'}: {exc}") from exc

    def write_artifact_index(self, run_id: str, index: Mapping[str, ArtifactRef]) -> None:
        run_id_text = validate_run_id(run_id, field="run_id")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id_text,
            "updated_at": utc_timestamp(),
            "artifacts": artifact_index_to_dict(index),
        }
        atomic_write_json(self.get_run_dir(run_id_text) / "artifacts.json", payload)

    def read_config_snapshot(self, run_id: str, name: str) -> str | None:
        path = self.get_config_path(run_id, name)
        if not path.exists():
            return None
        if not path.is_file():
            raise CorruptStoreDocumentError(f"Expected file at {path}")
        return path.read_text(encoding="utf-8")

    def write_config_snapshot(self, run_id: str, name: str, content: str) -> None:
        validate_run_id(run_id, field="run_id")
        if not isinstance(content, str):
            raise UnsafeStorePathError(f"config snapshot content must be string, got {type(content)!r}")
        atomic_write_text(self.get_config_path(run_id, name), content)

    def read_recipe_manifest(self, run_id: str) -> tuple[dict[str, PlainData], ...] | None:
        run_dir = self.get_run_dir(run_id)
        data = self._read_optional_json(run_dir / "config" / "recipe_manifest.json")
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"recipe manifest for {run_id} must be an object")
        if data.get("run_id") != validate_run_id(run_id, field="run_id"):
            raise CorruptStoreDocumentError(f"recipe manifest run_id mismatch for {run_id}")
        if data.get("schema_version") != _SCHEMA_VERSION:
            raise CorruptStoreDocumentError(f"Unsupported recipe manifest schema for {run_id}")
        manifest = ensure_plain_data(data.get("recipe_manifest", []), path="recipe_manifest")
        if not isinstance(manifest, list):
            raise CorruptStoreDocumentError(f"recipe_manifest must be an array for {run_id}")
        for item in manifest:
            if not isinstance(item, dict):
                raise CorruptStoreDocumentError(f"recipe_manifest entries must be mappings for {run_id}")
        return tuple(dict(item) for item in manifest)  # type: ignore[arg-type]

    def write_recipe_manifest(self, run_id: str, records: Sequence[Mapping[str, PlainData]]) -> None:
        run_id_text = validate_run_id(run_id, field="run_id")
        normalized = ensure_plain_data(records, path="recipe_manifest")
        if not isinstance(normalized, list):
            raise UnsafeStorePathError("recipe manifest must be a list")
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id_text,
            "created_at": utc_timestamp(),
            "recipe_manifest": normalized,
        }
        atomic_write_json(self.get_run_dir(run_id_text) / "config" / "recipe_manifest.json", payload)

    def read_provenance_document(self, run_id: str, name: str) -> dict[str, PlainData] | None:
        path = self.get_provenance_path(run_id, name)
        data = self._read_optional_json(path)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"provenance document {name} for {run_id} must be an object")
        if data.get("run_id") != validate_run_id(run_id, field="run_id"):
            raise CorruptStoreDocumentError(f"provenance run_id mismatch at {path}")
        if data.get("schema_version") != _SCHEMA_VERSION:
            raise CorruptStoreDocumentError(f"Unsupported provenance schema at {path}")
        kind = data.get("kind")
        if kind != validate_provenance_name(name):
            raise CorruptStoreDocumentError(f"provenance kind mismatch for {path}")
        value = ensure_plain_data(data.get("provenance", {}), path=f"provenance[{name}]")
        if not isinstance(value, dict):
            raise CorruptStoreDocumentError(f"provenance[{name}] must be a mapping")
        return value

    def write_provenance_document(self, run_id: str, name: str, document: Mapping[str, PlainData]) -> None:
        run_id_text = validate_run_id(run_id, field="run_id")
        validated_name = validate_provenance_name(name)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id_text,
            "kind": validated_name,
            "created_at": utc_timestamp(),
            "provenance": ensure_plain_data(document, path=f"provenance[{validated_name}]"),
        }
        atomic_write_json(self.get_provenance_path(run_id_text, validated_name), payload)

    def read_stage_status(self, run_id: str, stage_name: str) -> StageStatusRecord | None:
        data = self._read_optional_json(self._stage_file_path(run_id, stage_name, "status.json"))
        if data is None:
            return None
        try:
            return StageStatusRecord.from_dict(data)
        except Exception as exc:
            raise CorruptStoreDocumentError(
                f"Malformed stage status for {stage_name} in {run_id}: {exc}",
            ) from exc

    def write_stage_status(self, run_id: str, stage_name: str, status: StageStatusRecord) -> None:
        self._validate_stage_match(run_id, stage_name, status)
        stage_dir = self.get_stage_dir(run_id, stage_name)
        stage_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._stage_file_path(run_id, stage_name, "status.json"), status.to_dict())

    def read_stage_inputs(self, run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None:
        path = self._stage_file_path(run_id, stage_name, "inputs.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"stage inputs for {run_id}/{stage_name} must be an object")
        _ = self._validate_stage_attempt_payload(data, run_id, stage_name, "inputs")
        return _deserialize_stage_artifact_index(data["inputs"])

    def write_stage_inputs(
        self,
        run_id: str,
        stage_name: str,
        inputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_id, stage_name, "inputs.json")
        payload = self._build_stage_payload(
            run_id=run_id,
            stage_name=stage_name,
            attempt=attempt,
            field_name="inputs",
            field_value=_serialize_stage_artifact_index(inputs),
        )
        atomic_write_json(path, payload)

    def read_stage_outputs(self, run_id: str, stage_name: str) -> dict[str, ArtifactRef] | None:
        path = self._stage_file_path(run_id, stage_name, "outputs.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"stage outputs for {run_id}/{stage_name} must be an object")
        _ = self._validate_stage_attempt_payload(data, run_id, stage_name, "outputs")
        return _deserialize_stage_artifact_index(data["outputs"])

    def write_stage_outputs(
        self,
        run_id: str,
        stage_name: str,
        outputs: Mapping[str, ArtifactRef],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_id, stage_name, "outputs.json")
        payload = self._build_stage_payload(
            run_id=run_id,
            stage_name=stage_name,
            attempt=attempt,
            field_name="outputs",
            field_value=_serialize_stage_artifact_index(outputs),
        )
        atomic_write_json(path, payload)

    def read_stage_fingerprint(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None:
        path = self._stage_file_path(run_id, stage_name, "fingerprint.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"stage fingerprint for {run_id}/{stage_name} must be an object")
        _ = self._validate_stage_attempt_payload(data, run_id, stage_name, "fingerprint")
        return self._ensure_plain_mapping(
            data["fingerprint"],
            path=f"{run_id}/{stage_name}/fingerprint",
        )

    def write_stage_fingerprint(
        self,
        run_id: str,
        stage_name: str,
        fingerprint: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_id, stage_name, "fingerprint.json")
        payload = self._build_stage_payload(
            run_id=run_id,
            stage_name=stage_name,
            attempt=attempt,
            field_name="fingerprint",
            field_value=ensure_plain_data(fingerprint, path="fingerprint"),
        )
        atomic_write_json(path, payload)

    def read_stage_failure(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None:
        path = self._stage_file_path(run_id, stage_name, "failure.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"stage failure for {run_id}/{stage_name} must be an object")
        _ = self._validate_stage_attempt_payload(data, run_id, stage_name, "failure")
        return self._ensure_plain_mapping(
            data["failure"],
            path=f"{run_id}/{stage_name}/failure",
        )

    def write_stage_failure(
        self,
        run_id: str,
        stage_name: str,
        failure: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_id, stage_name, "failure.json")
        payload = self._build_stage_payload(
            run_id=run_id,
            stage_name=stage_name,
            attempt=attempt,
            field_name="failure",
            field_value=ensure_plain_data(failure, path="failure"),
            failure_timestamp_field=True,
        )
        atomic_write_json(path, payload)

    def read_stage_provenance(self, run_id: str, stage_name: str) -> dict[str, PlainData] | None:
        path = self._stage_file_path(run_id, stage_name, "provenance.json")
        data = self._read_optional_json(path)
        if data is None:
            return None
        if not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"stage provenance for {run_id}/{stage_name} must be an object")
        _ = self._validate_stage_attempt_payload(data, run_id, stage_name, "provenance")
        return self._ensure_plain_mapping(
            data["provenance"],
            path=f"{run_id}/{stage_name}/provenance",
        )

    def write_stage_provenance(
        self,
        run_id: str,
        stage_name: str,
        provenance: Mapping[str, PlainData],
        *,
        attempt: int,
    ) -> None:
        path = self._stage_file_path(run_id, stage_name, "provenance.json")
        payload = self._build_stage_payload(
            run_id=run_id,
            stage_name=stage_name,
            attempt=attempt,
            field_name="provenance",
            field_value=ensure_plain_data(provenance, path="provenance"),
        )
        atomic_write_json(path, payload)

    def read_stage_log(self, run_id: str, stage_name: str, stream: str) -> str | None:
        validated_stream = validate_log_stream(stream)
        path = self.get_stage_log_path(run_id, stage_name, validated_stream)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def write_stage_log(self, run_id: str, stage_name: str, stream: str, content: str) -> None:
        validated_stream = validate_log_stream(stream)
        if not isinstance(content, str):
            raise UnsafeStorePathError(f"stage log content must be text, got {type(content)!r}")
        atomic_write_text(self.get_stage_log_path(run_id, stage_name, validated_stream), content)

    def _stage_file_path(self, run_id: str, stage_name: str, filename: str) -> Path:
        stage_dir = self.get_stage_dir(run_id, stage_name)
        stage_dir.mkdir(parents=True, exist_ok=True)
        return stage_dir / filename

    def _read_optional_json(self, path: Path) -> dict[str, object] | list[object] | None:
        if not path.exists():
            return None
        if not path.is_file():
            raise CorruptStoreDocumentError(f"Expected file at {path}")
        try:
            value = json_loads(path.read_text(encoding="utf-8"), path=str(path))
        except DeserializationError as exc:
            raise CorruptStoreDocumentError(f"Malformed JSON at {path}: {exc}") from exc
        if not isinstance(value, (dict, list)):
            raise CorruptStoreDocumentError(f"Store JSON at {path} must be an object or array")
        return value

    def _read_run_wrapper(self, run_id: str) -> dict[str, PlainData]:
        path = self.get_run_dir(run_id) / "run.json"
        if not path.is_file():
            raise MissingStoreDocumentError(f"run metadata missing at {path}")
        data = self._read_optional_json(path)
        if data is None or not isinstance(data, dict):
            raise CorruptStoreDocumentError(f"run metadata for {run_id} must be an object")
        if data.get("schema_version") != _SCHEMA_VERSION:
            raise CorruptStoreDocumentError(f"Unsupported run metadata schema at {path}")
        if data.get("run_id") != run_id:
            raise CorruptStoreDocumentError(f"run_id mismatch in {path}")
        try:
            return {
                "schema_version": _SCHEMA_VERSION,
                "run_id": str(data["run_id"]),
                "created_at": str(data["created_at"]),
                "run_dir": str(data["run_dir"]),
                "metadata": ensure_plain_data(data.get("metadata", {}), path="metadata"),
            }
        except Exception as exc:
            raise CorruptStoreDocumentError(f"Malformed run metadata at {path}: {exc}") from exc

    def _build_stage_payload(
        self,
        *,
        run_id: str,
        stage_name: str,
        attempt: int,
        field_name: str,
        field_value: PlainData,
        failure_timestamp_field: bool = False,
    ) -> dict[str, PlainData]:
        run_id_text = validate_run_id(run_id, field="run_id")
        stage_name_text = validate_stage_name(stage_name, field="stage_name")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
            raise UnsafeStorePathError("attempt must be a positive integer")
        return {
            "schema_version": _SCHEMA_VERSION,
            "run_id": run_id_text,
            "stage_name": stage_name_text,
            "attempt": attempt,
            "failed_at" if failure_timestamp_field else "created_at": utc_timestamp(),
            field_name: field_value,
        }

    def _validate_stage_attempt_payload(
        self,
        payload: dict[str, object],
        run_id: str,
        stage_name: str,
        field_name: str,
    ) -> None:
        failure_key = "failed_at" if field_name == "failure" else "created_at"
        if payload.get(failure_key) is None:
            raise CorruptStoreDocumentError(f"stage payload missing {failure_key!r} for {run_id}/{stage_name}")

        run_id_text = validate_run_id(run_id, field="run_id")
        if payload.get("run_id") != run_id_text:
            raise CorruptStoreDocumentError(f"stage payload run_id mismatch for {run_id}")
        if payload.get("stage_name") != stage_name:
            raise CorruptStoreDocumentError(f"stage payload stage_name mismatch for {stage_name}")
        if payload.get("schema_version") != _SCHEMA_VERSION:
            raise CorruptStoreDocumentError(f"Unsupported stage payload schema for {run_id}/{stage_name}")
        attempt = payload.get("attempt")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt <= 0:
            raise CorruptStoreDocumentError("stage payload attempt must be a positive integer")
        if field_name not in payload:
            raise CorruptStoreDocumentError(f"stage payload missing {field_name!r} for {run_id}/{stage_name}")
        if field_name in {"inputs", "outputs"}:
            field_value = payload[field_name]
            if not isinstance(field_value, dict):
                raise CorruptStoreDocumentError(f"stage payload {field_name!r} for {run_id}/{stage_name} must be an object")
            for key in field_value:
                validate_output_name(key, field=f"{field_name}_key")

    def _validate_run_identifier_for_status(self, run_id: str, status_run_id: str) -> None:
        if status_run_id != run_id:
            raise UnsafeStorePathError(f"run id mismatch for status payload: {status_run_id} != {run_id}")

    def _validate_stage_match(self, run_id: str, stage_name: str, status: StageStatusRecord) -> None:
        if status.run_id != run_id:
            raise UnsafeStorePathError(f"run id mismatch for stage status: {status.run_id} != {run_id}")
        if status.stage_name != stage_name:
            raise UnsafeStorePathError(f"stage name mismatch for stage status: {status.stage_name} != {stage_name}")

    def _ensure_plain_mapping(self, value: object, *, path: str) -> dict[str, PlainData]:
        normalized = ensure_plain_data(value, path=path)
        if not isinstance(normalized, dict):
            raise CorruptStoreDocumentError(f"{path} must be a mapping")
        return normalized


def _serialize_stage_artifact_index(index: Mapping[str, ArtifactRef]) -> dict[str, PlainData]:
    if not isinstance(index, Mapping):
        raise CorruptStoreDocumentError("stage artifact payload must be a mapping")
    payload: dict[str, PlainData] = {}
    for key, ref in index.items():
        validated_key = validate_output_name(key, field="artifact_key")
        if not isinstance(ref, ArtifactRef):
            raise CorruptStoreDocumentError(f"stage artifact payload entry {validated_key!r} must be an ArtifactRef")
        payload[validated_key] = ensure_plain_data(ref.to_dict(), path=f"stage_artifact[{validated_key!r}]")
    return payload


def _deserialize_stage_artifact_index(mapping: object) -> dict[str, ArtifactRef]:
    if not isinstance(mapping, dict):
        raise CorruptStoreDocumentError("stage artifact payload must be an object")

    parsed: dict[str, ArtifactRef] = {}
    for key, value in mapping.items():
        validated_key = validate_output_name(key, field="artifact_key")
        if not isinstance(value, dict):
            raise CorruptStoreDocumentError(f"stage artifact payload value for {validated_key!r} must be an object")
        try:
            parsed[validated_key] = ArtifactRef.from_dict(dict(value))
        except ArtifactValidationError as exc:
            raise CorruptStoreDocumentError(f"invalid artifact ref for {validated_key!r}: {exc}") from exc
    return parsed


__all__ = ["LocalRunStore"]

"""Unit tests for local run-store behavior."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import loom.pipeline.stores.run_uri as run_uri_module
from loom.artifacts import ArtifactRef
from loom.pipeline import RunStatus, StageStatus
from loom.pipeline.events import EventScope, PipelineEvent
from loom.pipeline.status import RunStatusRecord, StageStatusRecord
from loom.pipeline.stores import (
    CorruptStoreDocumentError,
    InvalidRunURIError,
    LocalRunStore,
    PreparedRunStorePayloadError,
    RunLockConflictError,
    RunLockReleaseError,
    RunNotFoundError,
    UnsafeStorePathError,
    atomic_write_json,
    allocate_local_run_uri,
    path_to_run_uri,
    resolve_local_run_uri,
)
from loom.serialization import PlainData


def _artifact_ref(*, artifact_id: str = "stage/out") -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        uri="file:///tmp/stage/out.json",
        artifact_type="json",
        codec_key="json.v1",
    )


def _run_uri(tmp_path: Path, name: str = "run1") -> str:
    return path_to_run_uri(tmp_path / "runs" / name)


def _prepared_run_payload(run_uri: str) -> dict[str, PlainData]:
    return {
        "schema_version": 1,
        "run_uri": run_uri,
        "prepared_at": "2020-01-01T00:00:00Z",
        "executor_name": "local",
        "continuation_type": "whole_run",
        "plan": {"plan_path": "plan.json"},
        "config": {"composition_manifest_ref": "config/composition_manifest.json"},
        "provenance": {"command_ref": "provenance/command.json"},
        "runtime": {"document_ref": "runtime.json", "executor": "local"},
        "metadata": {},
    }


def test_run_uri_resolves_documented_local_forms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    cases = {
        path_to_run_uri(tmp_path / "absolute"): tmp_path / "absolute",
        "file://./relative": cwd / "relative",
        "file://../sibling": tmp_path / "sibling",
    }

    for raw_uri, expected_path in cases.items():
        resolved = resolve_local_run_uri(raw_uri)
        assert resolved.path == expected_path.resolve(strict=False)
        assert resolved.uri == path_to_run_uri(expected_path)


@pytest.mark.parametrize(
    "raw_uri",
    [
        "run1",
        "/tmp/run1",
        "file://localhost/tmp/run1",
        "file://server/tmp/run1",
        "s3://bucket/run1",
        "file:///tmp/run1?x=1",
        "file:///tmp/run1#frag",
        "file://",
        " file:///tmp/run1",
    ],
)
def test_run_uri_rejects_unsupported_forms(raw_uri: str) -> None:
    with pytest.raises(InvalidRunURIError):
        resolve_local_run_uri(raw_uri)


def test_default_run_uri_allocation_uses_store_root_and_collisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "runs"
    first = root / "20200101T000000Z"
    first.mkdir(parents=True)
    monkeypatch.setattr(
        run_uri_module,
        "safe_timestamp_for_path",
        lambda *, timespec: "20200101T000000Z",
    )

    assert allocate_local_run_uri(root) == path_to_run_uri(root / "20200101T000000Z-2")


def test_local_run_creation_writes_layout(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri, metadata={"project": "demo"})
    run_dir = store.local_run_dir(run_uri)

    assert run_dir.exists()
    assert (run_dir / "config").is_dir()
    assert (run_dir / "provenance").is_dir()
    assert (run_dir / "stages").is_dir()
    assert (run_dir / "artifacts").is_dir()
    assert (run_dir / "run.json").is_file()


def test_open_run_validates_required_run_metadata(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    store.open_run(run_uri)


def test_local_run_metadata_optional_reads(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri, metadata={"a": 1})
    metadata = store.read_run_document(run_uri)
    assert metadata["run_uri"] == run_uri
    assert metadata["metadata"] == {"a": 1}
    assert store.read_plan(run_uri) is None
    assert store.read_artifact_index(run_uri) == {}
    assert store.read_events(run_uri) == ()


def test_local_run_appends_and_reads_events(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    first = store.append_event(
        run_uri,
        PipelineEvent(
            scope=EventScope.run(),
            event_type="run.created",
            payload={"source": "test"},
            timestamp="2020-01-01T00:00:00Z",
        ),
    )
    second = store.append_event(
        run_uri,
        PipelineEvent(scope=EventScope.stage("build"), event_type="stage.started"),
    )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [record.sequence for record in store.read_events(run_uri)] == [1, 2]
    assert store.read_events(run_uri)[0].payload == {"source": "test"}
    assert (store.local_run_dir(run_uri) / "events.jsonl").read_text(
        encoding="utf-8"
    ).count("\n") == 2


def test_local_run_rejects_corrupt_event_log(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    path = store.local_run_dir(run_uri) / "events.jsonl"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "sequence": 2,
                "timestamp": "2020-01-01T00:00:00Z",
                "scope": {"kind": "RUN", "stage_name": None},
                "event_type": "run.created",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CorruptStoreDocumentError) as exc_info:
        store.read_events(run_uri)
    assert "sequence gap" in str(exc_info.value)
    assert f"{path}:1" in str(exc_info.value)


def test_local_run_acquires_reads_and_releases_lock(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    record = store.acquire_run_lock(run_uri, owner={"worker": "unit"})

    assert record.run_uri == run_uri
    assert record.token
    assert record.owner["metadata"] == {"worker": "unit"}
    assert isinstance(record.owner["pid"], int)
    assert isinstance(record.owner["hostname"], str)
    assert store.read_run_lock(run_uri) == record
    assert (store.local_run_dir(run_uri) / "lock.json").exists()

    store.release_run_lock(run_uri, record.token)

    assert store.read_run_lock(run_uri) is None
    assert not (store.local_run_dir(run_uri) / "lock.json").exists()


def test_local_run_lock_conflict_and_release_errors_preserve_lock(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    record = store.acquire_run_lock(run_uri)

    with pytest.raises(RunLockConflictError):
        store.acquire_run_lock(run_uri)

    with pytest.raises(RunLockReleaseError, match="mismatch"):
        store.release_run_lock(run_uri, "wrong-token")

    assert store.read_run_lock(run_uri) == record


def test_local_run_lock_requires_existing_run(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")

    with pytest.raises(RunNotFoundError):
        store.acquire_run_lock(_run_uri(tmp_path, "missing"))


def test_local_run_rejects_corrupt_lock_document(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    lock_path = store.local_run_dir(run_uri) / "lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_uri": _run_uri(tmp_path, "other"),
                "token": "token",
                "acquired_at": "2020-01-01T00:00:00Z",
                "owner": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(CorruptStoreDocumentError):
        store.read_run_lock(run_uri)
    with pytest.raises(RunLockReleaseError):
        store.release_run_lock(run_uri, "token")


def test_local_run_status_plan_and_artifacts(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    status = RunStatusRecord(
        run_uri=run_uri,
        status=RunStatus.CREATED,
        created_at="2020-01-01T00:00:00Z",
        updated_at="2020-01-01T00:00:00Z",
    )
    store.write_run_status(run_uri, status)
    assert store.read_run_status(run_uri) == status

    plan_payload: dict[str, PlainData] = {"stage": ["a", "b"]}
    store.write_plan(run_uri, plan_payload)
    assert store.read_plan(run_uri) == plan_payload

    prepared_run = _prepared_run_payload(run_uri)
    store.write_prepared_run(run_uri, prepared_run)
    assert store.read_prepared_run(run_uri) == prepared_run
    prepared_wrapper = json.loads(
        (store.local_run_dir(run_uri) / "prepared_run.json").read_text(
            encoding="utf-8"
        )
    )
    assert prepared_wrapper == prepared_run

    runtime_payload: dict[str, PlainData] = {
        "schema_version": 1,
        "executor": "local",
        "stages": {"build": {"executor": "local"}},
    }
    store.write_runtime_metadata(run_uri, runtime_payload)
    assert store.read_runtime_metadata(run_uri) == runtime_payload
    runtime_wrapper = json.loads(
        (store.local_run_dir(run_uri) / "runtime.json").read_text(encoding="utf-8")
    )
    assert set(runtime_wrapper) == {
        "schema_version",
        "run_uri",
        "updated_at",
        "runtime",
    }
    assert runtime_wrapper["run_uri"] == run_uri
    assert runtime_wrapper["runtime"] == runtime_payload

    ref = ArtifactRef(
        artifact_id="stage/output",
        uri="file:///tmp/stage/output.json",
        artifact_type="json",
        codec_key="json.v1",
    )
    store.write_artifact_index(run_uri, {"stage.output": ref})
    assert store.read_artifact_index(run_uri) == {"stage.output": ref}


def test_local_run_write_prepared_run_rejects_unsafe_nested_payload(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    prepared_run = _prepared_run_payload(run_uri)
    prepared_run["metadata"] = {
        "adapter": {
            "kind": "adapter_summary",
            "data": {"raw_adapter_payload": {"token": "secret"}},
        }
    }

    with pytest.raises(PreparedRunStorePayloadError) as exc_info:
        store.write_prepared_run(run_uri, prepared_run)

    assert exc_info.value.category == "unsafe_field"
    assert (
        exc_info.value.field
        == "prepared_run.metadata.adapter.data.raw_adapter_payload"
    )
    assert not (store.local_run_dir(run_uri) / "prepared_run.json").exists()


def test_local_run_snapshots_and_provenance(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    store.write_config_snapshot(run_uri, "raw", "a: b\n")
    assert store.read_config_snapshot(run_uri, "raw") == "a: b\n"
    manifest: dict[str, PlainData] = {
        "source_artifacts": [{"kind": "config", "path": "config.yaml"}],
        "metadata": {"fingerprint": "sha256:abc"},
    }
    store.write_composition_manifest(run_uri, manifest)
    assert store.read_composition_manifest(run_uri) == manifest
    read_manifest = store.read_composition_manifest(run_uri)
    assert read_manifest is not None
    read_manifest["metadata"] = {}
    assert store.read_composition_manifest(run_uri) == manifest
    wrapper_path = store.local_run_dir(run_uri) / "config" / "composition_manifest.json"
    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
    assert set(wrapper) == {
        "schema_version",
        "run_uri",
        "created_at",
        "composition_manifest",
    }
    assert wrapper["schema_version"] == 1
    assert wrapper["run_uri"] == run_uri
    assert wrapper["composition_manifest"] == manifest
    store.write_recipe_manifest(run_uri, ({"name": "demo"},))
    assert store.read_recipe_manifest(run_uri) == ({"name": "demo"},)

    store.write_provenance_document(run_uri, "environment", {"python": "3.12"})
    assert store.read_provenance_document(run_uri, "environment") == {"python": "3.12"}


def test_local_run_stage_docs_and_logs(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    stage_status = StageStatusRecord(
        run_uri=run_uri,
        stage_name="stage",
        status=StageStatus.PENDING,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
    )
    store.write_stage_status(run_uri, "stage", stage_status)
    assert store.read_stage_status(run_uri, "stage") == stage_status

    store.write_stage_inputs(
        run_uri,
        "stage",
        {
            "inp": ArtifactRef(
                artifact_id="other/one",
                uri="file:///tmp/other/one.json",
                artifact_type="json",
                codec_key="json.v1",
            ),
        },
        attempt=1,
    )
    assert store.read_stage_inputs(run_uri, "stage")

    store.write_stage_outputs(
        run_uri,
        "stage",
        {
            "out": ArtifactRef(
                artifact_id="stage/out",
                uri="file:///tmp/stage/out.json",
                artifact_type="json",
                codec_key="json.v1",
            ),
        },
        attempt=1,
    )
    assert store.read_stage_outputs(run_uri, "stage")

    store.write_stage_fingerprint(run_uri, "stage", {"x": 1}, attempt=1)
    assert store.read_stage_fingerprint(run_uri, "stage") == {"x": 1}

    store.write_stage_failure(run_uri, "stage", {"reason": "boom"}, attempt=1)
    assert store.read_stage_failure(run_uri, "stage") == {"reason": "boom"}

    store.write_stage_worker_request(
        run_uri,
        "stage",
        {"stage_name": "stage", "attempt": 1},
        attempt=1,
    )
    assert store.read_stage_worker_request(run_uri, "stage", attempt=1) == {
        "stage_name": "stage",
        "attempt": 1,
    }

    store.write_stage_worker_result(
        run_uri,
        "stage",
        {"stage_name": "stage", "attempt": 1, "status": "SUCCEEDED"},
        attempt=1,
    )
    assert store.read_stage_worker_result(run_uri, "stage", attempt=1) == {
        "stage_name": "stage",
        "attempt": 1,
        "status": "SUCCEEDED",
    }

    store.write_stage_provenance(run_uri, "stage", {"tool": "x"}, attempt=1)
    assert store.read_stage_provenance(run_uri, "stage") == {"tool": "x"}

    store.write_stage_log(run_uri, "stage", "stdout", "line1\n")
    assert store.read_stage_log(run_uri, "stage", "stdout") == "line1\n"


def test_local_run_worker_records_validate_attempt_identity(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    store.write_stage_worker_request(
        run_uri,
        "stage",
        {"stage_name": "stage", "attempt": 1},
        attempt=1,
    )

    with pytest.raises(CorruptStoreDocumentError, match="expected 2"):
        store.read_stage_worker_request(run_uri, "stage", attempt=2)


def test_local_run_inspection_discovers_stage_state(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    store.write_run_status(
        run_uri,
        RunStatusRecord(
            run_uri=run_uri,
            status=RunStatus.SUCCEEDED,
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-01T00:00:01Z",
        ),
    )
    stage_status = StageStatusRecord(
        run_uri=run_uri,
        stage_name="build",
        status=StageStatus.SUCCEEDED,
        attempt=1,
        updated_at="2020-01-01T00:00:01Z",
    )
    store.write_stage_status(run_uri, "build", stage_status)
    store.write_stage_outputs(run_uri, "build", {"out": _artifact_ref()}, attempt=1)
    store.write_stage_provenance(run_uri, "build", {"tool": "x"}, attempt=1)
    store.write_stage_log(run_uri, "build", "stdout", "line1\nline2\n")
    store.write_stage_status(
        run_uri,
        "report",
        StageStatusRecord(
            run_uri=run_uri,
            stage_name="report",
            status=StageStatus.BLOCKED,
            attempt=1,
            updated_at="2020-01-01T00:00:02Z",
            message="blocked",
        ),
    )

    assert store.list_run_stages(run_uri) == ("build", "report")
    inspection = store.inspect_run_state(run_uri)

    assert inspection.run_status is not None
    assert inspection.run_status.status is RunStatus.SUCCEEDED
    assert inspection.artifact_count == 0
    build = inspection.stage_inspections[0]
    assert build.stage_name == "build"
    assert build.status == stage_status
    assert build.output_count == 1
    assert build.provenance_available is True
    assert build.stdout_available is True
    assert build.stderr_available is False


def test_local_run_reads_and_writes_blocked_stage_status_only(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    status = StageStatusRecord(
        run_uri=run_uri,
        stage_name="blocked",
        status=StageStatus.BLOCKED,
        attempt=1,
        updated_at="2020-01-01T00:00:00Z",
        message="upstream failed",
        metadata={"blocked_by": ["stage"], "reason_code": "upstream_failed"},
    )

    store.write_stage_status(run_uri, "blocked", status)

    assert store.read_stage_status(run_uri, "blocked") == status
    stage_dir = store.local_stage_dir(run_uri, "blocked")
    assert sorted(path.name for path in stage_dir.iterdir()) == ["status.json"]


def test_local_run_rejects_corrupt_stage_plain_mapping(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    atomic_write_json(
        store.local_stage_dir(run_uri, "stage") / "fingerprint.json",
        {
            "schema_version": 1,
            "run_uri": run_uri,
            "stage_name": "stage",
            "attempt": 1,
            "created_at": "2020-01-01T00:00:00Z",
            "fingerprint": ["not", "a", "mapping"],
        },
    )

    with pytest.raises(CorruptStoreDocumentError):
        store.read_stage_fingerprint(run_uri, "stage")


def test_local_run_rejects_non_mapping_composition_manifest_write(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    with pytest.raises(UnsafeStorePathError, match="composition manifest"):
        store.write_composition_manifest(run_uri, ["not", "a", "mapping"])  # type: ignore[arg-type]


def test_local_run_generated_artifact_path_helper_is_safe_relative(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    path = store.local_generated_artifact_path(
        run_uri,
        "generated/submissions/p1/manifest.json",
    )

    assert path == store.local_run_dir(run_uri) / "generated" / "submissions" / "p1" / "manifest.json"
    assert path.parent.exists() is False


@pytest.mark.parametrize(
    "relative_path",
    [
        "",
        "/absolute",
        "generated//manifest.json",
        "generated/../manifest.json",
        "generated/./manifest.json",
        "generated\\manifest.json",
        "generated/manifest\n.json",
    ],
)
def test_local_run_generated_artifact_path_rejects_unsafe_relative_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)

    with pytest.raises(UnsafeStorePathError):
        store.local_generated_artifact_path(run_uri, relative_path)


def test_local_run_validates_prepared_run_document(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    path = store.local_run_dir(run_uri) / "prepared_run.json"
    valid = _prepared_run_payload(run_uri)
    cases = [
        {key: value for key, value in valid.items() if key != "prepared_at"},
        {**valid, "unexpected": True},
        {**valid, "schema_version": 2},
        {**valid, "run_uri": _run_uri(tmp_path, "other")},
        {**valid, "prepared_at": "2020-01-01 00:00:00"},
        {**valid, "plan": []},
    ]

    for payload in cases:
        atomic_write_json(path, payload)
        with pytest.raises(CorruptStoreDocumentError) as exc_info:
            store.read_prepared_run(run_uri)
        assert str(path) in str(exc_info.value)


def test_local_run_validates_composition_manifest_wrapper(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    path = store.local_run_dir(run_uri) / "config" / "composition_manifest.json"
    valid_timestamp = "2020-01-01T00:00:00Z"
    valid = {
        "schema_version": 1,
        "run_uri": run_uri,
        "created_at": valid_timestamp,
        "composition_manifest": {"source_artifacts": []},
    }
    missing_field_cases = [
        {key: value for key, value in valid.items() if key != field_name}
        for field_name in (
            "schema_version",
            "run_uri",
            "created_at",
            "composition_manifest",
        )
    ]
    cases = [
        *missing_field_cases,
        {**valid, "unexpected": True},
        {**valid, "schema_version": 2},
        {**valid, "schema_version": True},
        {**valid, "run_uri": _run_uri(tmp_path, "other")},
        {**valid, "created_at": "2020-01-01 00:00:00"},
        {**valid, "composition_manifest": []},
    ]

    for payload in cases:
        atomic_write_json(path, payload)
        with pytest.raises(CorruptStoreDocumentError) as exc_info:
            store.read_composition_manifest(run_uri)
        assert str(path) in str(exc_info.value)


def test_local_run_rejects_corrupt_wrapper_fields_with_document_path(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    run_dir = store.local_run_dir(run_uri)
    stage_dir = store.local_stage_dir(run_uri, "stage")
    valid_timestamp = "2020-01-01T00:00:00Z"
    cases: list[tuple[Path, dict[str, object], Callable[[], object]]] = [
        (
            run_dir / "run.json",
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "created_at": valid_timestamp,
                "run_dir": "file:///tmp/run1",
            },
            lambda: store.read_run_document(run_uri),
        ),
        (
            run_dir / "plan.json",
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "updated_at": "2020-01-01 00:00:00",
                "plan": {},
            },
            lambda: store.read_plan(run_uri),
        ),
        (
            run_dir / "artifacts.json",
            {
                "schema_version": True,
                "run_uri": run_uri,
                "updated_at": valid_timestamp,
                "artifacts": {},
            },
            lambda: store.read_artifact_index(run_uri),
        ),
        (
            run_dir / "config" / "composition_manifest.json",
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "created_at": valid_timestamp,
            },
            lambda: store.read_composition_manifest(run_uri),
        ),
        (
            run_dir / "config" / "recipe_manifest.json",
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "created_at": valid_timestamp,
            },
            lambda: store.read_recipe_manifest(run_uri),
        ),
        (
            store.local_provenance_path(run_uri, "environment"),
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "kind": "environment",
                "created_at": valid_timestamp,
                "provenance": [],
            },
            lambda: store.read_provenance_document(run_uri, "environment"),
        ),
        (
            stage_dir / "fingerprint.json",
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "stage_name": "stage",
                "attempt": 1,
                "created_at": 123,
                "fingerprint": {},
            },
            lambda: store.read_stage_fingerprint(run_uri, "stage"),
        ),
        (
            stage_dir / "failure.json",
            {
                "schema_version": 1,
                "run_uri": run_uri,
                "stage_name": "stage",
                "attempt": 1,
                "created_at": valid_timestamp,
                "failure": {},
            },
            lambda: store.read_stage_failure(run_uri, "stage"),
        ),
    ]

    for path, payload, reader in cases:
        atomic_write_json(path, payload)
        with pytest.raises(CorruptStoreDocumentError) as exc_info:
            reader()
        assert str(path) in str(exc_info.value)


def test_local_run_rejects_corrupt_artifact_index_refs(tmp_path: Path) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    run_dir = store.local_run_dir(run_uri)
    path = run_dir / "artifacts.json"
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "run_uri": run_uri,
            "updated_at": "2020-01-01T00:00:00Z",
            "artifacts": {
                "stage.output": {
                    "artifact_id": "",
                    "uri": "file:///tmp/out.json",
                    "artifact_type": "json",
                },
            },
        },
    )

    with pytest.raises(CorruptStoreDocumentError) as exc_info:
        store.read_artifact_index(run_uri)
    assert str(path) in str(exc_info.value)


def test_local_run_wraps_unsafe_root_artifact_index_keys_as_corrupt(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    run_dir = store.local_run_dir(run_uri)
    path = run_dir / "artifacts.json"
    atomic_write_json(
        path,
        {
            "schema_version": 1,
            "run_uri": run_uri,
            "updated_at": "2020-01-01T00:00:00Z",
            "artifacts": {"stage.bad/name": _artifact_ref().to_dict()},
        },
    )

    with pytest.raises(CorruptStoreDocumentError) as exc_info:
        store.read_artifact_index(run_uri)
    assert str(path) in str(exc_info.value)


def test_local_run_wraps_stage_artifact_index_failures_as_corrupt(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(root=tmp_path / "runs")
    run_uri = _run_uri(tmp_path)
    store.create_run(run_uri)
    path = store.local_stage_dir(run_uri, "stage") / "outputs.json"
    wrapper = {
        "schema_version": 1,
        "run_uri": run_uri,
        "stage_name": "stage",
        "attempt": 1,
        "created_at": "2020-01-01T00:00:00Z",
    }

    atomic_write_json(
        path, {**wrapper, "outputs": {"bad/name": _artifact_ref().to_dict()}}
    )
    with pytest.raises(CorruptStoreDocumentError) as unsafe_key_exc:
        store.read_stage_outputs(run_uri, "stage")
    assert str(path) in str(unsafe_key_exc.value)

    atomic_write_json(
        path,
        {
            **wrapper,
            "outputs": {
                "out": {
                    "artifact_id": "",
                    "uri": "file:///tmp/stage/out.json",
                    "artifact_type": "json",
                },
            },
        },
    )
    with pytest.raises(CorruptStoreDocumentError) as bad_ref_exc:
        store.read_stage_outputs(run_uri, "stage")
    assert str(path) in str(bad_ref_exc.value)

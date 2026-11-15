"""Fresh byte evidence authorizes reuse; cache contents never hide changed inputs."""

from dataclasses import replace
import os
from pathlib import Path
from typing import cast

import pytest

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec
from loom.pipeline.planning import ExecutionPlan
from loom.pipeline.stores.local_runs import LocalRunStore
from loom.pipeline.stores.errors import CorruptStoreDocumentError
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue._validated_context_cache import ValidatedContextCache
from loom.queue.agent_sessions import AgentPolicyConfig
from loom.queue.local_daemon_execution import ManagedLocalIntent, load_managed_local_intent
from loom.queue.local_daemon_runtime import prepare_managed_local_runtime_record
from loom.serialization import PlainData, json_dumps_pretty
from loom.serialization.errors import DeserializationError
from tests.integration.queue.test_local_daemon_production import (
    _daemon_config, _execution_requirements, _persist_single_stage_run,
)
from tests.unit.loom.pipeline.stores.test_local_runs import _prepared_run_payload
from tests.unit.loom.queue.test_agent_sessions import _policy


def _prepare(tmp_path, *, evidence=True, target=None, local_binding=False):
    store, uri, pipeline = _persist_single_stage_run(tmp_path / "runs")
    config = _daemon_config(tmp_path)
    stage = cast(list[dict[str, object]], pipeline["stages"])[0]
    if target is not None:
        stage["placement"] = {"target": target}
        config = replace(config, agent_policy=_policy())
    if local_binding:
        assert config.resident_worker_launch_profile is not None
        from loom.queue.preparation import LOCAL_PREPARATION_SCOPE
        stage["placement"] = {"target": config.machine_id}
        stage["fingerprint"] = {
            LOCAL_PREPARATION_SCOPE: {
                "agent_id": config.machine_id,
                "binding_fingerprint": config.resident_worker_launch_profile.fingerprint,
            },
        }
    store.write_config_snapshot(uri, "resolved", json_dumps_pretty({"pipeline": pipeline}))
    if evidence:
        authorship: dict[str, PlainData] = {"final_value_authorship": [{"path": ["input"], "source_path": "base.yaml"}]}
        store.write_composition_manifest(uri, {"schema_version": 1, "metadata": authorship})
        store.write_run_user_metadata(uri, {"config_provenance": {
            "schema_version": 2, "metadata": authorship,
        }})
        prepared = _prepared_run_payload(uri)
        prepared["metadata"] = {"loom.project_contracts": {
            "kind": "project_contracts",
            "data": {
                "schema_version": 1,
                "namespace": "test-project",
                "report_ref": ArtifactRef(
                    "report", "report.json", "json", codec_key="json.v1",
                    checksum="sha256:" + "a" * 64, producer_stage="prepare",
                ).to_dict(),
            },
        }}
        store.write_prepared_run(uri, prepared)
    spec = PipelineSpec.from_config(pipeline)
    prepare_managed_local_runtime_record(
        store=store, run_uri=uri, plan=ExecutionPlan.from_dict(store.read_plan(uri)),
        pipeline=spec, execution_requirements=_execution_requirements(spec),
    )
    return store, uri, config


def test_unchanged_inputs_are_read_and_hashed_without_deep_decoding(tmp_path, monkeypatch):
    from loom.queue import local_daemon_execution, local_daemon_runtime
    from loom.pipeline.stores import local_runs

    store, uri, config = _prepare(tmp_path)
    cache = ValidatedContextCache[ManagedLocalIntent]()
    first = load_managed_local_intent(config, uri, cache=cache)
    reads = []
    original = Path.read_bytes

    def read(path):
        reads.append(path.relative_to(store.local_run_dir(uri)).as_posix())
        return original(path)

    def unexpected_decode(*args, **kwargs):
        pytest.fail("unchanged validated bytes were decoded again")

    monkeypatch.setattr(Path, "read_bytes", read)
    for owner in (local_daemon_execution, local_daemon_runtime, local_runs):
        monkeypatch.setattr(owner, "json_loads", unexpected_decode)
    assert load_managed_local_intent(config, uri, cache=cache) is first
    assert set(reads) == {
        "run.json", "plan.json", "prepared_run.json", "config/resolved.yaml",
        "config/managed_local_runtime.json", "config/composition_manifest.json",
    }
    assert len(reads) == 6


@pytest.mark.parametrize("document", [
    "run.json", "plan.json", "prepared_run.json", "config/resolved.yaml",
    "config/managed_local_runtime.json", "config/composition_manifest.json",
])
def test_changed_bytes_with_same_size_and_mtime_cannot_reuse_context(tmp_path, document):
    store, uri, config = _prepare(tmp_path)
    cache = ValidatedContextCache[ManagedLocalIntent]()
    load_managed_local_intent(config, uri, cache=cache)
    path = store.local_run_dir(uri) / document
    original = path.read_bytes()
    stat = path.stat()
    position = original.rindex(b"}")
    path.write_bytes(original[:position] + b"!" + original[position + 1:])
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    with pytest.raises((CorruptStoreDocumentError, QueueServiceError, DeserializationError)):
        load_managed_local_intent(config, uri, cache=cache)


def test_verification_and_decode_use_one_capture_even_if_file_changes(tmp_path, monkeypatch):
    store, uri, config = _prepare(tmp_path)
    path = store.local_run_dir(uri) / "config/composition_manifest.json"
    original = LocalRunStore._read_document_bytes
    reads = 0

    def changed_after_read(reader, selected):
        nonlocal reads
        content = original(reader, selected)
        if selected == path:
            reads += 1
            selected.write_bytes(content.replace(b"base.yaml", b"evil.yaml"))
        return content

    monkeypatch.setattr(LocalRunStore, "_read_document_bytes", changed_after_read)
    cache = ValidatedContextCache[ManagedLocalIntent]()
    assert load_managed_local_intent(config, uri, cache=cache).plan.run_uri == uri
    assert reads == 1
    with pytest.raises(QueueServiceError, match="composition reference"):
        load_managed_local_intent(config, uri, cache=cache)


def test_new_runtime_references_capture_new_dependencies(tmp_path):
    store, uri, config = _prepare(tmp_path, evidence=False)
    cache = ValidatedContextCache[ManagedLocalIntent]()
    old = load_managed_local_intent(config, uri, cache=cache)
    store.write_composition_manifest(uri, {"metadata": {"final_value_authorship": []}})
    store.write_run_user_metadata(uri, {"config_provenance": {
        "schema_version": 2, "metadata": {"final_value_authorship": []},
    }})
    prepare_managed_local_runtime_record(
        store=store, run_uri=uri, plan=old.plan, pipeline=old.pipeline,
        execution_requirements=old.execution_requirements,
    )
    new = load_managed_local_intent(config, uri, cache=cache)
    assert new.digest != old.digest
    (store.local_run_dir(uri) / "config/composition_manifest.json").unlink()
    with pytest.raises(QueueServiceError, match="composition reference"):
        load_managed_local_intent(config, uri, cache=cache)


def test_cache_is_bounded_and_recent_contexts_survive_eviction(tmp_path):
    cache = ValidatedContextCache[ManagedLocalIntent](max_entries=2)
    runs = [_prepare(tmp_path / str(index), evidence=False) for index in range(3)]
    loaded = [load_managed_local_intent(config, uri, cache=cache) for _, uri, config in runs]
    assert len(cache) == 2
    assert load_managed_local_intent(runs[1][2], runs[1][1], cache=cache) is loaded[1]
    assert load_managed_local_intent(runs[0][2], runs[0][1], cache=cache) is not loaded[0]
    assert len(cache) == 2
    assert load_managed_local_intent(runs[1][2], runs[1][1], cache=cache) is loaded[1]


def test_changed_agent_authorization_cannot_reuse_context(tmp_path):
    _, uri, config = _prepare(tmp_path, target="agent-a")
    cache = ValidatedContextCache[ManagedLocalIntent]()
    load_managed_local_intent(config, uri, cache=cache)
    with pytest.raises(QueueServiceError, match="unauthorized managed agent"):
        load_managed_local_intent(replace(config, agent_policy=AgentPolicyConfig()), uri, cache=cache)


@pytest.mark.parametrize("change", ["profile", "machine"])
def test_changed_local_preparation_binding_cannot_reuse_context(tmp_path, change):
    _, uri, config = _prepare(tmp_path, local_binding=True)
    cache = ValidatedContextCache[ManagedLocalIntent]()
    load_managed_local_intent(config, uri, cache=cache)
    assert config.resident_worker_launch_profile is not None
    changed = (
        replace(config, machine_id="machine-B") if change == "machine" else
        replace(config, resident_worker_launch_profile=replace(
            config.resident_worker_launch_profile, environment={"CHANGED": "1"},
        ))
    )
    with pytest.raises(QueueConflictError, match="local preparation binding identity"):
        load_managed_local_intent(changed, uri, cache=cache)


def test_changed_slurm_authorization_cannot_reuse_context(tmp_path):
    from loom.pipeline.executors.slurm.commands import FakeSlurmCommandRunner
    from tests.integration.queue.test_slurm_ready_stage import _profile, _persist_rejected_slurm_run

    profile = _profile(FakeSlurmCommandRunner(), capability_path=tmp_path / "capability")
    uri = _persist_rejected_slurm_run(tmp_path / "runs", profile)
    config = replace(_daemon_config(tmp_path), slurm_profiles=(profile,))
    cache = ValidatedContextCache[ManagedLocalIntent]()
    first = load_managed_local_intent(config, uri, cache=cache)
    profiles = {(profile.profile_id, profile.configuration_fingerprint): profile}
    assert load_managed_local_intent(config, uri, cache=cache, slurm_profiles=profiles) is first
    with pytest.raises(QueueServiceError, match="unavailable SLURM profile"):
        load_managed_local_intent(config, uri, cache=cache, slurm_profiles={})


def test_absent_optional_document_is_rechecked(tmp_path):
    _, uri, config = _prepare(tmp_path, evidence=False)
    cache = ValidatedContextCache[object]()
    calls = []

    def decode(store):
        calls.append(None)
        return store.read_prepared_run(uri)

    assert cache.load(config, uri, slurm_profiles=None, decode=decode) is None
    store = LocalRunStore(config.run_store_root)
    store.write_prepared_run(uri, _prepared_run_payload(uri))
    assert cache.load(config, uri, slurm_profiles=None, decode=decode) is not None
    assert len(calls) == 2


def test_snapshot_newline_conversion_keeps_existing_runtime_digest(tmp_path):
    store, uri, config = _prepare(tmp_path, evidence=False)
    first = load_managed_local_intent(config, uri)
    path = store.local_config_path(uri, "resolved")
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert load_managed_local_intent(config, uri).digest == first.digest


def test_slow_cache_read_does_not_hold_cache_lock(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    cache = ValidatedContextCache[ManagedLocalIntent](max_entries=2)
    store, uri, config = _prepare(tmp_path / "slow", evidence=False)
    _, other_uri, other_config = _prepare(tmp_path / "other", evidence=False)
    load_managed_local_intent(config, uri, cache=cache)
    other = load_managed_local_intent(other_config, other_uri, cache=cache)
    entered, release = Event(), Event()
    original = LocalRunStore._read_document_bytes
    blocked = store.local_run_dir(uri) / "config/managed_local_runtime.json"

    def read(reader, path):
        if path == blocked:
            entered.set()
            assert release.wait(5)
        return original(reader, path)

    monkeypatch.setattr(LocalRunStore, "_read_document_bytes", read)
    with ThreadPoolExecutor(max_workers=2) as workers:
        slow = workers.submit(load_managed_local_intent, config, uri, cache=cache)
        try:
            assert entered.wait(2)
            ready = workers.submit(load_managed_local_intent, other_config, other_uri, cache=cache)
            assert ready.result(2) is other
            assert not release.is_set()
        finally:
            release.set()
            slow.result(5)


def test_cached_input_read_failure_keeps_original_loader_diagnostic(tmp_path, monkeypatch):
    store, uri, config = _prepare(tmp_path)
    cache = ValidatedContextCache[ManagedLocalIntent]()
    load_managed_local_intent(config, uri, cache=cache)
    failed = store.local_run_dir(uri) / "config/composition_manifest.json"
    original = LocalRunStore._read_document_bytes

    def read(reader, path):
        if path == failed:
            raise PermissionError("retained composition unavailable")
        return original(reader, path)

    monkeypatch.setattr(LocalRunStore, "_read_document_bytes", read)
    with pytest.raises(QueueServiceError, match="managed composition reference is missing or changed"):
        load_managed_local_intent(config, uri, cache=cache)

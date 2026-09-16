"""Per-node contracts through installed preparation, native retention and workers."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, cast

import pytest

from loom.preparation import CoordinatorPreparation, decode_preparation_report
from loom.queue import LocalDaemon
from loom.queue.errors import QueueConflictError, QueueServiceError
from loom.queue.deployment import load_coordinator_service_config
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.pipeline._project_contracts import load_contract_report
from loom.artifacts import ArtifactRef
from loom.queue.preparation import PreparationChildInput
from loom.queue.local_daemon_execution import load_managed_local_intent
from tests.integration.queue.test_preparation_operations import _service, _result
from tests.integration.queue.test_reconciled_runs import _reconciled_request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def _text_service(tmp_path, *, delay=0, fail_once=False, opt_out=False):
    _service(tmp_path, local=True)
    installation = tmp_path / "installed-project"
    installation.mkdir()
    fixture = Path(__file__).parents[2] / "support" / "installed_text_project.py"
    (installation / "native_text_project.py").write_bytes(fixture.read_bytes())
    agent_path = tmp_path / "agent.json"
    agent = json.loads(agent_path.read_text())
    agent["resident_profiles"][0]["environment"]["PYTHONPATH"] = str(installation)
    agent["resident_profiles"][0]["cpu_capacity"] = 2
    agent_path.write_text(json.dumps(agent))
    coordinator_path = tmp_path / "coordinator.json"
    coordinator = json.loads(coordinator_path.read_text())
    coordinator["preparation"]["profiles"]["existing-project"]["project_processor"] = {
        "schema_version": 3,
        "callable": "native_text_project:inspect",
        "evidence_namespace": "text-project",
        "target_prefix": "text-",
    }
    coordinator_path.write_text(json.dumps(coordinator))
    config_path = tmp_path / "projects" / "pipeline.yaml"
    config = json.loads(config_path.read_text())
    config["pipeline"]["stages"] = [
        {
            "name": "author",
            "factory": {"_target_": "native_text_project.GenerateText"},
            "config": {"delay": delay, "fail_once": fail_once},
            "outputs": {"text": {"artifact_type": "json", "codec_key": "json.v1"}},
        },
        {
            "name": "reader",
            "factory": {"_target_": "native_text_project.CountLines"},
            "config": {"opt_out": opt_out},
            "inputs": {"text": "author.text"},
            "outputs": {"count": {"artifact_type": "json", "codec_key": "json.v1"}},
        },
    ]
    config_path.write_text(json.dumps(config))
    return load_coordinator_service_config(coordinator_path)


def _start(daemon, name, *, retry=False):
    daemon.start_run(_reconciled_request(name, retry=retry), principal_id="caller")
    operation = daemon.wait_operation(name, timeout=50).operation
    assert operation.state == "applied", (operation.to_dict(), daemon._service_error)
    return _result(operation)


@pytest.mark.parametrize("opt_out", [False, True])
def test_installed_text_report_reload_workers_and_completed_reuse(tmp_path, opt_out):
    service = _text_service(tmp_path, opt_out=opt_out)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "first")
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=40).state.value
            == "SUCCEEDED"
        )
        uri = first["prepared_run"]["run_uri"]
        store = cast(Any, LocalRunStore(service.daemon.run_store_root))
        entry = store.read_prepared_run(uri)["metadata"]["loom.project_contracts"]
        assert set(entry["data"]) == {"schema_version", "namespace", "report_ref"}
        assert entry["data"]["report_ref"] == first["report_ref"]
        report = cast(Any, load_contract_report(store, uri))
        assert report["composition"] == report["requested_composition"]
        assert set(report["project_contracts"]) == {"author", "reader"}
        assert (
            report["project_contracts"]["reader"]["semantic_key"] is None
        ) == opt_out
        for name in ("author", "reader"):
            request = store.read_stage_worker_request(uri, name, attempt=1)
            assert (
                request["metadata"]["loom.project_contract"]
                == report["project_contracts"][name]
            )
            assert "loom.project_contracts" not in request["metadata"]
            result = store.read_stage_worker_result(uri, name, attempt=1)
            ref = ArtifactRef.from_dict(next(iter(result["outputs"].values())))
            expected = "alpha\nbeta\n" if name == "author" else 2
            assert (
                LocalArtifactStore(store.local_artifact_root(uri)).load(ref) == expected
            )
        candidate = cast(
            Any,
            CoordinatorPreparation(service).capture_candidate(
                service.daemon, uri, None
            ),
        )
        assert candidate["project_contracts"] == report["project_contracts"]
        second = _start(daemon, "second")
        assert second["prepared_run"] == first["prepared_run"]
        assert second["verification_report_ref"] is not None
        assert store.read_stage_worker_request(uri, "author", attempt=1)["attempt"] == 1
        from loom.pipeline._project_contracts import validate_admitted_worker
        from loom.pipeline.execution.models import StageWorkerRequest

        intent = load_managed_local_intent(service.daemon, uri)
        missing = store.read_stage_worker_request(uri, "author", attempt=1)
        missing["metadata"].pop("loom.project_contract")
        missing["metadata"].pop("loom.project_contract_capture")
        with pytest.raises(ValueError, match="admitted report"):
            validate_admitted_worker(
                store,
                StageWorkerRequest.from_dict(missing),
                intent.pipeline.get_stage("author"),
            )
        prepared = store.read_prepared_run(uri)
        wrong_reference = deepcopy(prepared)
        wrong_reference["metadata"]["loom.project_contracts"]["data"]["namespace"] = (
            "other-project"
        )
        store.write_prepared_run(uri, wrong_reference)
        with pytest.raises(ValueError, match="namespace"):
            load_contract_report(store, uri)
        with pytest.raises(QueueServiceError, match="missing or changed"):
            load_managed_local_intent(service.daemon, uri)
        store.write_prepared_run(uri, prepared)
        assert "native_text_project" not in sys.modules
        child = daemon.admission(first["preparation_admission_id"]).admission
        binding = PreparationChildInput.from_dict(
            load_managed_local_intent(service.daemon, child.run_uri)
            .pipeline.get_stage("prepare")
            .stage_config
        )
        assert binding.to_dict()["schema_version"] == 7
        for fault in ("missing", "extra", "composition", "binding", "version"):
            changed = deepcopy(report)
            if fault == "missing":
                changed["project_result"]["stage_contracts"].pop("reader")
            elif fault == "extra":
                changed["project_result"]["stage_contracts"]["extra"] = {
                    "semantic_key": None,
                    "payload": None,
                }
            elif fault == "composition":
                changed["composition"]["resolved"]["pipeline"]["stages"][0]["config"][
                    "delay"
                ] = 999
            elif fault == "binding":
                changed["project_contracts"]["author"]["binding_digest"] = "f" * 64
            else:
                changed["project_result"]["stage_contracts"]["author"]["semantic_key"][
                    "version"
                ] = 99
            with pytest.raises((QueueConflictError, QueueServiceError)):
                decode_preparation_report(changed, expected=binding)
    finally:
        daemon.stop()


def test_v3_failed_run_retry_uses_original_run_and_new_attempt(tmp_path):
    service = _text_service(tmp_path, fail_once=True)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "first")
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=40).state.value
            == "FAILED"
        )
        retried = _start(daemon, "retry", retry=True)
        assert retried["prepared_run"] == first["prepared_run"]
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=40).state.value
            == "SUCCEEDED"
        )
        store = cast(Any, LocalRunStore(service.daemon.run_store_root))
        assert (
            store.read_stage_worker_request(
                first["prepared_run"]["run_uri"], "author", attempt=2
            )["attempt"]
            == 2
        )
    finally:
        daemon.stop()


def test_v3_observes_already_owned_running_target(tmp_path):
    import time

    service = _text_service(tmp_path, delay=15)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "first")
        uri = first["prepared_run"]["run_uri"]
        store = cast(Any, LocalRunStore(service.daemon.run_store_root))
        marker = store.local_run_dir(uri) / "actions" / "author" / "started"
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists()
        observed = _start(daemon, "observer")
        assert (
            observed["admission"]["admission_id"] == first["admission"]["admission_id"]
        )
        reference = ArtifactRef.from_dict(dict(observed["verification_report_ref"]))
        report = cast(
            Any, LocalArtifactStore(store.local_artifact_root(uri)).load(reference)
        )
        assert report["candidate"]["authority"]["status"] == "RUNNING"
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=35).state.value
            == "SUCCEEDED"
        )
    finally:
        daemon.stop()

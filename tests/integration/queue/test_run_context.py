"""Context crosses the real preparation journal, authority and native adapters."""

from dataclasses import replace
import json
from threading import Event
from typing import Any, cast

import pytest

from loom.coordinator import CoordinatorClient, CoordinatorClientError, RunRequest
from loom.diagnostics.run_inspection import RunInspectionProjection
from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.runs import SubmissionContext
from tests.integration.queue.test_preparation_operations import _service, _request

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("late_failure", [False, True])
def test_native_context_replay_cli_and_inert_inspection(tmp_path, capsys, late_failure):
    from loom.cli.main import main

    service = _service(tmp_path)
    config = tmp_path / "projects" / "pipeline.yaml"
    authored = json.loads(config.read_text())
    authored["runtime"]["tags"] = {"model": "authored", "baseline": "kept"}
    if late_failure:
        first = authored["pipeline"]["stages"][0]
        authored["pipeline"]["stages"].append(
            {
                **first,
                "name": "later",
                "depends_on": ["produce"],
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.FailingStage"
                },
                "config": {},
            }
        )
    config.write_text(json.dumps(authored))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    inspection = RunInspectionProjection(
        run_store=LocalRunStore(service.daemon.run_store_root), daemon=daemon
    )
    server = LocalDaemonSocketServer(
        daemon,
        service.daemon.endpoint,
        inspect_run=lambda uri: inspection.inspect(uri).to_dict(),
    )
    server.start()
    try:
        request: Any = RunRequest(
            replace(
                _request(),
                context=SubmissionContext(
                    "reason",
                    {"model": "caller", "study": "example"},
                    {
                        "revision": 3,
                        "status": "caller-only",
                        "_target_": "never.import.this",
                    },
                ),
            ),
            "context-run",
        )
        with CoordinatorClient.from_unix_socket(service.daemon.endpoint) as client:
            accepted: Any = client.start_run(request)
            original = accepted.result["submission"]
            assert original["accepted_at"]
            assert original["principal_id"] != "caller-only"
            assert cast(Any, client.start_run(request).result)["submission"] == original
            with pytest.raises(CoordinatorClientError) as error:
                client.start_run(
                    replace(
                        request,
                        preparation=replace(
                            request.preparation, context=SubmissionContext("changed")
                        ),
                    )
                )
            assert error.value.code == "conflict"
            operation: Any = daemon.wait_operation(
                request.preparation.operation_id, timeout=60
            ).operation
            assert operation.state == "applied", operation
            uri = operation.result["prepared_run"]["run_uri"]
            daemon._wait("context-run", timeout_seconds=60)
            context: Any = client.get_run_context(uri)
            assert context.annotations.description == "reason"
            assert context.annotations.tags["model"] == "caller"
            assert context.annotations.tags["baseline"] == "kept"
            assert context.annotations.metadata["revision"] == 3
            assert (
                context.initializer_submission["context"]
                == request.preparation.context.to_dict()
            )
            assert context.submission_count == 1
            assert context.inspection is not None
            if late_failure:
                assert {
                    stage["stage_name"]: stage["state"]
                    for stage in context.inspection["stages"]
                } == {"produce": "SUCCEEDED", "later": "FAILED"}
                assert any(
                    location["kind"] == "artifact"
                    for location in context.inspection["locations"]
                )
            assert context.unavailable == ()
            assert (
                main(
                    [
                        "runs",
                        "context",
                        uri,
                        "--endpoint",
                        str(service.daemon.endpoint),
                        "--format",
                        "json",
                    ]
                )
                == 0
            )
            output = json.loads(capsys.readouterr().out)
            assert output["result"]["annotations"]["description"] == "reason"
    finally:
        server.stop()
        daemon.stop()


def test_restart_after_authority_initialization_before_binding(tmp_path, monkeypatch):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    persisted = Event()
    resume = Event()
    initialize = SQLitePerRunAuthorityStore.initialize_run_annotations

    def interrupted(self, *args, **kwargs):
        result = initialize(self, *args, **kwargs)
        persisted.set()
        if not resume.is_set():
            raise OSError("lost annotation acknowledgement")
        return result

    monkeypatch.setattr(
        SQLitePerRunAuthorityStore, "initialize_run_annotations", interrupted
    )
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    request = RunRequest(
        replace(_request(), context=SubmissionContext("retained")), "context-run"
    )
    try:
        daemon.start_run(request, principal_id="caller")
        assert persisted.wait(60)
        # The authority effect may exist; target admission must still await binding.
        operation: Any = daemon.operation(request.preparation.operation_id)
        assert operation.result["prepared_run"] is None
    finally:
        daemon.stop()
    resume.set()
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        operation = daemon.wait_operation(
            request.preparation.operation_id, timeout=60
        ).operation
        assert operation.state == "applied", operation
        uri = operation.result["prepared_run"]["run_uri"]
        factory = service.daemon.coordinator_authority_factory
        assert factory is not None
        annotation: Any = factory(uri).read_run_annotations(uri)
        assert annotation.description == "retained"
        assert annotation.initializer_operation_id == request.preparation.operation_id
        assert annotation.revision == 1
    finally:
        daemon.stop()


def test_failed_preparation_keeps_original_intent_without_run(tmp_path):
    service = _service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        request = replace(
            _request(),
            config_path="missing.yaml",
            context=SubmissionContext("failed reason", {"customer": "example"}),
        )
        daemon.prepare_run(request, principal_id="authenticated-caller")
        operation: Any = daemon.wait_operation(
            request.operation_id, timeout=60
        ).operation
        assert operation.state == "failed", operation
        assert operation.result["prepared_run"] is None
        assert (
            operation.result["submission"]["context"]["description"] == "failed reason"
        )
        assert operation.result["submission"]["principal_id"] == "authenticated-caller"
    finally:
        daemon.stop()


def test_reconciled_submissions_retain_reasons_without_relabeling(tmp_path):
    from tests.integration.queue.test_reconciled_runs import (
        _reconciled_service,
        _reconciled_request,
    )
    from loom.queue._run_context import get_run_context

    service = _reconciled_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        uris = []
        for operation_id, reason in (
            ("first", "initial reason"),
            ("second", "second reason"),
        ):
            request = _reconciled_request(operation_id)
            request = replace(
                request,
                preparation=replace(
                    request.preparation,
                    context=SubmissionContext(reason, {"purpose": reason}),
                ),
            )
            daemon.start_run(request, principal_id="caller")
            operation: Any = daemon.wait_operation(operation_id, timeout=90).operation
            assert operation.state == "applied", operation
            uris.append(operation.result["prepared_run"]["run_uri"])
            assert operation.result["submission"]["context"]["description"] == reason
            daemon._wait(operation.result["queue_item_id"], timeout_seconds=60)
        assert uris[0] == uris[1]
        context: Any = get_run_context(daemon, uris[0], None)
        assert context.annotations.description == "initial reason"
        assert context.annotations.tags["purpose"] == "initial reason"
        assert context.submission_count == 2
        assert {item["operation_id"] for item in context.submissions} == {
            "first",
            "second",
        }
    finally:
        daemon.stop()

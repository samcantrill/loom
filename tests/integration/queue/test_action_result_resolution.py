"""Installed native action identity, generation, selection and demand lifecycle."""

from dataclasses import replace
import json

import pytest

from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.queue.errors import QueueConflictError
from tests.integration.queue.test_installed_node_contracts import _start, _text_service
from tests.integration.queue.test_preparation_operations import _result
from tests.integration.queue.test_reconciled_runs import _reconciled_request


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


def test_native_fresh_generation_replay_and_default_target_are_distinct(tmp_path):
    service = _text_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "default")
        assert daemon._wait(first["queue_item_id"], timeout_seconds=40).state.value == "SUCCEEDED"
        request = replace(_reconciled_request("fresh"), fresh_stages=("author",))
        daemon.start_run(request, principal_id="caller")
        with daemon._connection() as conn:
            selected = json.loads(conn.execute(
                "SELECT selected_json FROM preparation_operations WHERE operation_id = 'fresh'"
            ).fetchone()[0])
        assert set(selected["generations"]) == {"author"}
        daemon.start_run(request, principal_id="caller")
        with daemon._connection() as conn:
            replay = json.loads(conn.execute(
                "SELECT selected_json FROM preparation_operations WHERE operation_id = 'fresh'"
            ).fetchone()[0])
        assert replay["generations"] == selected["generations"]
        with pytest.raises(QueueConflictError, match="intent conflicts"):
            daemon.start_run(replace(request, fresh_stages=("reader",)), principal_id="caller")
        operation = daemon.wait_operation("fresh", timeout=50).operation
        assert operation.state == "applied", operation.to_dict()
        fresh = _result(operation)
        assert fresh["prepared_run"]["run_uri"] != first["prepared_run"]["run_uri"]
        assert daemon._wait(fresh["queue_item_id"], timeout_seconds=40).state.value == "SUCCEEDED"
        again = _start(daemon, "default-again")
        assert again["prepared_run"] == first["prepared_run"]
    finally:
        daemon.stop()


def test_unknown_fresh_node_fails_before_target_admission(tmp_path):
    service = _text_service(tmp_path)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        request = replace(_reconciled_request("unknown"), fresh_stages=("missing",))
        daemon.start_run(request, principal_id="caller")
        operation = daemon.wait_operation("unknown", timeout=50).operation
        assert operation.state == "failed", operation.to_dict()
        assert _result(operation)["prepared_run"] is None
    finally:
        daemon.stop()

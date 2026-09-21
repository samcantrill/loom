"""Bad retained results and failed producers are explicit failures, never misses."""

import json
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import pytest

from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from tests.integration.queue.test_action_result_resolution import _rename_graph
from tests.integration.queue.test_installed_node_contracts import _start, _text_service

pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("failure", ["bytes", "project", "producer"])
def test_failed_or_rejected_original_does_not_silently_reexecute(tmp_path, failure):
    service = _text_service(
        tmp_path, qualify_actions=True, fail_once=failure == "producer"
    )
    if failure == "project":
        path = tmp_path / "projects" / "pipeline.yaml"
        config = json.loads(path.read_text())
        config["pipeline"]["stages"][0]["config"]["value"] = "unexpected\n"
        path.write_text(json.dumps(config))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "original")
        assert daemon._wait(first["queue_item_id"], timeout_seconds=50).state.value == (
            "FAILED" if failure == "producer" else "SUCCEEDED"
        )
        original_uri = first["prepared_run"]["run_uri"]
        authority = service.daemon.coordinator_authority_factory
        assert authority is not None
        original = authority(original_uri).open_run(original_uri)
        producer = next(
            stage for stage in original.stages if stage.stage_name == "author"
        )
        if failure == "bytes":
            Path(urlparse(producer.artifact_facts[0].artifact.uri).path).write_text(
                '"tampered"'
            )
        _rename_graph(tmp_path)
        second = _start(daemon, "consumer")
        outcome = daemon._wait(second["queue_item_id"], timeout_seconds=60)
        assert outcome.state.value == "FAILED", (outcome, daemon._service_error)
        consumer = authority(second["prepared_run"]["run_uri"]).open_run(
            second["prepared_run"]["run_uri"]
        )
        rejected = next(
            stage for stage in consumer.stages if stage.stage_name == "write-renamed"
        )
        assert rejected.attempts == ()
        assert rejected.result_binding is None
        assert rejected.reason is not None
        detail = cast(dict[str, Any], rejected.reason.detail)
        assert detail["origin_run_uri"] == original_uri
        assert detail["origin_node_id"] == "author"
        assert (
            rejected.reason.code
            == {
                "bytes": "action.candidate_unavailable",
                "project": "action.project_rejected",
                "producer": "action.producer_failed",
            }[failure]
        )
        if failure == "project":
            assert detail["namespace"] == "text-project"
            assert dict(detail["reason"]) == {
                "code": "line_count_mismatch",
                "output_port": "text",
            }
        if failure != "producer":
            assert detail["original_result"]["commit"]["run_uri"] == original_uri
        assert authority(original_uri).open_run(original_uri) == original
    finally:
        daemon.stop()


def test_successful_action_from_failed_graph_feeds_new_downstream_work(tmp_path):
    service = _text_service(tmp_path, qualify_actions=True)
    path = tmp_path / "projects" / "pipeline.yaml"
    config = json.loads(path.read_text())
    config["pipeline"]["stages"][1]["config"]["fail"] = True
    path.write_text(json.dumps(config))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "failed-graph")
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=50).state.value
            == "FAILED"
        )
        authority = service.daemon.coordinator_authority_factory
        assert authority is not None
        original_uri = first["prepared_run"]["run_uri"]
        original = authority(original_uri).open_run(original_uri)
        config["pipeline"]["stages"][1]["config"]["fail"] = False
        path.write_text(json.dumps(config))
        _rename_graph(tmp_path)
        second = _start(daemon, "new-graph")
        assert (
            daemon._wait(second["queue_item_id"], timeout_seconds=60).state.value
            == "SUCCEEDED"
        )
        stages = {
            stage.stage_name: stage
            for stage in authority(second["prepared_run"]["run_uri"])
            .open_run(second["prepared_run"]["run_uri"])
            .stages
        }
        assert stages["write-renamed"].attempts == ()
        assert stages["write-renamed"].latest_commit == next(
            stage.latest_commit
            for stage in original.stages
            if stage.stage_name == "author"
        )
        assert len(stages["count-renamed"].attempts) == 1
        assert authority(original_uri).open_run(original_uri) == original
    finally:
        daemon.stop()


def test_failed_waiter_can_explicitly_retry_after_original_producer_retry(tmp_path):
    service = _text_service(tmp_path, qualify_actions=True, fail_once=True)
    path = tmp_path / "projects" / "pipeline.yaml"
    original_config = path.read_text()
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "owner")
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=50).state.value
            == "FAILED"
        )
        _rename_graph(tmp_path)
        consumer_config = path.read_text()
        second = _start(daemon, "waiter")
        assert (
            daemon._wait(second["queue_item_id"], timeout_seconds=50).state.value
            == "FAILED"
        )
        path.write_text(original_config)
        assert (
            _start(daemon, "retry-owner", retry=True)["prepared_run"]
            == first["prepared_run"]
        )
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=50).state.value
            == "SUCCEEDED"
        )
        path.write_text(consumer_config)
        assert (
            _start(daemon, "retry-waiter", retry=True)["prepared_run"]
            == second["prepared_run"]
        )
        assert (
            daemon._wait(second["queue_item_id"], timeout_seconds=60).state.value
            == "SUCCEEDED"
        )
        authority = service.daemon.coordinator_authority_factory
        assert authority is not None
        original_uri, consumer_uri = (
            item["prepared_run"]["run_uri"] for item in (first, second)
        )
        original = authority(original_uri).open_run(original_uri)
        producer = next(
            stage for stage in original.stages if stage.stage_name == "author"
        )
        reused = next(
            stage
            for stage in authority(consumer_uri).open_run(consumer_uri).stages
            if stage.stage_name == "write-renamed"
        )
        assert len(producer.attempts) == 2
        assert reused.attempts == ()
        assert reused.latest_commit == producer.latest_commit
    finally:
        daemon.stop()

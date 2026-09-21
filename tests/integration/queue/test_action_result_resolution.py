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
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "default")
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=40).state.value
            == "SUCCEEDED"
        )
        factory = service.daemon.coordinator_authority_factory
        assert factory is not None
        original_uri = first["prepared_run"]["run_uri"]
        original = factory(original_uri).open_run(original_uri)
        request = replace(_reconciled_request("fresh"), fresh_stages=("author",))
        daemon.start_run(request, principal_id="caller")
        with daemon._connection() as conn:
            selected = json.loads(
                conn.execute(
                    "SELECT selected_json FROM preparation_operations WHERE operation_id = 'fresh'"
                ).fetchone()[0]
            )
        assert set(selected["generations"]) == {"author"}
        daemon.start_run(request, principal_id="caller")
        with daemon._connection() as conn:
            replay = json.loads(
                conn.execute(
                    "SELECT selected_json FROM preparation_operations WHERE operation_id = 'fresh'"
                ).fetchone()[0]
            )
        assert replay["generations"] == selected["generations"]
        with pytest.raises(QueueConflictError, match="intent conflicts"):
            daemon.start_run(
                replace(request, fresh_stages=("reader",)), principal_id="caller"
            )
        operation = daemon.wait_operation("fresh", timeout=50).operation
        assert operation.state == "applied", operation.to_dict()
        fresh = _result(operation)
        assert fresh["prepared_run"]["run_uri"] != first["prepared_run"]["run_uri"]
        assert (
            daemon._wait(fresh["queue_item_id"], timeout_seconds=40).state.value
            == "SUCCEEDED"
        )
        fresh_snapshot = factory(fresh["prepared_run"]["run_uri"]).open_run(
            fresh["prepared_run"]["run_uri"]
        )
        for old, new in zip(original.stages, fresh_snapshot.stages, strict=True):
            assert len(new.attempts) == 1
            assert new.latest_commit is not None and old.latest_commit is not None
            assert (new.latest_commit.run_uri, new.latest_commit.commit_id) != (
                old.latest_commit.run_uri,
                old.latest_commit.commit_id,
            )
            assert (
                new.artifact_facts[0].artifact.checksum
                == old.artifact_facts[0].artifact.checksum
            )
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


def test_renamed_graph_reuses_original_producers_without_attempts(tmp_path):
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "original-graph")
        assert (
            daemon._wait(first["queue_item_id"], timeout_seconds=50).state.value
            == "SUCCEEDED"
        )
        original_uri = first["prepared_run"]["run_uri"]
        authority = service.daemon.coordinator_authority_factory
        assert authority is not None
        before = authority(original_uri).open_run(original_uri)
        path = tmp_path / "projects" / "pipeline.yaml"
        config = json.loads(path.read_text())
        config["pipeline"]["stages"][0]["name"] = "write-renamed"
        config["pipeline"]["stages"][1]["name"] = "count-renamed"
        config["pipeline"]["stages"][1]["inputs"] = {"text": "write-renamed.text"}
        # Unrelated authored work must not invalidate either original action.
        config["pipeline"]["stages"].append(
            {
                **config["pipeline"]["stages"][1],
                "name": "additional-count",
                "config": {"opt_out": True},
            }
        )
        path.write_text(json.dumps(config))
        second = _start(daemon, "renamed-graph")
        assert second["prepared_run"]["run_uri"] != original_uri
        outcome = daemon._wait(second["queue_item_id"], timeout_seconds=70)
        assert outcome.state.value == "SUCCEEDED", (outcome, daemon._service_error)
        uri = second["prepared_run"]["run_uri"]
        reused = authority(uri).open_run(uri)
        originals = {stage.stage_name: stage for stage in before.stages}
        for stage, origin in zip(
            sorted(
                (
                    stage
                    for stage in reused.stages
                    if stage.stage_name != "additional-count"
                ),
                key=lambda stage: stage.stage_name,
            ),
            ("reader", "author"),
            strict=True,
        ):
            assert stage.attempts == ()
            assert stage.result_binding is not None
            assert stage.latest_commit == originals[origin].latest_commit
            assert stage.artifact_facts == originals[origin].artifact_facts
        assert (
            len(
                next(
                    stage
                    for stage in reused.stages
                    if stage.stage_name == "additional-count"
                ).attempts
            )
            == 1
        )
        assert authority(original_uri).open_run(original_uri) == before
    finally:
        daemon.stop()


def _until(predicate, timeout=40):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("native action lifecycle did not reach expected state")


def _rename_graph(tmp_path):
    path = tmp_path / "projects" / "pipeline.yaml"
    config = json.loads(path.read_text())
    config["pipeline"]["stages"][0]["name"] = "write-renamed"
    config["pipeline"]["stages"][1]["name"] = "count-renamed"
    config["pipeline"]["stages"][1]["inputs"] = {"text": "write-renamed.text"}
    path.write_text(json.dumps(config))


@pytest.mark.parametrize("cancel_final", [False, True])
def test_shared_producer_survives_original_graph_cancel_and_reopen(
    tmp_path, cancel_final
):
    service = _text_service(tmp_path, qualify_actions=True, delay=30)
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    daemon.start()
    try:
        first = _start(daemon, "original")
        original_uri = first["prepared_run"]["run_uri"]
        factory = service.daemon.coordinator_authority_factory
        assert factory is not None

        def original_stage():
            return next(
                (
                    stage
                    for stage in factory(original_uri).open_run(original_uri).stages
                    if stage.stage_name == "author"
                ),
                None,
            )

        _until(
            lambda: (
                (stage := original_stage()) is not None
                and stage.status.value == "RUNNING"
            )
        )
        _rename_graph(tmp_path)
        second = _start(daemon, "waiting")
        consumer_uri = second["prepared_run"]["run_uri"]

        def shared_claim():
            with daemon._connection() as conn:
                return conn.execute(
                    "SELECT c.claim_id FROM action_claims c JOIN action_demands d ON d.claim_id = c.claim_id WHERE c.owner_run_uri = ? AND d.run_uri = ? AND d.state = 'live'",
                    (original_uri, consumer_uri),
                ).fetchone()

        claim_id = _until(shared_claim)[0]
        assert daemon._execution is not None
        assert daemon._execution._action_resolution is not None
        with daemon._cycle_lock:
            daemon.cancel_run_operation("original", principal_id="caller")
            with daemon._connection() as conn:
                assert (
                    conn.execute(
                        "SELECT state FROM action_demands WHERE run_uri = ? AND node = 'author'",
                        (original_uri,),
                    ).fetchone()[0]
                    == "detached"
                )
            assert daemon._execution._action_resolution.store.producer_needed(
                original_uri, "author"
            )
            if cancel_final:
                daemon.cancel_run_operation("waiting", principal_id="caller")
                assert not daemon._execution._action_resolution.store.producer_needed(
                    original_uri, "author"
                )
        # Resume through retained claims, native attempts and existing workers.
        daemon.stop()
        daemon = LocalDaemon(
            service.daemon, preparation=CoordinatorPreparation(service)
        )
        daemon.start()
        assert daemon._execution is not None
        assert daemon._execution._action_resolution is not None
        original_result = daemon._wait(first["queue_item_id"], timeout_seconds=80)
        consumer_result = daemon._wait(second["queue_item_id"], timeout_seconds=80)
        assert original_result.state.value == "CANCELLED", (
            original_result,
            daemon._service_error,
        )
        assert consumer_result.state.value == (
            "CANCELLED" if cancel_final else "SUCCEEDED"
        ), (consumer_result, daemon._service_error)
        producer = original_stage()
        assert producer is not None
        assert len(producer.attempts) == 1
        consumer = factory(consumer_uri).open_run(consumer_uri)
        reused = next(
            (stage for stage in consumer.stages if stage.stage_name == "write-renamed"),
            None,
        )
        if cancel_final:
            assert producer.status.value == "CANCELLED"
            assert reused is None or reused.attempts == ()
            assert not daemon._execution._action_resolution.store.producer_needed(
                original_uri, "author"
            )
            assert daemon._execution._action_resolution.store.claim(claim_id)[
                "state"
            ] in {"settling", "cancelled"}
        else:
            assert producer.status.value == "SUCCEEDED"
            assert reused is not None and reused.result_binding is not None
            assert reused.attempts == ()
            assert reused.latest_commit == producer.latest_commit
            assert reused.result_binding.commit.run_uri == original_uri
            assert next(
                stage
                for stage in consumer.stages
                if stage.stage_name == "count-renamed"
            ).attempts
        assert daemon._execution.coordinator.list_run_live_states(original_uri) == ()
    finally:
        daemon.stop()

"""Pending native verifiers avoid repeated proof without authorizing adoption."""

import json
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

import pytest

from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon
from loom.queue import _action_result_resolution as resolution
from tests.integration.queue.test_action_result_resolution import _rename_graph, _until
from tests.integration.queue.test_installed_node_contracts import _start, _text_service


pytestmark = [pytest.mark.integration, pytest.mark.optional_dependency]


@pytest.mark.parametrize("change", ["none", "restart", "refresh", "input", "result"])
def test_pending_verifier_waits_cheaply_then_revalidates(tmp_path, monkeypatch, change):
    service = _text_service(tmp_path, qualify_actions=True)
    LocalDaemon.initialize_deployment(service.daemon)
    release = Event()
    held = set()
    observations = []
    loads = []
    hashes = []
    clock = [0.0]
    monkeypatch.setattr(resolution, "monotonic", lambda: clock[0])
    load = resolution.load_contract_report
    verify = resolution.ActionResultResolution._verify_artifact

    def load_contract(*args, **kwargs):
        loads.append(args[1])
        return load(*args, **kwargs)

    monkeypatch.setattr(resolution, "load_contract_report", load_contract)

    def verify_artifact(owner, ref):
        hashes.append(ref.uri)
        return verify(owner, ref)

    monkeypatch.setattr(resolution.ActionResultResolution, "_verify_artifact", verify_artifact)

    def start_daemon():
        daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
        preparations = daemon._preparations
        advance = preparations._advance
        observe = preparations.action_verification_pending

        def advance_unless_held(row):
            selected = json.loads(row["selected_json"])
            if selected.get("action_verification", {}).get("node_id") == "count-renamed":
                held.add(row["operation_id"])
                if not release.is_set():
                    return
            return advance(row)

        def observe_pending(child):
            result = observe(child)
            if child.operation_id in held and result:
                observations.append(child.operation_id)
            return result

        monkeypatch.setattr(preparations, "_advance", advance_unless_held)
        monkeypatch.setattr(preparations, "action_verification_pending", observe_pending)
        daemon.start()
        return daemon

    daemon = start_daemon()
    try:
        first = _start(daemon, "original")
        assert daemon._wait(first["queue_item_id"], timeout_seconds=50).state.value == "SUCCEEDED"
        factory = service.daemon.coordinator_authority_factory
        original_uri = first["prepared_run"]["run_uri"]
        original = factory(original_uri).open_run(original_uri)
        _rename_graph(tmp_path)
        second = _start(daemon, "consumer")
        uri = second["prepared_run"]["run_uri"]
        _until(lambda: len(observations) >= 5)
        loaded = loads.count(uri)
        hashed = len(hashes)
        _until(lambda: len(observations) >= 50)
        assert loads.count(uri) == loaded
        assert len(hashes) == hashed
        waiting = next((s for s in factory(uri).open_run(uri).stages if s.stage_name == "count-renamed"), None)
        # A dependency-ready reuse candidate need not yet have a lifecycle row.
        assert waiting is None or (waiting.result_binding is None and waiting.attempts == ())

        if change == "restart":
            previous_ids = set(held)
            daemon.stop()
            observations.clear()
            daemon = start_daemon()
            _until(lambda: len(observations) >= 5)
            assert loads.count(uri) > loaded
            assert held == previous_ids
        elif change == "refresh":
            clock[0] = 31.0
            _until(lambda: loads.count(uri) > loaded)
            _until(lambda: len(observations) >= 55)
            assert len(held) == 1
        elif change in {"input", "result"}:
            producer_name = "author" if change == "input" else "reader"
            producer = next(s for s in original.stages if s.stage_name == producer_name)
            Path(urlparse(producer.artifact_facts[0].artifact.uri).path).write_text('"changed"')
            if change == "result":
                # Damaged verifier inputs can prevent its child completing.
                # Expiry must recheck and reject even while that child is held.
                clock[0] = 31.0

        if change != "result":
            release.set()
        outcome = daemon._wait(second["queue_item_id"], timeout_seconds=60)
        expected = "FAILED" if change in {"input", "result"} else "SUCCEEDED"
        assert outcome.state.value == expected, (outcome, daemon._service_error)
        consumer = next(s for s in factory(uri).open_run(uri).stages if s.stage_name == "count-renamed")
        assert consumer.attempts == ()
        if expected == "SUCCEEDED":
            assert consumer.result_binding is not None
            assert consumer.latest_commit == next(s.latest_commit for s in original.stages if s.stage_name == "reader")
        else:
            assert consumer.result_binding is None
            assert consumer.reason.code == (
                "action.input_unavailable" if change == "input" else "action.candidate_unavailable"
            )
        assert loads.count(uri) > loaded
        assert len(hashes) > hashed
        with daemon._connection() as conn:
            children = conn.execute(
                "SELECT operation_id FROM preparation_operations WHERE operation_id LIKE 'action-verify-%'"
            ).fetchall()
        # Both reused nodes have one verifier each, including across restart.
        assert len(children) == 2
    finally:
        release.set()
        daemon.stop()

"""Opt-in coordinator dispatch acceptance with delayed selection and durable DAG replay."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
from threading import Event
import time

import pytest

from loom.pipeline.stores import LocalRunStore
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import LocalDaemon, LocalDaemonAdmissionRequest, LocalDaemonPrincipal, LocalDaemonRole
from loom.queue._remote_stage_execution import (
    REGULAR_FILE_RELAY_CAPABILITY, REMOTE_EXECUTION_CAPABILITY, ResidentExecutionProfile, ResidentProfileDescriptor,
)
from loom.queue._run_observations import DispatchObservations
from loom.queue.agent_session_transport import _resident_provider_descriptors
from loom.queue.agent_sessions import AgentOffer, AgentPrincipalPolicy, AgentRegistration
from tests.integration.queue.test_local_daemon_production import (
    _daemon_config, _launch_profile, _persist_sleep_run, _supervisor_launch_count,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(
        os.environ.get("LOOM_RUN_DISPATCH_ACCEPTANCE") != "1",
        reason="set LOOM_RUN_DISPATCH_ACCEPTANCE=1 to run the local dispatch suite",
    ),
]


def test_slow_selection_delivers_every_sibling_once_to_multiple_agents(tmp_path, monkeypatch):
    # Each host offers exactly one slot. No worker can release or advertise it
    # during this test, so every accepted delivery witnesses concurrent placement.
    stages = ("score_a", "score_b", "score_c")
    agents = [f"host-{n}" for n in range(2 * len(stages))]
    capabilities = ("python", REMOTE_EXECUTION_CAPABILITY, REGULAR_FILE_RELAY_CAPABILITY)
    descriptor = ResidentProfileDescriptor.from_dict(_launch_profile().descriptor)
    profile = ResidentExecutionProfile(descriptor, tmp_path, Path(sys.executable))
    base = _daemon_config(tmp_path)
    policy = replace(base.agent_policy, agents=tuple(
        AgentPrincipalPolicy(name, name, name, ("default",), capabilities) for name in agents
    ))
    config = replace(base, agent_root=None, resident_worker_launch_profile=None, cpu_capacity=0,
                     agent_resource_providers=(), agent_policy=policy, remote_profiles=(descriptor,),
                     poll_interval_seconds=0.1)
    runs = [_persist_sleep_run(config.run_store_root, run_name=name, stage_name=stages[0],
                               independent_stage_names=stages, max_parallel_stages=len(stages))
            for name in ("run-a", "run-b")]
    expected = Counter((uri, stage, 1) for uri in runs for stage in stages)
    delayed = Event()
    begin_cycle = DispatchObservations.begin_cycle

    def slow_consumer(owner, *args, **kwargs):
        if owner.requested_runs():
            # The store can finish on its normal worker while the selector is
            # busy. Advance real time beyond the old one-second read expiry.
            time.sleep(1.25)
            delayed.set()
        return begin_cycle(owner, *args, **kwargs)

    monkeypatch.setattr(DispatchObservations, "begin_cycle", slow_consumer)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    try:
        sessions = {}
        for name in agents:
            view = daemon.agent_view(LocalDaemonPrincipal(name, LocalDaemonRole.AGENT, name))
            hello = view.handshake()
            session = view.register(AgentRegistration(
                name, str(hello["coordinator_id"]), str(hello["coordinator_epoch"]), name,
                "config-1", "inventory-1", "availability-1", ("default",), capabilities,
                retirement_verifier="01" * 32,
            ))
            offer = AgentOffer(session.session_id, session.coordinator_epoch, session.config_revision,
                               session.inventory_revision, session.availability_revision, 1, 0, 120,
                               _resident_provider_descriptors(profile, name), resident_profiles=(descriptor,),
                               max_concurrent_assignments=1)
            view.publish_offer(offer, idempotency_key="initial")
            sessions[session.session_id] = (view, offer)
        client = daemon.client_view(LocalDaemonPrincipal("submit", LocalDaemonRole.CLIENT))
        for i, uri in enumerate(runs):
            client.submit(LocalDaemonAdmissionRequest(f"submit-{i}", uri))
        deadline = time.monotonic() + 45
        with sqlite3.connect(config.control_database) as conn:
            while True:
                rows = conn.execute(
                    "SELECT a.run_uri,a.stage_name,a.attempt,a.session_id,a.assignment_id,d.request_json "
                    "FROM remote_assignments a JOIN agent_deliveries d USING(assignment_id)"
                ).fetchall()
                if len(rows) >= len(expected) or time.monotonic() >= deadline:
                    break
                time.sleep(0.1)
        assert delayed.is_set(), "the selector never revisited a demanded observation"
        assert Counter(row[:3] for row in rows) == expected, (rows and [r[:3] for r in rows], daemon._service_error)
        assert len({row[3] for row in rows}) == len(agents)
        store = LocalRunStore(config.run_store_root)
        for uri, stage, _, session_id, assignment_id, encoded in rows:
            assert store.read_stage_worker_request(uri, stage, attempt=None) is not None
            view, offer = sessions[session_id]
            delivery = view.wait_for_work(session_id, offer.availability_revision, sequence=1, wait_timeout_ms=100)
            assert delivery["result"] == "assignment"
            request = delivery["request"]
            assert isinstance(request, Mapping) and request["assignment_id"] == assignment_id
            view.accept_assignment(session_id, assignment_id, request_digest=hashlib.sha256(encoded.encode()).hexdigest())
    finally:
        daemon.stop()


def test_restart_after_prediction_replays_fanout_and_join_once(tmp_path, monkeypatch):
    config = replace(_daemon_config(tmp_path, cpu_capacity=3), poll_interval_seconds=0.1)
    stages = ("predict", "score_a", "score_b", "summary")
    dependencies = {"score_a": ("predict",), "score_b": ("predict",), "summary": ("score_a", "score_b")}
    uri = _persist_sleep_run(config.run_store_root, run_name="fanout", stage_name="predict",
                             independent_stage_names=stages, max_parallel_stages=3,
                             dependencies=dependencies, seconds=0.01)
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    daemon.start()
    principal = LocalDaemonPrincipal("submit", LocalDaemonRole.CLIENT)
    offered = Event()
    try:
        execution = daemon._execution
        assert execution is not None
        execute = execution._execute

        def stop_at_fanout(**kwargs):
            if kwargs["record"].stage_name in dependencies:
                offered.set()
                return False
            return execute(**kwargs)

        monkeypatch.setattr(execution, "_execute", stop_at_fanout)
        daemon.client_view(principal).submit(LocalDaemonAdmissionRequest("fanout", uri))
        assert offered.wait(30), daemon._service_error
        assert _supervisor_launch_count(config) == 1
    finally:
        daemon.stop()
    daemon.start()
    try:
        assert daemon.client_view(principal).wait("fanout", timeout_seconds=60).state.value == "SUCCEEDED"
        snapshot = SQLitePerRunAuthorityStore(uri).open_run(uri)
        commits = {stage.stage_name: stage.latest_commit.commit_id for stage in snapshot.stages
                   if stage.latest_commit is not None}
        assert set(commits) == set(stages)
        for stage in snapshot.stages:
            assert len(stage.attempts) == 1 and stage.attempts[0].status.value == "SUCCEEDED"
            inputs = stage.attempts[0].input_bindings or ()
            assert {binding.input_name: binding.producer.commit_id for binding in inputs
                    if binding.producer is not None} == {
                parent: commits[parent] for parent in dependencies.get(stage.stage_name, ())
            }
        assert _supervisor_launch_count(config) == len(stages)
    finally:
        daemon.stop()

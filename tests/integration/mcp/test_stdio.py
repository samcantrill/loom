"""Installed SDK stdio over real native coordinator fixtures, with no live fleet."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sys
from threading import Event
from time import monotonic
from typing import Any, Literal, cast

import pytest

from loom.coordinator import CoordinatorClient
from loom.preparation import CoordinatorPreparation
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue.deployment import load_coordinator_service_config
from tests.integration.queue.test_preparation_operations import _request, _service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.optional_dependency,
    pytest.mark.mcp_extra,
]

TOOLS = {
    "loom_run",
    "loom_cancel_run_operation",
    "loom_status",
    "loom_prepare_run",
    "loom_get_operation",
    "loom_wait_for_operation",
    "loom_cancel_preparation",
    "loom_list_jobs",
    "loom_get_job",
    "loom_inspect_run",
    "loom_run_context",
    "loom_patch_run_annotations",
    "loom_append_run_note",
    "loom_list_run_notes",
    "loom_search_runs",
    "loom_select_outputs",
    "loom_trace_lineage",
    "loom_search_submissions",
    "loom_search_jobs",
    "loom_query_fields",
    "loom_tag_keys",
    "loom_tag_values",
    "loom_list_agents",
    "loom_get_agent",
    "loom_submit_run",
    "loom_wait_for_change",
    "loom_cancel_job",
}


def _client(arguments: list[str], *, mode: Literal["auto", "legacy"] = "auto"):
    from mcp import Client, StdioServerParameters

    executable = Path(sys.executable).parent / "loom-mcp"
    assert executable.is_file(), "the isolated MCP lane must install the console script"
    return Client(
        StdioServerParameters(command=str(executable), args=arguments),
        read_timeout_seconds=40,
        mode=mode,
    )


async def _call(client: Any, name: str, **arguments: Any) -> dict[str, Any]:
    result = await client.call_tool(name, arguments)
    assert not result.is_error, (name, result)
    assert isinstance(result.structured_content, dict), result
    return result.structured_content


@contextmanager
def _coordinator(
    tmp_path: Path,
    *,
    mode: str = "shared",
    https: bool = False,
    large: bool = False,
    inspection: Any = None,
    authority_factory: Any = None,
):
    credentials: dict[str, Path] = {}
    server: Any
    service = _service(tmp_path, mode=mode)
    if large:
        config = tmp_path / "projects" / "pipeline.yaml"
        authored = json.loads(config.read_text())
        authored["runtime"]["notes"] = ["large native check context " * 5000]
        config.write_text(json.dumps(authored))
    if https:
        path = tmp_path / "coordinator.json"
        authored = json.loads(path.read_text())
        authored["agent_policy"]["principals"] = [
            {
                "credential_id": "client-credential",
                "principal_id": "client",
                "role": "client",
                "actions": [],
                "agent_ids": [],
                "pools": [],
            },
            {"credential_id": "query-credential", "principal_id": "reader", "role": "query",
             "actions": [], "agent_ids": [], "pools": []},
        ]
        path.write_text(json.dumps(authored))
        service = load_coordinator_service_config(path)
    if authority_factory is not None:
        service = replace(service, daemon=replace(service.daemon, coordinator_authority_factory=authority_factory))
    LocalDaemon.initialize_deployment(service.daemon)
    daemon = LocalDaemon(service.daemon, preparation=CoordinatorPreparation(service))
    if https:
        from loom.queue.agent_session_transport import (
            AgentTlsServerConfig,
            LocalDaemonAgentHttpServer,
        )
        from tests.support.mutual_tls import (
            certificate_fingerprint,
            mutual_tls_credentials,
        )

        credentials = mutual_tls_credentials(tmp_path / "tls")
        server = LocalDaemonAgentHttpServer(
            daemon,
            AgentTlsServerConfig(
                "localhost",
                0,
                credentials["server"].with_suffix(".crt"),
                credentials["server"].with_suffix(".key"),
                credentials["ca"].with_suffix(".crt"),
                {
                    certificate_fingerprint(
                        credentials["other"].with_suffix(".crt")
                    ): "client-credential",
                    certificate_fingerprint(credentials["query"].with_suffix(".crt")): "query-credential",
                },
            ),
            inspect_run=inspection,
        )
    else:
        server = LocalDaemonSocketServer(
            daemon, service.daemon.endpoint, inspect_run=inspection
        )
    daemon.start()
    server.start()
    try:
        if https:
            path = tmp_path / "client.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "loom.coordinator-client",
                        "expected_coordinator_id": daemon._coordinator_id,
                        "transport": {
                            "kind": "https",
                            "url": f"https://localhost:{server.port}",
                            "server_ca_path": str(
                                credentials["ca"].with_suffix(".crt")
                            ),
                            "certificate_path": str(
                                credentials["other"].with_suffix(".crt")
                            ),
                            "private_key_path": str(
                                credentials["other"].with_suffix(".key")
                            ),
                        },
                    }
                )
            )
            path.chmod(0o600)
            connection = path
        else:
            connection = None
        selection = tmp_path / "mcp-deployment.json"
        value = {
            "schema_version": 1, "kind": "loom.deployment",
            "coordinator": {"service_config": "coordinator.json", "lifetime": "persistent"},
            "binding_path": "mcp-binding.json",
            "preparation": {"source": _request(mode).source.to_dict(), "profile": _request(mode).preparation_profile},
        }
        if connection is not None:
            value["connection"] = str(connection)
        selection.write_text(json.dumps(value))
        selection.chmod(0o600)
        from loom.deployment import _bind, load_deployment
        _bind(load_deployment(selection), "mcp-fixture", monotonic() + 20)
        args = ["--deployment", str(selection)]

        yield service, daemon, args
    finally:
        server.stop()
        daemon.stop()


@pytest.mark.parametrize("protocol_mode", ["auto", "legacy"])
def test_installed_offline_discovery_and_classified_failure(
    tmp_path: Path, protocol_mode: Literal["auto", "legacy"]
):
    from tests.integration.queue.test_service_lifetime import _selection
    selection = _selection(tmp_path)

    async def scenario():
        async with _client(
            ["--deployment", str(selection)], mode=protocol_mode
        ) as client:
            registered = (await client.list_tools()).tools
            assert {tool.name for tool in registered} == TOOLS
            for tool in registered:
                assert "expected_coordinator_id" in tool.input_schema["properties"]
                assert tool.annotations is not None
                assert tool.annotations.read_only_hint == (
                    tool.name
                    not in {
                        "loom_run",
                        "loom_cancel_run_operation",
                        "loom_prepare_run",
                        "loom_submit_run",
                        "loom_cancel_job",
                        "loom_cancel_preparation",
                        "loom_patch_run_annotations",
                        "loom_append_run_note",
                    }
                )
            offline = await client.call_tool("loom_status", {})
            assert offline.is_error
            assert offline.structured_content["code"] == "unavailable"
            assert offline.structured_content["boundary"] == "connection"
            assert len(offline.content) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("mode,https", [("shared", False), ("staged", True)])
def test_prepare_eof_reconnect_submit_observe_and_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, https: bool
):
    from loom.pipeline.execution.models import StageWorkerResult
    from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
    from loom.diagnostics import RunInspectionFailure, RunInspectionFailureCode

    inspection = RunInspectionFailure(RunInspectionFailureCode.UNAVAILABLE).to_dict()
    with _coordinator(
        tmp_path, mode=mode, https=https, inspection=lambda _: inspection
    ) as (service, daemon, args):

        async def scenario():
            async with _client(args) as client:
                status = await _call(client, "loom_status")
                assert status["status"]["coordinator_id"]
                accepted = await _call(
                    client, "loom_prepare_run", **_request(mode).to_dict(),
                    context={"description": "MCP native reason", "tags": {"application": "invoices"},
                             "metadata": {"revision": 3, "status": "caller-only"}},
                )
                assert accepted["operation_id"] == "prepare-1"
            # SDK EOF leaves coordinator-owned preparation intact.
            async with _client(args) as client:
                completed = (
                    await _call(
                        client, "loom_wait_for_operation", operation_id="prepare-1"
                    )
                )["operation"]
                assert completed["state"] == "applied", completed
                result = completed["result"]
                assert result["preflight_status"] == "PASS"
                assert result["preflight"]["status"] == "PASS"
                assert result["report_ref"] and result["prepared_run"]
                guard = {"expected_coordinator_id": result["coordinator_id"]}
                assert (
                    await _call(
                        client, "loom_get_operation", operation_id="prepare-1", **guard
                    )
                    == completed
                )
                reads: list[str] = []
                original = daemon.operation

                def counted(operation_id: str):
                    reads.append(operation_id)
                    return original(operation_id)

                monkeypatch.setattr(daemon, "operation", counted)
                wrong = await client.call_tool(
                    "loom_get_operation",
                    {
                        "operation_id": "prepare-1",
                        "expected_coordinator_id": "another-coordinator",
                    },
                )
                assert wrong.is_error and wrong.structured_content["code"] == "conflict"
                assert not reads
                monkeypatch.setattr(daemon, "operation", original)
                jobs = await _call(client, "loom_list_jobs", **guard)
                assert len(jobs["admissions"]) == 1  # Preparation child is visible.
                agents = await _call(client, "loom_list_agents", **guard)
                for agent in agents["agents"]:
                    assert (
                        await _call(
                            client,
                            "loom_get_agent",
                            agent_id=agent["agent_id"],
                            **guard,
                        )
                    )["agent_id"] == agent["agent_id"]
                admitted = await _call(
                    client,
                    "loom_submit_run",
                    run_uri=result["prepared_run"]["run_uri"],
                    queue_item_id="mcp-target",
                    **guard,
                )
            async with _client(
                args
            ) as client:
                observed = await _call(
                    client, "loom_get_job", queue_item_id="mcp-target"
                )
                assert observed["admission"]["admission_id"] == admitted["admission_id"]
                end = monotonic() + 30
                while observed["admission"]["state"] not in {
                    "SUCCEEDED",
                    "FAILED",
                    "CANCELLED",
                }:
                    assert monotonic() < end, observed
                    await _call(
                        client,
                        "loom_wait_for_change",
                        admission_id=admitted["admission_id"],
                        expected_revision=observed["admission"]["revision"],
                        timeout_seconds=5,
                    )
                    observed = await _call(
                        client, "loom_get_job", admission_id=admitted["admission_id"]
                    )
                assert observed["admission"]["state"] == "SUCCEEDED", observed
                outputs = await _call(client, "loom_select_outputs", selection={"run_uris": [admitted["run_uri"]]})
                lineage = await _call(client, "loom_trace_lineage", query={"start": {"run_uri": admitted["run_uri"]}})
                assert lineage["items"]
                assert outputs["items"][0]["locator"]["run_uri"] == admitted["run_uri"]
                assert outputs["items"][0]["availability"] == "not_checked"
                assert outputs["items"][0]["outcome"] == "selected"
                assert (
                    await _call(client, "loom_inspect_run", run_uri=admitted["run_uri"])
                    == inspection
                )
                context = await _call(client, "loom_run_context", run_uri=admitted["run_uri"])
                assert context["annotations"]["description"] == "MCP native reason"
                assert context["annotations"]["metadata"]["revision"] == 3
                assert context["initializer_submission"]["context"]["tags"] == {"application": "invoices"}
                updated = await _call(client, "loom_patch_run_annotations", run_uri=admitted["run_uri"], mutation_id="mcp-patch",
                    patch={"expected_revision": 1, "set_tags": {"review": "ready"}, "set_metadata": {"nullable": None}})
                assert updated["tags"] == {"application": "invoices", "review": "ready"}
                note = await _call(client, "loom_append_run_note", run_uri=admitted["run_uri"], mutation_id="mcp-note", text="Observed after completion")
                assert note["author"] and note["created_at"] and note["source"] == "native"
                assert await _call(client, "loom_append_run_note", run_uri=admitted["run_uri"], mutation_id="mcp-note", text="Observed after completion") == note
                notes = await _call(client, "loom_list_run_notes", run_uri=admitted["run_uri"], limit=1)
                assert notes["notes"] == [note]
                stale = await client.call_tool("loom_patch_run_annotations", {"run_uri": admitted["run_uri"], "mutation_id": "stale", "patch": {"expected_revision": 1}})
                assert stale.is_error and stale.structured_content["code"] == "conflict"
                store = LocalRunStore(service.daemon.run_store_root)
                worker = StageWorkerResult.from_dict(
                    store.read_stage_worker_result(
                        admitted["run_uri"], "produce", attempt=1
                    )
                )
                assert LocalArtifactStore(
                    store.local_artifact_root(admitted["run_uri"])
                ).load(worker.outputs["data"]) == {"value": 41}
                # Existing terminal admission retains its identity even after a cancel request.
                cancelled = await _call(
                    client, "loom_cancel_job", queue_item_id="mcp-target"
                )
                assert cancelled["admission_id"] == admitted["admission_id"]

        asyncio.run(scenario())


def test_real_large_report_preserves_native_projection(tmp_path: Path):
    from loom.artifacts import ArtifactRef
    from loom.pipeline.stores import LocalArtifactStore
    from loom.serialization import ensure_plain_data, stable_json_bytes

    with _coordinator(tmp_path, large=True) as (service, daemon, args):

        async def scenario():
            async with _client(args) as client:
                await _call(client, "loom_prepare_run", **_request().to_dict())
                operation = (
                    await _call(
                        client, "loom_wait_for_operation", operation_id="prepare-1"
                    )
                )["operation"]
                assert operation == ensure_plain_data(
                    daemon.operation("prepare-1").to_dict()
                )
                assert len(stable_json_bytes(operation)) <= 64 * 1024
                result = operation["result"]
                assert (
                    result["preflight"] is None and result["preflight_status"] == "PASS"
                )
                assert result["prepared_run"] is not None
                reference = ArtifactRef.from_dict(result["report_ref"])
                report = cast(
                    dict[str, Any],
                    LocalArtifactStore(service.daemon.run_store_root).load(reference),
                )
                assert len(stable_json_bytes(report["preflight"])) > 64 * 1024

        asyncio.run(scenario())


def test_waits_leave_capacity_for_status_and_explicit_preparation_cancel(
    tmp_path: Path,
):
    with _coordinator(tmp_path) as (_, daemon, args):
        assert daemon._preparations._reconcile_lock.acquire(timeout=25)

        async def scenario():
            async with _client(args) as client:
                await _call(client, "loom_prepare_run", **_request().to_dict())
                waits = [
                    asyncio.create_task(
                        _call(
                            client,
                            "loom_wait_for_operation",
                            operation_id="prepare-1",
                            timeout_seconds=3,
                        )
                    )
                    for _ in range(6)
                ]
                await asyncio.sleep(0.25)
                start = monotonic()
                await _call(client, "loom_status")
                await _call(client, "loom_cancel_preparation", operation_id="prepare-1")
                assert monotonic() - start < 2
                daemon._preparations._reconcile_lock.release()
                results = await asyncio.gather(*waits)
                assert all(
                    item["operation"]["state"] == "cancelled" for item in results
                )

        try:
            asyncio.run(scenario())
        finally:
            if daemon._preparations._reconcile_lock.locked():
                daemon._preparations._reconcile_lock.release()
        assert (
            cast(dict[str, Any], daemon.operation("prepare-1").result)[
                "preparation_admission_id"
            ]
            is None
        )


def test_lost_mutation_reply_retains_original_operation_and_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import loom.queue.local_daemon_transport as transport

    with _coordinator(tmp_path) as (service, daemon, args):
        write = transport._write_message
        dropped = Event()

        def drop_once(connection, response):
            result = response.get("result")
            if (
                isinstance(result, dict)
                and result.get("operation_id") == "prepare-1"
                and not dropped.is_set()
            ):
                dropped.set()
                return
            write(connection, response)

        monkeypatch.setattr(transport, "_write_message", drop_once)

        async def scenario():
            async with _client(args) as client:
                lost = await client.call_tool("loom_prepare_run", _request().to_dict())
                assert lost.is_error and dropped.is_set()
                assert lost.structured_content["mutation_outcome"] == "unknown"
                assert lost.structured_content["ids"]["operation_id"] == "prepare-1"
            async with _client(args) as client:
                operation = (
                    await _call(
                        client, "loom_wait_for_operation", operation_id="prepare-1"
                    )
                )["operation"]
                assert operation["state"] == "applied"
                assert (
                    await _call(client, "loom_prepare_run", **_request().to_dict())
                    == operation
                )
                with CoordinatorClient.from_unix_socket(
                    service.daemon.endpoint
                ) as native:
                    assert len(native.admissions().admissions) == 1

        asyncio.run(scenario())


@pytest.mark.parametrize("unified", [False, True])
def test_sdk_cancel_and_eof_do_not_cancel_dispatched_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unified: bool
):
    import loom.queue.local_daemon_transport as transport
    from contextlib import suppress

    with _coordinator(tmp_path) as (service, daemon, args):
        entered, release = Event(), Event()
        original = transport._write_message

        def held_reply(connection, response):
            result = response.get("result")
            if (
                isinstance(result, dict)
                and result.get("operation_id") == "prepare-1"
                and not entered.is_set()
            ):
                entered.set()
                release.wait(15)
            try:
                original(connection, response)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The SDK cancellation/EOF intentionally abandons this reply.

        monkeypatch.setattr(transport, "_write_message", held_reply)

        async def scenario():
            async with _client(args) as client:
                task = asyncio.create_task(
                    client.call_tool(
                        "loom_run" if unified else "loom_prepare_run",
                        {"request": {"preparation": _request().to_dict(), "queue_item_id": "mcp-unified"}}
                        if unified else _request().to_dict(),
                    )
                )
                assert await asyncio.to_thread(entered.wait, 10)
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            release.set()
            async with _client(args) as client:
                completed = (
                    await _call(
                        client, "loom_wait_for_operation", operation_id="prepare-1"
                    )
                )["operation"]
                assert completed["state"] == "applied", completed
                with CoordinatorClient.from_unix_socket(
                    service.daemon.endpoint
                ) as native:
                    assert len(native.admissions().admissions) == (2 if unified else 1)
                    if unified:
                        assert completed["kind"] == "run"
                        assert completed["result"]["admission"]["queue_item_id"] == "mcp-unified"

        try:
            asyncio.run(scenario())
        finally:
            release.set()


def test_cold_run_all_tools_reconnect_to_same_binding_after_restart(tmp_path: Path):
    from tests.integration.queue.test_service_lifetime import _selection, _stop_fixture_process
    from loom.deployment import connect_deployment, load_deployment

    selection = _selection(tmp_path, lifetime="persistent")
    args = ["--deployment", str(selection)]
    request = {"preparation": _request().to_dict(), "queue_item_id": "cold-mcp"}

    async def scenario():
        async with _client(args) as client:
            assert len((await client.list_tools()).tools) == len(TOOLS)
            assert not (tmp_path / "deployment").exists()
            offline = await client.call_tool("loom_status", {})
            assert offline.is_error
            assert not (tmp_path / "deployment").exists()
            refused = await client.call_tool("loom_run", {
                "request": request, "expected_coordinator_id": "another-owner",
            })
            assert refused.is_error
            assert refused.structured_content["code"] == "conflict"
            assert refused.structured_content["mutation_outcome"] == "not_applied"
            assert not (tmp_path / "deployment").exists()
            assert not (tmp_path / "binding.json").exists()
            accepted = await _call(client, "loom_run", request=request)
            owner = accepted["connection"]["coordinator_id"]
            assert accepted["operation_id"] == "prepare-1"
            completed = (await _call(client, "loom_wait_for_operation", operation_id="prepare-1"))["operation"]
            assert completed["state"] == "applied"
            assert (await _call(client, "loom_status"))["connection"]["coordinator_id"] == owner
            control = await _call(client, "loom_cancel_run_operation", operation_id="prepare-1")
            assert control["operation_id"] != "prepare-1"
            assert control["kind"] == "cancel_run"
            await _call(client, "loom_wait_for_operation", operation_id=control["operation_id"])
        binding = (tmp_path / "binding.json").read_bytes()
        _stop_fixture_process(tmp_path / "deployment/coordinator")
        database = tmp_path / "deployment/coordinator/control.sqlite"
        before_state = database.read_bytes()
        async with _client(args) as client:
            refused = await client.call_tool("loom_run", {
                "request": request, "expected_coordinator_id": "another-owner",
            })
            assert refused.is_error and refused.structured_content["code"] == "conflict"
            assert (tmp_path / "binding.json").read_bytes() == binding
            assert database.read_bytes() == before_state
            replay = await _call(client, "loom_run", request=request, expected_coordinator_id=owner)
            assert replay["connection"]["coordinator_id"] == owner
            assert replay["operation_id"] == "prepare-1"
            assert (tmp_path / "binding.json").read_bytes() == binding
            with connect_deployment(load_deployment(selection)) as native:
                assert native.describe_connection().coordinator_id == owner
                assert len(native.admissions().admissions) == 2

    try:
        asyncio.run(scenario())
    finally:
        _stop_fixture_process(tmp_path / "deployment/coordinator")

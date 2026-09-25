"""Focused MCP SDK boundary tests; imports remain inside the selected MCP lane."""

from __future__ import annotations

import asyncio
import time

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.mcp_extra, pytest.mark.optional_dependency]


class _Value:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def to_dict(self) -> dict[str, object]:
        return self.value


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str | None, float, bool]] = []

    def _native_call(
        self,
        operation: str,
        payload: dict[str, object],
        expected_coordinator_id: str | None,
        *,
        deadline: float,
        negotiate: bool = True,
    ) -> _Value | object:
        self.calls.append(
            (operation, payload, expected_coordinator_id, deadline, negotiate)
        )
        if operation == "admission_for_queue_item":
            return type("Admission", (), {"admission_id": "admission-a"})()
        if operation == "admission":
            return _Value({"admission_id": payload["admission_id"], "state": "RUNNING"})
        if operation == "operation":
            return _Value({"operation_id": payload["operation_id"], "state": "APPLIED"})
        if operation == "handshake":
            return _Value({"coordinator_id": "coordinator-a"})
        if operation == "status":
            return _Value({"service_health": "healthy"})
        raise AssertionError(f"unexpected operation: {operation}")


def test_sdk_registers_native_tool_names_and_forwards_guard() -> None:

    client = _Client()
    server = create_server(client=client)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
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
        "loom_search_submissions",
        "loom_search_jobs",
        "loom_query_fields",
        "loom_select_outputs",
        "loom_trace_lineage",
        "loom_describe_artifact",
        "loom_read_artifact",
        "loom_fetch_artifacts",
        "loom_tag_keys",
        "loom_tag_values",
        "loom_list_agents",
        "loom_get_agent",
        "loom_submit_run",
        "loom_wait_for_change",
        "loom_cancel_job",
    }
    prepare = next(tool for tool in tools if tool.name == "loom_prepare_run")
    schema = prepare.model_dump(by_alias=True)["inputSchema"]
    source = schema["properties"]["source"]
    assert set(source["required"]) == {
        "mode",
        "root",
        "path",
        "include",
    }
    result = asyncio.run(
        server.call_tool(
            "loom_get_operation",
            {"operation_id": "operation-a", "expected_coordinator_id": "coord-a"},
        )
    )
    assert getattr(result, "is_error") is False
    assert getattr(result, "structured_content") == {
        "operation_id": "operation-a",
        "state": "APPLIED",
    }
    assert "operation_id=operation-a" in getattr(result, "content")[0].text
    assert "state: APPLIED" in getattr(result, "content")[0].text
    assert client.calls[0][0:3] == (
        "operation",
        {"operation_id": "operation-a"},
        "coord-a",
    )


def test_queue_item_lookup_precedes_native_admission_detail() -> None:

    client = _Client()
    result = asyncio.run(
        create_server(client=client).call_tool(
            "loom_get_job", {"queue_item_id": "queue-a"}
        )
    )
    assert getattr(result, "is_error") is False
    assert getattr(result, "structured_content") == {
        "admission_id": "admission-a",
        "state": "RUNNING",
    }
    assert [call[0] for call in client.calls] == [
        "admission_for_queue_item",
        "admission",
    ]


def test_invalid_job_selector_is_a_structured_tool_error() -> None:

    result = asyncio.run(create_server(client=_Client()).call_tool("loom_get_job", {}))
    assert getattr(result, "is_error") is True
    detail = getattr(result, "structured_content")
    assert detail["code"] == "invalid_request"
    assert detail["operation"] == "admission"


def test_successful_calls_release_adapter_capacity() -> None:

    server = create_server(client=_Client())

    async def call_repeatedly() -> list[object]:
        return [
            await server.call_tool(
                "loom_get_operation", {"operation_id": f"op-{index}"}
            )
            for index in range(9)
        ]

    results = asyncio.run(call_repeatedly())
    assert all(getattr(result, "is_error") is False for result in results)


def test_compound_lookup_shares_one_absolute_native_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loom.mcp import _server

    class DelayedClient(_Client):
        def _native_call(
            self,
            operation: str,
            payload: dict[str, object],
            expected_coordinator_id: str | None,
            *,
            deadline: float,
            negotiate: bool = True,
        ) -> _Value | object:
            if operation == "admission_for_queue_item":
                time.sleep(0.02)
            return super()._native_call(
                operation,
                payload,
                expected_coordinator_id,
                deadline=deadline,
                negotiate=negotiate,
            )

    monkeypatch.setattr(_server, "REQUEST_BUDGET_SECONDS", 0.05)
    client = DelayedClient()
    result = asyncio.run(
        create_server(client=client).call_tool(
            "loom_get_job", {"queue_item_id": "queue-a"}
        )
    )
    assert getattr(result, "is_error") is False
    first, second = client.calls
    assert first[3] == second[3]
    assert second[3] - time.monotonic() < 0.04


def test_status_connection_and_status_share_one_absolute_native_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loom.mcp import _server

    class DelayedClient(_Client):
        def _native_call(
            self,
            operation: str,
            payload: dict[str, object],
            expected_coordinator_id: str | None,
            *,
            deadline: float,
            negotiate: bool = True,
        ) -> _Value | object:
            if operation == "handshake":
                time.sleep(0.02)
            return super()._native_call(
                operation,
                payload,
                expected_coordinator_id,
                deadline=deadline,
                negotiate=negotiate,
            )

    monkeypatch.setattr(_server, "REQUEST_BUDGET_SECONDS", 0.05)
    client = DelayedClient()
    result = asyncio.run(create_server(client=client).call_tool("loom_status", {}))
    assert getattr(result, "is_error") is False
    handshake, status = client.calls
    assert handshake[3] == status[3]
    assert status[3] - time.monotonic() < 0.04


def test_invalid_mutation_keeps_native_not_applied_outcome() -> None:

    result = asyncio.run(
        create_server(client=_Client()).call_tool(
            "loom_submit_run", {"run_uri": "file:///run", "queue_item_id": ""}
        )
    )
    detail = getattr(result, "structured_content")
    assert getattr(result, "is_error") is True
    assert detail["operation"] == "submit"
    assert detail["ids"]["run_uri"] == "file:///run"
    assert detail["mutation_outcome"] == "not_applied"


def create_server(*, client):
    """Substitute native resolution only; public deployment binding has real tests."""
    from contextlib import contextmanager
    from loom.mcp._server import _Adapter

    @contextmanager
    def connect():
        try:
            yield client
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                close()

    adapter = _Adapter("/unused/test-deployment.json")
    adapter._connect = connect
    return adapter.server()


def test_public_deployment_discovery_is_inert_and_has_no_override(tmp_path, monkeypatch):
    from loom.mcp import create_server as public_server
    from loom.mcp import _server

    def forbidden(*args, **kwargs):
        raise AssertionError("discovery attempted deployment IO")

    monkeypatch.setattr(_server.deployments, "load_deployment", forbidden)
    server = public_server(deployment=tmp_path / "uncreated.json")
    for tool in asyncio.run(server.list_tools()):
        properties = tool.model_dump(by_alias=True)["inputSchema"]["properties"]
        assert not {"deployment", "connection", "endpoint"} & properties.keys()
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint == (tool.name not in {
            "loom_run", "loom_submit_run", "loom_prepare_run", "loom_cancel_job",
            "loom_cancel_preparation", "loom_cancel_run_operation",
            "loom_patch_run_annotations", "loom_append_run_note", "loom_fetch_artifacts",
        })


@pytest.mark.parametrize("fresh", [False, True])
def test_run_delegates_complete_native_intent_and_absolute_deadline(tmp_path, monkeypatch, fresh):
    from loom.mcp import create_server as public_server
    from loom.mcp import _server
    from tests.contracts.test_mcp_tools import PREPARE

    captured = []
    request = {"preparation": {**PREPARE, "overlays": ["a.yaml", "b.yaml"],
                              "overrides": ["x=1", "x=2"], "run_options": {"tags": {"trial": "mcp-check"}}},
               "queue_item_id": "queue-one"}

    if fresh:
        request["fresh_stages"] = ["author", "reader"]

    def run(native, **kwargs):
        captured.append((native.to_dict(), kwargs))
        return _Value({"operation_id": "prepare-one", "cleanup": {"coordinator": "borrowed"}})

    monkeypatch.setattr(_server, "native_run", run)
    server = public_server(deployment=tmp_path / "deployment.json")
    before = time.monotonic()
    result = asyncio.run(server.call_tool("loom_run", {
        "request": request, "expected_coordinator_id": "owner-one",
    }))
    assert not getattr(result, "is_error")
    intent, options = captured.pop()
    assert intent == request
    assert options["deployment"] == tmp_path / "deployment.json"
    assert options["wait"] is False
    assert options["expected_coordinator_id"] == "owner-one"
    assert before < options["_deadline"] <= before + 30.1
    assert getattr(result, "structured_content")["operation_id"] == "prepare-one"


def test_run_unknown_outcome_retains_native_recovery(tmp_path, monkeypatch):
    from loom.mcp import create_server as public_server
    from loom.mcp import _server
    from loom.queue._coordinator_control import control_error
    from tests.contracts.test_mcp_tools import PREPARE

    request = {"preparation": PREPARE, "queue_item_id": "queue-one"}
    error = control_error("unavailable", "start_run", {"request": request}, dispatched=True)

    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(_server, "native_run", run)
    result = asyncio.run(public_server(deployment=tmp_path / "selection.json").call_tool(
        "loom_run", {"request": request}))
    assert getattr(result, "is_error")
    assert getattr(result, "structured_content") == error.to_dict()
    assert getattr(result, "structured_content")["mutation_outcome"] == "unknown"


def test_run_cancellation_calls_native_named_method_and_returns_control():
    class Client(_Client):
        def cancel_run_operation(self, operation_id, *, expected_coordinator_id, deadline):
            assert operation_id == "run-one"
            assert expected_coordinator_id == "owner-one"
            assert deadline > time.monotonic()
            return _Value({"operation_id": "cancel-run-one", "kind": "cancel_run", "state": "pending"})

    result = asyncio.run(create_server(client=Client()).call_tool(
        "loom_cancel_run_operation", {"operation_id": "run-one", "expected_coordinator_id": "owner-one"}))
    assert not getattr(result, "is_error")
    assert getattr(result, "structured_content")["operation_id"] == "cancel-run-one"


def test_prepare_controls_and_explicit_receipt_retry_reach_native_owner():
    from tests.contracts.test_mcp_tools import PREPARE

    class Client(_Client):
        def _native_call(self, operation, payload, *args, **kwargs):
            self.calls.append((operation, payload, None, 0.0, True))
            return _Value({"state": "pending"})

    native = Client()
    server = create_server(client=native)
    request = {**PREPARE, "overlays": ["a.yaml", "b.yaml"], "overrides": ["x=1", "x=2"], "run_options": {"tags": {"trial": "mcp-check"}}}
    assert not getattr(asyncio.run(server.call_tool("loom_prepare_run", request)), "is_error")
    assert native.calls[-1][:2] == ("prepare_run", {"request": request})
    receipt = {"run_uri": "file:///run", "queue_item_id": "queue-one", "retry_failed_revision": 4}
    assert not getattr(asyncio.run(server.call_tool("loom_submit_run", receipt)), "is_error")
    assert native.calls[-1][:2] == ("submit", {"request": receipt})


def test_cancelled_sdk_call_holds_capacity_until_native_completion(monkeypatch):
    from threading import Event
    from loom.mcp import _server

    monkeypatch.setattr(_server, "CLIENT_CAPACITY", 1)
    entered, release = Event(), Event()
    capacity = _server._Capacity()

    def held(deadline):
        entered.set()
        assert release.wait(5)

    async def scenario():
        first = asyncio.create_task(capacity.call(held, waiting=False))
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert capacity._requests.locked()
        release.set()
        await capacity.call(lambda deadline: None, waiting=False)
        assert not capacity._requests.locked()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
        capacity.close()

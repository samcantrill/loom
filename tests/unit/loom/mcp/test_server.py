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
    from loom.mcp import create_server

    client = _Client()
    server = create_server(client=client)
    tools = asyncio.run(server.list_tools())
    assert {tool.name for tool in tools} == {
        "loom_status",
        "loom_prepare_run",
        "loom_get_operation",
        "loom_wait_for_operation",
        "loom_cancel_preparation",
        "loom_list_jobs",
        "loom_get_job",
        "loom_inspect_run",
        "loom_list_agents",
        "loom_get_agent",
        "loom_submit_run",
        "loom_wait_for_change",
        "loom_cancel_job",
    }
    prepare = next(tool for tool in tools if tool.name == "loom_prepare_run")
    schema = prepare.model_dump(by_alias=True)["inputSchema"]
    source = schema["$defs"]["_PreparationSourceInput"]
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
    from loom.mcp import create_server

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
    from loom.mcp import create_server

    result = asyncio.run(create_server(client=_Client()).call_tool("loom_get_job", {}))
    assert getattr(result, "is_error") is True
    detail = getattr(result, "structured_content")
    assert detail["code"] == "invalid_request"
    assert detail["operation"] == "admission"


def test_successful_calls_release_adapter_capacity() -> None:
    from loom.mcp import create_server

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
    from loom.mcp import create_server
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
    from loom.mcp import create_server
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
    from loom.mcp import create_server

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

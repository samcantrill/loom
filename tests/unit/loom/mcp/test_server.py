"""Focused MCP SDK boundary tests; imports remain inside the selected MCP lane."""

from __future__ import annotations

import asyncio

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.mcp_extra, pytest.mark.optional_dependency]


class _Value:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def to_dict(self) -> dict[str, object]:
        return self.value


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def operation(self, *args: object, **kwargs: object) -> _Value:
        self.calls.append(("operation", args, kwargs))
        return _Value({"operation_id": args[0], "state": "APPLIED"})

    def admission_for_queue_item(self, *args: object, **kwargs: object) -> object:
        self.calls.append(("admission_for_queue_item", args, kwargs))
        return type("Admission", (), {"admission_id": "admission-a"})()

    def admission(self, *args: object, **kwargs: object) -> _Value:
        self.calls.append(("admission", args, kwargs))
        return _Value({"admission_id": args[0], "state": "RUNNING"})


def test_sdk_registers_native_tool_names_and_forwards_guard() -> None:
    from loom.mcp import create_server

    client = _Client()
    server = create_server(client=client)
    assert {tool.name for tool in asyncio.run(server.list_tools())} == {
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
    assert client.calls == [
        ("operation", ("operation-a",), {"expected_coordinator_id": "coord-a"})
    ]


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

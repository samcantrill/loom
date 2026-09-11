"""All assistant mappings preserve native arguments/results and guard identity."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.optional_dependency,
    pytest.mark.mcp_extra,
]

SOURCE = {
    "mode": "shared",
    "root": "projects",
    "path": ".",
    "include": ["pipeline.yaml"],
}
PREPARE = {
    "operation_id": "prepare-one",
    "run_name": "target-one",
    "source": SOURCE,
    "config_path": "pipeline.yaml",
    "preparation_profile": "existing",
}


class NativeValue:
    admission_id = "admission-one"

    def to_dict(self):
        return {
            "state": "failed",
            "native_evidence": {"detail": ["retained", 41]},
            "schema_version": 1,
        }


class Spy:
    def __init__(self):
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.closed = False

    def close(self):
        self.closed = True

    def _native_call(
        self, operation, payload, expected, *, deadline, negotiate=True
    ) -> object:
        self.calls.append(
            (
                operation,
                (payload,),
                {"expected_coordinator_id": expected, "deadline": deadline},
            )
        )
        if operation == "inspect_run":
            return {"schema_version": 1, "code": "unavailable"}
        return NativeValue()

    def _wait_native(self, operation, payload, timeout, expected, *, terminal_deadline):
        self.calls.append(
            (
                operation,
                (payload,),
                {
                    "expected_coordinator_id": expected,
                    "deadline": terminal_deadline,
                    "timeout_seconds": timeout,
                },
            )
        )
        return NativeValue()


@pytest.mark.parametrize(
    "tool,arguments,native,args",
    [
        ("loom_status", {}, ["describe_connection", "status"], [(), ()]),
        ("loom_prepare_run", PREPARE, ["prepare_run"], [(PREPARE,)]),
        (
            "loom_get_operation",
            {"operation_id": "prepare-one"},
            ["operation"],
            [("prepare-one",)],
        ),
        (
            "loom_wait_for_operation",
            {"operation_id": "prepare-one"},
            ["wait_operation"],
            [("prepare-one",)],
        ),
        (
            "loom_cancel_preparation",
            {"operation_id": "prepare-one"},
            ["cancel_preparation"],
            [("prepare-one",)],
        ),
        ("loom_list_jobs", {}, ["admissions"], [(20, None)]),
        (
            "loom_get_job",
            {"admission_id": "admission-one"},
            ["admission"],
            [("admission-one",)],
        ),
        (
            "loom_get_job",
            {"queue_item_id": "queue-one"},
            ["admission_for_queue_item", "admission"],
            [("queue-one",), ("admission-one",)],
        ),
        (
            "loom_inspect_run",
            {"run_uri": "file:///runs/one"},
            ["inspect_run"],
            [("file:///runs/one",)],
        ),
        ("loom_list_agents", {}, ["agents"], [(20, None)]),
        ("loom_get_agent", {"agent_id": "worker-one"}, ["agent"], [("worker-one",)]),
        (
            "loom_submit_run",
            {"run_uri": "file:///runs/one", "queue_item_id": "queue-one"},
            ["submit"],
            [({"run_uri": "file:///runs/one", "queue_item_id": "queue-one"},)],
        ),
        (
            "loom_wait_for_change",
            {"admission_id": "admission-one", "expected_revision": 7},
            ["wait_admission"],
            [("admission-one", 7)],
        ),
        (
            "loom_cancel_job",
            {"queue_item_id": "queue-one"},
            ["cancel"],
            [("queue-one",)],
        ),
    ],
)
def test_native_mapping_and_default_arguments(tool, arguments, native, args):
    from mcp import Client
    from loom.mcp import create_server

    spy = Spy()

    async def scenario():
        async with Client(create_server(client=spy)) as client:
            result = await client.call_tool(
                tool, {**arguments, "expected_coordinator_id": "coordinator-one"}
            )
            assert not result.is_error, result
            expected = NativeValue().to_dict()
            if tool == "loom_status":
                expected = {"connection": expected, "status": expected}
            elif tool == "loom_inspect_run":
                expected = {"schema_version": 1, "code": "unavailable"}
            assert result.structured_content == expected

    asyncio.run(scenario())
    native = ["handshake" if name == "describe_connection" else name for name in native]
    assert [call[0] for call in spy.calls] == native

    def request(name, values):
        if name in {"handshake", "status"}:
            return {}
        if name in {"prepare_run", "submit"}:
            return {"request": values[0]}
        if name in {"admissions", "agents"}:
            return {"limit": values[0], "cursor": values[1]}
        if name == "wait_admission":
            return {"admission_id": values[0], "expected_revision": values[1]}
        key = {
            "operation": "operation_id",
            "wait_operation": "operation_id",
            "cancel_preparation": "operation_id",
            "admission": "admission_id",
            "admission_for_queue_item": "queue_item_id",
            "inspect_run": "run_uri",
            "agent": "agent_id",
            "cancel": "queue_item_id",
        }[name]
        return {key: values[0]}

    assert [call[1][0] for call in spy.calls] == [
        request(name, values) for name, values in zip(native, args)
    ]
    assert spy.closed
    for _, _, kwargs in spy.calls:
        assert kwargs["expected_coordinator_id"] == "coordinator-one"
        if tool in {"loom_wait_for_change", "loom_wait_for_operation"}:
            assert kwargs["timeout_seconds"] == 25


@pytest.mark.parametrize(
    "tool,arguments",
    [
        ("loom_list_jobs", {"limit": 0}),
        ("loom_list_agents", {"limit": 101}),
        (
            "loom_wait_for_operation",
            {"operation_id": "prepare-one", "timeout_seconds": 26},
        ),
        (
            "loom_get_job",
            {"queue_item_id": "queue-one", "admission_id": "admission-one"},
        ),
        ("loom_prepare_run", {**PREPARE, "source": {**SOURCE, "path": "../outside"}}),
    ],
)
def test_native_invalid_request_is_not_an_offline_error(tmp_path, tool, arguments):
    from mcp import Client
    from loom.mcp import create_server
    from loom.coordinator import CoordinatorClient

    async def scenario():
        with CoordinatorClient.from_unix_socket(tmp_path / "offline.sock") as native:
            async with Client(create_server(client=native)) as client:
                result = await client.call_tool(tool, arguments)
                assert result.is_error
                assert result.structured_content["code"] == "invalid_request"
                if tool == "loom_prepare_run":
                    assert (
                        result.structured_content["mutation_outcome"] == "not_applied"
                    )
                    assert (
                        result.structured_content["ids"]["operation_id"]
                        == "prepare-one"
                    )

    asyncio.run(scenario())


def test_frozen_operation_evidence_serializes_without_changing_native_state():
    from mcp import Client
    from loom.mcp import create_server
    from loom.queue import LocalDaemonOperation
    from mcp.types import TextContent
    from loom.serialization import ensure_plain_data

    operation = LocalDaemonOperation.from_dict(
        {
            "operation_id": "prepare-one",
            "kind": "prepare_run",
            "state": "applied",
            "code": None,
            "result": {
                "coordinator_id": "coordinator-one",
                "preflight_status": "PASS",
                "report_ref": {"uri": "file:///evidence/report.json"},
                "preflight": {
                    "details": {
                        "state": "project-state",
                        "coordinator_id": "project-setting",
                    }
                },
                "prepared_run": {"run_uri": "file:///runs/one"},
            },
        }
    )

    class FrozenClient(Spy):
        def _native_call(self, *args, **kwargs):
            return operation

    async def scenario():
        async with Client(create_server(client=FrozenClient())) as client:
            result = await client.call_tool(
                "loom_get_operation", {"operation_id": "prepare-one"}
            )
            assert not result.is_error
            assert result.structured_content == ensure_plain_data(operation.to_dict())
            encoded = result.model_dump_json()
            assert "mappingproxy" not in encoded
            assert isinstance(result.content[0], TextContent)
            text = result.content[0].text
            assert "state: applied" in text
            assert "coordinator_id=coordinator-one" in text
            assert "Report evidence: file:///evidence/report.json" in text
            assert "project-state" not in text and "project-setting" not in text

    asyncio.run(scenario())


def test_source_unknown_fields_reach_native_refusal_instead_of_silent_removal():
    from mcp import Client
    from loom.mcp import create_server

    spy = Spy()

    async def scenario():
        async with Client(create_server(client=spy)) as client:
            request = {**PREPARE, "source": {**SOURCE, "exclude": ["private.txt"]}}
            result = await client.call_tool("loom_prepare_run", request)
            assert result.is_error
            assert result.structured_content["code"] == "invalid_request"
            assert result.structured_content["mutation_outcome"] == "not_applied"
            assert result.structured_content["ids"]["operation_id"] == "prepare-one"
            assert spy.calls == []

    asyncio.run(scenario())

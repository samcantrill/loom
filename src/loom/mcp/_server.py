"""MCP 2.x bindings for the native coordinator client.

This module is intentionally behind :mod:`loom.mcp`'s optional-import boundary.
The coordinator remains the sole owner of scheduling, durable state, guards and
native request deadlines.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import time
from typing import Any, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from loom.coordinator import CoordinatorClientError, PrepareRunRequest
from loom.queue._coordinator_transport import (
    CLIENT_CAPACITY,
    CLIENT_WAIT_CAPACITY,
    REQUEST_BUDGET_SECONDS,
)
from loom.queue.errors import QueueError
from loom.queue.local_daemon import LocalDaemonAdmissionRequest
from loom.serialization import PlainData


_Result = TypeVar("_Result")


class _Capacity:
    """Keep SDK-loop work bounded while native calls run on independent threads."""

    def __init__(self) -> None:
        self._requests = asyncio.BoundedSemaphore(CLIENT_CAPACITY)
        self._waits = asyncio.BoundedSemaphore(CLIENT_WAIT_CAPACITY)
        self._executor = ThreadPoolExecutor(
            max_workers=CLIENT_CAPACITY, thread_name_prefix="loom-mcp"
        )
        self._closed = False

    async def call(self, action: Callable[[], _Result], *, waiting: bool) -> _Result:
        if self._closed:
            raise CoordinatorClientError(
                "unavailable", boundary="client_protocol", operation="mcp"
            )
        deadline = time.monotonic() + REQUEST_BUDGET_SECONDS
        wait_reserved = request_reserved = False
        try:
            if waiting:
                await self._acquire(self._waits, deadline)
                wait_reserved = True
            await self._acquire(self._requests, deadline)
            request_reserved = True
        except BaseException:
            if request_reserved:
                self._requests.release()
            if wait_reserved:
                self._waits.release()
            raise

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, action)
        released = False

        def release(_: object | None = None) -> None:
            nonlocal released
            if released:
                return
            released = True
            self._requests.release()
            if waiting:
                self._waits.release()

        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Keep capacity reserved until the native deadline/connection cleanup
            # finishes.  Cancellation never becomes a durable lifecycle request.
            future.add_done_callback(lambda done: loop.call_soon_threadsafe(release, done))
            raise
        except BaseException:
            release()
            raise
        else:
            release()

    async def _acquire(
        self, semaphore: asyncio.BoundedSemaphore, deadline: float
    ) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise self._capacity_error()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=remaining)
        except TimeoutError as exc:
            raise self._capacity_error() from exc

    @staticmethod
    def _capacity_error() -> CoordinatorClientError:
        return CoordinatorClientError(
            "capacity_exhausted", boundary="client_protocol", operation="mcp"
        )

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=False)


def _payload(value: object) -> Any:
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return value


def _result(value: object, text: str) -> CallToolResult:
    payload = _payload(value)
    return CallToolResult(
        content=[TextContent(text=text)], structured_content=payload
    )


def _error(error: CoordinatorClientError) -> CallToolResult:
    detail = error.to_dict()
    return CallToolResult(
        content=[TextContent(text=f"{error.operation}: {error.code}")],
        structured_content=detail,
        is_error=True,
    )


class _Adapter:
    def __init__(self, client: Any) -> None:
        self._client = client
        self._capacity = _Capacity()

    async def _call(
        self,
        operation: str,
        action: Callable[[], _Result],
        *,
        text: str,
        ids: dict[str, PlainData],
        waiting: bool = False,
    ) -> CallToolResult:
        try:
            value = await self._capacity.call(action, waiting=waiting)
        except asyncio.CancelledError:
            raise
        except CoordinatorClientError as exc:
            return _error(exc)
        except (QueueError, TypeError, ValueError):
            return _error(
                CoordinatorClientError(
                    "invalid_request",
                    boundary="client_protocol",
                    operation=operation,
                    ids=ids,
                )
            )
        except Exception:
            return _error(
                CoordinatorClientError(
                    "internal_error",
                    boundary="client_protocol",
                    operation=operation,
                    ids=ids,
                )
            )
        return _result(value, text)

    def server(self) -> MCPServer:
        server = MCPServer(name="loom")
        read = ToolAnnotations(read_only_hint=True)
        mutate = ToolAnnotations(read_only_hint=False)

        @server.tool(annotations=read)
        async def loom_status(
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Read the configured connection and current native coordinator status."""
            return await self._call(
                "status",
                lambda: {
                    "connection": self._client.describe_connection(
                        expected_coordinator_id=expected_coordinator_id
                    ).to_dict(),
                    "status": self._client.status(
                        expected_coordinator_id=expected_coordinator_id
                    ).to_dict(),
                },
                text="Observed connection and coordinator status.",
                ids={"expected_coordinator_id": expected_coordinator_id},
            )

        @server.tool(annotations=mutate)
        async def loom_prepare_run(
            operation_id: str,
            run_name: str,
            source: dict[str, object],
            config_path: str,
            preparation_profile: str,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Durably request native preparation from an authored source and profile."""
            request_data = {
                "operation_id": operation_id,
                "run_name": run_name,
                "source": source,
                "config_path": config_path,
                "preparation_profile": preparation_profile,
            }
            return await self._call(
                "prepare_run",
                lambda: self._client.prepare_run(
                    PrepareRunRequest.from_dict(request_data),
                    expected_coordinator_id=expected_coordinator_id,
                ),
                text=f"Preparation operation {operation_id} was observed.",
                ids={"operation_id": operation_id},
            )

        @server.tool(annotations=read)
        async def loom_get_operation(
            operation_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Read one native preparation operation and its retained evidence."""
            return await self._call(
                "operation",
                lambda: self._client.operation(
                    operation_id, expected_coordinator_id=expected_coordinator_id
                ),
                text=f"Observed operation {operation_id}.",
                ids={"operation_id": operation_id},
            )

        @server.tool(annotations=read)
        async def loom_wait_for_operation(
            operation_id: str,
            timeout_seconds: float = 25,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Observe an operation for 0–25 seconds without cancelling durable work."""
            return await self._call(
                "wait_operation",
                lambda: self._client.wait_operation(
                    operation_id,
                    timeout_seconds=timeout_seconds,
                    expected_coordinator_id=expected_coordinator_id,
                ),
                text=f"Bounded observation for operation {operation_id} completed.",
                ids={"operation_id": operation_id},
                waiting=True,
            )

        @server.tool(annotations=mutate)
        async def loom_cancel_preparation(
            operation_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Request native cancellation of one preparation operation."""
            return await self._call(
                "cancel_preparation",
                lambda: self._client.cancel_preparation(
                    operation_id, expected_coordinator_id=expected_coordinator_id
                ),
                text=f"Cancellation request for preparation {operation_id} was observed.",
                ids={"operation_id": operation_id},
            )

        @server.tool(annotations=read)
        async def loom_list_jobs(
            limit: int = 20,
            cursor: str | None = None,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Read a native admissions page, including preparation child admissions."""
            return await self._call(
                "admissions",
                lambda: self._client.admissions(
                    limit, cursor, expected_coordinator_id=expected_coordinator_id
                ),
                text="Observed native admissions.",
                ids={},
            )

        @server.tool(annotations=read)
        async def loom_get_job(
            admission_id: str | None = None,
            queue_item_id: str | None = None,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Read one admission by exactly one admission or queue-item identifier."""
            if (admission_id is None) == (queue_item_id is None):
                return _error(
                    CoordinatorClientError(
                        "invalid_request",
                        boundary="client_protocol",
                        operation="admission",
                        ids={
                            key: value
                            for key, value in {
                                "admission_id": admission_id,
                                "queue_item_id": queue_item_id,
                            }.items()
                            if value is not None
                        },
                    )
                )
            if queue_item_id is not None:
                return await self._call(
                    "admission_for_queue_item",
                    lambda: self._client.admission(
                        self._client.admission_for_queue_item(
                            queue_item_id,
                            expected_coordinator_id=expected_coordinator_id,
                        ).admission_id,
                        expected_coordinator_id=expected_coordinator_id,
                    ),
                    text=f"Observed admission for queue item {queue_item_id}.",
                    ids={"queue_item_id": queue_item_id},
                )
            assert admission_id is not None
            return await self._call(
                "admission",
                lambda: self._client.admission(
                    admission_id, expected_coordinator_id=expected_coordinator_id
                ),
                text=f"Observed admission {admission_id}.",
                ids={"admission_id": admission_id},
            )

        @server.tool(annotations=read)
        async def loom_inspect_run(
            run_uri: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Inspect a run, returning either native diagnostic union member."""
            return await self._call(
                "inspect_run",
                lambda: self._client.inspect_run(
                    run_uri, expected_coordinator_id=expected_coordinator_id
                ),
                text=f"Observed run inspection for {run_uri}.",
                ids={"run_uri": run_uri},
            )

        @server.tool(annotations=read)
        async def loom_list_agents(
            limit: int = 20,
            cursor: str | None = None,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Read a native page of observed agents."""
            return await self._call(
                "agents",
                lambda: self._client.agents(
                    limit, cursor, expected_coordinator_id=expected_coordinator_id
                ),
                text="Observed native agents.",
                ids={},
            )

        @server.tool(annotations=read)
        async def loom_get_agent(
            agent_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Read one native agent projection."""
            return await self._call(
                "agent",
                lambda: self._client.agent(
                    agent_id, expected_coordinator_id=expected_coordinator_id
                ),
                text=f"Observed agent {agent_id}.",
                ids={"agent_id": agent_id},
            )

        @server.tool(annotations=mutate)
        async def loom_submit_run(
            run_uri: str,
            queue_item_id: str,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Submit a prepared run with its stable native queue-item identifier."""
            return await self._call(
                "submit",
                lambda: self._client.submit(
                    LocalDaemonAdmissionRequest(queue_item_id, run_uri),
                    expected_coordinator_id=expected_coordinator_id,
                ),
                text=f"Submission for queue item {queue_item_id} was observed.",
                ids={"queue_item_id": queue_item_id, "run_uri": run_uri},
            )

        @server.tool(annotations=read)
        async def loom_wait_for_change(
            admission_id: str,
            expected_revision: int,
            timeout_seconds: float = 25,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Observe one admission revision for 0–25 seconds."""
            return await self._call(
                "wait_admission",
                lambda: self._client.wait_admission(
                    admission_id,
                    expected_revision,
                    timeout_seconds=timeout_seconds,
                    expected_coordinator_id=expected_coordinator_id,
                ),
                text=f"Bounded observation for admission {admission_id} completed.",
                ids={"admission_id": admission_id},
                waiting=True,
            )

        @server.tool(annotations=mutate)
        async def loom_cancel_job(
            queue_item_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Request native cancellation for one queue-item identifier."""
            return await self._call(
                "cancel",
                lambda: self._client.cancel(
                    queue_item_id, expected_coordinator_id=expected_coordinator_id
                ),
                text=f"Cancellation request for queue item {queue_item_id} was observed.",
                ids={"queue_item_id": queue_item_id},
            )

        return server

    def close(self) -> None:
        self._capacity.close()
        close = getattr(self._client, "close", None)
        if callable(close):
            close()


def create_server(*, client: Any) -> MCPServer:
    """Register the 13 native coordinator tools without contacting a coordinator."""
    return _Adapter(client).server()


def run_server(*, client: Any) -> None:
    """Run stdio and release only local adapter/client resources on shutdown."""
    adapter = _Adapter(client)
    try:
        adapter.server().run(transport="stdio")
    finally:
        adapter.close()

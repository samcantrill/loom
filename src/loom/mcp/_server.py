"""MCP 2.x bindings for the native coordinator client.

This module is intentionally behind :mod:`loom.mcp`'s optional-import boundary.
The coordinator remains the sole owner of scheduling, durable state, guards and
native request deadlines.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import time
from typing import Annotated, Any, TypeVar, cast

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import TypeAdapter, WithJsonSchema

from loom.coordinator import CoordinatorClientError, PrepareRunRequest
from loom.diagnostics.run_inspection import decode_run_inspection_response
from loom.queue._coordinator_control import control_error
from loom.queue._coordinator_transport import (
    CLIENT_CAPACITY,
    CLIENT_WAIT_CAPACITY,
    REQUEST_BUDGET_SECONDS,
)
from loom.queue.errors import QueueError
from loom.queue.preparation import PreparationSource
from loom.queue.local_daemon import LocalDaemonAdmissionRequest
from loom.serialization import PlainData, to_plain_data


_Result = TypeVar("_Result")


# Advertise the native source fields without SDK normalization dropping unknown
# keys before the native exact-field decoder can reject the authored intent.
_PreparationSourceInput = Annotated[
    dict[str, object],
    WithJsonSchema(TypeAdapter(PreparationSource).json_schema()),
]


class _CapacityUnavailable(Exception):
    """Adapter admission ended before synchronous native work could start."""


class _CapacityClosed(Exception):
    """The stdio adapter is shutting down its local execution capacity."""


class _Capacity:
    """Keep SDK-loop work bounded while native calls run on independent threads."""

    def __init__(self) -> None:
        self._requests = asyncio.BoundedSemaphore(CLIENT_CAPACITY)
        self._waits = asyncio.BoundedSemaphore(CLIENT_WAIT_CAPACITY)
        self._executor = ThreadPoolExecutor(
            max_workers=CLIENT_CAPACITY, thread_name_prefix="loom-mcp"
        )
        self._closed = False

    async def call(
        self, action: Callable[[float], _Result], *, waiting: bool
    ) -> _Result:
        if self._closed:
            raise _CapacityClosed()
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
        future = loop.run_in_executor(self._executor, action, deadline)
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
            value = await asyncio.shield(future)
        except asyncio.CancelledError:
            # Keep capacity reserved until the native deadline/connection cleanup
            # finishes.  Cancellation never becomes a durable lifecycle request.
            future.add_done_callback(
                lambda done: loop.call_soon_threadsafe(release, done)
            )
            raise
        except BaseException:
            release()
            raise
        else:
            release()
        return value

    async def _acquire(
        self, semaphore: asyncio.BoundedSemaphore, deadline: float
    ) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _CapacityUnavailable()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=remaining)
        except TimeoutError as exc:
            raise _CapacityUnavailable() from exc

    def close(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=False)


def _payload(value: object) -> PlainData:
    # Native operations freeze nested evidence after decoding; use the same
    # plain-data owner as native wire output before the SDK serializes it.
    return to_plain_data(value)


def _result(value: object, text: str) -> CallToolResult:
    payload = _payload(value)
    return CallToolResult(
        content=[TextContent(text=_summary(payload, text))], structured_content=payload
    )


def _error(error: CoordinatorClientError) -> CallToolResult:
    detail = error.to_dict()
    return CallToolResult(
        content=[TextContent(text=f"{error.operation}: {error.code}")],
        structured_content=detail,
        is_error=True,
    )


def _summary(payload: object, text: str) -> str:
    """Add stable native identifiers, state, and retained report evidence to tool text."""
    values = _named_values(payload)
    details = [text.rstrip(".")]
    identifiers = [
        f"{key}={values[key]}"
        for key in ("coordinator_id", "operation_id", "admission_id", "queue_item_id")
        if isinstance(values.get(key), str)
    ]
    if identifiers:
        details.append("Identifiers: " + ", ".join(identifiers))
    for key in ("state", "kind", "preflight_status"):
        if isinstance(values.get(key), str):
            details.append(f"{key}: {values[key]}")
            break
    reference = values.get("report_ref")
    if isinstance(reference, Mapping) and isinstance(reference.get("uri"), str):
        details.append(f"Report evidence: {reference['uri']}")
    return ". ".join(details) + "."


def _named_values(payload: object) -> dict[str, object]:
    """Summarize native envelopes without interpreting project evidence as state."""
    if not isinstance(payload, Mapping):
        return {}
    keys = {
        "coordinator_id",
        "operation_id",
        "admission_id",
        "queue_item_id",
        "state",
        "kind",
        "preflight_status",
        "report_ref",
    }
    found = {key: value for key, value in payload.items() if key in keys}
    for wrapper in ("operation", "admission", "result", "status", "connection"):
        for key, value in _named_values(payload.get(wrapper)).items():
            found.setdefault(key, value)
    return found


class _Adapter:
    def __init__(self, client: Any) -> None:
        self._client = client
        self._capacity = _Capacity()
        self._closed = False

    async def _call(
        self,
        operation: str,
        action: Callable[[float], _Result],
        *,
        text: str,
        payload: dict[str, object],
        waiting: bool = False,
    ) -> CallToolResult:
        try:
            value = await self._capacity.call(action, waiting=waiting)
        except asyncio.CancelledError:
            raise
        except _CapacityClosed:
            return _error(control_error("unavailable", operation, payload))
        except _CapacityUnavailable:
            return _error(control_error("capacity_exhausted", operation, payload))
        except CoordinatorClientError as exc:
            return _error(exc)
        except (QueueError, TypeError, ValueError):
            return _error(control_error("invalid_request", operation, payload))
        except Exception:
            return _error(control_error("internal_error", operation, payload))
        return _result(value, text)

    def _native(
        self,
        operation: str,
        payload: dict[str, PlainData],
        expected_coordinator_id: str | None,
        deadline: float,
        *,
        negotiate: bool = True,
    ) -> Any:
        return self._client._native_call(
            operation,
            payload,
            expected_coordinator_id,
            deadline=deadline,
            negotiate=negotiate,
        )

    def _wait_native(
        self,
        operation: str,
        payload: dict[str, PlainData],
        timeout_seconds: float,
        expected_coordinator_id: str | None,
        deadline: float,
    ) -> Any:
        return self._client._wait_native(
            operation,
            payload,
            timeout_seconds,
            expected_coordinator_id,
            terminal_deadline=deadline,
        )

    def _inspect_run(
        self, run_uri: str, expected_coordinator_id: str | None, deadline: float
    ) -> Any:
        try:
            return decode_run_inspection_response(
                self._native(
                    "inspect_run",
                    {"run_uri": run_uri},
                    expected_coordinator_id,
                    deadline,
                )
            )
        except CoordinatorClientError:
            raise
        except (QueueError, TypeError, ValueError, KeyError, RecursionError) as exc:
            raise control_error(
                "invalid_response",
                "inspect_run",
                {"run_uri": run_uri},
                dispatched=True,
            ) from exc

    def server(self) -> MCPServer:
        @asynccontextmanager
        async def lifespan(_: Any):
            try:
                yield
            finally:
                self.close()

        server = MCPServer(name="loom", lifespan=lifespan)
        read = ToolAnnotations(read_only_hint=True)
        mutate = ToolAnnotations(read_only_hint=False)

        @server.tool(annotations=read)
        async def loom_status(
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Read the configured connection and current native coordinator status."""
            return await self._call(
                "status",
                lambda deadline: {
                    "connection": self._native(
                        "handshake", {}, expected_coordinator_id, deadline
                    ).to_dict(),
                    "status": self._native(
                        "status", {}, expected_coordinator_id, deadline, negotiate=False
                    ).to_dict(),
                },
                text="Observed connection and coordinator status.",
                payload={"expected_coordinator_id": expected_coordinator_id},
            )

        @server.tool(annotations=mutate)
        async def loom_prepare_run(
            operation_id: str,
            run_name: str,
            source: _PreparationSourceInput,
            config_path: str,
            preparation_profile: str,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Durably request native preparation from an authored source and profile."""
            request_data = {
                "operation_id": operation_id,
                "run_name": run_name,
                "source": cast(dict[str, object], source),
                "config_path": config_path,
                "preparation_profile": preparation_profile,
            }
            return await self._call(
                "prepare_run",
                lambda deadline: self._native(
                    "prepare_run",
                    {"request": PrepareRunRequest.from_dict(request_data).to_dict()},
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Preparation operation {operation_id} was observed.",
                payload={
                    **request_data,
                    "expected_coordinator_id": expected_coordinator_id,
                },
            )

        @server.tool(annotations=read)
        async def loom_get_operation(
            operation_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Read one native preparation operation and its retained evidence."""
            return await self._call(
                "operation",
                lambda deadline: self._native(
                    "operation",
                    {"operation_id": operation_id},
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Observed operation {operation_id}.",
                payload={
                    "operation_id": operation_id,
                    "expected_coordinator_id": expected_coordinator_id,
                },
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
                lambda deadline: self._wait_native(
                    "wait_operation",
                    {"operation_id": operation_id},
                    timeout_seconds,
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Bounded observation for operation {operation_id} completed.",
                payload={
                    "operation_id": operation_id,
                    "timeout": timeout_seconds,
                    "expected_coordinator_id": expected_coordinator_id,
                },
                waiting=True,
            )

        @server.tool(annotations=mutate)
        async def loom_cancel_preparation(
            operation_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Request native cancellation of one preparation operation."""
            return await self._call(
                "cancel_preparation",
                lambda deadline: self._native(
                    "cancel_preparation",
                    {"operation_id": operation_id},
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Cancellation request for preparation {operation_id} was observed.",
                payload={
                    "operation_id": operation_id,
                    "expected_coordinator_id": expected_coordinator_id,
                },
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
                lambda deadline: self._native(
                    "admissions",
                    {"limit": limit, "cursor": cursor},
                    expected_coordinator_id,
                    deadline,
                ),
                text="Observed native admissions.",
                payload={
                    "limit": limit,
                    "cursor": cursor,
                    "expected_coordinator_id": expected_coordinator_id,
                },
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
                    control_error(
                        "invalid_request",
                        "admission",
                        {
                            key: value
                            for key, value in {
                                "admission_id": admission_id,
                                "queue_item_id": queue_item_id,
                                "expected_coordinator_id": expected_coordinator_id,
                            }.items()
                            if value is not None
                        },
                    )
                )
            if queue_item_id is not None:
                return await self._call(
                    "admission_for_queue_item",
                    lambda deadline: self._native(
                        "admission",
                        {
                            "admission_id": self._native(
                                "admission_for_queue_item",
                                {"queue_item_id": queue_item_id},
                                expected_coordinator_id,
                                deadline,
                            ).admission_id
                        },
                        expected_coordinator_id,
                        deadline,
                    ),
                    text=f"Observed admission for queue item {queue_item_id}.",
                    payload={
                        "queue_item_id": queue_item_id,
                        "expected_coordinator_id": expected_coordinator_id,
                    },
                )
            assert admission_id is not None
            return await self._call(
                "admission",
                lambda deadline: self._native(
                    "admission",
                    {"admission_id": admission_id},
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Observed admission {admission_id}.",
                payload={
                    "admission_id": admission_id,
                    "expected_coordinator_id": expected_coordinator_id,
                },
            )

        @server.tool(annotations=read)
        async def loom_inspect_run(
            run_uri: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Inspect a run, returning either native diagnostic union member."""
            return await self._call(
                "inspect_run",
                lambda deadline: self._inspect_run(
                    run_uri, expected_coordinator_id, deadline
                ),
                text=f"Observed run inspection for {run_uri}.",
                payload={
                    "run_uri": run_uri,
                    "expected_coordinator_id": expected_coordinator_id,
                },
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
                lambda deadline: self._native(
                    "agents",
                    {"limit": limit, "cursor": cursor},
                    expected_coordinator_id,
                    deadline,
                ),
                text="Observed native agents.",
                payload={
                    "limit": limit,
                    "cursor": cursor,
                    "expected_coordinator_id": expected_coordinator_id,
                },
            )

        @server.tool(annotations=read)
        async def loom_get_agent(
            agent_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Read one native agent projection."""
            return await self._call(
                "agent",
                lambda deadline: self._native(
                    "agent", {"agent_id": agent_id}, expected_coordinator_id, deadline
                ),
                text=f"Observed agent {agent_id}.",
                payload={
                    "agent_id": agent_id,
                    "expected_coordinator_id": expected_coordinator_id,
                },
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
                lambda deadline: self._native(
                    "submit",
                    {
                        "request": LocalDaemonAdmissionRequest(
                            queue_item_id, run_uri
                        ).to_dict()
                    },
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Submission for queue item {queue_item_id} was observed.",
                payload={
                    "queue_item_id": queue_item_id,
                    "run_uri": run_uri,
                    "expected_coordinator_id": expected_coordinator_id,
                },
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
                lambda deadline: self._wait_native(
                    "wait_admission",
                    {
                        "admission_id": admission_id,
                        "expected_revision": expected_revision,
                    },
                    timeout_seconds,
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Bounded observation for admission {admission_id} completed.",
                payload={
                    "admission_id": admission_id,
                    "expected_revision": expected_revision,
                    "timeout": timeout_seconds,
                    "expected_coordinator_id": expected_coordinator_id,
                },
                waiting=True,
            )

        @server.tool(annotations=mutate)
        async def loom_cancel_job(
            queue_item_id: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Request native cancellation for one queue-item identifier."""
            return await self._call(
                "cancel",
                lambda deadline: self._native(
                    "cancel",
                    {"queue_item_id": queue_item_id},
                    expected_coordinator_id,
                    deadline,
                ),
                text=f"Cancellation request for queue item {queue_item_id} was observed.",
                payload={
                    "queue_item_id": queue_item_id,
                    "expected_coordinator_id": expected_coordinator_id,
                },
            )

        return server

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
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

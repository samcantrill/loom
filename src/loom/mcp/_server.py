"""MCP 2.x bindings for the native coordinator client.

This module is intentionally behind :mod:`loom.mcp`'s optional-import boundary.
The coordinator remains the sole owner of scheduling, durable state, guards and
native request deadlines.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, asynccontextmanager
import time
from pathlib import Path
from typing import Annotated, Any, TypeVar, cast

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import TypeAdapter, WithJsonSchema

from loom.coordinator import CoordinatorClientError, PrepareRunRequest, RunRequest
from loom import deployment as deployments
from loom._run import run as native_run
from loom.diagnostics.run_inspection import decode_run_inspection_response
from loom.errors import ValidationError
from loom.queue._coordinator_control import control_error
from loom.queue._coordinator_transport import (
    CLIENT_CAPACITY,
    CLIENT_WAIT_CAPACITY,
    REQUEST_BUDGET_SECONDS,
)
from loom.queue.errors import QueueError, QueueConflictError
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


_RunInput = dict[str, object]


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
    def __init__(self, deployment: str | Path) -> None:
        self._deployment = Path(deployment).resolve()
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
            if exc.operation == "connection":
                contextual = control_error(exc.code, operation, payload, boundary=exc.boundary)
                return _error(CoordinatorClientError(
                    exc.code, boundary=exc.boundary, operation=operation,
                    ids={**exc.ids, **contextual.ids}, evidence_refs=exc.evidence_refs,
                    mutation_outcome=contextual.mutation_outcome,
                ))
            return _error(exc)
        except QueueConflictError:
            return _error(control_error("conflict", operation, payload))
        except (QueueError, ValidationError, TypeError, ValueError):
            return _error(control_error("invalid_request", operation, payload))
        except Exception:
            return _error(control_error("internal_error", operation, payload))
        return _result(value, text)

    def _connect(self) -> AbstractContextManager[Any]:
        return deployments.connect_deployment(deployments.load_deployment(self._deployment))

    def _native(
        self,
        operation: str,
        payload: dict[str, PlainData],
        expected_coordinator_id: str | None,
        deadline: float,
        *,
        negotiate: bool = True,
    ) -> Any:
        with self._connect() as client:
            if operation == "cancel_run_operation":
                return client.cancel_run_operation(
                    cast(str, payload["operation_id"]),
                    expected_coordinator_id=expected_coordinator_id, deadline=deadline,
                )
            return client._native_call(
                operation, payload, expected_coordinator_id,
                deadline=deadline, negotiate=negotiate,
            )

    def _wait_native(
        self,
        operation: str,
        payload: dict[str, PlainData],
        timeout_seconds: float,
        expected_coordinator_id: str | None,
        deadline: float,
    ) -> Any:
        with self._connect() as client:
            return client._wait_native(
                operation, payload, timeout_seconds, expected_coordinator_id,
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
            overlays: list[str] | None = None,
            overrides: list[str] | None = None,
            run_options: dict[str, object] | None = None,
            context: dict[str, object] | None = None,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Durably request native preparation from an authored source and profile."""
            request_data = {
                "operation_id": operation_id,
                "run_name": run_name,
                "source": cast(dict[str, object], source),
                "config_path": config_path,
                "preparation_profile": preparation_profile,
                "overlays": [] if overlays is None else overlays,
                "overrides": [] if overrides is None else overrides,
                "run_options": {} if run_options is None else run_options,
                **({"context": context} if context is not None else {}),
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

        @server.tool(annotations=mutate)
        async def loom_run(
            request: _RunInput, expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Ensure configured services and accept durable preparation-to-admission.

            Request uses native preparation and queue_item_id fields; preparation
            includes operation_id, run_name, source, config_path, preparation_profile,
            ordered overlays/overrides and sparse run_options. Reconciled intent
            supplies mode, retry_policy and unresolved native target identities.
            Returning or disconnecting detaches; applied means admitted, not
            execution complete. Replay the exact native request after uncertainty.
            """
            return await self._call(
                "start_run",
                lambda deadline: native_run(
                    RunRequest.from_dict(request), deployment=self._deployment,
                    wait=False, _deadline=deadline,
                    expected_coordinator_id=expected_coordinator_id,
                ),
                text="Observed native run acceptance.",
                payload={"request": request, "expected_coordinator_id": expected_coordinator_id},
            )

        @server.tool(annotations=mutate)
        async def loom_cancel_run_operation(
            operation_id: str, expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Request native run cancellation; wait on the returned control ID."""
            return await self._call(
                "cancel_run_operation",
                lambda deadline: self._native(
                    "cancel_run_operation", {"operation_id": operation_id},
                    expected_coordinator_id, deadline,
                ),
                text=f"Observed cancellation control for run operation {operation_id}.",
                payload={"operation_id": operation_id, "expected_coordinator_id": expected_coordinator_id},
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
        async def loom_search_runs(query: dict[str, Any], expected_coordinator_id: str | None = None) -> CallToolResult:
            """Search explicit run scope; retain coverage warnings and live continuation."""
            return await self._call("search_runs", lambda deadline: self._native("search_runs", {"query": query}, expected_coordinator_id, deadline), text="Observed run search page.", payload={"query": query})

        @server.tool(annotations=read)
        async def loom_search_submissions(query: dict[str, Any], expected_coordinator_id: str | None = None) -> CallToolResult:
            """Search all original submissions, including failed/unbound requests."""
            return await self._call("search_submissions", lambda deadline: self._native("search_submissions", {"query": query}, expected_coordinator_id, deadline), text="Observed submission search page.", payload={"query": query})

        @server.tool(annotations=read)
        async def loom_search_jobs(query: dict[str, Any], expected_coordinator_id: str | None = None) -> CallToolResult:
            """Search native admission views with their existing associations."""
            return await self._call("search_jobs", lambda deadline: self._native("search_jobs", {"query": query}, expected_coordinator_id, deadline), text="Observed job search page.", payload={"query": query})

        @server.tool(annotations=read)
        async def loom_query_fields(entity: str = "runs", expected_coordinator_id: str | None = None) -> CallToolResult:
            """Discover native query fields, operators and bounds."""
            return await self._call("query_fields", lambda deadline: self._native("query_fields", {"entity": entity}, expected_coordinator_id, deadline), text="Read query capabilities.", payload={"entity": entity})

        @server.tool(annotations=read)
        async def loom_tag_keys(scope: dict[str, Any], limit: int = 50, cursor: str | None = None, expected_coordinator_id: str | None = None) -> CallToolResult:
            """Discover bounded distinct current tag keys without registration."""
            payload: dict[str, PlainData] = {"scope": scope, "limit": limit, "cursor": cursor}
            return await self._call("tag_keys", lambda deadline: self._native("tag_keys", payload, expected_coordinator_id, deadline), text="Observed tag keys.", payload=dict(payload))

        @server.tool(annotations=read)
        async def loom_tag_values(scope: dict[str, Any], key: str, limit: int = 50, cursor: str | None = None, expected_coordinator_id: str | None = None) -> CallToolResult:
            """Discover bounded distinct values of one literal tag key."""
            payload: dict[str, PlainData] = {"scope": scope, "key": key, "limit": limit, "cursor": cursor}
            return await self._call("tag_values", lambda deadline: self._native("tag_values", payload, expected_coordinator_id, deadline), text="Observed tag values.", payload=dict(payload))

        @server.tool(annotations=read)
        async def loom_run_context(
            run_uri: str, expected_coordinator_id: str | None = None
        ) -> CallToolResult:
            """Read original submission intent, current annotations and native evidence."""
            return await self._call(
                "get_run_context",
                lambda deadline: self._native("get_run_context", {"run_uri": run_uri}, expected_coordinator_id, deadline),
                text=f"Observed run context for {run_uri}.",
                payload={"run_uri": run_uri, "expected_coordinator_id": expected_coordinator_id},
            )

        @server.tool(annotations=mutate)
        async def loom_patch_run_annotations(
            run_uri: str, mutation_id: str, patch: dict[str, Any],
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Patch annotations with expected_revision; replay uncertain writes with the same ID and patch."""
            payload: dict[str, PlainData] = {"run_uri": run_uri, "mutation_id": mutation_id, "patch": patch}
            return await self._call("patch_run_annotations",
                lambda deadline: self._native("patch_run_annotations", payload, expected_coordinator_id, deadline),
                text=f"Patched annotations for {run_uri}.", payload=dict(payload))

        @server.tool(annotations=mutate)
        async def loom_append_run_note(
            run_uri: str, mutation_id: str, text: str,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Append a native attributed note. Corrections are new notes; IDs are run-scoped."""
            payload: dict[str, PlainData] = {"run_uri": run_uri, "mutation_id": mutation_id, "text": text}
            return await self._call("append_run_note",
                lambda deadline: self._native("append_run_note", payload, expected_coordinator_id, deadline),
                text=f"Appended note for {run_uri}.", payload=dict(payload))

        @server.tool(annotations=read)
        async def loom_list_run_notes(
            run_uri: str, limit: int = 50, cursor: str | None = None,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Read bounded notes in native time/ID order, retaining unknown legacy attribution."""
            payload: dict[str, PlainData] = {"run_uri": run_uri, "limit": limit, "cursor": cursor}
            return await self._call("list_run_notes",
                lambda deadline: self._native("list_run_notes", payload, expected_coordinator_id, deadline),
                text=f"Read notes for {run_uri}.", payload=dict(payload))

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
            retry_failed_revision: int | None = None,
            expected_coordinator_id: str | None = None,
        ) -> CallToolResult:
            """Submit a prepared run with its stable native queue-item identifier."""
            return await self._call(
                "submit",
                lambda deadline: self._native(
                    "submit",
                    {
                        "request": LocalDaemonAdmissionRequest(
                            queue_item_id, run_uri, retry_failed_revision
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


def create_server(*, deployment: str | Path) -> MCPServer:
    """Register native coordinator tools without loading or contacting a deployment."""
    return _Adapter(deployment).server()


def run_server(*, deployment: str | Path) -> None:
    """Run stdio and release only local adapter/client resources on shutdown."""
    adapter = _Adapter(deployment)
    try:
        adapter.server().run(transport="stdio")
    finally:
        adapter.close()

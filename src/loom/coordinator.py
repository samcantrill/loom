"""Direct native control of one Loom coordinator over Unix or authenticated HTTPS.

Queue owns control requests and durable admission state. This integration facade
adds connection selection and the diagnostic result union above that boundary.
"""

from __future__ import annotations

from pathlib import Path

from loom.diagnostics.run_inspection import (
    RunInspectionResponse,
    decode_run_inspection_response,
)
from loom.queue._coordinator_client import NativeCoordinatorClient
from loom.queue._coordinator_control import (
    CoordinatorClientError,
    CoordinatorConnectionDescription,
    control_error,
    optional_id,
)
from loom.queue._coordinator_transport import (
    HttpsControlTransport,
    UnixControlTransport,
)
from loom.queue.errors import QueueError


class CoordinatorClient(NativeCoordinatorClient):
    """Lazy coordinator client; close releases I/O without cancelling submitted work."""

    @classmethod
    def from_unix_socket(
        cls, path: str | Path, *, expected_coordinator_id: str | None = None
    ) -> CoordinatorClient:
        """Select an owner-only local socket without starting or contacting a service."""
        return cls(
            UnixControlTransport(path), expected_coordinator_id=expected_coordinator_id
        )

    @classmethod
    def from_connection_file(
        cls, path: str | Path, *, expected_coordinator_id: str | None = None
    ) -> CoordinatorClient:
        """Load protected HTTPS settings; certificate use and negotiation are lazy."""
        from loom.queue.deployment import load_coordinator_connection_file

        config = load_coordinator_connection_file(path)
        try:
            selected = optional_id(expected_coordinator_id)
        except ValueError as exc:
            raise control_error("invalid_request", "connection", {}) from exc
        configured = config.expected_coordinator_id
        if configured is not None and selected is not None and configured != selected:
            raise control_error(
                "conflict",
                "connection",
                {},
                ids={
                    "configured_expected_coordinator_id": configured,
                    "expected_coordinator_id": selected,
                },
            )
        return cls(
            HttpsControlTransport(
                config.url,
                config.server_ca_path,
                config.certificate_path,
                config.private_key_path,
            ),
            expected_coordinator_id=configured if configured is not None else selected,
        )

    def inspect_run(
        self, run_uri: str, *, expected_coordinator_id: str | None = None
    ) -> RunInspectionResponse:
        """Read a managed run's native inspection success or diagnostic failure union."""
        value = self._native_call(
            "inspect_run", {"run_uri": run_uri}, expected_coordinator_id
        )
        try:
            return decode_run_inspection_response(value)
        except (QueueError, ValueError, TypeError, KeyError, RecursionError) as exc:
            raise control_error(
                "invalid_response", "inspect_run", {"run_uri": run_uri}, dispatched=True
            ) from exc


__all__ = [
    "CoordinatorClient",
    "CoordinatorClientError",
    "CoordinatorConnectionDescription",
]

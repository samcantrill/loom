"""Foreground role compositions used by explicit CLI and managed availability."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

from loom.diagnostics.run_inspection import projection_callable
from loom.preparation import CoordinatorPreparation
from loom.pipeline.stores import LocalRunStore
from loom.queue import LocalDaemon, LocalDaemonSocketServer
from loom.queue.local_daemon import DaemonStatus
from loom.queue.agent_session_transport import LocalDaemonAgentHttpServer
from loom.queue.deployment import (
    CoordinatorServiceConfig,
    load_coordinator_service_config,
)
from loom.queue.errors import QueueError, QueueServiceError
from loom.queue._service_lifetime import record_process, retained_lifetime


def serve_coordinator(
    service: CoordinatorServiceConfig,
    *,
    stop: Event,
    lifetime: str | None = None,
    ready: Callable[[DaemonStatus, int | None], None] | None = None,
) -> None:
    """Serve reconciled endpoints until explicit stop or authorized run retirement."""
    config = service.daemon
    active_service = service
    pending_service = None
    agent_server = None

    def load_replacement():  # type: ignore[no-untyped-def]
        nonlocal pending_service
        pending_service = load_coordinator_service_config(
            service.source_path,
            env_file=service.environment_path,
            current=active_service,
        )
        return pending_service.daemon

    def prepare_role_reload(replacement):  # type: ignore[no-untyped-def]
        nonlocal pending_service
        prepared = pending_service
        if prepared is None or prepared.daemon is not replacement:
            raise QueueServiceError("trusted coordinator role snapshot is unavailable")
        if agent_server is None:
            if prepared.agent_server is not None:
                raise QueueServiceError("agent TLS listener cannot be added by reload")

            def install_absent() -> None:
                nonlocal active_service, pending_service
                active_service = prepared
                pending_service = None

            return install_absent
        if prepared.agent_server is None:
            raise QueueServiceError("agent TLS listener cannot be removed by reload")
        install_server = agent_server.prepare_reload(prepared.agent_server)

        def install() -> None:
            nonlocal active_service, pending_service
            install_server()
            active_service = prepared
            pending_service = None

        return install

    daemon = LocalDaemon(
        config,
        trusted_scheduling_loader=load_replacement,
        prepare_role_reload=prepare_role_reload,
        preparation=CoordinatorPreparation(service),
    )
    server = LocalDaemonSocketServer(
        daemon,
        config.endpoint,
        inspect_run=projection_callable(
            run_store=LocalRunStore(config.run_store_root), daemon=daemon
        ),
    )
    agent_server = (
        None
        if service.agent_server is None
        else LocalDaemonAgentHttpServer(
            daemon,
            service.agent_server,
            inspect_run=projection_callable(
                run_store=LocalRunStore(config.run_store_root), daemon=daemon
            ),
        )
    )
    try:
        status = daemon.start()
        lifetime = retained_lifetime(config.coordinator_root, lifetime)
        record_process(config.coordinator_root, stopped=False)
        server.start()
        if agent_server is not None:
            agent_server.start()
        if ready is not None:
            ready(status, None if agent_server is None else agent_server.port)
        while not stop.wait(0.1):
            if lifetime == "run":
                try:
                    if daemon._lifetime.retire_if_idle():
                        assert daemon._execution is not None
                        daemon._execution.shutdown_clean()
                        daemon._lifetime.clean_shutdown_verified = True
                        break
                except QueueError as exc:
                    daemon._lifetime.cleanup_blocked = str(exc)
                    # Unknown work/containment never authorizes a clean stop.
                    continue
    finally:
        if agent_server is not None:
            agent_server.stop()
        server.stop()
        daemon.stop()
        if daemon._lifetime.clean_shutdown_verified:
            record_process(config.coordinator_root, stopped=True)


def main() -> None:
    import sys
    from loom.deployment import load_deployment
    from loom.queue.deployment import (
        load_outbound_agent_service_config,
        run_outbound_agent_service,
    )

    selection = load_deployment(Path(sys.argv[1]))
    role = sys.argv[2]
    config = getattr(selection, role)
    if config is None:
        raise QueueServiceError("role is not configured for local startup")
    stop = Event()
    if role == "coordinator":
        serve_coordinator(
            load_coordinator_service_config(config.config, env_file=config.env_file),
            stop=stop,
            lifetime=config.lifetime,
        )
    elif role == "agent":
        import json
        from loom.queue.deployment import load_coordinator_connection_file

        if selection.connection is not None:
            expected = load_coordinator_connection_file(
                selection.connection
            ).expected_coordinator_id
        else:
            assert selection.binding is not None
            expected = json.loads(selection.binding.read_text())["roles"][
                "coordinator"
            ]["ids"]["coordinator"]
        agent = load_outbound_agent_service_config(
            config.config, env_file=config.env_file
        )
        run_outbound_agent_service(
            agent, stop=stop, lifetime=config.lifetime, expected_coordinator_id=expected
        )
    else:
        raise QueueServiceError("unsupported local role")


if __name__ == "__main__":
    main()

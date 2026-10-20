"""Owned remote agent process for opt-in cross-host acceptance."""

from pathlib import Path
import json
import sqlite3
import sys
from threading import Event, Thread

from loom.queue._agent_process_supervisor import _launch_from_value
from loom.queue.agent_session_transport import LocalDaemonAgentHttpClient
from loom.queue.deployment import load_outbound_agent_service_config, run_outbound_agent_service


def main():
    service = load_outbound_agent_service_config(Path(sys.argv[1]))
    stop_file = Path(sys.argv[2])
    stop = Event()
    LocalDaemonAgentHttpClient.initialize_agent_root(service.client)

    def watch():
        while not stop.wait(0.2):
            if stop_file.exists():
                stop.set()

    Thread(target=watch, daemon=True).start()
    try:
        run_outbound_agent_service(service, stop=stop)
    finally:
        stop.set()
        client = LocalDaemonAgentHttpClient(service.client)
        try:
            assert service.client.agent_root is not None
            if client._supervisor is not None:
                with sqlite3.connect(service.client.agent_root / "supervisor/supervisor.sqlite") as conn:
                    launches = conn.execute("SELECT launch_json FROM launches").fetchall()
                for (raw,) in launches:
                    client._supervisor.contain(_launch_from_value(json.loads(raw)))
                client._supervisor.shutdown_for_test()
        finally:
            client.close()


if __name__ == "__main__":
    main()

"""Cross-suite cleanup for test-owned detached supervisor services."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
import json
from pathlib import Path
import sqlite3

import pytest

from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
    _launch_from_value,
)


@pytest.fixture(autouse=True)
def _cleanup_test_owned_supervisors(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Register every initialized/started test root and stop it at teardown."""

    roots: dict[Path, SupervisorLaunchConfiguration] = {}
    initialize = AgentProcessSupervisorService.initialize_process_free.__func__
    start = AgentProcessSupervisorService._start

    def tracked_initialize(
        cls: type[AgentProcessSupervisorService],
        agent_root: Path,
        *,
        configuration: SupervisorLaunchConfiguration,
    ) -> None:
        initialize(cls, agent_root, configuration=configuration)
        roots[Path(agent_root).resolve()] = configuration

    def tracked_start(
        agent_root: Path, configuration: SupervisorLaunchConfiguration
    ) -> AgentProcessSupervisorClient:
        roots[Path(agent_root).resolve()] = configuration
        return start(agent_root, configuration)

    monkeypatch.setattr(
        AgentProcessSupervisorService,
        "initialize_process_free",
        classmethod(tracked_initialize),
    )
    monkeypatch.setattr(
        AgentProcessSupervisorService, "_start", staticmethod(tracked_start)
    )
    yield

    for agent_root, configuration in reversed(tuple(roots.items())):
        with suppress(Exception):
            client = AgentProcessSupervisorClient(agent_root, configuration)
            database = agent_root / "supervisor" / "supervisor.sqlite"
            with sqlite3.connect(database) as conn:
                launches = tuple(
                    str(row[0])
                    for row in conn.execute(
                        "SELECT launch_json FROM launches "
                        "WHERE state NOT IN ('exited', 'contained')"
                    )
                )
            for encoded in launches:
                with suppress(Exception):
                    client.contain(_launch_from_value(json.loads(encoded)))
            client.shutdown_for_test()

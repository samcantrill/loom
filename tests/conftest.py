"""Cross-suite cleanup for test-owned detached supervisor services."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from loom.queue._agent_process_supervisor import (
    AgentProcessSupervisorClient,
    AgentProcessSupervisorService,
    SupervisorLaunchConfiguration,
    _launch_from_value,
)


@pytest.fixture
def download_root(tmp_path: Path) -> Iterator[Path]:
    """Use the selected atomic-publication filesystem for download destinations."""
    configured = os.environ.get("LOOM_TEST_ARTIFACT_DOWNLOAD_ROOT")
    if configured is None:
        yield tmp_path
        return
    root = Path(configured)
    assert root.is_absolute() and root.is_dir(), "download test root must already exist"
    with TemporaryDirectory(prefix="loom-fetch-", dir=root) as directory:
        yield Path(directory)


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
        final_agent_root: Path | None = None,
    ) -> None:
        initialize(
            cls, agent_root, configuration=configuration, final_agent_root=final_agent_root
        )
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

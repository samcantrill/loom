"""Shared helpers for runnable example scripts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import io
import json
from pathlib import Path
import socket
from typing import Any
from urllib.parse import urlsplit

from loom.cli.main import main as loom_main
from loom.pipeline.stores import (
    AuthorityConfig,
    authority_config_from_mapping,
    authority_config_to_cli_args,
)


def run_cli_json(
    argv: list[str],
    *,
    expected: int = 0,
    allow_stderr: bool = False,
) -> dict[str, Any]:
    """Run a Loom CLI command and parse its JSON output."""

    stdout = io.StringIO()
    stderr = io.StringIO()
    code = loom_main(argv, stdout=stdout, stderr=stderr)
    if code != expected:
        raise RuntimeError(
            f"loom {' '.join(argv)} exited {code}; stdout={stdout.getvalue()!r}; "
            f"stderr={stderr.getvalue()!r}"
        )
    if stderr.getvalue() and not allow_stderr:
        raise RuntimeError(f"unexpected stderr from loom {' '.join(argv)}")
    output = stdout.getvalue()
    if not output:
        return {}
    return require_mapping(json.loads(output))


@dataclass(slots=True)
class ExampleAuthoritySession:
    """Public-CLI authority lifecycle facts for an example run."""

    state_dir: Path
    workspace_root: Path
    workspace_id: str
    authority_config: AuthorityConfig
    _start_result: dict[str, Any]
    _stopped: bool = False

    @property
    def start_result(self) -> Mapping[str, Any]:
        return dict(self._start_result)

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def endpoint(self) -> str:
        endpoint = self._start_result.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise RuntimeError("authority start result did not include an endpoint")
        return endpoint

    @property
    def generation(self) -> str:
        generation = self._start_result.get("service_generation")
        if not isinstance(generation, str) or not generation:
            raise RuntimeError("authority start result did not include a generation")
        return generation

    @property
    def authority_args(self) -> tuple[str, ...]:
        return authority_config_to_cli_args(self.authority_config)

    def status(self) -> dict[str, Any]:
        payload = run_cli_json(
            [
                "authority",
                "status",
                "--workspace-root",
                str(self.workspace_root),
                "--format",
                "json",
            ]
        )
        return require_mapping(payload["result"])

    def doctor(self) -> dict[str, Any]:
        payload = run_cli_json(
            [
                "authority",
                "doctor",
                "--workspace-root",
                str(self.workspace_root),
                "--format",
                "json",
            ]
        )
        return require_mapping(payload["result"])

    def restart(self) -> dict[str, Any]:
        parsed = urlsplit(self.endpoint)
        port = parsed.port
        if port is None:
            raise RuntimeError("authority endpoint did not include a port")
        host = parsed.hostname
        if host is None:
            raise RuntimeError("authority endpoint did not include a host")
        payload = run_cli_json(
            [
                "authority",
                "restart",
                "--state-dir",
                str(self.state_dir),
                "--workspace-root",
                str(self.workspace_root),
                "--workspace-id",
                self.workspace_id,
                "--host",
                host,
                "--port",
                str(port),
                "--format",
                "json",
            ]
        )
        self._start_result = require_mapping(payload["result"])
        self.authority_config = _authority_config(
            endpoint=self.endpoint,
            workspace_id=self.workspace_id,
        )
        return self._start_result

    def stop(self) -> dict[str, Any]:
        if self._stopped:
            return {}
        payload = run_cli_json(
            [
                "authority",
                "stop",
                "--state-dir",
                str(self.state_dir),
                "--workspace-root",
                str(self.workspace_root),
                "--format",
                "json",
            ]
        )
        self._stopped = True
        return require_mapping(payload["result"])


def start_authority_session(
    output_root: Path,
    *,
    workspace_id: str = "workspace-a",
) -> ExampleAuthoritySession:
    """Start an explicit local authority supervisor for an example."""

    output_root.mkdir(parents=True, exist_ok=True)
    state_dir = output_root / "authority-state"
    workspace_root = output_root / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    payload = run_cli_json(
        [
            "authority",
            "start",
            "--state-dir",
            str(state_dir),
            "--workspace-root",
            str(workspace_root),
            "--workspace-id",
            workspace_id,
            "--port",
            str(port),
            "--format",
            "json",
        ]
    )
    result = require_mapping(payload["result"])
    authority_config = _authority_config(
        endpoint=_required_string(result, "endpoint"),
        workspace_id=workspace_id,
    )
    return ExampleAuthoritySession(
        state_dir=state_dir,
        workspace_root=workspace_root,
        workspace_id=workspace_id,
        authority_config=authority_config,
        _start_result=result,
    )


@contextmanager
def started_authority_session(
    output_root: Path,
    *,
    workspace_id: str = "workspace-a",
) -> Iterator[ExampleAuthoritySession]:
    """Yield a started authority session and stop it on exit."""

    session = start_authority_session(output_root, workspace_id=workspace_id)
    try:
        yield session
    finally:
        session.stop()


def require_mapping(value: object) -> dict[str, Any]:
    """Require a mutable JSON-like mapping."""

    if not isinstance(value, dict):
        raise RuntimeError("expected a mapping")
    return value


def _authority_config(*, endpoint: str, workspace_id: str) -> AuthorityConfig:
    return authority_config_from_mapping(
        backend_kind="managed_service",
        deployment_profile="managed_service",
        endpoint=endpoint,
        workspace_id=workspace_id,
    )


def _required_string(mapping: Mapping[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"expected a non-empty string for {key}")
    return value


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

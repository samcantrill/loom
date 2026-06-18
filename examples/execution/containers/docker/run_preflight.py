"""Inspect selected-Docker preflight diagnostics for the example config."""

from __future__ import annotations

# ruff: noqa: E402

import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import run_cli_json
from fake_docker import activate_fake_docker
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent


def main() -> None:
    _configure_import_path()
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_root.mkdir(parents=True, exist_ok=True)
    activate_fake_docker(output_root)
    config_path = HERE / "pipeline.yaml"
    run_uri = path_to_run_uri(run_root / f"docker-preflight-{uuid4().hex[:8]}")

    passing = _run_cli(
        [
            "preflight",
            str(config_path),
            "--run-uri",
            run_uri,
            "--check",
            "executor",
            "--check",
            "filesystem",
            "--check",
            "resources",
            "--format",
            "json",
        ]
    )
    old_path = os.environ.get("PATH", "")
    missing_bin = output_root / "missing-docker-bin"
    missing_bin.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(missing_bin)
    try:
        failing = _run_cli(
            [
                "preflight",
                str(config_path),
                "--check",
                "executor",
                "--format",
                "json",
            ],
            expected=4,
        )
    finally:
        os.environ["PATH"] = old_path

    pass_checks = _checks_by_id(passing)
    fail_checks = _checks_by_id(failing)
    print(f"preflight_pass_status: {passing['result']['status']}")
    print(
        "executor_docker_command: "
        f"{pass_checks['executor.docker.command']['status']}"
    )
    print(
        "filesystem_docker_artifact_root_visible: "
        f"{pass_checks['filesystem.docker.artifact_root_visible']['status']}"
    )
    print(
        "missing_docker_command: "
        f"{fail_checks['executor.docker.command']['status']}"
    )


def _configure_import_path() -> None:
    sys.path.insert(0, str(HERE))
    existing = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = (
        str(HERE) if not existing else str(HERE) + os.pathsep + existing
    )


def _checks_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(check["check_id"]): check
        for check in payload["result"]["checks"]
        if isinstance(check, dict)
    }


def _run_cli(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    return run_cli_json(argv, expected=expected)


if __name__ == "__main__":
    main()

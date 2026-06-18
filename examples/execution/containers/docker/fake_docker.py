"""Daemon-free Docker CLI helper for the Docker execution examples."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


FAKE_DOCKER_SCRIPT = r"""#!__PYTHON__
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


NO_VALUE_FLAGS = {"--rm", "--init", "--tty", "-i", "-t"}
VALUE_FLAGS = {
    "--cpus",
    "--env",
    "-e",
    "--hostname",
    "--memory",
    "--mount",
    "--network",
    "--platform",
    "--user",
    "--workdir",
}


def main(argv: list[str]) -> int:
    if not argv:
        print("fake docker: expected an operation", file=sys.stderr)
        return 2
    if argv == ["--version"]:
        print("Docker version 27.0.0, build loom-example")
        return 0
    if len(argv) >= 3 and argv[:2] == ["image", "inspect"]:
        _log({"operation": "image.inspect", "image": argv[2]})
        print(json.dumps([{"Id": "sha256:loom-example", "RepoDigests": []}]))
        return 0
    if argv[0] == "run":
        return _run(argv[1:])
    print(f"fake docker: unsupported operation {argv[0]!r}", file=sys.stderr)
    return 2


def _run(args: list[str]) -> int:
    env = os.environ.copy()
    env_names: set[str] = set()
    option_names: list[str] = []
    image: str | None = None
    command: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token == "--":
            index += 1
            break
        if not token.startswith("-"):
            image = token
            command = args[index + 1 :]
            break
        if token in NO_VALUE_FLAGS:
            option_names.append(token)
            index += 1
            continue
        if token in VALUE_FLAGS:
            if index + 1 >= len(args):
                print(f"fake docker: missing value for {token}", file=sys.stderr)
                return 2
            value = args[index + 1]
            option_names.append(token)
            if token in {"--env", "-e"}:
                _apply_env(value, env, env_names)
            index += 2
            continue
        if token.startswith("--env="):
            option_names.append("--env")
            _apply_env(token.split("=", 1)[1], env, env_names)
            index += 1
            continue
        if "=" in token and token.startswith("--"):
            option_names.append(token.split("=", 1)[0])
            index += 1
            continue
        option_names.append(token)
        index += 1
    if image is None and index < len(args):
        image = args[index]
        command = args[index + 1 :]
    if image is None:
        print("fake docker: missing image", file=sys.stderr)
        return 2
    _log(
        {
            "operation": "run",
            "image": image,
            "option_names": option_names,
            "env_names": sorted(env_names),
            "command": command,
        }
    )
    if not command:
        return 0
    completed = subprocess.run(command, env=env, check=False)
    return int(completed.returncode)


def _apply_env(value: str, env: dict[str, str], env_names: set[str]) -> None:
    if "=" in value:
        name, resolved = value.split("=", 1)
        env[name] = resolved
        env_names.add(name)
        return
    env_names.add(value)


def _log(record: dict[str, object]) -> None:
    target = os.environ.get("LOOM_FAKE_DOCKER_LOG")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
"""


@dataclass(frozen=True, slots=True)
class FakeDockerEnvironment:
    """Paths used by the example fake Docker command."""

    bin_dir: Path
    command_path: Path
    log_path: Path


def activate_fake_docker(output_root: Path) -> FakeDockerEnvironment:
    """Install the fake Docker command and prepend it to ``PATH``."""

    bin_dir = output_root / "fake-docker-bin"
    log_path = output_root / "fake-docker.jsonl"
    if log_path.exists():
        log_path.unlink()
    command_path = install_fake_docker(bin_dir)
    existing_path = os.environ.get("PATH")
    os.environ["PATH"] = (
        str(bin_dir) if not existing_path else str(bin_dir) + os.pathsep + existing_path
    )
    os.environ["LOOM_FAKE_DOCKER_LOG"] = str(log_path)
    return FakeDockerEnvironment(
        bin_dir=bin_dir,
        command_path=command_path,
        log_path=log_path,
    )


def install_fake_docker(bin_dir: Path) -> Path:
    """Write a small ``docker`` executable that runs the worker command locally."""

    bin_dir.mkdir(parents=True, exist_ok=True)
    command_path = bin_dir / "docker"
    command_path.write_text(
        FAKE_DOCKER_SCRIPT.replace("__PYTHON__", sys.executable),
        encoding="utf-8",
    )
    command_path.chmod(command_path.stat().st_mode | stat.S_IXUSR)
    return command_path


def read_fake_docker_log(path: Path) -> list[dict[str, Any]]:
    """Read fake Docker JSON lines written by the helper command."""

    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        loaded = json.loads(line)
        if isinstance(loaded, dict):
            records.append(loaded)
    return records

"""Local fake ``apptainer`` command for the example's hermetic e2e path."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


FAKE_APPTAINER_SCRIPT = r'''#!__PYTHON__
import json
import os
from pathlib import Path
import subprocess
import sys

NO_VALUE_FLAGS = {"--cleanenv", "--nv", "--rocm", "--fakeroot", "--no-home"}
VALUE_FLAGS = {"--bind", "--env", "--pwd"}

def log(record):
    target = os.environ.get("LOOM_FAKE_APPTAINER_LOG")
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

def main(argv):
    if argv == ["--version"]:
        print("apptainer version 1.3.0-looom-example")
        return 0
    if not argv or argv[0] != "exec":
        print("fake apptainer: expected exec", file=sys.stderr)
        return 2
    env = os.environ.copy()
    flags = []
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in NO_VALUE_FLAGS:
            flags.append(token)
            index += 1
            continue
        if token in VALUE_FLAGS:
            if index + 1 >= len(argv):
                return 2
            value = argv[index + 1]
            flags.append(token)
            if token == "--env" and "=" in value:
                key, resolved = value.split("=", 1)
                env[key] = resolved
            index += 2
            continue
        image = token
        command = argv[index + 1:]
        log({"operation": "exec", "image": image, "flags": flags, "command": command})
        if not command:
            return 0
        return subprocess.run(command, env=env, check=False).returncode
    return 2

raise SystemExit(main(sys.argv[1:]))
'''


@dataclass(frozen=True, slots=True)
class FakeApptainerEnvironment:
    command_path: Path
    log_path: Path


def activate_fake_apptainer(output_root: Path) -> FakeApptainerEnvironment:
    bin_dir = output_root / "fake-apptainer-bin"
    log_path = output_root / "fake-apptainer.jsonl"
    if log_path.exists():
        log_path.unlink()
    bin_dir.mkdir(parents=True, exist_ok=True)
    command_path = bin_dir / "apptainer"
    command_path.write_text(
        FAKE_APPTAINER_SCRIPT.replace("__PYTHON__", sys.executable), encoding="utf-8"
    )
    command_path.chmod(command_path.stat().st_mode | stat.S_IXUSR)
    existing_path = os.environ.get("PATH")
    os.environ["PATH"] = str(bin_dir) if not existing_path else str(bin_dir) + os.pathsep + existing_path
    os.environ["LOOM_FAKE_APPTAINER_LOG"] = str(log_path)
    return FakeApptainerEnvironment(command_path=command_path, log_path=log_path)


def read_fake_apptainer_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [record for line in path.read_text(encoding="utf-8").splitlines() if isinstance(record := json.loads(line), dict)]

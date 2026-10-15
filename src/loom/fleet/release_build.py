"""Build a native service bundle from a clean, locked Loom source checkout."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

from loom.queue.errors import QueueConfigError


PIP_VERSION = "25.3"


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _git(source: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(source), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise QueueConfigError(
            "service source must be an accessible Git checkout"
        ) from exc


def _source(source: Path) -> dict[str, str]:
    if _git(source, "status", "--porcelain", "--untracked-files=normal"):
        raise QueueConfigError(
            "service source must be clean, including untracked files"
        )
    metadata = tomllib.loads((source / "pyproject.toml").read_text())
    if metadata["project"]["name"] != "loom":
        raise QueueConfigError("service source must select the Loom project")
    return {
        "commit": _git(source, "rev-parse", "HEAD"),
        "tree": _git(source, "rev-parse", "HEAD^{tree}"),
        "lock_sha256": _sha(source / "uv.lock"),
        "source_date_epoch": _git(source, "show", "-s", "--format=%ct", "HEAD"),
    }


def _run(command: list[str], *, source: Path, log: Path, env: dict[str, str]) -> None:
    try:
        with log.open("ab") as stream:
            subprocess.run(
                command, cwd=source, env=env, stdout=stream, stderr=stream, check=True
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise QueueConfigError(
            f"release build failed; inspect protected log {log}"
        ) from exc


def _seal_wheels(output: Path) -> dict[str, Any]:
    from packaging.utils import parse_wheel_filename

    wheels = output / "wheels"
    requirements, manifest = [], []
    selected = set()
    for path in sorted(wheels.glob("*.whl")):
        name, version, _, _ = parse_wheel_filename(path.name)
        if name in selected:
            raise QueueConfigError(
                "release wheelhouse contains competing wheels for one package"
            )
        selected.add(name)
        digest = _sha(path)
        requirement = f"{name}{'[fleet]' if name == 'loom' else ''}=={version}"
        requirements.append(f"{requirement} --hash=sha256:{digest}")
        manifest.append(f"{digest}  {path.name}")
    if "loom" not in selected:
        raise QueueConfigError("release build did not produce a Loom wheel")
    (output / "requirements.txt").write_text("\n".join(requirements) + "\n")
    (output / "wheels.sha256").write_text("\n".join(manifest) + "\n")
    return {
        "requirements": {
            "path": "requirements.txt",
            "sha256": _sha(output / "requirements.txt"),
        },
        "wheelhouse": {
            "path": "wheels",
            "manifest": "wheels.sha256",
            "sha256": _sha(output / "wheels.sha256"),
        },
    }


def build_release(
    source: str | Path, output: str | Path, *, release_id: str | None = None
) -> dict[str, Any]:
    """Build and offline-install a service bundle for this Python 3.12 host.

    The clean Git source and its unchanged uv lock select all runtime
    dependencies. VCS dependencies are built at their exported locked revisions;
    the published service lock contains only exact versions and wheel hashes.
    Network access may be used to obtain build dependencies. Installation proof
    uses a new environment with networking and dependency resolution disabled.

    Output must not exist. Failed builds retain their protected log and partial
    artifacts without a successful build receipt. Existing releases are never
    modified. Matching input revisions establish source identity, not a promise
    of byte-identical wheels across different packaging toolchains/platforms.
    """
    from loom.fleet.releases import verify_release

    if sys.version_info[:2] != (3, 12):
        raise QueueConfigError("service release construction requires Python 3.12")
    source, output = Path(source).resolve(), Path(output).absolute()
    identity = _source(source)
    if output.exists() or output.is_symlink():
        raise QueueConfigError(
            "release output already exists; select a new destination"
        )
    if not output.parent.is_dir():
        raise QueueConfigError("release output parent must already exist")
    # One creator owns this output; partial work never replaces an existing release.
    output.mkdir(mode=0o700)
    log = output / "build.log"
    log.touch(mode=0o600)
    wheels = output / "wheels"
    wheels.mkdir(mode=0o700)
    staging = output / "wheel-build"
    staging.mkdir(mode=0o700)
    environment = {**os.environ, "SOURCE_DATE_EPOCH": identity["source_date_epoch"]}
    exported = output / "source-requirements.txt"
    _run(
        [
            "uv",
            "export",
            "--project",
            str(source),
            "--locked",
            "--no-dev",
            "--extra",
            "fleet",
            "--no-emit-project",
            "--no-editable",
            "--no-hashes",
            "--format",
            "requirements-txt",
            "--output-file",
            str(exported),
        ],
        source=source,
        log=log,
        env=environment,
    )
    _run(
        [
            "uv",
            "build",
            "--wheel",
            "--python",
            sys.executable,
            "--out-dir",
            str(staging),
            str(source),
        ],
        source=source,
        log=log,
        env=environment,
    )
    if any(
        line.strip() and not line.lstrip().startswith("#")
        for line in exported.read_text().splitlines()
    ):
        _run(
            [
                "uvx",
                "--python",
                sys.executable,
                "--from",
                f"pip=={PIP_VERSION}",
                "pip",
                "wheel",
                "--no-deps",
                "--wheel-dir",
                str(staging),
                "-r",
                str(exported),
            ],
            source=source,
            log=log,
            env=environment,
        )
    # Packaging tools also write support files such as .gitignore. Only their
    # actual wheels enter the exact manifest consumed by offline installation.
    for wheel in staging.glob("*.whl"):
        wheel.rename(wheels / wheel.name)
    descriptor = {
        "schema_version": 1,
        "kind": "loom.service-release",
        "release_id": release_id or "loom-" + identity["commit"],
        "python": "3.12",
        **_seal_wheels(output),
    }
    # Keep the candidate descriptor private until the complete offline check passes.
    candidate = output / ".candidate.json"
    candidate.write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n")
    candidate.chmod(0o600)
    verified = verify_release(candidate)
    with tempfile.TemporaryDirectory(prefix=".verify-", dir=output) as temporary:
        environment_path = Path(temporary) / "environment"
        python = environment_path / "bin/python"
        _run(
            ["uv", "venv", "--python", sys.executable, str(environment_path)],
            source=source,
            log=log,
            env=environment,
        )
        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--offline",
                "--no-index",
                "--require-hashes",
                "--find-links",
                str(wheels),
                "-r",
                str(output / "requirements.txt"),
            ],
            source=source,
            log=log,
            env=environment,
        )
        _run(
            ["uv", "pip", "check", "--python", str(python)],
            source=source,
            log=log,
            env=environment,
        )
        _run(
            [
                str(python),
                "-I",
                "-c",
                "import loom.fleet._host; import sys; assert sys.version_info[:2] == (3, 12)",
            ],
            source=output,
            log=log,
            env=environment,
        )
    if _source(source) != identity:
        raise QueueConfigError(
            "service source changed during the build; output is unqualified"
        )
    receipt = {
        "schema_version": 1,
        "source": identity,
        "export_sha256": _sha(exported),
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "tools": {
            "uv": subprocess.run(
                ["uv", "--version"], check=True, capture_output=True, text=True
            ).stdout.strip(),
            "pip": PIP_VERSION,
        },
        "release": verified,
        "offline_installation": "passed",
    }
    receipt_path = output / "build-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    receipt_path.chmod(0o600)
    release = output / "release.json"
    candidate.rename(release)
    return {
        "outcome": "complete",
        "release": str(release),
        "receipt": str(receipt_path),
        "source": identity,
        "verification": verified,
        "offline_installation": "passed",
    }

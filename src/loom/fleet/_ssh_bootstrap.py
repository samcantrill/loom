"""Fixed standard-library bootstrap sent to the selected SSH Python interpreter.

This file is also the wire program: request values are data, never shell source.
The installed candidate owns all native operations after offline installation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

LIMIT = 128 * 1024 * 1024


def private(path):
    if path.exists():
        info = path.stat()
        if not path.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("host administrative directory must be owner-protected")
    else:
        if not path.parent.exists():
            private(path.parent)
        path.mkdir(mode=0o700)


def local(path):
    while not path.exists():
        path = path.parent
    result = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stdout.strip() not in {
        "ext2",
        "ext3",
        "ext4",
        "xfs",
        "btrfs",
        "zfs",
        "overlay",
    }:
        raise ValueError("native state requires a supported host-local filesystem")


def publish(path, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".fleet-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    os.umask(0o077)
    encoded = sys.stdin.buffer.read(LIMIT + 1)
    if len(encoded) > LIMIT:
        raise ValueError("host request exceeds limit")
    request = json.loads(encoded)
    root = Path(request["root"])
    if not root.is_absolute():
        raise ValueError("native root must be absolute")
    admin = root.parent / (
        ".loom-fleet-" + hashlib.sha256(str(root).encode()).hexdigest()[:16]
    )
    local(root)
    local(admin)
    missing = [
        name
        for name in ("uv", "tmux", "openssl", "findmnt")
        if shutil.which(name) is None
    ]
    if missing or sys.version_info[:2] != (3, 12):
        raise ValueError("host requires Python 3.12, uv, tmux, openssl and findmnt")
    release = request["release"]
    destination = admin / "releases" / release["descriptor_sha256"]
    python = destination / "environment/bin/python"
    marker = destination / "installed.json"
    active = admin / "active.json"
    if request["action"] == "inspect":
        installed = json.loads(active.read_text()) if active.exists() else None
        native_owner = None
        bound_root = False
        for intent_path in (admin / "operations").glob("*/intent.json"):
            if (
                json.loads(intent_path.read_text()).get("action") == "initialize"
                and (intent_path.parent / "dispatched.json").exists()
            ):
                bound_root = True
        if root.exists() and installed is not None:
            installed_python = (
                admin
                / "releases"
                / installed["descriptor_sha256"]
                / "environment/bin/python"
            )
            inspected_root = (
                root / "coordinator" if request.get("name") == "coordinator" else root
            )
            result = subprocess.run(
                [
                    str(installed_python),
                    "-c",
                    "import json,sys; from loom.queue.operations import inspect_native_service; print(json.dumps(inspect_native_service(sys.argv[1]).to_dict()))",
                    str(inspected_root),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            native_owner = json.loads(result.stdout)
        return {
            "root_exists": root.exists(),
            "bound_root": bound_root,
            "admin": str(admin),
            "installed": installed,
            "native_owner": native_owner,
            "local_storage": True,
            "boot_start": False,
            "credentials_complete": all(
                Path(path).is_file() for path in request.get("credential_paths", [])
            ),
        }
    private(admin)
    if active.exists() and json.loads(active.read_text()) != release:
        raise ValueError("service release change requires explicit upgrade")
    import fcntl

    with (admin / "installation.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if request["action"] == "install":
            if marker.exists():
                if json.loads(marker.read_text()) != release:
                    raise ValueError("installed immutable release differs")
                if not active.exists():
                    publish(active, json.dumps(release, sort_keys=True).encode())
                return {"installed": release, "outcome": "unchanged"}
            private(destination)
            for entry in request["files"]:
                relative = Path(entry["path"])
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("bundle path escapes installation")
                target = destination / "bundle" / relative
                private(target.parent)
                content = base64.b64decode(entry["data"], validate=True)
                if hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise ValueError("bundle transfer digest differs")
                if target.exists():
                    if target.read_bytes() != content:
                        raise ValueError("retained bundle bytes differ")
                else:
                    publish(target, content)
            bundle = destination / "bundle"
            environment = destination / "environment"
            log = destination / "install.log"
            with log.open("ab") as stream:
                if not python.exists():
                    subprocess.run(
                        ["uv", "venv", "--python", sys.executable, str(environment)],
                        stdout=stream,
                        stderr=stream,
                        check=True,
                    )
                subprocess.run(
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
                        str(bundle / request["wheelhouse"]),
                        "-r",
                        str(bundle / request["requirements"]),
                    ],
                    stdout=stream,
                    stderr=stream,
                    check=True,
                )
                subprocess.run(
                    [
                        str(python),
                        "-c",
                        "import loom.fleet._host; import sys; assert sys.version_info[:2] == (3,12)",
                    ],
                    stdout=stream,
                    stderr=stream,
                    check=True,
                )
            publish(marker, json.dumps(release, sort_keys=True).encode())
            if not active.exists():
                publish(active, json.dumps(release, sort_keys=True).encode())
            return {"installed": release, "outcome": "applied"}
    if not marker.exists() or json.loads(marker.read_text()) != release:
        raise ValueError("exact installed candidate unavailable")
    request["admin"] = str(admin)
    result = subprocess.run(
        [str(python), "-m", "loom.fleet._host"],
        input=json.dumps(request).encode(),
        capture_output=True,
    )
    reply = json.loads(result.stdout)
    if result.returncode:
        raise ValueError(
            reply.get("host_error", {}).get(
                "reason", "native host command failed; inspect protected host evidence"
            )
        )
    return reply


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "result": main()}, sort_keys=True))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": type(exc).__name__,
                    "reason": str(exc)
                    if isinstance(exc, ValueError)
                    else "host prerequisite or retained operation conflict",
                }
            )
        )
        sys.exit(1)

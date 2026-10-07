"""Explicit service-manager lifetimes for installed native roles.

Fleet owns unit configuration only. Native locks, journals and supervisor
receipts remain authoritative for execution and quiescence.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys
import time

from loom.queue.errors import QueueConflictError


def manager_environment():
    """Discover the current user's protected systemd runtime over ordinary SSH."""
    runtime = Path("/run/user") / str(os.getuid())
    try:
        info = runtime.stat()
    except OSError as exc:
        raise QueueConflictError(
            f"current-user runtime unavailable; ask administrator to start user@{os.getuid()}.service with approved linger"
        ) from exc
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise QueueConflictError("current-user runtime directory is not protected")
    if not (runtime / "bus").is_socket():
        raise QueueConflictError(
            "current-user systemd bus unavailable; administrator must enable the user manager"
        )
    return {
        **os.environ,
        "XDG_RUNTIME_DIR": str(runtime),
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=" + str(runtime / "bus"),
    }


def systemctl(*args):
    result = subprocess.run(
        ["systemctl", "--user", "--no-ask-password", *args],
        env=manager_environment(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode:
        raise QueueConflictError(
            "systemd-user operation refused: " + result.stderr.strip()
        )
    return result.stdout.strip()


def prerequisites():
    result = subprocess.run(
        [
            "loginctl",
            "--no-ask-password",
            "show-user",
            str(os.getuid()),
            "--property=Linger",
            "--value",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode or result.stdout.strip() != "yes":
        raise QueueConflictError(
            "systemd-user requires approved linger; ask the administrator to enable linger for this user"
        )
    systemctl("show-environment")


def unit_name(request, kind):
    import hashlib

    return (
        "loom-"
        + hashlib.sha256(str(Path(request["root"]).resolve()).encode()).hexdigest()[:16]
        + "-"
        + kind
        + ".service"
    )


def quote(value):
    value = str(value)
    if any(c in value for c in "\n\r\x00"):
        raise QueueConflictError("service argument contains a control character")
    return (
        '"'
        + value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
        + '"'
    )


def render(request, kind):
    """Render distinct cgroups; agent failure cannot stop its supervisor unit."""
    from loom.fleet._host import config, environment

    command = {
        "agent": "agent-serve",
        "coordinator": "daemon-serve",
        "supervisor": "agent-supervisor-serve",
    }[kind]
    argv = [
        sys.executable,
        "-c",
        "from loom.cli.main import main; raise SystemExit(main())",
        "queue",
        command,
        str(config(request)),
        "--format",
        "json",
    ]
    if environment(request) is not None:
        argv += ["--env-file", str(environment(request))]
    if kind == "agent":
        argv += [
            "--external-supervisor",
            "--expected-coordinator-id",
            request["coordinator_id"],
        ]
    # ExecStartPre is an identity/readiness check, never native initialization.
    ready = [
        sys.executable,
        "-m",
        "loom.fleet._services",
        str(Path(request["admin"]) / "service.json"),
    ]
    dependency = ""
    if kind == "agent":
        supervisor = unit_name(request, "supervisor")
        dependency = f"Wants={supervisor}\nAfter={supervisor}\n"
    return (
        "[Unit]\nDescription=Loom native "
        + kind
        + "\n"
        + dependency
        + "[Service]\n"
        + (
            "Type=notify\nNotifyAccess=main\n"
            if kind == "supervisor"
            else "Type=exec\n"
        )
        + "UMask=0077\n"
        + "ExecStartPre="
        + " ".join(map(quote, ready))
        + "\n"
        + "ExecStart="
        + " ".join(map(quote, argv))
        + "\n"
        + (
            "Restart=no\n"
            if kind == "supervisor"
            else "Restart=on-failure\nRestartSec=3\n"
        )
        + "KillMode=control-group\nTimeoutStopSec=infinity\n[Install]\nWantedBy=default.target\n"
    )


def readiness(request):
    from loom.fleet._host import owner, payload, config

    observed = owner(request)
    if observed["owner"] != request["expected_root_id"]:
        raise QueueConflictError("bound native root identity changed")
    selected = payload(request)
    base = config(request).parent
    paths = []
    for item in selected.get("shared_roots", {}).values():
        paths.append(item["host_path"])
    for profile in selected.get("resident_profiles", []):
        paths += list(profile.get("preparation_shared_roots", {}).values())
        paths += [item["host_path"] for item in profile.get("shared_roots", {}).values()]
    for value in paths:
        path = (base / value).resolve()
        if not path.is_dir() or not os.access(path, os.R_OK | os.X_OK):
            raise QueueConflictError(
                "required shared resource unavailable: " + str(path)
            )
    return observed


def start(request):
    from loom.fleet._host import atomic, keep, owner, role

    prerequisites()
    readiness(request)
    admin = Path(request["admin"])
    binding = admin / "service.json"
    if binding.exists():
        from loom.fleet._host import read

        old = read(binding)
        if any(
            old.get(k) != request.get(k)
            for k in ("root", "expected_root_id", "config", "coordinator_id")
        ):
            raise QueueConflictError("retained service binding differs")
    else:
        if owner(request)["value"]["ownership"] == "live":
            raise QueueConflictError("native service already has a different owner")
        atomic(binding, request)
    kinds = ["supervisor", "agent"] if role(request) == "agent" else ["coordinator"]
    units = admin / "units"
    for kind in kinds:
        # Unit definitions contain protected role paths, never secret values.
        keep(units / unit_name(request, kind), render(request, kind).encode())
    systemctl("daemon-reload")
    systemctl("enable", *[str(units / unit_name(request, kind)) for kind in kinds])
    systemctl("start", *[unit_name(request, kind) for kind in kinds])
    deadline = time.monotonic() + 30
    while True:
        observed = owner(request)
        pid = systemctl(
            "show", unit_name(request, role(request)), "--property=MainPID", "--value"
        )
        if (
            observed["value"]["ownership"] == "live"
            and str(observed["value"]["expected_process"]) == pid
        ):
            break
        if time.monotonic() >= deadline:
            raise QueueConflictError(
                "native systemd service readiness remains unproven"
            )
        time.sleep(0.1)
    return {
        "native_owner": observed,
        "service_manager": "systemd-user",
        "boot_start": True,
        "units": [unit_name(request, kind) for kind in kinds],
    }


def migrate(request):
    """Move a stopped, natively settled tmux role to systemd with the same IDs."""
    from loom.fleet._host import read, atomic, role, config, environment, owner
    from loom.queue.deployment import (
        load_coordinator_service_config,
        load_outbound_agent_service_config,
        service_backend_migration_guard,
    )

    if request.get("service_manager") != "systemd-user":
        raise QueueConflictError(
            "only explicit tmux to systemd-user migration is supported"
        )
    prerequisites()
    readiness(request)
    path = Path(request["admin"]) / "service.json"
    old = read(path) if path.exists() else None
    if old is not None and old.get("service_manager", "tmux") == "systemd-user":
        return start(request)
    if owner(request)["value"]["ownership"] == "live":
        raise QueueConflictError(
            "drain and stop the native tmux service before migration"
        )
    # A remaining tmux pane can still start the service after an observation.
    pane = subprocess.run(
        [
            "tmux",
            "-S",
            str(Path(request["admin"]) / "tmux.sock"),
            "has-session",
            "-t",
            "loom",
        ],
        capture_output=True,
    )
    if pane.returncode == 0:
        raise QueueConflictError(
            "tmux service session must be stopped before migration"
        )
    loader = (
        load_coordinator_service_config
        if role(request) == "coordinator"
        else load_outbound_agent_service_config
    )
    service = loader(config(request), env_file=environment(request))
    with service_backend_migration_guard(service, request["expected_root_id"]):
        atomic(path, request)
    return start(request)


if __name__ == "__main__":
    from loom.fleet._host import read

    readiness(read(Path(sys.argv[1])))

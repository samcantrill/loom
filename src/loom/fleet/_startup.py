"""One retained service launch, observed across host-command continuations."""
from __future__ import annotations

from pathlib import Path
import time

from loom.fleet.configuration import protected_directory
from loom.queue.errors import QueueConflictError

READINESS_SECONDS = 180.0
INITIAL_OBSERVATION_SECONDS = 20.0


class ServiceStarting(Exception):
    """The retained launch exists but has not proved native readiness yet."""
    fleet_pending = True


def process_identity(pid):
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            raise FileNotFoundError
        return {"pid": int(pid), "started": fields[19]}
    except (FileNotFoundError, ProcessLookupError) as exc:
        raise QueueConflictError("service_start_failed: launched process exited") from exc


def startup_path(request):
    from loom.fleet._host import digest
    identity = request.get("startup_id") or request["request_id"]
    token = digest({"startup": identity})
    return Path(request["admin"]) / "operations" / ("start-" + token[:24]) / "startup.json"


class Startup:
    """Retain the deadline and backend/process binding under the host operation."""

    def __init__(self, request):
        from loom.fleet._host import atomic, digest, read

        identity = request.get("startup_id") or request["request_id"]
        self.token = digest({"startup": identity})
        self.path = startup_path(request)
        protected_directory(self.path.parent)
        self.binding = {key: request.get(key) for key in (
            "root", "expected_root_id", "release", "config", "env_file", "env_sha256",
            "coordinator_id", "service_manager", "expected_declaration",
        )}
        self.first = not self.path.exists()
        if self.first:
            self.record = {
                "binding": self.binding,
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                "deadline": time.monotonic() + READINESS_SECONDS,
                "dispatched": False, "backend": None, "process": None, "ready": False,
            }
            atomic(self.path, self.record)
        else:
            self.record = read(self.path)
            if self.record["binding"] != self.binding:
                raise QueueConflictError("service startup intent changed")
        if self.record["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
            raise QueueConflictError("service startup boot identity changed")

    def save(self):
        from loom.fleet._host import atomic
        atomic(self.path, self.record)

    def dispatch(self):
        if self.record["dispatched"]:
            raise QueueConflictError("service_start_failed: retained launch is absent")
        self.pending()
        # A lost reply is reconciled against the backend identity. Absence after
        # dispatch is not permission to silently launch another process.
        self.record["dispatched"] = True
        self.save()

    def bind_backend(self, identity):
        old = self.record["backend"]
        if old is not None and old != identity:
            raise QueueConflictError("service startup backend ownership changed")
        if old is None:
            self.record["backend"] = identity
            self.record["dispatched"] = True
            self.save()

    def bind_process(self, pid):
        current = process_identity(pid)
        old = self.record["process"]
        if old is not None and old != current:
            raise QueueConflictError("service startup process ownership changed")
        if old is None:
            self.record["process"] = current
            self.save()

    def pending(self):
        if time.monotonic() >= self.record["deadline"]:
            raise QueueConflictError("service_readiness_timeout: retained launch deadline expired")

    def observe(self, probe):
        deadline = time.monotonic() + (INITIAL_OBSERVATION_SECONDS if self.first else 0)
        while True:
            fact, pid = probe()
            if fact["owner"] != self.binding["expected_root_id"]:
                raise QueueConflictError("native root identity changed")
            if pid:
                self.bind_process(pid)
            if fact["value"]["ownership"] == "live":
                if not pid or int(fact["value"]["expected_process"]) != int(pid):
                    raise QueueConflictError("service startup native process ownership changed")
                if not self.record["ready"]:
                    self.record["ready"] = True
                    self.save()
                return fact
            self.pending()
            if time.monotonic() >= deadline:
                raise ServiceStarting("service_starting: continue the retained launch")
            time.sleep(0.1)

"""Bounded, non-mutating qualification for resident worker profiles.

The profile process is the authority for installation facts.  Role files may
declare the small set of imports, distributions, and local source roots that a
project needs, but they never assert that those facts are installed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from time import monotonic, sleep
from typing import TYPE_CHECKING

from loom.serialization import PlainData, freeze_plain_data

from ._process_group import OwnedProcessGroup, require_group_wait_support

if TYPE_CHECKING:
    from ._remote_stage_execution import ResidentExecutionProfile


_PROBE_TIMEOUT_SECONDS = 5.0
_PROBE_MAX_OUTPUT_BYTES = 64 * 1024
_PROBE = r"""
import hashlib, importlib, importlib.metadata, json, pathlib, platform, sys
r = json.loads(sys.argv[1])
out = {"python": {"implementation": platform.python_implementation(), "version": platform.python_version(), "abi": getattr(sys.implementation, "cache_tag", "")}, "imports": {}, "distributions": {}, "sources": {}}
for name in r["imports"]:
    try: module = importlib.import_module(name)
    except Exception: print(json.dumps({"failure": "imports"})); sys.exit(0)
    out["imports"][name] = getattr(module, "__version__", None)
for name in r["distributions"]:
    try: dist = importlib.metadata.distribution(name)
    except Exception: print(json.dumps({"failure": "distributions"})); sys.exit(0)
    out["distributions"][name] = dist.version
for root_name in r["source_roots"]:
    root = pathlib.Path(root_name)
    if not root.is_dir(): print(json.dumps({"failure": "sources"})); sys.exit(0)
    digest = hashlib.sha256()
    for item in sorted(root.rglob("*")):
        if not item.is_file() or any(part in {".git", ".venv", "__pycache__"} for part in item.parts): continue
        relative = item.relative_to(root).as_posix().encode()
        digest.update(relative + b"\0" + item.read_bytes())
    out["sources"][root.name] = digest.hexdigest()
print(json.dumps(out, sort_keys=True, separators=(",", ":")))
"""


@dataclass(frozen=True, slots=True)
class ResidentReadinessCheck:
    """One redacted, stable qualification finding."""

    check_id: str
    status: str
    message: str
    details: Mapping[str, PlainData]

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ResidentReadinessResult:
    """The ephemeral evidence used to qualify one profile operation."""

    checks: tuple[ResidentReadinessCheck, ...]
    identity: str | None

    @property
    def ok(self) -> bool:
        return self.identity is not None and all(
            item.status == "PASS" for item in self.checks
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "ok": self.ok,
            "checks": [item.to_dict() for item in self.checks],
            "identity": self.identity,
        }


def qualify_resident_profile(
    profile: "ResidentExecutionProfile",
) -> ResidentReadinessResult:
    """Probe the exact worker executable with its launch cwd and environment.

    This creates only a contained temporary process.  It deliberately has no
    assigned GPU binding and never imports project code beyond declared imports.
    """

    requirements = profile.readiness_requirements
    request = {
        "imports": list(requirements.imports),
        "distributions": list(requirements.distributions),
        "source_roots": [
            str(profile.project_root / item) for item in requirements.source_roots
        ],
    }
    environment = {
        "PATH": str(profile.python_executable.parent),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        **dict(profile.environment),
    }
    try:
        require_group_wait_support()
        child = subprocess.Popen(
            [
                str(profile.python_executable),
                "-c",
                _PROBE,
                json.dumps(request, separators=(",", ":")),
            ],
            cwd=profile.project_root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        group = OwnedProcessGroup(child)
        deadline = monotonic() + requirements.timeout_seconds
        while group.root_status() is None and monotonic() < deadline:
            sleep(0.01)
        if group.root_status() is None:
            group.kill()
            group.contain()
            return _failed("python.interpreter", "resident Python probe timed out")
        assert child.stdout is not None
        output = child.stdout.read(_PROBE_MAX_OUTPUT_BYTES + 1)
        # The probe root can exit before an imported library's helper.  Retain
        # the unreaped leader as the group anchor and settle that owned tree.
        group.kill()
        if not group.contain():
            return _failed("python.interpreter", "resident Python probe cleanup failed")
    except OSError:
        return _failed("python.interpreter", "resident Python probe could not start")
    if group.returncode != 0:
        return _failed("python.interpreter", "resident Python probe failed")
    if len(output) > _PROBE_MAX_OUTPUT_BYTES:
        return _failed(
            "python.interpreter", "resident Python probe output exceeded its bound"
        )
    try:
        observed = json.loads(output)
        frozen = freeze_plain_data(observed, path="resident readiness")
        if not isinstance(frozen, Mapping):
            raise ValueError
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return _failed(
            "python.interpreter", "resident Python probe returned invalid evidence"
        )
    failure = observed.get("failure")
    if failure == "imports" or failure == "distributions":
        return _failed(
            "packages.required_imports", "declared package or import is unavailable"
        )
    if failure == "sources":
        return _failed("execution.source", "declared source root is unavailable")
    if failure is not None:
        return _failed(
            "python.interpreter", "resident Python probe returned invalid evidence"
        )
    checks = [
        ResidentReadinessCheck(
            "python.interpreter",
            "PASS",
            "selected Python responded",
            {
                "implementation": observed["python"]["implementation"],
                "version": observed["python"]["version"],
            },
        ),
        ResidentReadinessCheck(
            "packages.required_imports",
            "PASS",
            "declared imports resolved",
            {"count": len(requirements.imports)},
        ),
    ]
    identity = hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ResidentReadinessResult(tuple(checks), identity)


def _failed(check_id: str, message: str) -> ResidentReadinessResult:
    return ResidentReadinessResult(
        (ResidentReadinessCheck(check_id, "FAIL", message, {}),), None
    )


@dataclass(frozen=True, slots=True)
class ResidentReadinessRequirements:
    """Finite project-supplied installation evidence for one profile."""

    imports: tuple[str, ...] = ()
    distributions: tuple[str, ...] = ()
    source_roots: tuple[str, ...] = ()
    timeout_seconds: float = _PROBE_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        for values, label in (
            (self.imports, "imports"),
            (self.distributions, "distributions"),
            (self.source_roots, "source_roots"),
        ):
            if len(values) != len(set(values)) or any(
                not isinstance(item, str)
                or not item
                or item.startswith("/")
                or ".." in Path(item).parts
                for item in values
            ):
                raise ValueError(f"resident readiness {label} are invalid")
        if len({Path(item).name for item in self.source_roots}) != len(
            self.source_roots
        ):
            raise ValueError("resident readiness source roots are ambiguous")
        if (
            not isinstance(self.timeout_seconds, float | int)
            or isinstance(self.timeout_seconds, bool)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError("resident readiness timeout is invalid")
        object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))

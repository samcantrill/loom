"""Observed installation requirements for managed resident workers.

Qualification never provisions an environment. Its portable software descriptors
cover the declared installation subset; launch paths remain private bindings.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import hashlib
import json
import re
from typing import TYPE_CHECKING, cast

from loom.diagnostics.models import (
    PreflightCheckResult,
    PreflightCheckStatus,
    PreflightGroup,
    PreflightSeverity,
)
from loom.serialization import PlainData

from ._resident_probe import run_resident_probe

if TYPE_CHECKING:
    from ._remote_stage_execution import ResidentExecutionProfile


_HANDSHAKE = r"""
import json, platform, sys, sysconfig
print(json.dumps({"protocol": "loom.resident-python.v1", "implementation": platform.python_implementation(), "version": list(sys.version_info[:3]), "abi": sysconfig.get_config_var("SOABI") or sys.implementation.cache_tag, "platform": sysconfig.get_platform()}))
"""
_INSTALLATION = r"""
import contextlib, hashlib, importlib, importlib.metadata, json, os, pathlib, shutil, sys, urllib.parse
request = json.loads(sys.argv[1])
result = {"protocol": "loom.resident-installation.v1", "imports": {}, "distributions": {}, "sources": [], "environment": {}, "programs": {}, "lockfile": None}
if request.get("preparation", False):
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from loom.preparation import PreparationStage
            from weave import compose_config
        result["preparation_available"] = callable(PreparationStage) and callable(compose_config)
    except Exception:
        result["preparation_available"] = False
for name in request["imports"]:
    try:
        with contextlib.redirect_stdout(sys.stderr):
            module = importlib.import_module(name)
        paths = list(getattr(module, "__path__", ()))
        origin = getattr(module, "__file__", None)
        if origin: paths.append(origin)
        expected = request["import_roots"].get(name)
        matches = expected is None or bool(paths) and all(pathlib.Path(path).resolve().is_relative_to(pathlib.Path(expected).resolve()) for path in paths)
        version = getattr(module, "__version__", None)
        result["imports"][name] = {"available": True, "origin_matches": matches, "version": version if isinstance(version, str) else None}
    except Exception:
        result["imports"][name] = {"available": False, "origin_matches": False, "version": None}
for name in request["distributions"]:
    try:
        distribution = importlib.metadata.distribution(name)
        origin = json.loads(distribution.read_text("direct_url.json") or "{}")
        # Editable paths are private. Only immutable remote origins participate
        # in portable software identity; selected source contents cover edits.
        immutable = None
        if "vcs_info" in origin:
            parsed = urllib.parse.urlsplit(origin.get("url", ""))
            remote_url = urllib.parse.urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", "")) if parsed.scheme in {"http", "https", "ssh", "git"} else None
            immutable = {"url": remote_url, "commit": origin["vcs_info"].get("commit_id"), "vcs": origin["vcs_info"].get("vcs")}
        elif origin.get("archive_info", {}).get("hashes"):
            immutable = {"hashes": origin["archive_info"]["hashes"]}
        result["distributions"][name] = {"version": distribution.version, "origin": immutable}
    except Exception:
        result["distributions"][name] = None
for root_name in request["source_roots"]:
    root = pathlib.Path(root_name)
    if root.is_file() and not root.is_symlink():
        members = [(str(root.parent), [], [root.name])]
        relative_root = root.parent
    elif root.is_dir():
        members = os.walk(root)
        relative_root = root
    else:
        result["sources"].append(None)
        continue
    digest = hashlib.sha256()
    # Bind contents to their project-relative location before combining roots.
    location = pathlib.Path(os.path.relpath(root.resolve(), pathlib.Path.cwd())).as_posix().encode()
    digest.update(len(location).to_bytes(8, "big") + location)
    excluded = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "datasets", "caches", "runs", "build", "dist"}
    for directory, names, files in members:
        names[:] = sorted(name for name in names if name not in excluded and not pathlib.Path(directory, name).is_symlink())
        for name in sorted(files):
            item = pathlib.Path(directory, name)
            if item.is_symlink() or item.suffix in {".pyc", ".pyo"}: continue
            relative = item.relative_to(relative_root).as_posix().encode()
            contents = item.read_bytes()
            digest.update(len(relative).to_bytes(8, "big") + relative + len(contents).to_bytes(8, "big") + contents)
    result["sources"].append(digest.hexdigest())
for name in request["required_environment"]:
    result["environment"][name] = bool(os.environ.get(name))
for name in request["required_programs"]:
    result["programs"][name] = shutil.which(name) is not None
lockfile = pathlib.Path(request["lockfile"])
if lockfile.is_file(): result["lockfile"] = hashlib.sha256(lockfile.read_bytes()).hexdigest()
print(json.dumps(result, sort_keys=True, separators=(",", ":")))
"""


def readiness_check(
    check_id: str,
    group: PreflightGroup,
    status: PreflightCheckStatus,
    message: str,
    *,
    owner: str,
    consequence: str,
    repair: str,
    applicability: str = "required",
    evidence: Mapping[str, PlainData] | None = None,
) -> PreflightCheckResult:
    """Construct a role finding using the existing diagnostics result contract."""

    return PreflightCheckResult(
        check_id,
        group,
        status,
        PreflightSeverity.ERROR
        if status is PreflightCheckStatus.FAIL
        else (
            PreflightSeverity.WARNING
            if status is PreflightCheckStatus.WARN
            else PreflightSeverity.INFO
        ),
        message,
        {
            "owner": owner,
            "consequence": consequence,
            "repair": repair,
            "applicability": applicability,
            "evidence": dict(evidence or {}),
        },
    )


@dataclass(frozen=True, slots=True)
class ResidentReadinessRequirements:
    """Finite installation requirements; versions are exact, Python may be a prefix.

    Source/import roots and the optional lockfile resolve against the project.
    Source identity includes each root's resolved project-relative location.
    Import roots assert the expected location without adding absolute paths to
    portable identity. Declared distributions alone require presence; entries in
    distribution_versions additionally require an exact installed version.
    ``preparation`` also imports Loom's preparation stage and configuration loader
    in the selected Python. A shared preparation mapping requests the same check.
    This qualification does not add members to portable software fingerprints.
    """

    imports: tuple[str, ...] = ("loom",)
    distributions: tuple[str, ...] = ("loom",)
    source_roots: tuple[str, ...] = ()
    timeout_seconds: float = 5.0
    python_version: str | None = None
    python_implementation: str | None = None
    python_abi: str | None = None
    import_roots: Mapping[str, str] = field(default_factory=dict)
    distribution_versions: Mapping[str, str] = field(default_factory=dict)
    required_environment: tuple[str, ...] = ()
    required_programs: tuple[str, ...] = ()
    lockfile: str = "uv.lock"
    preparation: bool = False

    def __post_init__(self) -> None:
        if type(self.preparation) is not bool:
            raise ValueError("resident preparation requirement must be boolean")
        for values in (
            self.imports,
            self.distributions,
            self.source_roots,
            self.required_environment,
            self.required_programs,
        ):
            if any(not isinstance(item, str) or not item for item in values) or len(
                values
            ) != len(set(values)):
                raise ValueError("resident readiness declarations are invalid")
        for values in (self.import_roots, self.distribution_versions):
            if any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                or not value
                for key, value in values.items()
            ):
                raise ValueError(
                    "resident readiness compatibility requirements are invalid"
                )
        distributions = tuple(
            re.sub(r"[-_.]+", "-", name).lower() for name in self.distributions
        )
        versions = {
            re.sub(r"[-_.]+", "-", name).lower(): version
            for name, version in self.distribution_versions.items()
        }
        if len(distributions) != len(set(distributions)) or len(versions) != len(
            self.distribution_versions
        ):
            raise ValueError("resident distribution declarations overlap")
        object.__setattr__(self, "distributions", distributions)
        object.__setattr__(self, "distribution_versions", versions)
        if not set(self.import_roots).issubset(self.imports) or not set(
            self.distribution_versions
        ).issubset(self.distributions):
            raise ValueError(
                "compatibility requirements must name declared installation members"
            )
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError(
                "resident readiness timeout must be positive and at most 30 seconds"
            )
        if self.python_version is not None and (
            not isinstance(self.python_version, str)
            or not 1 <= len(self.python_version.split(".")) <= 3
            or any(not item.isdecimal() for item in self.python_version.split("."))
        ):
            raise ValueError("Python version must have one to three numeric components")
        for value in (self.python_implementation, self.python_abi, self.lockfile):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("resident readiness requirement is invalid")
        object.__setattr__(self, "import_roots", dict(self.import_roots))
        object.__setattr__(
            self, "distribution_versions", dict(self.distribution_versions)
        )


@dataclass(frozen=True, slots=True)
class ResidentReadinessResult:
    """Ephemeral findings and the observed portable software descriptor fields."""

    checks: tuple[PreflightCheckResult, ...]
    identity: str | None
    fingerprints: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.identity is not None and not any(
            check.status is PreflightCheckStatus.FAIL for check in self.checks
        )

    @property
    def preparation_ready(self) -> bool:
        """Whether this observation qualified the installed preparation entrypoints."""
        return self.ok and any(
            check.check_id == "packages.preparation_imports"
            and check.status is PreflightCheckStatus.PASS
            for check in self.checks
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "ok": self.ok,
            "checks": [item.to_dict() for item in self.checks],
            "identity": self.identity,
            "fingerprints": dict(self.fingerprints),
        }


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def qualify_resident_profile(
    profile: ResidentExecutionProfile,
) -> ResidentReadinessResult:
    """Observe the selected interpreter before loading any declared project import.

    Both subprocesses reuse worker environment/containment. No training object,
    cache, deployment, run or resource claim is created. Limits cover each probe;
    cleanup uncertainty is a failure, never permission to release retained work.
    """

    requirements = profile.readiness_requirements
    preparation = requirements.preparation or bool(profile.preparation_shared_roots)
    checks: list[PreflightCheckResult] = []

    def add(
        check_id: str,
        group: PreflightGroup,
        passed: bool,
        message: str,
        repair: str,
        evidence: Mapping[str, PlainData] | None = None,
    ) -> None:
        checks.append(
            readiness_check(
                check_id,
                group,
                PreflightCheckStatus.PASS if passed else PreflightCheckStatus.FAIL,
                message,
                owner="resident profile",
                consequence="New profile eligibility is withheld on failure; retained work keeps its owner.",
                repair=repair,
                evidence=evidence,
            )
        )

    response = run_resident_probe(
        profile.launch_profile,
        _HANDSHAKE,
        {},
        timeout_seconds=requirements.timeout_seconds,
    )
    python = response.payload
    valid = (
        isinstance(python, Mapping)
        and python.get("protocol") == "loom.resident-python.v1"
    )
    if valid:
        assert python is not None
        version = python.get("version")
        valid = (
            isinstance(version, list)
            and len(version) == 3
            and all(
                isinstance(item, int) and not isinstance(item, bool) and item >= 0
                for item in version
            )
        )
        valid = valid and all(
            isinstance(python.get(key), str) and python[key]
            for key in ("implementation", "abi", "platform")
        )
    if response.failure or not valid:
        add(
            "python.interpreter",
            PreflightGroup.PYTHON,
            False,
            response.failure
            or "Selected executable did not return the Python handshake.",
            "Select an installed compatible Python executable.",
        )
        checks.append(
            readiness_check(
                "packages.required_imports",
                PreflightGroup.PACKAGES,
                PreflightCheckStatus.SKIP,
                "Package checks require the Python handshake.",
                owner="resident profile",
                consequence="Profile eligibility is blocked by python.interpreter.",
                repair="Repair the selected interpreter first.",
                applicability="blocked by python.interpreter",
            )
        )
        return ResidentReadinessResult(tuple(checks), None)
    assert python is not None
    version = cast(list[int], python["version"])
    compatible = tuple(version) >= (3, 12, 0)
    if requirements.python_version is not None:
        expected = [int(item) for item in requirements.python_version.split(".")]
        compatible = compatible and version[: len(expected)] == expected
    compatible = compatible and (
        requirements.python_implementation is None
        or python["implementation"] == requirements.python_implementation
    )
    compatible = compatible and (
        requirements.python_abi is None or python["abi"] == requirements.python_abi
    )
    add(
        "python.interpreter",
        PreflightGroup.PYTHON,
        compatible,
        "Selected Python meets declared compatibility."
        if compatible
        else "Selected Python does not meet declared compatibility.",
        "Select the declared Python implementation/version/ABI.",
        python,
    )
    if not compatible:
        checks.append(
            readiness_check(
                "packages.required_imports",
                PreflightGroup.PACKAGES,
                PreflightCheckStatus.SKIP,
                "Imports require a compatible Python.",
                owner="resident profile",
                consequence="Profile eligibility is blocked.",
                repair="Repair Python compatibility first.",
                applicability="blocked by python.interpreter",
            )
        )
        return ResidentReadinessResult(tuple(checks), None)
    request: dict[str, PlainData] = {
        "imports": list(requirements.imports),
        "distributions": list(requirements.distributions),
        "import_roots": {
            name: str(profile.project_root / root)
            for name, root in requirements.import_roots.items()
        },
        "source_roots": [
            str(profile.project_root / root) for root in requirements.source_roots
        ],
        "required_environment": list(requirements.required_environment),
        "required_programs": list(requirements.required_programs),
        "lockfile": str(profile.project_root / requirements.lockfile),
    }
    if preparation:
        request["preparation"] = True
    response = run_resident_probe(
        profile.launch_profile,
        _INSTALLATION,
        request,
        timeout_seconds=requirements.timeout_seconds,
    )
    observed = response.payload
    valid = (
        observed is not None
        and observed.get("protocol") == "loom.resident-installation.v1"
        and all(
            isinstance(observed.get(key), Mapping)
            for key in ("imports", "distributions", "environment", "programs")
        )
        and isinstance(observed.get("sources"), list)
    )
    if response.failure or not valid:
        add(
            "packages.required_imports",
            PreflightGroup.PACKAGES,
            False,
            response.failure or "Installation probe returned invalid evidence.",
            "Repair the declared imports and their bounded probe behavior.",
        )
        return ResidentReadinessResult(tuple(checks), None)
    assert observed is not None
    if preparation:
        available = observed.get("preparation_available") is True
        add(
            "packages.preparation_imports",
            PreflightGroup.PACKAGES,
            available,
            "Selected Python imports the installed preparation stage and config loader."
            if available
            else "The preparation stage or config loader is unavailable in the selected Python.",
            "Install compatible Loom with its config extra in the existing environment before enabling preparation.",
        )
    imports = cast(Mapping[str, Mapping[str, object]], observed["imports"])
    distributions = cast(
        Mapping[str, Mapping[str, object] | None], observed["distributions"]
    )
    imports_ok = set(imports) == set(requirements.imports) and all(
        isinstance(item, Mapping)
        and item.get("available") is True
        and item.get("origin_matches") is True
        for item in imports.values()
    )
    distributions_ok = set(distributions) == set(requirements.distributions) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("version"), str)
        and (
            name not in requirements.distribution_versions
            or item["version"] == requirements.distribution_versions[name]
        )
        for name, item in distributions.items()
    )
    add(
        "packages.required_imports",
        PreflightGroup.PACKAGES,
        imports_ok and distributions_ok,
        "Declared imports, origins and distributions match."
        if imports_ok and distributions_ok
        else "A declared import, origin or distribution is missing or incompatible.",
        "Install the declared project/package versions in the selected environment and correct import roots.",
        {
            "imports": len(requirements.imports),
            "distributions": len(requirements.distributions),
        },
    )
    environment_ok = observed["environment"] == {
        name: True for name in requirements.required_environment
    } and observed["programs"] == {
        name: True for name in requirements.required_programs
    }
    add(
        "environment.worker",
        PreflightGroup.ENVIRONMENT,
        environment_ok,
        "Declared worker environment and programs are available."
        if environment_ok
        else "A required worker variable or program is unavailable.",
        "Set explicit profile variables and PATH/program requirements; daemon variables are not inherited.",
    )
    sources = cast(list[object], observed["sources"])
    sources_ok = len(sources) == len(requirements.source_roots) and all(
        isinstance(item, str) and len(item) == 64 for item in sources
    )
    add(
        "execution.source",
        PreflightGroup.IDENTITY,
        sources_ok,
        "Declared source evidence is available."
        if sources_ok
        else "A declared source root is unavailable.",
        "Install the declared source roots; dataset/cache/run roots are not source evidence.",
        {"roots": len(sources), "lockfile_digest": observed.get("lockfile")},
    )
    if any(check.status is PreflightCheckStatus.FAIL for check in checks):
        return ResidentReadinessResult(tuple(checks), None)
    fingerprints = {
        "project_fingerprint": _digest(
            {"imports": imports, "sources": sorted(cast(list[str], sources))}
        ),
        "environment_fingerprint": _digest(
            {"python": python, "distributions": distributions}
        ),
        "executor_fingerprint": _digest(
            {
                "worker": "loom.queue._resident_stage_worker",
                "protocol": "resident-v3",
                "python": python,
            }
        ),
    }
    identity = _digest(fingerprints)
    add(
        "execution.identity",
        PreflightGroup.IDENTITY,
        True,
        "Observed software descriptor fields are qualified.",
        "Requalify a new profile/deployment after retained work settles if this identity changes.",
        {
            "identity": identity,
            "descriptor": {**profile.descriptor.to_dict(), **fingerprints},
        },
    )
    return ResidentReadinessResult(tuple(checks), identity, fingerprints)


def qualified_resident_profile(
    profile: ResidentExecutionProfile,
) -> ResidentExecutionProfile:
    """Return a profile carrying one operation's observation and derived descriptor."""

    result = qualify_resident_profile(profile)
    descriptor = profile.descriptor
    if result.ok:
        descriptor = replace(descriptor, **dict(result.fingerprints))
    return replace(
        profile,
        descriptor=descriptor,
        readiness_identity=result.identity,
        readiness_result=result,
    )


__all__ = [
    "ResidentReadinessRequirements",
    "ResidentReadinessResult",
    "qualified_resident_profile",
    "qualify_resident_profile",
]

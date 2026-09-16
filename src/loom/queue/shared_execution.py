"""Protected root qualification and explicit shared workload locations.

Locations contain logical identity only. Host mappings are private launch policy;
qualification reads a bounded regular-file challenge, never an entire dataset.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
import hashlib
import os
import stat
from typing import cast

from loom.fingerprints import hash_mapping
from loom.serialization import PlainData, thaw_plain_data
from .errors import QueueServiceError

SHARED_EXECUTION_CAPABILITY = "shared-execution-v1"
SHARED_EXECUTION_SCOPE = "loom.shared_execution"


def _relative(value: object) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or "\x00" in value
        or PurePosixPath(value).is_absolute() or ".." in value.split("/")
        or str(PurePosixPath(value)) != value):
        raise QueueServiceError("shared location requires a normalized relative path")
    return value


def location(value: object) -> dict[str, PlainData]:
    """Decode a versioned, host-independent location (read access only)."""
    if (not isinstance(value, Mapping) or set(value) != {"kind", "schema_version", "root_id", "path"}
        or value.get("kind") != "loom.shared-location" or type(value.get("schema_version")) is not int
        or value["schema_version"] != 1 or not isinstance(value["root_id"], str)
        or not value["root_id"] or "/" in value["root_id"]):
        raise QueueServiceError("shared location capability is unsupported")
    return {"kind": "loom.shared-location", "schema_version": 1,
            "root_id": value["root_id"], "path": _relative(value["path"])}


def root_bindings(value: object) -> dict[str, PlainData]:
    """Validate private absolute bindings and bounded challenge declarations."""
    if not isinstance(value, Mapping):
        raise QueueServiceError("shared_roots must be a protected mapping")
    result: dict[str, PlainData] = {}
    for alias, raw in value.items():
        if (not isinstance(alias, str) or not alias or "/" in alias or not isinstance(raw, Mapping)
            or set(raw) != {"host_path", "container_path", "access", "challenge"}):
            raise QueueServiceError("protected shared root is invalid")
        if not isinstance(raw["host_path"], str) or not Path(raw["host_path"]).is_absolute():
            raise QueueServiceError("shared root host_path must be absolute")
        target = raw["container_path"]
        if target is not None and (not isinstance(target, str) or not target.startswith("/loom/")
                                   or str(PurePosixPath(target)) != target or ".." in target.split("/")):
            raise QueueServiceError("shared root container_path must be a canonical /loom target")
        challenge = raw["challenge"]
        if (raw["access"] not in ("ro", "rw") or not isinstance(challenge, Mapping)
            or set(challenge) != {"path", "sha256"} or not isinstance(challenge["sha256"], str)
            or len(challenge["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in challenge["sha256"])):
            raise QueueServiceError("shared root challenge or access is invalid")
        result[alias] = {"host_path": raw["host_path"], "container_path": target,
                         "access": raw["access"], "challenge": {"path": _relative(challenge["path"]), "sha256": challenge["sha256"]}}
    targets = [str(cast(Mapping[str, PlainData], root)["container_path"]) for root in result.values()
               if cast(Mapping[str, PlainData], root)["container_path"] is not None]
    for index, target in enumerate(targets):
        if any(PurePosixPath(target).is_relative_to(other) or PurePosixPath(other).is_relative_to(target)
               for other in targets[index + 1:]):
            raise QueueServiceError("shared container targets must not overlap")
    return result


def resolve(root: Mapping[str, PlainData], path: str) -> Path:
    """Resolve an existing selected file/tree without traversal or symbolic links."""
    base = Path(str(root["host_path"]))
    target = base / _relative(path)
    if not base.is_dir() or not target.exists() or not target.resolve().is_relative_to(base.resolve()):
        raise QueueServiceError("shared root or selected location is unavailable or escaping")
    current = base
    for part in PurePosixPath(path).parts:
        current /= part
        if current.is_symlink():
            raise QueueServiceError("shared locations do not admit symbolic links")
    return target


def qualifications(roots: Mapping[str, PlainData]) -> dict[str, PlainData]:
    """Verify bounded root challenges; return portable qualification facts."""
    result: dict[str, PlainData] = {}
    for alias, raw in roots.items():
        root = cast(Mapping[str, PlainData], raw)
        challenge = cast(Mapping[str, PlainData], root["challenge"])
        path = resolve(root, str(challenge["path"]))
        if not path.is_file() or path.stat().st_size > 65536:
            raise QueueServiceError("shared root challenge must be a bounded regular file")
        if hashlib.sha256(path.read_bytes()).hexdigest() != challenge["sha256"]:
            raise QueueServiceError("shared root challenge bytes mismatch")
        result[alias] = {"container_path": root["container_path"], "access": root["access"], "challenge": dict(challenge)}
    return result


def qualified_roots(value: object) -> dict[str, PlainData]:
    """Decode portable root facts without admitting private host paths."""
    if not isinstance(value, Mapping):
        raise QueueServiceError("shared root qualifications must be a mapping")
    private = {}
    for alias, facts in value.items():
        if not isinstance(facts, Mapping) or set(facts) != {"container_path", "access", "challenge"}:
            raise QueueServiceError("shared root qualification fields are invalid")
        private[alias] = {**facts, "host_path": "/"}
    return {alias: {key: item for key, item in cast(Mapping[str, PlainData], raw).items() if key != "host_path"}
            for alias, raw in root_bindings(private).items()}


def scope(value: object) -> dict[str, PlainData] | None:
    if value is None:
        return None
    if (not isinstance(value, Mapping) or set(value) != {"capability", "roots", "locations"}
        or value["capability"] != SHARED_EXECUTION_CAPABILITY or not isinstance(value["roots"], Mapping)
        or not isinstance(value["locations"], (list, tuple))):
        raise QueueServiceError("shared execution scope is unsupported")
    locations = [location(item) for item in value["locations"]]
    roots = qualified_roots(thaw_plain_data(value["roots"]))
    if any(item["root_id"] not in roots for item in locations):
        raise QueueServiceError("shared location root is not permitted")
    return {"capability": SHARED_EXECUTION_CAPABILITY, "roots": roots, "locations": cast(PlainData, locations)}


def selected_locations(value: object) -> list[dict[str, PlainData]]:
    if isinstance(value, Mapping):
        if value.get("kind") == "loom.shared-location":
            return [location(value)]
        return [item for child in value.values() for item in selected_locations(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in selected_locations(child)]
    return []


def stage_scope(config: object, factory_init: object, permitted: Mapping[str, PlainData]) -> dict[str, PlainData]:
    locations = selected_locations(config) + selected_locations(factory_init)
    if "locations" in permitted:
        admitted = cast(list[Mapping[str, PlainData]], permitted["locations"])
        for item in locations:
            if not any(item["root_id"] == parent["root_id"]
                       and PurePosixPath(str(item["path"])).is_relative_to(str(parent["path"])) for parent in admitted):
                raise QueueServiceError("stage location is outside the preparation selection")
    aliases = {str(item["root_id"]) for item in locations}
    roots = cast(Mapping[str, PlainData], permitted["roots"])
    if not aliases.issubset(roots):
        raise QueueServiceError("stage selects an undeclared shared root")
    return {"capability": SHARED_EXECUTION_CAPABILITY, "roots": {alias: roots[alias] for alias in sorted(aliases)}, "locations": cast(PlainData, locations)}


def require_bindings(required: Mapping[str, PlainData], roots: Mapping[str, PlainData]) -> None:
    selected = cast(Mapping[str, PlainData], required["roots"])
    if not set(selected).issubset(roots):
        raise QueueServiceError("shared execution root is not mapped")
    observed = qualifications({alias: roots[alias] for alias in selected})
    if observed != selected:
        raise QueueServiceError("shared execution qualification conflicts")
    for item in cast(list[Mapping[str, PlainData]], required["locations"]):
        selected_path = resolve(cast(Mapping[str, PlainData], roots[str(item["root_id"])]), str(item["path"]))
        if selected_path.is_dir():
            for directory, names, files in os.walk(selected_path):
                for name in names + files:
                    mode = (Path(directory) / name).lstat().st_mode
                    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                        raise QueueServiceError("shared input trees require regular files and directories")
        elif not selected_path.is_file():
            raise QueueServiceError("shared input requires a regular file or directory")


def attributes(required: Mapping[str, PlainData] | None) -> dict[str, PlainData]:
    if required is None:
        return {}
    return {"shared_execution_capability": SHARED_EXECUTION_CAPABILITY,
            **{"shared_root_" + alias: hash_mapping(facts) for alias, facts in cast(Mapping[str, PlainData], required["roots"]).items()}}


def validate_workload(value: object, required: Mapping[str, PlainData]) -> None:
    """Allow explicit locations, ordinary data, and selected canonical paths only."""
    locations = cast(list[Mapping[str, PlainData]], required["locations"])
    roots = cast(Mapping[str, Mapping[str, PlainData]], required["roots"])
    allowed = [str(PurePosixPath(str(roots[str(item["root_id"])]["container_path"])) / str(item["path"]))
               for item in locations if roots[str(item["root_id"])]["container_path"] is not None]
    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            if item.get("kind") == "loom.shared-location":
                if location(item) not in locations:
                    raise QueueServiceError("shared workload location is not selected")
            else:
                for child in item.values():
                    visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        elif isinstance(item, str) and (item.startswith(("/", "file:", "http:", "https:")) or "\\" in item):
            if not any(item == path or item.startswith(path + "/") and ".." not in item.split("/") for path in allowed):
                raise QueueServiceError("shared workload contains an unbound host path")
    visit(value)


def materialize(value: object, roots: Mapping[str, PlainData], *, container: bool) -> object:
    """Resolve typed locations only; preserve text and identity strings verbatim."""
    if isinstance(value, Mapping):
        if value.get("kind") == "loom.shared-location":
            item = location(value)
            root = cast(Mapping[str, PlainData], roots[str(item["root_id"])])
            if container:
                if root["container_path"] is None:
                    raise QueueServiceError("shared container target is missing")
                return str(PurePosixPath(str(root["container_path"])) / str(item["path"]))
            return str(resolve(root, str(item["path"])))
        return {key: materialize(child, roots, container=container) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [materialize(child, roots, container=container) for child in value]
    return value


def bind_snapshot(snapshot: dict[str, PlainData], permitted: Mapping[str, PlainData], *, redacted: dict[str, PlainData] | None = None) -> None:
    """Retain each stage's selected roots independently of the preparation union."""
    pipeline = cast(Mapping[str, PlainData], snapshot["pipeline"])
    stages = cast(list[dict[str, PlainData]], pipeline["stages"])
    for index, stage in enumerate(stages):
        factory = cast(Mapping[str, PlainData], stage["factory"])
        selected = stage_scope(stage.get("config", {}), factory.get("init", {}), permitted)
        validate_workload(stage.get("config", {}), selected)
        validate_workload(factory.get("init", {}), selected)
        fingerprint = cast(Mapping[str, PlainData], stage.get("fingerprint", {}))
        if SHARED_EXECUTION_SCOPE in fingerprint:
            raise QueueServiceError("authored configuration cannot select shared execution scope")
        stage["fingerprint"] = {**fingerprint, SHARED_EXECUTION_SCOPE: selected}
        if redacted is not None:
            view = cast(Mapping[str, PlainData], redacted["pipeline"])
            diagnostic = cast(list[dict[str, PlainData]], view["stages"])[index]
            diagnostic["fingerprint"] = {**cast(Mapping[str, PlainData], diagnostic.get("fingerprint", {})), SHARED_EXECUTION_SCOPE: selected}


def assignment_scope(fingerprint: Mapping[str, PlainData]) -> dict[str, PlainData] | None:
    payload = cast(Mapping[str, PlainData], fingerprint["payload"])
    fields = cast(Mapping[str, PlainData], payload["fingerprint_fields"])
    selected = scope(fields.get(SHARED_EXECUTION_SCOPE))
    from .preparation import PREPARATION_STAGE_TARGET, PreparationChildInput
    if payload["factory_target"] == PREPARATION_STAGE_TARGET:
        binding = PreparationChildInput.from_dict(payload["stage_config"])
        if binding.shared_scope != selected:
            raise QueueServiceError("preparation shared scope conflicts with assignment")
    return selected


def execution_roots(roots: Mapping[str, PlainData], *, container: bool) -> dict[str, PlainData]:
    return {alias: {**cast(Mapping[str, PlainData], raw),
                    "host_path": cast(Mapping[str, PlainData], raw)["container_path"]}
            if container else raw for alias, raw in roots.items()}


def snapshot_mount(profile: object, receipt: object) -> tuple[Path, Path]:
    """Bind the native captured snapshot below exactly one permitted shared root."""
    from .preparation import SharedInputReceipt
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile
    assert isinstance(profile, ResidentWorkerLaunchProfile)
    assert isinstance(receipt, SharedInputReceipt)
    source_root = profile.preparation_shared_roots.get(receipt.root)
    if source_root is None:
        raise QueueServiceError("shared snapshot root is not mapped")
    matches = []
    for raw in profile.shared_roots.values():
        root = cast(Mapping[str, PlainData], raw)
        host = Path(str(root["host_path"]))
        if source_root.is_relative_to(host):
            relative = source_root.relative_to(host) / receipt.path
            source = resolve(root, relative.as_posix())
            if root["container_path"] is None:
                raise QueueServiceError("shared snapshot container target is missing")
            matches.append((source, Path(str(root["container_path"])) / relative))
    if len(matches) != 1:
        raise QueueServiceError("shared snapshot must select one protected root")
    return matches[0]

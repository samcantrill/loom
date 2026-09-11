"""Protected preparation selection; no project imports or environment provisioning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
from types import MappingProxyType
from typing import cast

from loom.fingerprints import hash_mapping, hash_text
from loom.pipeline.runtime.options import RunOptions
from loom.serialization import PlainData

from ._remote_stage_execution import ResidentProfileDescriptor
from .errors import QueueConfigError, QueueError, QueueServiceError
from .models import validate_queue_id
from .preparation import PrepareRunRequest


_IMPLEMENTED_MODES = frozenset({"shared", "staged"})


@dataclass(frozen=True, slots=True)
class PreparationSourceRoot:
    path: Path
    shared_snapshot_root: Path | None

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "path": str(self.path),
            "shared_snapshot_root": None if self.shared_snapshot_root is None else str(self.shared_snapshot_root),
        }


@dataclass(frozen=True, slots=True)
class PreparationProfile:
    descriptor: ResidentProfileDescriptor
    allowed_source_roots: tuple[str, ...]
    source_modes: tuple[str, ...]
    runtime_options: RunOptions

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "profile_descriptor": self.descriptor.to_dict(),
            "allowed_source_roots": list(self.allowed_source_roots),
            "source_modes": list(self.source_modes),
            "runtime_options": self.runtime_options.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PreparationPolicy:
    """Validated protected policy; only effective aliases are safe to advertise."""

    source_roots: Mapping[str, PreparationSourceRoot]
    profiles: Mapping[str, PreparationProfile]

    @property
    def effective_profiles(self) -> tuple[str, ...]:
        return tuple(sorted(alias for alias, profile in self.profiles.items()
                            if _IMPLEMENTED_MODES.intersection(profile.source_modes)))

    @property
    def effective_roots(self) -> tuple[str, ...]:
        return tuple(sorted({root for alias in self.effective_profiles
                             for root in self.profiles[alias].allowed_source_roots}))

    @property
    def effective_modes(self) -> tuple[str, ...]:
        return tuple(sorted({mode for profile in self.profiles.values()
                             for mode in profile.source_modes if mode in _IMPLEMENTED_MODES}))

    def select(self, request: PrepareRunRequest) -> dict[str, PlainData]:
        """Return the private snapshot retained with this accepted request."""
        profile = self.profiles.get(request.preparation_profile)
        if profile is None or request.source.root not in profile.allowed_source_roots:
            raise QueueServiceError("preparation profile/root selection is not allowed")
        if request.source.mode not in _IMPLEMENTED_MODES or request.source.mode not in profile.source_modes:
            raise QueueServiceError("preparation source mode is unsupported")
        root = self.source_roots[request.source.root]
        return {"source_root": root.to_dict(), "profile": profile.to_dict()}

    def safe_identity(self) -> dict[str, object]:
        """Hash private paths/options while retaining the effective policy meaning."""
        return {
            "source_roots": [{
                "alias": alias,
                "path_digest": hash_text(str(root.path)),
                "shared_snapshot_root_digest": None if root.shared_snapshot_root is None else hash_text(str(root.shared_snapshot_root)),
            } for alias, root in sorted(self.source_roots.items())],
            "profiles": [{
                "alias": alias,
                "profile_descriptor": profile.descriptor.to_dict(),
                "allowed_source_roots": list(profile.allowed_source_roots),
                "source_modes": list(profile.source_modes),
                "runtime_options_digest": hash_mapping(profile.runtime_options.to_dict()),
            } for alias, profile in sorted(self.profiles.items())],
            "effective_modes": list(self.effective_modes),
        }


def load_preparation_policy(
    value: object, *, base: Path, descriptors: Sequence[ResidentProfileDescriptor]
) -> PreparationPolicy | None:
    """Decode only explicit roots, qualified descriptor selections and native options.

    Missing and empty sections normalize to disabled. A permission for a future
    input mode never enables it; there need not be a live agent offer at load or
    acceptance. Worker eligibility still checks the selected software identity.
    """
    if value is None or isinstance(value, Mapping) and not value:
        return None
    policy = _mapping(value, "preparation", required={"source_roots", "profiles"})
    raw_roots = _mapping(policy["source_roots"], "preparation source roots")
    raw_profiles = _mapping(policy["profiles"], "preparation profiles")
    if not raw_roots or not raw_profiles:
        raise QueueConfigError("nonempty preparation policy requires roots and profiles")
    roots: dict[str, PreparationSourceRoot] = {}
    for alias, raw in raw_roots.items():
        _alias(alias, "preparation source root")
        data = _mapping(raw, "preparation source root", required={"path"}, optional={"shared_snapshot_root"})
        roots[alias] = PreparationSourceRoot(
            _path(data["path"], base),
            None if data.get("shared_snapshot_root") is None else _path(data["shared_snapshot_root"], base),
        )
    profiles: dict[str, PreparationProfile] = {}
    for alias, raw in raw_profiles.items():
        _alias(alias, "preparation profile")
        data = _mapping(raw, "preparation profile", required={"resident_profile_id", "allowed_source_roots", "source_modes", "runtime_options"})
        profile_id = _alias(data["resident_profile_id"], "resident_profile_id")
        matches = {descriptor for descriptor in descriptors if descriptor.profile_id == profile_id}
        if len(matches) != 1:
            raise QueueConfigError("preparation resident_profile_id must select one qualified descriptor")
        allowed = _strings(data["allowed_source_roots"], "allowed_source_roots")
        if not set(allowed).issubset(roots):
            raise QueueConfigError("preparation profile names an unknown source root")
        modes = _strings(data["source_modes"], "source_modes")
        if not set(modes).issubset({"shared", "staged"}):
            raise QueueConfigError("preparation source mode is invalid")
        if "shared" in modes and any(roots[root].shared_snapshot_root is None for root in allowed):
            raise QueueConfigError("shared preparation requires a shared_snapshot_root for every allowed root")
        try:
            options = RunOptions.from_dict(data["runtime_options"])
        except (TypeError, ValueError) as exc:
            raise QueueConfigError("preparation runtime_options are invalid") from exc
        if options.executor != "local":
            raise QueueConfigError("preparation runtime_options must explicitly select the local managed executor")
        profiles[alias] = PreparationProfile(next(iter(matches)), allowed, modes, options)
    return PreparationPolicy(MappingProxyType(roots), MappingProxyType(profiles))


def _mapping(value: object, label: str, *, required: set[str] | None = None, optional: set[str] | None = None) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise QueueConfigError(f"{label} must be a mapping")
    if required is not None and (not required.issubset(value) or not set(value).issubset(required | (optional or set()))):
        raise QueueConfigError(f"{label} fields are invalid")
    return cast(Mapping[str, object], value)


def _alias(value: object, label: str) -> str:
    try:
        return validate_queue_id(value, label)
    except QueueError as exc:
        raise QueueConfigError(f"{label} is invalid") from exc


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value or any(not isinstance(item, str) or not item for item in value):
        raise QueueConfigError(f"preparation {label} must be a nonempty sequence")
    return tuple(sorted(set(value)))


def _path(value: object, base: Path) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise QueueConfigError("preparation root path is invalid")
    path = Path(value)
    return Path(os.path.normpath(path if path.is_absolute() else base / path))

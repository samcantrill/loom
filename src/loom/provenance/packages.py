"""Dependency provenance capture."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version

from .errors import ProvenanceCaptureError
from .models import DependencyProvenance


def capture_dependency_provenance(
    packages: tuple[str, ...] = ("loom",),
    *,
    strict: bool = False,
) -> DependencyProvenance:
    versions: dict[str, str] = {}
    missing: list[str] = []

    for package_name in packages:
        try:
            versions[package_name] = package_version(package_name)
            continue
        except PackageNotFoundError:
            missing.append(package_name)
            if strict:
                raise ProvenanceCaptureError(f"Package not found: {package_name!r}")

    return DependencyProvenance(packages=versions, missing_packages=tuple(missing))

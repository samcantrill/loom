"""Core runtime imports."""

from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from loom._run import RunOutcome
    from loom.queue.run import RunRequest

from loom.artifacts import ArtifactAddress, ArtifactRef
from loom.fingerprints import Fingerprint, hash_mapping
from loom.records import InMemoryManifest, ManifestView, Record
from loom.refs import ResourceRef

try:
    __version__ = version("loom")
except PackageNotFoundError:
    __version__ = "0.1.0"


def run(
    request: "RunRequest",
    *,
    deployment: "str | Path",
    wait: bool = True,
    timeout_seconds: float | None = None,
    expected_coordinator_id: str | None = None,
) -> "RunOutcome":
    """Start selected services, optionally pinning their owner, and observe the exact run."""
    from loom._run import run as managed_run

    return managed_run(
        request, deployment=deployment, wait=wait, timeout_seconds=timeout_seconds,
        expected_coordinator_id=expected_coordinator_id,
    )


__all__ = [
    "__version__",
    "run",
    "ResourceRef",
    "InMemoryManifest",
    "ManifestView",
    "Record",
    "ArtifactAddress",
    "ArtifactRef",
    "Fingerprint",
    "hash_mapping",
]

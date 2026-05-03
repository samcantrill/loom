"""Core runtime imports."""

from importlib.metadata import PackageNotFoundError, version

from loom.artifacts import ArtifactRef
from loom.fingerprints import Fingerprint, hash_mapping
from loom.records import InMemoryManifest, ManifestView, Record
from loom.refs import ResourceRef

try:
    __version__ = version("loom")
except PackageNotFoundError:
    __version__ = "0.1.0"

__all__ = [
    "__version__",
    "ResourceRef",
    "InMemoryManifest",
    "ManifestView",
    "Record",
    "ArtifactRef",
    "Fingerprint",
    "hash_mapping",
]

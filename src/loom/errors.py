"""Error hierarchy for loom."""


class LoomError(Exception):
    """Base exception for loom."""


class ValidationError(LoomError):
    """Error raised for invalid validation state."""


class ContractError(LoomError):
    """Error raised for protocol or contract violations."""


class ResourceError(LoomError):
    """Error raised for invalid resource references."""


class ArtifactError(LoomError):
    """Error raised for artifact-level failures."""


class ConfigError(LoomError):
    """Error raised for config-related operations."""


class PipelineError(LoomError):
    """Error raised for pipeline-level failures."""


class SerializationError(LoomError):
    """Error raised for serialization and de-serialization failures."""


class FingerprintError(LoomError):
    """Error raised for fingerprint or digest failures."""


class ExecutionError(LoomError):
    """Error raised for execution-level failures."""


class ProvenanceError(LoomError):
    """Error raised for provenance capture or provenance data errors."""


class IOErrorBase(LoomError):
    """Base error for Loom I/O operations."""


__all__ = [
    "LoomError",
    "ValidationError",
    "ContractError",
    "ResourceError",
    "ArtifactError",
    "ConfigError",
    "SerializationError",
    "FingerprintError",
    "PipelineError",
    "ExecutionError",
    "ProvenanceError",
    "IOErrorBase",
]

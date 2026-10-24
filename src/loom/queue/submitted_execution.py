"""Submission-owned container identity, independent of installed host software.

Images are already published on protected shared storage. This contract transports
their identity, never image bytes, host executables, mounts or runtime options.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import stat
from typing import cast

from loom.fingerprints import hash_mapping, validate_digest
from loom.pipeline.orchestration import SubmittedContainerRequirement
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from .errors import QueueServiceError
from .models import validate_queue_id
from .shared_execution import has_input_directories, location, qualified_roots


SUBMITTED_CONTAINER_WORKER_CONTRACT = "resident-submitted-container-v1"
INPUT_DIRECTORY_WORKER_CONTRACT = "resident-submitted-container-v2"
SUPPORTED_WORKER_CONTRACTS = (SUBMITTED_CONTAINER_WORKER_CONTRACT, INPUT_DIRECTORY_WORKER_CONTRACT)
SUBMITTED_CONTAINER_CAPABILITY = "submitted-container-execution-v1"
SUBMITTED_EXECUTION_SCOPE = "loom.submitted_execution"

_WORKER_BOOTSTRAP = """\
import runpy, sys
from pathlib import Path
from loom.queue import submitted_execution as implementation
required = sys.argv.pop(1)
supported = getattr(implementation, "SUPPORTED_WORKER_CONTRACTS", (implementation.SUBMITTED_CONTAINER_WORKER_CONTRACT,))
if required not in supported:
    message = "Selected workload image does not support required worker contract: " + required
    logs = Path(sys.argv[-1]) / "logs"
    logs.mkdir(exist_ok=True)
    with (logs / "stderr.log").open("a") as output:
        output.write(message + "\\n")
    raise SystemExit(message)
sys.argv[0] = "loom.queue._resident_stage_worker"
runpy.run_module(sys.argv[0], run_name="__main__")
"""


def submitted_worker_command(execution: SubmittedContainerExecution, workspace: Path) -> tuple[str, ...]:
    """Check newer worker contracts in the selected image before request decoding.

    Legacy commands remain byte-for-byte unchanged for retained launch replay.
    The fixed bootstrap executes through the selected image's interpreter.
    Incompatibilities reach assignment stderr before the installed worker starts
    its usual logging and result handling.
    """
    if execution.worker_contract == SUBMITTED_CONTAINER_WORKER_CONTRACT:
        return (execution.python_executable, "-m", "loom.queue._resident_stage_worker",
                "--workspace", str(workspace))
    return (execution.python_executable, "-c", f"exec({_WORKER_BOOTSTRAP!r})", execution.worker_contract,
            "--workspace", str(workspace))


@dataclass(frozen=True, slots=True)
class SubmittedImage:
    """Immutable SIF bytes at a logical shared location.

    ``sha256`` is the complete lowercase hexadecimal SHA-256; ``size_bytes`` is
    the positive file size. A location supplies no host path or mount authority.
    """

    location: Mapping[str, PlainData]
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "location", freeze_plain_data(location(self.location)))
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.sha256)
        ):
            raise QueueServiceError("submitted image sha256 is invalid")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise QueueServiceError("submitted image size_bytes must be positive")

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "location": thaw_plain_data(self.location),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, value: object) -> SubmittedImage:
        if not isinstance(value, Mapping) or set(value) != {
            "location", "sha256", "size_bytes",
        }:
            raise QueueServiceError("submitted image fields are invalid")
        return cls(
            cast(Mapping[str, PlainData], value["location"]),
            cast(str, value["sha256"]),
            cast(int, value["size_bytes"]),
        )


@dataclass(frozen=True, slots=True)
class SubmittedContainerExecution:
    """One retained container for preparation and all managed graph actions.

    ``python_executable`` is a normalized absolute POSIX path *inside* the image.
    It is never resolved on the host. ``project_integration`` uses the native
    versioned preparation processor contract; null selects no project callback.
    """

    runtime: str
    image: SubmittedImage
    python_executable: str
    worker_contract: str
    project_integration: Mapping[str, PlainData] | None = None

    def __post_init__(self) -> None:
        from .preparation import _project_processor

        # Initial delivery is the existing shared SIF adapter. The host policy
        # supplies the actual apptainer/singularity executable and options.
        if self.runtime != "apptainer":
            raise QueueServiceError("submitted container runtime is unsupported")
        if not isinstance(self.image, SubmittedImage):
            raise QueueServiceError("submitted container image is invalid")
        path = self.python_executable
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or path == "/"
            or "\x00" in path
            or "\\" in path
            or ".." in path.split("/")
            or str(PurePosixPath(path)) != path
        ):
            raise QueueServiceError("contained Python must be a normalized absolute path")
        validate_queue_id(self.worker_contract, "submitted worker contract")
        processor = _project_processor(self.project_integration)
        object.__setattr__(
            self, "project_integration",
            None if processor is None else freeze_plain_data(processor),
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": "submitted_container",
            "schema_version": 1,
            "runtime": self.runtime,
            "image": self.image.to_dict(),
            "python_executable": self.python_executable,
            "worker_contract": self.worker_contract,
            "project_integration": thaw_plain_data(self.project_integration),
        }

    @classmethod
    def from_dict(cls, value: object) -> SubmittedContainerExecution:
        if (
            not isinstance(value, Mapping)
            or set(value) != {
                "kind", "schema_version", "runtime", "image", "python_executable",
                "worker_contract", "project_integration",
            }
            or value["kind"] != "submitted_container"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise QueueServiceError("submitted container execution is unsupported")
        return cls(
            cast(str, value["runtime"]),
            SubmittedImage.from_dict(value["image"]),
            cast(str, value["python_executable"]),
            cast(str, value["worker_contract"]),
            cast(Mapping[str, PlainData] | None, value["project_integration"]),
        )


@dataclass(frozen=True, slots=True)
class SubmittedContainerCapability:
    """Portable site permission for submitted SIF execution, without image identity.

    Hosts qualify logical storage permissions using their private paths.
    All workloads admitted by this capability share the host's resource inventory.
    The callback interface versions authorize the existing processor protocol,
    not a project package list.
    """

    policy_id: str
    runtime: str
    worker_contracts: tuple[str, ...]
    allowed_image_roots: tuple[str, ...]
    shared_roots: Mapping[str, PlainData]
    environment_fingerprint: str
    project_integration_versions: tuple[int, ...] = (3,)

    def __post_init__(self) -> None:
        validate_queue_id(self.policy_id, "container policy ID")
        object.__setattr__(
            self, "environment_fingerprint",
            validate_digest(self.environment_fingerprint, algorithms={"sha256"}),
        )
        if self.runtime != "apptainer":
            raise QueueServiceError("container policy runtime is unsupported")
        contracts = self.worker_contracts
        if (
            not isinstance(contracts, (tuple, list))
            or not contracts
            or any(item not in SUPPORTED_WORKER_CONTRACTS for item in contracts)
        ):
            raise QueueServiceError("container policy worker contracts are unsupported")
        object.__setattr__(self, "worker_contracts", tuple(sorted(set(contracts))))
        roots = qualified_roots(self.shared_roots)
        if has_input_directories(roots) and INPUT_DIRECTORY_WORKER_CONTRACT not in contracts:
            raise QueueServiceError("input directories require the resident-submitted-container-v2 worker contract")
        allowed = self.allowed_image_roots
        if (
            not isinstance(allowed, (tuple, list))
            or not allowed
            or any(not isinstance(item, str) or item not in roots for item in allowed)
        ):
            raise QueueServiceError("container policy image roots are invalid")
        if any(cast(Mapping[str, PlainData], roots[item])["access"] != "ro" for item in allowed):
            raise QueueServiceError("container image roots must be read-only for workloads")
        if any("qualification" in cast(Mapping[str, PlainData], roots[item]) for item in allowed):
            raise QueueServiceError("container image roots require challenged storage")
        object.__setattr__(self, "allowed_image_roots", tuple(sorted(set(allowed))))
        object.__setattr__(self, "shared_roots", freeze_plain_data(roots))
        versions = self.project_integration_versions
        if not isinstance(versions, (tuple, list)) or any(
            type(item) is not int or item != 3 for item in versions
        ):
            raise QueueServiceError("container policy project interfaces are unsupported")
        object.__setattr__(self, "project_integration_versions", tuple(sorted(set(versions))))

    def require_execution(self, execution: SubmittedContainerExecution) -> None:
        """Reject unsupported intent before capture or child dispatch."""
        if (
            execution.runtime != self.runtime
            or execution.worker_contract not in self.worker_contracts
            or (has_input_directories(self.shared_roots)
                and execution.worker_contract != INPUT_DIRECTORY_WORKER_CONTRACT)
            or execution.image.location["root_id"] not in self.allowed_image_roots
            or (
                execution.project_integration is not None
                and execution.project_integration["schema_version"]
                not in self.project_integration_versions
            )
        ):
            raise QueueServiceError("submitted execution is not allowed by container policy")

    @property
    def required_worker_contract(self) -> str:
        """Select the least worker contract permitted by this storage policy.

        This is a policy requirement, not evidence of an image's implementation.
        The selected image checks support before decoding the worker request.
        """
        if has_input_directories(self.shared_roots):
            return INPUT_DIRECTORY_WORKER_CONTRACT
        return next(item for item in SUPPORTED_WORKER_CONTRACTS if item in self.worker_contracts)

    def requirement(self, execution: SubmittedContainerExecution) -> SubmittedContainerRequirement:
        """Project eligibility only after this site policy permits the request."""
        self.require_execution(execution)
        return SubmittedContainerRequirement(
            self.policy_id, self.runtime, execution.worker_contract, self.shared_roots,
            self.fingerprint,
        )

    @property
    def workload_roots(self) -> dict[str, PlainData]:
        """Roots visible to contained work; host-only image storage stays outside."""
        return {
            alias: thaw_plain_data(facts)
            for alias, facts in self.shared_roots.items()
            if cast(Mapping[str, PlainData], facts)["container_path"] is not None
        }

    def satisfies(self, requirement: SubmittedContainerRequirement) -> bool:
        return (
            self.policy_id == requirement.policy_id
            and self.fingerprint == requirement.policy_fingerprint
            and self.runtime == requirement.runtime
            and requirement.worker_contract in self.worker_contracts
            and all(
                self.shared_roots.get(alias) == facts
                for alias, facts in requirement.shared_root_requirements.items()
            )
        )

    @property
    def fingerprint(self) -> str:
        return hash_mapping(self.to_dict()).split(":", 1)[1]

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "kind": "submitted_container",
            "schema_version": 1,
            "policy_id": self.policy_id,
            "runtime": self.runtime,
            "worker_contracts": list(self.worker_contracts),
            "allowed_image_roots": list(self.allowed_image_roots),
            "shared_roots": thaw_plain_data(self.shared_roots),
            "environment_fingerprint": self.environment_fingerprint,
            "project_integration_versions": list(self.project_integration_versions),
        }

    @classmethod
    def from_dict(cls, value: object) -> SubmittedContainerCapability:
        if (
            not isinstance(value, Mapping)
            or set(value) != {
                "kind", "schema_version", "policy_id", "runtime", "worker_contracts",
                "allowed_image_roots", "shared_roots", "environment_fingerprint",
                "project_integration_versions",
            }
            or value["kind"] != "submitted_container"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise QueueServiceError("container execution capability is unsupported")
        return cls(
            cast(str, value["policy_id"]),
            cast(str, value["runtime"]),
            cast(tuple[str, ...], value["worker_contracts"]),
            cast(tuple[str, ...], value["allowed_image_roots"]),
            cast(Mapping[str, PlainData], value["shared_roots"]),
            cast(str, value["environment_fingerprint"]),
            cast(tuple[int, ...], value["project_integration_versions"]),
        )


def verify_submitted_image(image: SubmittedImage, roots: Mapping[str, PlainData]) -> Path:
    """Verify immutable image bytes at a physical worker or probe launch boundary."""
    from ._remote_stage_execution import _file_digest
    from .shared_execution import resolve

    root = cast(Mapping[str, PlainData], roots[str(image.location["root_id"])])
    path = resolve(root, str(image.location["path"]))
    details = path.stat()
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_mode & 0o222
        or details.st_size != image.size_bytes
        or _file_digest(path) != image.sha256
    ):
        raise ValueError("submitted image bytes or immutable publication differ from retained intent")
    return path


def retain_submitted_image(
    image: SubmittedImage,
    roots: Mapping[str, PlainData],
    *,
    coordinator_id: str,
    operation_id: str,
) -> None:
    """Pin the published image directory before dispatch, without reading SIF bytes.

    The supervisor verifies bytes at each new physical launch. Retention checks
    only the protected location and publication shape, outside acceptance SQL.
    A crash after the idempotent pin leaves retained storage, never unpinned work.
    """
    from loom.pipeline.cleanup.preparation_pins import retain_preparation_path
    from .shared_execution import resolve

    root = roots.get(str(image.location["root_id"]))
    if not isinstance(root, Mapping):
        raise QueueServiceError("submitted image root is unavailable")
    path = resolve(root, str(image.location["path"]))
    metadata = path.stat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size != image.size_bytes
        or metadata.st_mode & 0o222
        or path.parent == Path(str(root["host_path"]))
    ):
        raise QueueServiceError("submitted image must be a complete read-only file in a published directory")
    retain_preparation_path(
        path.parent, coordinator_id=coordinator_id, operation_id=operation_id,
    )


def submitted_binding(
    value: object,
) -> tuple[SubmittedContainerExecution, SubmittedContainerCapability]:
    """Decode the checked execution selection carried by a stage fingerprint."""
    if not isinstance(value, Mapping) or set(value) != {"execution", "container_capability"}:
        raise QueueServiceError("submitted workload binding is invalid")
    execution = SubmittedContainerExecution.from_dict(value["execution"])
    capability = SubmittedContainerCapability.from_dict(value["container_capability"])
    capability.require_execution(execution)
    return execution, capability


def assignment_binding(
    fingerprint: Mapping[str, PlainData],
) -> tuple[SubmittedContainerExecution, SubmittedContainerCapability] | None:
    payload = cast(Mapping[str, PlainData], fingerprint["payload"])
    fields = cast(Mapping[str, PlainData], payload["fingerprint_fields"])
    if SUBMITTED_EXECUTION_SCOPE not in fields:
        return None
    return submitted_binding(fields[SUBMITTED_EXECUTION_SCOPE])


def _validate_retired_capabilities(previous, replacement):
    """Match narrowed portable permissions to retained policy IDs at retirement.

    The environment digest may change with the explicitly replaced policy's
    environment/scratch mounts. Runtime, roots, image permissions and worker
    interfaces cannot expand or rebind retained portable storage identities.
    """
    from .errors import QueueConflictError

    policies = {value.policy_id: value for value in previous}
    for value in replacement:
        old = policies.get(value.policy_id)
        if (old is None or old.runtime != value.runtime
            or not set(value.worker_contracts) <= set(old.worker_contracts)
            or not set(value.allowed_image_roots) <= set(old.allowed_image_roots)
            or not set(value.project_integration_versions) <= set(old.project_integration_versions)
            or any(old.shared_roots.get(key) != root for key, root in value.shared_roots.items())):
            raise QueueConflictError("coordinator retirement cannot expand or rebind container capability")


def submitted_implementation(
    execution: SubmittedContainerExecution, capability: SubmittedContainerCapability,
) -> dict[str, PlainData]:
    """Portable implementation identity for reconciliation, reuse and recovery.

    Image bytes, contained interpreter/interface, project integration and the
    policy's portable environment participate. Image locations, host runtime
    paths, assignment identities and allocated GPU bindings do not. This is an
    identity projection; new-launch byte verification remains with the supervisor.
    """
    capability.require_execution(execution)
    return {
        "schema_version": 1,
        "kind": "submitted_container",
        "image_sha256": execution.image.sha256,
        "runtime": execution.runtime,
        "python_executable": execution.python_executable,
        "worker_contract": execution.worker_contract,
        "project_integration": None if execution.project_integration is None else thaw_plain_data(execution.project_integration),
        "environment_fingerprint": capability.environment_fingerprint,
    }

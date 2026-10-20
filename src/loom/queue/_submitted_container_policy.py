"""Stable protected host policy projected into assignment-owned container launches."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING, cast

from loom.fingerprints import hash_mapping
from loom.pipeline.executors.apptainer.commands import ApptainerExecOptions
from loom.pipeline.executors.containers import ContainerMount, ContainerOptions
from loom.serialization import PlainData, freeze_plain_data, thaw_plain_data

from ._container_worker import portable_container_settings
from ._temporary_storage import _temporary_targets_for_mounts
from .errors import QueueServiceError
from .shared_execution import project_path, qualified_roots, qualifications, root_bindings
from .submitted_execution import (
    SUBMITTED_CONTAINER_WORKER_CONTRACT,
    SubmittedContainerCapability,
    SubmittedContainerExecution,
)

if TYPE_CHECKING:
    from ._agent_process_supervisor import ResidentWorkerLaunchProfile


@dataclass(frozen=True, slots=True)
class SubmittedContainerPolicy:
    """Host-owned runtime, storage and environment; never an installed image.

    Decoding is IO-free so retained supervisor state remains inspectable when
    storage is unavailable. Live agent activation calls ``qualify`` separately.
    Mounts and runtime options use the existing container adapter contracts.
    """

    policy_id: str
    runtime_options: Mapping[str, PlainData]
    shared_roots: Mapping[str, PlainData]
    allowed_image_roots: tuple[str, ...]
    preparation_shared_roots: Mapping[str, Path] = field(default_factory=dict)
    environment: Mapping[str, str] = field(default_factory=dict)
    mounts: tuple[ContainerMount, ...] = ()
    temporary_mounts: tuple[str, ...] = ()
    worker_contracts: tuple[str, ...] = (SUBMITTED_CONTAINER_WORKER_CONTRACT,)
    project_integration_versions: tuple[int, ...] = (3,)

    def __post_init__(self) -> None:
        from ._agent_process_supervisor import _preparation_root_bindings

        options = ApptainerExecOptions.from_dict(self.runtime_options)
        if not Path(options.command).is_absolute():
            raise QueueServiceError("container policy runtime executable must be absolute")
        object.__setattr__(self, "runtime_options", freeze_plain_data(options.to_dict()))
        object.__setattr__(self, "shared_roots", freeze_plain_data(root_bindings(self.shared_roots)))
        object.__setattr__(self, "preparation_shared_roots", _preparation_root_bindings(self.preparation_shared_roots))
        environment = dict(self.environment)
        if any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in environment.items()
        ):
            raise QueueServiceError("container policy environment is invalid")
        object.__setattr__(self, "environment", freeze_plain_data(environment))
        mounts = tuple(self.mounts)
        if any(not isinstance(item, ContainerMount) for item in mounts):
            raise QueueServiceError("container policy mounts are invalid")
        if len({item.target for item in mounts}) != len(mounts):
            raise QueueServiceError("container policy mount targets must be unique")
        object.__setattr__(self, "mounts", mounts)
        object.__setattr__(self, "temporary_mounts", _temporary_targets_for_mounts(self.temporary_mounts, mounts))
        # Normalize the portable declarations using their single codec.
        capability = self.capability
        object.__setattr__(self, "allowed_image_roots", capability.allowed_image_roots)
        object.__setattr__(self, "worker_contracts", capability.worker_contracts)
        object.__setattr__(self, "project_integration_versions", capability.project_integration_versions)

    @property
    def capability(self) -> SubmittedContainerCapability:
        roots = qualified_roots({
            alias: {key: value for key, value in cast(Mapping[str, PlainData], root).items() if key != "host_path"}
            for alias, root in self.shared_roots.items()
        })
        portable = portable_container_settings(
            {"mounts": [item.to_dict() for item in self.mounts]},
            self.runtime_options,
        )
        environment = hash_mapping({
            **portable,
            "environment": dict(self.environment),
            "temporary_mounts": list(self.temporary_mounts),
        })
        return SubmittedContainerCapability(
            self.policy_id, "apptainer", self.worker_contracts, self.allowed_image_roots,
            roots, environment, self.project_integration_versions,
        )

    @property
    def fingerprint(self) -> str:
        """Private launch authorization, including host paths."""
        return hash_mapping(self.to_dict()).split(":", 1)[1]

    def qualify(self) -> SubmittedContainerCapability:
        """Check host runtime and bounded shared-root challenges, without images."""
        command = str(self.runtime_options["command"])
        if not Path(command).is_file() or not os.access(command, os.X_OK):
            raise QueueServiceError("container policy runtime is unavailable")
        result = subprocess.run(
            [command, "--version"], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False,
        )
        if result.returncode:
            raise QueueServiceError("container policy runtime probe failed")
        capability = self.capability
        if qualifications(self.shared_roots) != capability.shared_roots:
            raise QueueServiceError("container policy shared roots changed")
        return capability

    def launch_profile(
        self, execution: SubmittedContainerExecution, *, workspace: Path,
    ) -> ResidentWorkerLaunchProfile:
        """Pure projection for new launch and saved-launch comparison."""
        from ._agent_process_supervisor import ResidentWorkerLaunchProfile

        capability = self.capability
        capability.require_execution(execution)
        root = cast(Mapping[str, PlainData], self.shared_roots[str(execution.image.location["root_id"])])
        image = project_path(root, str(execution.image.location["path"]))
        container = ContainerOptions(image=str(image), mounts=self.mounts)
        return ResidentWorkerLaunchProfile(
            project_root=workspace,
            python_executable=Path(execution.python_executable),
            descriptor=capability.to_dict(),
            environment=dict(self.environment),
            preparation_shared_roots=self.preparation_shared_roots,
            shared_roots=self.shared_roots,
            temporary_mounts=self.temporary_mounts,
            container={
                "kind": "apptainer",
                "container": container.to_dict(),
                "options": thaw_plain_data(self.runtime_options),
                "python_executable": execution.python_executable,
                "daemon_endpoint": None,
            },
            submitted_execution=execution,
        )

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": 1,
            "policy_id": self.policy_id,
            "runtime_options": thaw_plain_data(self.runtime_options),
            "shared_roots": thaw_plain_data(self.shared_roots),
            "allowed_image_roots": list(self.allowed_image_roots),
            "preparation_shared_roots": {alias: str(path) for alias, path in self.preparation_shared_roots.items()},
            "environment": dict(self.environment),
            "mounts": [item.to_dict() for item in self.mounts],
            "temporary_mounts": list(self.temporary_mounts),
            "worker_contracts": list(self.worker_contracts),
            "project_integration_versions": list(self.project_integration_versions),
        }

    @classmethod
    def from_dict(cls, value: object) -> SubmittedContainerPolicy:
        if (
            not isinstance(value, Mapping)
            or set(value) != {
                "schema_version", "policy_id", "runtime_options", "shared_roots",
                "allowed_image_roots", "preparation_shared_roots", "environment",
                "mounts", "temporary_mounts", "worker_contracts",
                "project_integration_versions",
            }
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or not isinstance(value["mounts"], (tuple, list))
        ):
            raise QueueServiceError("submitted container policy fields are unsupported")
        return cls(
            policy_id=cast(str, value["policy_id"]),
            runtime_options=cast(Mapping[str, PlainData], value["runtime_options"]),
            shared_roots=cast(Mapping[str, PlainData], value["shared_roots"]),
            allowed_image_roots=cast(tuple[str, ...], value["allowed_image_roots"]),
            preparation_shared_roots=cast(Mapping[str, Path], value["preparation_shared_roots"]),
            environment=cast(Mapping[str, str], value["environment"]),
            mounts=tuple(ContainerMount.from_dict(item) for item in value["mounts"]),
            temporary_mounts=cast(tuple[str, ...], value["temporary_mounts"]),
            worker_contracts=cast(tuple[str, ...], value["worker_contracts"]),
            project_integration_versions=cast(tuple[int, ...], value["project_integration_versions"]),
        )

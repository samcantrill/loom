"""Fixed one-shot SLURM bootstrap using protected out-of-band configuration."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Mapping, cast
from uuid import uuid4

from loom.pipeline.execution.stage_worker import execute_resident_stage_worker_request
from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.scheduling import SchedulingComponentDescriptor
from loom.serialization import PlainData, thaw_plain_data

from ._remote_stage_execution import _decode_chunk
from .agent_session_transport import (
    AgentTlsClientConfig,
    LocalDaemonAgentHttpClient,
)
from .errors import QueueConflictError, QueueServiceError
from .slurm_ready_stage import SlurmBootstrapWorkspace, SlurmStageDelivery


SLURM_BOOTSTRAP_CONFIG_ENV = "LOOM_SLURM_BOOTSTRAP_CONFIG"
_ROLE = "slurm_bootstrap"


@dataclass(frozen=True, slots=True)
class SlurmBootstrapClientConfig:
    """Protected compute-side composition; this value never enters the script."""

    url: str
    server_ca_path: Path
    certificate_path: Path
    private_key_path: Path
    workspace_root: Path
    project_root: Path
    profile_id: str
    profile_configuration_fingerprint: str
    credential_policy_revision: str
    project_fingerprint: str
    environment_fingerprint: str
    executor_fingerprint: str
    executor_name: str

    def __post_init__(self) -> None:
        for name in (
            "profile_id",
            "profile_configuration_fingerprint",
            "credential_policy_revision",
            "project_fingerprint",
            "environment_fingerprint",
            "executor_fingerprint",
            "executor_name",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise QueueServiceError(f"SLURM bootstrap {name} is invalid")
        if self.executor_name != "local":
            raise QueueServiceError("SLURM bootstrap executor is unsupported")
        workspace = Path(self.workspace_root).resolve()
        project = Path(self.project_root).resolve()
        if not project.is_dir():
            raise QueueServiceError("SLURM resident project root is unavailable")
        workspace.mkdir(parents=True, exist_ok=True)
        workspace.chmod(0o700)
        if stat.S_IMODE(workspace.stat().st_mode) & 0o077:
            raise QueueServiceError("SLURM bootstrap workspace must be private")
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "project_root", project)

    @property
    def tls(self) -> AgentTlsClientConfig:
        return AgentTlsClientConfig(
            url=self.url,
            server_ca_path=self.server_ca_path,
            certificate_path=self.certificate_path,
            private_key_path=self.private_key_path,
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "SlurmBootstrapClientConfig":
        source = Path(path)
        if not source.is_file() or stat.S_IMODE(source.stat().st_mode) & 0o077:
            raise QueueServiceError("SLURM bootstrap config must be a private file")
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QueueServiceError("SLURM bootstrap config is invalid") from exc
        expected = {
            "url",
            "server_ca_path",
            "certificate_path",
            "private_key_path",
            "workspace_root",
            "project_root",
            "profile_id",
            "profile_configuration_fingerprint",
            "credential_policy_revision",
            "project_fingerprint",
            "environment_fingerprint",
            "executor_fingerprint",
            "executor_name",
        }
        if (
            not isinstance(value, Mapping)
            or set(value) != expected
            or any(
                not isinstance(value[key], str) or not value[key] for key in expected
            )
        ):
            raise QueueServiceError("SLURM bootstrap config fields are invalid")
        return cls(
            url=cast(str, value["url"]),
            server_ca_path=Path(cast(str, value["server_ca_path"])),
            certificate_path=Path(cast(str, value["certificate_path"])),
            private_key_path=Path(cast(str, value["private_key_path"])),
            workspace_root=Path(cast(str, value["workspace_root"])),
            project_root=Path(cast(str, value["project_root"])),
            profile_id=cast(str, value["profile_id"]),
            profile_configuration_fingerprint=cast(
                str, value["profile_configuration_fingerprint"]
            ),
            credential_policy_revision=cast(str, value["credential_policy_revision"]),
            project_fingerprint=cast(str, value["project_fingerprint"]),
            environment_fingerprint=cast(str, value["environment_fingerprint"]),
            executor_fingerprint=cast(str, value["executor_fingerprint"]),
            executor_name=cast(str, value["executor_name"]),
        )


def load_slurm_bootstrap_config() -> SlurmBootstrapClientConfig:
    value = os.environ.get(SLURM_BOOTSTRAP_CONFIG_ENV)
    if not value:
        raise QueueServiceError("protected SLURM bootstrap config is unavailable")
    return SlurmBootstrapClientConfig.from_file(value)


def run_slurm_bootstrap(
    *,
    operation_id: str,
    request_digest: str,
    config: SlurmBootstrapClientConfig | None = None,
) -> None:
    """Drive one exact bootstrap from registration through verified result commit."""

    selected = config or load_slurm_bootstrap_config()
    # The protected path is bootstrap-only capability material. Authored stage
    # code runs later in this process and must not inherit its location.
    os.environ.pop(SLURM_BOOTSTRAP_CONFIG_ENV, None)
    job_id = os.environ.get("SLURM_JOB_ID")
    if not job_id or not job_id.isdecimal():
        raise QueueServiceError("SLURM_JOB_ID is unavailable or invalid")
    cluster = os.environ.get("SLURM_CLUSTER_NAME")
    incarnation = _operation_incarnation(selected.workspace_root, operation_id)
    client = LocalDaemonAgentHttpClient(selected.tls)
    try:
        handshake = client.handshake(role=_ROLE)
        capabilities = handshake.get("capabilities")
        descriptor = SchedulingComponentDescriptor.from_dict(
            thaw_plain_data(
                handshake.get("profile_descriptor"), path="SLURM profile descriptor"
            )
        )
        if (
            handshake.get("profile_id") != selected.profile_id
            or descriptor.configuration_fingerprint
            != selected.profile_configuration_fingerprint
            or handshake.get("credential_policy_revision")
            != selected.credential_policy_revision
            or not isinstance(capabilities, (list, tuple))
            or "slurm-ready-stage-bootstrap-v1" not in capabilities
        ):
            raise QueueConflictError("SLURM bootstrap profile handshake conflicts")
        registration = client.call_application(
            _ROLE,
            "register",
            {
                "operation_id": operation_id,
                "request_digest": request_digest,
                "job_id": job_id,
                "cluster": cluster,
                "incarnation": incarnation,
            },
        )
        assignment_id = _string(registration, "assignment_id")
        delivery = SlurmStageDelivery.from_dict(
            thaw_plain_data(registration.get("delivery"), path="SLURM delivery")
        )
        if (
            delivery.assignment_id != assignment_id
            or delivery.profile_id != selected.profile_id
            or delivery.project_fingerprint != selected.project_fingerprint
            or delivery.environment_fingerprint != selected.environment_fingerprint
            or delivery.executor_fingerprint != selected.executor_fingerprint
            or delivery.executor_name != selected.executor_name
        ):
            raise QueueConflictError("SLURM resident profile identity conflicts")
        workspace = SlurmBootstrapWorkspace(selected.workspace_root, assignment_id)
        workspace.persist_delivery(delivery)
        for item in delivery.inputs:
            offset = 0
            while True:
                response = client.call_application(
                    _ROLE,
                    "input",
                    {
                        "assignment_id": assignment_id,
                        "incarnation": incarnation,
                        "transfer_id": item.transfer_id,
                        "offset": offset,
                    },
                )
                data = _decode_chunk(response.get("data"))
                final = response.get("final")
                if not isinstance(final, bool):
                    raise QueueServiceError("SLURM input response is invalid")
                offset = workspace.stage_input_chunk(
                    item.transfer_id, offset, data, final=final
                )
                if final:
                    break
        workspace.accept_inputs()
        client.call_application(
            _ROLE,
            "inputs_ready",
            {"assignment_id": assignment_id, "incarnation": incarnation},
        )
        grant = client.call_application(
            _ROLE,
            "grant",
            {"assignment_id": assignment_id, "incarnation": incarnation},
        )
        fence = _string(grant, "fence")
        permit = client.call_application(
            _ROLE,
            "start",
            {
                "assignment_id": assignment_id,
                "incarnation": incarnation,
                "fence": fence,
            },
        )
        permitted = permit.get("permitted")
        if not isinstance(permitted, bool):
            raise QueueServiceError("SLURM start-permit response is invalid")
        if permitted:
            process_execution_id = "slurm-root-" + _sha256(
                assignment_id + "\0" + incarnation
            )
            client.call_application(
                _ROLE,
                "started",
                {
                    "assignment_id": assignment_id,
                    "incarnation": incarnation,
                    "fence": fence,
                    "process_execution_id": process_execution_id,
                },
            )
            os.chdir(selected.project_root)
            if str(selected.project_root) not in sys.path:
                sys.path.insert(0, str(selected.project_root))
            result = execute_resident_stage_worker_request(
                worker_request=workspace.worker_request(),
                workspace_root=workspace.root,
            )
            report = workspace.retain_result(result)
        else:
            report = workspace.retained_report()
            if report is None:
                raise QueueConflictError(
                    "SLURM authored-root permit is consumed without a retained result"
                )
        client.call_application(
            _ROLE,
            "report",
            {
                "assignment_id": assignment_id,
                "incarnation": incarnation,
                "fence": fence,
                "report": report.to_dict(),
            },
        )
        for output in report.outputs:
            offset = 0
            while True:
                data, final = workspace.output_chunk(output.transfer_id, offset)
                response = client.call_application(
                    _ROLE,
                    "output",
                    {
                        "assignment_id": assignment_id,
                        "incarnation": incarnation,
                        "transfer_id": output.transfer_id,
                        "offset": offset,
                        "data": _encode(data),
                        "final": final,
                    },
                )
                received = response.get("received")
                if isinstance(received, bool) or not isinstance(received, int):
                    raise QueueServiceError("SLURM output response is invalid")
                offset = received
                if final:
                    break
        client.call_application(
            _ROLE,
            "result",
            {
                "assignment_id": assignment_id,
                "incarnation": incarnation,
                "fence": fence,
            },
        )
        client.call_application(
            _ROLE,
            "release",
            {"assignment_id": assignment_id, "incarnation": incarnation},
        )
    finally:
        client.close()


def _operation_incarnation(root: Path, operation_id: str) -> str:
    if not operation_id or any(ord(char) < 32 for char in operation_id):
        raise QueueServiceError("SLURM operation identity is invalid")
    path = root / "operations" / _sha256(operation_id) / "incarnation"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
        raise QueueServiceError("SLURM bootstrap incarnation is corrupt")
    value = "bootstrap-" + uuid4().hex
    atomic_write_bytes(path, (value + "\n").encode())
    path.chmod(0o600)
    return value


def _string(value: Mapping[str, PlainData], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise QueueServiceError(f"SLURM bootstrap {key} is invalid")
    return item


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


__all__ = [
    "SLURM_BOOTSTRAP_CONFIG_ENV",
    "SlurmBootstrapClientConfig",
    "load_slurm_bootstrap_config",
    "run_slurm_bootstrap",
]

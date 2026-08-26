"""Explicit ready-stage SLURM mapping and at-most-one submission ownership."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import cast

from loom.pipeline.runtime.placement import ExecutionRouteKind, ResolvedStagePlacement
from loom.scheduling import SchedulingComponentDescriptor
from loom.serialization import PlainData, stable_json_dumps
from loom.timestamps import utc_timestamp

from .commands import (
    SlurmCommandResult,
    SlurmCommandRunner,
    parse_sbatch_parsable_output,
)
from .errors import SlurmPlanningError, SlurmResourceMappingError
from .rendering import render_sbatch_directive
from .resources import SlurmSbatchDirective, map_slurm_resources


READY_STAGE_REQUEST_SCHEMA_VERSION = 3
READY_STAGE_SUBMISSION_SCHEMA_VERSION = 3
_HELPER_ENVELOPE_VERSION = 2
_PROFILE_IMPLEMENTATION_FINGERPRINT = "loom.slurm.ready-stage-profile.v1"
_OPERATION_MARKER_PREFIX = "loom-op-v1:"
_SUBMISSION_TABLE = "ready_stage_submissions"


@dataclass(frozen=True, slots=True)
class SlurmContainmentReceipt:
    """A bounded site-owned proof for one retained ready-stage operation."""

    state: str
    evidence_id: str | None = None
    evidence_revision: str | None = None
    echo: Mapping[str, PlainData] | None = None

    @property
    def contained(self) -> bool:
        return self.state == "CONTAINED"


@dataclass(frozen=True, slots=True)
class SlurmContainmentHelper:
    """One protected, retained site helper invocation.

    This is deliberately a process boundary rather than a composition-time
    Python callback.  The descriptor and executable identity are incorporated
    into the retained profile fingerprint below.
    """

    descriptor: str
    argv: tuple[str, ...]
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        _safe_text(self.descriptor)
        if not self.argv or any(not isinstance(value, str) or not value for value in self.argv):
            raise SlurmPlanningError("SLURM containment helper command is invalid")
        if not isinstance(self.timeout_seconds, (int, float)) or self.timeout_seconds <= 0:
            raise SlurmPlanningError("SLURM containment helper timeout is invalid")

    def resolve(self, request: Mapping[str, PlainData]) -> Mapping[str, PlainData] | None:
        try:
            completed = subprocess.run(
                self.argv,
                input=stable_json_dumps(dict(request)).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=float(self.timeout_seconds),
            )
            if completed.returncode != 0 or len(completed.stdout) > 16_384:
                return None
            value = json.loads(completed.stdout.decode("utf-8"))
            return cast(Mapping[str, PlainData], value) if isinstance(value, Mapping) else None
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError, json.JSONDecodeError):
            return None


def resolve_slurm_containment(
    profile: "SlurmReadyStageProfile", request: Mapping[str, PlainData]
) -> SlurmContainmentReceipt:
    """Ask one retained protected helper, failing closed on every weak result."""

    helper = profile.containment_helper
    if helper is None:
        return SlurmContainmentReceipt("UNKNOWN")
    try:
        value = helper.resolve(request)
        if not isinstance(value, Mapping) or set(value) != {
            "state", "evidence_id", "evidence_revision", "echo"
        }:
            return SlurmContainmentReceipt("UNKNOWN")
        if value["state"] != "CONTAINED":
            return SlurmContainmentReceipt("UNKNOWN")
        evidence_id = value["evidence_id"]
        evidence_revision = value["evidence_revision"]
        echo = value["echo"]
        if (
            not isinstance(evidence_id, str)
            or not evidence_id
            or not isinstance(evidence_revision, str)
            or not evidence_revision
            or not isinstance(echo, Mapping)
            or dict(echo) != dict(request)
        ):
            return SlurmContainmentReceipt("UNKNOWN")
        return SlurmContainmentReceipt(
            "CONTAINED", evidence_id=evidence_id,
            evidence_revision=evidence_revision, echo=cast(Mapping[str, PlainData], echo)
        )
    except Exception:
        return SlurmContainmentReceipt("UNKNOWN")


@dataclass(frozen=True, slots=True)
class JobPrivateFilePrepared:
    """The only durable view of a site-provided allocation capability."""

    receipt: str
    verifier: str
    expires_at: str
    path: str
    descriptor: str

    def __post_init__(self) -> None:
        for value in (
            self.receipt,
            self.verifier,
            self.expires_at,
            self.path,
            self.descriptor,
        ):
            _safe_text(value)


class SlurmJobPrivateFileProvider:
    """Concrete protected-profile binding for ``job_private_file_v1``.

    This deliberately is not a provider protocol: deployment composition owns
    one site helper invocation.  The helper owns generation, durable replay,
    protected allocation staging, and revocation; Loom sees verifier-only
    results.
    """

    delivery_kind = "job_private_file_v1"

    def __init__(
        self,
        *,
        fixed_path: str,
        descriptor: str,
        helper_argv: Sequence[str],
    ) -> None:
        _safe_text(fixed_path)
        _safe_text(descriptor)
        argv = tuple(helper_argv)
        if not argv or any(
            not isinstance(item, str) or not item or "\x00" in item for item in argv
        ):
            raise SlurmPlanningError("job-private capability helper is invalid")
        self.fixed_path = fixed_path
        self.descriptor = descriptor
        self._helper_argv = argv

    def prepare(
        self, *, operation_id: str, request_digest: str
    ) -> JobPrivateFilePrepared:
        operation_id = _safe_text(operation_id)
        request_digest = _safe_text(request_digest)
        result = self._invoke(
            {
                "version": _HELPER_ENVELOPE_VERSION,
                "action": "prepare",
                "operation_id": operation_id,
                "request_digest": request_digest,
                "fixed_path": self.fixed_path,
                "descriptor": self.descriptor,
            }
        )
        expected = {
            "version",
            "action",
            "operation_id",
            "request_digest",
            "receipt",
            "verifier",
            "expires_at",
            "path",
            "descriptor",
        }
        if (
            set(result) != expected
            or result.get("version") != _HELPER_ENVELOPE_VERSION
            or result.get("action") != "prepare"
        ):
            raise SlurmPlanningError("job-private capability helper result is invalid")
        if (
            result.get("operation_id") != operation_id
            or result.get("request_digest") != request_digest
        ):
            raise SlurmPlanningError("job-private capability helper identity conflicts")
        if (
            result.get("path") != self.fixed_path
            or result.get("descriptor") != self.descriptor
        ):
            raise SlurmPlanningError("job-private capability helper binding conflicts")
        verifier = result.get("verifier")
        if (
            not isinstance(verifier, str)
            or len(verifier) != 64
            or any(char not in "0123456789abcdef" for char in verifier)
        ):
            raise SlurmPlanningError("job-private capability verifier is invalid")
        return JobPrivateFilePrepared(
            receipt=cast(str, result["receipt"]),
            verifier=verifier,
            expires_at=cast(str, result["expires_at"]),
            path=cast(str, result["path"]),
            descriptor=cast(str, result["descriptor"]),
        )

    def revoke(self, prepared: JobPrivateFilePrepared) -> None:
        """Request definite terminal cleanup without passing capability material."""

        result = self._invoke(
            {
                "version": _HELPER_ENVELOPE_VERSION,
                "action": "revoke",
                "receipt": prepared.receipt,
                "verifier": prepared.verifier,
                "path": prepared.path,
                "descriptor": prepared.descriptor,
            }
        )
        if result != {
            "version": _HELPER_ENVELOPE_VERSION,
            "action": "revoke",
            "receipt": prepared.receipt,
        }:
            raise SlurmPlanningError(
                "job-private capability helper revocation is invalid"
            )

    def _invoke(self, request: Mapping[str, object]) -> Mapping[str, object]:
        import subprocess

        payload = stable_json_dumps(cast(dict[str, PlainData], request))
        try:
            completed = subprocess.run(
                self._helper_argv,
                input=payload + "\n",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"PATH": os.defpath},
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SlurmPlanningError(
                "job-private capability helper is unavailable"
            ) from exc
        if completed.returncode != 0 or len(completed.stdout) > 4096:
            raise SlurmPlanningError("job-private capability helper is unavailable")
        try:
            return _mapping(
                json.loads(completed.stdout), "job-private capability helper result"
            )
        except (json.JSONDecodeError, SlurmPlanningError) as exc:
            raise SlurmPlanningError(
                "job-private capability helper result is invalid"
            ) from exc


class ReadyStageState(StrEnum):
    INTENT = "intent"
    SUBMITTING = "submitting"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class SlurmReadyStageProfile:
    """Protected site-owned profile for one concrete ready-stage route."""

    profile_id: str
    partition: str
    max_outstanding: int
    bootstrap_argv: tuple[str, ...]
    runner: SlurmCommandRunner
    command_adapter_fingerprint: str
    bootstrap_principal_id: str
    credential_reference: str
    coordinator_endpoint: str
    project_fingerprint: str
    environment_fingerprint: str
    executor_fingerprint: str
    job_private_file_provider: SlurmJobPrivateFileProvider
    executor_name: str = "local"
    credential_policy_revision: str = "slurm-policy-1"
    account: str | None = None
    qos: str | None = None
    cluster: str | None = None
    available: bool = True
    containment_helper: SlurmContainmentHelper | None = field(default=None, repr=False)
    descriptor: SchedulingComponentDescriptor = field(init=False)

    def __post_init__(self) -> None:
        for value in (
            self.profile_id,
            self.partition,
            self.command_adapter_fingerprint,
            self.bootstrap_principal_id,
            self.credential_reference,
            self.coordinator_endpoint,
            self.project_fingerprint,
            self.environment_fingerprint,
            self.executor_fingerprint,
            self.executor_name,
            self.credential_policy_revision,
        ):
            _safe_text(value)
        for value in (self.account, self.qos, self.cluster):
            if value is not None:
                _safe_text(value)
        if (
            isinstance(self.max_outstanding, bool)
            or not isinstance(self.max_outstanding, int)
            or not 1 <= self.max_outstanding <= 10_000
        ):
            raise SlurmPlanningError("ready-stage profile limit is invalid")
        if not isinstance(self.available, bool):
            raise SlurmPlanningError("ready-stage profile availability is invalid")
        if self.executor_name != "local":
            raise SlurmPlanningError(
                "ready-stage profile executor is not supported by the fixed bootstrap"
            )
        if not isinstance(self.job_private_file_provider, SlurmJobPrivateFileProvider):
            raise SlurmPlanningError("ready-stage profile requires job_private_file_v1")
        argv = tuple(self.bootstrap_argv)
        if argv != ("loom", "slurm-bootstrap"):
            raise SlurmPlanningError(
                "ready-stage profile must invoke the fixed Loom bootstrap"
            )
        object.__setattr__(self, "bootstrap_argv", argv)
        payload = {
            "profile_id": self.profile_id,
            "partition": self.partition,
            "account": self.account,
            "qos": self.qos,
            "cluster": self.cluster,
            "max_outstanding": self.max_outstanding,
            "bootstrap_argv": list(argv),
            "command_adapter_fingerprint": self.command_adapter_fingerprint,
            "bootstrap_principal_id": self.bootstrap_principal_id,
            "credential_reference_digest": _digest(self.credential_reference),
            "coordinator_endpoint_digest": _digest(self.coordinator_endpoint),
            "project_fingerprint": self.project_fingerprint,
            "environment_fingerprint": self.environment_fingerprint,
            "executor_fingerprint": self.executor_fingerprint,
            "executor_name": self.executor_name,
            "credential_policy_revision": self.credential_policy_revision,
            "capability_delivery_kind": self.job_private_file_provider.delivery_kind,
            "capability_descriptor": self.job_private_file_provider.descriptor,
            "capability_path": self.job_private_file_provider.fixed_path,
            "containment_helper_descriptor": (
                None if self.containment_helper is None else self.containment_helper.descriptor
            ),
            "containment_helper_argv": (
                None if self.containment_helper is None else list(self.containment_helper.argv)
            ),
        }
        object.__setattr__(
            self,
            "descriptor",
            SchedulingComponentDescriptor(
                kind="slurm_profile",
                contract_version=1,
                implementation_version="1",
                implementation_fingerprint=_PROFILE_IMPLEMENTATION_FINGERPRINT,
                configuration_fingerprint=_digest(stable_json_dumps(payload)),
            ),
        )

    @property
    def configuration_fingerprint(self) -> str:
        return self.descriptor.configuration_fingerprint

    def preflight(self, *, started_after: str | None = None) -> str | None:
        """Validate required command and durable discovery capabilities."""

        del started_after
        if not self.available:
            return "slurm_profile_unavailable"
        try:
            for command in ("sbatch", "squeue", "sacct", "scancel"):
                self.runner.require(command)
            if not callable(self.runner.discover_live_operations) or not callable(
                self.runner.discover_accounted_operations
            ):
                return "slurm_profile_operation_discovery_unavailable"
        except Exception:
            return "slurm_profile_operation_discovery_unavailable"
        return None


@dataclass(frozen=True, slots=True)
class SlurmReadyStageRequest:
    operation_id: str
    stage_work_id: str
    run_uri: str
    attempt_id: str
    profile_id: str
    profile_descriptor: SchedulingComponentDescriptor
    placement_fingerprint: str
    directives: tuple[SlurmSbatchDirective, ...]
    script: str
    digest: str
    script_digest: str
    schema_version: int = READY_STAGE_REQUEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != READY_STAGE_REQUEST_SCHEMA_VERSION:
            raise SlurmPlanningError("ready-stage request schema is unsupported")
        for value in (
            self.operation_id,
            self.stage_work_id,
            self.attempt_id,
            self.profile_id,
            self.placement_fingerprint,
            self.digest,
            self.script_digest,
        ):
            _safe_text(value)
        _safe_text(self.run_uri, allow_uri=True)
        if not isinstance(self.profile_descriptor, SchedulingComponentDescriptor):
            raise SlurmPlanningError("ready-stage profile descriptor is invalid")
        directives = tuple(self.directives)
        if any(not isinstance(item, SlurmSbatchDirective) for item in directives):
            raise SlurmPlanningError("ready-stage directives are invalid")
        if not isinstance(self.script, str) or not self.script:
            raise SlurmPlanningError("ready-stage script is required")
        object.__setattr__(self, "directives", directives)
        expected = _digest(stable_json_dumps(self.semantic_dict()))
        if self.digest != expected:
            raise SlurmPlanningError("ready-stage request digest conflicts")
        if self.script_digest != _digest(self.script):
            raise SlurmPlanningError("ready-stage script digest conflicts")

    def semantic_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "stage_work_id": self.stage_work_id,
            "run_uri": self.run_uri,
            "attempt_id": self.attempt_id,
            "profile_id": self.profile_id,
            "profile_descriptor": self.profile_descriptor.to_dict(),
            "placement_fingerprint": self.placement_fingerprint,
            "directives": [item.to_dict() for item in self.directives],
        }

    def to_dict(self, *, include_digest: bool = True) -> dict[str, PlainData]:
        value: dict[str, PlainData] = {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "stage_work_id": self.stage_work_id,
            "run_uri": self.run_uri,
            "attempt_id": self.attempt_id,
            "profile_id": self.profile_id,
            "profile_descriptor": self.profile_descriptor.to_dict(),
            "placement_fingerprint": self.placement_fingerprint,
            "directives": [item.to_dict() for item in self.directives],
            "script": self.script,
            "script_digest": self.script_digest,
        }
        if include_digest:
            value["digest"] = self.digest
        return value

    @classmethod
    def from_dict(cls, value: object) -> "SlurmReadyStageRequest":
        mapping = _mapping(value, "ready-stage request")
        expected = {
            "schema_version",
            "operation_id",
            "stage_work_id",
            "run_uri",
            "attempt_id",
            "profile_id",
            "profile_descriptor",
            "placement_fingerprint",
            "directives",
            "script",
            "digest",
            "script_digest",
        }
        if set(mapping) != expected:
            raise SlurmPlanningError("ready-stage request fields are unsupported")
        raw_directives = mapping["directives"]
        if not isinstance(raw_directives, Sequence) or isinstance(
            raw_directives, (str, bytes)
        ):
            raise SlurmPlanningError("ready-stage request directives are invalid")
        return cls(
            operation_id=cast(str, mapping["operation_id"]),
            stage_work_id=cast(str, mapping["stage_work_id"]),
            run_uri=cast(str, mapping["run_uri"]),
            attempt_id=cast(str, mapping["attempt_id"]),
            profile_id=cast(str, mapping["profile_id"]),
            profile_descriptor=SchedulingComponentDescriptor.from_dict(
                mapping["profile_descriptor"]
            ),
            placement_fingerprint=cast(str, mapping["placement_fingerprint"]),
            directives=tuple(
                SlurmSbatchDirective.from_dict(item) for item in raw_directives
            ),
            script=cast(str, mapping["script"]),
            digest=cast(str, mapping["digest"]),
            script_digest=cast(str, mapping["script_digest"]),
            schema_version=cast(int, mapping["schema_version"]),
        )


def map_ready_stage(
    *,
    placement: ResolvedStagePlacement,
    profile: SlurmReadyStageProfile,
    operation_id: str,
    stage_work_id: str,
    run_uri: str,
    attempt_id: str,
) -> SlurmReadyStageRequest:
    """Translate every supported hard semantic or reject before submission."""

    if placement.route.kind is not ExecutionRouteKind.SLURM:
        raise SlurmPlanningError("stage is not explicitly routed to SLURM")
    if (
        placement.route.profile_id != profile.profile_id
        or placement.route.profile_descriptor != profile.descriptor
        or placement.route.profile_configuration_fingerprint
        != profile.configuration_fingerprint
    ):
        raise SlurmPlanningError("slurm_profile_changed")
    profile_diagnostic = profile.preflight()
    if profile_diagnostic is not None:
        raise SlurmPlanningError(profile_diagnostic)
    if (
        placement.hard_constraints
        or placement.target is not None
        or placement.pool_name != "default"
    ):
        raise SlurmResourceMappingError("slurm_hard_requirement_unmappable")
    resources = map_slurm_resources(placement.resource_request)
    marker = operation_marker(operation_id)
    directives: list[SlurmSbatchDirective] = [
        SlurmSbatchDirective("partition", profile.partition, "profile")
    ]
    if profile.account is not None:
        directives.append(SlurmSbatchDirective("account", profile.account, "profile"))
    if profile.qos is not None:
        directives.append(SlurmSbatchDirective("qos", profile.qos, "profile"))
    directives.extend(resources)
    directives.append(SlurmSbatchDirective("comment", marker, "operation"))
    argv = " ".join(_shell_quote(item) for item in profile.bootstrap_argv)
    semantic: dict[str, PlainData] = {
        "schema_version": READY_STAGE_REQUEST_SCHEMA_VERSION,
        "operation_id": operation_id,
        "stage_work_id": stage_work_id,
        "run_uri": run_uri,
        "attempt_id": attempt_id,
        "profile_id": profile.profile_id,
        "profile_descriptor": profile.descriptor.to_dict(),
        "placement_fingerprint": placement.fingerprint,
        "directives": [item.to_dict() for item in directives],
    }
    request_digest = _digest(stable_json_dumps(semantic))
    script_lines = [
        "#!/usr/bin/env bash",
        *(render_sbatch_directive(item) for item in directives),
        "set -euo pipefail",
        (
            f"exec {argv} --operation-id {_shell_quote(operation_id)} "
            f"--request-digest {_shell_quote(request_digest)}"
        ),
        "",
    ]
    script = "\n".join(script_lines)
    return SlurmReadyStageRequest(
        operation_id=operation_id,
        stage_work_id=stage_work_id,
        run_uri=run_uri,
        attempt_id=attempt_id,
        profile_id=profile.profile_id,
        profile_descriptor=profile.descriptor,
        placement_fingerprint=placement.fingerprint,
        directives=tuple(directives),
        script=script,
        digest=request_digest,
        script_digest=_digest(script),
    )


@dataclass(frozen=True, slots=True)
class SlurmReadyStageSubmission:
    request: SlurmReadyStageRequest
    state: ReadyStageState
    created_at: str
    job_id: str | None = None
    cluster: str | None = None
    evidence: str | None = None
    scheduler_state: str | None = None
    scheduler_source: str | None = None
    scheduler_observed_at: str | None = None
    conflicting_handles: tuple[tuple[str, str | None], ...] = ()
    start_consumed: bool = False
    cancel_requested: bool = False
    capability: JobPrivateFilePrepared | None = None
    schema_version: int = READY_STAGE_SUBMISSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != READY_STAGE_SUBMISSION_SCHEMA_VERSION:
            raise SlurmPlanningError("ready-stage submission schema is unsupported")
        if not isinstance(self.request, SlurmReadyStageRequest):
            raise SlurmPlanningError("ready-stage submission request is invalid")
        object.__setattr__(self, "state", ReadyStageState(self.state))
        _safe_text(self.created_at, allow_uri=True)
        for value in (
            self.job_id,
            self.cluster,
            self.evidence,
            self.scheduler_state,
            self.scheduler_source,
            self.scheduler_observed_at,
        ):
            if value is not None:
                _safe_text(value)
        if self.state is ReadyStageState.ACCEPTED and self.job_id is None:
            raise SlurmPlanningError("accepted ready-stage handle is missing")
        if self.state is not ReadyStageState.ACCEPTED and self.job_id is not None:
            raise SlurmPlanningError("non-accepted ready-stage has a handle")
        if not isinstance(self.start_consumed, bool) or not isinstance(
            self.cancel_requested, bool
        ):
            raise SlurmPlanningError("ready-stage submission flags are invalid")
        if self.capability is not None and not isinstance(
            self.capability, JobPrivateFilePrepared
        ):
            raise SlurmPlanningError("ready-stage capability receipt is invalid")
        if self.state is not ReadyStageState.INTENT and self.capability is None:
            raise SlurmPlanningError(
                "ready-stage submission requires a prepared capability"
            )
        if self.scheduler_source not in {None, "squeue", "sacct", "unavailable"}:
            raise SlurmPlanningError("ready-stage scheduler source is invalid")
        if self.scheduler_source is None and any(
            value is not None
            for value in (self.scheduler_state, self.scheduler_observed_at)
        ):
            raise SlurmPlanningError("ready-stage scheduler observation is incomplete")
        if self.scheduler_source is not None and self.scheduler_observed_at is None:
            raise SlurmPlanningError(
                "ready-stage scheduler observation time is missing"
            )
        if self.scheduler_state is not None and self.scheduler_source == "unavailable":
            raise SlurmPlanningError(
                "unavailable scheduler evidence cannot carry state"
            )
        raw_handles = tuple(self.conflicting_handles)
        handles: list[tuple[str, str | None]] = []
        for item in raw_handles:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise SlurmPlanningError("ready-stage conflicting handles are invalid")
            job_id, cluster = item
            _job_id(job_id)
            if cluster is not None:
                _safe_text(cluster)
            handles.append((cast(str, job_id), cast(str | None, cluster)))
        normalized_handles = tuple(handles)
        if len(normalized_handles) > 16 or len(set(normalized_handles)) != len(
            normalized_handles
        ):
            raise SlurmPlanningError("ready-stage conflicting handles are invalid")
        if self.state is ReadyStageState.CONFLICT:
            if len(normalized_handles) < 2:
                raise SlurmPlanningError("ready-stage conflict lacks exact handles")
        elif normalized_handles:
            raise SlurmPlanningError("non-conflicting submission has conflict handles")
        object.__setattr__(self, "conflicting_handles", normalized_handles)

    def to_dict(self) -> dict[str, PlainData]:
        return {
            "schema_version": self.schema_version,
            "request": self.request.to_dict(),
            "state": self.state.value,
            "created_at": self.created_at,
            "job_id": self.job_id,
            "cluster": self.cluster,
            "evidence": self.evidence,
            "scheduler_state": self.scheduler_state,
            "scheduler_source": self.scheduler_source,
            "scheduler_observed_at": self.scheduler_observed_at,
            "conflicting_handles": [
                {"job_id": job_id, "cluster": cluster}
                for job_id, cluster in self.conflicting_handles
            ],
            "start_consumed": self.start_consumed,
            "cancel_requested": self.cancel_requested,
            "capability": (
                None
                if self.capability is None
                else {
                    "receipt": self.capability.receipt,
                    "verifier": self.capability.verifier,
                    "expires_at": self.capability.expires_at,
                    "path": self.capability.path,
                    "descriptor": self.capability.descriptor,
                }
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> "SlurmReadyStageSubmission":
        mapping = _mapping(value, "ready-stage submission")
        expected = {
            "schema_version",
            "request",
            "state",
            "created_at",
            "job_id",
            "cluster",
            "evidence",
            "scheduler_state",
            "scheduler_source",
            "scheduler_observed_at",
            "conflicting_handles",
            "start_consumed",
            "cancel_requested",
            "capability",
        }
        if set(mapping) != expected:
            raise SlurmPlanningError("ready-stage submission fields are unsupported")
        raw_handles = mapping["conflicting_handles"]
        if not isinstance(raw_handles, Sequence) or isinstance(
            raw_handles, (str, bytes)
        ):
            raise SlurmPlanningError("ready-stage conflicting handles are invalid")
        handles: list[tuple[str, str | None]] = []
        for item in raw_handles:
            handle = _mapping(item, "ready-stage conflicting handle")
            if set(handle) != {"job_id", "cluster"}:
                raise SlurmPlanningError(
                    "ready-stage conflicting handle fields are unsupported"
                )
            handles.append(
                (cast(str, handle["job_id"]), cast(str | None, handle["cluster"]))
            )
        raw_capability = mapping["capability"]
        capability = None
        if raw_capability is not None:
            parsed_capability = _mapping(raw_capability, "ready-stage capability")
            if set(parsed_capability) != {
                "receipt",
                "verifier",
                "expires_at",
                "path",
                "descriptor",
            }:
                raise SlurmPlanningError(
                    "ready-stage capability fields are unsupported"
                )
            capability = JobPrivateFilePrepared(
                receipt=cast(str, parsed_capability["receipt"]),
                verifier=cast(str, parsed_capability["verifier"]),
                expires_at=cast(str, parsed_capability["expires_at"]),
                path=cast(str, parsed_capability["path"]),
                descriptor=cast(str, parsed_capability["descriptor"]),
            )
        return cls(
            request=SlurmReadyStageRequest.from_dict(mapping["request"]),
            state=ReadyStageState(cast(str, mapping["state"])),
            created_at=cast(str, mapping["created_at"]),
            job_id=cast(str | None, mapping["job_id"]),
            cluster=cast(str | None, mapping["cluster"]),
            evidence=cast(str | None, mapping["evidence"]),
            scheduler_state=cast(str | None, mapping["scheduler_state"]),
            scheduler_source=cast(str | None, mapping["scheduler_source"]),
            scheduler_observed_at=cast(str | None, mapping["scheduler_observed_at"]),
            conflicting_handles=tuple(handles),
            start_consumed=cast(bool, mapping["start_consumed"]),
            cancel_requested=cast(bool, mapping["cancel_requested"]),
            capability=capability,
            schema_version=cast(int, mapping["schema_version"]),
        )


class SQLiteReadyStageSubmissions:
    """The sole durable owner of one ready-stage ``sbatch`` invocation."""

    def __init__(self, path: str | Path, *, _allow_initialize: bool = True) -> None:
        self.path = Path(path)
        self._allow_initialize = _allow_initialize
        if _allow_initialize:
            self._initialize()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (_SUBMISSION_TABLE,),
            ).fetchone()
            if (
                existing is not None
                and int(conn.execute("PRAGMA user_version").fetchone()[0]) != 3
            ):
                raise SlurmPlanningError("ready-stage submission store is unsupported")
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {_SUBMISSION_TABLE} ("
                "operation_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
                "value_json TEXT NOT NULL)"
            )
            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({_SUBMISSION_TABLE})")
            }
            if columns != {"operation_id", "state", "value_json"}:
                raise SlurmPlanningError("ready-stage submission store is unsupported")
            conn.execute("PRAGMA user_version = 3")

    def _open_existing(self) -> None:
        if not self.path.is_file():
            raise SlurmPlanningError("ready-stage submission store is missing")
        with self._connect(require_existing=True) as conn:
            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({_SUBMISSION_TABLE})")
            }
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version != 3 or columns != {"operation_id", "state", "value_json"}:
            raise SlurmPlanningError("ready-stage submission store is unsupported")

    def prepare(
        self,
        request: SlurmReadyStageRequest,
        profile: SlurmReadyStageProfile,
        script_path: str | Path,
    ) -> SlurmReadyStageSubmission:
        """Retain one replay-stable capability before either owner submits."""

        self._require_profile(request, profile)
        script = Path(script_path)
        if script.read_text(encoding="utf-8") != request.script:
            raise SlurmPlanningError("ready-stage script bytes conflict")
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (request.operation_id,),
            ).fetchone()
            if row is not None:
                current = _submission_from_json(str(row[0]))
                if current.request != request:
                    raise SlurmPlanningError("ready-stage submission replay conflicts")
                if current.state is not ReadyStageState.INTENT:
                    return current
            else:
                current = SlurmReadyStageSubmission(
                    request=request,
                    state=ReadyStageState.INTENT,
                    created_at=utc_timestamp(),
                )
                conn.execute(
                    f"INSERT INTO {_SUBMISSION_TABLE} VALUES (?, ?, ?)",
                    (
                        request.operation_id,
                        current.state.value,
                        _submission_json(current),
                    ),
                )
        if current.capability is not None:
            return current
        prepared = profile.job_private_file_provider.prepare(
            operation_id=request.operation_id, request_digest=request.digest
        )
        return self._compare_and_set(
            request.operation_id,
            expected=ReadyStageState.INTENT,
            value=replace(current, capability=prepared),
        )

    def submit(
        self,
        request: SlurmReadyStageRequest,
        profile: SlurmReadyStageProfile,
        script_path: str | Path,
        *,
        before_runner: Callable[[SlurmReadyStageSubmission], bool | None] | None = None,
    ) -> SlurmReadyStageSubmission:
        """Persist intent and ``SUBMITTING`` before the one automatic call."""

        current = self.prepare(request, profile, script_path)
        if current.state is not ReadyStageState.INTENT:
            return current
        submitting = self._compare_and_set(
            request.operation_id,
            expected=ReadyStageState.INTENT,
            value=replace(current, state=ReadyStageState.SUBMITTING),
        )
        if submitting.state is not ReadyStageState.SUBMITTING:
            return submitting
        if before_runner is not None and before_runner(submitting) is False:
            return self._record_outcome(
                request.operation_id,
                ReadyStageState.REJECTED,
                evidence="slurm_submit_suppressed_before_call",
            )
        script = Path(script_path)
        try:
            result = profile.runner.sbatch(
                script,
                comment=operation_marker(request.operation_id),
                environment={},
            )
        except BaseException:  # noqa: BLE001 - call outcome is intentionally unknown.
            return self._record_outcome(
                request.operation_id,
                ReadyStageState.UNKNOWN,
                evidence="slurm_submit_unknown",
            )
        if not result.ok:
            return self._record_outcome(
                request.operation_id,
                ReadyStageState.REJECTED,
                evidence="slurm_submit_definitely_rejected",
            )
        try:
            parsed = parse_sbatch_parsable_output(result.stdout)
        except Exception:
            return self._record_outcome(
                request.operation_id,
                ReadyStageState.UNKNOWN,
                evidence="slurm_submit_unusable_success",
            )
        try:
            return self._record_outcome(
                request.operation_id,
                ReadyStageState.ACCEPTED,
                job_id=parsed.job_id,
                cluster=parsed.cluster or profile.cluster,
            )
        except Exception:
            return self._record_outcome(
                request.operation_id,
                ReadyStageState.UNKNOWN,
                evidence="slurm_submit_handle_persist_unknown",
            )

    def reconcile(
        self, operation_id: str, profile: SlurmReadyStageProfile
    ) -> SlurmReadyStageSubmission:
        current = self.read(operation_id)
        self._require_profile(current.request, profile)
        if current.state not in {ReadyStageState.SUBMITTING, ReadyStageState.UNKNOWN}:
            return current
        marker = operation_marker(operation_id)
        try:
            live = profile.runner.discover_live_operations()
            retained = profile.runner.discover_accounted_operations(
                started_after=current.created_at
            )
            if not live.ok or not retained.ok:
                raise SlurmPlanningError("operation discovery is unavailable")
            matches = _operation_matches(
                marker=marker,
                cluster=profile.cluster,
                live=live,
                retained=retained,
            )
        except Exception:
            return self._record_outcome(
                operation_id,
                ReadyStageState.UNKNOWN,
                evidence="slurm_discovery_unknown",
            )
        if len(matches) == 1:
            job_id, cluster = next(iter(matches))
            return self._record_outcome(
                operation_id,
                ReadyStageState.ACCEPTED,
                job_id=job_id,
                cluster=cluster,
                evidence="slurm_operation_reconciled",
            )
        if len(matches) > 1:
            return self._record_outcome(
                operation_id,
                ReadyStageState.CONFLICT,
                evidence="slurm_operation_multiple_matches",
                conflicting_handles=_sorted_handles(matches),
            )
        return self._record_outcome(
            operation_id,
            ReadyStageState.UNKNOWN,
            evidence="slurm_operation_not_found",
        )

    def read(self, operation_id: str) -> SlurmReadyStageSubmission:
        with self._connect(require_existing=True) as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise SlurmPlanningError("SLURM submission is not durable")
        return _submission_from_json(str(row[0]))

    def find(self, operation_id: str) -> SlurmReadyStageSubmission | None:
        """Return an exact retained operation without masking store failures."""

        with self._connect(require_existing=True) as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        return None if row is None else _submission_from_json(str(row[0]))

    def list_nonterminal(self) -> tuple[SlurmReadyStageSubmission, ...]:
        with self._connect(require_existing=True) as conn:
            rows = tuple(
                conn.execute(
                    f"SELECT value_json FROM {_SUBMISSION_TABLE} "
                    "WHERE state NOT IN ('rejected', 'conflict') ORDER BY operation_id"
                )
            )
        return tuple(_submission_from_json(str(row[0])) for row in rows)

    def suppress_before_submit(self, operation_id: str) -> SlurmReadyStageSubmission:
        """Close an INTENT with durable proof that ``sbatch`` was never invoked."""

        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise SlurmPlanningError("SLURM submission is not durable")
            current = _submission_from_json(str(row[0]))
            if current.state is ReadyStageState.REJECTED:
                return current
            if current.state is not ReadyStageState.INTENT:
                raise SlurmPlanningError(
                    "only an unsubmitted SLURM intent can be suppressed"
                )
            suppressed = replace(
                current,
                state=ReadyStageState.REJECTED,
                evidence="slurm_submit_suppressed_before_call",
            )
            conn.execute(
                f"UPDATE {_SUBMISSION_TABLE} SET state = ?, value_json = ? "
                "WHERE operation_id = ?",
                (
                    suppressed.state.value,
                    _submission_json(suppressed),
                    operation_id,
                ),
            )
        return suppressed

    def consume_start(self, operation_id: str) -> bool:
        """Atomically consume the one authored-root permit after acceptance."""

        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise SlurmPlanningError("SLURM submission is not durable")
            current = _submission_from_json(str(row[0]))
            if current.state is not ReadyStageState.ACCEPTED:
                raise SlurmPlanningError("SLURM start requires an accepted handle")
            if current.start_consumed:
                return False
            consumed = replace(current, start_consumed=True)
            result = conn.execute(
                f"UPDATE {_SUBMISSION_TABLE} SET state = ?, value_json = ? "
                "WHERE operation_id = ? AND value_json = ?",
                (
                    consumed.state.value,
                    _submission_json(consumed),
                    operation_id,
                    str(row[0]),
                ),
            )
            return result.rowcount == 1

    def associate_handle(
        self,
        operation_id: str,
        profile: SlurmReadyStageProfile,
        *,
        job_id: str,
        cluster: str | None,
    ) -> SlurmReadyStageSubmission:
        """Associate an exact bootstrap-observed handle, including response races."""

        _job_id(job_id)
        resolved_cluster = cluster or profile.cluster
        current = self.read(operation_id)
        self._require_profile(current.request, profile)
        return self._record_outcome(
            operation_id,
            ReadyStageState.ACCEPTED,
            job_id=job_id,
            cluster=resolved_cluster,
            evidence="slurm_bootstrap_handle_associated",
            bootstrap_association=True,
        )

    def request_cancel(
        self, operation_id: str, profile: SlurmReadyStageProfile
    ) -> SlurmReadyStageSubmission:
        current = self.read(operation_id)
        self._require_profile(current.request, profile)
        if current.job_id is None:
            raise SlurmPlanningError("SLURM cancel requires an exact known handle")
        if current.cancel_requested:
            return current
        try:
            result = profile.runner.scancel(job_ids=(current.job_id,))
        except Exception:
            return self._record_cancel(
                operation_id,
                expected_job_id=current.job_id,
                requested=False,
                evidence="slurm_cancel_unknown",
            )
        return self._record_cancel(
            operation_id,
            expected_job_id=current.job_id,
            requested=result.ok,
            evidence=(
                "slurm_cancel_requested"
                if result.ok
                else "slurm_cancel_request_rejected"
            ),
        )

    def observe(
        self, operation_id: str, profile: SlurmReadyStageProfile
    ) -> SlurmReadyStageSubmission:
        """Retain one bounded exact-handle scheduler fact without lifecycle inference."""

        current = self.read(operation_id)
        self._require_profile(current.request, profile)
        if current.job_id is None:
            raise SlurmPlanningError("SLURM observation requires an exact known handle")
        source = "unavailable"
        state: str | None = None
        try:
            live = profile.runner.squeue(job_ids=(current.job_id,))
            if live.ok:
                state = _exact_scheduler_state(
                    live, job_id=current.job_id, source="squeue"
                )
                if state is not None:
                    source = "squeue"
            if state is None:
                retained = profile.runner.sacct(job_ids=(current.job_id,))
                if retained.ok:
                    state = _exact_scheduler_state(
                        retained, job_id=current.job_id, source="sacct"
                    )
                    if state is not None:
                        source = "sacct"
        except Exception:
            source = "unavailable"
            state = None
        return self._record_observation(
            operation_id,
            expected_job_id=current.job_id,
            scheduler_state=state,
            scheduler_source=source,
            observed_at=utc_timestamp(),
        )

    def _require_profile(
        self, request: SlurmReadyStageRequest, profile: SlurmReadyStageProfile
    ) -> None:
        if (
            request.profile_id != profile.profile_id
            or request.profile_descriptor != profile.descriptor
        ):
            raise SlurmPlanningError("ready-stage profile identity conflicts")

    def _compare_and_set(
        self,
        operation_id: str,
        *,
        expected: ReadyStageState,
        value: SlurmReadyStageSubmission,
    ) -> SlurmReadyStageSubmission:
        with self._transaction() as conn:
            result = conn.execute(
                f"UPDATE {_SUBMISSION_TABLE} SET state = ?, value_json = ? "
                "WHERE operation_id = ? AND state = ?",
                (
                    value.state.value,
                    _submission_json(value),
                    operation_id,
                    expected.value,
                ),
            )
            if result.rowcount == 1:
                return value
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            raise SlurmPlanningError("SLURM submission is not durable")
        return _submission_from_json(str(row[0]))

    def _record_outcome(
        self,
        operation_id: str,
        state: ReadyStageState,
        *,
        job_id: str | None = None,
        cluster: str | None = None,
        evidence: str | None = None,
        bootstrap_association: bool = False,
        conflicting_handles: Sequence[tuple[str, str | None]] = (),
    ) -> SlurmReadyStageSubmission:
        """Record one closed outcome without regressing stronger concurrent facts."""

        if state not in {
            ReadyStageState.ACCEPTED,
            ReadyStageState.REJECTED,
            ReadyStageState.UNKNOWN,
            ReadyStageState.CONFLICT,
        }:
            raise SlurmPlanningError("ready-stage call outcome is invalid")
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise SlurmPlanningError("SLURM submission is not durable")
            current = _submission_from_json(str(row[0]))
            if current.state is ReadyStageState.CONFLICT:
                return current
            if current.state is ReadyStageState.REJECTED:
                if bootstrap_association:
                    raise SlurmPlanningError(
                        "SLURM bootstrap cannot associate a rejected submission"
                    )
                return current
            if current.state is ReadyStageState.ACCEPTED:
                if state is ReadyStageState.CONFLICT:
                    handles = tuple(
                        sorted(
                            {
                                *conflicting_handles,
                                (cast(str, current.job_id), current.cluster),
                            },
                            key=lambda item: (item[0], item[1] or ""),
                        )
                    )
                    value = replace(
                        current,
                        state=ReadyStageState.CONFLICT,
                        job_id=None,
                        cluster=None,
                        evidence=evidence,
                        conflicting_handles=handles,
                    )
                elif state is ReadyStageState.ACCEPTED:
                    if current.job_id != job_id or current.cluster != cluster:
                        value = replace(
                            current,
                            state=ReadyStageState.CONFLICT,
                            job_id=None,
                            cluster=None,
                            evidence="slurm_bootstrap_handle_conflict",
                            conflicting_handles=(
                                (cast(str, current.job_id), current.cluster),
                                (cast(str, job_id), cluster),
                            ),
                        )
                    else:
                        return current
                else:
                    # An exact accepted handle is stronger than a late unknown or
                    # rejection classification from the original call path.
                    return current
            else:
                if current.state not in {
                    ReadyStageState.SUBMITTING,
                    ReadyStageState.UNKNOWN,
                }:
                    raise SlurmPlanningError(
                        "SLURM call outcome cannot update this submission"
                    )
                value = replace(
                    current,
                    state=state,
                    job_id=job_id,
                    cluster=cluster,
                    evidence=evidence,
                    conflicting_handles=(
                        tuple(conflicting_handles)
                        if state is ReadyStageState.CONFLICT
                        else ()
                    ),
                )
            conn.execute(
                f"UPDATE {_SUBMISSION_TABLE} SET state = ?, value_json = ? "
                "WHERE operation_id = ?",
                (value.state.value, _submission_json(value), operation_id),
            )
        return value

    def _record_cancel(
        self,
        operation_id: str,
        *,
        expected_job_id: str,
        requested: bool,
        evidence: str,
    ) -> SlurmReadyStageSubmission:
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise SlurmPlanningError("SLURM submission is not durable")
            current = _submission_from_json(str(row[0]))
            if current.job_id != expected_job_id:
                raise SlurmPlanningError("SLURM cancel handle changed concurrently")
            value = replace(
                current,
                cancel_requested=current.cancel_requested or requested,
                evidence=evidence,
            )
            conn.execute(
                f"UPDATE {_SUBMISSION_TABLE} SET state = ?, value_json = ? "
                "WHERE operation_id = ?",
                (
                    value.state.value,
                    _submission_json(value),
                    operation_id,
                ),
            )
        return value

    def _record_observation(
        self,
        operation_id: str,
        *,
        expected_job_id: str,
        scheduler_state: str | None,
        scheduler_source: str,
        observed_at: str,
    ) -> SlurmReadyStageSubmission:
        with self._transaction() as conn:
            row = conn.execute(
                f"SELECT value_json FROM {_SUBMISSION_TABLE} WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if row is None:
                raise SlurmPlanningError("SLURM submission is not durable")
            current = _submission_from_json(str(row[0]))
            if current.job_id != expected_job_id:
                raise SlurmPlanningError(
                    "SLURM observation handle changed concurrently"
                )
            value = replace(
                current,
                scheduler_state=scheduler_state,
                scheduler_source=scheduler_source,
                scheduler_observed_at=observed_at,
            )
            conn.execute(
                f"UPDATE {_SUBMISSION_TABLE} SET state = ?, value_json = ? "
                "WHERE operation_id = ?",
                (value.state.value, _submission_json(value), operation_id),
            )
        return value

    def _connect(self, *, require_existing: bool = False) -> sqlite3.Connection:
        if require_existing:
            return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=rw", uri=True)
        return sqlite3.connect(self.path)

    def _transaction(self) -> "_SQLiteTransaction":
        return _SQLiteTransaction(self.path)


class _SQLiteTransaction:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self.conn is not None
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()


def operation_marker(operation_id: str) -> str:
    _safe_text(operation_id)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:@+"
    if any(char not in allowed for char in operation_id):
        raise SlurmPlanningError("ready-stage operation marker is invalid")
    marker = _OPERATION_MARKER_PREFIX + operation_id
    if len(marker) > 120:
        raise SlurmPlanningError("ready-stage operation marker is too long")
    return marker


def _operation_matches(
    *,
    marker: str,
    cluster: str | None,
    live: SlurmCommandResult,
    retained: SlurmCommandResult,
) -> set[tuple[str, str | None]]:
    matches: set[tuple[str, str | None]] = set()
    for raw in live.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        fields = line.split("|")
        if len(fields) != 2:
            raise SlurmPlanningError("live operation discovery row is malformed")
        job_id, comment = fields
        if comment == marker:
            _job_id(job_id)
            matches.add((job_id, cluster))
    for raw in retained.stdout.splitlines():
        line = raw.strip().removesuffix("|")
        if not line:
            continue
        fields = line.split("|")
        if len(fields) != 3:
            raise SlurmPlanningError("accounted operation discovery row is malformed")
        job_id, comment, row_cluster = fields
        if comment == marker:
            _job_id(job_id)
            resolved_cluster = row_cluster or cluster
            if cluster is not None and resolved_cluster != cluster:
                continue
            matches.add((job_id, resolved_cluster))
    normalized: set[tuple[str, str | None]] = set()
    by_job_id: dict[str, set[str | None]] = {}
    for job_id, row_cluster in matches:
        by_job_id.setdefault(job_id, set()).add(row_cluster)
    for job_id, clusters in by_job_id.items():
        concrete = {item for item in clusters if item is not None}
        if len(concrete) == 1:
            normalized.add((job_id, next(iter(concrete))))
        elif concrete:
            normalized.update((job_id, item) for item in concrete)
        else:
            normalized.add((job_id, None))
    return normalized


def _exact_scheduler_state(
    result: SlurmCommandResult, *, job_id: str, source: str
) -> str | None:
    matches: list[str] = []
    for raw in result.stdout.splitlines():
        line = raw.strip().removesuffix("|")
        if not line:
            continue
        fields = line.split("|")
        if len(fields) != 3:
            raise SlurmPlanningError("scheduler observation row is malformed")
        row_job_id, raw_state, _detail = fields
        if row_job_id != job_id:
            continue
        state = raw_state.strip().upper().split(maxsplit=1)[0].removesuffix("+")
        if not state or any(not (char.isalnum() or char == "_") for char in state):
            raise SlurmPlanningError("scheduler observation state is malformed")
        matches.append(state)
    if len(matches) > 1 or len(set(matches)) > 1:
        raise SlurmPlanningError("scheduler observation identity is ambiguous")
    if source not in {"squeue", "sacct"}:
        raise SlurmPlanningError("scheduler observation source is invalid")
    return None if not matches else matches[0]


def _sorted_handles(
    values: Iterable[tuple[str, str | None]],
) -> tuple[tuple[str, str | None], ...]:
    return tuple(sorted(set(values), key=lambda item: (item[0], item[1] or ""))[:16])


def _submission_json(value: SlurmReadyStageSubmission) -> str:
    return json.dumps(
        value.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _submission_from_json(value: str) -> SlurmReadyStageSubmission:
    parsed = json.loads(value)
    return SlurmReadyStageSubmission.from_dict(parsed)


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise SlurmPlanningError(f"{path} must be a string-keyed mapping")
    return cast(Mapping[str, object], value)


def _job_id(value: object) -> str:
    if not isinstance(value, str) or not value.isdigit():
        raise SlurmPlanningError("ready-stage scheduler job ID is invalid")
    return value


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_text(value: object, *, allow_uri: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise SlurmPlanningError("SLURM ready-stage identity is invalid")
    if any(ord(char) < 32 for char in value):
        raise SlurmPlanningError("SLURM ready-stage identity is invalid")
    if not allow_uri and any(char.isspace() for char in value):
        raise SlurmPlanningError("SLURM ready-stage identity is invalid")
    return value


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


__all__ = [
    "READY_STAGE_REQUEST_SCHEMA_VERSION",
    "READY_STAGE_SUBMISSION_SCHEMA_VERSION",
    "SlurmContainmentReceipt",
    "ReadyStageState",
    "SQLiteReadyStageSubmissions",
    "SlurmReadyStageProfile",
    "SlurmReadyStageRequest",
    "SlurmReadyStageSubmission",
    "resolve_slurm_containment",
    "map_ready_stage",
    "operation_marker",
]

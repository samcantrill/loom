"""Shared payload routing within the native resident assignment protocol."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loom.artifacts import ArtifactRef
from loom.io.uris import uri_to_path
from loom.pipeline.stores.atomic import atomic_write_bytes
from loom.pipeline.stores.errors import ArtifactStoreError
from loom.pipeline.stores.shared_artifacts import (
    SHARED_PUBLICATION,
    RECEIPT,
    binding,
    budgets,
    contained,
    encoded,
    file_identity,
    inventory,
    read_receipt,
    receipt_bytes,
    resolve_binding,
)
from loom.serialization import PlainData
from .errors import QueueConflictError, QueueServiceError
from .shared_execution import assignment_scope

if TYPE_CHECKING:
    from loom.pipeline.execution.models import StageWorkerResult
    from ._remote_stage_execution import (
        _ResidentAssignmentBundle,
        _ResidentAssignmentWorkspace,
        _RemoteArtifact,
        _RemoteOutputArtifact,
        _RemoteExecutionReport,
    )

CAPABILITY = "shared-artifact-publication-v1"


def selected(
    request: _ResidentAssignmentBundle,
) -> tuple[str, Mapping[str, PlainData]] | None:
    scope = assignment_scope(request.fingerprint)
    if scope is None:
        return None
    roots = cast(Mapping[str, Mapping[str, PlainData]], scope["roots"])
    matches = [
        (alias, facts) for alias, facts in roots.items() if "publication" in facts
    ]
    return None if not matches else matches[0]


def identity(
    request: _ResidentAssignmentBundle, *, agent_id: str, fence: str
) -> dict[str, PlainData]:
    return {
        "assignment_id": request.assignment_id,
        "attempt_id": request.attempt_id,
        "stage_name": request.stage_name,
        "attempt": request.attempt,
        "agent_id": agent_id,
        "fence": fence,
    }


def publication_id(identity: Mapping[str, PlainData]) -> str:
    return hashlib.sha256(encoded(identity)).hexdigest()


def staging_relative(request: _ResidentAssignmentBundle, agent_id: str) -> str:
    # Hash only path components whose native identities can contain punctuation.
    machine = hashlib.sha256(agent_id.encode()).hexdigest()
    return f"loom-work/{machine}/{request.assignment_id}/{request.attempt_id}/artifacts/{request.stage_name}"


def staging_tree(
    request: _ResidentAssignmentBundle,
    roots: Mapping[str, PlainData],
    agent_id: str,
    *,
    create: bool = False,
) -> Path:
    selection = selected(request)
    if selection is None:
        raise QueueServiceError("assignment has no shared publication policy")
    alias, facts = selection
    root = cast(Mapping[str, PlainData], roots[alias])
    if root.get("publication") != facts["publication"] or root["access"] != "rw":
        raise QueueConflictError("shared publication policy conflicts")
    base = Path(str(root["host_path"]))
    tree = contained(base, staging_relative(request, agent_id), exists=False)
    if create:
        tree.mkdir(parents=True, exist_ok=True)
    return tree


def workspace_facts(
    workspace: _ResidentAssignmentWorkspace,
) -> tuple[dict[str, Any], dict[str, PlainData]]:
    value = workspace.supervisor_launch_json()
    if value is None:
        raise QueueConflictError("shared publication requires a retained launch")
    launch = json.loads(value)
    return launch, identity(
        workspace.request(),
        agent_id=launch["agent_id"],
        fence=launch["execution_fence"],
    )


def worker_artifact_root(
    workspace: _ResidentAssignmentWorkspace, *, container: bool = False
) -> Path | None:
    request = workspace.request()
    if selected(request) is None:
        return None
    launch, owner = workspace_facts(workspace)
    from .shared_execution import execution_roots

    roots = execution_roots(launch["profile"]["shared_roots"], container=container)
    tree = staging_tree(request, roots, launch["agent_id"], create=True)
    marker = tree / RECEIPT
    if not marker.exists():
        atomic_write_bytes(marker, encoded({"schema_version": 1, "identity": owner}))
    return tree.parent


def retain(
    workspace: _ResidentAssignmentWorkspace, result: StageWorkerResult
) -> list[_RemoteOutputArtifact]:
    try:
        from ._remote_stage_execution import _RemoteOutputArtifact

        request = workspace.request()
        selection = selected(request)
        assert selection is not None
        alias, facts = selection
        limits = budgets(facts["publication"])
        launch, owner = workspace_facts(workspace)
        roots = launch["profile"]["shared_roots"]
        tree = staging_tree(request, roots, launch["agent_id"])
        pub_id = publication_id(owner)
        final_relative = f"loom-artifacts/{pub_id}"
        final = contained(Path(roots[alias]["host_path"]), final_relative, exists=False)
        # Lost replies replay the exact tree already renamed by the coordinator.
        available = tree if tree.is_dir() else final
        members = inventory(available, limits)
        indexed = {str(member["path"]): member for member in members}
        outputs = {}
        for name, ref in result.outputs.items():
            source = uri_to_path(ref.uri)
            if (
                not source.resolve().is_relative_to(tree.resolve())
                and roots[alias]["container_path"] is not None
            ):
                source = Path(roots[alias]["host_path"]) / source.relative_to(
                    roots[alias]["container_path"]
                )
            relative = source.resolve().relative_to(tree.resolve()).as_posix()
            member = indexed.get(relative)
            if member is None or (
                ref.checksum is not None
                and ref.checksum != "sha256:" + str(member["digest"])
            ):
                raise QueueConflictError("shared primary output integrity conflicts")
            outputs[name] = relative
        receipt = {
            "schema_version": 1,
            "publication_id": pub_id,
            "identity": owner,
            "members": members,
            "outputs": outputs,
        }
        data = encoded(receipt)
        if len(data) > limits["max_manifest_bytes"]:
            raise QueueServiceError("shared publication exceeds manifest budget")
        receipt_path = available / RECEIPT
        if receipt_path.exists():
            prior = receipt_bytes(receipt_path, limits["max_manifest_bytes"])
            if (
                prior == encoded({"schema_version": 1, "identity": owner})
                and available == tree
            ):
                atomic_write_bytes(receipt_path, data)
            elif prior != data:
                raise QueueConflictError("shared publication replay conflicts")
        elif available == tree:
            atomic_write_bytes(receipt_path, data)
        else:
            raise QueueConflictError("shared publication receipt is missing")
        descriptors = []
        for name, ref in sorted(result.outputs.items()):
            primary = outputs[name]
            member = indexed[primary]
            reference = {
                "schema_version": 1,
                "root_id": alias,
                "tree": final_relative,
                "publication_id": pub_id,
                "receipt_digest": hashlib.sha256(data).hexdigest(),
                "primary": primary,
                "budgets": limits,
            }
            descriptors.append(
                _RemoteOutputArtifact(
                    transfer_id="shared-"
                    + hashlib.sha256((pub_id + "\0" + name).encode()).hexdigest(),
                    logical_name=name,
                    digest=str(member["digest"]),
                    size_bytes=cast(int, member["size_bytes"]),
                    artifact_id=ref.artifact_id,
                    artifact_type=ref.artifact_type,
                    codec_key=ref.codec_key,
                    artifact_schema_version=ref.schema_version,
                    fingerprint=ref.fingerprint,
                    producer_stage=ref.producer_stage,
                    created_at=ref.created_at,
                    metadata={**ref.metadata, SHARED_PUBLICATION: reference},
                )
            )
        return descriptors
    except (ArtifactStoreError, OSError, ValueError) as exc:
        raise QueueConflictError(str(exc)) from exc


def publish(
    request: _ResidentAssignmentBundle,
    report: _RemoteExecutionReport,
    roots: Mapping[str, PlainData],
    *,
    agent_id: str,
    fence: str,
) -> dict[str, ArtifactRef]:
    try:
        selection = selected(request)
        if selection is None:
            raise QueueConflictError("shared output was not admitted")
        alias, facts = selection
        root = cast(Mapping[str, PlainData], roots[alias])
        limits = budgets(facts["publication"])
        if root.get("publication") != facts["publication"]:
            raise QueueConflictError("coordinator publication policy conflicts")
        owner = identity(request, agent_id=agent_id, fence=fence)
        pub_id = publication_id(owner)
        final_relative = f"loom-artifacts/{pub_id}"
        final = contained(Path(str(root["host_path"])), final_relative, exists=False)
        staging = staging_tree(request, roots, agent_id)
        available = final if final.exists() else staging
        receipt = None
        receipt_digest = None
        outputs = {}
        for item in report.outputs:
            reference = binding(item.metadata)
            if (
                reference is None
                or reference["root_id"] != alias
                or reference["publication_id"] != pub_id
                or reference["tree"] != final_relative
                or reference["budgets"] != limits
            ):
                raise QueueConflictError("shared output publication identity conflicts")
            if receipt is None:
                receipt = read_receipt(available, reference, limits=limits)
                receipt_digest = reference["receipt_digest"]
            elif reference["receipt_digest"] != receipt_digest:
                raise QueueConflictError("shared outputs select different closures")
            if (
                receipt["identity"] != owner
                or cast(Mapping[str, PlainData], receipt["outputs"]).get(
                    item.logical_name
                )
                != reference["primary"]
            ):
                raise QueueConflictError(
                    "shared output ownership or association conflicts"
                )
            member = next(
                member
                for member in cast(list[Mapping[str, PlainData]], receipt["members"])
                if member["path"] == reference["primary"]
            )
            if (member["size_bytes"], member["digest"]) != (
                item.size_bytes,
                item.digest,
            ):
                raise QueueConflictError("shared primary output bytes conflict")
            outputs[item.logical_name] = item.local_ref(
                final / str(reference["primary"])
            )
        if receipt is not None:
            if set(cast(Mapping[str, PlainData], receipt["outputs"])) != set(
                request.declared_outputs
            ):
                raise QueueConflictError("shared output declaration is incomplete")
            if not final.exists():
                final.parent.mkdir(parents=True, exist_ok=True)
                from ._remote_stage_execution import _fsync_directory

                for directory, _, files in os.walk(staging, topdown=False):
                    for name in files:
                        descriptor = os.open(
                            Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW
                        )
                        try:
                            os.fsync(descriptor)
                        finally:
                            os.close(descriptor)
                    _fsync_directory(Path(directory))
                # The complete nonempty directory makes an existing winner nonreplaceable.
                os.rename(staging, final)
                from ._remote_stage_execution import _fsync_directory

                _fsync_directory(final.parent)
                _fsync_directory(final.parent.parent)
                _fsync_directory(staging.parent)
        return outputs
    except (ArtifactStoreError, OSError, ValueError) as exc:
        raise QueueConflictError(str(exc)) from exc


def resolve_input(item: _RemoteArtifact, roots: Mapping[str, PlainData]) -> Path:
    try:
        reference = binding(item.metadata)
        if reference is None:
            raise QueueServiceError("input has no shared publication binding")
        primary = resolve_binding(reference, roots)
        if file_identity(primary) != (item.size_bytes, item.digest):
            raise QueueConflictError("shared input primary identity conflicts")
        return primary
    except (ArtifactStoreError, OSError, ValueError) as exc:
        raise QueueConflictError(str(exc)) from exc

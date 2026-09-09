"""Private immutable resource intent for delayed submitted-stage preparation."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import cast

from loom.pipeline.errors import RuntimeResourceError
from loom.pipeline.resources import ResourceRequest, ResourceValidatorRegistry
from loom.pipeline.runtime.metadata import ResolvedStageRuntimeOptions
from loom.pipeline.runtime.resource_policy import (
    ResourcePolicy,
    validate_resource_selection,
)
from loom.pipeline.stores.atomic import unique_temp_path
from loom.pipeline.stores.run_store import LocalRunStorePaths
from loom.serialization import PlainData, json_dumps_pretty, json_loads

_FIELDS = frozenset({"resources", "resource_policy", "resource_selection"})
_DOCUMENT_FIELDS = frozenset(
    {"schema_version", "run_uri", "manifest_relative_path", "stages"}
)
_GUIDANCE = (
    "finish with the pinned original runtime or prepare a fresh execution identity"
)


def write_resource_handoff(
    *,
    store_paths: LocalRunStorePaths,
    run_uri: str,
    manifest_relative_path: str,
    stage_names: Sequence[str],
    stage_runtime: Mapping[str, ResolvedStageRuntimeOptions],
) -> None:
    """Publish exact intent once, before the submission manifest is published."""

    stages: dict[str, PlainData] = {}
    for stage_name in stage_names:
        runtime = stage_runtime.get(stage_name)
        if (
            not isinstance(runtime, ResolvedStageRuntimeOptions)
            or runtime.stage_id != stage_name
        ):
            raise RuntimeResourceError(
                f"stage_runtime must contain matching resolved runtime for {stage_name!r}"
            )
        private = runtime.for_execution()._to_worker_metadata()
        stages[stage_name] = {key: private[key] for key in _FIELDS}
    payload = {
        "schema_version": 1,
        "run_uri": run_uri,
        "manifest_relative_path": manifest_relative_path,
        "stages": stages,
    }
    encoded = json_dumps_pretty(payload, sort_keys=True).encode("utf-8")
    path = _handoff_path(store_paths, run_uri, manifest_relative_path)
    if path.exists():
        _require_same_bytes(path, encoded)
        return
    if store_paths.local_generated_artifact_path(
        run_uri, manifest_relative_path
    ).exists():
        raise RuntimeResourceError(
            f"existing preparation has no private execution-resource handoff at {path}; "
            f"{_GUIDANCE}; existing preparations cannot be retrofitted"
        )
    # A hard-link publication never replaces the winner if preparations race.
    # The temporary file is private from creation and complete before publication.
    temporary = unique_temp_path(path)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            _require_same_bytes(path, encoded)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def read_resource_handoff(
    *,
    store_paths: LocalRunStorePaths,
    run_uri: str,
    manifest_relative_path: str,
    stage_name: str,
    registry: ResourceValidatorRegistry | None,
) -> Mapping[str, PlainData]:
    """Validate the durable boundary without filling omissions or rewriting it."""

    path = _handoff_path(store_paths, run_uri, manifest_relative_path)
    document = json_loads(path.read_text(encoding="utf-8"), path=str(path))
    if (
        not isinstance(document, dict)
        or set(document) != _DOCUMENT_FIELDS
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
        or document["run_uri"] != run_uri
        or document["manifest_relative_path"] != manifest_relative_path
    ):
        raise RuntimeResourceError(
            f"private execution-resource handoff schema/identity mismatch at {path}"
        )
    stages = document["stages"]
    stage = stages.get(stage_name) if isinstance(stages, Mapping) else None
    if not isinstance(stage, Mapping) or set(stage) != _FIELDS:
        raise RuntimeResourceError(
            f"private execution-resource handoff lacks exact stage {stage_name!r} at {path}"
        )
    resources = stage["resources"]
    policy = stage["resource_policy"]
    if (
        not isinstance(resources, Mapping)
        or not isinstance(policy, Mapping)
        or set(policy) != {"account_for", "enforce"}
    ):
        raise RuntimeResourceError(
            f"private execution-resource handoff lacks resolved demand/policy at {path}"
        )
    normalized = ResourceRequest.from_dict(resources, registry=registry)
    if normalized.to_dict() != resources:
        raise RuntimeResourceError(
            f"private execution-resource handoff demand is not normalized at {path}"
        )
    validate_resource_selection(
        stage["resource_selection"],
        normalized.entries,
        ResourcePolicy.from_dict(policy),
        path=f"{path}.stages.{stage_name}.resource_selection",
    )
    return cast(Mapping[str, PlainData], stage)


def _handoff_path(
    store_paths: LocalRunStorePaths, run_uri: str, manifest_relative_path: str
) -> Path:
    # Validate the original reference before deriving the sibling path.
    store_paths.local_generated_artifact_path(run_uri, manifest_relative_path)
    relative = PurePosixPath(manifest_relative_path).with_name(
        "execution-resources.json"
    )
    return store_paths.local_generated_artifact_path(run_uri, str(relative))


def _require_same_bytes(path: Path, expected: bytes) -> None:
    if path.read_bytes() != expected:
        raise RuntimeResourceError(
            f"private execution-resource handoff conflicts with retained preparation at {path}; "
            f"{_GUIDANCE}; retained bytes were not changed"
        )

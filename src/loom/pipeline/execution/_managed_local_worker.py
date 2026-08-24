"""Private child entry point for one GPU-bound managed-local stage."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from loom.io.codecs import create_default_codec_registry
from loom.pipeline.execution.models import StageWorkerRequest
from loom.pipeline.execution.stage_worker import execute_stage_worker_request
from loom.pipeline.resources import DEFAULT_RESOURCE_VALIDATOR_REGISTRY
from loom.pipeline.status import StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.plugins import (
    LOOM_CODECS_GROUP,
    LOOM_RESOURCE_VALIDATORS_GROUP,
    list_entry_points,
    load_codec_entry_points,
    load_resource_validator_entry_points,
    resolve_plugin_selections,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-uri", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--attempt", required=True, type=int)
    parser.add_argument("--plugin", action="append", default=[])
    args = parser.parse_args(argv)
    if args.attempt < 1:
        parser.error("--attempt must be positive")

    store = LocalRunStore()
    raw_request = store.read_stage_worker_request(
        args.run_uri,
        args.stage,
        attempt=args.attempt,
    )
    if raw_request is None:
        raise RuntimeError("managed-local worker request is missing")
    request = StageWorkerRequest.from_dict(raw_request)
    if (
        request.run_uri != args.run_uri
        or request.stage_name != args.stage
        or request.attempt != args.attempt
    ):
        raise RuntimeError("managed-local worker request identity conflicts")
    if (
        store.read_stage_worker_result(
            request.run_uri,
            request.stage_name,
            attempt=request.attempt,
        )
        is not None
    ):
        raise RuntimeError("managed-local worker result already exists")

    selected_records = ()
    artifact_store_factory = None
    validator_registry = None
    if args.plugin:
        allowed_groups = (LOOM_CODECS_GROUP, LOOM_RESOURCE_VALIDATORS_GROUP)
        selected_records = resolve_plugin_selections(
            tuple(args.plugin),
            list_entry_points(groups=allowed_groups),
            allowed_groups=allowed_groups,
        )
        codecs = create_default_codec_registry()
        load_codec_entry_points(
            selected_records,
            codecs,
            selected=selected_records,
            strict=True,
        )
        validator_registry, _ = load_resource_validator_entry_points(
            selected_records,
            DEFAULT_RESOURCE_VALIDATOR_REGISTRY,
            selected=selected_records,
            strict=True,
        )

        def selected_artifact_store_factory(root: Path) -> LocalArtifactStore:
            return LocalArtifactStore(root, codec_registry=codecs)

        artifact_store_factory = selected_artifact_store_factory

    result = execute_stage_worker_request(
        run_store=store,
        worker_request=request,
        artifact_store_factory=artifact_store_factory,
        selected_plugin_records=selected_records,
        resource_validator_registry=validator_registry,
    )
    store.write_stage_worker_result(
        request.run_uri,
        request.stage_name,
        result.to_dict(),
        attempt=request.attempt,
    )
    return 0 if result.status in {StageStatus.SUCCEEDED, StageStatus.CANCELLED} else 1


if __name__ == "__main__":
    raise SystemExit(main())

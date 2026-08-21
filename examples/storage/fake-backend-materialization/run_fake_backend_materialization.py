"""Register a fake backend and explicitly copy one local artifact payload."""

from __future__ import annotations

# ruff: noqa: E402

import os
from pathlib import Path
import sys

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loom.artifacts import ArtifactRef, ArtifactStoreRef
from loom.fingerprints import hash_bytes
from loom.io.uris import path_to_file_uri
from loom.pipeline.stores import (
    ArtifactMaterializationRequest,
    ArtifactStoreBackendOperation,
    ArtifactStoreBackendRegistry,
    materialize_artifact_locally,
)

from fake_backend import ExampleBackendFactory, is_backend_handler


HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    journey_root = output_root / "fake-backend-materialization"
    source_path = journey_root / "source.bin"
    target_path = journey_root / "materialized" / "payload.bin"
    payload = b"local materialization example payload\n"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(payload)
    artifact = ArtifactRef(
        artifact_id="example/payload",
        uri=path_to_file_uri(source_path),
        artifact_type="bytes",
        codec_key="bytes.v1",
        checksum=hash_bytes(payload),
        producer_stage="example",
    )

    registry = ArtifactStoreBackendRegistry((ExampleBackendFactory(),))
    handler = registry.create_handler(
        "example-backend",
        ArtifactStoreRef(
            kind="example-backend",
            uri="example://not-a-provider/payloads",
            display_uri="example://local-fixture/payloads",
        ),
    )
    if not is_backend_handler(handler):
        raise RuntimeError("registry did not create an artifact-store backend handler")
    capability = handler.capabilities.support_for(
        ArtifactStoreBackendOperation.MATERIALIZE
    )
    operation = handler.unsupported_operation(
        ArtifactStoreBackendOperation.MATERIALIZE,
        message="the fake backend never materializes provider payloads",
    )

    materialized = materialize_artifact_locally(
        ArtifactMaterializationRequest(artifact=artifact, target_path=target_path)
    )
    if not materialized.succeeded or target_path.read_bytes() != payload:
        raise RuntimeError("local materialization did not copy the exact payload")
    if materialized.materialized_ref is None:
        raise RuntimeError("local materialization did not return a materialized ref")
    if materialized.materialized_ref.checksum != artifact.checksum:
        raise RuntimeError("local materialization did not preserve the checksum")

    print(f"registered_backend_kind: {registry.registered_kinds[0]}")
    print(f"materialize_capability: {capability.support.value}")
    print(f"backend_operation_support: {operation.support.value}")
    print(f"backend_operation: {operation.operation.value}")
    print(f"materialization_status: {materialized.operation.status.value}")
    print(f"materialization_operation: {materialized.operation.operation}")
    print("checksum_verified: True")
    print("bytes_equal: True")
    print(f"bytes_copied: {materialized.bytes_copied}")


if __name__ == "__main__":
    main()

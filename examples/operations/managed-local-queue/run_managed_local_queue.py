"""Run a persisted dependency-ordered pipeline through the local daemon."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import sys
import tempfile

from loom.artifacts import ArtifactRef
from loom.pipeline import PipelineSpec
from loom.pipeline.context import StageContext
from loom.pipeline.planning import plan_pipeline
from loom.pipeline.status import RunStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore, path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.queue import (
    LocalDaemon,
    LocalDaemonAdmissionRequest,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    ResidentWorkerLaunchProfile,
    prepare_managed_local_runtime_record,
)
from loom.serialization import json_dumps_pretty


class ProduceStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        return {
            "data": context.save_artifact(
                "data",
                {"value": 42},
                artifact_type="json",
                codec_key="json.v1",
            )
        }


class ConsumeStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        value = context.load_input("data", expected_type="json")
        return {
            "report": context.save_artifact(
                "report",
                f"consumed {value}",
                artifact_type="text",
                codec_key="text.v1",
            )
        }


def main() -> None:
    here = Path(__file__).resolve().parent
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", here / "output"))
    output_root.mkdir(parents=True, exist_ok=True)
    example_root = Path(tempfile.mkdtemp(prefix="run-", dir=output_root))
    run_root = example_root / "runs"
    store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "pipeline-1")
    store.create_run(run_uri)
    pipeline = {
        "name": "managed-local-daemon-example",
        "stages": [
            {
                "name": "produce",
                "factory": {"_target_": "__main__.ProduceStage"},
                "resources": _cpu_resource(),
                "outputs": {
                    "data": {
                        "artifact_type": "json",
                        "codec_key": "json.v1",
                    }
                },
            },
            {
                "name": "consume",
                "factory": {"_target_": "__main__.ConsumeStage"},
                "depends_on": ["produce"],
                "inputs": {"data": "produce.data"},
                "resources": _cpu_resource(),
                "outputs": {
                    "report": {
                        "artifact_type": "text",
                        "codec_key": "text.v1",
                    }
                },
            },
        ],
    }
    spec = PipelineSpec.from_config(pipeline)
    plan = plan_pipeline(
        spec,
        run_uri=run_uri,
        run_store=store,
        artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)),
        persist=True,
    )
    store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {
                stage_name: {"executor": "local"} for stage_name in spec.stage_names
            },
        },
    )
    store.write_config_snapshot(
        run_uri,
        "resolved",
        json_dumps_pretty({"pipeline": pipeline}),
    )
    prepare_managed_local_runtime_record(
        store=store, run_uri=run_uri, plan=plan, pipeline=spec
    )
    authority = SQLitePerRunAuthorityStore(run_uri)
    authority.create_run(run_uri, status=RunStatus.RUNNING)

    config = LocalDaemonConfig(
        coordinator_root=example_root / "coordinator",
        agent_root=example_root / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=ResidentWorkerLaunchProfile(
            project_root=Path.cwd(),
            python_executable=Path(sys.executable),
            descriptor={
                "profile_id": "local-default",
                "revision": "v1",
                "project_fingerprint": "managed-local-example",
                "environment_fingerprint": "managed-local-example",
                "executor_fingerprint": "local",
            },
        ),
    )
    LocalDaemon.initialize(config)
    daemon = LocalDaemon(config)
    started = daemon.start()
    try:
        client = daemon.client_view(
            LocalDaemonPrincipal("example-client", LocalDaemonRole.CLIENT)
        )
        client.submit(LocalDaemonAdmissionRequest("example-run", run_uri))
        completed = client.wait("example-run", timeout_seconds=10)
    finally:
        daemon.stop()

    print("managed_local_daemon:")
    print(f"  coordinator: {started.coordinator_id}")
    print(f"  status: {completed.state.value}")
    print("  stages: produce,consume")
    print("  admissions: 1")
    print(f"  root: {example_root}")


def _cpu_resource() -> dict[str, object]:
    return {"entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}}


if __name__ == "__main__":
    main()

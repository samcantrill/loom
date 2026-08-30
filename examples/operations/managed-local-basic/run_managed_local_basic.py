"""Run, inspect, restart, and cleanly stop one managed-local pipeline."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import sys


OPERATIONS_ROOT = Path(__file__).resolve().parents[1]
if str(OPERATIONS_ROOT) not in sys.path:
    sys.path.insert(0, str(OPERATIONS_ROOT))

from _managed_journey_support import (  # noqa: E402
    JourneyRecorder,
    assert_processes_dead,
    example_root,
)
from loom.artifacts import ArtifactRef  # noqa: E402
from loom.pipeline import PipelineSpec  # noqa: E402
from loom.pipeline.context import StageContext  # noqa: E402
from loom.pipeline.planning import plan_pipeline  # noqa: E402
from loom.pipeline.stores import (  # noqa: E402
    LocalArtifactStore,
    LocalRunStore,
    path_to_run_uri,
)
from loom.pipeline.stores.coordinator_authority import (  # noqa: E402
    initialize_embedded_coordinator_authority,
)
from loom.queue import (  # noqa: E402
    ExecutionRequirement,
    LocalDaemon,
    LocalDaemonConfig,
    LocalDaemonPrincipal,
    LocalDaemonRole,
    LocalDaemonSocketServer,
    ResidentWorkerLaunchProfile,
    prepare_managed_local_runtime_record,
)
from loom.serialization import json_dumps_pretty  # noqa: E402


class ProduceStage:
    def run(
        self, context: StageContext, inputs: Mapping[str, ArtifactRef]
    ) -> Mapping[str, ArtifactRef]:
        del inputs
        return {
            "data": context.save_artifact(
                "data", {"value": 42}, artifact_type="json", codec_key="json.v1"
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
    recorder = JourneyRecorder()
    root = example_root("managed-local-basic")
    run_root = root / "runs"
    run_store = LocalRunStore(run_root)
    run_uri = path_to_run_uri(run_root / "pipeline-1")
    run_store.create_run(run_uri)
    pipeline_config = _pipeline_config()
    pipeline = PipelineSpec.from_config(pipeline_config)
    plan = plan_pipeline(
        pipeline,
        run_uri=run_uri,
        run_store=run_store,
        artifact_store=LocalArtifactStore(run_store.local_artifact_root(run_uri)),
        persist=True,
    )
    run_store.write_runtime_metadata(
        run_uri,
        {
            "executor": "local",
            "stages": {
                stage_name: {"executor": "local"} for stage_name in pipeline.stage_names
            },
        },
    )
    run_store.write_config_snapshot(
        run_uri, "resolved", json_dumps_pretty({"pipeline": pipeline_config})
    )
    recorder.python(
        "prepare_managed_local_runtime_record",
        lambda: prepare_managed_local_runtime_record(
            store=run_store,
            run_uri=run_uri,
            plan=plan,
            pipeline=pipeline,
            execution_requirements={
                stage_name: ExecutionRequirement(
                    "managed-local-example", "managed-local-example", "local"
                )
                for stage_name in pipeline.stage_names
            },
        ),
    )
    recorder.python(
        "initialize_embedded_coordinator_authority",
        lambda: initialize_embedded_coordinator_authority(run_uri),
    )
    config = LocalDaemonConfig(
        coordinator_root=root / "coordinator",
        agent_root=root / "agent",
        run_store_root=run_root,
        resident_worker_launch_profile=ResidentWorkerLaunchProfile(
            project_root=Path(__file__).resolve().parent,
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
    recorder.python("LocalDaemon.initialize", lambda: LocalDaemon.initialize(config))

    first = LocalDaemon(config)
    first_server = LocalDaemonSocketServer(first, config.endpoint)
    try:
        started = recorder.python("LocalDaemon.start", first.start)
        recorder.python("LocalDaemonSocketServer.start", first_server.start)
        recorder.observe_process_tree(os.getpid())
        status = recorder.cli(
            "queue", "daemon-status", "--endpoint", str(config.endpoint)
        )
        submitted = recorder.cli(
            "queue",
            "daemon-submit",
            "--endpoint",
            str(config.endpoint),
            "example-run",
            run_uri,
        )
        admissions = recorder.cli(
            "queue",
            "daemon-admissions",
            "--endpoint",
            str(config.endpoint),
            "--limit",
            "10",
        )
        admission_id = str(submitted["admission_id"])
        detail = recorder.cli(
            "queue",
            "daemon-admission",
            "--endpoint",
            str(config.endpoint),
            admission_id,
        )
        completed = recorder.cli(
            "queue",
            "daemon-wait",
            "--endpoint",
            str(config.endpoint),
            "example-run",
            "--timeout",
            "15",
        )
        client = recorder.python(
            "LocalDaemon.client_view",
            lambda: first.client_view(
                LocalDaemonPrincipal("example-client", LocalDaemonRole.CLIENT)
            ),
        )
        recorder.python("LocalDaemonClientView.status", client.status)
        recorder.python(
            "LocalDaemonClientView.admission", lambda: client.admission(admission_id)
        )
        if status["coordinator_id"] != started.coordinator_id:
            raise RuntimeError("CLI status observed another coordinator")
        admission_items = admissions.get("admissions")
        detail_admission = detail.get("admission")
        if (
            not isinstance(admission_items, list)
            or len(admission_items) != 1
            or not isinstance(detail_admission, Mapping)
            or detail_admission.get("admission_id") != admission_id
        ):
            raise RuntimeError("bounded admission reads did not find the submitted run")
        if completed["state"] != "SUCCEEDED":
            raise RuntimeError("managed-local run did not succeed")
    finally:
        recorder.python("LocalDaemonSocketServer.stop", first_server.stop)
        recorder.python("LocalDaemon.stop", first.stop)
    assert_processes_dead(recorder.started_pids)

    replacement = LocalDaemon(config)
    replacement_server = LocalDaemonSocketServer(replacement, config.endpoint)
    try:
        restarted = recorder.python("LocalDaemon.start", replacement.start)
        recorder.python("LocalDaemonSocketServer.start", replacement_server.start)
        recorder.observe_process_tree(os.getpid())
        retained = recorder.cli(
            "queue",
            "daemon-admission",
            "--endpoint",
            str(config.endpoint),
            admission_id,
        )
        if restarted.coordinator_id != started.coordinator_id:
            raise RuntimeError("restart changed the stable coordinator identity")
        if restarted.coordinator_epoch == started.coordinator_epoch:
            raise RuntimeError("restart did not rotate the coordinator epoch")
        retained_admission = retained.get("admission")
        if (
            not isinstance(retained_admission, Mapping)
            or retained_admission.get("state") != "SUCCEEDED"
        ):
            raise RuntimeError("restart lost the terminal admission")
    finally:
        recorder.python("LocalDaemonSocketServer.stop", replacement_server.stop)
        recorder.python("LocalDaemon.stop", replacement.stop)
    assert_processes_dead(recorder.started_pids)

    recorder.emit(
        coordinator_id=started.coordinator_id,
        admission_id=admission_id,
        status="SUCCEEDED",
        restarted=True,
        root=str(root),
    )


def _pipeline_config() -> dict[str, object]:
    return {
        "name": "managed-local-basic",
        "stages": [
            {
                "name": "produce",
                "factory": {"_target_": "run_managed_local_basic.ProduceStage"},
                "resources": _cpu_resource(),
                "outputs": {"data": {"artifact_type": "json", "codec_key": "json.v1"}},
            },
            {
                "name": "consume",
                "factory": {"_target_": "run_managed_local_basic.ConsumeStage"},
                "depends_on": ["produce"],
                "inputs": {"data": "produce.data"},
                "resources": _cpu_resource(),
                "outputs": {
                    "report": {"artifact_type": "text", "codec_key": "text.v1"}
                },
            },
        ],
    }


def _cpu_resource() -> dict[str, object]:
    return {"entries": {"cpu": {"kind": "cpu", "amount": 1, "unit": "count"}}}


if __name__ == "__main__":
    main()

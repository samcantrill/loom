"""Integration tests for Apptainer prepared-worker execution."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import cast

from loom.pipeline import PipelineSpec
from loom.pipeline.execution import (
    PipelineRunner,
    RunRequest,
    StageWorkerRunRequest,
    create_authority_backed_serial_run_store,
    run_stage_worker,
)
from loom.pipeline.executors import ApptainerExecutor, SingularityExecutor
from loom.pipeline.executors.apptainer import (
    ApptainerCommandResult,
    ApptainerExecCommand,
)
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LegacyRunStore, LocalArtifactStore
from loom.pipeline.stores.service_authority import LocalAuthorityService
from loom.provenance.models import ProvenanceCaptureOptions


class InProcessApptainerRunner:
    def __init__(self, store: LegacyRunStore) -> None:
        self.store = store
        self.calls: list[ApptainerExecCommand] = []

    def require(self, command: str) -> None:
        assert command
        return None

    def run(
        self,
        command: ApptainerExecCommand,
        *,
        timeout_seconds: int | float | None = None,
    ) -> ApptainerCommandResult:
        self.calls.append(command)
        run_stage_worker(
            run_store=self.store,
            request=StageWorkerRunRequest(
                run_uri=_option(command.argv, "--run-uri"),
                stage_name=_option(command.argv, "--stage"),
                attempt=int(_option(command.argv, "--attempt")),
            ),
        )
        return ApptainerCommandResult(
            command=command.argv[0],
            argv=command.argv,
            redacted_argv=cast(Sequence[str], command.redacted_argv),
            returncode=0,
            timeout_seconds=timeout_seconds,
        )

    def version(self, *_args: object, **_kwargs: object) -> ApptainerCommandResult:
        return ApptainerCommandResult(
            command="apptainer",
            argv=("apptainer", "--version"),
            redacted_argv=("apptainer", "--version"),
            returncode=0,
        )


def _option(argv: Sequence[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def _spec() -> PipelineSpec:
    return PipelineSpec.from_config(
        {
            "name": "demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": (
                            "tests.support.pipeline_execution_stages.JsonProducerStage"
                        )
                    },
                    "config": {"value": 123},
                    "outputs": {
                        "data": {"artifact_type": "json", "codec_key": "json.v1"}
                    },
                }
            ],
        }
    )


def _request(*, executor: str = "apptainer") -> RunRequest:
    return RunRequest(
        pipeline=_spec(),
        options={
            "executor": executor,
            "adapter_options": {
                "container": {
                    "image": {"reference": "analysis.sif"},
                    "environment": {"variables": {"TOKEN": "secret"}},
                },
                "apptainer": {"cleanenv": True, "nv": True},
            },
        },
        provenance_options=ProvenanceCaptureOptions(
            capture_git=False,
            capture_environment=False,
            capture_dependencies=False,
            capture_command=False,
        ),
    )


def test_apptainer_executor_fake_runner_parent_finalizes_stage(
    tmp_path: Path,
) -> None:
    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=service.config(),
        )
        apptainer_runner = InProcessApptainerRunner(store)

        result = PipelineRunner(
            run_store=store,
            executor=ApptainerExecutor(
                run_store=store,
                apptainer_command_runner=apptainer_runner,
            ),
        ).run(_request())

        assert result.status == RunStatus.SUCCEEDED
        assert result.stage_results["build"].status == StageStatus.SUCCEEDED
        outputs = store.read_stage_outputs(result.run_uri, "build")
        assert outputs is not None
        artifact_store = LocalArtifactStore(store.local_artifact_root(result.run_uri))
        assert artifact_store.load(outputs["data"]) == {"value": 123}
        assert apptainer_runner.calls
        assert apptainer_runner.calls[0].argv[:3] == (
            "apptainer",
            "exec",
            "--cleanenv",
        )
        assert "--run-uri" in apptainer_runner.calls[0].argv
        assert store.read_stage_worker_result(
            result.run_uri,
            "build",
            attempt=1,
        )
        provenance = store.read_stage_provenance(result.run_uri, "build")
        assert provenance is not None
        executor_metadata = cast(dict[str, object], provenance["executor_metadata"])
        assert executor_metadata["executor"] == "apptainer"
        assert executor_metadata["returncode"] == 0
        assert "secret" not in repr(executor_metadata)


def test_singularity_executor_fake_runner_uses_singularity_command(
    tmp_path: Path,
) -> None:
    with LocalAuthorityService.start() as service:
        store = create_authority_backed_serial_run_store(
            tmp_path / "runs",
            authority_config=service.config(),
        )
        apptainer_runner = InProcessApptainerRunner(store)

        result = PipelineRunner(
            run_store=store,
            executor=SingularityExecutor(
                run_store=store,
                apptainer_command_runner=apptainer_runner,
            ),
        ).run(_request(executor="singularity"))

        assert result.status == RunStatus.SUCCEEDED
        assert apptainer_runner.calls[0].argv[:2] == ("singularity", "exec")
        executor_metadata = cast(
            dict[str, object],
            result.stage_results["build"].executor_metadata,
        )
        assert executor_metadata["executor"] == "singularity"
        assert executor_metadata["selected_command"] == "singularity"

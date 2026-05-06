"""End-to-end local pipeline run through public Python APIs."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest

from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.locks import RunLockRecord
from loom.pipeline.planning import PlanAction
from loom.pipeline.status import RunStatus, StageStatus
from loom.pipeline.stores import LocalArtifactStore, LocalRunStore
from loom.serialization import PlainData
from tests.support.pipeline_execution_configs import local_execution_config


pytest.importorskip("pydantic")
pytest.importorskip("omegaconf")
pytest.importorskip("yaml")

from loom.config import (
    RecipeCatalog,
    compose_config,
    compose_config_with_catalog,
    register_recipe,
)

pytestmark = pytest.mark.e2e


def _failure_config(target: str) -> dict[str, PlainData]:
    return cast(
        dict[str, PlainData],
        {
            "pipeline": {
                "name": "failure-demo",
                "stages": [
                    {
                        "name": "build",
                        "factory": {"_target_": target},
                        "outputs": {
                            "data": {
                                "artifact_type": "json",
                                "codec_key": "json.v1",
                            }
                        },
                    },
                    {
                        "name": "report",
                        "factory": {
                            "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                        },
                        "inputs": {"data": "build.data"},
                        "outputs": {
                            "text": {
                                "artifact_type": "text",
                                "codec_key": "text.v1",
                            }
                        },
                    },
                ],
            }
        },
    )


def _legacy_catalog_recipe(**_: Any) -> dict[str, Any]:
    return {
        "name": "legacy-pipeline",
        "stages": [
            {
                "name": "legacy",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                },
                "config": {"value": 100},
                "outputs": {
                    "data": {"artifact_type": "json", "codec_key": "json.v1"},
                },
            }
        ],
    }


def _explicit_catalog_recipe(**_: Any) -> dict[str, Any]:
    return {
        "name": "explicit-pipeline",
        "stages": [
            {
                "name": "build",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.JsonProducerStage"
                },
                "config": {"value": 1},
                "outputs": {
                    "data": {"artifact_type": "json", "codec_key": "json.v1"},
                },
            },
            {
                "name": "report",
                "factory": {
                    "_target_": "tests.support.pipeline_execution_stages.TextConsumerStage"
                },
                "inputs": {"data": "build.data"},
                "outputs": {
                    "text": {"artifact_type": "text", "codec_key": "text.v1"},
                },
            },
        ],
    }


class _TrackingLocalRunStore(LocalRunStore):
    def __init__(self, run_root: Path) -> None:
        super().__init__(run_root)
        self.lock_events: list[str] = []

    def acquire_run_lock(
        self,
        run_id: str,
        *,
        owner: Mapping[str, Any] | None = None,
    ) -> RunLockRecord:
        self.lock_events.append("acquire")
        return super().acquire_run_lock(run_id, owner=owner)

    def release_run_lock(self, run_id: str, token: str) -> None:
        self.lock_events.append("release")
        super().release_run_lock(run_id, token)


def test_local_pipeline_run_and_resume_from_config(tmp_path: Path) -> None:
    counter_path = tmp_path / "counter.txt"
    run_store = LocalRunStore(tmp_path / "runs")
    runner = PipelineRunner(run_store=run_store)

    result = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path), run_id="run1"
        )
    )
    resumed = runner.run(
        RunRequest(
            config=local_execution_config(counter_path=counter_path),
            run_id="run1",
            open_existing=True,
        )
    )

    assert result.status == RunStatus.SUCCEEDED
    assert resumed.status == RunStatus.SUCCEEDED
    assert resumed.stage_results["build"].action == PlanAction.REUSE
    assert resumed.stage_results["report"].action == PlanAction.REUSE
    assert counter_path.read_text(encoding="utf-8") == "1"
    run_dir = tmp_path / "runs" / "run1"
    for relative in [
        "config/resolved.yaml",
        "plan.json",
        "status.json",
        "artifacts.json",
        "stages/build/inputs.json",
        "stages/build/outputs.json",
        "stages/build/fingerprint.json",
        "stages/build/provenance.json",
        "stages/report/inputs.json",
        "stages/report/outputs.json",
        "stages/report/fingerprint.json",
        "stages/report/provenance.json",
    ]:
        assert (run_dir / relative).is_file(), relative


def test_local_pipeline_run_with_composed_config_persists_manifest_not_resolved_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "name: composed-e2e\n"
        "metadata:\n"
        "  runtime_root: ${oc.env:LOOM_E2E_RUNNER_ROOT}\n"
        "pipeline:\n"
        "  name: demo\n"
        "  stages:\n"
        "    - name: build\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOOM_E2E_RUNNER_ROOT", "/runtime/from-env")
    composed = compose_config(config_path)
    run_store = LocalRunStore(tmp_path / "runs")

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=composed, run_id="run1")
    )

    run_dir = tmp_path / "runs" / "run1"
    composition_manifest_path = run_dir / "config" / "composition_manifest.json"
    recipe_manifest_path = run_dir / "config" / "recipe_manifest.json"
    persisted_wrapper = json.loads(composition_manifest_path.read_text(encoding="utf-8"))
    serialized_wrapper = json.dumps(persisted_wrapper, sort_keys=True)

    assert result.status == RunStatus.SUCCEEDED
    assert composed.resolved["metadata"] == {"runtime_root": "/runtime/from-env"}
    assert run_store.read_composition_manifest("run1") == composed.manifest.to_dict()
    assert run_store.read_recipe_manifest("run1") == composed.recipe_manifest
    assert composition_manifest_path.is_file()
    assert recipe_manifest_path.is_file()
    assert persisted_wrapper["schema_version"] == 1
    assert persisted_wrapper["run_id"] == "run1"
    assert set(persisted_wrapper) == {
        "schema_version",
        "run_id",
        "created_at",
        "composition_manifest",
    }
    assert persisted_wrapper["composition_manifest"] == composed.manifest.to_dict()
    assert "oc.env:LOOM_E2E_RUNNER_ROOT" in serialized_wrapper
    assert "/runtime/from-env" not in serialized_wrapper
    assert "source_snapshots" not in serialized_wrapper
    assert not (run_dir / "config" / "resolved.yaml").exists()
    assert not (run_dir / "config" / "resolved.redacted.yaml").exists()


def test_local_pipeline_run_fails_with_blocked_outcomes(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(
            config=_failure_config(
                "tests.support.pipeline_execution_stages.FailingStage"
            ),
            run_id="run1",
        )
    )
    blocked = run_store.read_stage_status("run1", "report")

    assert result.status == RunStatus.FAILED
    assert result.stage_results["build"].status == StageStatus.FAILED
    assert result.stage_results["report"].status == StageStatus.BLOCKED
    assert blocked is not None
    assert blocked.status == StageStatus.BLOCKED
    assert blocked.metadata["blocked_by"] == ["build"]
    assert blocked.metadata["reason_code"] == "upstream_failed"
    assert run_store.read_events("run1")[-1].event_type == "run.failed"


def test_local_pipeline_run_uses_explicit_catalog_without_global_recipes(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "name: catalog-demo\npipeline:\n  _recipe_: explicit_catalog_pipeline\n",
        encoding="utf-8",
    )
    register_recipe("explicit_catalog_pipeline", _legacy_catalog_recipe)
    catalog = RecipeCatalog()
    catalog.register("explicit_catalog_pipeline", _explicit_catalog_recipe)
    composed = compose_config_with_catalog(config_path, recipe_catalog=catalog)
    run_store = LocalRunStore(tmp_path / "runs")

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=composed.resolved, run_id="run1")
    )

    assert result.status == RunStatus.SUCCEEDED
    assert set(result.stage_results) == {"build", "report"}


def test_local_pipeline_run_keeps_factory_init_separate_from_stage_config(
    tmp_path: Path,
) -> None:
    run_store = LocalRunStore(tmp_path / "runs")
    config = {
        "pipeline": {
            "name": "factory-init-demo",
            "stages": [
                {
                    "name": "build",
                    "factory": {
                        "_target_": "tests.support.pipeline_execution_stages.ConfiguredProducerStage",
                        "init": {"constructor_value": 7},
                    },
                    "config": {"runtime_value": 11},
                    "outputs": {
                        "data": {"artifact_type": "json", "codec_key": "json.v1"},
                    },
                }
            ],
        }
    }

    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=config, run_id="run1")
    )
    artifact_store = LocalArtifactStore(run_store.local_artifact_root("run1"))
    payload = artifact_store.load(result.stage_results["build"].outputs["data"])

    assert result.status == RunStatus.SUCCEEDED
    assert payload == {
        "constructor": 7,
        "runtime": 11,
        "constructor_in_stage_config": False,
    }


def test_local_pipeline_run_records_events_and_lock_lifecycle(tmp_path: Path) -> None:
    run_store = _TrackingLocalRunStore(tmp_path / "runs")
    result = PipelineRunner(run_store=run_store).run(
        RunRequest(config=local_execution_config(), run_id="run1")
    )
    events = run_store.read_events("run1")
    event_types = [event.event_type for event in events]

    assert result.status == RunStatus.SUCCEEDED
    assert event_types[:2] == ["run.created", "run.planned"]
    assert event_types[-1] == "run.completed"
    assert run_store.lock_events == ["acquire", "release"]
    assert run_store.read_run_lock("run1") is None

"""Demonstrate fingerprint-backed reuse and checksum-local branch repair."""

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

from weave import compose_config
from loom.io.uris import uri_to_path
from loom.pipeline import PipelineRunner, RunRequest
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.planning import PlanAction, PlanReasonCode
from loom.pipeline.stores import path_to_run_uri
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from loom.timestamps import safe_timestamp_for_path


HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(
        run_root / f"local-example-{safe_timestamp_for_path(timespec='seconds')}"
    )

    composed = compose_config(HERE / "pipeline.yaml")
    runner = PipelineRunner(
        run_store=create_authority_backed_serial_run_store(
            run_root,
            authority_store=SQLitePerRunAuthorityStore(),
        )
    )

    first = runner.run(RunRequest(config=composed, run_uri=run_uri))
    second = runner.run(
        RunRequest(config=composed, run_uri=run_uri, open_existing=True)
    )
    corrupted = second.artifact_index["left_seed.numbers"]
    uri_to_path(corrupted.uri).write_bytes(b"checksum-invalid example payload")
    repaired = runner.run(
        RunRequest(config=composed, run_uri=run_uri, open_existing=True)
    )

    _require_actions(
        second,
        {
            "left_seed": PlanAction.REUSE,
            "left_summarize": PlanAction.REUSE,
            "right_seed": PlanAction.REUSE,
            "right_summarize": PlanAction.REUSE,
        },
        label="unchanged resume",
    )
    _require_actions(
        repaired,
        {
            "left_seed": PlanAction.RUN,
            "left_summarize": PlanAction.RUN,
            "right_seed": PlanAction.REUSE,
            "right_summarize": PlanAction.REUSE,
        },
        label="checksum repair",
    )
    _require_reason(repaired, "left_seed", PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH)

    print(f"run_uri: {first.run_uri}")
    print(f"first_status: {first.status.name}")
    print(f"config_fingerprint: {_config_fingerprint(runner, first.run_uri)}")
    print(f"pipeline_stage_fingerprint_count: {_stage_fingerprint_count(runner, first.run_uri)}")
    print("first_stage_actions:")
    for stage_name, result in first.stage_results.items():
        print(f"  {stage_name}: {result.action.value}")

    print(f"resume_status: {second.status.name}")
    print(f"resume_actions: {_action_summary_from_result(second)}")
    print("resume_stage_actions:")
    for stage_name, result in second.stage_results.items():
        print(f"  {stage_name}: {result.action.value}")

    print(f"repair_status: {repaired.status.name}")
    print(f"repair_actions: {_action_summary_from_result(repaired)}")
    print("repair_stage_actions:")
    for stage_name, result in repaired.stage_results.items():
        print(f"  {stage_name}: {result.action.value}")
    print("repair_reason: ARTIFACT_CHECKSUM_MISMATCH")

    print("artifacts:")
    for key, ref in sorted(second.artifact_index.items()):
        print(f"  {key}: {ref.uri}")


def _require_actions(
    result: object,
    expected: dict[str, PlanAction],
    *,
    label: str,
) -> None:
    stage_results = getattr(result, "stage_results", None)
    if not hasattr(stage_results, "items"):
        raise RuntimeError(f"{label} did not return stage results")
    actual = {name: stage_result.action for name, stage_result in stage_results.items()}
    if actual != expected:
        raise RuntimeError(
            f"{label} actions were "
            f"{_action_summary(actual)}, expected {_action_summary(expected)}"
        )


def _require_reason(
    result: object,
    stage_name: str,
    expected: PlanReasonCode,
) -> None:
    stage_results = getattr(result, "stage_results", None)
    if not hasattr(stage_results, "__getitem__"):
        raise RuntimeError("checksum repair did not return stage results")
    reasons = stage_results[stage_name].reasons
    if expected not in {reason.code for reason in reasons}:
        raise RuntimeError(f"{stage_name} did not report {expected.value}")


def _config_fingerprint(runner: PipelineRunner, run_uri: str) -> str:
    manifest = runner.run_store.read_composition_manifest(run_uri)
    if not isinstance(manifest, dict):
        raise RuntimeError("run did not persist a composition manifest")
    records = manifest.get("fingerprint_records")
    if not isinstance(records, list) or not records:
        raise RuntimeError("composition manifest did not contain fingerprint records")
    fingerprint = records[0].get("digest") if isinstance(records[0], dict) else None
    if not isinstance(fingerprint, str) or not fingerprint:
        raise RuntimeError("composition fingerprint record did not contain a digest")
    return fingerprint


def _stage_fingerprint_count(runner: PipelineRunner, run_uri: str) -> int:
    plan = runner.run_store.read_plan(run_uri)
    if not isinstance(plan, dict):
        raise RuntimeError("run did not persist an execution plan")
    stages = plan.get("stage_plans")
    if not isinstance(stages, list) or not stages:
        raise RuntimeError("execution plan did not contain stage plans")
    count = sum(
        1
        for stage in stages
        if isinstance(stage, dict)
        and isinstance(stage.get("fingerprint"), dict)
        and isinstance(stage["fingerprint"].get("fingerprint"), str)
        and stage["fingerprint"]["fingerprint"]
    )
    if count == 0:
        raise RuntimeError("execution plan did not contain stage fingerprint evidence")
    return count


def _action_summary(actions: dict[str, PlanAction]) -> str:
    return ",".join(f"{name}={action.value}" for name, action in actions.items())


def _action_summary_from_result(result: object) -> str:
    stage_results = getattr(result, "stage_results", None)
    if not hasattr(stage_results, "items"):
        raise RuntimeError("result did not return stage results")
    return _action_summary(
        {name: stage_result.action for name, stage_result in stage_results.items()}
    )


if __name__ == "__main__":
    main()

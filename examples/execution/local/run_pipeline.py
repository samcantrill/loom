"""Execute native stages and inspect fingerprint reuse and branch repair plans."""

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
from loom.pipeline.execution import create_authority_backed_serial_run_store
from loom.pipeline.planning import (
    ExecutionPlan,
    PlanAction,
    PlanReasonCode,
    plan_pipeline,
)
from loom.pipeline.specs import parse_pipeline_config
from loom.pipeline.stores import LocalArtifactStore
from loom.pipeline.stores.sqlite_authority import SQLitePerRunAuthorityStore
from examples.execution.agent_workers import run_example, worker_records

HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    outcome = run_example(HERE / "pipeline.yaml", output_root, run_root=run_root)
    admission = outcome.observation.admission
    if admission.state.name != "SUCCEEDED":
        raise RuntimeError("native example failed")
    store = create_authority_backed_serial_run_store(
        run_root, authority_store=SQLitePerRunAuthorityStore()
    )
    saved = ExecutionPlan.from_dict(store.read_plan(admission.run_uri))
    spec = parse_pipeline_config(
        compose_config(HERE / "pipeline.yaml").resolved["pipeline"]
    )
    artifacts = LocalArtifactStore(store.local_artifact_root(admission.run_uri))

    def inspect_plan():
        return plan_pipeline(
            spec,
            run_uri=admission.run_uri,
            run_store=store,
            artifact_store=artifacts,
            fingerprint_context=saved.fingerprint_context,
        )

    unchanged = inspect_plan()
    assert all(stage.action is PlanAction.REUSE for stage in unchanged.stage_plans)
    refs = store.read_artifact_index(admission.run_uri)
    payload = uri_to_path(refs["left_seed.numbers"].uri)
    original = payload.read_bytes()
    try:
        payload.write_bytes(b"checksum-invalid example payload")
        repair = inspect_plan()
        actions = {stage.stage_name: stage.action for stage in repair.stage_plans}
        assert actions == {
            "left_seed": PlanAction.RUN,
            "left_summarize": PlanAction.RUN,
            "right_seed": PlanAction.REUSE,
            "right_summarize": PlanAction.REUSE,
        }
        assert PlanReasonCode.ARTIFACT_CHECKSUM_MISMATCH in {
            reason.code
            for stage in repair.stage_plans
            if stage.stage_name == "left_seed"
            for reason in stage.reasons
        }
    finally:
        payload.write_bytes(original)
    print(f"run_uri: {admission.run_uri}")
    print(f"first_status: {admission.state.name}")
    print(f"pipeline_stage_fingerprint_count: {len(saved.stage_plans)}")
    print("reuse_plan: " + _actions(unchanged))
    print("repair_plan: " + _actions(repair))
    print("repair_reason: ARTIFACT_CHECKSUM_MISMATCH")
    print(f"committed_stage_count: {len(worker_records(outcome))}")
    print("repair_execution: not_requested")


def _actions(plan):
    return ",".join(
        f"{stage.stage_name}={stage.action.value}" for stage in plan.stage_plans
    )


if __name__ == "__main__":
    main()

"""Generate SLURM dry-run artifacts for both supported modes."""

from __future__ import annotations

# ruff: noqa: E402

import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import started_authority_session
from loom.pipeline.stores import path_to_run_uri


HERE = Path(__file__).resolve().parent
SCHEDULER_JOB_ID_KEYS = ("scheduler_job_id", "raw_job_id_output", "dependency_job_ids")


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    config_path = HERE / "pipeline.yaml"

    with started_authority_session(output_root) as authority:
        with scheduler_commands_unavailable():
            summaries = [
                run_dry_run(
                    config_path,
                    run_root,
                    "slurm-single-job",
                    authority.authority_config,
                ),
                run_dry_run(
                    config_path,
                    run_root,
                    "slurm-afterok",
                    authority.authority_config,
                ),
            ]

    print("slurm_dry_run_basics:")
    for summary in summaries:
        print(f"  mode: {summary['mode']}")
        print(f"    planning_id: {summary['planning_id']}")
        print(f"    jobs: {summary['job_count']}")
        print(f"    dependencies: {summary['dependency_count']}")
        print(f"    manifest: {summary['manifest_path']}")
        print(f"    scripts: {','.join(summary['script_paths'])}")
        print(f"    logs: {','.join(summary['log_paths'])}")
        print(f"    warnings: {','.join(summary['warning_codes'])}")
        print(f"    scheduler_ids_absent: {summary['scheduler_ids_absent']}")


def run_dry_run(
    config_path: Path,
    run_root: Path,
    mode: str,
    authority_config,
) -> dict[str, Any]:
    run_uri = path_to_run_uri(run_root / f"{mode}-{uuid4().hex[:8]}")
    import shutil
    result = _plan_example(config_path, run_root, run_uri, mode, authority_config)
    payload = {"warnings": ([{"code": "executor.slurm.sbatch"}] if shutil.which("sbatch") is None else [])}
    if not isinstance(result, dict):
        raise RuntimeError("SLURM dry-run result was not a mapping")
    manifest_path = Path(require_string(result["manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("SLURM manifest did not contain a jobs list")
    script_paths = [
        require_string(item["path"])
        for item in require_mappings(result.get("script_paths", []))
    ]
    log_paths = [
        require_string(item["stdout_relative_path"])
        for item in require_mappings(result.get("log_paths", []))
    ]
    warning_codes = [
        require_string(item["code"])
        for item in require_mappings(payload.get("warnings", []))
    ]
    scheduler_ids_absent = not any(
        any(key in job and job[key] for key in SCHEDULER_JOB_ID_KEYS)
        for job in jobs
        if isinstance(job, dict)
    )
    if not scheduler_ids_absent:
        raise RuntimeError("dry-run manifest unexpectedly included scheduler job IDs")
    return {
        "mode": result["mode"],
        "planning_id": result["planning_id"],
        "job_count": result["job_count"],
        "dependency_count": result["dependency_count"],
        "manifest_path": str(manifest_path),
        "script_paths": script_paths,
        "log_paths": log_paths,
        "warning_codes": warning_codes,
        "scheduler_ids_absent": scheduler_ids_absent,
    }

def require_mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError("expected a list")
    output: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError("expected a list of mappings")
        output.append(item)
    return output


def require_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError("expected a non-empty string")
    return value


@contextmanager
def scheduler_commands_unavailable() -> Iterator[None]:
    original_path = os.environ.get("PATH")
    os.environ["PATH"] = ""
    try:
        yield
    finally:
        if original_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = original_path


def _plan_example(config_path, run_root, run_uri, mode, authority_config):
    """Render this example's scripts through the retained pure planning owners."""
    from weave import compose_config
    from loom.pipeline.validation import validate_pipeline_config
    from loom.pipeline.planning import plan_pipeline
    from loom.pipeline.runtime import merge_config_run_options
    from loom.pipeline.stores import LocalRunStore, LocalArtifactStore
    from loom.pipeline.executors.slurm import SlurmOptions, render_slurm_script
    from loom.pipeline.executors.slurm.planning import build_single_job_planned_submission, build_afterok_planned_submission
    from loom.pipeline.executors.slurm.artifacts import write_slurm_dry_run_artifacts
    from loom.timestamps import utc_timestamp

    composed = compose_config(config_path)
    # Plan durable artifacts from unresolved authored references, never expanded
    # secrets. No worker or scheduler submission is launched by this example.
    spec = validate_pipeline_config(composed.unresolved).spec
    runtime = merge_config_run_options(composed.resolved, explicit={"executor": mode})
    store = LocalRunStore(run_root)
    store.create_run(run_uri)
    plan = plan_pipeline(spec, run_uri=run_uri, run_store=store, artifact_store=LocalArtifactStore(store.local_artifact_root(run_uri)), persist=True)
    options = SlurmOptions.from_dict({**SlurmOptions().to_dict(), **dict(runtime.adapter_options.get("slurm", {}))})
    common = {"run_uri": run_uri, "planning_id": "planning-" + uuid4().hex, "created_at": utc_timestamp(), "options": options, "authority_config": authority_config}
    if mode == "slurm-single-job":
        submission = build_single_job_planned_submission(**common)
    else:
        per_stage = {name: SlurmOptions.from_dict({**options.to_dict(), **dict(value.adapter_options.get("slurm", {}))}) for name, value in runtime.stage_options.items()}
        resources = {name: value.resources for name, value in runtime.stage_options.items()}
        submission = build_afterok_planned_submission(**common, execution_plan=plan, stage_options=per_stage, stage_resources=resources)
    artifacts = write_slurm_dry_run_artifacts(store_paths=store, run_uri=run_uri, submission=submission, scripts={job.logical_key: render_slurm_script(job, options=options) for job in submission.jobs}, plan_metadata={"plan_summary": dict(plan.summary)})
    return {"mode": submission.mode.value, "planning_id": submission.planning_id, "manifest_path": str(artifacts.manifest_artifact.local_path), "job_count": len(submission.jobs), "dependency_count": len(submission.dependencies), "script_paths": [{"logical_key": key, "path": str(value.local_path)} for key, value in artifacts.script_artifacts.items()], "log_paths": [{"stdout_relative_path": job.stdout_relative_path} for job in submission.jobs]}


if __name__ == "__main__":
    main()

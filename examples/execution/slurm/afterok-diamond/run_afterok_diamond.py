"""Generate and inspect a SLURM afterok dry run for a diamond DAG."""

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
from loom.pipeline.stores import path_to_run_uri, run_uri_to_path


HERE = Path(__file__).resolve().parent
SECRET_ENV = "LOOM_EXAMPLE_SLURM_SECRET"
SECRET_VALUE = "EXAMPLE_SLURM_SECRET_VALUE_SHOULD_NOT_PERSIST"


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    run_uri = path_to_run_uri(run_root / f"afterok-diamond-{uuid4().hex[:8]}")
    config_path = HERE / "pipeline.yaml"

    with started_authority_session(output_root) as authority:
        with controlled_environment():
            result = _plan_example(config_path, run_root, run_uri, "slurm-afterok", authority.authority_config)

    manifest_path = Path(require_string(result["manifest_path"]))
    manifest = require_mapping(json.loads(manifest_path.read_text(encoding="utf-8")))
    dependencies = dependency_summary(manifest)
    scripts = script_text_by_key(result)
    run_path = run_uri_to_path(run_uri)
    secret_persisted = contains_text(run_path, SECRET_VALUE)

    if secret_persisted:
        raise RuntimeError("resolved secret value leaked into dry-run artifacts")
    if any("loom stage run" in script for script in scripts.values()):
        raise RuntimeError("afterok dry-run script used the parent-managed worker")
    if not all("loom stage-job run" in script for script in scripts.values()):
        raise RuntimeError("afterok dry-run script missed stage-job continuation")
    if any("scheduler_job_id" in job for job in require_mappings(manifest["jobs"])):
        raise RuntimeError("dry-run manifest unexpectedly included scheduler job IDs")

    print("slurm_afterok_diamond:")
    print(f"  run_uri: {run_uri}")
    print(f"  planning_id: {result['planning_id']}")
    print(f"  job_count: {result['job_count']}")
    print(f"  dependency_count: {result['dependency_count']}")
    print(f"  manifest: {manifest_path}")
    print(f"  dependencies: {format_dependencies(dependencies)}")
    print(f"  train_has_cpu_directive: {'#SBATCH --cpus-per-task=2' in scripts['stage:train']}")
    print(f"  train_partition: {'#SBATCH --partition=train' in scripts['stage:train']}")
    print(f"  report_partition: {'#SBATCH --partition=report' in scripts['stage:report']}")
    print(f"  stage_job_commands: {all('loom stage-job run' in item for item in scripts.values())}")
    print("  scheduler_ids_absent: True")
    print(f"  resolved_secret_persisted: {secret_persisted}")


def dependency_summary(manifest: dict[str, Any]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for item in require_mappings(manifest["dependencies"]):
        key = require_string(item["job_key"])
        upstream = item["upstream_job_keys"]
        if not isinstance(upstream, list) or not all(
            isinstance(value, str) for value in upstream
        ):
            raise RuntimeError("dependency upstream_job_keys must be a string list")
        output[key] = upstream
    return output


def script_text_by_key(result: dict[str, Any]) -> dict[str, str]:
    scripts: dict[str, str] = {}
    for item in require_mappings(result["script_paths"]):
        logical_key = require_string(item["logical_key"])
        path = Path(require_string(item["path"]))
        scripts[logical_key] = path.read_text(encoding="utf-8")
    return scripts


def format_dependencies(dependencies: dict[str, list[str]]) -> str:
    return ",".join(
        f"{key}<-{'+'.join(upstream)}" for key, upstream in sorted(dependencies.items())
    )


def contains_text(root: Path, needle: str) -> bool:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if needle in content:
            return True
    return False

def require_mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("expected a mapping")
    return value


def require_mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError("expected a list")
    output: list[dict[str, Any]] = []
    for item in value:
        output.append(require_mapping(item))
    return output


def require_string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError("expected a non-empty string")
    return value


@contextmanager
def controlled_environment() -> Iterator[None]:
    original_path = os.environ.get("PATH")
    original_secret = os.environ.get(SECRET_ENV)
    os.environ["PATH"] = ""
    os.environ[SECRET_ENV] = SECRET_VALUE
    try:
        yield
    finally:
        if original_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = original_path
        if original_secret is None:
            os.environ.pop(SECRET_ENV, None)
        else:
            os.environ[SECRET_ENV] = original_secret


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

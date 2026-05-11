"""Generate SLURM dry-run artifacts for both supported modes."""

from __future__ import annotations

import io
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from loom.cli.main import main as loom_main
from loom.pipeline.stores import authority_config_to_cli_args, path_to_run_uri
from loom.pipeline.stores.service_authority import LocalAuthorityService


HERE = Path(__file__).resolve().parent
SCHEDULER_JOB_ID_KEYS = ("scheduler_job_id", "raw_job_id_output", "dependency_job_ids")


def main() -> None:
    sys.path.insert(0, str(HERE))
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    run_root = Path(os.environ.get("LOOM_EXAMPLE_RUN_ROOT", output_root / "runs"))
    config_path = HERE / "pipeline.yaml"

    with LocalAuthorityService.start() as service:
        authority_args = authority_config_to_cli_args(service.config())
        with scheduler_commands_unavailable():
            summaries = [
                run_dry_run(config_path, run_root, "slurm-single-job", authority_args),
                run_dry_run(config_path, run_root, "slurm-afterok", authority_args),
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
    authority_args: tuple[str, ...],
) -> dict[str, Any]:
    run_uri = path_to_run_uri(run_root / f"{mode}-{uuid4().hex[:8]}")
    payload = run_cli_json(
        [
            "run",
            str(config_path),
            "--executor",
            mode,
            "--dry-run",
            "--run-uri",
            run_uri,
            *authority_args,
            "--format",
            "json",
        ]
    )
    result = payload["result"]
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


def run_cli_json(argv: list[str], *, expected: int = 0) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = loom_main(argv, stdout=stdout, stderr=stderr)
    if code != expected:
        raise RuntimeError(
            f"loom {' '.join(argv)} exited {code}; stdout={stdout.getvalue()!r}; "
            f"stderr={stderr.getvalue()!r}"
        )
    if stderr.getvalue():
        raise RuntimeError(f"unexpected stderr from loom {' '.join(argv)}")
    payload = json.loads(stdout.getvalue())
    if not isinstance(payload, dict):
        raise RuntimeError("CLI JSON output was not a mapping")
    return payload


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


if __name__ == "__main__":
    main()

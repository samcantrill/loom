"""Representative end-to-end example journey coverage."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.optional_dependency]

REPO_ROOT = next(
    candidate
    for candidate in Path(__file__).resolve().parents
    if (candidate / "pyproject.toml").exists()
)
EXAMPLES_ROOT = REPO_ROOT / "examples"


def test_e2e_example_local_pipeline_run_with_resume(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "execution" / "local" / "run_pipeline.py"
    output_root = tmp_path / "local"
    payload = _parse_summary(_run_example_script(script, output_root))

    assert payload["first_status"] == "SUCCEEDED"
    assert payload["resume_status"] == "SUCCEEDED"
    first_stage_actions = payload["first_stage_actions"]
    resume_stage_actions = payload["resume_stage_actions"]
    assert isinstance(first_stage_actions, dict)
    assert isinstance(resume_stage_actions, dict)
    assert set(first_stage_actions) == {"seed", "summarize"}
    assert set(resume_stage_actions) == {"seed", "summarize"}
    assert resume_stage_actions["seed"] == "REUSE"
    assert resume_stage_actions["summarize"] == "REUSE"
    assert _run_uri_path(payload["run_uri"]).is_dir()


def test_e2e_example_authority_lifecycle_cli(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "operations" / "authority-lifecycle" / "run_authority_lifecycle.py"
    payload = _parse_summary(_run_example_script(script, tmp_path / "authority"))

    summary = payload["authority_lifecycle"]
    assert isinstance(summary, dict)
    assert summary["readiness"] == "ready"
    assert summary["registry_status"] == "valid"
    assert summary["doctor_ok"] is True
    assert summary["restarted_generation_changed"] is True
    assert summary["stop_state"] in {"stopped", "stopping"}


def test_e2e_example_slurm_dry_run_basics(tmp_path: Path) -> None:
    script = (
        EXAMPLES_ROOT / "execution" / "slurm" / "dry-run-basics" / "run_dry_run_basics.py"
    )
    output_root = tmp_path / "slurm"
    summaries = _parse_slurm_summaries(_run_example_script(script, output_root))

    modes = {summary["mode"] for summary in summaries}
    assert modes == {"slurm-single-job", "slurm-afterok"}
    assert len(summaries) == 2
    for summary in summaries:
        assert summary["jobs"] >= 1
        assert summary["dependencies"] >= 0
        assert summary["scheduler_ids_absent"] is True
        manifest = Path(summary["manifest"])
        assert manifest.is_file()
        manifest = Path(summary["manifest"])
        for relative in _parse_csv_list(summary["scripts"]):
            path = _resolve_dry_run_path(relative, manifest)
            assert path.is_file()
        for relative in _parse_csv_list(summary["logs"]):
            path = _resolve_dry_run_path(relative, manifest)
            assert path.suffix == ".log"
        assert "executor.slurm.sbatch" in summary["warnings"]


def test_e2e_example_docker_executor_smoke_and_failure_diagnostics(tmp_path: Path) -> None:
    script = EXAMPLES_ROOT / "execution" / "containers" / "docker" / "run_docker_pipeline.py"
    failure_script = (
        EXAMPLES_ROOT / "execution" / "containers" / "docker" / "run_failure_diagnostics.py"
    )
    output_root = tmp_path / "docker"
    payload = _parse_summary(_run_example_script(script, output_root))

    assert payload["run_status"] == "SUCCEEDED"
    assert payload["seed_executor"] == "docker"
    assert payload["container_image"] == "python:3.12-slim"
    assert payload["artifact_count"] >= 1
    assert payload["fake_docker_call_count"] >= 1
    assert _run_uri_path(payload["run_uri"]).is_dir()

    failure_payload = _parse_summary(
        _run_example_script(failure_script, output_root)
    )

    assert failure_payload["run_status"] == "FAILED"
    assert failure_payload["failure_executor"] == "docker"
    assert failure_payload["failure_exit_code"] == 1
    assert failure_payload["stderr_available"] is True
    assert failure_payload["fake_docker_call_count"] >= 1
    assert _run_uri_path(failure_payload["run_uri"]).is_dir()


def _run_example_script(
    script: Path,
    output_root: Path,
    *,
    expected: int = 0,
) -> str:
    output_root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    pythonpath = [str(REPO_ROOT), str(REPO_ROOT / "src")]
    current_pythonpath = env.get("PYTHONPATH")
    if current_pythonpath:
        pythonpath.append(current_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env["LOOM_EXAMPLE_OUTPUT_ROOT"] = str(output_root)
    env["LOOM_EXAMPLE_RUN_ROOT"] = str(output_root / "runs")

    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(script.parent),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if result.returncode != expected:
        raise AssertionError(
            f"{script} failed with exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if not result.stdout:
        raise AssertionError(f"{script} produced no stdout output")
    return result.stdout


def _parse_summary(output: str) -> dict[str, object]:
    parsed: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, parsed)]

    for raw_line in output.splitlines():
        if not raw_line.strip() or ":" not in raw_line:
            continue

        key, _, value = raw_line.partition(":")
        key = key.strip()
        value = value.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise AssertionError(f"could not parse line without a parent container: {raw_line!r}")

        current = stack[-1][1]
        if not value:
            child: dict[str, object] = {}
            current[key] = child
            stack.append((indent, child))
        else:
            current[key] = _coerce_scalar(value)

    return parsed


def _parse_slurm_summaries(output: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    in_section = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line == "slurm_dry_run_basics:":
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("mode:"):
            if current is not None:
                entries.append(current)
            current = {"mode": _coerce_scalar(line.partition(":")[2].strip())}
            continue
        if current is None:
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key and value:
            current[key.strip()] = _coerce_scalar(value.strip())

    if current is not None:
        entries.append(current)

    if len(entries) != 2:
        raise AssertionError(
            "expected two dry-run summaries, got: "
            + ", ".join(str(summary.get("mode", "<missing>")) for summary in entries)
        )

    return [
        {
            "mode": _require_str(summary["mode"]),
            "jobs": _require_int(summary["jobs"]),
            "dependencies": _require_int(summary["dependencies"]),
            "manifest": _require_str(summary["manifest"]),
            "scripts": summary["scripts"],
            "logs": summary["logs"],
            "warnings": _require_str(summary["warnings"]),
            "scheduler_ids_absent": _require_bool(summary["scheduler_ids_absent"]),
        }
        for summary in entries
    ]


def _parse_csv_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(value) for value in raw]
    if not isinstance(raw, str):
        raise AssertionError(f"expected comma list string, got {raw!r}")
    if not raw:
        return []
    return [item for item in (value.strip() for value in raw.split(",")) if item]


def _resolve_dry_run_path(value: str, manifest: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    run_dir = manifest.parents[3]
    return run_dir / path


def _coerce_scalar(value: str) -> object:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        return int(value)
    except ValueError:
        return value


def _require_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise AssertionError(f"expected boolean value, got {value!r}")
    return value


def _require_str(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AssertionError(f"expected non-empty string, got {value!r}")
    return value


def _require_int(value: object) -> int:
    if not isinstance(value, int):
        raise AssertionError(f"expected integer, got {value!r}")
    return value


def _run_uri_path(value: object) -> Path:
    if not isinstance(value, str):
        raise AssertionError(f"expected file URI string, got {value!r}")
    parsed = urlparse(value)
    if parsed.scheme != "file":
        raise AssertionError(f"expected file URI, got {value!r}")
    return Path(parsed.path)

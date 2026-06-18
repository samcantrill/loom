"""Opt-in real SLURM acceptance tests.

These tests submit real scheduler jobs. They are skipped unless
``LOOM_RUN_SLURM_ACCEPTANCE=1`` and ``LOOM_SLURM_ACCEPTANCE_ROOT`` are set.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import time
from typing import Any
import uuid

import pytest

from loom.cli.main import main
from loom.pipeline.stores import path_to_run_uri

pytestmark = [pytest.mark.slurm, pytest.mark.slow]


@dataclass(frozen=True, slots=True)
class SlurmAcceptanceEnv:
    root: Path
    timeout_seconds: float
    poll_seconds: float


@pytest.fixture()
def slurm_env() -> SlurmAcceptanceEnv:
    if os.environ.get("LOOM_RUN_SLURM_ACCEPTANCE") != "1":
        pytest.skip("set LOOM_RUN_SLURM_ACCEPTANCE=1 to run real SLURM acceptance")
    root_text = os.environ.get("LOOM_SLURM_ACCEPTANCE_ROOT")
    if not root_text:
        pytest.skip("set LOOM_SLURM_ACCEPTANCE_ROOT to a shared filesystem path")
    pytest.importorskip("pydantic")
    pytest.importorskip("omegaconf")
    pytest.importorskip("yaml")
    root = Path(root_text).expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    return SlurmAcceptanceEnv(
        root=root,
        timeout_seconds=float(os.environ.get("LOOM_SLURM_ACCEPTANCE_TIMEOUT", "300")),
        poll_seconds=float(os.environ.get("LOOM_SLURM_ACCEPTANCE_POLL", "5")),
    )


def test_real_slurm_single_job_success_status_logs_and_manifest(
    slurm_env: SlurmAcceptanceEnv,
) -> None:
    case = _new_case(slurm_env, "single")
    config_path = case / "single.yaml"
    _write_config(config_path, mode="single")
    run_uri = path_to_run_uri(case / "runs" / "single")

    payload = _main_json(
        [
            "run",
            str(config_path),
            "--executor",
            "slurm-single-job",
            "--run-uri",
            run_uri,
            "--format",
            "json",
        ],
        expected_code=0,
    )
    status_payload = _wait_for_run_status(
        run_uri,
        expected={"SUCCEEDED"},
        timeout_seconds=slurm_env.timeout_seconds,
        poll_seconds=slurm_env.poll_seconds,
    )
    jobs_payload = _main_json(["status", run_uri, "--jobs", "--format", "json"])
    manifest = _read_manifest(payload)

    assert payload["result"]["mode"] == "slurm-single-job"
    assert status_payload["result"]["status"] == "SUCCEEDED"
    assert manifest["submitted_jobs"][0]["scheduler_job_id"].isdecimal()
    assert jobs_payload["result"]["jobs"][0]["scheduler_job_id"].isdecimal()
    assert _log_paths_exist(manifest)


def test_real_slurm_afterok_success_dependencies_and_artifacts(
    slurm_env: SlurmAcceptanceEnv,
) -> None:
    case = _new_case(slurm_env, "afterok")
    config_path = case / "afterok.yaml"
    _write_config(config_path, mode="afterok")
    run_uri = path_to_run_uri(case / "runs" / "afterok")

    payload = _main_json(
        [
            "run",
            str(config_path),
            "--executor",
            "slurm-afterok",
            "--run-uri",
            run_uri,
            "--format",
            "json",
        ],
        expected_code=0,
    )
    status_payload = _wait_for_run_status(
        run_uri,
        expected={"SUCCEEDED"},
        timeout_seconds=slurm_env.timeout_seconds,
        poll_seconds=slurm_env.poll_seconds,
    )
    manifest = _read_manifest(payload)

    assert payload["result"]["mode"] == "slurm-afterok"
    assert status_payload["result"]["status"] == "SUCCEEDED"
    assert len(manifest["submitted_jobs"]) == 2
    assert manifest["submitted_jobs"][1]["dependency_job_ids"] == [
        manifest["submitted_jobs"][0]["scheduler_job_id"]
    ]
    assert _log_paths_exist(manifest)


def test_real_slurm_cancel_sleeping_job_records_cancellation(
    slurm_env: SlurmAcceptanceEnv,
) -> None:
    case = _new_case(slurm_env, "cancel")
    config_path = case / "cancel.yaml"
    _write_config(config_path, mode="sleep")
    run_uri = path_to_run_uri(case / "runs" / "cancel")

    payload = _main_json(
        [
            "run",
            str(config_path),
            "--executor",
            "slurm-single-job",
            "--run-uri",
            run_uri,
            "--format",
            "json",
        ],
        expected_code=0,
    )
    try:
        _wait_for_jobs_visible(
            run_uri,
            timeout_seconds=slurm_env.timeout_seconds,
            poll_seconds=slurm_env.poll_seconds,
        )
        cancel_payload = _main_json(
            ["cancel", run_uri, "--jobs", "--format", "json"],
            expected_code=0,
        )
    finally:
        _main_json(["cancel", run_uri, "--jobs", "--format", "json"], expected_code=None)

    manifest = _read_manifest(payload)
    assert cancel_payload["result"]["status"] in {"CANCELLED", "COMPLETED"}
    assert manifest["cancellation_attempts"]


def _new_case(env: SlurmAcceptanceEnv, name: str) -> Path:
    path = env.root / f"loom-slurm-{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _main_json(
    argv: list[str],
    *,
    expected_code: int | None = 0,
) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(argv, stdout=stdout, stderr=stderr)
    if expected_code is not None:
        assert code == expected_code, stderr.getvalue()
        assert stderr.getvalue() == ""
    if not stdout.getvalue():
        return {}
    return json.loads(stdout.getvalue())


def _wait_for_run_status(
    run_uri: str,
    *,
    expected: set[str],
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_payload = _main_json(["status", run_uri, "--format", "json"])
        result = _mapping(last_payload["result"])
        if str(result.get("status")) in expected:
            return last_payload
        time.sleep(poll_seconds)
    pytest.fail(f"run did not reach {sorted(expected)} before timeout: {last_payload}")


def _wait_for_jobs_visible(
    run_uri: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_payload = _main_json(["status", run_uri, "--jobs", "--format", "json"])
        result = _mapping(last_payload["result"])
        jobs = result.get("jobs")
        if isinstance(jobs, list) and jobs:
            return last_payload
        time.sleep(poll_seconds)
    pytest.fail(f"submitted jobs were not visible before timeout: {last_payload}")


def _read_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    result = _mapping(payload["result"])
    return _mapping(json.loads(Path(str(result["manifest_path"])).read_text()))


def _log_paths_exist(manifest: dict[str, Any]) -> bool:
    submitted_jobs = manifest.get("submitted_jobs")
    if not isinstance(submitted_jobs, list):
        return False
    run_path = Path(str(_mapping(manifest)["run_uri"]).removeprefix("file://"))
    for raw_job in submitted_jobs:
        job = _mapping(raw_job)
        for key in ("stdout_relative_path", "stderr_relative_path"):
            relative = job.get(key)
            if not isinstance(relative, str) or not (run_path / relative).exists():
                return False
    return True


def _mapping(value: object) -> dict[str, Any]:
    assert isinstance(value, dict)
    return value


def _write_config(path: Path, *, mode: str) -> None:
    runtime_yaml = _runtime_yaml()
    if mode == "afterok":
        stages = _afterok_stages_yaml()
    elif mode == "sleep":
        stages = _sleep_stages_yaml()
    else:
        stages = _single_stage_yaml()
    path.write_text(f"{runtime_yaml}pipeline:\n  name: {path.stem}\n{stages}", encoding="utf-8")


def _runtime_yaml() -> str:
    fields = {
        "partition": os.environ.get("LOOM_SLURM_ACCEPTANCE_PARTITION"),
        "account": os.environ.get("LOOM_SLURM_ACCEPTANCE_ACCOUNT"),
        "qos": os.environ.get("LOOM_SLURM_ACCEPTANCE_QOS"),
        "time": os.environ.get("LOOM_SLURM_ACCEPTANCE_TIME", "00:05:00"),
    }
    present = {key: value for key, value in fields.items() if value}
    if not present:
        return ""
    lines = ["runtime:", "  adapter_options:", "    slurm:"]
    lines.extend(f"      {key}: {value}" for key, value in present.items())
    return "\n".join(lines) + "\n"


def _single_stage_yaml() -> str:
    return (
        "  stages:\n"
        "    - name: produce\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
    )


def _afterok_stages_yaml() -> str:
    return (
        "  stages:\n"
        "    - name: extract\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.JsonProducerStage\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
        "    - name: report\n"
        "      depends_on: [extract]\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.TextConsumerStage\n"
        "      inputs:\n"
        "        data: extract.data\n"
        "      outputs:\n"
        "        text:\n"
        "          artifact_type: text\n"
        "          codec_key: text.v1\n"
    )


def _sleep_stages_yaml() -> str:
    return (
        "  stages:\n"
        "    - name: sleep\n"
        "      factory:\n"
        "        _target_: tests.support.pipeline_execution_stages.SleepStage\n"
        "      config:\n"
        "        seconds: 120\n"
        "      outputs:\n"
        "        data:\n"
        "          artifact_type: json\n"
        "          codec_key: json.v1\n"
    )

"""Run-time log path helpers for execution failures and stream capture."""

from __future__ import annotations

from pathlib import Path


TRACEBACK_LOG_NAME = "traceback.txt"


def traceback_log_path(*, run_store, run_id: str, stage_name: str) -> Path:
    """Return the traceback log path for a stage."""

    return run_store.local_stage_dir(run_id, stage_name) / "logs" / TRACEBACK_LOG_NAME


def write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


__all__ = ["TRACEBACK_LOG_NAME", "traceback_log_path", "write_text_file"]

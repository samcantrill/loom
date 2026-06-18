"""Git provenance capture helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import ProvenanceCaptureError
from .models import GitProvenance


def capture_git_provenance(path: str, *, include_remote: bool = False, strict: bool = False) -> GitProvenance:
    """Capture lightweight git metadata for a local repository root."""

    repo = Path(path)
    try:
        repository_root = _run_git(["git", "-C", str(repo), "rev-parse", "--show-toplevel"], strict=True).strip() or None
        commit = _run_git(["git", "-C", str(repo), "rev-parse", "HEAD"], strict=True).strip() or None
        branch = _run_git(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"], strict=True).strip() or None
        status = _run_git(["git", "-C", str(repo), "status", "--porcelain"], strict=strict)
    except ProvenanceCaptureError:
        if strict:
            raise
        return GitProvenance(capture_error="git unavailable")

    lines = [line for line in status.splitlines() if line.strip()]
    tracked = [line for line in lines if not line.startswith("??")]
    untracked = [line for line in lines if line.startswith("??")]

    remote_url: str | None = None
    if include_remote:
        try:
            remote_url = _run_git(
                ["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
                strict=True,
            ).strip() or None
        except ProvenanceCaptureError:
            remote_url = None

    if remote_url is not None:
        remote_url = _redact_remote_url(remote_url)

    return GitProvenance(
        repository_root=repository_root,
        commit=commit,
        branch=branch,
        is_dirty=bool(tracked),
        has_untracked=bool(untracked),
        remote_url=remote_url,
    )


def _run_git(command: list[str], *, strict: bool) -> str:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except FileNotFoundError as exc:
        if strict:
            raise ProvenanceCaptureError("git binary is unavailable") from exc
        raise ProvenanceCaptureError("git binary is unavailable")
    except subprocess.TimeoutExpired as exc:
        if strict:
            raise ProvenanceCaptureError("git command timed out") from exc
        raise ProvenanceCaptureError("git command timed out")

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "git command failed").strip()
        if strict:
            raise ProvenanceCaptureError(message)
        raise ProvenanceCaptureError(message)
    return result.stdout.strip()


def _redact_remote_url(url: str) -> str:
    if "@" in url and "://" in url:
        prefix, rest = url.split("://", 1)
        if "@" in rest:
            _, suffix = rest.split("@", 1)
            return f"{prefix}://redacted:{'x'*4}@{suffix}"
    return url

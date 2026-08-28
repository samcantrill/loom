"""Installed command for a Discord coordinator reporting sidecar."""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from loom.queue import LocalDaemonSocketClient, LocalDaemonStatus

from .coordinator import DiscordCoordinatorReporter
from .sink import DEFAULT_TIMEOUT_SECONDS, DiscordWebhookError, WEBHOOK_URL_ENVIRONMENT_VARIABLE


DEFAULT_POLL_INTERVAL_SECONDS = 60.0
DEFAULT_HEARTBEAT_SECONDS = 900.0


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[str | Path], LocalDaemonSocketClient] = LocalDaemonSocketClient,
    reporter_factory: Callable[[str, float], DiscordCoordinatorReporter] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one report or keep polling without exposing transport details."""

    parser = _parser()
    namespace = parser.parse_args(argv)
    webhook_url = os.environ.get(WEBHOOK_URL_ENVIRONMENT_VARIABLE)
    if not webhook_url:
        print(f"{WEBHOOK_URL_ENVIRONMENT_VARIABLE} must be set", file=stderr)
        return 2
    build_reporter = reporter_factory or (
        lambda url, timeout: DiscordCoordinatorReporter(url, timeout_seconds=timeout)
    )
    try:
        reporter = build_reporter(webhook_url, namespace.timeout_seconds)
        client = client_factory(namespace.endpoint)
    except (TypeError, ValueError):
        print("Discord coordinator reporter configuration is invalid", file=stderr)
        return 2
    if namespace.once:
        return _report_once(client, reporter, force=True, stderr=stderr)

    last_heartbeat = monotonic()
    while True:
        force = monotonic() - last_heartbeat >= namespace.heartbeat_seconds
        _report_once(client, reporter, force=force, stderr=stderr)
        if force:
            last_heartbeat = monotonic()
        try:
            sleep(namespace.interval_seconds)
        except KeyboardInterrupt:
            return 0


def _report_once(
    client: LocalDaemonSocketClient,
    reporter: DiscordCoordinatorReporter,
    *,
    force: bool,
    stderr: TextIO,
) -> int:
    try:
        status: LocalDaemonStatus = client.status()
    except Exception:
        print("Discord coordinator status read failed", file=stderr)
        return 1
    try:
        reporter.report(status, force=force)
    except DiscordWebhookError as exc:
        print(f"Discord coordinator report delivery failed: {exc}", file=stderr)
        return 1
    except Exception:
        print("Discord coordinator report delivery failed", file=stderr)
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loom-discord-coordinator",
        description="Report local Loom coordinator status to Discord.",
    )
    parser.add_argument("--endpoint", required=True, help="local daemon socket path")
    parser.add_argument("--once", action="store_true", help="send one status report")
    parser.add_argument(
        "--interval",
        dest="interval_seconds",
        type=_positive_finite,
        default=DEFAULT_POLL_INTERVAL_SECONDS,
        help="positive polling interval in seconds",
    )
    parser.add_argument(
        "--heartbeat",
        dest="heartbeat_seconds",
        type=_positive_finite,
        default=DEFAULT_HEARTBEAT_SECONDS,
        help="positive forced-report interval in seconds",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout_seconds",
        type=_positive_finite,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="positive webhook timeout in seconds",
    )
    return parser


def _positive_finite(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive finite number") from exc
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return result

"""Command-line entry point for ``python -m tools.loom_monitor``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from .app import LoomMonitorApp
from .collector import MonitorCollector
from .demo import DEMO_SCENARIOS, DemoSession, create_demo_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.loom_monitor",
        description=(
            "Open a read-only, evidence-aware TUI for one Loom queue configuration."
        ),
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="trusted Loom queue YAML config (omit with --demo)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="open an isolated deterministic playground instead of a real queue",
    )
    parser.add_argument(
        "--demo-scenario",
        choices=DEMO_SCENARIOS,
        help="demo evidence mix (default: mixed)",
    )
    parser.add_argument(
        "--demo-speed",
        type=_positive_float,
        metavar="MULTIPLIER",
        help="demo lifecycle speed multiplier (default: 1)",
    )
    parser.add_argument(
        "--demo-seed",
        type=int,
        metavar="INTEGER",
        help="deterministic demo identity seed (default: 42)",
    )
    parser.add_argument(
        "--demo-output",
        type=Path,
        metavar="DIRECTORY",
        help="preserve the generated demo in a new subdirectory",
    )
    parser.add_argument(
        "--queue-interval",
        type=_positive_float,
        default=1.0,
        metavar="SECONDS",
        help="durable queue refresh cadence (default: 1)",
    )
    parser.add_argument(
        "--run-interval",
        type=_positive_float,
        default=1.0,
        metavar="SECONDS",
        help="visible/selected run refresh cadence (default: 1)",
    )
    parser.add_argument(
        "--authority-interval",
        type=_positive_float,
        default=1.0,
        metavar="SECONDS",
        help="authority readiness cadence (default: 1)",
    )
    parser.add_argument(
        "--scheduler-interval",
        type=_positive_float,
        default=1.0,
        metavar="SECONDS",
        help="selected delegated jobs cadence (default: 1)",
    )
    parser.add_argument(
        "--log-interval",
        type=_positive_float,
        default=1.0,
        metavar="SECONDS",
        help="selected stage log cadence (default: 1)",
    )
    parser.add_argument(
        "--tail",
        type=_positive_int,
        default=100,
        metavar="LINES",
        help="bounded lines retained per selected log stream (default: 100)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    if options.demo and options.config is not None:
        parser.error("provide either CONFIG or --demo, but not both")
    if not options.demo and options.config is None:
        parser.error("provide either CONFIG or --demo")
    if not options.demo and any(
        value is not None
        for value in (
            options.demo_scenario,
            options.demo_speed,
            options.demo_seed,
            options.demo_output,
        )
    ):
        parser.error("--demo-* options require --demo")
    demo_session: DemoSession | None = None
    try:
        if options.demo:
            demo_session = create_demo_session(
                scenario=options.demo_scenario or "mixed",
                speed=options.demo_speed or 1.0,
                seed=options.demo_seed if options.demo_seed is not None else 42,
                output_root=options.demo_output,
            )
            collector = demo_session.collector
        else:
            assert options.config is not None
            collector = MonitorCollector.from_config(options.config)
    except Exception as exc:
        sys.stderr.write(f"loom monitor: {exc}\n")
        return 2
    app = LoomMonitorApp(
        collector,
        queue_interval=options.queue_interval,
        run_interval=options.run_interval,
        authority_interval=options.authority_interval,
        scheduler_interval=options.scheduler_interval,
        log_interval=options.log_interval,
        log_tail=options.tail,
    )
    if demo_session is not None:
        app.current_view = demo_session.initial_view
        app.pool_filter = demo_session.initial_pool_filter
    try:
        app.run()
    finally:
        if demo_session is not None:
            if demo_session.preserved:
                sys.stderr.write(
                    f"loom monitor: demo preserved at {demo_session.workspace_path}\n"
                )
            demo_session.close()
    return 0


def _positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def _positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

"""Import-light parser for optional Fleet administration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def register_subparser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "fleet", help="inspect and prepare a generic native fleet"
    )
    commands = parser.add_subparsers(dest="fleet_command", required=True)
    init = commands.add_parser("init", help="create protected local placeholders")
    init.add_argument("name")
    init.add_argument(
        "--service-manager", choices=("systemd-user", "tmux"), default="systemd-user"
    )
    init.add_argument("--capture-root", type=Path, action="append", default=[])
    for name in ("status", "plan", "preflight", "export-deployment"):
        command = commands.add_parser(name)
        command.add_argument(
            "--fleet", required=True, help="Fleet name or inventory path"
        )
        command.add_argument(
            "--hosts", help="comma-separated inventory keys; coordinator is reserved"
        )
        command.add_argument(
            "--env-file", type=Path, help="explicit native role environment"
        )
        if name != "export-deployment":
            command.add_argument("--profile", help="required native workload profile ID")
        if name == "export-deployment":
            command.add_argument(
                "--deployment",
                type=Path,
                required=True,
                help="existing native selection with connection/source/profile bindings",
            )
            command.add_argument(
                "--output",
                type=Path,
                required=True,
                help="new versioned destination; never overwrites",
            )
            command.add_argument(
                "--capture-root", type=Path, action="append", default=[]
            )
        else:
            command.add_argument(
                "--connection", type=Path, help="protected native operator connection"
            )
            command.add_argument(
                "--explain",
                action="store_true",
                help="render observation boundaries (also included by default)",
            )
            if name == "preflight":
                command.add_argument(
                    "--previous-release",
                    type=Path,
                    help="retained descriptor for detecting same-label conflicts",
                )
        command.set_defaults(handler=handle)
        command.add_argument(
            "--format", dest="output_format", choices=("text", "json"), default="text"
        )
    init.add_argument(
        "--format", dest="output_format", choices=("text", "json"), default="text"
    )
    init.set_defaults(handler=handle)


def handle(namespace: argparse.Namespace) -> int:
    try:
        import yaml  # noqa: F401
        import packaging  # noqa: F401
        import dotenv  # noqa: F401
    except ModuleNotFoundError as exc:
        raise RuntimeError("Fleet administration requires loom[fleet]") from exc
    from loom.fleet.configuration import fleet_path, init_fleet, load_inventory
    from loom.fleet.administration import observe

    command = namespace.fleet_command
    if command == "init":
        result = init_fleet(
            namespace.name,
            service_manager=namespace.service_manager,
            capture_roots=namespace.capture_root,
        )
    else:
        candidate = Path(namespace.fleet)
        path = (
            candidate
            if candidate.is_absolute()
            or len(candidate.parts) > 1
            or candidate.suffix in {".yaml", ".yml", ".json"}
            else fleet_path(namespace.fleet)
        )
        inventory = load_inventory(path)
        hosts = None if namespace.hosts is None else namespace.hosts.split(",")
        if command == "export-deployment":
            from loom.deployment import export_connection_deployment, load_deployment
            from loom.fleet.configuration import exclude_captures
            from loom.queue.errors import QueueConfigError

            selection = load_deployment(namespace.deployment)
            report = observe(
                inventory,
                command="status",
                hosts=hosts,
                env_file=namespace.env_file,
                profile=selection.preparation_profile,
            )
            if report["outcome"] == "failed":
                raise QueueConfigError(
                    "export profile is unsupported by selected native declarations"
                )
            exclude_captures(namespace.output.parent, namespace.capture_root)
            written = export_connection_deployment(selection, namespace.output)
            result = {
                "schema_version": 1,
                "outcome": "exported",
                "path": str(written),
                "profile": selection.preparation_profile,
            }
        else:
            result = observe(
                inventory,
                command=command,
                hosts=hosts,
                connection=namespace.connection,
                env_file=namespace.env_file,
                previous_release=getattr(namespace, "previous_release", None),
                profile=namespace.profile,
            )
    if namespace.output_format == "json":
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            f"Fleet {result.get('fleet', getattr(namespace, 'name', 'selection'))}: {result['outcome']}"
        )
        if "path" in result:
            print(result["path"])
        if "coordinator" in result:
            print("coordinator observation: " + json.dumps(result["coordinator"], sort_keys=True))
        for name, facts in result.get("hosts", {}).items():
            print(f"{name}: not qualified")
            for kind, fact in facts.items():
                if isinstance(fact, dict):
                    print(
                        f"  {kind}: {fact.get('availability', 'unknown')} ({fact.get('reason') or fact.get('freshness', 'unknown')}); owner={fact.get('owner')}, revision={fact.get('revision')}, observed_at={fact.get('observed_at')}"
                    )
                    if "availability" not in fact:
                        print("    " + json.dumps(fact, sort_keys=True))
                    if fact.get("value"):
                        print("    " + json.dumps(fact["value"], sort_keys=True))
        if "release" in result:
            print("release: " + json.dumps(result["release"], sort_keys=True))
        if "preview" in result:
            print("preview: " + json.dumps(result["preview"], sort_keys=True))
        print(result.get("next", ""))
    if command == "preflight":
        return 2 if result["outcome"] == "failed" else 3
    return 0

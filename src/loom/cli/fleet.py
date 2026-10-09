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
    build = commands.add_parser("build-release", help="build and offline-verify a locked service bundle")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--release-id")
    build.add_argument("--format", dest="output_format", choices=("text", "json"), default="text")
    build.set_defaults(handler=handle)
    adoption = commands.add_parser("adopt", help="adopt quiesced retained tmux installations")
    adoption.add_argument("--fleet", required=True)
    adoption.add_argument("--bindings", type=Path, required=True)
    adoption.add_argument("--operation-id")
    adoption.add_argument("--env-file", type=Path)
    adoption.add_argument("--operator-exclusion", action="store_true", help="acknowledge maintained submission and administration exclusion")
    adoption_mode = adoption.add_mutually_exclusive_group()
    adoption_mode.add_argument("--plan", action="store_true")
    adoption_mode.add_argument("--apply", action="store_true")
    adoption.add_argument("--format", dest="output_format", choices=("text", "json"), default="text")
    adoption.set_defaults(handler=handle)
    check = commands.add_parser(
        "self-test", help="run deliberate native infrastructure checks"
    )
    check.add_argument("--fleet", required=True)
    check.add_argument("--deployment", type=Path)
    check.add_argument("--connection", type=Path, help="protected operator connection")
    check.add_argument("--config", default="fleet-check.yaml")
    check.add_argument("--agent", dest="agent_id")
    check.add_argument("--checks", default="cpu,storage")
    check.add_argument(
        "--operation-id", help="continue an existing check without a new identity"
    )
    check.add_argument(
        "--retry-of", help="explicit new attempt linked to a failed check"
    )
    check.add_argument("--timeout", type=float, default=120)
    check.add_argument("--env-file", type=Path)
    check.add_argument(
        "--format", dest="output_format", choices=("text", "json"), default="text"
    )
    check.set_defaults(handler=handle)
    apply_command = commands.add_parser(
        "apply", help="apply selected native setup over configured SSH"
    )
    apply_command.add_argument("--fleet", required=True)
    apply_command.add_argument("--operation-id", required=True)
    apply_command.add_argument("--hosts")
    apply_command.add_argument(
        "--issuer", type=Path, help="original coordinator-host-local CA directory"
    )
    apply_command.add_argument("--deployment", type=Path, required=True)
    apply_command.add_argument("--config", default="fleet-check.yaml")
    apply_command.add_argument(
        "--connection", type=Path, help="existing pinned operator connection"
    )
    apply_command.add_argument("--client-credential-id")
    apply_command.add_argument("--operator-credential-id")
    apply_command.add_argument("--env-file", type=Path)
    apply_command.add_argument(
        "--format", dest="output_format", choices=("text", "json"), default="text"
    )
    apply_command.set_defaults(handler=handle)
    migration = commands.add_parser("migrate-services", help="migrate stopped, settled tmux roles to systemd-user")
    migration.add_argument("--fleet", required=True)
    migration.add_argument("--operation-id", required=True)
    migration.add_argument("--hosts")
    migration.add_argument("--env-file", type=Path)
    migration.add_argument("--format", dest="output_format", choices=("text", "json"), default="text")
    migration.set_defaults(handler=handle)
    upgrade = commands.add_parser("upgrade", help="preview or apply service or selected workload maintenance")
    upgrade.add_argument("--fleet", required=True)
    target = upgrade.add_mutually_exclusive_group(required=True)
    target.add_argument("--runtime-release", type=Path)
    target.add_argument("--workload-profile")
    upgrade.add_argument("--image", type=Path)
    upgrade.add_argument(
        "--workload-inventory", type=Path,
        help="protected candidate inventory selecting retained source/profile paths",
    )
    mode = upgrade.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    upgrade.add_argument("--operation-id")
    upgrade.add_argument("--deployment", type=Path)
    upgrade.add_argument("--connection", type=Path)
    upgrade.add_argument("--config", default="fleet-check.yaml")
    upgrade.add_argument("--env-file", type=Path)
    upgrade.add_argument("--timeout", type=float, default=120)
    upgrade.add_argument("--format", dest="output_format", choices=("text", "json"), default="text")
    upgrade.set_defaults(handler=handle)
    operation = commands.add_parser(
        "operation", help="inspect or continue retained setup"
    )
    operations = operation.add_subparsers(dest="operation_command", required=True)
    for action in ("status", "resume", "abort", "retry-check", "retry-control"):
        item = operations.add_parser(action)
        item.add_argument("operation_id")
        item.add_argument("--fleet", required=True)
        if action == "retry-check":
            item.add_argument("--failed-check", required=True)
            item.add_argument("--operation-id", dest="new_check", required=True)
        if action == "retry-control":
            item.add_argument("--failed-control", required=True)
            item.add_argument("--operation-id", dest="new_control", required=True)
        item.add_argument(
            "--format", dest="output_format", choices=("text", "json"), default="text"
        )
        item.set_defaults(handler=handle)
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
        if name == "plan":
            command.add_argument(
                "--issuer", type=Path, help="coordinator-host-local CA directory"
            )
        if name != "export-deployment":
            command.add_argument(
                "--profile", help="required native workload profile ID"
            )
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
    if command == "build-release":
        from loom.fleet.release_build import build_release

        result = build_release(namespace.source, namespace.output, release_id=namespace.release_id)
        if namespace.output_format == "json":
            print(json.dumps(result, sort_keys=True))
        else:
            print("service release: " + str(result["release"]))
            print("offline installation: passed")
            print("build receipt: " + str(result["receipt"]))
        return 0
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
        hosts = (
            None
            if getattr(namespace, "hosts", None) is None
            else namespace.hosts.split(",")
        )
        if command == "adopt":
            from loom.fleet.adoption import adopt
            result = adopt(inventory, bindings=namespace.bindings, operation_id=namespace.operation_id if namespace.apply else None, env_file=namespace.env_file, apply=namespace.apply, operator_exclusion=namespace.operator_exclusion)
        elif command == "upgrade":
            from loom.fleet.upgrades import upgrade
            if not namespace.apply:
                from loom.fleet.upgrades import preview
                result = preview(inventory, runtime_release=namespace.runtime_release, workload_profile=namespace.workload_profile, image=namespace.image, workload_inventory=namespace.workload_inventory, deployment=namespace.deployment, connection=namespace.connection, config=namespace.config, env_file=namespace.env_file)
            else:
                result = upgrade(inventory, operation_id=namespace.operation_id, runtime_release=namespace.runtime_release, workload_profile=namespace.workload_profile, image=namespace.image, workload_inventory=namespace.workload_inventory, deployment=namespace.deployment, connection=namespace.connection, config=namespace.config, env_file=namespace.env_file, timeout_seconds=namespace.timeout, apply=True)
        elif command == "migrate-services":
            from loom.fleet.ssh_operations import migrate_services
            result = migrate_services(inventory, operation_id=namespace.operation_id,
                                      hosts=hosts, env_file=namespace.env_file)
        elif command in {"apply", "operation"}:
            from loom.fleet.ssh_operations import apply, operation_status

            if command == "operation":
                from loom.fleet._host import read
                from loom.fleet.ssh_operations import _directory
                intent = read(_directory(inventory, namespace.operation_id) / "intent.json")
                if namespace.operation_command == "status":
                    result = operation_status(inventory, namespace.operation_id)
                elif intent.get("kind") == "installation-adoption":
                    if namespace.operation_command not in {"resume", "abort"}:
                        raise ValueError("retry requires a maintenance upgrade")
                    from loom.fleet.adoption import adopt
                    result = adopt(inventory, operation_id=namespace.operation_id, action=namespace.operation_command)
                elif intent.get("kind") in {"runtime-upgrade", "workload-upgrade"}:
                    from loom.fleet.upgrades import upgrade
                    result = upgrade(inventory, operation_id=namespace.operation_id, action=namespace.operation_command, failed_check=getattr(namespace, "failed_check", None), new_check=getattr(namespace, "new_check", None), failed_control=getattr(namespace, "failed_control", None), new_control=getattr(namespace, "new_control", None))
                elif namespace.operation_command == "resume":
                    result = apply(inventory, operation_id=namespace.operation_id, resume=True)
                else:
                    raise ValueError("abort/retry requires a maintenance upgrade")
            else:
                result = apply(
                    inventory,
                    operation_id=namespace.operation_id,
                    hosts=hosts,
                    issuer=namespace.issuer,
                    env_file=namespace.env_file,
                    check_selection={
                        "deployment": str(namespace.deployment.resolve()),
                        "config": namespace.config,
                        "operator_connection": None
                        if namespace.connection is None
                        else str(namespace.connection.resolve()),
                        "client_credential_id": namespace.client_credential_id,
                        "operator_credential_id": namespace.operator_credential_id,
                    },
                )
        elif command == "plan":
            from loom.fleet.ssh_operations import plan

            result = plan(
                inventory,
                hosts=hosts,
                issuer=namespace.issuer,
                env_file=namespace.env_file,
            )
        elif command == "self-test":
            from loom.fleet.self_tests import self_test

            result = self_test(
                inventory,
                deployment=namespace.deployment,
                operator_connection=namespace.connection,
                config=namespace.config,
                agent_id=namespace.agent_id,
                checks=namespace.checks.split(","),
                operation_id=namespace.operation_id,
                retry_of=namespace.retry_of,
                timeout_seconds=namespace.timeout,
                env_file=namespace.env_file,
            )
        elif command == "export-deployment":
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
            print(
                "coordinator observation: "
                + json.dumps(result["coordinator"], sort_keys=True)
            )
        for name, facts in result.get("hosts", {}).items():
            print(f"{name}: not qualified")
            if "host" in facts:
                print(
                    f"  alias: {facts['host']}; dependency: {facts.get('dependency', False)}"
                )
            for field in ("actions", "conflict", "unavailable"):
                if field in facts:
                    value = facts[field]
                    print(
                        f"  {field}: "
                        + ("; ".join(value) if isinstance(value, list) else str(value))
                    )
            for kind, fact in facts.items():
                if isinstance(fact, dict):
                    print(
                        f"  {kind}: {fact.get('availability', 'unknown')} ({fact.get('reason') or fact.get('freshness', 'unknown')}); owner={fact.get('owner')}, revision={fact.get('revision')}, observed_at={fact.get('observed_at')}"
                    )
                    if "availability" not in fact:
                        print("    " + json.dumps(fact, sort_keys=True))
                    if fact.get("value"):
                        print("    " + json.dumps(fact["value"], sort_keys=True))
        for name, fact in result.get("checks", {}).items():
            if not isinstance(fact, dict) or "outcome" not in fact:
                continue
            print(
                f"  {name}: {fact['outcome']} ({fact.get('code', '')}); operation={fact.get('operation_id', '')}"
            )
        if "operation_id" in result:
            print(
                ("check operation: " if command == "self-test" else "setup operation: ")
                + result["operation_id"]
            )
        if "reason" in result:
            print("reason: " + result["reason"])
        for reference in ("deployment", "operator_connection"):
            if reference in result:
                print(reference + ": " + result[reference])
        if "identities" in result:
            print(
                "native identities: " + json.dumps(result["identities"], sort_keys=True)
            )
        if "release" in result:
            print("release: " + json.dumps(result["release"], sort_keys=True))
        if "preview" in result:
            print("preview: " + json.dumps(result["preview"], sort_keys=True))
        print(result.get("next", ""))
    if command in {"apply", "operation", "upgrade", "adopt"}:
        return (
            0
            if result["outcome"] in {"complete", "aborted", "preview"}
            else 2
            if result["outcome"] in {"pending", "running", "waiting"}
            else 1
        )
    if command == "self-test":
        return {"passed": 0, "failed": 1, "waiting": 2, "unsupported": 3}[
            result["outcome"]
        ]
    if command == "preflight":
        return 2 if result["outcome"] == "failed" else 3
    return 0

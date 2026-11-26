"""Explicit stopped, same-root upgrades for native service storage.

Snapshots and prepared targets form one protected cohort. Publication never
calls a scheduler, starts an owner, or silently creates missing live storage.
"""

from __future__ import annotations

from contextlib import ExitStack, closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
from typing import cast
from uuid import uuid4

from loom._sqlite_inspection import inspect_sqlite_database
from loom.pipeline.stores.atomic import atomic_write_bytes, _fsync_path_strict
from loom.serialization import PlainData, thaw_plain_data

from .errors import QueueConfigError, QueueServiceError
from ._storage_policy import parse_storage_policy
from ._storage_upgrade_state import (
    GUARD_NAME, owner_key, publish_json, read_private_json, require_storage_upgrade_ready,
)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _private_directory(path: Path) -> None:
    details = path.lstat()
    if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid() or details.st_mode & 0o077:
        raise QueueServiceError(f"storage upgrade directory is not private: {path}")


def _path(value) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute() or ".." in Path(value).parts:
        raise QueueConfigError("storage upgrade paths must be absolute without '..'")
    return Path(value).resolve()


def _request(path: str | Path) -> tuple[dict, str]:
    from .deployment import _load_protected_config

    request = read_private_json(Path(path))
    if set(request) != {"version", "operation_id", "snapshot_root", "roles"} or type(request["version"]) is not int or request["version"] != 1:
        raise QueueConfigError("unsupported storage upgrade request")
    if not isinstance(request["operation_id"], str) or not 1 <= len(request["operation_id"]) <= 512:
        raise QueueConfigError("storage upgrade operation_id is invalid")
    request["snapshot_root"] = str(_path(request["snapshot_root"]))
    if not isinstance(request["roles"], list) or not request["roles"]:
        raise QueueConfigError("storage upgrade requires selected roles")
    inputs, composed = {}, []
    for role in request["roles"]:
        if (not isinstance(role, dict)
                or set(role) - {"source_env_file", "target_env_file"} != {"role", "expected_root_id", "source_config", "target_config"}
                or role["role"] not in {"coordinator", "outbound-agent"}
                or not isinstance(role["expected_root_id"], str) or not role["expected_root_id"]):
            raise QueueConfigError("storage upgrade role is invalid")
        for name in ("source_config", "target_config", "source_env_file", "target_env_file"):
            if role.get(name) is None:
                continue
            selected = _path(role[name])
            info = selected.stat()
            if not selected.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise QueueConfigError("storage upgrade declarations must be private files")
            role[name] = str(selected)
            inputs[str(selected)] = hashlib.sha256(selected.read_bytes()).hexdigest()
        if Path(role["source_config"]).parent != Path(role["target_config"]).parent:
            raise QueueConfigError("storage upgrade declarations must be siblings; declaration relocation is unsupported")
        composed.append({side: _load_protected_config(
            role[side + "_config"], env_file=role.get(side + "_env_file"),
        )[3] for side in ("source", "target")})
    return request, _digest({"request": request, "inputs": inputs, "composed": composed})


def _declarations(request: dict, *, qualify: bool) -> list[dict]:
    from . import deployment as d

    roles = []
    allowed = {"storage", "slurm_profiles", "slurm_admission", "slurm_terminal_recovery", "slurm_submit_interval_seconds", "slurm_observation_policy"}
    for item in request["roles"]:
        selected = {"request": item}
        for side in ("source", "target"):
            path, env = item[side + "_config"], item.get(side + "_env_file")
            if item["role"] == "coordinator":
                d.inspect_role_declaration(path, role="coordinator", env_file=env)
                source, _, payload = d._read_coordinator_declaration(path, env_file=env)
                if payload["local_agent"] is not None:
                    raise QueueConfigError("storage upgrade of a coordinator bundle is unsupported; no state changed")
                root = d._path(payload, "deployment_root", source.parent)
                # HTTPS construction qualifies remote readiness. Inspection and
                # interrupted recovery need only its inert retained declaration.
                authority = None
                authority_declaration = d._mapping(payload, "authority")
                if authority_declaration["kind"] == "embedded":
                    authority = d._coordinator_authority_factory(
                        authority_declaration, source.parent, deployment_root=root,
                        storage=parse_storage_policy(payload.get("storage")),
                    )
                projection = d._coordinator_immutable_projection(payload)
                if "state_root" in authority_declaration:
                    from loom.pipeline.stores.coordinator_authority import coordinator_authority_identity
                    projection["authority"] = coordinator_authority_identity(authority)
                immutable = d._canonical_fingerprint({"coordinator": projection, "local_agent": None})
                selected[side] = {
                    "payload": payload, "root": root / "coordinator", "deployment_root": root,
                    "immutable": immutable,
                    "active": d.read_coordinator_scheduling_fingerprint(path, env_file=env),
                    "authority": authority,
                }
            else:
                spec = d.read_agent_spec(path, env_file=env)
                payload = cast(dict[str, PlainData], thaw_plain_data(spec.declarations))
                selected[side] = {
                    "payload": payload, "root": spec.agent_root, "spec": spec,
                }
            selected[side]["storage"] = parse_storage_policy(payload.get("storage"))
            if selected[side]["storage"] is not None:
                selected[side]["storage"].require_owner()
        before, after = selected["source"], selected["target"]
        comparable_target = json.loads(json.dumps(after["payload"]))
        from .agent_sessions import (
            SLURM_ASYNC_OUTPUT_CAPABILITY,
            SLURM_PENDING_EFFECTS_CAPABILITY,
            SLURM_SUBMISSION_CAPABILITY,
        )
        from ._slurm_start import SLURM_REPLAYABLE_START_CAPABILITY
        from .shared_execution import STAGING_CONTINUATION_CAPABILITY

        def allow_protocol_capabilities(old, new):
            previous = old.get("capabilities", [])
            current = new.get("capabilities", [])
            if SLURM_SUBMISSION_CAPABILITY in previous:
                added = {
                    SLURM_PENDING_EFFECTS_CAPABILITY,
                    SLURM_REPLAYABLE_START_CAPABILITY,
                    SLURM_ASYNC_OUTPUT_CAPABILITY,
                    STAGING_CONTINUATION_CAPABILITY,
                } - set(previous)
                new["capabilities"] = [value for value in current if value not in added]

        if item["role"] == "coordinator":
            old_agents = before["payload"]["agent_policy"]["agents"]
            new_agents = comparable_target["agent_policy"]["agents"]
            for old, new in zip(old_agents, new_agents):
                allow_protocol_capabilities(old, new)
                old_bindings, new_bindings = old.get("external_slurm_profiles", []), new.get("external_slurm_profiles", [])
                if old_bindings != new_bindings:
                    from loom.pipeline.executors.slurm.ready_stage import SlurmReadyStageProfile

                    # A pinned bootstrap update changes its profile fingerprint.
                    # Remap existing grants only to the same declared profile;
                    # never authorize additional profiles or arbitrary digests.
                    old_profiles = {p.profile_id: p.configuration_fingerprint for p in cast(
                        tuple[SlurmReadyStageProfile, ...],
                        d._slurm_profile_composition(before["payload"].get("slurm_profiles")),
                    )}
                    new_profiles = {p.profile_id: p.configuration_fingerprint for p in cast(
                        tuple[SlurmReadyStageProfile, ...],
                        d._slurm_profile_composition(after["payload"].get("slurm_profiles")),
                    )}
                    expected = [[name, new_profiles.get(name)] for name, fingerprint in old_bindings
                                if old_profiles.get(name) == fingerprint and name in new_profiles]
                    if len(expected) == len(old_bindings) and new_bindings == expected:
                        new["external_slurm_profiles"] = old_bindings
        else:
            allow_protocol_capabilities(before["payload"]["registration"], comparable_target["registration"])
        if before["root"] != after["root"] or {
            k: v for k, v in before["payload"].items() if k not in allowed
        } != {k: v for k, v in comparable_target.items() if k not in allowed}:
            raise QueueConfigError("storage upgrade may change storage and Slurm policy only; roots and other declarations must match")
        if before["storage"] is not None and after["storage"] is None:
            raise QueueConfigError("removing explicit storage policy requires a separate migration")
        if qualify:
            load = d.load_coordinator_service_config if item["role"] == "coordinator" else d.load_outbound_agent_service_config
            selected["qualified"] = load(item["target_config"], env_file=item.get("target_env_file"))
        roles.append(selected)
    roots = [str(role["source"]["root"]) for role in roles]
    if len(roots) != len(set(roots)):
        raise QueueConfigError("storage upgrade selects an owner more than once")
    destination = Path(request["snapshot_root"])
    if any(destination.is_relative_to(Path(root)) or Path(root).is_relative_to(destination) for root in roots):
        raise QueueConfigError("storage upgrade snapshots must be outside live owner roots")
    return roles


def _metadata(path: Path, table: str) -> dict:
    with inspect_sqlite_database(path) as conn:
        return dict(conn.execute(f"SELECT key, value FROM {table}"))


def _authority_inventory(source: dict, identity: str) -> list[Path]:
    """Join retained run references to per-run native ownership evidence.

    Neither a missing namespace nor a hash-shaped child proves an empty/owned
    authority. Legacy unannotated stores can still bind through a retained native
    admission receipt. Stores with neither form of evidence are ambiguous.
    """
    from loom.pipeline.stores.authority import CoordinatorAdmissionRequest, CoordinatorAdmissionReceipt
    from loom.pipeline.stores.run_uri import run_uri_to_path
    from loom.pipeline.stores.coordinator_authority import _require_embedded_schema
    from loom.runs.context import RunAnnotations

    def canonical(uri):
        return run_uri_to_path(uri).resolve().as_uri()

    authority, root = source["authority"], source["root"]
    expected, operations, admissions = set(), {}, {}
    references = {
        root / "control.sqlite": (
            ("managed_admissions", "run_uri"), ("queue_items", "run_uri"),
            ("remote_assignments", "run_uri"), ("action_claims", "owner_run_uri"),
            ("action_demands", "run_uri"), ("action_graph_cancellations", "run_uri"),
        ),
        root / "execution.sqlite": (
            ("stage_work", "run_uri"), ("coordinator_assignments", "run_uri"),
            ("slurm_stage_assignments", "run_uri"),
        ),
    }
    for database, tables in references.items():
        with inspect_sqlite_database(database) as conn:
            present = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table, column in tables:
                if table in present:
                    expected.update(canonical(row[0]) for row in conn.execute(f"SELECT DISTINCT {column} FROM {table}"))
    with inspect_sqlite_database(root / "control.sqlite") as conn:
        for row in conn.execute("SELECT run_uri, authority_operation_id, intent_digest, coordinator_id FROM managed_admissions"):
            if row[3] != identity:
                raise QueueServiceError("embedded authority admission belongs to another coordinator")
            admissions[canonical(row[0])] = (row[1], row[2])
        for operation, encoded in conn.execute("SELECT operation_id, result_json FROM preparation_operations"):
            operations[operation] = set()
            result = json.loads(encoded)
            for name in ("prepared_run", "binding"):
                if result.get(name) is not None:
                    uri = canonical(result[name]["run_uri"])
                    expected.add(uri)
                    operations[operation].add(uri)
    bucket = authority.state_root / hashlib.sha256(str(authority.deployment_root).encode()).hexdigest()
    found, databases = set(), []
    if bucket.is_symlink():
        raise QueueServiceError("embedded authority inventory must not traverse a namespace symlink")
    if bucket.exists():
        for child in sorted(bucket.iterdir()):
            if child.is_symlink() or not child.is_dir() or len(child.name) != 64 or any(c not in "0123456789abcdef" for c in child.name):
                raise QueueServiceError("embedded authority inventory contains an unrecognized owner")
            database = child / "authority.sqlite3"
            with inspect_sqlite_database(database) as conn:
                _require_embedded_schema(conn)
                annotations = conn.execute("SELECT run_uri, annotations_json, initialization_json FROM run_annotations").fetchall()
                receipts = conn.execute("SELECT operation_id, request_json, receipt_json FROM coordinator_admission_receipts").fetchall()
            bound = set()
            for run_uri, current, initial in annotations:
                now, original = RunAnnotations.from_dict(json.loads(current)), RunAnnotations.from_dict(json.loads(initial))
                uri = canonical(run_uri)
                if now.run_uri != run_uri or original.run_uri != run_uri:
                    raise QueueServiceError("embedded authority annotation run identity conflicts")
                owner = (original.initializer_coordinator_id, original.initializer_operation_id)
                if owner != (now.initializer_coordinator_id, now.initializer_operation_id):
                    raise QueueServiceError("embedded authority annotation initializer changed")
                if owner != (None, None):
                    if owner[0] != identity or owner[1] not in operations:
                        raise QueueServiceError("embedded authority initializer ownership is unavailable")
                    if operations[owner[1]] and uri not in operations[owner[1]]:
                        raise QueueServiceError("embedded authority initializer run binding conflicts")
                    bound.add(uri)
                elif not receipts:
                    raise QueueServiceError("embedded authority inventory lacks native ownership evidence")
                # A legacy annotation URI must agree with any admission evidence.
                if child.name != hashlib.sha256(uri.encode()).hexdigest():
                    raise QueueServiceError("embedded authority run identity does not match its storage key")
            for operation, encoded, retained in receipts:
                request = CoordinatorAdmissionRequest.from_dict(json.loads(encoded))
                receipt = CoordinatorAdmissionReceipt.from_dict(json.loads(retained))
                uri = canonical(request.run_uri)
                if (request.coordinator_id != identity or request.operation_id != operation
                        or receipt.request != request or admissions.get(uri) != (operation, request.intent_digest)):
                    raise QueueServiceError("embedded authority admission ownership is unavailable")
                bound.add(uri)
            if len(bound) != 1 or child.name != hashlib.sha256(next(iter(bound), "").encode()).hexdigest():
                raise QueueServiceError("embedded authority inventory lacks an unambiguous run identity")
            found.update(bound)
            databases.append(database)
    if expected - found:
        raise QueueServiceError("embedded authority inventory is missing retained run storage")
    return databases


def _source_inventory(role: dict, request: dict) -> dict:
    from .local_daemon import _open_root
    from .retirement import require_unretired
    from .service_upgrade import inspect_service_settlement

    item, source = role["request"], role["source"]
    root = source["root"]
    _private_directory(root)
    guard = root / GUARD_NAME
    prior_guard = read_private_json(guard) if guard.exists() else None
    if prior_guard is not None:
        if prior_guard.get("operation_id") == request["operation_id"]:
            if prior_guard.get("manifest") != str(Path(request["snapshot_root"]) / "manifest.json"):
                raise QueueServiceError("storage upgrade operation is already bound to another snapshot")
        else:
            require_storage_upgrade_ready(root)
    native_role = "coordinator" if item["role"] == "coordinator" else "local-agent"
    identity = _open_root(root, role=native_role, for_storage_upgrade=True)
    if identity != item["expected_root_id"]:
        raise QueueServiceError("storage upgrade owner identity changed")
    require_unretired(root)
    databases = [root / "control.sqlite"]
    files = []
    inventory = None
    if item["role"] == "coordinator":
        binding = source["deployment_root"] / "deployment-binding.json"
        expected = {"schema_version": 3, "role_kind": "coordinator", "coordinator_id": identity,
                    "immutable_fingerprint": source["immutable"]}
        if read_private_json(binding) != expected:
            raise QueueServiceError("storage upgrade source coordinator binding changed")
        values = _metadata(root / "control.sqlite", "daemon_metadata")
        if values.get("scheduling_fingerprint") != source["active"]:
            raise QueueServiceError("storage upgrade source scheduling binding changed")
        from ._maintenance import _KEY
        if json.loads(values[_KEY])["state"] != "closed":
            raise QueueServiceError("storage upgrade requires closed coordinator admission")
        with inspect_sqlite_database(root / "control.sqlite") as conn:
            if conn.execute("SELECT 1 FROM scheduling_reloads WHERE state='applying' LIMIT 1").fetchone():
                raise QueueServiceError("storage upgrade requires scheduling reload settlement")
        databases.append(root / "execution.sqlite")
        files.append(binding)
        from loom.pipeline.stores.coordinator_authority import EmbeddedCoordinatorAuthorityFactory
        authority = source["authority"]
        if isinstance(authority, EmbeddedCoordinatorAuthorityFactory):
            databases.extend(_authority_inventory(source, identity))
        elif source["payload"]["authority"]["kind"] == "embedded":
            raise QueueConfigError("storage upgrade requires an existing explicit authority state_root; run-local relocation is unsupported")
        # The native queue repository shares control.sqlite. Independent workspace
        # coordination stores are not owned by this service and are not migrated.
    else:
        binding = root / "role-binding.json"
        values = _metadata(root / "control.sqlite", "root_metadata")
        accepted = json.loads(values.get("declaration_binding", "null"))
        if (not isinstance(accepted, dict) or accepted.get("version") != 1
                or accepted.get("declaration_digest") != source["spec"].declaration_digest
                or accepted.get("active_fingerprint") != values.get("active_configuration_fingerprint")
                or str(accepted.get("active_configuration_revision")) != values.get("active_configuration_revision")):
            raise QueueServiceError("storage upgrade requires the accepted source agent declaration")
        if read_private_json(binding) != {
            "schema_version": 2, "role_kind": "outbound-agent", "stable_id": identity,
            "immutable_fingerprint": accepted["immutable_fingerprint"],
        }:
            raise QueueServiceError("storage upgrade source agent binding changed")
        if values.get("availability_state") != "drained":
            raise QueueServiceError("storage upgrade requires a drained agent")
        if values.get("profile_promotion_pending"):
            raise QueueServiceError("storage upgrade requires profile promotion settlement")
        inventory = {"version": 1, "supervisor": bool(source["payload"]["resident_profiles"] or source["payload"].get("container_policies")),
                     "slurm": bool(source["payload"].get("slurm_profiles"))}
        if "execution_store_requirements" in values:
            inventory = json.loads(values["execution_store_requirements"])
        if role["target"]["payload"].get("slurm_profiles"):
            if not (root / "slurm.sqlite").is_file():
                raise QueueServiceError("storage upgrade target Slurm profiles require a retained Slurm store")
            inventory = {**inventory, "slurm": True}
        databases.append(root / "journal.sqlite")
        workspaces = root / "assignments"
        if workspaces.exists():
            from ._remote_stage_execution import _require_current_workspace_path, _require_resident_workspace_schema
            with inspect_sqlite_database(root / "journal.sqlite") as conn:
                assignments = dict(conn.execute("SELECT assignment_id, state FROM assignments"))
            for workspace in sorted(workspaces.iterdir()):
                if workspace.is_symlink() or not workspace.is_dir():
                    raise QueueServiceError("resident workspace inventory is invalid")
                _require_current_workspace_path(workspace)
                database = workspace / "resident.sqlite"
                if not database.exists():
                    raise QueueServiceError("resident workspace inventory is missing its database")
                with inspect_sqlite_database(database) as conn:
                    _require_resident_workspace_schema(conn)
                    if conn.execute("SELECT 1 FROM request LIMIT 1").fetchone() and assignments.get(workspace.name) not in {"released", "declined"}:
                        raise QueueServiceError("resident workspace lacks a settled native assignment")
                databases.append(database)
        if inventory["slurm"] or (root / "slurm.sqlite").exists():
            databases.append(root / "slurm.sqlite")
        if inventory["supervisor"] or (root / "supervisor").exists():
            databases.append(root / "supervisor/supervisor.sqlite")
            files.append(root / "supervisor/service-config.json")
        files.append(binding)
    observation = inspect_service_settlement(root, expected_root_id=identity, _verified_agent_inventory=inventory)
    if observation.availability != "available" or not observation.value["settled"]:
        raise QueueServiceError(f"storage upgrade requires settled native work: {observation.to_dict()}")
    for path in databases:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise QueueServiceError("storage upgrade database is not a regular owned file")
        with inspect_sqlite_database(path) as conn:
            _integrity(conn)
    if root / "supervisor/supervisor.sqlite" in databases:
        _verify_supervisor(root, identity)
    return {"root": str(root), "root_id": identity, "role": item["role"],
            "databases": [str(path) for path in databases], "files": [str(path) for path in files],
            "inventory": inventory, "supervisor": (root / "supervisor/supervisor.sqlite") in databases,
            "prior_guard": prior_guard}


def _supervisor_fingerprint(value: dict) -> str:
    from ._agent_process_supervisor import _digest as supervisor_digest
    from loom.fingerprints import hash_mapping
    return supervisor_digest({
        "agent_id": value["agent_id"],
        **({"storage": value["storage"]} if value.get("storage") is not None else {}),
        "profiles": [{"profile_id": p["descriptor"]["profile_id"], "fingerprint": supervisor_digest(p)} for p in value["profiles"]],
        **({"container_policies": [{"policy_id": p["policy_id"], "fingerprint": hash_mapping(p).split(":", 1)[1]}
                                   for p in value["container_policies"]]} if value.get("container_policies") else {}),
    })


def _verify_supervisor(root: Path, identity: str) -> None:
    from ._agent_process_supervisor import AgentProcessSupervisor, _host_boot_evidence
    value = read_private_json(root / "supervisor/service-config.json")
    metadata = _metadata(root / "supervisor/supervisor.sqlite", "metadata")
    if (value["agent_id"] != identity or value["configuration_fingerprint"] != _supervisor_fingerprint(value)
            or metadata["configuration_fingerprint"] != value["configuration_fingerprint"]
            or metadata["agent_id"] != identity or metadata["schema_version"] != str(AgentProcessSupervisor._SCHEMA_VERSION)
            or metadata["execution_root"] != str(root / "supervisor")
            or json.loads(metadata["boot_evidence"])["host"] != _host_boot_evidence()["host"]):
        raise QueueServiceError("storage upgrade supervisor binding changed")
    with inspect_sqlite_database(root / "supervisor/supervisor.sqlite") as conn:
        if conn.execute("SELECT 1 FROM launches LIMIT 1").fetchone() and (
            not metadata.get("continuity_epoch") or metadata.get("clean_shutdown_epoch") != metadata["continuity_epoch"]
        ):
            raise QueueServiceError("storage upgrade supervisor lacks a clean stopped boundary")


def _integrity(conn) -> None:
    if tuple(row[0] for row in conn.execute("PRAGMA integrity_check")) != ("ok",) or conn.execute("PRAGMA foreign_key_check").fetchone():
        raise QueueServiceError("storage upgrade database integrity failed")


def _contents(conn) -> str:
    digest = hashlib.sha256(str(conn.execute("PRAGMA user_version").fetchone()[0]).encode())
    for statement in conn.iterdump():
        digest.update(statement.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _db_facts(path: Path) -> tuple[str, str]:
    with inspect_sqlite_database(path) as conn:
        return _contents(conn), conn.execute("PRAGMA journal_mode").fetchone()[0].lower()


def _copy_database(source: Path, target: Path, *, mode: str) -> None:
    with inspect_sqlite_database(source) as src, closing(sqlite3.connect(target, isolation_level=None)) as dst:
        dst.execute("PRAGMA synchronous=EXTRA")
        src.backup(dst)
        if dst.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal":
            busy, _, _ = dst.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if busy:
                raise QueueServiceError("storage upgrade WAL checkpoint is busy")
        if mode not in {"delete", "wal"} or dst.execute("PRAGMA journal_mode=" + mode).fetchone()[0].lower() != mode:
            raise QueueServiceError("storage upgrade journal conversion failed")
        _integrity(dst)
    target.chmod(0o600)
    _sync_database(target)


def _sync_database(target: Path) -> None:
    with target.open("rb") as stream:
        os.fsync(stream.fileno())
    _fsync_path_strict(target.parent)


def _target_file(role: dict, path: Path) -> bytes:
    value = read_private_json(path)
    target = role["qualified"]
    if path.name in {"deployment-binding.json", "role-binding.json"}:
        value["immutable_fingerprint"] = target.immutable_fingerprint
    else:
        storage = role["target"]["storage"]
        if storage is not None:
            value["storage"] = storage.to_dict()
        value["configuration_fingerprint"] = _supervisor_fingerprint(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _upgrade_admission_creators(conn: sqlite3.Connection) -> None:
    """Upgrade a verified v19 coordinator in its caller's write transaction."""
    from ._preparation_operations import PREPARATION_RUN_PREFIX
    from .local_daemon import _validate_coordinator_schema

    conn.execute("ALTER TABLE managed_admissions ADD COLUMN admitted_by TEXT")
    # Only a claimed preparation operation could submit these reserved names.
    # A reconciler rotates child_name on each new verification generation.
    # Different operation IDs can generate the same historical name (':' is
    # valid in an ID), so retain a principal only when all creators agree.
    principals: dict[str, set[str]] = {}
    rows = conn.execute(
        "SELECT operation_id, principal_id, child_name, dispatch_claimed, "
        "COALESCE(json_extract(selected_json, '$.reconciliation.verification_generation'), 0) "
        "FROM preparation_operations"
    )
    for operation_id, principal, current_child, dispatched, generation in rows:
        for previous in range(generation):
            identity = operation_id if previous == 0 else f"{operation_id}:verify:{previous}"
            child = PREPARATION_RUN_PREFIX + hashlib.sha256(identity.encode()).hexdigest()
            principals.setdefault(child, set()).add(principal)
        if dispatched and current_child.startswith(PREPARATION_RUN_PREFIX):
            principals.setdefault(current_child, set()).add(principal)
    # Target receipts can also be retained by an operation observing someone
    # else's admission. They cannot establish the creator of a v19 target.
    updates = [(next(iter(owners)), child) for child, owners in principals.items() if len(owners) == 1]
    conn.executemany("UPDATE managed_admissions SET admitted_by=? WHERE queue_item_id=?", updates)
    _validate_coordinator_schema(conn)
    conn.execute("PRAGMA user_version=20")


def _upgrade_stopped_admissions(root: Path, *, fleet_replacement: bool = False) -> dict:
    """Commit under the native owner lock after the caller verifies root identity."""
    from ._maintenance import _read as maintenance_gate
    from .errors import QueueConflictError

    database = root / "control.sqlite"
    details = database.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or details.st_mode & 0o077:
        raise QueueServiceError("admission upgrade requires a private coordinator database")
    require_storage_upgrade_ready(root)
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True)) as conn, conn:
            conn.execute("PRAGMA synchronous=EXTRA")
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("PRAGMA user_version").fetchone()[0]
            if previous == 19:
                if fleet_replacement and maintenance_gate(conn)["state"] != "closed":
                    raise QueueConflictError("admission upgrade for runtime replacement requires closed maintenance")
                # Fence restoration of an older cohort snapshot before writing.
                require_storage_upgrade_ready(root, entering=True)
                _upgrade_admission_creators(conn)
            elif previous != 20:
                raise QueueServiceError("coordinator admission storage version is unsupported")
            total, attributed = conn.execute(
                "SELECT COUNT(*), COUNT(admitted_by) FROM managed_admissions"
            ).fetchone()
    except sqlite3.Error as exc:
        raise QueueServiceError(f"coordinator admission storage upgrade failed: {exc}") from exc
    return {"previous_version": previous, "storage_version": 20,
            "attributed": attributed, "unknown": total - attributed}


def upgrade_admission_creators(coordinator_root: Path, *, expected_coordinator_id: str) -> dict:
    """Atomically migrate one stopped coordinator journal, including bundles and retained work."""
    from .local_daemon import _acquire_lock, _open_root
    from .retirement import require_unretired

    root = coordinator_root.resolve()
    _private_directory(root)
    with _acquire_lock(root):
        identity = _open_root(root, role="coordinator", for_storage_upgrade=True)
        if identity != expected_coordinator_id:
            raise QueueServiceError("storage upgrade coordinator identity changed")
        require_unretired(root)
        return {"coordinator_id": identity, **_upgrade_stopped_admissions(root)}


def _prepare_database(role: dict, owner: dict, original: Path, candidate: Path) -> None:
    target = role["qualified"]
    with closing(sqlite3.connect(candidate, isolation_level=None)) as conn:
        conn.execute("PRAGMA synchronous=EXTRA")
        conn.execute("BEGIN IMMEDIATE")
        if original == Path(owner["root"]) / "control.sqlite":
            table = "daemon_metadata" if owner["role"] == "coordinator" else "root_metadata"
            values = dict(conn.execute(f"SELECT key, value FROM {table}"))
            revision = int(values["active_configuration_revision"]) + 1
            updates = {"active_configuration_revision": str(revision)}
            if owner["role"] == "coordinator":
                if conn.execute("PRAGMA user_version").fetchone()[0] == 19:
                    _upgrade_admission_creators(conn)
                updates.update(scheduling_fingerprint=target.active_fingerprint, scheduling_epoch="scheduling-epoch-" + str(uuid4()))
            else:
                from ._agent_session_journal import _record_agent_declaration_binding
                updates.update(active_configuration_fingerprint=target.active_fingerprint,
                               execution_store_requirements=json.dumps(owner["inventory"], sort_keys=True, separators=(",", ":")))
                _record_agent_declaration_binding(conn, target.client, revision)
            for key, value in updates.items():
                conn.execute(f"INSERT INTO {table}(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        elif owner["role"] == "coordinator" and original == Path(owner["root"]) / "execution.sqlite":
            from .slurm_ready_stage import _require_schema, _upgrade_released_schema, _upgrade_pending_effects_schema, _upgrade_start_request_schema, _upgrade_terminal_observation_schema
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 3 and target.daemon.slurm_schema_version >= 4:
                _upgrade_released_schema(conn)
                version = 4
            if version == 4 and target.daemon.slurm_schema_version >= 5:
                _upgrade_pending_effects_schema(conn)
                version = 5
            if version == 5 and target.daemon.slurm_schema_version >= 6:
                _upgrade_start_request_schema(conn)
                version = 6
            if version == 6 and target.daemon.slurm_schema_version >= 7:
                _upgrade_terminal_observation_schema(conn)
            _require_schema(conn, expected_version=target.daemon.slurm_schema_version)
            if {row[1] for row in conn.execute("PRAGMA table_info(ready_stage_submissions)")} != {"operation_id", "state", "value_json"}:
                raise QueueServiceError("storage upgrade submission projection is incompatible")
        elif original.name == "supervisor.sqlite":
            value = json.loads(_target_file(role, original.parent / "service-config.json"))
            conn.execute("UPDATE metadata SET value=? WHERE key='configuration_fingerprint'", (value["configuration_fingerprint"],))
        elif original.name == "resident.sqlite" and role["target"]["storage"] is not None:
            from ._remote_stage_execution import _require_resident_workspace_schema
            _require_resident_workspace_schema(conn)
            policy = role["target"]["storage"]
            if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
                conn.execute("CREATE TABLE storage_policy (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), value_json TEXT NOT NULL)")
                conn.execute("PRAGMA user_version=1")
            conn.execute("INSERT INTO storage_policy VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET value_json=excluded.value_json",
                         (json.dumps({**asdict(policy.sqlite), "durable_files": policy.durable_files}, sort_keys=True, separators=(",", ":")),))
            if _require_resident_workspace_schema(conn) != (policy.sqlite, policy.durable_files):
                raise QueueServiceError("resident workspace target policy did not verify")
        conn.commit()
        _integrity(conn)
    _sync_database(candidate)


def _locks(stack: ExitStack, owners: list[dict]) -> None:
    import fcntl
    from .local_daemon import _acquire_lock
    for owner in sorted(owners, key=lambda owner: owner["root"]):
        root = Path(owner["root"])
        _private_directory(root)
        stack.enter_context(_acquire_lock(root))
        if owner["supervisor"]:
            path = root / "supervisor/service.lock"
            lock = stack.enter_context(path.open("a+"))
            path.chmod(0o600)
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QueueServiceError("storage upgrade supervisor is still running") from exc


def _prepare(request: dict, request_digest: str, roles: list[dict], owners: list[dict]) -> dict:
    root = Path(request["snapshot_root"])
    manifest = {"version": 1, "operation_id": request["operation_id"], "request_digest": request_digest,
                "owners": owners, "state": "preparing", "databases": [], "files": [], "completed": []}
    if root.exists():
        _private_directory(root)
        prior = read_private_json(root / "manifest.json")
        if prior["request_digest"] != request_digest or prior["state"] not in {"preparing", "prepared"}:
            raise QueueServiceError("storage upgrade snapshot cannot be replaced")
        publish_json(root / "manifest.json", manifest)
    else:
        _private_directory(root.parent)
        staging = root.parent / (".storage-upgrade-" + str(uuid4()))
        staging.mkdir(mode=0o700)
        try:
            publish_json(staging / "manifest.json", manifest)
            staging.rename(root)
            _fsync_path_strict(root.parent)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    for role, owner in zip(roles, owners, strict=True):
        for name in owner["databases"]:
            original = Path(name)
            key = "db-" + hashlib.sha256(name.encode()).hexdigest()
            source, target = root / (key + "-source.sqlite"), root / (key + "-target.sqlite")
            digest, mode = _db_facts(original)
            _copy_database(original, source, mode="delete")
            if _db_facts(source)[0] != digest:
                raise QueueServiceError("storage upgrade snapshot changed during capture")
            _copy_database(source, target, mode="delete")
            _prepare_database(role, owner, original, target)
            policy = role["target"]["storage"]
            manifest["databases"].append({"path": name, "source": source.name, "target": target.name,
                "source_digest": digest, "target_digest": _db_facts(target)[0], "source_mode": mode,
                "target_mode": mode if policy is None else policy.sqlite.journal_mode})
        for name in owner["files"]:
            original = Path(name)
            key = "file-" + hashlib.sha256(name.encode()).hexdigest()
            source, target = root / (key + "-source"), root / (key + "-target")
            before, after = original.read_bytes(), _target_file(role, original)
            atomic_write_bytes(source, before, durability="strict")
            atomic_write_bytes(target, after, durability="strict")
            manifest["files"].append({"path": name, "source": source.name, "target": target.name,
                "source_digest": hashlib.sha256(before).hexdigest(), "target_digest": hashlib.sha256(after).hexdigest()})
    manifest["state"] = "prepared"
    publish_json(root / "manifest.json", manifest)
    return manifest


def _guards(root: Path, manifest: dict, *, allow_previous: bool = False) -> None:
    for owner in manifest["owners"]:
        path = Path(owner["root"]) / GUARD_NAME
        expected = {
            "version": 1, "operation_id": manifest["operation_id"], "manifest": str(root / "manifest.json"), "root_id": owner["root_id"],
        }
        current = read_private_json(path) if path.exists() else None
        if current != expected:
            if not allow_previous or current != owner["prior_guard"]:
                raise QueueServiceError("storage upgrade owner guard belongs to a different operation")
            require_storage_upgrade_ready(Path(owner["root"]))
        publish_json(path, expected)


def _publish_entries(root: Path, manifest: dict, side: str) -> None:
    for kind in ("databases", "files"):
        for entry in manifest[kind]:
            live = Path(entry["path"])
            for selection in ("source", "target"):
                artifact = root / entry[selection]
                actual = _db_facts(artifact)[0] if kind == "databases" else hashlib.sha256(artifact.read_bytes()).hexdigest()
                if actual != entry[selection + "_digest"]:
                    raise QueueServiceError("storage upgrade snapshot or prepared target changed")
            actual = _db_facts(live)[0] if kind == "databases" else hashlib.sha256(live.read_bytes()).hexdigest()
            if actual not in {entry["source_digest"], entry["target_digest"]}:
                raise QueueServiceError("storage upgrade encountered unrecorded live state")
            selected = root / entry[side]
            if kind == "databases":
                _copy_database(selected, live, mode=entry[side + "_mode"])
                if _db_facts(live) != (entry[side + "_digest"], entry[side + "_mode"]):
                    raise QueueServiceError("storage upgrade database publication did not verify")
            else:
                atomic_write_bytes(live, selected.read_bytes(), durability="strict")
                if hashlib.sha256(live.read_bytes()).hexdigest() != entry[side + "_digest"]:
                    raise QueueServiceError("storage upgrade binding publication did not verify")
            if entry["path"] not in manifest["completed"]:
                manifest["completed"].append(entry["path"])
            publish_json(root / "manifest.json", manifest)


def storage_upgrade(request_path: str | Path, *, action: str = "inspect") -> dict:
    """Inspect/apply/resume/restore one protected stopped-upgrade request.

    Supported: pure coordinators with explicit embedded authority roots or a
    separately owned remote authority, and outbound resident/Slurm agents. No
    root relocation, active migration, arbitrary old control-schema conversion
    or coordinator-bundle conversion is performed.
    """
    if action not in {"inspect", "apply", "resume", "restore"}:
        raise QueueConfigError("unsupported storage upgrade action")
    request, digest = _request(request_path)
    root = Path(request["snapshot_root"])
    manifest_path = root / "manifest.json"
    manifest = read_private_json(manifest_path) if manifest_path.exists() else None
    if manifest is not None and (manifest.get("version") != 1 or manifest.get("request_digest") != digest):
        raise QueueServiceError("storage upgrade request conflicts with the retained operation")
    if manifest is not None and action == "inspect":
        return {"operation_id": request["operation_id"], "state": manifest["state"], "owners": manifest["owners"],
                "completed": manifest["completed"], "snapshot_root": str(root),
                "entered": any((root / ("entered-" + owner_key(Path(owner["root"])) + ".json")).exists() for owner in manifest["owners"])}
    if action == "restore" and manifest is None:
        raise QueueServiceError("storage upgrade has no retained snapshot")
    if action == "resume" and manifest is None:
        raise QueueServiceError("storage upgrade has no retained operation")
    if manifest is None or manifest["state"] in {"preparing", "prepared"} and action != "restore":
        roles = _declarations(request, qualify=action != "inspect")
        owners = [_source_inventory(role, request) for role in roles]
        if action == "inspect":
            return {"operation_id": request["operation_id"], "state": "eligible", "owners": owners,
                    "snapshot_root": str(root), "qualified": False}
    else:
        roles, owners = [], manifest["owners"]
    with ExitStack() as stack:
        _locks(stack, owners)
        # Recovery may start after any live binding was converted. Recheck the
        # declarations and physical owner, not those original live bindings.
        _declarations(request, qualify=False)
        if _request(request_path)[1] != digest:
            raise QueueServiceError("storage upgrade declarations changed after inspection")
        if action == "restore":
            assert manifest is not None  # Missing restore snapshots were rejected above.
            if any((root / ("entered-" + owner_key(Path(owner["root"])) + ".json")).exists() for owner in owners):
                raise QueueServiceError("storage upgrade restore is forbidden after a target owner entered")
            if manifest["state"] == "restored":
                return {"operation_id": request["operation_id"], "state": "restored"}
            if manifest["state"] != "preparing":
                _guards(root, manifest, allow_previous=manifest["state"] == "prepared")
                manifest["state"], manifest["completed"] = "restoring", []
                publish_json(manifest_path, manifest)
                _publish_entries(root, manifest, "source")
            manifest["state"] = "restored"
            publish_json(manifest_path, manifest)
        else:
            if manifest is not None and manifest["state"] in {"ready", "restored"}:
                return {"operation_id": request["operation_id"], "state": manifest["state"]}
            if manifest is not None and manifest["state"] == "restoring":
                raise QueueServiceError("storage upgrade restore is incomplete; resume with restore")
            if roles:
                owners = [_source_inventory(role, request) for role in roles]
                manifest = _prepare(request, digest, roles, owners)
            assert manifest is not None  # Retained or just prepared under the owner locks.
            _guards(root, manifest, allow_previous=manifest["state"] == "prepared")
            manifest["state"] = "converting"
            publish_json(manifest_path, manifest)
            _publish_entries(root, manifest, "target")
            manifest["state"] = "ready"
            publish_json(manifest_path, manifest)
    return {"operation_id": request["operation_id"], "state": manifest["state"], "snapshot_root": str(root)}

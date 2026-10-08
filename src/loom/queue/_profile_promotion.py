"""Maintenance-only executable promotion on the existing control/journal owner.

One accepted local intent fences startup before any protected binding changes.
Recovery completes that intent under the agent and supervisor locks. Completed
control replay never revisits bindings, including after a later promotion.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import fields, replace
import fcntl
import json
import os
import tempfile
from pathlib import Path
import sqlite3
from typing import Any

from loom.serialization import thaw_plain_data
from .errors import QueueConflictError, QueueServiceError

CAPABILITY = "quiescent-profile-promotion-v2"
_PENDING = "profile_promotion_pending"


def validate_promotion(value: object) -> None:
    keys = {
        "maintenance_id",
        "maintenance_intent_digest",
        "expected_gate_revision",
        "agent_root_id",
        "predecessor_immutable",
        "predecessor_active",
        "target_immutable",
        "target_active",
        "profile_id",
        "target_profile",
    }
    if not isinstance(value, Mapping) or set(value) not in (
        keys,
        keys | {"candidate_source"},
    ):
        raise QueueServiceError("profile promotion binding fields are invalid")
    if "candidate_source" in value and (
        not isinstance(value["candidate_source"], str)
        or not Path(value["candidate_source"]).is_absolute()
    ):
        raise QueueServiceError("profile promotion candidate source is invalid")
    for key in keys - {"expected_gate_revision", "target_profile"}:
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 512:
            raise QueueServiceError("profile promotion binding is invalid")
    if (
        type(value["expected_gate_revision"]) is not int
        or value["expected_gate_revision"] < 0
    ):
        raise QueueServiceError("profile promotion gate revision is invalid")
    from ._remote_stage_execution import ResidentProfileDescriptor

    profile = ResidentProfileDescriptor.from_dict(value["target_profile"])
    if profile.profile_id != value["profile_id"]:
        raise QueueServiceError("profile promotion target identity differs")


def authorize(daemon: Any, conn: sqlite3.Connection, control: Any) -> None:
    """Validate the native gate and session in the control acceptance transaction."""
    from ._maintenance import _read
    from ._service_lifetime import _retained_coordinator_operations

    value = control.promotion
    gate = _read(conn)
    if (
        gate["state"] != "closed"
        or gate["maintenance_id"] != value["maintenance_id"]
        or gate["intent_digest"] != value["maintenance_intent_digest"]
        or gate["revision"] != value["expected_gate_revision"]
        or gate["checks"]
    ):
        raise QueueConflictError(
            "profile promotion requires the exact closed maintenance gate"
        )
    if (
        _retained_coordinator_operations(conn)
        or daemon._service_error is not None
        or conn.execute(
            "SELECT 1 FROM agent_coordinator_references WHERE resolved=0 LIMIT 1"
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM agent_controls WHERE state IN ('pending_delivery','applying') OR acknowledged=0 LIMIT 1"
        ).fetchone()
    ):
        raise QueueConflictError("profile promotion requires native settlement")
    session = conn.execute(
        "SELECT agent_root_id FROM agent_sessions WHERE session_id=?",
        (control.expected_session_id,),
    ).fetchone()
    previous = conn.execute(
        "SELECT request_json,state,acknowledged FROM agent_controls WHERE session_id=? ORDER BY rowid DESC LIMIT 1",
        (control.expected_session_id,),
    ).fetchone()
    if (
        session is None
        or session[0] != value["agent_root_id"]
        or previous is None
        or previous[1] != "applied"
        or not previous[2]
        or json.loads(previous[0])["kind"] not in {"drain", "reload", "promote"}
    ):
        raise QueueConflictError(
            "profile promotion requires the exact drained native agent"
        )


def atomic_write_bytes(path: Path, value: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".promotion-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _encoded(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _validate_target(config: Any, control: Any) -> None:
    from ._agent_session_journal import _agent_active_fingerprint

    p = control.promotion
    if (
        config.deployment_configuration_fingerprint != p["target_immutable"]
        or _agent_active_fingerprint(config) != p["target_active"]
        or len(config.resident_profiles) != 1
        or config.resident_profiles[0].descriptor.to_dict()
        != thaw_plain_data(p["target_profile"])
    ):
        raise QueueConflictError(
            "profile promotion target differs from accepted intent"
        )


def validate_candidate(previous: Any, replacement: Any, profile_id: str) -> None:
    """Check a selected native profile candidate before or during promotion.

    Capacity, snapshot mappings and logical storage qualifications are retained.
    A read-only root may move to an equally qualified path; native promotion's
    existing maintenance, settlement and owner guards authorize activation.
    """
    allowed = {
        "resident_profiles", "deployment_configuration_fingerprint",
        "active_configuration_fingerprint", "declaration_digest",
    }
    if any(
        getattr(previous, field.name) != getattr(replacement, field.name)
        for field in fields(replacement) if field.name not in allowed
    ):
        raise QueueConflictError("profile promotion cannot change unrelated role configuration")
    if (
        len(previous.resident_profiles) != 1 or len(replacement.resident_profiles) != 1
        or previous.resident_profiles[0].descriptor.profile_id != profile_id
        or replacement.resident_profiles[0].descriptor.profile_id != profile_id
    ):
        raise QueueConflictError("profile promotion requires one selected resident profile")
    old, new = previous.resident_profiles[0], replacement.resident_profiles[0]
    for name in ("cpu_capacity", "memory_capacity_bytes", "gpu_devices", "preparation_shared_roots"):
        if getattr(old, name) != getattr(new, name):
            raise QueueConflictError("profile promotion cannot change resource or storage policy")
    from .shared_execution import _readonly_root_relocations

    _readonly_root_relocations(old.shared_roots, new.shared_roots)
    if set(old.shared_roots) != set(new.shared_roots):
        raise QueueConflictError("profile promotion cannot add or remove logical storage roots")


def _supervisor_value(root_id: str, config: Any) -> dict[str, Any]:
    from ._agent_process_supervisor import SupervisorLaunchConfiguration, _profile_value

    value = SupervisorLaunchConfiguration(
        root_id, tuple(p.launch_profile for p in config.resident_profiles)
    )
    return {
        "agent_id": root_id,
        "profiles": [_profile_value(p) for p in value.profiles],
        "configuration_fingerprint": value.fingerprint,
    }


@contextmanager
def _supervisor_lock(root: Path):
    with (root / "supervisor" / "service.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QueueConflictError(
                "profile promotion supervisor is still owned"
            ) from exc
        yield


def _finish(journal: Any, config: Any, pending: dict[str, Any]) -> Any:
    """Caller holds both native locks; retained intent permits only two bindings."""
    from .agent_sessions import AgentControl, AgentControlEffect
    from ._agent_session_journal import (
        _AGENT_BINDING_FILE,
        _agent_config_revision,
        _agent_inventory_revision,
        _agent_revision,
    )
    from ._agent_process_supervisor import AgentProcessSupervisorService

    control = AgentControl.from_value(pending["control"])
    _validate_target(config, control)
    root = Path(config.agent_root)
    publication = pending.get("source")
    if publication is not None:
        source = Path(publication["path"])
        if source.read_text() not in (publication["before"], publication["after"]):
            raise QueueConflictError("profile promotion source publication conflicts")
        atomic_write_bytes(source, publication["after"].encode())
    target = _supervisor_value(journal.root_id, config)
    path = root / "supervisor" / AgentProcessSupervisorService._CONFIG_NAME
    old = pending["supervisor"]
    current = json.loads(path.read_bytes())
    if current not in (old, target):
        raise QueueConflictError("profile promotion supervisor binding conflicts")
    with sqlite3.connect(root / "supervisor" / "supervisor.sqlite") as conn:
        conn.execute("BEGIN IMMEDIATE")
        fp = conn.execute(
            "SELECT value FROM metadata WHERE key='configuration_fingerprint'"
        ).fetchone()[0]
        if fp not in (
            old["configuration_fingerprint"],
            target["configuration_fingerprint"],
        ):
            raise QueueConflictError(
                "profile promotion supervisor predecessor conflicts"
            )
        if conn.execute(
            "SELECT 1 FROM launches WHERE state NOT IN ('contained','exited') LIMIT 1"
        ).fetchone():
            raise QueueConflictError(
                "profile promotion has unresolved supervisor launches"
            )
        conn.execute(
            "UPDATE metadata SET value=? WHERE key='configuration_fingerprint'",
            (target["configuration_fingerprint"],),
        )
        conn.commit()
    atomic_write_bytes(path, _encoded(target))
    binding_path = root / _AGENT_BINDING_FILE
    binding = json.loads(binding_path.read_bytes())
    target_binding = {
        **pending["binding"],
        "immutable_fingerprint": config.deployment_configuration_fingerprint,
    }
    if binding not in (pending["binding"], target_binding):
        raise QueueConflictError("profile promotion protected predecessor conflicts")
    atomic_write_bytes(binding_path, _encoded(target_binding))
    effect = AgentControlEffect(
        control.operation_id,
        "applied",
        _agent_config_revision(config),
        _agent_inventory_revision(config),
        _agent_revision(
            "availability",
            {
                "operation_id": control.operation_id,
                "drained": True,
                "inventory_revision": _agent_inventory_revision(config),
            },
        ),
    )
    journal.complete_reload(control, config, effect)
    return effect


def apply(client: Any, control: Any) -> Any:
    """Apply one delivered promotion; never relax the ordinary reload boundary."""
    from ._agent_session_journal import _AGENT_BINDING_FILE, _agent_active_fingerprint
    from ._agent_process_supervisor import (
        AgentProcessSupervisorService,
        retained_supervisor_guard,
    )

    journal = client._require_journal()
    replay = journal.replayed_control_effect(control)
    if replay is not None:
        return replay
    if client._trusted_config_loader is None:
        raise QueueServiceError("profile promotion requires protected configuration")
    source = None
    if control.promotion.get("candidate_source") is not None:
        if client._trusted_promotion_loader is None:
            raise QueueServiceError("native service promotion loader unavailable")
        replacement, source = client._trusted_promotion_loader(
            control.promotion["candidate_source"]
        )
    else:
        replacement = client._trusted_config_loader()
    _validate_target(replacement, control)
    p = control.promotion
    if (
        journal.root_id != p["agent_root_id"]
        or client._config.deployment_configuration_fingerprint
        != p["predecessor_immutable"]
        or _agent_active_fingerprint(client._config) != p["predecessor_active"]
        or client._has_retained_agent_work()
        or journal.pending_poll() is not None
    ):
        raise QueueConflictError(
            "profile promotion predecessor or native settlement conflicts"
        )
    validate_candidate(client._config, replacement, p["profile_id"])
    root = Path(replacement.agent_root)
    install = (
        client._prepare_role_reload(replacement)
        if client._prepare_role_reload
        else lambda: None
    )
    with journal._connection() as conn:
        retained = conn.execute(
            "SELECT value FROM root_metadata WHERE key=?", (_PENDING,)
        ).fetchone()
    if retained is not None:
        pending = json.loads(retained[0])
        if pending["control"] != control.value():
            raise QueueConflictError("another profile promotion is pending")
        with _supervisor_lock(root):
            effect = _finish(journal, replacement, pending)
        _install(client, replacement, install)
        return effect
    # The retained native guard proves a clean cut and holds the supervisor lock.
    with retained_supervisor_guard(root, agent_id=journal.root_id):
        pending = {
            "control": control.value(),
            "source": source,
            "binding": json.loads((root / _AGENT_BINDING_FILE).read_bytes()),
            "supervisor": json.loads(
                (
                    root / "supervisor" / AgentProcessSupervisorService._CONFIG_NAME
                ).read_bytes()
            ),
        }
        with journal._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT request_json,effect_json FROM agent_controls_local WHERE operation_id=?",
                (control.operation_id,),
            ).fetchone()
            if (
                row is None
                or json.loads(row[0]) != control.value()
                or row[1] is not None
            ):
                raise QueueConflictError("profile promotion delivery differs")
            metadata = dict(conn.execute("SELECT key,value FROM root_metadata"))
            if (
                metadata.get("active_configuration_fingerprint")
                != p["predecessor_active"]
                or metadata.get(_PENDING) is not None
                or metadata.get("availability_state") != "drained"
            ):
                raise QueueConflictError(
                    "profile promotion native predecessor conflicts"
                )
            conn.execute(
                "INSERT INTO root_metadata(key,value) VALUES (?,?)",
                (_PENDING, _encoded(pending).decode()),
            )
            # Old software also refuses this intermediate active binding. No schema
            # migration or reinterpretation of settled historical rows is required.
            conn.execute(
                "UPDATE root_metadata SET value=? WHERE key='active_configuration_fingerprint'",
                ("promotion-pending:" + control.operation_id,),
            )
            conn.execute(
                "UPDATE agent_controls_local SET replacement_fingerprint=? WHERE operation_id=?",
                (p["target_active"], control.operation_id),
            )
            conn.commit()
        effect = _finish(journal, replacement, pending)
    _install(client, replacement, install)
    return effect


def _install(client: Any, replacement: Any, install: Any) -> None:
    client._config = replacement
    install()
    client._profiles = {
        p.descriptor.profile_id: p for p in replacement.resident_profiles
    }
    client._retained_profiles.clear()
    if replacement.external_supervisor:
        # Fleet restarts the separately managed supervisor after native effect;
        # resume joins that exact endpoint before any capacity can return.
        client._supervisor = None
    else:
        client._supervisor, _ = client._open_supervisor(replacement)
    client._reset_runtime_providers()


def recover(config: Any) -> Any:
    """Resolve accepted partial bindings before any service/supervisor can start."""
    if config.agent_root is None:
        return config
    root = Path(config.agent_root)
    database = root / "control.sqlite"
    if not database.is_file():
        return config
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT value FROM root_metadata WHERE key=?", (_PENDING,)
        ).fetchone()
    if row is None:
        return config
    from ._agent_session_journal import _RemoteAgentJournal
    from .local_daemon import _acquire_lock, _open_root

    with _acquire_lock(root), _supervisor_lock(root):
        root_id = _open_root(root, role="local-agent")
        with sqlite3.connect(database) as conn:
            row = conn.execute(
                "SELECT value FROM root_metadata WHERE key=?", (_PENDING,)
            ).fetchone()
        if row is None:
            return config
        # Reuse the existing journal completion transaction while its native
        # lock is already held; no constructor may bypass pending validation.
        journal = object.__new__(_RemoteAgentJournal)
        journal._root = root
        journal._path = database
        journal.root_id = root_id
        pending = json.loads(row[0])
        if pending.get("source") is not None:
            from .deployment import load_outbound_agent_service_config

            source = pending["source"]
            target = load_outbound_agent_service_config(
                source["candidate"], env_file=source["environment"]
            )
            config = replace(
                target.client, external_supervisor=config.external_supervisor
            )
        _finish(journal, config, pending)
        return config


def publication_state(root: Path, operation_id: str) -> str | None:
    """Inspect native authorization of one canonical source publication."""
    database = root / "control.sqlite"
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        pending = conn.execute(
            "SELECT value FROM root_metadata WHERE key=?", (_PENDING,)
        ).fetchone()
        if (
            pending is not None
            and json.loads(pending[0])["control"]["operation_id"] == operation_id
        ):
            return "pending"
        row = conn.execute(
            "SELECT effect_json FROM agent_controls_local WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    if (
        row is not None
        and row[0] is not None
        and json.loads(row[0])["code"] == "applied"
    ):
        return "applied"
    return None


def completed(root: Path, operation_id: str) -> bool:
    """Read the native local effect before restarting its changed supervisor."""
    return publication_state(root, operation_id) == "applied"

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
RETIREMENT_CAPABILITY = "quiescent-configuration-retirement-v1"
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
    retirement = isinstance(value, Mapping) and value.get("retire_configuration") is True
    addition = isinstance(value, Mapping) and value.get("add_container_policies") is True
    increase = isinstance(value, Mapping) and value.get("increase_publication_budgets") is True
    if increase:
        keys = keys - {"profile_id", "target_profile"} | {"increase_publication_budgets"}
    if addition:
        keys = keys - {"profile_id", "target_profile"} | {"add_container_policies"}
    if retirement:
        keys = keys - {"profile_id", "target_profile"} | {"retire_configuration"}
    if not isinstance(value, Mapping) or set(value) - {"candidate_source", "enable_submitted_containers"} != keys:
        raise QueueServiceError("profile promotion binding fields are invalid")
    if "enable_submitted_containers" in value and value["enable_submitted_containers"] is not True:
        raise QueueServiceError("submitted container enablement must be true")
    if "candidate_source" in value and (
        not isinstance(value["candidate_source"], str)
        or not Path(value["candidate_source"]).is_absolute()
    ):
        raise QueueServiceError("profile promotion candidate source is invalid")
    for key in keys - {"expected_gate_revision", "target_profile", "retire_configuration", "add_container_policies", "increase_publication_budgets"}:
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 512:
            raise QueueServiceError("profile promotion binding is invalid")
    if (
        type(value["expected_gate_revision"]) is not int
        or value["expected_gate_revision"] < 0
    ):
        raise QueueServiceError("profile promotion gate revision is invalid")
    from ._remote_stage_execution import ResidentProfileDescriptor

    if retirement or addition or increase:
        if sum((retirement, addition, increase)) > 1:
            raise QueueServiceError("policy addition, retirement and budget increase are mutually exclusive")
        if "enable_submitted_containers" in value:
            raise QueueServiceError("configuration retirement cannot enable a new execution capability")
        return
    profile = ResidentProfileDescriptor.from_dict(value["target_profile"])
    if profile.profile_id != value["profile_id"]:
        raise QueueServiceError("profile promotion target identity differs")


def authorize(daemon: Any, conn: sqlite3.Connection, control: Any) -> None:
    """Validate the native gate and session in the control acceptance transaction."""
    from ._maintenance import _read
    from ._service_lifetime import _retained_coordinator_operations

    value = control.promotion
    if value.get("enable_submitted_containers"):
        from .submitted_execution import SUBMITTED_CONTAINER_CAPABILITY
        rule = next(rule for rule in daemon._agent_policy.agents if rule.agent_id == control.agent_id)
        if SUBMITTED_CONTAINER_CAPABILITY not in rule.capabilities:
            raise QueueConflictError("submitted container capability is not authorized by agent policy")
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
    if p.get("enable_submitted_containers") and not config.container_policies:
        raise QueueConflictError("submitted container enablement requires a protected policy")
    if (
        config.deployment_configuration_fingerprint != p["target_immutable"]
        or _agent_active_fingerprint(config) != p["target_active"]
        or (not (p.get("retire_configuration") or p.get("add_container_policies") or p.get("increase_publication_budgets")) and (
            len(config.resident_profiles) != 1
            or config.resident_profiles[0].descriptor.to_dict()
            != thaw_plain_data(p["target_profile"])
        ))
    ):
        raise QueueConflictError(
            "profile promotion target differs from accepted intent"
        )


def validate_candidate(previous: Any, replacement: Any, profile_id: str | None, *, retire_configuration: bool = False, add_container_policies: bool = False, increase_publication_budgets: bool = False) -> None:
    """Check a selected native profile candidate before or during promotion.

    Capacity, snapshot mappings and logical storage qualifications are retained.
    A read-only root may move to an equally qualified path; native promotion's
    existing maintenance, settlement and owner guards authorize activation.
    """
    allowed = {
        "resident_profiles", "deployment_configuration_fingerprint",
        "active_configuration_fingerprint", "declaration_digest", "container_policies",
    }
    if any(
        getattr(previous, field.name) != getattr(replacement, field.name)
        for field in fields(replacement) if field.name not in allowed
    ):
        raise QueueConflictError("profile promotion cannot change unrelated role configuration")
    if sum((retire_configuration, add_container_policies, increase_publication_budgets)) > 1:
        raise QueueConflictError("policy addition, retirement and budget increase are mutually exclusive")
    if increase_publication_budgets:
        from ._publication_budget_increase import validate_agent
        validate_agent(previous, replacement)
        return
    if add_container_policies:
        from ._container_policy_addition import validate_agent
        validate_agent(previous, replacement)
        return
    if retire_configuration:
        _validate_retirement(previous, replacement)
        return
    # Enable submission-selected execution through the existing quiescent cut.
    # Existing policies and the single host resource inventory remain immutable.
    policies = {policy.policy_id: policy for policy in replacement.container_policies}
    if any(policies.get(policy.policy_id) != policy for policy in previous.container_policies):
        raise QueueConflictError("profile promotion cannot remove or replace container policies")
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


def _validate_retirement(previous: Any, replacement: Any) -> None:
    """Retire unused declarations without rebinding retained logical identities."""
    if previous.resource_inventory is None or not replacement.container_policies:
        raise QueueConflictError("configuration retirement requires explicit resources and retained container policies")
    profiles = {profile.descriptor.profile_id: profile for profile in previous.resident_profiles}
    if any(profiles.get(profile.descriptor.profile_id) != profile for profile in replacement.resident_profiles):
        raise QueueConflictError("configuration retirement cannot add or change resident profiles")
    _validate_retired_policies(
        [policy.to_dict() for policy in previous.container_policies],
        [policy.to_dict() for policy in replacement.container_policies],
    )


def _validate_retired_policies(previous, replacement):
    from .shared_execution import _readonly_root_relocations

    policies = {policy["policy_id"]: policy for policy in previous}
    for policy in replacement:
        old = policies.get(policy["policy_id"])
        if old is None:
            raise QueueConflictError("configuration retirement cannot add container policies")
        roots = policy["shared_roots"]
        if not set(roots) <= set(old["shared_roots"]):
            raise QueueConflictError("configuration retirement cannot add shared roots")
        _readonly_root_relocations(
            {key: old["shared_roots"][key] for key in roots}, roots
        )
        if any(old["preparation_shared_roots"].get(key) != value
               for key, value in policy["preparation_shared_roots"].items()):
            raise QueueConflictError("configuration retirement cannot rebind preparation roots")


def validate_retirement_specs(previous, replacement):
    """Compare protected AgentSpecs without qualifying retired dependencies.

    This is candidate validation, not activation authority. The native update
    must separately match the predecessor's declaration digest to accepted root
    evidence, require settled maintenance, and qualify the replacement.
    """
    before, after = previous.declarations, replacement.declarations
    mutable = {"resident_profiles", "container_policies"}
    if ({key: value for key, value in before.items() if key not in mutable}
        != {key: value for key, value in after.items() if key not in mutable}):
        raise QueueConflictError("configuration retirement cannot change unrelated role declarations")
    if before["resources"] is None or not after.get("container_policies"):
        raise QueueConflictError("configuration retirement requires explicit resources and retained container policies")
    profiles = {profile["descriptor"]["profile_id"]: profile for profile in before["resident_profiles"]}
    if any(profiles.get(profile["descriptor"]["profile_id"]) != profile
           for profile in after["resident_profiles"]):
        raise QueueConflictError("configuration retirement cannot add or change resident profiles")
    _validate_retired_policies(before.get("container_policies", ()), after["container_policies"])


def _supervisor_value(root_id: str, config: Any) -> dict[str, Any]:
    from ._agent_process_supervisor import SupervisorLaunchConfiguration, _profile_value

    value = SupervisorLaunchConfiguration(
        root_id, tuple(p.launch_profile for p in config.resident_profiles), config.container_policies
    )
    return {
        "agent_id": root_id,
        "profiles": [_profile_value(p) for p in value.profiles],
        "configuration_fingerprint": value.fingerprint,
        **({"container_policies": [policy.to_dict() for policy in value.container_policies]} if value.container_policies else {}),
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
    from ._agent_session_journal import _agent_active_fingerprint

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
    validate_candidate(client._config, replacement, p.get("profile_id"),
                       retire_configuration=p.get("retire_configuration", False),
                       add_container_policies=p.get("add_container_policies", False),
                       increase_publication_budgets=p.get("increase_publication_budgets", False))
    if not client._config.container_policies and replacement.container_policies and not p.get("enable_submitted_containers"):
        raise QueueConflictError("adding container policies requires explicit session capability enablement")
    install = (
        client._prepare_role_reload(replacement)
        if client._prepare_role_reload
        else lambda: None
    )
    effect = _apply_retained(journal, replacement, control, source)
    _install(client, replacement, install)
    return effect


def receive_stopped(spec, control, *, expected_coordinator_id):
    """Retain an exact coordinator delivery under stopped agent ownership.

    Uses only selected TLS credentials and the accepted native session; it does
    not qualify predecessor execution, register a replacement session, poll for
    work, or acknowledge the control. An existing receipt is replayed locally.
    Once promotion is pending, use :func:`apply_stopped` for native recovery.
    """
    from .agent_sessions import AgentControl, AgentControlKind, AgentSessionState
    from .deployment import read_agent_spec
    from .retirement import read_agent_declaration_binding, require_unretired, _retained_agent_owners
    from ._agent_session_journal import _RemoteAgentJournal
    from .agent_session_transport import AgentTlsClientConfig, LocalDaemonAgentHttpClient, _has_retained_agent_work

    if control.kind is not AgentControlKind.PROMOTE or not control.promotion.get("retire_configuration"):
        raise QueueConflictError("stopped delivery requires configuration retirement")
    current = read_agent_spec(spec.source_path, env_file=spec.environment_path)
    if current.declaration_digest != spec.declaration_digest:
        raise QueueConflictError("stopped delivery declaration changed")
    binding = read_agent_declaration_binding(current.agent_root, current.declaration_digest)
    if binding is None:
        raise QueueConflictError("stopped delivery requires accepted declaration binding")
    journal = _RemoteAgentJournal(current.agent_root,
        expected_configuration_fingerprint=binding.immutable_fingerprint,
        expected_active_configuration_fingerprint=binding.active_fingerprint)
    try:
        require_unretired(current.agent_root)
        if read_agent_declaration_binding(current.agent_root, current.declaration_digest) != binding:
            raise QueueConflictError("stopped delivery declaration changed during ownership check")
        session = journal.session(control.expected_session_id)
        if (session.coordinator_id != expected_coordinator_id
            or session.agent_id != control.agent_id or session.agent_root_id != binding.root_id
            or session.state is not AgentSessionState.ACTIVE
            or binding.root_id != control.promotion["agent_root_id"]):
            raise QueueConflictError("stopped delivery session or native identity conflicts")
        with journal._connection() as conn:
            row = conn.execute("SELECT request_json FROM agent_controls_local WHERE operation_id=?",
                               (control.operation_id,)).fetchone()
            drained = conn.execute("SELECT value FROM root_metadata WHERE key='availability_state'").fetchone()
        if row is not None:
            if json.loads(row[0]) != control.value():
                raise QueueConflictError("stopped delivery replay conflicts")
            return control
        if (drained is None or drained[0] != "drained"
            or session.config_revision != control.expected_config_revision
            or binding.immutable_fingerprint != control.promotion["predecessor_immutable"]
            or binding.active_fingerprint != control.promotion["predecessor_active"]):
            raise QueueConflictError("stopped delivery requires the drained predecessor")
        execution, slurm = _retained_agent_owners(current)
        if _has_retained_agent_work(journal, execution, slurm) or journal.pending_poll() is not None:
            raise QueueConflictError("stopped delivery requires settled native work")
        values = current.declarations
        transport = AgentTlsClientConfig(values["url"], Path(values["server_ca_path"]),
            Path(values["certificate_path"]), Path(values["private_key_path"]))

        client = LocalDaemonAgentHttpClient(transport)
        # Borrow the already locked journal for the normal reconciliation
        # transaction. Transport-only construction does not load retired inputs.
        client._journal = journal
        try:
            handshake = client.handshake()
            if handshake.get("coordinator_id") != expected_coordinator_id:
                raise QueueConflictError("stopped delivery coordinator identity changed")
            if session.coordinator_epoch != handshake["coordinator_epoch"]:
                from .deployment import _operation_id
                session = client.reconcile(session.session_id, handshake["coordinator_epoch"],
                    idempotency_key=_operation_id("reconcile", session.session_id, handshake["coordinator_epoch"]))
            raw = client._call("control", {"session_id": session.session_id}).get("control")
        finally:
            client._journal = None
            client.close()
        if raw is None or AgentControl.from_value(raw) != control:
            raise QueueConflictError("stopped delivery differs from authorized coordinator control")
        if read_agent_spec(current.source_path, env_file=current.environment_path).declaration_digest != current.declaration_digest:
            raise QueueConflictError("stopped delivery source changed during exchange")
        journal.retain_control(control)
        effect = journal.prepare_control(control)
        if effect is not None:
            raise QueueConflictError("stopped delivery native revision changed")
        return control
    finally:
        journal.close()


def apply_stopped(spec, control):
    """Apply an already received retirement control without loading old inputs.

    The authenticated agent transport must have retained the exact delivery.
    This does not fabricate a control or acknowledge it to the coordinator.
    Normal service continuation owns acknowledgement after runtime replacement.
    Only the accepted pending intent may recover partially published bindings.
    """
    from .agent_sessions import AgentControlKind, AgentSessionState
    from .deployment import read_agent_spec, load_outbound_agent_service_config, _load_protected_config
    from .retirement import read_agent_declaration_binding, require_unretired, _retained_agent_owners
    from ._agent_session_journal import _RemoteAgentJournal
    from .agent_session_transport import _has_retained_agent_work

    if control.kind is not AgentControlKind.PROMOTE or not control.promotion.get("retire_configuration"):
        raise QueueConflictError("stopped conversion requires configuration retirement")
    validate_promotion(control.promotion)
    database = spec.agent_root / "control.sqlite"
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        pending = conn.execute("SELECT value FROM root_metadata WHERE key=?", (_PENDING,)).fetchone()
    if pending is not None:
        if json.loads(pending[0])["control"] != control.value():
            raise QueueConflictError("another profile promotion is pending")
        recover(spec)
    current = read_agent_spec(spec.source_path, env_file=spec.environment_path)
    if pending is None and current.declaration_digest != spec.declaration_digest:
        raise QueueConflictError("stopped retirement declaration changed")
    binding = read_agent_declaration_binding(current.agent_root, current.declaration_digest)
    if binding is None:
        raise QueueConflictError("stopped retirement requires accepted declaration binding")
    journal = _RemoteAgentJournal(current.agent_root,
        expected_configuration_fingerprint=binding.immutable_fingerprint,
        expected_active_configuration_fingerprint=binding.active_fingerprint)
    try:
        require_unretired(current.agent_root)
        if read_agent_declaration_binding(current.agent_root, current.declaration_digest) != binding:
            raise QueueConflictError("stopped retirement declaration changed during ownership check")
        replay = journal.replayed_control_effect(control)
        if replay is not None:
            return replay
        p = control.promotion
        with journal._connection() as conn:
            delivery = conn.execute("SELECT request_json FROM agent_controls_local WHERE operation_id=?",
                                    (control.operation_id,)).fetchone()
            state = conn.execute("SELECT value FROM root_metadata WHERE key='availability_state'").fetchone()
        session = journal.session(control.expected_session_id)
        if (delivery is None or json.loads(delivery[0]) != control.value()
            or state is None or state[0] != "drained"
            or session.state is not AgentSessionState.ACTIVE
            or session.agent_id != control.agent_id
            or session.config_revision != control.expected_config_revision
            or journal.root_id != p["agent_root_id"]
            or binding.immutable_fingerprint != p["predecessor_immutable"]
            or binding.active_fingerprint != p["predecessor_active"]):
            raise QueueConflictError("stopped retirement delivery or native predecessor conflicts")
        execution, slurm = _retained_agent_owners(current)
        if _has_retained_agent_work(journal, execution, slurm) or journal.pending_poll() is not None:
            raise QueueConflictError("stopped retirement requires settled native work")
        candidate = Path(p.get("candidate_source", ""))
        if not candidate.is_absolute() or candidate.parent != current.source_path.parent or candidate == current.source_path:
            raise QueueConflictError("stopped retirement requires a separate sibling candidate")
        target_spec = read_agent_spec(candidate, env_file=current.environment_path)
        validate_retirement_specs(current, target_spec)
        target = load_outbound_agent_service_config(candidate, env_file=current.environment_path)
        _validate_target(target.client, control)
        _, _, authored, _ = _load_protected_config(candidate, env_file=current.environment_path)
        if (read_agent_spec(current.source_path, env_file=current.environment_path).declaration_digest != current.declaration_digest
            or read_agent_spec(candidate, env_file=current.environment_path).declaration_digest != target_spec.declaration_digest):
            raise QueueConflictError("stopped retirement source changed during qualification")
        source = {"path": str(current.source_path), "candidate": str(candidate),
            "environment": None if current.environment_path is None else str(current.environment_path),
            "before": current.source_path.read_text(), "after": json.dumps(authored, sort_keys=True)}
        return _apply_retained(journal, target.client, control, source)
    finally:
        journal.close()


def _apply_retained(journal, replacement, control, source):
    """Apply an already validated delivery using the native promotion journal."""
    from ._agent_session_journal import _AGENT_BINDING_FILE
    from ._agent_process_supervisor import AgentProcessSupervisorService, retained_supervisor_guard

    root = Path(replacement.agent_root)
    p = control.promotion
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
    # Promotion has proved empty native claims/deliveries and a clean supervisor
    # cut under the mutation gate. A previous UNKNOWN observation must not strand
    # this drained service; no capacity returns until the explicit resume.
    client._restart_with_retained_work = False
    client._service_recovery_admission = False


def recover(config: Any) -> Any:
    """Resolve accepted partial bindings before any service/supervisor can start.

    An IO-free AgentSpec can recover retained source publication even if the
    predecessor execution inputs disappeared. It must select the recorded source
    and environment; only the recorded target is fully qualified. With no pending
    promotion this function returns the input and grants no readiness exemption.
    """
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
        from .deployment import AgentSpec, load_outbound_agent_service_config

        if isinstance(config, AgentSpec):
            source = pending.get("source")
            if source is None or Path(source["path"]).resolve() != config.source_path:
                raise QueueConflictError("pending promotion does not own the selected agent source")
            if source["environment"] != (None if config.environment_path is None else str(config.environment_path)):
                raise QueueConflictError("pending promotion environment differs from selected source")
        if pending.get("source") is not None:
            source = pending["source"]
            target = load_outbound_agent_service_config(
                source["candidate"], env_file=source["environment"]
            )
            if target.client.agent_root != root:
                raise QueueConflictError("pending promotion candidate changed native root")
            config = replace(
                target.client, external_supervisor=getattr(config, "external_supervisor", False)
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


def publication_declaration(spec, control):
    """Read the source authorized by an exact pending or applied promotion.

    This is recovery evidence for a lost host receipt, not acceptance of an
    arbitrary authored edit. It neither completes a promotion nor probes data.
    """
    from .deployment import _load_protected_config
    from .retirement import read_agent_declaration_binding

    database = spec.agent_root / "control.sqlite"
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("BEGIN")
        pending = conn.execute("SELECT value FROM root_metadata WHERE key=?", (_PENDING,)).fetchone()
        row = conn.execute(
            "SELECT request_json,effect_json FROM agent_controls_local WHERE operation_id=?",
            (control.operation_id,),
        ).fetchone()
    if pending is not None:
        value = json.loads(pending[0])
        source = value.get("source")
        if (value["control"] != control.value() or source is None
            or Path(source["path"]).resolve() != spec.source_path
            or source["environment"] != (None if spec.environment_path is None else str(spec.environment_path))):
            raise QueueConflictError("pending source publication differs from retained control")
        return json.loads(source["after"])
    if row is None or row[1] is None:
        return None
    if json.loads(row[0]) != control.value():
        raise QueueConflictError("source publication control replay conflicts")
    if json.loads(row[1])["code"] != "applied":
        return None
    binding = read_agent_declaration_binding(spec.agent_root, spec.declaration_digest)
    if (binding is None or binding.root_id != control.promotion["agent_root_id"]
        or binding.immutable_fingerprint != control.promotion["target_immutable"]
        or binding.active_fingerprint != control.promotion["target_active"]):
        raise QueueConflictError("published source differs from accepted promotion target")
    return _load_protected_config(spec.source_path, env_file=spec.environment_path)[2]


def completed(root: Path, operation_id: str) -> bool:
    """Read the native local effect before restarting its changed supervisor."""
    return publication_state(root, operation_id) == "applied"


def promoted_capabilities(control: Any, previous: tuple[str, ...]) -> tuple[str, ...]:
    """Apply only the capability transition retained in an accepted promotion."""
    if control.promotion and control.promotion.get("enable_submitted_containers"):
        from .submitted_execution import SUBMITTED_CONTAINER_CAPABILITY
        return tuple(sorted({*previous, SUBMITTED_CONTAINER_CAPABILITY}))
    return previous

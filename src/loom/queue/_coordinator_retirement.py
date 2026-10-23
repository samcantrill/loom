"""Stage stopped coordinator conversion in the existing scheduling journal."""

import json
import os
from types import SimpleNamespace

from .errors import QueueConflictError


def stage_retirement(source, candidate, request, *, expected_root_id, env_file=None):
    """Retain one qualified scheduling replacement under stopped native ownership.

    The caller stages runtime and candidate files first and closes admission
    through the running operator protocol. This function neither publishes source
    nor starts services. The existing scheduling-reload startup recovery applies
    the exact recorded target after checked source publication. The old source
    is decoded without execution IO; only the candidate is fully qualified.
    """
    from .agent_sessions import ScopedAuthorizer
    from .deployment import (
        _coordinator_execution_declarations, _read_coordinator_declaration,
        load_coordinator_service_config, read_coordinator_scheduling_fingerprint,
        service_replacement_guard,
    )
    from .local_daemon import (
        CoordinatorSchedulingReload, LocalDaemon, LocalDaemonPrincipal, LocalDaemonRole,
        _public_operation_id, _scheduling_reload_receipt, _validate_deployment_binding,
        _validate_retired_coordinator_execution,
    )
    from ._maintenance import _read
    from .service_upgrade import inspect_service_settlement

    request = CoordinatorSchedulingReload.from_dict(request.to_dict())
    _public_operation_id(request.operation_id)
    if request.retirement is None:
        raise QueueConflictError("stopped conversion requires a retirement binding")
    source, _, before = _read_coordinator_declaration(source, env_file=env_file)
    candidate, _, after = _read_coordinator_declaration(candidate, env_file=env_file)
    if source == candidate or source.parent != candidate.parent:
        raise QueueConflictError("stopped conversion requires a separate sibling candidate")
    mutable = {"shared_roots", "preparation", "remote_profiles", "container_capabilities"}
    if before["local_agent"] is not None or {
        key: value for key, value in before.items() if key not in mutable
    } != {key: value for key, value in after.items() if key not in mutable}:
        raise QueueConflictError("stopped retirement changed unrelated coordinator declaration")
    profiles, capabilities, preparation = _coordinator_execution_declarations(before, source.parent, None)
    previous = SimpleNamespace(coordinator_shared_roots=before.get("shared_roots", {}),
        remote_profiles=profiles, container_capabilities=capabilities, preparation_policy=preparation)
    target = load_coordinator_service_config(candidate, env_file=env_file)
    _validate_retired_coordinator_execution(previous, target.daemon)
    predecessor = read_coordinator_scheduling_fingerprint(source, env_file=env_file)
    principal = LocalDaemonPrincipal(f"uid:{os.getuid()}", LocalDaemonRole.OPERATOR)
    authorizer = ScopedAuthorizer(target.daemon.agent_policy, verified_local_owner_subject=principal.subject)
    authorizer.require_operator(principal, "maintenance")
    authorizer.require_operator(principal, "scheduling_reload")
    encoded = json.dumps(request.to_dict(), sort_keys=True, separators=(",", ":"))
    with service_replacement_guard(target, expected_root_id):
        _validate_deployment_binding(target.daemon, coordinator_id=expected_root_id)
        # Recheck mutable source inputs after acquiring the existing role lock.
        if (_read_coordinator_declaration(source, env_file=env_file)[2] != before
            or _read_coordinator_declaration(candidate, env_file=env_file)[2] != after):
            raise QueueConflictError("stopped retirement source changed during qualification")
        native = LocalDaemon(target.daemon)
        with native._connection() as conn:
            prior = conn.execute("SELECT * FROM scheduling_reloads WHERE operation_id=?",
                                 (request.operation_id,)).fetchone()
            if prior is not None:
                if (prior["principal_id"] != principal.subject or prior["request_json"] != encoded
                    or prior["replacement_fingerprint"] != target.active_fingerprint):
                    raise QueueConflictError("stopped retirement replay conflicts")
                return _scheduling_reload_receipt(request.operation_id, prior)
            gate = _read(conn)
            binding = request.retirement
            if (gate["state"] != "closed" or gate["checks"]
                or gate["maintenance_id"] != binding["maintenance_id"]
                or gate["intent_digest"] != binding["maintenance_intent_digest"]
                or gate["revision"] != binding["expected_gate_revision"]):
                raise QueueConflictError("stopped retirement requires exact closed maintenance")
            scheduling = dict(conn.execute("SELECT key,value FROM daemon_metadata WHERE key IN "
                "('scheduling_fingerprint','scheduling_epoch')"))
            if (scheduling.get("scheduling_fingerprint") != predecessor
                or scheduling.get("scheduling_epoch") != request.expected_scheduling_epoch
                or conn.execute("SELECT 1 FROM scheduling_reloads WHERE state='applying'").fetchone()):
                raise QueueConflictError("stopped retirement scheduling predecessor conflicts")
        settlement = inspect_service_settlement(target.daemon.coordinator_root, expected_root_id=expected_root_id)
        if settlement.availability != "available" or not settlement.value.get("settled"):
            raise QueueConflictError("stopped retirement requires native settlement")
        native._record_scheduling_reload_intent(operation_id=request.operation_id,
            principal_id=principal.subject, request_json=encoded,
            replacement_fingerprint=target.active_fingerprint,
            assignment_payload_root_id=target.daemon.assignment_payload_root_id)
        return native._pending_scheduling_reload(request.operation_id)

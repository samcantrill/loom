"""Candidate check preparation before Fleet changes maintenance or services."""

from __future__ import annotations

from loom.fleet._host import environment, owner, role
from loom.fleet._timing import timed
from loom.queue.errors import QueueConflictError


@timed("check_preflight_capture")
def capture(request):
    """Capture the selected check through the target coordinator's native policy."""
    from loom.fleet._workload_host import _candidate_config
    from loom.queue.deployment import load_coordinator_service_config
    from loom.queue.preparation import (
        PrepareRunRequest, PreparationChildInput, capture_shared_input,
        _project_target_uri,
    )

    if role(request) != "coordinator" or owner(request)["owner"] != request["expected_root_id"]:
        raise QueueConflictError("check preflight coordinator identity differs")
    with _candidate_config(request, request["candidate_declaration"]) as temporary:
        service = load_coordinator_service_config(temporary, env_file=environment(request))
    policy = service.daemon.preparation_policy
    if policy is None:
        raise QueueConflictError("candidate check preparation is disabled")
    bindings = {}
    captures = {}
    for check, raw in request["checks"].items():
        selected = PrepareRunRequest.from_dict(raw)
        if selected.run_name is None:
            raise QueueConflictError("check preflight requires a named target")
        policy.select(selected)
        profile = policy.profiles[selected.preparation_profile]
        source = policy.source_roots[selected.source.root]
        if source.shared_snapshot_root is None:
            raise QueueConflictError("check preparation requires shared capture")
        capture_key = (selected.source, selected.config_path, selected.overlays)
        if capture_key not in captures:
            captures[capture_key] = capture_shared_input(
                selected, source_root=source.path, snapshot_root=source.shared_snapshot_root,
                owner_id=request["expected_root_id"],
            )
        receipt = captures[capture_key]
        project = None
        if profile.project_processor is not None:
            project = {
                "processor": dict(profile.project_processor),
                "target_run_uri": _project_target_uri(service.daemon.run_store_root, selected.run_name),
            }
        bindings[check] = PreparationChildInput(
            operation_id=selected.operation_id,
            preparation_profile=selected.preparation_profile,
            config_path=selected.config_path,
            input_receipt=receipt,
            profile_descriptor=profile.descriptor.to_dict(),
            overlays=selected.overlays,
            overrides=selected.overrides,
            run_options=selected.run_options,
            local_scope=profile.local_scope,
            project_preparation=project,
            shared_scope=profile.shared_scope,
        ).to_dict()
    return {"bindings": bindings}


@timed("check_preflight")
def prepare(request):
    """Exercise the actual candidate installation, even if not yet advertised."""
    from loom.fleet._workload_host import _candidate_config
    from loom.queue.deployment import load_outbound_agent_service_config
    from loom.queue._preparation_probe import probe_preparation
    from loom.queue.preparation import PreparationChildInput

    if role(request) != "agent" or owner(request)["owner"] != request["expected_root_id"]:
        raise QueueConflictError("check preflight agent identity differs")
    with _candidate_config(request, request["candidate_declaration"]) as temporary:
        service = load_outbound_agent_service_config(temporary, env_file=environment(request))
    results = {}
    for check, raw in request["bindings"].items():
        binding = PreparationChildInput.from_dict(raw)
        matches = [p for p in service.client.resident_profiles
                   if p.descriptor.to_dict() == dict(binding.profile_descriptor)]
        if len(matches) != 1:
            raise QueueConflictError("candidate check profile is unavailable or ambiguous")
        results[check] = dict(probe_preparation(
            matches[0].launch_profile, binding, agent_id=request["agent_id"],
        ))
    return {"checks": results}

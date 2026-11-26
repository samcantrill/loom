"""Candidate check preparation before Fleet changes maintenance or services."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from loom.serialization import PlainData

from loom.fleet._host import environment, owner, role
from loom.fleet._timing import timed
from loom.queue.errors import QueueConflictError


def _slurm_preparation_resources(options, components):
    """Use the child stage's native planners to bind canonical demand including units."""
    from loom.pipeline.resources import ResourceEntry, ResourceRequest
    from loom.pipeline.runtime.metadata import resolve_run_runtime
    from loom.pipeline.runtime.options import RunOptions
    from loom.pipeline.runtime.placement import StagePlacementPolicy, resolve_stage_placement

    runtime = resolve_run_runtime(RunOptions.from_dict(options), stage_ids=("prepare",))["prepare"]
    placement = resolve_stage_placement(
        authored=ResourceRequest({"cpu": ResourceEntry("cpu", 1, "count")}),
        runtime=cast(ResourceRequest, runtime.resources), resource_policy=runtime.resource_policy,
        policy=StagePlacementPolicy(), planners={p.resource_kind: p for p in components.planners},
    )
    return placement.resource_request.to_dict()


@timed("check_preflight_capture")
def capture(request):
    """Capture the selected check through the target coordinator's native policy."""
    from loom.fleet._workload_host import _candidate_config
    from loom.queue.deployment import load_coordinator_service_config
    from loom.queue.preparation import (
        PrepareRunRequest, PreparationChildInput, capture_shared_input,
        _project_target_uri,
    )
    from loom.queue.submitted_execution import SubmittedContainerCapability

    if role(request) != "coordinator" or owner(request)["owner"] != request["expected_root_id"]:
        raise QueueConflictError("check preflight coordinator identity differs")
    with _candidate_config(request, request["candidate_declaration"]) as temporary:
        service = load_coordinator_service_config(temporary, env_file=environment(request))
    policy = service.daemon.preparation_policy
    if policy is None:
        raise QueueConflictError("candidate check preparation is disabled")
    bindings = {}
    captures = {}
    preparation_resources = {}
    for check, raw in request["checks"].items():
        selected = PrepareRunRequest.from_dict(raw)
        if selected.run_name is None:
            raise QueueConflictError("check preflight requires a named target")
        profile = cast(Mapping[str, PlainData], policy.select(selected)["profile"])
        if profile.get("execution_route"):
            preparation_resources[check] = _slurm_preparation_resources(
                profile["runtime_options"], service.daemon.scheduling_components,
            )
        processor = (selected.execution.project_integration if selected.execution is not None
                     else cast(Mapping[str, PlainData] | None, profile.get("project_processor")))
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
        if processor is not None:
            project = {
                "processor": dict(processor),
                "target_run_uri": _project_target_uri(service.daemon.run_store_root, selected.run_name),
            }
        bindings[check] = PreparationChildInput(
            operation_id=selected.operation_id,
            preparation_profile=selected.preparation_profile,
            config_path=selected.config_path,
            input_receipt=receipt,
            profile_descriptor=None if selected.execution is not None else cast(Mapping[str, PlainData], profile["profile_descriptor"]),
            execution=selected.execution,
            container_capability=SubmittedContainerCapability.from_dict(profile["container_capability"]) if selected.execution is not None else None,
            overlays=selected.overlays,
            overrides=selected.overrides,
            run_options=selected.run_options,
            local_scope=cast(Mapping[str, PlainData] | None, profile.get("local_scope")),
            project_preparation=project,
            shared_scope=cast(Mapping[str, PlainData] | None, profile.get("shared_scope")),
        ).to_dict()
    return {"bindings": bindings, **({"preparation_resources": preparation_resources} if preparation_resources else {})}


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
    slurm_images = set()
    for check, raw in request["bindings"].items():
        binding = PreparationChildInput.from_dict(raw)
        if binding.execution is None:
            assert binding.profile_descriptor is not None
            descriptor = dict(binding.profile_descriptor)
            matches = [p for p in service.client.resident_profiles
                       if p.descriptor.to_dict() == descriptor]
            if len(matches) != 1:
                raise QueueConflictError("candidate check profile is unavailable or ambiguous")
            launch = matches[0].launch_profile
        else:
            policies = [p for p in service.client.container_policies
                        if p.capability == binding.container_capability
                        or (binding.container_capability is not None and p.capability.permits(binding.container_capability))]
            if request.get("slurm_profile"):
                from loom.queue._submitted_container_policy import SubmittedContainerPolicy

                for profile in service.client.slurm_profiles:
                    if profile.profile_id != request.get("slurm_profile") or profile.submitted_container_policy is None:
                        continue
                    policy = SubmittedContainerPolicy.from_dict(profile.submitted_container_policy)
                    if binding.container_capability is not None and policy.capability.permits(binding.container_capability):
                        # Installation and image binding are checked locally; the authorized
                        # preparation and workload probes below run in real allocations.
                        from loom.queue.submitted_execution import verify_submitted_image

                        image = binding.execution.image
                        root = cast(Mapping, policy.shared_roots[str(image.location["root_id"])])
                        image_key = (image.sha256, root["host_path"], image.location["path"])
                        if image_key not in slurm_images:
                            path = verify_submitted_image(image, policy.shared_roots)
                            if path.parent == Path(root["host_path"]):
                                raise QueueConflictError("candidate Slurm image requires a published directory")
                            slurm_images.add(image_key)
                        results[check] = {"slurm_profile": profile.profile_id,
                                          "fingerprint": profile.configuration_fingerprint,
                                          "image_sha256": binding.execution.image.sha256}
                        break
                if check not in results:
                    raise QueueConflictError("candidate Slurm check profile or image policy differs")
                continue
            if len(policies) != 1:
                raise QueueConflictError("candidate check container policy is unavailable or ambiguous")
            # The bounded probe creates its own workspace; this path supplies
            # the native launch's host context, never a new dataset root.
            assert service.client.agent_root is not None
            launch = policies[0].launch_profile(binding.execution, workspace=service.client.agent_root,
                                               selected_capability=binding.container_capability)
        results[check] = dict(probe_preparation(
            launch, binding, agent_id=request["agent_id"],
        ))
    return {"checks": results}

"""Demonstrate public authority-backed resource lease coordination."""

from __future__ import annotations

# ruff: noqa: E402

import os
from pathlib import Path
import sys

REPO_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "examples" / "support.py").is_file()
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from examples.support import start_authority_session
from loom.pipeline.stores import WorkspaceIdentity, create_authority_client


HERE = Path(__file__).resolve().parent


def main() -> None:
    output_root = Path(os.environ.get("LOOM_EXAMPLE_OUTPUT_ROOT", HERE))
    authority = start_authority_session(output_root)
    try:
        client = create_authority_client(authority.authority_config)
        workspace = client.create_workspace(
            WorkspaceIdentity(
                workspace_id=authority.workspace_id,
                root_uri=authority.workspace_root.resolve().as_uri(),
                metadata={"example": "operations.resource-leases"},
            ),
            request_id="workspace-create-1",
            service_generation=authority.generation,
        )
        limit = client.set_resource_limit(
            authority.workspace_id,
            "gpu",
            limit=1,
            request_id="resource-limit-1",
            service_generation=authority.generation,
        )
        first = client.acquire_resource_lease(
            authority.workspace_id,
            "gpu",
            owner_id="worker-1",
            amount=1,
            lease_ttl_seconds=30,
            request_id="resource-lease-1",
            service_generation=authority.generation,
        )
        blocked = client.acquire_resource_lease(
            authority.workspace_id,
            "gpu",
            owner_id="worker-2",
            amount=1,
            lease_ttl_seconds=30,
            request_id="resource-lease-2",
            service_generation=authority.generation,
        )
        if first.result is None or first.result.resource_lease is None:
            raise RuntimeError("expected an accepted resource lease")
        lease = first.result.resource_lease.lease
        released = client.release_coordination_lease(
            lease.lease_id,
            owner_id="worker-1",
            fencing_token=lease.fencing_token,
            request_id="resource-lease-release-1",
            service_generation=authority.generation,
            workspace_id=authority.workspace_id,
        )
        reacquired = client.acquire_resource_lease(
            authority.workspace_id,
            "gpu",
            owner_id="worker-2",
            amount=1,
            lease_ttl_seconds=30,
            request_id="resource-lease-3",
            service_generation=authority.generation,
        )
    finally:
        authority.stop()

    if workspace.result is None or workspace.result.workspace is None:
        raise RuntimeError("expected a created workspace identity")
    if limit.result is None or limit.result.counter is None:
        raise RuntimeError("expected a resource limit counter")
    if blocked.rejection is None:
        raise RuntimeError("expected the second resource request to be rejected")
    if released.result is None or released.result.lease is None:
        raise RuntimeError("expected a released lease result")
    if reacquired.result is None or reacquired.result.resource_lease is None:
        raise RuntimeError("expected the resource to be reacquired")

    print("resource_leases:")
    print(f"  counter_name: {limit.result.counter.counter_name}")
    print(f"  first_lease_kind: {first.result.resource_lease.lease.kind.value}")
    print(f"  blocked_category: {blocked.rejection.category.value}")
    print(f"  released_state: {released.result.lease.state.value}")
    print(f"  reacquired_kind: {reacquired.result.resource_lease.lease.kind.value}")


if __name__ == "__main__":
    main()

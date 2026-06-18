# Resource Lease Coordination

This example demonstrates the v10 public Python API for resource limits and
leases after starting authority through the public lifecycle commands.

It sets a named resource limit, acquires one lease, shows that a conflicting
second request is rejected, releases the first lease, and then acquires the
resource again.

## Public Python Surface

This example teaches `create_authority_client`, `WorkspaceIdentity`,
`set_resource_limit`, `acquire_resource_lease`, and
`release_coordination_lease`.

Run from the repository root:

```sh
uv run python examples/operations/resource-leases/run_resource_leases.py
```

# Managed Ready-Stage SLURM

## Workflow

Configure one protected SLURM profile on the coordinator, route the exact
stage to that profile, and use the managed operation detail/wait commands to
observe submission and release. The E2E uses the repository fake command
gateway, never a cluster.

## Variants

Use the remote journey for a resident agent or the local journey for embedded
execution.

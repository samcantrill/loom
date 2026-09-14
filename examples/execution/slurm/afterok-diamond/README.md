# Read-only dependency planning

## Workflow

Run the Python entrypoint in this directory to inspect the authored stage graph.
It invokes the pure planner without executing a stage, submitting a job or
rendering a continuation command. Native SLURM execution is documented in
[SLURM execution](../../../../docs/features/slurm.md).

## Variants

Use explicit native deployment selection for execution; graph-only inspection needs no service.

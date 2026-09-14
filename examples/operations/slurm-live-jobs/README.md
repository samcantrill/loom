# Connected SLURM operations

## Workflow

Configure the native coordinator and connected submit agent as described in
[SLURM execution](../../../docs/features/slurm.md). Use native run admission,
status, cancellation and reconnect operations. Inspect retained scheduler
observations in admission detail. Missing accounting and outage completion
require owner reconciliation; they do not authorize resubmission.

This is a site-dependent manual journey. No local example qualifies live SLURM.
Settle old jobs and retain their records before an incompatible version switch.

## Variants

Use explicit native deployment selection for execution; graph-only inspection needs no service.

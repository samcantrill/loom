# SLURM example coverage

The [native ready-stage journey](../../examples/operations/managed-ready-stage-slurm/README.md)
exercises fake-gateway submission, bootstrap, restart and release boundaries.
The graph examples inspect two-stage and diamond dependency plans without
submitting jobs or generating executable continuation commands.

Physical SLURM requires a configured connected submit agent, protected site
profile, shared result retention and qualified scheduler/accounting behavior.
See [SLURM execution](slurm.md) and the approved phase completion records for
actual qualification and unavailable cases. Synthetic tests are not live site
evidence. Allocation-native workers remain deferred.

Historical manifests, submitted-operation records and imported evidence retain
read-only consumers. They do not retain a scheduler controller or execution API.

| Example | Current consumer |
| --- | --- |
| execution.slurm.dry-run-basics | Two-stage graph planning |
| execution.slurm.afterok-diamond | Diamond graph planning |
| execution.slurm.live | Manual connected native SLURM |
| operations.slurm-live-jobs | Native admission scheduler observations |
| operations.submitted-status | Historical submitted record inspection |

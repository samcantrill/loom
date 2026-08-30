# Managed Remote Operations

## Workflow

Start the protected coordinator and outbound agent services, then use
`daemon-agents`, `daemon-agent`, and the guarded agent-control commands with
the returned session and revision fences. The focused E2E fixture supplies a
generated local CA and never needs a remote service.

## Variants

Use the embedded lifecycle for one machine, or the SLURM journey for an
explicit ready-stage route.

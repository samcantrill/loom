# Native local execution and reuse planning

`run_pipeline.py` executes four synthetic stages through a run-owned native
coordinator and installed agent. It then inspects the unchanged reuse plan and
a checksum-corruption branch repair plan through the pure planner, restoring
the original bytes afterward. It does not replay a successful admission as an
implicit retry. Artifact checksums and unaffected-branch reuse remain asserted.

## Public Python Surface

`loom.run`, native worker result records and the pure `plan_pipeline` owner.

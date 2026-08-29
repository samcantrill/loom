# NVIDIA Local GPU Pool Discovery

This dependency-free example uses a fake `nvidia-smi` command runner, so it is
safe to run on a CPU-only host. It demonstrates the explicit NVIDIA provider,
whole-GPU, two-share, and topology-grouped plans, then completes one managed
local grouped queue item.

```sh
uv run python examples/operations/nvidia-gpu-pool/run_nvidia_gpu_pool.py
```

For a real host, explicitly import
`NvidiaSmiGpuInventoryProvider` from `loom.queue.gpu.nvidia`, call
`discover()`, prepare the resulting plan with
`ensure_local_gpu_pool_limits(...)`, then build the managed-local runtime. A
share is only an integer scheduling-capacity unit: it does not isolate GPU
memory or compute. Topology grouping requires a complete supported
`nvidia-smi topo -m` matrix and never weakens to a fallback order.

The fake UUIDs and topology remain operator-local plan input. Ordinary queue
status and assignment evidence do not store device bindings, PCI addresses, or
the command output.

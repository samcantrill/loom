"""Explicit, import-light planning helpers for locally managed GPU pools."""

from .local import (
    LocalGpuDevice,
    LocalGpuInventory,
    LocalGpuInventoryProvider,
    LocalGpuPoolLayout,
    LocalGpuPoolPlan,
    build_managed_local_gpu_runtime,
    ensure_local_gpu_pool_limits,
    plan_local_gpu_pool,
    shares_per_gpu,
    whole_gpus,
)

__all__ = [
    "LocalGpuDevice",
    "LocalGpuInventory",
    "LocalGpuInventoryProvider",
    "LocalGpuPoolLayout",
    "LocalGpuPoolPlan",
    "build_managed_local_gpu_runtime",
    "ensure_local_gpu_pool_limits",
    "plan_local_gpu_pool",
    "shares_per_gpu",
    "whole_gpus",
]

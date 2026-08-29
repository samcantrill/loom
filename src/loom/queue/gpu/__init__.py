"""Explicit, import-light planning helpers for locally managed GPU pools."""

from .local import (
    LocalGpuDevice,
    LocalGpuInventory,
    LocalGpuInventoryProvider,
    LocalGpuLink,
    LocalGpuPoolLayout,
    LocalGpuPoolPlan,
    ensure_local_gpu_pool_limits,
    grouped,
    plan_local_gpu_pool,
    shares_per_gpu,
    whole_gpus,
)

__all__ = [
    "LocalGpuDevice",
    "LocalGpuInventory",
    "LocalGpuInventoryProvider",
    "LocalGpuLink",
    "LocalGpuPoolLayout",
    "LocalGpuPoolPlan",
    "ensure_local_gpu_pool_limits",
    "grouped",
    "plan_local_gpu_pool",
    "shares_per_gpu",
    "whole_gpus",
]

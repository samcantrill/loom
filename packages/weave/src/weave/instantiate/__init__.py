"""Target instantiation helpers."""

from __future__ import annotations

from .targets import import_target
from .recursive import instantiate

__all__ = ["import_target", "instantiate"]

"""Target instantiation helpers."""

from __future__ import annotations

import sys

from .targets import import_target
from .recursive import instantiate

_parent_name = __package__.rsplit(".", 1)[0]
_parent = sys.modules.get(_parent_name)
if _parent is not None:
    _parent.instantiate = instantiate

__all__ = ["import_target", "instantiate"]

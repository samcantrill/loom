"""Executor protocol for pipeline stages."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Executor(Protocol):
    name: str

    def execute(self, request: object) -> object: ...


__all__ = ["Executor"]

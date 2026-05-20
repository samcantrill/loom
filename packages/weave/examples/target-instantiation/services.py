"""Small targets used by the target instantiation example."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Prefixer:
    prefix: str

    def render(self, value: str) -> str:
        return f"{self.prefix}{value}"


@dataclass(frozen=True, slots=True)
class Formatter:
    prefixer: Prefixer
    suffix: str = ""

    def render(self, value: str) -> str:
        return f"{self.prefixer.render(value)}{self.suffix}"


def join_values(values: Sequence[str], separator: str = ", ") -> str:
    return separator.join(values)


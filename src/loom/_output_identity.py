"""Lightweight exact native output identity shared by authority and queries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class QueryError(ValueError):
    """Invalid or unsupported query; never an empty search result."""


@dataclass(frozen=True)
class OutputLocator:
    """Address an original producer's immutable commit, without granting access."""

    run_uri: str
    stage_name: str
    commit_id: str
    output_name: str

    def __post_init__(self) -> None:
        for value in self.to_dict().values():
            if not isinstance(value, str) or not value or len(value.encode()) > 4096:
                raise QueryError(
                    "output locator fields must be bounded nonempty strings"
                )

    def to_dict(self) -> dict[str, str]:
        return {
            name: getattr(self, name)
            for name in ("run_uri", "stage_name", "commit_id", "output_name")
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OutputLocator:
        if not isinstance(value, Mapping) or set(value) != {
            "run_uri",
            "stage_name",
            "commit_id",
            "output_name",
        }:
            raise QueryError("invalid output locator")
        return cls(**value)

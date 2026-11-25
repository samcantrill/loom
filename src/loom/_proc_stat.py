"""Decode Linux process birth and state fields independently of the task name."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessStat:
    state: str
    start_ticks: str
    parent: int
    group: int
    session: int


def parse_process_stat(raw: bytes) -> ProcessStat:
    # comm may contain whitespace, closing parentheses, and non-UTF-8 bytes.
    prefix, separator, tail = raw.rpartition(b")")
    fields = tail.split()
    if not separator or b"(" not in prefix or len(fields) < 20:
        raise ValueError("incomplete Linux process stat record")
    return ProcessStat(
        state=fields[0].decode("ascii"), start_ticks=fields[19].decode("ascii"),
        parent=int(fields[1]), group=int(fields[2]), session=int(fields[3]),
    )


def read_process_stat(pid: int) -> ProcessStat:
    return parse_process_stat(Path(f"/proc/{pid}/stat").read_bytes())

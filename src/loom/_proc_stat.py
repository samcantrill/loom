"""Decode Linux process birth and state fields independently of the task name."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessStat:
    state: str
    start_ticks: str


def parse_process_stat(raw: bytes) -> ProcessStat:
    # comm may contain whitespace, closing parentheses, and non-UTF-8 bytes.
    prefix, separator, tail = raw.rpartition(b")")
    fields = tail.split()
    if not separator or b"(" not in prefix or len(fields) < 20:
        raise ValueError("incomplete Linux process stat record")
    return ProcessStat(fields[0].decode("ascii"), fields[19].decode("ascii"))


def read_process_stat(pid: int) -> ProcessStat:
    return parse_process_stat(Path(f"/proc/{pid}/stat").read_bytes())

"""Slurm start-request negotiation and intended execution identity."""

import hashlib


SLURM_REPLAYABLE_START_CAPABILITY = "slurm-replayable-start-v1"


def intended_execution_id(assignment_id: str, incarnation: str) -> str:
    """Name the authorized root; this does not assert that it started."""
    return "slurm-root-" + hashlib.sha256(
        (assignment_id + "\0" + incarnation).encode()
    ).hexdigest()

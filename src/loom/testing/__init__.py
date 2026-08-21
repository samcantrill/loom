"""Opt-in, dependency-light conformance checks for downstream extensions.

The checks execute caller-provided objects and samples.  They are test support
for trusted project code, not runtime admission, discovery, or isolation.
"""

from .checks import (
    check_codec_contract,
    check_event_sink_contract,
    check_executor_contract,
    check_resource_validator_contract,
)
from .reports import ContractFinding, ContractReport

__all__ = [
    "ContractFinding",
    "ContractReport",
    "check_codec_contract",
    "check_event_sink_contract",
    "check_executor_contract",
    "check_resource_validator_contract",
]

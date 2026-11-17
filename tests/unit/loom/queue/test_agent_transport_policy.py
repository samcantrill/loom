"""Transport expiry preserves uncertain outcomes; it is not workload timeout."""

from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace
from typing import Any, cast

import pytest

from loom.queue._agent_transport_policy import AgentTransportPolicy, parse_transport_policy
from loom.queue.agent_session_transport import AgentTlsClientConfig, _exchange_agent_request, _IndeterminateAgentProtocolError
from loom.queue.errors import QueueConfigError
from loom.queue._managed_local import _ManagedApplicationSuspended


@pytest.mark.parametrize("value", [True, 0, -1, float("inf"), float("nan"), 301])
def test_transport_policy_rejects_nonfinite_or_unbounded_deadlines(value):
    with pytest.raises(QueueConfigError):
        AgentTransportPolicy(response_timeout_seconds=value)


def test_transport_policy_requires_distinct_complete_budgets():
    with pytest.raises(QueueConfigError):
        parse_transport_policy({"timeout_seconds": 10})
    policy = parse_transport_policy({"connect_timeout_seconds": 2, "response_timeout_seconds": 9})
    assert policy.to_dict() == {"connect_timeout_seconds": 2, "response_timeout_seconds": 9}


@pytest.mark.parametrize("service_stop", [False, True])
def test_header_wait_interruption_preserves_the_exact_request(service_stop):
    stopped = Event()
    cancel = Event()
    requests = []

    class Connection:
        sock = SimpleNamespace(settimeout=lambda _: None, shutdown=lambda _: stopped.set())

        def request(self, *args, **kwargs):
            requests.append((args, kwargs))

        def getresponse(self):
            # A peer can send just enough header bytes to defeat socket-idle
            # timeouts. The total budget must still interrupt this read.
            if service_stop:
                cancel.set()
            assert stopped.wait(2)
            raise OSError("socket shut down at deadline")

        def close(self):
            stopped.set()

    config = AgentTlsClientConfig(
        "https://localhost:7446", Path("ca"), Path("cert"), Path("key"),
        transport_policy=AgentTransportPolicy(1, 10 if service_stop else 0.05),
    )
    started = monotonic()
    expected = _ManagedApplicationSuspended if service_stop else _IndeterminateAgentProtocolError
    with pytest.raises(expected):
        _exchange_agent_request(config, "poll" if service_stop else "slurm_work",
            b'{"exact":"evidence"}', "agent", cast(Any, Connection()), True,
            cancel_requested=cancel.is_set if service_stop else None)
    assert monotonic() - started < 1
    assert len(requests) == 1
    assert requests[0][1]["body"] == b'{"exact":"evidence"}'

"""Session-scoped hints for pending agent polls."""

from ._service_signals import _ChangeSignal, _KeyedWaiters


class _PollSignal(_ChangeSignal):
    """Session-scoped hint, owned by the pending work-poll subscriptions."""


class _PollWaiters(_KeyedWaiters):
    signal_type = _PollSignal

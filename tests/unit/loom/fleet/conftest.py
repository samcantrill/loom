"""Revision-conditional maintenance gate for fleet orchestration tests."""

from copy import deepcopy
import time

import pytest


class CheckGate:
    def __init__(self):
        self.checks = {}
        self.revision = 1

    def observe(self, *, deadline):
        assert deadline > time.monotonic()
        return {"checks": deepcopy(self.checks), "revision": self.revision}

    def authorize(self, key, action, authorization, *, deadline, revision):
        assert action == "authorize" and key.startswith("authorize-")
        assert revision == self.revision and deadline > time.monotonic()
        identity = key.removeprefix("authorize-")
        assert identity not in self.checks
        self.checks[identity] = authorization
        self.revision += 1
        return {"gate": self.observe(deadline=deadline)}


@pytest.fixture
def check_gate():
    return CheckGate()

"""Fixtures for the identity tests.

Every test enters through Seam A — the surface an external buyer agent uses. It
generates a real keypair, registers it, and sends signed requests. Nothing reaches
into the registry table or builds an identity by hand, because an external agent
could not do either.
"""

from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.identity import AgentRegistry, IdentityCheck


@pytest.fixture
def registry(pool: ConnectionPool, trail: AuditTrail) -> AgentRegistry:
    return AgentRegistry(pool, trail)


@pytest.fixture
def identity_check(registry: AgentRegistry, trail: AuditTrail) -> IdentityCheck:
    return IdentityCheck(registry, trail)

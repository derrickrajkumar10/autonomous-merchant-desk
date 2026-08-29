"""Fixtures for the mandate tests.

Every test enters the way the real thing does: a principal generates a keypair in a
wallet, an agent generates its own and registers, the Desk enrols the principal, and
the wallet signs a mandate naming that agent. Nothing writes a mandate by hand or
reaches into a table, because a buyer agent could do neither.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.identity import AgentIdentity, AgentRegistry, PrincipalDirectory
from desk.mandate import MandateCheck
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

PRINCIPAL_ID = "principal-asha"

#: One hour, which is roughly the "smallest value that lets the agent finish the task"
#: AP2 recommends, and long enough that a slow test does not expire mid-run.
AN_HOUR = 3600


@pytest.fixture
def wallet() -> PrincipalKeypair:
    return PrincipalKeypair.generate()


@pytest.fixture
def principals(pool: ConnectionPool, wallet: PrincipalKeypair) -> PrincipalDirectory:
    directory = PrincipalDirectory(pool)
    directory.enrol(principal_id=PRINCIPAL_ID, public_key=wallet.public_key)
    return directory


@pytest.fixture
def mandate_check(principals: PrincipalDirectory, trail: AuditTrail) -> MandateCheck:
    return MandateCheck(principals, trail)


@pytest.fixture
def agent() -> AgentKeypair:
    return AgentKeypair.generate()


@pytest.fixture
def identity(pool: ConnectionPool, trail: AuditTrail, agent: AgentKeypair) -> AgentIdentity:
    """The agent as check 1 would hand it to check 2: registered, and authenticated."""
    return AgentRegistry(pool, trail).register(
        public_key=agent.public_key, principal_id=PRINCIPAL_ID
    )


def line_items(sku: str = "SKU-COFFEE-1KG", quantity: int = 2) -> dict[str, Any]:
    """The one constraint AP2 makes mandatory on an open Checkout Mandate."""
    return {
        "type": "checkout.line_items",
        "items": [
            {
                "id": "beans",
                "acceptable_items": [{"id": sku, "title": "Single origin beans, 1kg"}],
                "quantity": quantity,
            }
        ],
    }


def a_mandate(
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    *,
    principal_id: str = PRINCIPAL_ID,
    lifetime: int = AN_HOUR,
    constraints: list[Mapping[str, Any]] | None = None,
) -> str:
    """A mandate this principal signed, binding this agent, valid for ``lifetime``.

    A negative lifetime produces one that has already expired, which is how the expiry
    test avoids waiting for the clock.
    """
    now = int(time.time())
    return wallet.sign_open_checkout_mandate(
        principal_id=principal_id,
        agent_key=agent.public_key,
        constraints=[line_items()] if constraints is None else constraints,
        issued_at=now,
        expires_at=now + lifetime,
    )

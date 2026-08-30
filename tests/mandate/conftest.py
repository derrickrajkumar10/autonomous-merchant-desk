"""Mandate-building helpers for the mandate and spend suites.

The cast — a principal with a wallet, an agent that has registered, the Desk holding
the principal's key — lives in the root ``conftest``. What is here is the other half:
how those characters produce a *mandate*, since AP2 v0.2 has two of them and check 3
needs both.

Every mandate is signed by a real wallet with a real key. Nothing is stubbed, because
the thing under test is a signature.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from tests.conftest import AN_HOUR, PRINCIPAL_ID
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

__all__ = [
    "AN_HOUR",
    "PRINCIPAL_ID",
    "a_mandate",
    "a_payment_mandate",
    "budget",
    "execution_window",
    "line_items",
]


def line_items(
    sku: str = "SKU-COFFEE-1KG", quantity: int = 2, also: str | None = None
) -> dict[str, Any]:
    """The one constraint AP2 makes mandatory on an open Checkout Mandate.

    ``also`` adds a second acceptable item, which is how a principal authorises more than
    one thing in a single constraint. The negotiation suite needs it: a bundle companion
    has to be something the mandate names, so a mandate naming one sku can never produce
    one.
    """
    acceptable = [{"id": sku, "title": "Single origin beans, 1kg"}]
    if also is not None:
        acceptable.append({"id": also, "title": "Something else the principal allowed"})
    return {
        "type": "checkout.line_items",
        "items": [{"id": "beans", "acceptable_items": acceptable, "quantity": quantity}],
    }


def budget(maximum: str = "2000.00", currency: str = "INR") -> dict[str, Any]:
    """A payment.budget ceiling, written the way AP2's own example writes one.

    ``maximum`` is a string here and a JSON *number* on the wire, which is what AP2
    types it as -- so the float is the serialiser's, for the length of one
    ``json.dumps``, and never the Desk's: mandate claims are parsed back with
    ``parse_float=Decimal``.
    """
    return {"type": "payment.budget", "max": float(Decimal(maximum)), "currency": currency}


def execution_window(not_before: str | None = None, not_after: str | None = None) -> dict[str, Any]:
    """A payment.execution_date window. Either end may be left open."""
    constraint: dict[str, Any] = {"type": "payment.execution_date"}
    if not_before is not None:
        constraint["not_before"] = not_before
    if not_after is not None:
        constraint["not_after"] = not_after
    return constraint


def a_mandate(
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    *,
    principal_id: str = PRINCIPAL_ID,
    lifetime: int = AN_HOUR,
    constraints: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """An open Checkout Mandate this principal signed, binding this agent.

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


def a_payment_mandate(
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    for_checkout: str,
    *,
    principal_id: str = PRINCIPAL_ID,
    lifetime: int = AN_HOUR,
    constraints: Sequence[Mapping[str, Any]] | None = None,
    execution_date: str | None = None,
) -> str:
    """The open Payment Mandate that goes with ``for_checkout``.

    Defaults to a ceiling and nothing else, which is the smallest mandate check 3 will
    accept: the ``payment.reference`` the wallet adds itself, plus a ``payment.budget``,
    since a mandate setting no ceiling is refused.
    """
    now = int(time.time())
    return wallet.sign_open_payment_mandate(
        principal_id=principal_id,
        agent_key=agent.public_key,
        for_checkout=for_checkout,
        constraints=[budget()] if constraints is None else constraints,
        issued_at=now,
        expires_at=now + lifetime,
        execution_date=execution_date,
    )

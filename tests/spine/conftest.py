"""Fixtures for the spine, which is the only seam this suite drives.

Every test here does what a stranger's buyer agent can do and nothing else: build two
mandates in a wallet, present them, sign a request, hand the string to
``TrustSpine.receive``, and then read the audit trail. Nothing calls a check directly,
because a test that reached inside the sequence could not catch the ordering defects
that matter most -- a check running after a refusal, or two of them swapped.

``a_request`` below is deliberately one function with a long signature rather than nine
builders. Every one of the nine refusals is the happy path with **one** argument
changed, and having that visible in one place is the point: it is how a reader sees
that the cases differ only in the thing each check is supposed to notice.

The freshness policy is stated rather than read from the environment, so a run does not
depend on what happens to be set in the shell.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditEntry, AuditTrail, ReasonCode
from desk.freshness import FreshnessCheck, FreshnessPolicy, NonceStore
from desk.identity import AgentIdentity, AgentRegistry, IdentityCheck, PrincipalDirectory
from desk.mandate import MandateCheck
from desk.spend import BudgetAccumulator, SpendAuthorityCheck
from desk.spine import AMOUNT, CHECKOUT, CURRENCY, ITEM_ID, PAYMENT, TrustSpine
from tests.conftest import AN_HOUR, PRINCIPAL_ID
from tests.freshness.conftest import DESK, SKEW, WINDOW
from tests.mandate.conftest import budget, line_items
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

#: What the principal authorised the purchase of, and what a well-behaved request asks
#: for. A second SKU is all it takes to be asking for something else entirely.
COFFEE = "SKU-COFFEE-1KG"
LAPTOP = "SKU-LAPTOP-14"

#: The ceiling on the Payment Mandate, and an asking price comfortably inside it.
CEILING = "2000.00"
ASKING = "750.00"


@pytest.fixture
def policy() -> FreshnessPolicy:
    return FreshnessPolicy(window=WINDOW, clock_skew=SKEW, audience=DESK)


@pytest.fixture
def spine(
    pool: ConnectionPool,
    trail: AuditTrail,
    policy: FreshnessPolicy,
    principals: PrincipalDirectory,
) -> TrustSpine:
    """The Desk's deterministic half, wired the way a running Desk wires it.

    Five collaborators and one method. The wiring is the ticket: each check was built
    and tested on its own, and what is new here is only the order they are called in.
    """
    return TrustSpine(
        IdentityCheck(AgentRegistry(pool, trail), trail),
        MandateCheck(principals, trail),
        SpendAuthorityCheck(BudgetAccumulator(pool), trail),
        FreshnessCheck(NonceStore(pool), trail, policy),
        trail,
    )


def a_request(
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    item_id: str = COFFEE,
    amount: Any = ASKING,
    currency: Any = "INR",
    sku: str = COFFEE,
    also: str | None = None,
    ceiling: str = CEILING,
    ceiling_currency: str = "INR",
    lifetime: int = AN_HOUR,
    binds: AgentKeypair | None = None,
    issued_by: PrincipalKeypair | None = None,
    signed_by: AgentKeypair | None = None,
    claiming: str | None = None,
    execution: Mapping[str, Any] | None = None,
    execution_date: str | None = None,
    pay_for: str | None = None,
    hop_age: int = 0,
    checkout_nonce: str | None = None,
    payment_nonce: str | None = None,
    audience: str = DESK,
    raw_amount: str | None = None,
    enquiry: str | None = None,
    body: Mapping[str, Any] | None = None,
) -> str:
    """One signed purchase request, defaulting to a wholly valid one.

    Each argument is the single change that reaches one refusal, and they are named for
    the lie they tell rather than for the mechanism: ``issued_by`` signs the mandates
    with somebody else's key, ``binds`` binds them to somebody else's agent, ``signed_by``
    signs the *request* with a key the Desk never registered while ``claiming`` still
    names ours, ``hop_age`` backdates the proof of possession.

    ``also`` puts a second acceptable item in the Checkout Mandate, which is what a
    principal authorising two things looks like.

    ``body`` replaces the request body outright, which is how a request that is validly
    signed and still not a purchase request gets built. Nothing else about the request
    changes; check 1 passes it, and what happens next is the spine's reading of it.

    ``enquiry`` is free text on the request. The spine never reads it -- only check 5
    does -- so it changes nothing about which checks pass; it is here so a check-5 test
    can drive a request with a message on it through the real front door.

    ``raw_amount`` writes the price into the JSON as written, unquoted, which is the only
    way to put an exact decimal *number* on the wire from Python: ``json.dumps`` cannot
    serialise a ``Decimal``, and routing one through a float to reach the encoder is the
    precise loss the Desk's own parsing exists to avoid.
    """
    now = int(time.time())
    issuer = wallet if issued_by is None else issued_by
    bound = (agent if binds is None else binds).public_key
    constraints: list[Mapping[str, Any]] = [budget(ceiling, ceiling_currency)]
    if execution is not None:
        constraints.append(execution)

    checkout_mandate = issuer.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=bound,
        constraints=[line_items(sku=sku, also=also)],
        issued_at=now - hop_age,
        expires_at=now + lifetime,
    )
    payment_mandate = issuer.sign_open_payment_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=bound,
        for_checkout=checkout_mandate if pay_for is None else pay_for,
        constraints=constraints,
        issued_at=now - hop_age,
        expires_at=now + lifetime,
        execution_date=execution_date,
    )

    # Presented by the agent that is sending, always -- a mandate bound to somebody else
    # is exactly what a stolen one looks like, and the Desk has to be handed one to
    # refuse it.
    presented_checkout = agent.present(
        checkout_mandate, audience=audience, nonce=checkout_nonce, issued_at=now - hop_age
    )
    presented_payment = agent.present(
        payment_mandate, audience=audience, nonce=payment_nonce, issued_at=now - hop_age
    )

    sender = agent if signed_by is None else signed_by
    agent_id = identity.agent_id if claiming is None else claiming
    if body is not None:
        return sender.sign_request(body, agent_id=agent_id)
    if raw_amount is not None:
        written = ", ".join(
            [
                f"{json.dumps(CHECKOUT)}: {json.dumps(presented_checkout)}",
                f"{json.dumps(PAYMENT)}: {json.dumps(presented_payment)}",
                f"{json.dumps(ITEM_ID)}: {json.dumps(item_id)}",
                f"{json.dumps(AMOUNT)}: {raw_amount}",
                f"{json.dumps(CURRENCY)}: {json.dumps(currency)}",
            ]
        )
        return sender.sign(("{" + written + "}").encode("utf-8"), agent_id=agent_id)
    return sender.request_purchase(
        agent_id=agent_id,
        checkout=presented_checkout,
        payment=presented_payment,
        item_id=item_id,
        amount=amount,
        currency=currency,
        enquiry=enquiry,
    )


def checks_recorded(trail: AuditTrail) -> list[int]:
    """Which checks left an entry, in the order they left one.

    Read from the trail rather than from the outcome, because the outcome is what the
    spine says it did and the trail is what actually happened. One agent per test, so
    every check entry in the table belongs to the run under test.
    """
    return [int(entry.payload["check"]) for entry in _check_entries(trail)]


def reasons_recorded(trail: AuditTrail) -> list[ReasonCode | None]:
    """The reason code on each check entry, in order. ``None`` where a check passed."""
    return [entry.reason_code for entry in _check_entries(trail)]


def _check_entries(trail: AuditTrail) -> list[AuditEntry]:
    entries: Sequence[AuditEntry] = trail.query()
    return [entry for entry in entries if "check" in entry.payload]

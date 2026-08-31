"""What the settlement suite needs: a real deal, and a rail it can make behave.

Every test here reaches settlement the way a running Desk does -- two mandates signed
in a wallet, a request signed with an agent key, four checks, a negotiation that closes.
Nothing constructs a closed Checkout Mandate by hand, because the artefact settlement
charges against is the one the Desk actually signed, and a hand-built one would let a
test pass against a mandate the real path could never produce.

The single substitution is the payment rail. It is substituted because the correctness
core of this ticket is what the Desk does when a charge *does not* complete, and a suite
that could only reach that case by having somebody else's server be down would not test
it. ``StubRail`` is what a rail looks like from the Desk's side and nothing more: it
takes a charge and answers. Its answers are the ones the boundary allows, so a test that
passes against it is a test about the Desk rather than about the stub.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.catalogue import Catalogue
from desk.catalogue import install_schema as install_catalogue_schema
from desk.freshness import FreshnessCheck, FreshnessPolicy, NonceStore
from desk.identity import (
    AgentIdentity,
    AgentRegistry,
    DeskKeyVault,
    IdentityCheck,
    PrincipalDirectory,
)
from desk.mandate import (
    MandateCheck,
    MandateOutcome,
    OpenCheckoutMandate,
    OpenPaymentMandate,
)
from desk.negotiation import Ask, Desk, DeskMessage, TrustTier
from desk.settlement import Charge, RailCharge, Receipts, Settled, Settlement
from desk.spend import BudgetAccumulator, Money, SpendAuthorityCheck
from desk.spine import SpineOutcome, TrustSpine
from tests.conftest import AN_HOUR, PRINCIPAL_ID
from tests.freshness.conftest import DESK, SKEW, WINDOW
from tests.mandate.conftest import budget, line_items
from tests.spine.conftest import a_request
from world.agents.keys import AgentKeypair
from world.storefront import COFFEE, PRODUCTS, TERMS
from world.wallet import PrincipalKeypair

__all__ = ["COFFEE", "PRODUCTS", "TERMS"]

#: A ceiling well clear of the deals settled here. Check 3's refusals are ticket 04's;
#: the one test that wants the ceiling in the way sets its own.
CEILING = "200000.00"

#: What the storefront sells a kilogram of beans for, inside the floor, two at a time.
ASKING = "750.00"


def rupees(amount: str) -> Money:
    return Money.of(amount, "INR")


class StubRail:
    """A payment rail whose answer the test chooses. Satisfies ``PaymentRail``.

    Records what it was asked for, so a test can assert the Desk asked for the amount
    that was agreed rather than merely that a charge happened.
    """

    def __init__(self, answer: RailCharge | None = None) -> None:
        self.answer = answer if answer is not None else completed()
        self.asked: list[Charge] = []

    def charge(self, charge: Charge) -> RailCharge:
        self.asked.append(charge)
        return self.answer


class UnreachableRail:
    """A rail that raises rather than answering, which is a rail nobody can reach.

    Distinct from a charge that did not complete: there, the rail said no. Here the Desk
    does not know what happened, which is the case the attempt entry exists for.
    """

    def __init__(self) -> None:
        self.asked: list[Charge] = []

    def charge(self, charge: Charge) -> RailCharge:
        self.asked.append(charge)
        raise ConnectionError("the rail did not answer")


def completed(
    charge_id: str = "pay_TESTMODE0000001", status: str = "captured"
) -> RailCharge:
    """A rail that took the money, worded the way Razorpay words it."""
    return RailCharge(
        rail="razorpay",
        completed=True,
        status=status,
        charge_id=charge_id,
        order_id="order_TESTMODE00001",
    )


def declined(status: str = "failed") -> RailCharge:
    """A rail that did not. An ordinary outcome, and the one the ticket turns on."""
    return RailCharge(
        rail="razorpay",
        completed=False,
        status=status,
        order_id="order_TESTMODE00001",
        detail="the card was declined by the issuer",
    )


@pytest.fixture
def storefront(pool: ConnectionPool) -> Iterator[Catalogue]:
    with pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS product")
        install_catalogue_schema(conn)
    catalogue = Catalogue(pool)
    catalogue.seed(PRODUCTS)
    yield catalogue


@pytest.fixture
def vault(pool: ConnectionPool) -> DeskKeyVault:
    """The Desk's own keys, from the store they will be read back out of.

    Not ``DeskKeypair.generate()``: the claim this ticket makes is that a receipt stays
    verifiable against a published key, and a key that exists only inside the test
    process could not fail the way a real one would.
    """
    return DeskKeyVault(pool)


@pytest.fixture
def receipts(pool: ConnectionPool, vault: DeskKeyVault) -> Receipts:
    """The store, wired to the same published key a stranger would be handed."""
    return Receipts(pool, vault.published().receipt)


@pytest.fixture
def rail() -> StubRail:
    return StubRail()


@pytest.fixture
def spine(pool: ConnectionPool, trail: AuditTrail, principals: PrincipalDirectory) -> TrustSpine:
    return TrustSpine(
        IdentityCheck(AgentRegistry(pool, trail), trail),
        MandateCheck(principals, trail),
        SpendAuthorityCheck(BudgetAccumulator(pool), trail),
        FreshnessCheck(
            NonceStore(pool), trail, FreshnessPolicy(window=WINDOW, clock_skew=SKEW, audience=DESK)
        ),
        trail,
    )


@pytest.fixture
def selling(storefront: Catalogue, trail: AuditTrail, vault: DeskKeyVault) -> Desk:
    return Desk(storefront, TERMS, trail, vault.mandate_key())


@pytest.fixture
def settlement(
    rail: StubRail,
    pool: ConnectionPool,
    receipts: Receipts,
    trail: AuditTrail,
    vault: DeskKeyVault,
) -> Settlement:
    return Settlement(
        rail,
        BudgetAccumulator(pool),
        receipts,
        trail,
        pool,
        receipt_key=vault.receipt_key(),
        mandate_key=vault.mandate_key().public_key,
    )


@dataclass(frozen=True)
class Authorised:
    """One request that cleared the four checks, with its two mandates as check 2 left
    them.

    The narrowing is the point. ``SpineOutcome`` types its mandates optional because a
    refused request carries none, and every settlement test would otherwise open with the
    same two assertions before it could say anything. Making them non-optional once, here,
    is what keeps the tests about settlement.

    ``outcome`` is kept whole beside them because ``Desk.open`` takes it: a negotiation
    opens on the request as the spine reported it, not on the two mandates alone.
    """

    outcome: SpineOutcome
    checkout: MandateOutcome[OpenCheckoutMandate]
    payment: MandateOutcome[OpenPaymentMandate]


@dataclass(frozen=True)
class Agreed:
    """A closed deal and the authorisation it was negotiated under.

    Everything ``Settlement.settle`` needs, in the shape the real caller has it in: the
    signed artefact, and the two verified mandates behind it.
    """

    authorised: Authorised
    reply: DeskMessage
    closed_mandate: str

    @property
    def checkout(self) -> MandateOutcome[OpenCheckoutMandate]:
        return self.authorised.checkout

    @property
    def payment(self) -> MandateOutcome[OpenPaymentMandate]:
        return self.authorised.payment


def presented(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    ceiling: str = CEILING,
) -> Authorised:
    """One request that really went through the four checks, ready to negotiate on."""
    outcome = spine.receive(
        a_request(
            wallet,
            agent,
            identity,
            item_id=COFFEE.sku,
            sku=COFFEE.sku,
            amount="1.00",
            ceiling=ceiling,
        )
    )
    assert outcome.passed, outcome.reason_code
    assert outcome.checkout is not None and outcome.payment is not None
    return Authorised(outcome=outcome, checkout=outcome.checkout, payment=outcome.payment)


def closed_deal(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    quantity: int = 2,
    ceiling: str = CEILING,
) -> Agreed:
    """A whole deal, from signed request to agreement, with nothing stubbed but the rail.

    Reaches the closed Checkout Mandate the way the Desk does and no other way, so a test
    that passes here could not pass against a mandate the real path cannot produce.
    """
    authorised = presented(spine, wallet, agent, identity, ceiling=ceiling)
    reply = selling.open(authorised.outcome, tier=TrustTier.NEW).receive(
        Ask(sku=COFFEE.sku, quantity=quantity, target_unit_price=rupees(ASKING))
    )
    assert reply.closed and reply.closed_mandate is not None, reply.move
    return Agreed(authorised=authorised, reply=reply, closed_mandate=reply.closed_mandate)


def two_deals_on_one_mandate(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    quantities: tuple[int, int] = (2, 3),
    ceiling: str = CEILING,
) -> tuple[Agreed, Agreed]:
    """Two closed deals drawn against **the same pair of mandates**.

    ``a_request`` signs a fresh pair every call, which is right for almost everything and
    wrong for the one property the accumulator exists to hold -- that a *second* deal
    under *one* authorisation adds to the running total rather than starting it again. So
    the mandates are signed once here and presented twice.

    Twice with different nonces, because that is the only honest way to do it: check 4
    refuses a key-binding hop it has already honoured, so a genuine second presentation
    of the same mandate carries a fresh nonce. Reusing the first one would be a replay and
    the Desk would be right to refuse it.
    """
    now = int(time.time())
    checkout_mandate = wallet.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        constraints=[line_items(sku=COFFEE.sku)],
        issued_at=now,
        expires_at=now + AN_HOUR,
    )
    payment_mandate = wallet.sign_open_payment_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        for_checkout=checkout_mandate,
        constraints=[budget(ceiling, "INR")],
        issued_at=now,
        expires_at=now + AN_HOUR,
    )

    deals: list[Agreed] = []
    for quantity in quantities:
        outcome = spine.receive(
            agent.request_purchase(
                agent_id=identity.agent_id,
                checkout=agent.present(checkout_mandate, audience=DESK),
                payment=agent.present(payment_mandate, audience=DESK),
                item_id=COFFEE.sku,
                amount="1.00",
                currency="INR",
            )
        )
        assert outcome.passed, outcome.reason_code
        assert outcome.checkout is not None and outcome.payment is not None
        reply = selling.open(outcome, tier=TrustTier.NEW).receive(
            Ask(sku=COFFEE.sku, quantity=quantity, target_unit_price=rupees(ASKING))
        )
        assert reply.closed and reply.closed_mandate is not None, reply.move
        deals.append(
            Agreed(
                authorised=Authorised(
                    outcome=outcome, checkout=outcome.checkout, payment=outcome.payment
                ),
                reply=reply,
                closed_mandate=reply.closed_mandate,
            )
        )

    first, second = deals
    assert first.payment.mandate_id == second.payment.mandate_id, (
        "both deals must draw against one authorisation, or this proves nothing about "
        "the accumulator"
    )
    return first, second


def settle(settlement: Settlement, deal: Agreed, identity: AgentIdentity) -> Settled:
    """``Settlement.settle``, with the four arguments a settled deal always supplies.

    A helper rather than a fixture, because the call is the thing under test and a test
    that varies one of the four -- settling against somebody else's authorisation, say --
    calls ``settle`` directly and should visibly differ from the ones that do not.
    """
    return settlement.settle(
        deal.closed_mandate,
        checkout=deal.checkout,
        payment=deal.payment,
        presented_by=identity,
    )

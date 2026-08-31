"""Settling a closed deal: the money, the receipt, and the ledger under both.

Every test drives a whole deal -- signed mandates, four checks, a negotiation that
closes -- and then settles it. What is asserted is the receipt as an *external artefact*
and what the audit trail says, never the SDK's internals and never a row in our own
tables. A test that read the ``receipt`` table directly would pass just as happily if the
signature covered nothing.

The correctness core of the ticket is one pair of facts and it is worth naming, because
half the tests here are about it: **a charge that completed produces exactly one receipt
and advances the accumulator by exactly that amount, and a charge that did not complete
produces neither.**
"""

from __future__ import annotations

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType
from desk.identity import AgentIdentity, DeskKeyVault
from desk.mandate import read_closed_checkout
from desk.negotiation import Desk
from desk.settlement import NotSettleable, Receipts, Settlement, read_receipt
from desk.spend import BudgetAccumulator, CeilingExceeded, Money
from desk.spine import TrustSpine
from tests.settlement.conftest import (
    ASKING,
    StubRail,
    UnreachableRail,
    closed_deal,
    completed,
    declined,
    presented,
    rupees,
    settle,
    two_deals_on_one_mandate,
)
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

#: Two kilos of beans at the asking price. What every deal here closes at.
AGREED = "1500.00"


def settlement_events(trail: AuditTrail) -> list[EventType]:
    """Only what settlement wrote. The spine's and the negotiation's are theirs."""
    return [
        entry.event_type
        for entry in trail.query()
        if entry.event_type
        in {
            EventType.SETTLEMENT_ATTEMPTED,
            EventType.SETTLEMENT_INCOMPLETE,
            EventType.RECEIPT_ISSUED,
        }
    ]


def test_a_closed_deal_charges_and_produces_a_signed_receipt(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The first acceptance criterion, end to end, including what the rail was asked."""
    deal = closed_deal(spine, selling, wallet, agent, identity)

    settled = settle(settlement, deal, identity)

    assert settled.completed
    assert settled.receipt is not None
    assert settled.charge.charge_id == "pay_TESTMODE0000001"

    # The rail was asked for what was agreed, not for something near it.
    assert len(rail.asked) == 1
    assert rail.asked[0].amount == rupees(AGREED)
    assert rail.asked[0].agent_id == identity.agent_id

    assert settlement_events(trail) == [
        EventType.SETTLEMENT_ATTEMPTED,
        EventType.RECEIPT_ISSUED,
    ]


def test_the_receipt_binds_the_chain_the_terms_the_amount_and_the_time(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """FR-7.2. All four, because any one of them alone is arguable.

    The terms are compared against the closed Checkout Mandate read back from its own
    bytes, so this asserts the two signed documents agree -- not that one object in
    memory was copied into another.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)
    closed = read_closed_checkout(deal.closed_mandate, key=vault.published().mandate)

    settled = settle(settlement, deal, identity)
    assert settled.receipt is not None
    receipt = settled.receipt.receipt

    assert deal.checkout.mandate_id is not None
    assert deal.payment.mandate_id is not None
    assert receipt.chain.open_checkout == deal.checkout.mandate_id.value
    assert receipt.chain.open_payment == deal.payment.mandate_id.value
    assert receipt.chain.closed_checkout == closed.checkout_hash.value

    assert receipt.agreed == closed.checkout.as_claims()
    assert receipt.agreed["total"] == AGREED
    assert receipt.agreed["terms"] == {"delivery": "standard", "payment": "on_delivery"}

    assert receipt.charged == rupees(AGREED)
    assert receipt.charged == closed.checkout.total
    assert receipt.issued_at.tzinfo is not None
    assert receipt.charge.rail == "razorpay"
    assert receipt.charge.charge_id == "pay_TESTMODE0000001"


def test_a_charge_that_does_not_complete_produces_no_receipt(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    receipts: Receipts,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Half the correctness core. A document asserting a charge that did not happen
    would be worse than no document, because everything downstream trusts it."""
    rail.answer = declined()
    deal = closed_deal(spine, selling, wallet, agent, identity)

    settled = settle(settlement, deal, identity)

    assert not settled.completed
    assert settled.receipt is None
    assert settled.charge.status == "failed"
    assert receipts.between() == []
    assert settlement_events(trail) == [
        EventType.SETTLEMENT_ATTEMPTED,
        EventType.SETTLEMENT_INCOMPLETE,
    ]


def test_a_charge_that_does_not_complete_leaves_the_accumulated_total_alone(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    pool: ConnectionPool,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The other half. A ceiling spent on a charge that never happened refuses the
    next honest request, for a reason nobody could find."""
    rail.answer = declined()
    deal = closed_deal(spine, selling, wallet, agent, identity)

    accumulator = BudgetAccumulator(pool)
    before = accumulator.spent_against(deal.payment)

    settle(settlement, deal, identity)

    after = accumulator.spent_against(deal.payment)
    assert before.spent == Money.of("0", "INR")
    assert after.spent == before.spent
    assert after.remaining == before.remaining


def test_a_rail_that_cannot_be_reached_leaves_an_attempt_and_nothing_else(
    spine: TrustSpine,
    selling: Desk,
    receipts: Receipts,
    trail: AuditTrail,
    pool: ConnectionPool,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A charge the Desk never got an answer about is not the same as one that was
    declined, and the trail should not claim to know which it was.

    What is left behind is an attempt with nothing after it -- which is exactly what a
    charge whose outcome is unknown should look like from the outside.
    """
    settlement = Settlement(
        UnreachableRail(),
        BudgetAccumulator(pool),
        receipts,
        trail,
        pool,
        receipt_key=vault.receipt_key(),
        mandate_key=vault.mandate_key().public_key,
    )
    deal = closed_deal(spine, selling, wallet, agent, identity)

    with pytest.raises(ConnectionError):
        settle(settlement, deal, identity)

    assert settlement_events(trail) == [EventType.SETTLEMENT_ATTEMPTED]
    assert receipts.between() == []
    assert BudgetAccumulator(pool).spent_against(deal.payment).spent == Money.of("0", "INR")


def test_two_deals_against_one_mandate_advance_the_accumulator_by_the_right_amounts(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    pool: ConnectionPool,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Partial spend has to stay accurate across settlements, or the ceiling drifts.

    **One** Payment Mandate, presented twice. That is the whole point of the test and it
    is easy to get wrong: two deals under two separate authorisations would pass against
    an accumulator that overwrote the running total instead of adding to it, because each
    would be the first spend against its own row.

    Two different quantities for the same reason -- 1,500 then 2,250, so a total of 3,750
    can only come from adding those two and not from doubling either.
    """
    accumulator = BudgetAccumulator(pool)
    first, second = two_deals_on_one_mandate(spine, selling, wallet, agent, identity)

    settle(settlement, first, identity)
    after_one = accumulator.spent_against(first.payment).spent

    rail.answer = completed(charge_id="pay_TESTMODE0000002")
    settled = settle(settlement, second, identity)

    assert after_one == rupees("1500.00")
    assert accumulator.spent_against(second.payment).spent == rupees("3750.00")
    assert settled.remaining == rupees("196250.00")


def test_a_deal_beyond_what_the_ceiling_has_left_is_not_charged(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    receipts: Receipts,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The accumulator is drawn down before the rail is called, on purpose.

    Its refusal is the Desk's own rule, and it should happen while there is still
    nothing to unwind. A charge taken and then found to breach the ceiling would leave
    money moved that the Desk cannot account for.
    """
    deal = closed_deal(
        spine, selling, wallet, agent, identity, quantity=2, ceiling="1000.00"
    )

    with pytest.raises(CeilingExceeded):
        settle(settlement, deal, identity)

    assert rail.asked == []
    assert receipts.between() == []


def test_settling_the_same_deal_twice_charges_once(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    receipts: Receipts,
    pool: ConnectionPool,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A retry is the ordinary reason anyone settles twice, and it must be safe.

    The second call returns the receipt that already exists: no second charge, no second
    draw on the ceiling, no second receipt for one deal.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)

    first = settle(settlement, deal, identity)
    again = settle(settlement, deal, identity)

    assert first.receipt is not None and again.receipt is not None
    assert again.receipt.signed == first.receipt.signed
    assert len(rail.asked) == 1
    assert len(receipts.between()) == 1
    assert BudgetAccumulator(pool).spent_against(deal.payment).spent == rupees(AGREED)


def test_a_closed_deal_cannot_be_settled_against_another_authorisation(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The chain on a receipt has to be a chain the Desk checked, not one it asserted.

    A deal negotiated under one open Checkout Mandate, presented for settlement beside a
    different one, would otherwise produce a receipt binding three digests that never
    went together.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)
    somebody_elses = presented(spine, wallet, agent, identity)

    with pytest.raises(NotSettleable, match="different open Checkout"):
        settlement.settle(
            deal.closed_mandate,
            checkout=somebody_elses.checkout,
            payment=somebody_elses.payment,
            presented_by=identity,
        )

    assert rail.asked == []


def test_a_deal_cannot_be_charged_against_an_unrelated_payment_mandate(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    pool: ConnectionPool,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The third link of the chain, checked rather than assumed.

    Check 3 paired *its* Checkout Mandate with *its* Payment Mandate. Settlement is
    handed its own three arguments, and being passed together is not what makes them a
    chain. Without this check, a deal presented beside somebody else's Payment Mandate
    produces a signed receipt naming an authorisation that had nothing to do with it,
    and draws the money off a ceiling granted for something else entirely.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)
    unrelated = presented(spine, wallet, agent, identity)

    with pytest.raises(NotSettleable, match="different open Checkout"):
        settlement.settle(
            deal.closed_mandate,
            checkout=deal.checkout,
            payment=unrelated.payment,
            presented_by=identity,
        )

    assert rail.asked == []
    accumulator = BudgetAccumulator(pool)
    assert accumulator.spent_against(unrelated.payment).spent == Money.of("0", "INR")
    assert accumulator.spent_against(deal.payment).spent == Money.of("0", "INR")


def test_the_desks_own_refusal_still_writes_an_ending(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """An attempt with nothing after it has to mean one thing only.

    It means *the Desk called the rail and never heard back*. A ceiling refusal is the
    Desk stopping itself, which it knows about, so it writes an ending — otherwise the
    one case where the Desk genuinely does not know would be indistinguishable from
    several where it does.

    The ending carries no ``rail`` evidence, which is how a reader tells this apart from
    a charge the rail declined. Not a reason code: reason codes are refusals of a
    *counterparty*, and the buyer did nothing wrong here.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity, quantity=2, ceiling="1000.00")

    with pytest.raises(CeilingExceeded):
        settle(settlement, deal, identity)

    assert rail.asked == []
    assert settlement_events(trail) == [
        EventType.SETTLEMENT_ATTEMPTED,
        EventType.SETTLEMENT_INCOMPLETE,
    ]
    ending = trail.query(event_type=EventType.SETTLEMENT_INCOMPLETE)[0]
    assert "rail" not in ending.payload["evidence"]
    assert ending.reason_code is None


def test_a_closed_mandate_the_desk_did_not_sign_is_not_settleable(
    settlement: Settlement,
    rail: StubRail,
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Settlement charges against the artefact, so the artefact is verified first."""
    authorised = presented(spine, wallet, agent, identity)

    with pytest.raises(NotSettleable, match="closed Checkout Mandate"):
        settlement.settle(
            "not-a-mandate.at.all",
            checkout=authorised.checkout,
            payment=authorised.payment,
            presented_by=identity,
        )

    assert rail.asked == []


def test_the_trail_carries_the_rails_identifiers_on_both_endings(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """FR-7.5: a settlement outcome is legible from the trail alone, either way."""
    deal = closed_deal(spine, selling, wallet, agent, identity)
    settle(settlement, deal, identity)

    issued = trail.query(event_type=EventType.RECEIPT_ISSUED)
    assert len(issued) == 1
    evidence = issued[0].payload["evidence"]
    assert evidence["rail"]["charge_id"] == "pay_TESTMODE0000001"
    assert evidence["rail"]["rail"] == "razorpay"
    assert evidence["charged"] == AGREED
    assert evidence["remaining"] is not None
    assert issued[0].subject_id == identity.agent_id
    # Not a refusal. The Desk refused nothing here, and the refusals view is built on
    # reason codes being exactly that.
    assert issued[0].reason_code is None


def test_an_incomplete_settlement_is_not_recorded_as_a_refusal(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    trail: AuditTrail,
    pool: ConnectionPool,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A rail declining a card is not the Desk refusing anything.

    If it carried a reason code it would land in ``audit_refusals``, and every metric
    over that view would start counting somebody else's declines as our refusals.
    """
    rail.answer = declined()
    deal = closed_deal(spine, selling, wallet, agent, identity)
    settle(settlement, deal, identity)

    entry = trail.query(event_type=EventType.SETTLEMENT_INCOMPLETE)[0]
    assert entry.reason_code is None
    assert entry.payload["evidence"]["rail"]["status"] == "failed"
    assert entry.payload["state_change"] == {"settlement": "did not complete"}

    with pool.connection() as conn:
        refusals = conn.execute("SELECT count(*) FROM audit_refusals").fetchone()
    assert refusals is not None and refusals[0] == 0


def test_a_receipt_survives_the_process_that_signed_it(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    pool: ConnectionPool,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """FR-7.3 is worth nothing if the published key changes when the Desk restarts.

    A second vault over the same database is what a restarted Desk is, and the receipt
    the first one signed still verifies against the key the second one publishes.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)
    settled = settle(settlement, deal, identity)
    assert settled.receipt is not None

    restarted = DeskKeyVault(pool).published()
    assert read_receipt(settled.receipt.signed, key=restarted.receipt).charged == rupees(AGREED)


def test_the_receipt_is_named_by_the_deal_it_settles(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """So that "the receipt for this deal" is answerable without a lookup table."""
    deal = closed_deal(spine, selling, wallet, agent, identity)
    closed = read_closed_checkout(deal.closed_mandate, key=vault.published().mandate)

    settled = settle(settlement, deal, identity)

    assert settled.receipt is not None
    assert settled.receipt.receipt_id == closed.checkout_hash.value


def test_the_charge_is_the_agreed_total_and_not_the_asking_price(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    rail: StubRail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The request said one rupee. What is charged is what the negotiation agreed.

    Worth its own test because the request's amount is a number a *counterparty* wrote,
    and a settlement that charged it would be letting the buyer name its own price.
    """
    deal = closed_deal(spine, selling, wallet, agent, identity)

    settle(settlement, deal, identity)

    assert rail.asked[0].amount == rupees(AGREED)
    assert rail.asked[0].amount != rupees(ASKING)

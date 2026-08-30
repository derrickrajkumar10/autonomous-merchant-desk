"""Whole negotiations, driven the way a stranger's buyer agent would drive one.

Every test here starts by signing two real mandates in a wallet, signing a real request
with a real agent key, and handing the string to ``TrustSpine.receive``. Nothing reaches
into a check, nothing constructs a verified mandate by hand, and nothing asks the policy
a question directly -- that is ``test_fixed_policy.py``'s job. What is asserted is what
the audit trail says afterwards: which events were written, in what order, with what
reason code and what evidence.

That is not a convention borrowed from somewhere. The trail is already required to be the
thing the control room draws and the metrics count, so a test reading it exercises the
same contract those two do.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.catalogue import Catalogue
from desk.identity import AgentIdentity, DeskKeypair
from desk.mandate import read_closed_checkout
from desk.negotiation import (
    Ask,
    Delivery,
    Desk,
    Lever,
    Move,
    Negotiation,
    NegotiationOver,
    Payment,
    TrustTier,
)
from desk.spend import Money
from desk.spine import TrustSpine
from tests.negotiation.conftest import COFFEE, GRINDER, LAPTOP, TERMS
from tests.spine.conftest import a_request
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

#: A ceiling well clear of anything negotiated here. Check 3's refusals are ticket 04's
#: to test; what this suite needs from the spine is a request that passes it.
CEILING = "200000.00"


def rupees(amount: str) -> Money:
    return Money.of(amount, "INR")


@pytest.fixture
def selling(storefront: Catalogue, trail: AuditTrail, desk_key: DeskKeypair) -> Desk:
    return Desk(storefront, TERMS, trail, desk_key)


def opened(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    *,
    sku: str = "SKU-COFFEE-1KG",
    also: str | None = None,
    tier: TrustTier = TrustTier.NEW,
) -> Negotiation:
    """One negotiation, opened on a request that really went through the four checks.

    ``also`` is a second sku the principal authorised, which is the only way a bundle
    becomes available -- the Desk reads its companions off the verified mandate.
    """
    outcome = spine.receive(
        a_request(
            wallet,
            agent,
            identity,
            item_id=sku,
            sku=sku,
            also=also,
            amount="1.00",
            ceiling=CEILING,
        )
    )
    assert outcome.passed, outcome.reason_code
    return selling.open(outcome, tier=tier)


def negotiation_entries(trail: AuditTrail) -> list[AuditEntry]:
    """Only what the negotiation wrote. The spine's four entries are ticket 06's."""
    return [entry for entry in trail.query() if "round" in entry.payload]


def events(trail: AuditTrail) -> list[EventType]:
    return [entry.event_type for entry in negotiation_entries(trail)]


def test_a_buyer_inside_the_floor_closes(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    desk_key: DeskKeypair,
) -> None:
    """The first acceptance criterion, end to end, including the artefact it produces."""
    deal = opened(spine, selling, wallet, agent, identity)

    reply = deal.receive(Ask(sku=COFFEE.sku, quantity=2, target_unit_price=rupees("750.00")))

    assert reply.move is Move.ACCEPT
    assert reply.closed
    assert events(trail) == [EventType.DEAL_CLOSED]
    assert reply.closed_mandate is not None

    closed = read_closed_checkout(reply.closed_mandate, key=desk_key.public_key)
    assert closed.checkout.items[0].item_id == COFFEE.sku
    assert closed.checkout.items[0].quantity == 2
    assert closed.checkout.items[0].unit_price == rupees("750.00")
    assert closed.checkout.total == rupees("1500.00")
    assert closed.checkout.terms == {"delivery": "standard", "payment": "on_delivery"}


def test_the_closed_mandate_names_the_open_one_it_was_negotiated_under(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    desk_key: DeskKeypair,
) -> None:
    """Without this, the agreed terms float free of the authorisation behind them."""
    deal = opened(spine, selling, wallet, agent, identity)

    reply = deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("750.00")))

    assert reply.closed_mandate is not None
    closed = read_closed_checkout(reply.closed_mandate, key=desk_key.public_key)
    assert closed.checkout.open_checkout


def test_a_buyer_below_the_floor_gets_a_lever_and_not_a_refusal(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The second acceptance criterion. The conversation continues rather than ending."""
    deal = opened(spine, selling, wallet, agent, identity)

    reply = deal.receive(
        Ask(
            sku=COFFEE.sku,
            quantity=1,
            target_unit_price=rupees("650.00"),
            largest_quantity=5,
        )
    )

    assert reply.move is Move.COUNTER
    assert reply.lever is Lever.QUANTITY_BREAK
    assert not deal.over
    assert events(trail) == [
        EventType.NEGOTIATION_MESSAGE_SENT,
        EventType.LEVER_OFFERED,
    ]


def test_the_desk_declines_a_discount_and_offers_a_bundle_in_the_same_message(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The third acceptance criterion, and the beat the pitch video shows.

    Ten percent off the grinder does not hold alone. The Desk does not say no; it says
    the same ten percent, beside a kilo of coffee at list -- one message, one decision
    about the pair.
    """
    deal = opened(spine, selling, wallet, agent, identity, sku=GRINDER.sku, also=COFFEE.sku)

    reply = deal.receive(
        Ask(sku=GRINDER.sku, quantity=1, target_unit_price=GRINDER.discounted("0.10"))
    )

    assert reply.move is Move.COUNTER
    assert reply.lever is Lever.BUNDLE
    assert reply.offer_unit_price == GRINDER.discounted("0.10")
    assert reply.rationale.inside_floor

    offered = negotiation_entries(trail)[0].payload["evidence"]["offered"]
    assert offered["bundled"] == [COFFEE.sku]


def test_a_bundle_is_never_built_from_something_the_principal_did_not_authorise(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The lever reads the mandate, not the request. Otherwise it is check 3 by a side door.

    Same ask as the test above, on a mandate that authorises the grinder alone. The
    coffee is stocked and would rescue the deal, and the Desk will not reach for it.
    """
    deal = opened(spine, selling, wallet, agent, identity, sku=GRINDER.sku)

    reply = deal.receive(
        Ask(sku=GRINDER.sku, quantity=1, target_unit_price=GRINDER.discounted("0.10"))
    )

    assert reply.lever is not Lever.BUNDLE
    assert reply.offer_unit_price > GRINDER.discounted("0.10")


def test_a_buyer_far_below_the_floor_is_walked_away_from_as_a_success(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The fourth acceptance criterion, and the vocabulary matters as much as the code.

    ``walked_away`` under ``below_margin_floor``: its own event type, in the
    closed/walked breakdown, never an incident. CONTEXT.md section 6 bans the word
    *failure* for this outcome, and the reason is not politeness -- metrics that punished
    correct refusals would teach the Desk to close everything.
    """
    deal = opened(spine, selling, wallet, agent, identity)

    reply = deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("300.00")))

    assert reply.move is Move.WALK_AWAY
    assert reply.walked_away
    assert deal.over

    written = negotiation_entries(trail)
    assert [entry.event_type for entry in written] == [EventType.WALKED_AWAY]
    assert written[0].reason_code is ReasonCode.BELOW_MARGIN_FLOOR
    assert written[0].payload["state_change"] == {"deal": "walked away"}


def test_a_walk_away_still_records_where_the_margin_would_have_been(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A reader should be able to see how far apart the two parties actually were."""
    deal = opened(spine, selling, wallet, agent, identity)

    reply = deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("300.00")))

    assert reply.rationale.as_payload()["surplus"] is not None
    assert reply.rationale.as_payload()["lever"] is None


def test_every_desk_message_carries_a_rationale(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The fifth acceptance criterion, asserted on all of them rather than on a sample.

    One quote, three counters and a close, and each entry the negotiation wrote carries
    the margin, the floor, the gap and the verdict.
    """
    deal = opened(spine, selling, wallet, agent, identity)

    deal.receive(Ask(sku=COFFEE.sku, quantity=1))
    deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("660.00")))
    deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("680.00")))
    deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("720.00")))

    written = negotiation_entries(trail)
    assert len(written) == 4
    for entry in written:
        rationale = entry.payload["evidence"]["rationale"]
        assert set(rationale) == {
            "asked",
            "margin",
            "floor",
            "revenue",
            "surplus",
            "inside_floor",
            "lever",
        }
        assert rationale["asked"]
        assert rationale["inside_floor"] is True


def test_a_counterparty_that_never_concedes_is_finished_with(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The sixth acceptance criterion. The bound is what makes this terminate at all.

    The ask sits inside REACH, so the Desk keeps countering rather than walking on the
    merits. What stops it is the round bound, and the outcome is written as the same
    walk-away as any other -- from the Desk's side, nothing different happened.
    """
    deal = opened(spine, selling, wallet, agent, identity)
    stubborn = Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("640.00"))

    replies = [deal.receive(stubborn) for _ in range(6)]

    assert [reply.move for reply in replies[:-1]] == [Move.COUNTER] * 5
    assert replies[-1].move is Move.WALK_AWAY
    assert deal.rounds_used == 6
    assert events(trail)[-1] is EventType.WALKED_AWAY
    with pytest.raises(NegotiationOver):
        deal.receive(stubborn)


def test_the_bound_never_walks_away_from_a_deal_the_desk_would_have_taken(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A buyer that concedes on its last allowed message still closes.

    Checking the bound before asking the policy would make the round count cost money
    rather than save time, which is the opposite of what it is for.
    """
    deal = opened(spine, selling, wallet, agent, identity)
    for _ in range(5):
        deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("640.00")))

    last = deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("750.00")))

    assert last.move is Move.ACCEPT


def test_every_negotiation_logs_what_a_policy_would_need_to_learn_from(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The seventh acceptance criterion, and FR-6.1's list read back off the trail.

    Product, trust tier, stated constraints, lever offered, outcome and realised margin.
    Recorded from the first deal, because a field added after a thousand of them is a
    field those thousand do not have -- and ticket 21 has to be trainable without a re-run.
    """
    deal = opened(spine, selling, wallet, agent, identity, tier=TrustTier.KNOWN)

    deal.receive(
        Ask(
            sku=COFFEE.sku,
            quantity=1,
            target_unit_price=rupees("650.00"),
            largest_quantity=5,
            wants_delivery=Delivery.EXPRESS,
            can_prepay=True,
        )
    )

    evidence = negotiation_entries(trail)[0].payload["evidence"]
    assert evidence["product"] == COFFEE.sku
    assert evidence["trust_tier"] == "known"
    assert evidence["stated"]["target_unit_price"] == "650.00 INR"
    assert evidence["stated"]["largest_quantity"] == 5
    assert evidence["stated"]["wants_delivery"] == "express"
    assert evidence["stated"]["can_prepay"] is True
    assert evidence["rationale"]["lever"] is not None
    assert Decimal(evidence["rationale"]["margin"]) > 0


def test_a_buyer_can_accept_the_offer_on_the_table(
    spine: TrustSpine,
    selling: Desk,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    desk_key: DeskKeypair,
) -> None:
    """Saying yes closes on exactly what was offered, terms and lever included."""
    deal = opened(spine, selling, wallet, agent, identity)
    counter = deal.receive(
        Ask(
            sku=COFFEE.sku,
            quantity=1,
            target_unit_price=rupees("650.00"),
            wants_delivery=Delivery.EXPRESS,
        )
    )
    assert counter.lever is Lever.DELIVERY_SPEED

    closed = deal.accept()

    assert closed.move is Move.ACCEPT
    assert closed.offer_unit_price == counter.offer_unit_price
    assert closed.terms.delivery is Delivery.EXPRESS
    assert closed.closed_mandate is not None

    read = read_closed_checkout(closed.closed_mandate, key=desk_key.public_key)
    assert read.checkout.terms == {"delivery": "express", "payment": "on_delivery"}
    assert [charge.label for charge in read.checkout.charges] == ["express delivery"]


def test_what_the_buyer_holds_says_nothing_about_what_the_desk_paid(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    desk_key: DeskKeypair,
) -> None:
    """Handling is a cost with no revenue, so it is not a line the buyer is shown.

    The margin position behind the deal goes to the trail, where the Desk's own reader
    sees it and the counterparty does not.
    """
    deal = opened(spine, selling, wallet, agent, identity)
    reply = deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("750.00")))

    assert reply.closed_mandate is not None
    read = read_closed_checkout(reply.closed_mandate, key=desk_key.public_key)

    assert read.checkout.charges == ()
    assert "cost" not in str(read.checkout.as_claims())


def test_nothing_answers_a_negotiation_that_has_already_ended(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A second ending for one negotiation would be two outcomes in the record."""
    deal = opened(spine, selling, wallet, agent, identity)
    deal.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("750.00")))

    with pytest.raises(NegotiationOver):
        deal.receive(Ask(sku=COFFEE.sku, quantity=1))
    with pytest.raises(NegotiationOver):
        deal.accept()


def test_there_is_nothing_to_accept_before_the_desk_has_spoken(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    deal = opened(spine, selling, wallet, agent, identity)

    with pytest.raises(NegotiationOver, match="nothing on the table"):
        deal.accept()


def test_a_negotiation_does_not_open_on_a_request_the_spine_refused(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A conversation after a refusal would be a conversation the refusal already ended."""
    refused = spine.receive(a_request(wallet, agent, identity, item_id=LAPTOP.sku, ceiling=CEILING))
    assert not refused.passed

    with pytest.raises(ValueError, match="passed the spine"):
        selling.open(refused, tier=TrustTier.NEW)


def test_the_same_request_gets_a_different_answer_on_two_products(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """FR-5.2 through the front door: margin is per product, not a Desk-wide discount rule.

    Fifteen percent off is comfortable on coffee and out of the question on a laptop --
    whose floor is *half* the coffee's, because it is bought at eighty-one percent of
    what it is asked for and there is nothing else in the price to give.
    """
    cheap = opened(spine, selling, wallet, agent, identity, sku=COFFEE.sku)
    reply_cheap = cheap.receive(
        Ask(sku=COFFEE.sku, quantity=1, target_unit_price=COFFEE.discounted("0.15"))
    )

    dear = opened(spine, selling, wallet, agent, identity, sku=LAPTOP.sku)
    reply_dear = dear.receive(
        Ask(sku=LAPTOP.sku, quantity=1, target_unit_price=LAPTOP.discounted("0.15"))
    )

    assert reply_cheap.move is Move.ACCEPT
    assert reply_dear.move is Move.WALK_AWAY


def test_prepayment_and_speed_reach_a_price_that_neither_reaches_alone(
    spine: TrustSpine,
    selling: Desk,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Each lever pays for the concession in a different currency, and both are real."""
    plain = opened(spine, selling, wallet, agent, identity)
    prepaid = opened(spine, selling, wallet, agent, identity)

    without = plain.receive(Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("640.00")))
    with_terms = prepaid.receive(
        Ask(sku=COFFEE.sku, quantity=1, target_unit_price=rupees("640.00"), can_prepay=True)
    )

    assert with_terms.offer_unit_price < without.offer_unit_price
    assert with_terms.terms.payment is Payment.PREPAID
    assert without.terms.payment is Payment.ON_DELIVERY

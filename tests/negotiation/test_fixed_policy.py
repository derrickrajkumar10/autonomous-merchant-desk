"""The fixed policy: what it offers, what it will not offer, and when it stops.

These tests read the policy directly rather than through a negotiation, which is the one
place in this suite that does. The reason is that the policy is the seam ticket 21
replaces, and its contract -- the three moves, the closed lever set, the price it will
not go below -- has to be pinned somewhere a bandit can be held to the same one.
Everything about the *conversation* is tested through the front door instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

import pytest

from desk.catalogue import Line, Offer, Product, margin_on
from desk.negotiation import (
    REACH,
    Ask,
    Delivery,
    FixedPolicy,
    Lever,
    Move,
    Payment,
    Position,
    Proposal,
    TrustTier,
)
from desk.spend import Money
from tests.negotiation.conftest import COFFEE, GRINDER, LAPTOP, PRODUCTS, TERMS

POLICY = FixedPolicy()


def rupees(amount: str) -> Money:
    return Money.of(amount, "INR")


def propose(
    ask: Ask, product: Product = COFFEE, *, companions: Sequence[Product] = ()
) -> Proposal:
    return POLICY.propose(
        Position(
            ask=ask,
            product=product,
            companions=tuple(companions),
            sheet=TERMS,
            tier=TrustTier.NEW,
            round=1,
        )
    )


def coffee(
    price: str | None = None,
    *,
    largest_quantity: int | None = None,
    wants_delivery: Delivery | None = None,
    can_prepay: bool = False,
) -> Ask:
    return Ask(
        sku=COFFEE.sku,
        quantity=1,
        target_unit_price=None if price is None else rupees(price),
        largest_quantity=largest_quantity,
        wants_delivery=wants_delivery,
        can_prepay=can_prepay,
    )


def test_an_ask_with_no_price_is_answered_with_a_quote() -> None:
    """A buyer asking what a thing costs has not started haggling, so no lever is spent."""
    proposal = propose(coffee())

    assert proposal.move is Move.COUNTER
    assert proposal.unit_price == COFFEE.list_price
    assert proposal.lever is None


def test_a_price_inside_the_floor_is_taken_as_it_stands() -> None:
    proposal = propose(coffee("700.00"))

    assert proposal.move is Move.ACCEPT
    assert proposal.unit_price == rupees("700.00")
    assert proposal.lever is None
    assert proposal.margin.inside_floor


def test_a_buyer_offering_above_list_is_answered_at_list() -> None:
    """Taking the higher number would be the Desk profiting from somebody's mistake."""
    proposal = propose(coffee("1200.00"))

    assert proposal.unit_price == COFFEE.list_price


def test_below_the_floor_and_with_no_lever_available_the_desk_counters() -> None:
    """The buyer gets a number rather than a refusal, and the number holds."""
    proposal = propose(coffee("650.00"))

    assert proposal.move is Move.COUNTER
    assert proposal.lever is None
    assert proposal.unit_price > rupees("650.00")
    assert proposal.margin.inside_floor


def test_the_counter_is_the_least_the_desk_can_charge_and_not_a_round_number() -> None:
    """One step below the countered price and the floor is crossed. That is the test.

    A policy that countered at a comfortable price would be leaving money on the table in
    the buyer's direction and would also be untestable -- there would be no way to tell a
    tight number from a cautious one.
    """
    proposal = propose(coffee("650.00"))

    a_paisa_less = Money(amount=proposal.unit_price.amount - Decimal("0.01"), currency="INR")
    shaved = margin_on(
        Offer.of(
            Line(product=COFFEE, quantity=1, unit_price=a_paisa_less),
            charges=proposal.offer.charges,
        )
    )

    assert proposal.margin.inside_floor
    assert not shaved.inside_floor


def test_a_buyer_that_would_take_more_is_offered_a_quantity_break() -> None:
    """The fixed cost of a deal spreads, so the rate the buyer wanted becomes affordable."""
    proposal = propose(coffee("650.00", largest_quantity=5))

    assert proposal.move is Move.COUNTER
    assert proposal.lever is Lever.QUANTITY_BREAK
    assert proposal.unit_price == rupees("650.00")
    assert proposal.offer.lines[0].quantity == 5
    assert proposal.margin.inside_floor


def test_a_firm_quantity_gets_no_quantity_break() -> None:
    """A lever is available because a buyer said something, never because the Desk hoped."""
    assert propose(coffee("650.00")).lever is not Lever.QUANTITY_BREAK
    assert propose(coffee("650.00", largest_quantity=1)).lever is not Lever.QUANTITY_BREAK


def test_a_buyer_in_a_hurry_is_sold_the_hurry() -> None:
    """FR-5.3's "at a premium": the goods are not cheaper, the deal is bigger."""
    proposal = propose(coffee("650.00", wants_delivery=Delivery.EXPRESS))

    assert proposal.lever is Lever.DELIVERY_SPEED
    assert proposal.terms.delivery is Delivery.EXPRESS
    assert proposal.unit_price == rupees("650.00")


def test_prepayment_buys_a_lower_price_because_it_costs_less_to_carry() -> None:
    proposal = propose(coffee("650.00", can_prepay=True))
    without = propose(coffee("650.00"))

    assert proposal.lever is Lever.PAYMENT_TERMS
    assert proposal.terms.payment is Payment.PREPAID
    assert proposal.unit_price < without.unit_price


def test_the_desk_declines_a_discount_and_offers_a_bundle_in_the_same_message() -> None:
    """FR-5.3's sentence, and the beat the pitch video shows.

    Ten percent off the grinder does not hold on its own. Beside a kilo of coffee at
    list, the same ten percent does -- because the pair is what the Desk is deciding
    about.
    """
    asked = GRINDER.discounted("0.10")
    alone = propose(Ask(sku=GRINDER.sku, quantity=1, target_unit_price=asked), GRINDER)
    bundled = propose(
        Ask(sku=GRINDER.sku, quantity=1, target_unit_price=asked),
        GRINDER,
        companions=(COFFEE,),
    )

    assert alone.lever is None
    assert alone.unit_price > asked

    assert bundled.lever is Lever.BUNDLE
    assert bundled.unit_price == asked
    assert [line.product.sku for line in bundled.offer.lines[1:]] == [COFFEE.sku]


def test_a_companion_is_never_worth_more_than_the_thing_being_asked_for() -> None:
    """The arithmetic would sell coffee at 300 beside a laptop. That is the wrong answer.

    A buyer who asked for a kilo of coffee is not one small concession away from buying a
    laptop, and an offer built on the possibility is a merchant not listening. A bundle is
    an add-on to a deal, not a deal with an add-on.
    """
    proposal = propose(coffee("300.00"), companions=PRODUCTS)

    assert proposal.lever is not Lever.BUNDLE
    assert proposal.move is Move.WALK_AWAY


def test_a_bundle_is_only_offered_from_products_it_was_handed() -> None:
    """The engine hands over what the mandate authorised; the policy cannot reach past it."""
    asked = GRINDER.discounted("0.10")

    assert propose(Ask(sku=GRINDER.sku, quantity=1, target_unit_price=asked), GRINDER).lever is None


def test_a_buyer_far_below_anything_reachable_is_walked_away_from() -> None:
    proposal = propose(coffee("300.00"))

    assert proposal.move is Move.WALK_AWAY


def test_the_walk_away_line_is_where_reach_puts_it() -> None:
    """Just inside is a conversation; just outside is not, and the constant says where."""
    best = propose(coffee("650.00")).unit_price
    inside = best.amount * (Decimal(1) - REACH) + Decimal("0.01")
    outside = best.amount * (Decimal(1) - REACH) - Decimal("0.01")

    assert propose(coffee(str(inside))).move is Move.COUNTER
    assert propose(coffee(str(outside))).move is Move.WALK_AWAY


def test_the_same_discount_gets_a_different_answer_on_two_products() -> None:
    """FR-5.2, through the policy rather than through the arithmetic.

    Fifteen percent off is comfortable on coffee and out of the question on a laptop --
    on a floor that is half the coffee's. A Desk reasoning about discount percentages
    would treat the two the same and lose money on one of them.
    """
    cheap = propose(
        Ask(sku=COFFEE.sku, quantity=1, target_unit_price=COFFEE.discounted("0.15")), COFFEE
    )
    dear = propose(
        Ask(sku=LAPTOP.sku, quantity=1, target_unit_price=LAPTOP.discounted("0.15")), LAPTOP
    )

    assert cheap.move is Move.ACCEPT
    assert dear.move is Move.WALK_AWAY
    assert LAPTOP.margin_floor < COFFEE.margin_floor


def test_every_proposal_holds_or_is_a_walk_away() -> None:
    """The property the whole package rests on, swept over a range of asks.

    Nothing the policy is prepared to *do* is ever beneath the floor. A walk-away's offer
    is the arrangement the Desk could not reach agreement on, and it is not something it
    offered -- so it is the one case exempt.
    """
    for product in PRODUCTS:
        for tenth in range(0, 11):
            ask = Ask(
                sku=product.sku,
                quantity=2,
                target_unit_price=product.discounted(Decimal(tenth) / 10),
                largest_quantity=6,
                wants_delivery=Delivery.EXPRESS,
                can_prepay=True,
            )
            proposal = propose(ask, product, companions=PRODUCTS)
            if proposal.move is not Move.WALK_AWAY:
                assert proposal.margin.inside_floor, f"{product.sku} at {tenth} tenths off"


@pytest.mark.parametrize("lever", list(Lever))
def test_the_action_space_is_four_wide(lever: Lever) -> None:
    """A guard on the closed set: adding a member without meaning to should be noticed."""
    assert lever.value in {
        "quantity_break",
        "bundle",
        "delivery_speed",
        "payment_terms",
    }

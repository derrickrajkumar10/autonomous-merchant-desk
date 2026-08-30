"""A deal is not only goods, and the parts that are not goods still move the margin.

Two of the negotiation's four levers are arithmetic only because of this file. Express
delivery at a premium earns money the goods did not have to earn, and the fixed work of
putting one deal out of the door does not double when the order does -- so a larger
quantity spreads it thinner. Without charges, both of those levers would be a sentence
in a log line with nothing behind it.

The numbers here are the storefront's own, so they stay true to what will be seeded.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.catalogue import Charge, Line, Offer, margin_on
from desk.spend import CurrencyMismatch, Money
from tests.catalogue.conftest import COFFEE, GRINDER

#: What it costs the Desk to put one deal out of the door, whatever is in it.
HANDLING = Charge.of("handling", revenue=0, cost="150.00", currency="INR")

#: Express delivery: the buyer pays 400, the courier takes 240, the Desk keeps 160.
EXPRESS = Charge.of("express delivery", revenue="400.00", cost="240.00", currency="INR")


def _coffee(quantity: int, unit_price: Money, *charges: Charge) -> Offer:
    return Offer.of(
        Line(product=COFFEE, quantity=quantity, unit_price=unit_price), charges=charges
    )


def test_a_charge_with_no_revenue_is_a_cost_the_deal_carries() -> None:
    """Handling is money out and nothing in, so it comes straight off the surplus."""
    plain = margin_on(_coffee(1, COFFEE.list_price))
    handled = margin_on(_coffee(1, COFFEE.list_price, HANDLING))

    assert plain.surplus - handled.surplus == Decimal("150.00")
    assert handled.cost == Money.of("570.00", "INR")
    assert handled.revenue == plain.revenue


def test_the_floor_asks_the_same_of_a_deal_that_carries_a_charge() -> None:
    """A charge asks for nothing itself. The lines' requirement does not move."""
    plain = margin_on(_coffee(1, COFFEE.list_price))
    handled = margin_on(_coffee(1, COFFEE.list_price, HANDLING))

    assert handled.required_profit == plain.required_profit == Decimal("269.700")


def test_a_fixed_cost_spreads_over_a_larger_order() -> None:
    """The quantity break, in one assertion.

    A fifth off a single kilo of coffee is 719.20 against a 420 cost, and 150 of
    handling takes the deal under its floor. The same fifth off five kilos carries the
    same 150, and it holds -- which is a real reason to grant a rate at volume that
    could not be granted on one.
    """
    rate = COFFEE.discounted("0.20")

    one = margin_on(_coffee(1, rate, HANDLING))
    five = margin_on(_coffee(5, rate, HANDLING))

    assert not one.inside_floor
    assert five.inside_floor


def test_a_premium_charge_funds_a_concession_on_the_goods() -> None:
    """The delivery lever, in one assertion.

    A tenth off the grinder is 38.18 short of its floor on its own. Express delivery
    priced at 400 against a 240 courier cost puts 160 into the deal, and the same tenth
    holds -- the goods were not made cheaper, the deal was made bigger.
    """
    discounted = GRINDER.discounted("0.10")

    alone = margin_on(Offer.of(Line(product=GRINDER, quantity=1, unit_price=discounted)))
    expressed = margin_on(
        Offer.of(
            Line(product=GRINDER, quantity=1, unit_price=discounted), charges=(EXPRESS,)
        )
    )

    assert not alone.inside_floor
    assert expressed.inside_floor
    assert expressed.profit - alone.profit == Decimal("160.00")


def test_a_charge_reports_itself_in_the_breakdown() -> None:
    """The breakdown explains the decision, so what the courier took has to be in it."""
    margin = margin_on(_coffee(1, COFFEE.list_price, HANDLING, EXPRESS))

    assert [charge.label for charge in margin.charges] == ["handling", "express delivery"]
    assert [charge.profit for charge in margin.charges] == [
        Decimal("-150.00"),
        Decimal("160.00"),
    ]
    assert margin.charges[0].rate is None
    assert margin.charges[1].rate == Decimal("0.400000")


def test_an_offer_refuses_a_charge_in_another_currency() -> None:
    with pytest.raises(CurrencyMismatch):
        _coffee(1, COFFEE.list_price, Charge.of("shipping", revenue=0, cost=99, currency="USD"))


def test_a_charge_is_named() -> None:
    with pytest.raises(ValueError, match="named"):
        Charge.of("  ", revenue=0, cost="1.00", currency="INR")


def test_a_charge_refuses_two_currencies_of_its_own() -> None:
    with pytest.raises(CurrencyMismatch):
        Charge(
            label="express delivery",
            revenue=Money.of("400.00", "INR"),
            cost=Money.of("3.00", "USD"),
        )

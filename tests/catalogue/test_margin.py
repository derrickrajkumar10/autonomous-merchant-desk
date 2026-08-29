"""Margin on a single line: the arithmetic, and what the floor is compared against.

No database. Margin is arithmetic over a product and a proposed price, and the only
thing that could make it wrong is the arithmetic.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.catalogue import Line, Offer, Product, margin_on
from desk.spend import CurrencyMismatch, Money
from tests.catalogue.conftest import COFFEE, LAPTOP


def _margin_at(product: Product, unit_price: Money, quantity: int = 1):  # type: ignore[no-untyped-def]
    return margin_on(Offer.of(Line(product=product, quantity=quantity, unit_price=unit_price)))


def test_margin_is_computable_for_any_proposed_price_and_quantity() -> None:
    """The ticket's second acceptance criterion. Two kilos, at a price nobody listed."""
    margin = _margin_at(COFFEE, Money.of("750.00", "INR"), quantity=2)

    assert margin.revenue == Money.of("1500.00", "INR")
    assert margin.cost == Money.of("840.00", "INR")
    assert margin.profit == Decimal("660.00")
    assert margin.inside_floor


def test_margin_is_the_share_of_revenue_that_is_profit() -> None:
    """Gross margin, not markup on cost. 479 of 899 rupees is 53.28 percent."""
    margin = _margin_at(COFFEE, COFFEE.list_price)

    assert margin.profit == Decimal("479.00")
    assert margin.rate == Decimal("0.532814")


def test_the_floor_is_a_share_of_revenue_and_not_a_price() -> None:
    """Coffee floored at 30 percent of an 899-rupee sale needs 269.70 of profit."""
    margin = _margin_at(COFFEE, COFFEE.list_price)

    assert margin.floor == Decimal("0.30")
    assert margin.required_profit == Decimal("269.7000")
    assert margin.surplus == Decimal("209.3000")


def test_a_deal_below_the_floor_reports_how_far_below() -> None:
    """Forty percent off coffee. Still well above cost, and still refused."""
    margin = _margin_at(COFFEE, COFFEE.discounted("0.40"))

    assert margin.profit == Decimal("119.40")
    assert not margin.inside_floor
    assert margin.surplus == Decimal("-42.4200")


def test_the_decision_is_made_without_dividing() -> None:
    """The one that matters, and the reason ``rate`` never decides anything.

    Profit of 666,667 on revenue of 2,000,000 is a margin of 0.3333335 exactly --
    which, reported to six places, rounds *up* to 0.333334 and reads as meeting a
    floor of 0.333334. Compare the rounded number and this deal is inside the floor.
    Compare profit against ``floor x revenue``, where nothing is divided and nothing
    rounds, and it is one rupee short.
    """
    knife_edge = Product.of(
        sku="SKU-KNIFE-EDGE",
        name="Priced to land half a millionth from its floor",
        cost="1333333.00",
        list_price="2100000.00",
        margin_floor="0.333334",
        currency="INR",
    )
    margin = _margin_at(knife_edge, Money.of("2000000.00", "INR"))

    assert margin.rate == Decimal("0.333334")
    assert margin.rate >= margin.floor
    assert margin.required_profit == Decimal("666668.00000000")
    assert margin.profit == Decimal("666667.00")
    assert not margin.inside_floor


def test_quantity_moves_the_profit_and_leaves_the_rate_alone() -> None:
    """Which is why a quantity break is a lever and not a way around the floor.

    Five kilos at the same discount earns five times the profit at exactly the same
    margin. Selling more of something below its floor does not bring it back inside.
    """
    one = _margin_at(COFFEE, COFFEE.discounted("0.15"))
    five = _margin_at(COFFEE, COFFEE.discounted("0.15"), quantity=5)

    assert one.rate == five.rate == Decimal("0.450370")
    assert five.profit == one.profit * 5 == Decimal("1720.75")
    assert one.inside_floor and five.inside_floor

    below = _margin_at(COFFEE, COFFEE.discounted("0.40"))
    below_in_bulk = _margin_at(COFFEE, COFFEE.discounted("0.40"), quantity=100)
    assert not below.inside_floor
    assert not below_in_bulk.inside_floor


def test_two_products_with_different_costs_answer_the_same_discount_differently() -> None:
    """The ticket's fourth acceptance criterion, and the point of a floor per product.

    Fifteen percent off is comfortable for coffee, which costs 420 and asks 899. It is
    nowhere near acceptable for the laptop, which costs 61,000 and asks 74,999 -- even
    though the laptop's floor is *half* the coffee's. Cost is what decides, and a
    single Desk-wide discount rule could not tell these two apart.
    """
    coffee = _margin_at(COFFEE, COFFEE.discounted("0.15"))
    laptop = _margin_at(LAPTOP, LAPTOP.discounted("0.15"))

    assert COFFEE.margin_floor > LAPTOP.margin_floor
    assert coffee.inside_floor
    assert not laptop.inside_floor
    assert laptop.profit > 0  # not a loss -- simply not enough of one


def test_the_laptop_has_a_little_room_and_the_coffee_has_a_lot() -> None:
    """The same two products, at the largest discount each can actually take."""
    assert _margin_at(COFFEE, COFFEE.discounted("0.33")).inside_floor
    assert not _margin_at(COFFEE, COFFEE.discounted("0.34")).inside_floor

    assert _margin_at(LAPTOP, LAPTOP.discounted("0.04")).inside_floor
    assert not _margin_at(LAPTOP, LAPTOP.discounted("0.05")).inside_floor


def test_giving_a_line_away_is_a_loss_the_size_of_its_cost() -> None:
    """Revenue of nothing has no margin to report, and the profit is signed."""
    margin = _margin_at(COFFEE, Money.of("0.00", "INR"))

    assert margin.profit == Decimal("-420.00")
    assert margin.rate is None
    assert not margin.inside_floor


def test_profit_is_a_signed_number_and_not_money() -> None:
    """``Money`` refuses to be negative, and a loss is not an amount the Desk holds.

    So a losing deal is expressible rather than unrepresentable, and the type stops it
    being handed to the spend accumulator by mistake.
    """
    margin = _margin_at(LAPTOP, Money.of("60000.00", "INR"))

    assert isinstance(margin.profit, Decimal)
    assert not isinstance(margin.profit, Money)
    assert margin.profit == Decimal("-1000.00")


def test_a_line_priced_in_the_wrong_currency_is_refused() -> None:
    with pytest.raises(CurrencyMismatch):
        Line(product=COFFEE, quantity=1, unit_price=Money.of("750.00", "USD"))


def test_a_line_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        Line(product=COFFEE, quantity=0, unit_price=COFFEE.list_price)


def test_an_offer_with_no_lines_is_refused() -> None:
    """There is no margin on nothing, and returning zero would be a lie about it."""
    with pytest.raises(ValueError, match="at least one"):
        Offer.of()


def test_the_rationale_line_says_what_was_asked_and_whether_it_holds() -> None:
    """FR-5.4 -- one machine-readable line beside every Desk reply."""
    assert str(_margin_at(COFFEE, COFFEE.discounted("0.15"))) == (
        "margin 45.0370% on 764.15 INR revenue, floor 30.0000%, inside by 114.9050 INR"
    )
    assert str(_margin_at(COFFEE, COFFEE.discounted("0.40"))) == (
        "margin 22.1357% on 539.40 INR revenue, floor 30.0000%, short by 42.4200 INR"
    )

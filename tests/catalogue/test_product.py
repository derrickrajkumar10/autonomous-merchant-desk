"""A product is a cost, an asking price and a floor, and none of the three is optional.

Unit tests over a value object, like ``tests/spend/test_money.py`` and for the same
reason: the properties here belong to the type rather than to the database, and they
are what every margin computed above them rests on.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.catalogue import Product
from desk.spend import CurrencyMismatch, Money
from tests.catalogue.conftest import COFFEE, LAPTOP


def test_a_product_carries_cost_list_price_and_a_floor() -> None:
    """The whole of the ticket's first acceptance criterion, in one assertion."""
    assert COFFEE.cost == Money.of("420.00", "INR")
    assert COFFEE.list_price == Money.of("899.00", "INR")
    assert COFFEE.margin_floor == Decimal("0.30")


def test_cost_and_list_price_must_be_the_same_currency() -> None:
    """Otherwise the margin is a subtraction across an exchange rate the Desk lacks."""
    with pytest.raises(CurrencyMismatch):
        Product(
            sku="SKU-NONSENSE",
            name="Priced in one currency and bought in another",
            cost=Money.of("420.00", "INR"),
            list_price=Money.of("899.00", "USD"),
            margin_floor=Decimal("0.30"),
        )


def test_a_floor_the_asking_price_cannot_meet_is_refused() -> None:
    """A product nobody could sell at its own asking price is a data error.

    Not a walk-away -- a walk-away is the Desk refusing a *deal*. This is a row that
    could never produce one, and catching it here beats discovering it mid-negotiation.
    """
    with pytest.raises(ValueError, match="cannot meet its own margin floor"):
        Product.of(
            sku="SKU-UNSELLABLE",
            name="Marked up by a tenth, floored at a half",
            cost="900.00",
            list_price="1000.00",
            margin_floor="0.50",
            currency="INR",
        )


def test_a_margin_floor_of_one_or_more_is_refused() -> None:
    """A floor of 1 asks the whole price to be profit, so the cost must be zero."""
    with pytest.raises(ValueError, match="fraction of revenue"):
        Product.of(
            sku="SKU-IMPOSSIBLE",
            name="All profit",
            cost="0.00",
            list_price="1000.00",
            margin_floor="1",
            currency="INR",
        )


def test_a_negative_margin_floor_is_refused() -> None:
    with pytest.raises(ValueError, match="fraction of revenue"):
        Product.of(
            sku="SKU-BACKWARDS",
            name="Floored below nothing",
            cost="100.00",
            list_price="1000.00",
            margin_floor="-0.1",
            currency="INR",
        )


def test_a_margin_floor_built_from_a_float_is_refused() -> None:
    """The same rule ``Money`` enforces, for the same reason.

    ``0.30`` as a float is ``0.299999999999999988897769753748...``, and a floor that is
    not the number somebody wrote is a floor nobody set.
    """
    with pytest.raises(TypeError, match="cannot be built from a float"):
        Product.of(
            sku="SKU-FLOATY",
            name="Floored by approximation",
            cost="420.00",
            list_price="899.00",
            margin_floor=0.30,  # type: ignore[arg-type]
            currency="INR",
        )


def test_something_that_is_not_a_sku_is_refused() -> None:
    """The sku is what check 3 matches against the mandate's ``acceptable_items``.

    A product whose id could not appear there is a product no mandate could authorise.
    """
    with pytest.raises(ValueError, match="sku"):
        Product.of(
            sku="sku coffee 1kg",
            name="Lowercase and spaced",
            cost="420.00",
            list_price="899.00",
            margin_floor="0.30",
            currency="INR",
        )


def test_a_discount_comes_off_the_list_price_exactly() -> None:
    assert COFFEE.discounted("0.10") == Money.of("809.10", "INR")


def test_a_discount_rounds_to_the_scale_the_price_is_written_at() -> None:
    """``74999.00`` is priced to the paisa, so a discount off it lands on a paisa.

    Fifteen percent off 74,999.00 is 63,749.15 exactly; a third off is not exact and
    has to land somewhere, and where it lands is the price's own scale rather than a
    currency table this module would otherwise have to carry.
    """
    assert LAPTOP.discounted("0.15") == Money.of("63749.15", "INR")
    assert LAPTOP.discounted("0.3333") == Money.of("50001.83", "INR")


def test_a_discount_rounds_toward_the_desk_on_a_tie() -> None:
    """A concession is granted deliberately, never handed over by a rounding rule.

    Ten percent off ``10.05`` is ``9.045``, exactly half a paisa between two prices.
    It goes up.
    """
    product = Product.of(
        sku="SKU-TIEBREAK",
        name="Priced to land on a half paisa",
        cost="1.00",
        list_price="10.05",
        margin_floor="0.10",
        currency="INR",
    )
    assert product.discounted("0.10") == Money.of("9.05", "INR")


def test_giving_something_away_is_a_hundred_percent_discount() -> None:
    """A free add-on is a lever (FR-5.3), so the edge of the range is allowed."""
    assert COFFEE.discounted("1") == Money.of("0.00", "INR")


def test_a_discount_of_more_than_everything_is_refused() -> None:
    with pytest.raises(ValueError, match="fraction"):
        COFFEE.discounted("1.5")


def test_a_coarsely_written_price_still_discounts_to_whole_units() -> None:
    """``Decimal("1E+3")`` is one thousand recorded to the nearest thousand.

    Rounding a discount to *that* scale would send every price under 1,500 back to the
    full list price -- a discount that silently became no discount, which is the
    quietest way this method could be wrong. The scale is clamped at whole units.
    """
    coarse = Product(
        sku="SKU-ROUND-THOUSANDS",
        name="Priced to the nearest thousand",
        cost=Money.of("100", "INR"),
        list_price=Money(amount=Decimal("1E+3"), currency="INR"),
        margin_floor=Decimal("0.10"),
    )

    assert coarse.list_price.amount.as_tuple().exponent == 3
    assert coarse.discounted("0.10") == Money.of("900", "INR")
    assert coarse.discounted("0.49") == Money.of("510", "INR")
    assert coarse.discounted("0.51") == Money.of("490", "INR")

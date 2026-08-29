"""A bundle is one deal with one margin, not several deals that each have to hold.

This is the ticket's third acceptance criterion, and it is also FR-5.3's whole reason
for existing: the Desk may refuse a discount on its own and grant the same discount
inside a bundle, because the bundle is what it is deciding about.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.catalogue import Line, Offer, margin_on
from desk.spend import CurrencyMismatch, Money
from tests.catalogue.conftest import COFFEE, GRINDER, LAPTOP

#: Ten percent off the grinder: too much on its own, affordable beside coffee at list.
GRINDER_DISCOUNT = "0.10"


def _grinder_alone() -> Offer:
    return Offer.of(
        Line(product=GRINDER, quantity=1, unit_price=GRINDER.discounted(GRINDER_DISCOUNT))
    )


def _grinder_with_coffee() -> Offer:
    return Offer.of(
        Line(product=GRINDER, quantity=1, unit_price=GRINDER.discounted(GRINDER_DISCOUNT)),
        Line(product=COFFEE, quantity=1, unit_price=COFFEE.list_price),
    )


def test_the_same_discount_is_refused_alone_and_granted_in_a_bundle() -> None:
    """The lever, in one test.

    Ten percent off the grinder leaves 749.10 of profit where its own floor asks for
    787.28 -- so the Desk walks. Add a kilo of coffee at full list and the *pair*
    earns 1,228.10 against a combined ask of 1,056.98, and the same discount holds.
    """
    alone = margin_on(_grinder_alone())
    bundled = margin_on(_grinder_with_coffee())

    assert not alone.inside_floor
    assert alone.surplus == Decimal("-38.1750")

    assert bundled.inside_floor
    assert bundled.surplus == Decimal("171.1250")


def test_a_bundle_is_decided_on_its_combined_numbers() -> None:
    bundled = margin_on(_grinder_with_coffee())

    assert bundled.revenue == Money.of("4048.10", "INR")
    assert bundled.cost == Money.of("2820.00", "INR")
    assert bundled.profit == Decimal("1228.10")
    assert bundled.rate == Decimal("0.303377")


def test_a_bundles_floor_is_what_its_lines_ask_for_added_up() -> None:
    """Not the strictest line's floor, and not an average of the percentages.

    Each line asks for ``floor x its own revenue``; the bundle asks for the sum. Read
    back as a percentage that is a revenue-weighted blend -- 26.11 percent here, which
    is between the coffee's 30 and the grinder's 25 and closer to the grinder because
    the grinder is most of the money.
    """
    bundled = margin_on(_grinder_with_coffee())

    assert bundled.required_profit == Decimal("1056.9750")
    assert bundled.required_profit == Decimal("787.2750") + Decimal("269.7000")
    assert bundled.floor == Decimal("0.261104")
    assert GRINDER.margin_floor < bundled.floor < COFFEE.margin_floor


def test_the_lines_are_still_readable_but_carry_no_verdict() -> None:
    """The breakdown is for the rationale line. The decision is not available per line.

    ``LineMargin`` has no ``inside_floor``, on purpose: a bundle in which one line is
    below its own floor is the ordinary case, and any code that could ask a line
    whether it holds would eventually refuse a bundle that was perfectly fine.
    """
    bundled = margin_on(_grinder_with_coffee())
    grinder, coffee = bundled.lines

    assert grinder.sku == "SKU-GRINDER-BURR"
    assert grinder.profit == Decimal("749.10")
    assert grinder.required_profit == Decimal("787.2750")
    assert coffee.sku == "SKU-COFFEE-1KG"
    assert coffee.profit == Decimal("479.00")

    assert not hasattr(grinder, "inside_floor")


def test_a_bundle_cannot_be_rescued_by_adding_a_line_that_loses_money() -> None:
    """Subsidy runs one way. A line given away brings its cost and no revenue."""
    padded = margin_on(
        Offer.of(
            Line(product=GRINDER, quantity=1, unit_price=GRINDER.discounted(GRINDER_DISCOUNT)),
            Line(product=COFFEE, quantity=1, unit_price=Money.of("0.00", "INR")),
        )
    )

    assert not padded.inside_floor
    assert padded.profit == Decimal("329.10")
    assert padded.required_profit == Decimal("787.2750")


def test_the_same_product_may_appear_on_more_than_one_line() -> None:
    """Two kilos at list and one thrown in free is a real offer, not a mistake.

    Nothing here needs the lines to be distinct, so nothing here insists on it. Both
    lines are simply added up.
    """
    mixed = margin_on(
        Offer.of(
            Line(product=COFFEE, quantity=2, unit_price=COFFEE.list_price),
            Line(product=COFFEE, quantity=1, unit_price=Money.of("0.00", "INR")),
        )
    )

    assert mixed.revenue == Money.of("1798.00", "INR")
    assert mixed.cost == Money.of("1260.00", "INR")
    assert mixed.profit == Decimal("538.00")
    assert mixed.required_profit == Decimal("539.4000")
    assert not mixed.inside_floor


def test_a_bundle_across_two_currencies_is_refused() -> None:
    """The Desk holds no exchange rate, so there is no combined number to compute."""
    from desk.catalogue import Product

    priced_in_dollars = Product.of(
        sku="SKU-IMPORTED",
        name="Priced in dollars",
        cost="10.00",
        list_price="30.00",
        margin_floor="0.20",
        currency="USD",
    )
    with pytest.raises(CurrencyMismatch):
        Offer.of(
            Line(product=COFFEE, quantity=1, unit_price=COFFEE.list_price),
            Line(product=priced_in_dollars, quantity=1, unit_price=Money.of("30.00", "USD")),
        )


def test_a_laptop_cannot_be_floated_by_a_bag_of_coffee() -> None:
    """Subsidy is bounded by how much profit the subsidising line actually carries."""
    doomed = margin_on(
        Offer.of(
            Line(product=LAPTOP, quantity=1, unit_price=LAPTOP.discounted("0.15")),
            Line(product=COFFEE, quantity=1, unit_price=COFFEE.list_price),
        )
    )

    assert not doomed.inside_floor
    earned = Decimal("2749.15") + Decimal("479.00")
    asked = Decimal("9562.3725") + Decimal("269.7000")
    assert doomed.surplus == earned - asked

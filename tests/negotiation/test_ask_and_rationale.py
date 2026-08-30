"""What a buyer says, and what the Desk records about answering it.

Two small types with one job each. An ask is a claim and is recorded as one. A rationale
is the object three consumers read -- the trail, the control room and, later, the policy
-- so it is asserted here rather than only through a negotiation, where a shape defect
would show up as a confusing failure four modules away.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.catalogue import Line, Margin, Offer, margin_on
from desk.negotiation import Ask, Delivery, Lever, Payment, Rationale
from desk.spend import Money
from tests.negotiation.conftest import COFFEE, GRINDER


def _margin_on_grinder(discount: str) -> Margin:
    return margin_on(
        Offer.of(Line(product=GRINDER, quantity=1, unit_price=GRINDER.discounted(discount)))
    )


def test_an_ask_that_states_nothing_states_the_defaults() -> None:
    """Silence is not a constraint, and it is not a concession either."""
    ask = Ask(sku="SKU-COFFEE-1KG", quantity=1)

    assert ask.payment is Payment.ON_DELIVERY
    assert not ask.wants_it_faster
    assert ask.largest_quantity is None


def test_stating_a_constraint_is_what_makes_a_lever_available() -> None:
    ask = Ask(
        sku="SKU-COFFEE-1KG",
        quantity=2,
        largest_quantity=6,
        wants_delivery=Delivery.EXPRESS,
        can_prepay=True,
    )

    assert ask.wants_it_faster
    assert ask.payment is Payment.PREPAID
    assert ask.largest_quantity == 6


def test_the_whole_ask_goes_to_the_trail() -> None:
    """FR-6.1 wants the buyer's stated constraints, and a partial record is not them."""
    ask = Ask(
        sku="SKU-COFFEE-1KG",
        quantity=2,
        target_unit_price=Money.of("600.00", "INR"),
        largest_quantity=6,
        wants_delivery=Delivery.EXPRESS,
        can_prepay=True,
    )

    assert ask.stated() == {
        "sku": "SKU-COFFEE-1KG",
        "quantity": 2,
        "target_unit_price": "600.00 INR",
        "largest_quantity": 6,
        "wants_delivery": "express",
        "can_prepay": True,
    }


def test_an_ask_for_none_of_something_is_not_an_ask() -> None:
    with pytest.raises(ValueError, match="not an ask to buy it"):
        Ask(sku="SKU-COFFEE-1KG", quantity=0)


def test_the_most_a_buyer_would_take_is_not_less_than_what_it_asked_for() -> None:
    with pytest.raises(ValueError, match="not less than what it asked for"):
        Ask(sku="SKU-COFFEE-1KG", quantity=5, largest_quantity=2)


def test_a_rationale_carries_the_margin_the_floor_and_the_gap() -> None:
    """The three things FR-5.4 names, in the object the control room draws."""
    rationale = Rationale(asked="10% off, 1 x SKU-GRINDER-BURR", margin=_margin_on_grinder("0.10"))

    payload = rationale.as_payload()

    assert payload["asked"] == "10% off, 1 x SKU-GRINDER-BURR"
    assert payload["margin"] == "0.237877"
    assert payload["floor"] == "0.250000"
    assert payload["surplus"] == "-38.1750"
    assert payload["inside_floor"] is False
    assert payload["lever"] is None


def test_the_verdict_comes_from_the_offer_and_is_not_restated_beside_it() -> None:
    """A rationale that could disagree with its own margin would be worse than none."""
    inside = Rationale(asked="list price", margin=_margin_on_grinder("0"))

    assert inside.inside_floor is inside.margin.inside_floor is True


def test_the_lever_is_recorded_when_one_was_offered() -> None:
    rationale = Rationale(
        asked="10% off, 1 x SKU-GRINDER-BURR",
        margin=margin_on(
            Offer.of(
                Line(product=GRINDER, quantity=1, unit_price=GRINDER.discounted("0.10")),
                Line(product=COFFEE, quantity=1, unit_price=COFFEE.list_price),
            )
        ),
        lever=Lever.BUNDLE,
    )

    assert rationale.as_payload()["lever"] == "bundle"
    assert rationale.inside_floor
    assert "offering a bundle" in str(rationale)


def test_the_one_line_says_what_was_asked_and_where_the_margin_landed() -> None:
    """The line a viewer reads beside the speech bubble."""
    line = str(Rationale(asked="10% off", margin=_margin_on_grinder("0.10")))

    assert line == (
        "asked 10% off; margin 23.7877% on 3149.10 INR revenue, floor 25.0000%, "
        "short by 38.1750 INR"
    )


def test_a_rationale_reports_the_rounded_rate_and_decides_on_the_exact_one() -> None:
    """The rounded percentages are for reading; ``surplus`` is what was acted on."""
    rationale = Rationale(asked="anything", margin=_margin_on_grinder("0.10"))
    payload = rationale.as_payload()

    assert Decimal(payload["margin"]) < Decimal(payload["floor"])
    assert Decimal(payload["surplus"]) < 0

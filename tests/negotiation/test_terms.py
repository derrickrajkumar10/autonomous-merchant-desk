"""The terms sheet: what each way of doing a deal costs, and what it charges.

Two properties carry the levers that come later. Handling is flat, so a bigger order
spreads it; carry is a share, so it scales with what is actually at risk. Everything
else here is refusing to price a deal the sheet cannot price.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.catalogue import Line, Offer, margin_on
from desk.negotiation import CARRY, EXPRESS, HANDLING, Delivery, Payment, Terms, TermsSheet
from desk.spend import CurrencyMismatch, Money
from tests.negotiation.conftest import COFFEE, LAPTOP, TERMS

DEFAULT = Terms()
FAST = Terms(delivery=Delivery.EXPRESS)
PREPAID = Terms(payment=Payment.PREPAID)


def _labels(terms: Terms, goods: str) -> list[str]:
    return [charge.label for charge in TERMS.charges(terms, goods=Money.of(goods, "INR"))]


def test_every_deal_is_packed_and_sent() -> None:
    """Handling is on every offer, because every offer is put in a box."""
    assert _labels(DEFAULT, "899.00")[0] == HANDLING


def test_a_charge_appears_only_where_the_terms_moved() -> None:
    """An offer's charges read as what was traded, not as a standing tariff."""
    assert _labels(PREPAID, "899.00") == [HANDLING]
    assert _labels(DEFAULT, "899.00") == [HANDLING, CARRY]
    assert _labels(FAST, "899.00") == [HANDLING, EXPRESS, CARRY]


def test_handling_is_the_same_on_a_big_order_as_on_a_small_one() -> None:
    """The flat cost a quantity break spreads. One assertion, and the lever rests on it."""
    small = TERMS.charges(DEFAULT, goods=Money.of("899.00", "INR"))[0]
    large = TERMS.charges(DEFAULT, goods=Money.of("4495.00", "INR"))[0]

    assert small.cost == large.cost == Money.of("60.00", "INR")


def test_waiting_for_money_costs_a_share_of_it_and_not_a_flat_fee() -> None:
    """Thirty days on a laptop ties up eighty times what thirty days on coffee does.

    A flat carry cost would be the same mistake as a flat price floor -- right for the
    one deal it was set on and wrong for every other.
    """
    net_30 = Terms(payment=Payment.NET_30)

    coffee = TERMS.charges(net_30, goods=COFFEE.list_price)[-1]
    laptop = TERMS.charges(net_30, goods=LAPTOP.list_price)[-1]

    assert coffee.cost == Money.of("26.97", "INR")
    assert laptop.cost == Money.of("2249.97", "INR")


def test_prepayment_costs_nothing_to_carry() -> None:
    """Money the Desk already has is not money it is waiting for."""
    assert CARRY not in _labels(PREPAID, "74999.00")


def test_express_delivery_puts_more_in_than_it_takes_out() -> None:
    """ "At a premium" in FR-5.3 means the Desk sells speed rather than giving it away."""
    express = TERMS.charges(FAST, goods=COFFEE.list_price)[1]

    assert express.revenue - express.cost == Money.of("160.00", "INR")


def test_the_terms_change_the_verdict_on_a_real_offer() -> None:
    """The sheet is not decoration: its charges go through the same floor test.

    Twenty-two percent off a single kilo of coffee holds when it is paid for up front.
    The same twenty-two percent at thirty days does not, because three percent of the
    goods is money the Desk is out of pocket while it waits.
    """
    line = Line(product=COFFEE, quantity=1, unit_price=COFFEE.discounted("0.22"))
    goods = line.revenue

    prompt = margin_on(Offer.of(line, charges=TERMS.charges(PREPAID, goods=goods)))
    waiting = margin_on(
        Offer.of(line, charges=TERMS.charges(Terms(payment=Payment.NET_30), goods=goods))
    )

    assert prompt.inside_floor
    assert not waiting.inside_floor


def test_the_sheet_refuses_goods_in_another_currency() -> None:
    with pytest.raises(CurrencyMismatch):
        TERMS.charges(DEFAULT, goods=Money.of("100.00", "USD"))


def test_a_sheet_that_cannot_cost_a_term_it_could_agree_to_is_refused() -> None:
    """A term the Desk can say yes to and cannot price is one it would agree to blind."""
    with pytest.raises(ValueError, match="prices no carry cost"):
        TermsSheet(
            currency="INR",
            handling=Money.of("60.00", "INR"),
            express_premium=Money.of("400.00", "INR"),
            express_cost=Money.of("240.00", "INR"),
            carry={Payment.PREPAID: Decimal("0")},
        )


def test_a_carry_rate_is_a_share_of_the_goods() -> None:
    with pytest.raises(ValueError, match="carry rate is a share"):
        TermsSheet(
            currency="INR",
            handling=Money.of("60.00", "INR"),
            express_premium=Money.of("400.00", "INR"),
            express_cost=Money.of("240.00", "INR"),
            carry=dict.fromkeys(Payment, Decimal("1.5")),
        )


def test_a_sheet_is_written_in_one_currency() -> None:
    with pytest.raises(CurrencyMismatch):
        TermsSheet(
            currency="INR",
            handling=Money.of("60.00", "USD"),
            express_premium=Money.of("400.00", "INR"),
            express_cost=Money.of("240.00", "INR"),
            carry=dict.fromkeys(Payment, Decimal("0")),
        )


def test_the_default_terms_are_the_ones_nobody_asked_for() -> None:
    """Anything that is not the default was traded for, which is what makes an offer readable."""
    assert Terms() == Terms(delivery=Delivery.STANDARD, payment=Payment.ON_DELIVERY)
    assert Terms().as_claims() == {"delivery": "standard", "payment": "on_delivery"}

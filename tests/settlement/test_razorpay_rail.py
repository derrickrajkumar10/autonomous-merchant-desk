"""The Razorpay adapter: the paise conversion, the shapes, and one real call.

Two kinds of test, and the split is the point.

**Most of them need no network.** The adapter is handed a stand-in client that answers
the way Razorpay's SDK answers, and what is asserted is the translation: rupees to
whole paise, Razorpay's collection of payments to one ``RailCharge``, an exception from
somebody else's client to a charge that did not complete rather than to a raise on the
money path. None of that needs Razorpay to be up, and none of it is about Razorpay --
it is about what this file does with what Razorpay says.

**One of them talks to the real test-mode API** and is marked ``razorpay``, skipped
unless credentials are set. It exists because the translation being right proves nothing
if the call sequence is wrong, and the only way to find that out is to make the call.
What it can assert is bounded by what Razorpay's API allows headlessly: a real order
with a real identifier is created, and nothing has been paid against it, because a
payment on an order is made by a payer through Checkout. ``razorpay_rail.py``'s
docstring sets out why that is the rail's shape rather than a gap in it.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from desk.settlement import (
    KEY_ID_VAR,
    KEY_SECRET_VAR,
    Charge,
    RailNotConfigured,
    RazorpayRail,
    from_minor_units,
    in_minor_units,
)
from desk.spend import Money

A_DEAL = "MTIzNDU2Nzg5MGFiY2RlZg"


def rupees(amount: str) -> Money:
    return Money.of(amount, "INR")


def a_charge(amount: str = "1500.00") -> Charge:
    return Charge(
        amount=rupees(amount),
        reference=A_DEAL,
        agent_id="agent-whoever",
        description="a test charge",
    )


class StandInClient:
    """What Razorpay's SDK looks like from this adapter: two calls on ``order``."""

    def __init__(self, payments: Any, order_id: str = "order_STANDIN00001") -> None:
        self.order = _Orders(payments, order_id)
        self.created: list[dict[str, Any]] = self.order.created


class _Orders:
    def __init__(self, payments: Any, order_id: str) -> None:
        self._payments = payments
        self._order_id = order_id
        self.created: list[dict[str, Any]] = []

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        self.created.append(body)
        return {"id": self._order_id, "amount": body["amount"], "status": "created"}

    def payments(self, order_id: str) -> Any:
        if isinstance(self._payments, Exception):
            raise self._payments
        return self._payments


def captured(amount: int = 150000) -> dict[str, Any]:
    return {"items": [{"id": "pay_STANDIN000001", "status": "captured", "amount": amount}]}


def test_rupees_become_whole_paise() -> None:
    """A rounding here is money, so the conversion is exact or it does not happen."""
    assert in_minor_units(rupees("1500.00")) == 150000
    assert in_minor_units(rupees("0.01")) == 1
    assert in_minor_units(rupees("1234.56")) == 123456
    assert from_minor_units(123456, "INR") == rupees("1234.56")


def test_an_amount_finer_than_a_paise_is_refused_rather_than_rounded() -> None:
    """Rounding up and rounding down are both the Desk moving a different amount of
    money from the one that was agreed, so neither happens."""
    with pytest.raises(ValueError, match="smaller than a paise"):
        in_minor_units(Money.of("1500.005", "INR"))


def test_a_currency_this_rail_is_not_configured_for_is_refused() -> None:
    """Multiple currencies are out of scope, and a silent conversion would be worse."""
    with pytest.raises(ValueError, match="configured for INR"):
        in_minor_units(Money.of("10.00", "USD"))


def test_a_captured_payment_is_a_completed_charge() -> None:
    """And it carries both of Razorpay's identifiers, because a person looking this up
    afterwards may have either."""
    rail = RazorpayRail(StandInClient(captured()))

    outcome = rail.charge(a_charge())

    assert outcome.completed
    assert outcome.rail == "razorpay"
    assert outcome.status == "captured"
    assert outcome.charge_id == "pay_STANDIN000001"
    assert outcome.order_id == "order_STANDIN00001"


def test_the_order_is_created_in_paise_and_names_the_deal() -> None:
    """So that Razorpay's own record and the Desk's point at each other."""
    client = StandInClient(captured())
    RazorpayRail(client).charge(a_charge())

    assert client.created[0]["amount"] == 150000
    assert client.created[0]["currency"] == "INR"
    assert client.created[0]["notes"]["deal"] == A_DEAL
    assert client.created[0]["notes"]["agent_id"] == "agent-whoever"


def test_an_authorised_payment_is_not_a_completed_charge() -> None:
    """Money held is not money taken, and a receipt for it would say something false."""
    rail = RazorpayRail(StandInClient({"items": [{"id": "pay_x", "status": "authorized"}]}))

    outcome = rail.charge(a_charge())

    assert not outcome.completed
    assert outcome.status == "awaiting_payment"
    assert outcome.order_id == "order_STANDIN00001"


def test_an_order_nobody_has_paid_is_a_charge_that_did_not_complete() -> None:
    """The ordinary headless case against test mode, reported as what it is."""
    rail = RazorpayRail(StandInClient({"items": []}))

    outcome = rail.charge(a_charge())

    assert not outcome.completed
    assert outcome.status == "awaiting_payment"
    assert outcome.charge_id is None


def test_a_client_that_raises_becomes_a_charge_that_did_not_complete() -> None:
    """Not a raise on the money path.

    A third party's client can go wrong in ways their next release will add to, and an
    unhandled one of those between the order and the answer is the worst place in the
    system for a surprise.
    """
    rail = RazorpayRail(StandInClient(RuntimeError("gateway timeout")))

    outcome = rail.charge(a_charge())

    assert not outcome.completed
    assert outcome.status == "not_reached"
    assert outcome.detail is not None and "gateway timeout" in outcome.detail


def test_a_rail_with_no_credentials_refuses_to_be_built() -> None:
    """At start-up rather than half way through a deal."""
    with pytest.raises(RailNotConfigured, match="rzp_test_"):
        RazorpayRail(key_id="", key_secret="")


@pytest.mark.razorpay
def test_a_real_test_mode_order_is_created() -> None:
    """The one call that goes over the network. The integration and the identifiers.

    What this proves is that the call sequence is right and the identifiers are real --
    the part no stand-in can tell us. It cannot prove a capture: a payment against an
    order is made by a payer through Razorpay's Checkout, so a headless run correctly
    reports that nothing has been paid yet.
    """
    if not (os.environ.get(KEY_ID_VAR) and os.environ.get(KEY_SECRET_VAR)):
        pytest.skip(f"set {KEY_ID_VAR} and {KEY_SECRET_VAR} to run against Razorpay test mode")

    outcome = RazorpayRail().charge(a_charge())

    assert outcome.rail == "razorpay"
    assert outcome.order_id is not None
    assert outcome.order_id.startswith("order_"), outcome.detail
    assert not outcome.completed
    assert outcome.status == "awaiting_payment"

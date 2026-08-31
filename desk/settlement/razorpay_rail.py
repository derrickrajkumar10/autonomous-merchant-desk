"""Razorpay test mode, behind the rail boundary.

**Test mode moves no real money, and that is the point rather than a compromise.** What
a test-mode integration exercises is the part that is actually hard to get right: the
call sequence, the identifiers, the shapes that come back, and what happens when a
charge does not complete. The one thing it does not exercise is the settling of real
funds, which is also the one thing nobody would want a demonstration to do.

**Two calls, because Razorpay's model has two objects.** An *order* is the merchant
saying what it wants paid; a *payment* is the money against it. The Desk creates the
order and then looks for the payment, and keeps both identifiers, because a person
looking this charge up in Razorpay's dashboard afterwards may have either.

**The honest limit, stated here rather than discovered later.** A payment against an
order is made by the *payer*, through Razorpay's Checkout, in a browser -- test mode
included. There is no server-side call, in test mode or out of it, that makes a payment
appear on an order without one, unless the account has server-to-server payments
specifically enabled. So a headless run of this rail creates a real order with a real
identifier and then honestly reports that nothing has been paid against it yet. That is
not a gap in this module; it is what Razorpay's API is. It is also most of why the
boundary in ``rail.py`` exists: the Desk's own behaviour on a completed charge, on an
incomplete one, and on the ledger underneath both, is tested against a substituted rail
that can produce either on demand, and this module is tested for the thing only it can
be tested for -- that the call sequence and the identifiers are real.

**Amounts are integer paise.** Razorpay takes the smallest currency unit as a whole
number, which is the right decision on their side and a trap on ours: 1,500.00 rupees
is 150000, and a rounding here is money. So the conversion is one function, it refuses
anything with sub-paise precision rather than rounding it away, and a test covers it.
``Money`` is a ``Decimal`` throughout precisely so this conversion is exact.

**What is not here.** Refunds, chargebacks, reversals and adjustments are out of scope
for this ticket and for the project (CONTEXT.md section 7a). Webhooks are not read: the
Desk asks and gets an answer synchronously, and a charge it never got an answer about
shows up as an attempt with nothing after it in the trail.

The SDK is an optional dependency. A Desk that never settles against the real rail --
every test but the handful marked ``razorpay`` -- does not need it installed, so the
import happens when a rail is constructed rather than when this module is read.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from desk.settlement.rail import Charge, RailCharge
from desk.spend.money import Money

#: What this rail calls itself on a receipt and in the trail.
RAIL = "razorpay"

#: Razorpay's own words for a payment that has been taken. Anything else is a charge
#: that did not complete -- including ``authorized``, which is money held and not taken.
COMPLETED_STATUSES = frozenset({"captured"})

#: The environment variables the test-mode keys are read from. Named after Razorpay's
#: own dashboard labels so that whoever is copying them across is not translating.
KEY_ID_VAR = "RAZORPAY_KEY_ID"
KEY_SECRET_VAR = "RAZORPAY_KEY_SECRET"

#: Paise per rupee. Razorpay's unit for INR, and the only currency this ticket handles.
MINOR_UNITS = 100


class RailNotConfigured(RuntimeError):
    """No test-mode credentials, so there is no rail to talk to.

    Raised when the rail is built rather than when a charge is attempted, so that a
    misconfigured Desk stops at start-up instead of half way through a deal.
    """


def in_minor_units(amount: Money) -> int:
    """Rupees as whole paise, refusing anything that would have to be rounded.

    A charge of 1,500.005 is not a charge Razorpay can take, and the two ways to make
    it into one -- rounding up or down -- are both the Desk deciding to move a different
    amount of money from the one that was agreed. So neither happens.
    """
    if amount.currency != "INR":
        raise ValueError(
            f"this rail is configured for INR and was handed {amount.currency}. "
            f"Multiple currencies are out of scope for this ticket."
        )
    minor = amount.amount * MINOR_UNITS
    if minor != minor.to_integral_value():
        raise ValueError(
            f"{amount} is smaller than a paise can express, and a charge rounded to fit "
            f"is a different amount from the one that was agreed"
        )
    return int(minor)


def from_minor_units(minor: int, currency: str) -> Money:
    """The other direction, for reading back what the rail says it took."""
    return Money(amount=Decimal(minor) / MINOR_UNITS, currency=currency)


class RazorpayRail:
    """The Desk's charges, taken against Razorpay's test-mode APIs.

    Satisfies ``PaymentRail``. A charge that Razorpay declines, or that comes back in
    any state other than captured, is a ``RailCharge`` with ``completed`` false and
    Razorpay's own words on it -- not an exception, because a declined card is an
    ordinary outcome and the Desk has a correct answer for it.
    """

    def __init__(
        self, client: Any | None = None, *, key_id: str | None = None, key_secret: str | None = None
    ) -> None:
        if client is not None:
            self._client = client
            return

        key_id = key_id if key_id is not None else os.environ.get(KEY_ID_VAR)
        key_secret = key_secret if key_secret is not None else os.environ.get(KEY_SECRET_VAR)
        if not key_id or not key_secret:
            raise RailNotConfigured(
                f"no Razorpay test-mode credentials: set {KEY_ID_VAR} and {KEY_SECRET_VAR}, "
                f"or hand this rail a client. Test mode keys start with 'rzp_test_'."
            )
        try:
            import razorpay
        except ImportError as exc:  # pragma: no cover - depends on the local install
            raise RailNotConfigured(
                "the razorpay SDK is not installed. It is in the 'rail' extra, which a "
                "Desk that only settles against a substituted rail does not need."
            ) from exc
        self._client = razorpay.Client(auth=(key_id, key_secret))

    def charge(self, charge: Charge) -> RailCharge:
        """Create an order, look for the payment against it, and report what happened.

        Every way this can go other than a captured payment produces the same shape:
        ``completed`` false, with whatever the rail said in ``status`` and ``detail``.
        A caller cannot tell a declined card from an unreachable rail from this, and
        should not: the Desk's response is the same either way, and the difference is
        recorded in the trail for whoever is debugging rather than deciding.
        """
        minor = in_minor_units(charge.amount)

        # Two calls, caught separately, because they leave the Desk knowing different
        # amounts. If the order was never created there is nothing to name; if it was
        # and the lookup went wrong, an order really exists on Razorpay and the trail
        # should carry its identifier -- otherwise the one handle to it is lost at the
        # moment somebody most needs it.
        #
        # Both catches are deliberately broad. Every way a third party's client can go
        # wrong means the same thing here -- the Desk does not know that money moved --
        # and a narrower catch would turn an SDK release adding an exception type into an
        # unhandled raise on the money path.
        try:
            order = self._client.order.create(
                {
                    "amount": minor,
                    "currency": charge.amount.currency,
                    "receipt": charge.reference[:40],
                    "notes": {"agent_id": charge.agent_id, "deal": charge.reference},
                }
            )
        except Exception as exc:  # noqa: BLE001 - the SDK raises its own hierarchy
            return RailCharge(
                rail=RAIL,
                completed=False,
                status="not_reached",
                detail=f"{type(exc).__name__}: {exc}",
            )

        try:
            payment = self._client.order.payments(order["id"])
        except Exception as exc:  # noqa: BLE001 - the SDK raises its own hierarchy
            return RailCharge(
                rail=RAIL,
                completed=False,
                status="not_reached",
                order_id=order.get("id"),
                detail=f"{type(exc).__name__}: {exc}",
            )

        taken = _captured(payment)
        if taken is None:
            return RailCharge(
                rail=RAIL,
                completed=False,
                status="awaiting_payment",
                order_id=order.get("id"),
                detail=(
                    "the order exists on the rail and nothing has been captured against "
                    "it; a payer makes a payment through Razorpay's Checkout"
                ),
            )
        return RailCharge(
            rail=RAIL,
            completed=True,
            status=str(taken.get("status")),
            charge_id=str(taken.get("id")),
            order_id=order.get("id"),
        )


def _captured(payments: Any) -> dict[str, Any] | None:
    """The first captured payment in what the rail returned, if there is one.

    Razorpay answers with a collection, because an order may be attempted more than
    once. The Desk wants the one that was actually taken and treats everything else --
    an authorised payment, a failed attempt, an empty collection -- as not completed.
    """
    if not isinstance(payments, dict):
        return None
    items = payments.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("status") in COMPLETED_STATUSES:
            return item
    return None

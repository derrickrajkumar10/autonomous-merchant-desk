"""The terms of a deal, and what each of them costs -- which is what makes two levers real.

A price is not the whole of a deal. When it arrives, and when it is paid for, are both
part of what was agreed, and both cost the Desk something it can name:

- **Delivery.** Standard is whatever the handling charge already covers. Express is a
  courier, and a courier sends a bill.
- **Payment.** Prepaid money is money the Desk has. Money owed for thirty days is money
  it has to carry, and carrying money costs a share of it.

Those costs are why *delivery speed* and *payment terms* are levers rather than
courtesies. Offering express delivery at a premium puts more into a deal than it takes
out. Getting paid up front takes a cost out of a deal that was there before. Either one
buys room the goods did not have.

**Handling is flat and carry is proportional, and the difference is the point.** Packing
a box and getting it to a courier is the same work for one kilo of coffee as for five,
so it is one fixed amount per deal -- which is precisely what a quantity break spreads
thinner. Financing is not like that: waiting thirty days for 75,000 rupees ties up
eighty times what waiting for 899 does. A flat carry cost would be the same mistake as a
flat price floor, wrong for every deal except the one it was set on (CONTEXT.md section
6). So it is a share of what the goods come to.

**A share of the goods, not of the deal.** The carry cost has to be computed from
something that is already known, and the deal's own total is not -- it includes the
charges, one of which is this. Financing is against the value of what was sold, which is
both well defined and the honest reading.

The numbers themselves are the world's, not the Desk's. ``world/storefront/terms.py``
holds the sheet the Desk actually runs on, for the same reason the catalogue's contents
live out there: what a merchant charges for express delivery is not the defensible part.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from desk.catalogue import Charge
from desk.spend import CurrencyMismatch, Money

#: What the handling charge is called on an offer and in a closed mandate.
HANDLING = "handling"

#: What the express-delivery charge is called. Absent entirely on a standard delivery,
#: rather than present at zero: a charge of nothing is a line the buyer has to read.
EXPRESS = "express delivery"

#: What the cost of waiting to be paid is called.
CARRY = "payment terms"


class Delivery(StrEnum):
    """How fast the thing arrives."""

    STANDARD = "standard"
    EXPRESS = "express"


class Payment(StrEnum):
    """When the Desk gets its money."""

    PREPAID = "prepaid"
    ON_DELIVERY = "on_delivery"
    NET_30 = "net_30"


@dataclass(frozen=True)
class Terms:
    """Everything about a deal that is not the price or the goods.

    Defaults are the ones a buyer gets without asking for anything: it arrives normally
    and it is paid for when it arrives. Both levers move away from a default, which is
    what makes an offer's terms readable at a glance -- anything that is not the default
    was traded for.
    """

    delivery: Delivery = Delivery.STANDARD
    payment: Payment = Payment.ON_DELIVERY

    def as_claims(self) -> dict[str, str]:
        """The terms as a closed Checkout Mandate carries them: plain strings."""
        return {"delivery": self.delivery.value, "payment": self.payment.value}


@dataclass(frozen=True)
class TermsSheet:
    """What each set of terms costs the Desk and charges the buyer.

    One sheet per Desk, in one currency. A deal in another currency is not one this
    sheet can price, and it says so rather than converting -- the Desk holds no exchange
    rate, and inventing one here would put a made-up number inside a margin decision.
    """

    currency: str
    handling: Money
    express_premium: Money
    express_cost: Money
    carry: dict[Payment, Decimal]

    def __post_init__(self) -> None:
        for role, amount in (
            ("handling", self.handling),
            ("express premium", self.express_premium),
            ("express cost", self.express_cost),
        ):
            if not isinstance(amount, Money):
                raise TypeError(f"a terms sheet's {role} is Money, not {type(amount).__name__}")
            if amount.currency != self.currency:
                raise CurrencyMismatch(
                    f"this sheet is written in {self.currency} and its {role} is in "
                    f"{amount.currency}"
                )
        missing = set(Payment) - set(self.carry)
        if missing:
            raise ValueError(
                f"the sheet prices no carry cost for {', '.join(sorted(missing))}; a term "
                f"the Desk can agree to and cannot cost is one it would agree to blind"
            )
        for terms, rate in self.carry.items():
            if not isinstance(rate, Decimal):
                raise TypeError(f"a carry rate is a Decimal, not a {type(rate).__name__}")
            if not rate.is_finite() or not (0 <= rate < 1):
                raise ValueError(
                    f"{terms} carries at {rate}; a carry rate is a share of the goods in "
                    f"[0, 1), and 1 would mean waiting cost everything the goods earned"
                )

    def charges(self, terms: Terms, *, goods: Money) -> tuple[Charge, ...]:
        """The charges these terms put on a deal whose goods come to ``goods``.

        Always at least the handling charge, because every deal is packed and sent. The
        other two appear only when the terms moved away from their default, so an offer's
        charges read as a list of what was traded rather than as a standing tariff.
        """
        if goods.currency != self.currency:
            raise CurrencyMismatch(
                f"this sheet prices deals in {self.currency} and these goods come to "
                f"{goods}; the Desk holds no exchange rate"
            )

        charges = [Charge(label=HANDLING, revenue=self._nil(), cost=self.handling)]
        if terms.delivery is Delivery.EXPRESS:
            charges.append(
                Charge(label=EXPRESS, revenue=self.express_premium, cost=self.express_cost)
            )
        carried = self._carried(terms.payment, goods)
        if carried.amount > 0:
            charges.append(Charge(label=CARRY, revenue=self._nil(), cost=carried))
        return tuple(charges)

    def _carried(self, payment: Payment, goods: Money) -> Money:
        """What waiting for this money costs, rounded the way a price is rounded.

        Half up, toward the Desk recognising the cost, for the same reason a discount
        rounds toward the Desk: a rounding rule should never quietly hand out the benefit
        of a doubt on the Desk's behalf.

        The grid it lands on is ``Money.scale``'s, which is the grid a discounted price
        lands on too. Two computations about one deal that rounded differently would
        disagree by a paisa, and would do it invisibly.
        """
        amount = (self.carry[payment] * goods.amount).quantize(
            goods.scale(), rounding=ROUND_HALF_UP
        )
        return Money(amount=amount, currency=self.currency)

    def _nil(self) -> Money:
        return Money(amount=Decimal(0), currency=self.currency)

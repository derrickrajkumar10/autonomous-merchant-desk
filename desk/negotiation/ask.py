"""What a buyer says it wants, which is not the same as what is true.

Nothing in here is believed. An ask is a counterparty's own account of its position --
what it wants to buy, what it says it will pay, and what it says it could live with --
and the Desk treats every field as a claim rather than a fact. It cannot do otherwise:
a buyer that says it will pay no more than 600 may be telling the truth or may be
negotiating, and there is no check that tells those apart.

What the Desk can do is make the claims *load-bearing in the buyer's own direction*.
Each stated constraint unlocks exactly one lever, and each lever costs the buyer
something it said it did not mind:

============================  ===============================================
Stated                        What it makes available
============================  ===============================================
``largest_quantity`` above     a quantity break -- more units, better rate
the quantity asked for
``wants_delivery`` express     express delivery, at a premium
``can_prepay``                 a better price for money that arrives sooner
============================  ===============================================

A buyer that overstates gets an offer built on the overstatement, and one that
understates gets fewer levers reached for. Neither is a hole, because the floor is
tested on the offer that actually results -- a lie about what a buyer wants cannot make
an unprofitable deal profitable.

The fourth lever, a bundle, is the one no ask can request. The companion product has to
be something the *principal* authorised, which is read off the verified mandate and not
off anything the agent says. See ``policy.py``.

The whole ask is written to the trail on every negotiation, because FR-6.1 asks for the
buyer's stated constraints and ticket 21 has to be able to learn from them. What is
recorded is the claim, labelled as a claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desk.negotiation.terms import Delivery, Payment
from desk.spend import Money


@dataclass(frozen=True)
class Ask:
    """One thing a buyer wants, and the constraints it states around wanting it."""

    sku: str
    quantity: int
    #: What it says it will pay for each one. ``None`` on an opening ask that names no
    #: number, which is a buyer asking what the thing costs rather than haggling.
    target_unit_price: Money | None = None
    #: The most it would take. ``None`` means the quantity is firm, which is the
    #: assumption a quantity break must not be built on.
    largest_quantity: int | None = None
    #: Faster than standard, if it said so. ``None`` is no stated preference, which is
    #: not the same as not wanting it -- only that the Desk was not told.
    wants_delivery: Delivery | None = None
    #: Whether it says it can pay up front.
    can_prepay: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.sku, str) or not self.sku:
            raise ValueError("an ask names what it is for")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError(f"a quantity is a whole count, not a {type(self.quantity).__name__}")
        if self.quantity < 1:
            raise ValueError(
                f"an ask for {self.quantity} of {self.sku} is not an ask to buy it"
            )
        if self.target_unit_price is not None and not isinstance(self.target_unit_price, Money):
            raise TypeError("a target price is Money, or it is absent")
        if self.largest_quantity is not None:
            if isinstance(self.largest_quantity, bool) or not isinstance(
                self.largest_quantity, int
            ):
                raise TypeError("the largest quantity a buyer would take is a whole count")
            if self.largest_quantity < self.quantity:
                raise ValueError(
                    f"this ask says it wants {self.quantity} and would take at most "
                    f"{self.largest_quantity}; the most it would take is not less than "
                    f"what it asked for"
                )

    @property
    def payment(self) -> Payment:
        """The best payment terms this ask says it can meet."""
        return Payment.PREPAID if self.can_prepay else Payment.ON_DELIVERY

    @property
    def wants_it_faster(self) -> bool:
        return self.wants_delivery is Delivery.EXPRESS

    def stated(self) -> dict[str, Any]:
        """The constraints as the trail records them (FR-6.1), claims and all."""
        return {
            "sku": self.sku,
            "quantity": self.quantity,
            "target_unit_price": (
                None if self.target_unit_price is None else str(self.target_unit_price)
            ),
            "largest_quantity": self.largest_quantity,
            "wants_delivery": None if self.wants_delivery is None else self.wants_delivery.value,
            "can_prepay": self.can_prepay,
        }

"""The four levers, and why the set is closed.

A merchant that can only move price has one thing to say to a buyer who cannot afford
the price: no. A **lever** is anything else it can change about the shape of a deal so
that the answer becomes yes without the floor being crossed.

The vocabulary is deliberate (CONTEXT.md section 6). These are *levers* and not
*discounts*, because a discount is money given away and a lever is a trade -- the Desk
gets something back for each one, and that something is what pays for the concession.

- **Quantity break.** More units. The fixed work of putting a deal out of the door does
  not double when the order does, so a bigger order spreads it thinner and a lower rate
  becomes affordable.
- **Bundle.** A second product beside the first, at list. The pair is decided as one
  deal, so the companion's margin carries a concession the first product could not.
- **Delivery speed.** Faster, at a premium. The buyer pays more and the courier takes
  some of it, and what is left is margin the goods did not have to find.
- **Payment terms.** Paying sooner. Money the Desk is not waiting for costs it nothing
  to carry, and that saving is what funds the lower price.

**The set is closed and adding to it is a deliberate act.** Ticket 21 makes the choice
of lever a contextual bandit, and a bandit needs a fixed action space: an action that
appeared halfway through a run would make everything learned before it incomparable
with everything after. So a new lever is a new member here, a new arm there, and a
decision about whether the old data still counts -- which is exactly the amount of
friction it should have.

**No member for "a lower price".** Price is the axis being negotiated rather than a
lever on it, and a member called ``discount`` would let the policy learn to reach for
the one move that never earns anything back. A Desk message that concedes on price and
nothing else records no lever, and the trail says so with an absent one rather than a
present nothing.
"""

from __future__ import annotations

from enum import StrEnum


class Lever(StrEnum):
    """A non-price move the Desk can make. The whole action space, and it is four wide."""

    QUANTITY_BREAK = "quantity_break"
    BUNDLE = "bundle"
    DELIVERY_SPEED = "delivery_speed"
    PAYMENT_TERMS = "payment_terms"


#: The order the fixed policy considers them in, written once so that reordering the
#: policy is a visible edit to a named sequence. Cheapest to the Desk first: a bundle
#: and a quantity break sell more of what it already stocks, and the two that change
#: the terms of the deal come after.
CONSIDERED: tuple[Lever, ...] = (
    Lever.BUNDLE,
    Lever.QUANTITY_BREAK,
    Lever.DELIVERY_SPEED,
    Lever.PAYMENT_TERMS,
)

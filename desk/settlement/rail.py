"""The payment rail, as a boundary rather than as a vendor.

One protocol with one method. Everything the Desk needs from a payment rail is *take
this amount and tell me what happened*, and everything it needs back is whether the
money moved and what the rail calls the thing that moved it.

**Why the boundary is here and not around the SDK.** A rail is the one collaborator
the Desk cannot make behave. A charge that does not complete is an ordinary outcome, not
a fault -- a card is declined, a test-mode account is out of whatever test mode has --
and it is the outcome the correctness core of this ticket turns on. A suite that could
only produce it by having a third party's server be down that day would not test it at
all. So the interface is narrow enough that a test can implement it in a dozen lines,
and ``razorpay_rail.py`` is one implementation of it rather than the thing itself.

**Why ``RailCharge`` carries the rail's own words.** ``status`` and ``detail`` are
whatever the rail said, unmapped. The Desk decides one thing about them -- ``completed``
-- and records the rest verbatim, so that a receipt can be traced back to the rail's own
record of it (FR-7.4) and a run can be argued about afterwards with the rail's vocabulary
rather than ours. Mapping every rail status onto a Desk enum would be inventing a
vocabulary for somebody else's system, and the mapping would be the thing that rots.

Nothing here writes to the trail or touches the ledger. This layer's whole job is to
turn a network call into a value; ``settle.py`` decides what it means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from desk.spend.money import Money


@dataclass(frozen=True)
class Charge:
    """What the Desk asks a rail to take, and what it says the charge is for.

    ``reference`` is the closed Checkout Mandate's hash -- the name of the deal being
    settled. It goes to the rail so that the rail's own record and the Desk's point at
    each other, which is what makes "trace this charge back" answerable from either end.
    """

    amount: Money
    reference: str
    agent_id: str
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Money):
            raise TypeError(f"a charge is for Money, not a {type(self.amount).__name__}")
        if self.amount.amount <= 0:
            raise ValueError(f"a charge of {self.amount} is not a charge")
        if not self.reference.strip():
            raise ValueError("a charge names the deal it settles")
        if not self.agent_id.strip():
            raise ValueError("a charge names who it is being taken from")


@dataclass(frozen=True)
class RailCharge:
    """What the rail says came of it.

    ``completed`` is the Desk's reading and the only judgment in here; everything else
    is the rail's account of itself, kept as the rail worded it.
    """

    rail: str
    completed: bool
    status: str
    charge_id: str | None = None
    order_id: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.rail.strip():
            raise ValueError("a charge outcome names the rail it came from")
        if not self.status.strip():
            raise ValueError("a charge outcome carries the rail's own status")
        if self.completed and not (self.charge_id or "").strip():
            raise ValueError(
                "a completed charge carries the rail's identifier for it. Without one "
                "the receipt could not be traced back to the rail, which is most of "
                "what a receipt is for."
            )

    def as_claim(self) -> dict[str, str | None]:
        """The rail's identifiers as they are bound into a receipt."""
        return {
            "rail": self.rail,
            "status": self.status,
            "charge_id": self.charge_id,
            "order_id": self.order_id,
        }


class PaymentRail(Protocol):
    """Whatever can take a charge. One method, so that a test can be one.

    Implementations do not raise for a charge that did not complete -- that is a
    ``RailCharge`` with ``completed`` false, because it is an outcome and not a fault.
    A rail that cannot be reached at all *may* raise, and ``settle.py`` treats that the
    way it treats any charge it never got an answer about: nothing is recorded, and the
    attempt already written to the trail is what shows it happened.
    """

    def charge(self, charge: Charge) -> RailCharge: ...

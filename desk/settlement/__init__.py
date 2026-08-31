"""Settlement -- where an agreed deal becomes money, and evidence that it did.

Everything before this was the Desk deciding. Checks 1 to 4 said the request was
authentic, authorised, inside a ceiling and not a replay. The negotiation reached terms
and signed a closed Checkout Mandate saying what they were. None of it moved a rupee,
and none of it produced anything a third party could check.

This package closes both gaps, and the second one is the larger. It is being built up a
piece at a time; what is here so far is the boundary the payment rail sits behind, and
one implementation of it.
"""

from desk.settlement.rail import Charge, PaymentRail, RailCharge
from desk.settlement.razorpay_rail import (
    KEY_ID_VAR,
    KEY_SECRET_VAR,
    MINOR_UNITS,
    RAIL,
    RailNotConfigured,
    RazorpayRail,
    from_minor_units,
    in_minor_units,
)

__all__ = [
    "KEY_ID_VAR",
    "KEY_SECRET_VAR",
    "MINOR_UNITS",
    "RAIL",
    "Charge",
    "PaymentRail",
    "RailCharge",
    "RailNotConfigured",
    "RazorpayRail",
    "from_minor_units",
    "in_minor_units",
]

"""The trust spine -- checks 1 to 4, run in one order, on one request.

The four deterministic checks each arrived with its own ticket and its own package:
``desk.identity`` proves who is asking, ``desk.mandate`` proves a human authorised it,
``desk.spend`` proves what is asked for is inside that authorisation, and
``desk.freshness`` proves this is happening now and only once. This package is the
thing that runs them, and it is the only place in ``desk/`` where the *order* of the
checks is written down.

That order is the point. Cheap and certain before expensive and probabilistic, and a
refusal stops everything after it, so the trail can afterwards be read as *which
condition stopped this, and nothing later ran*. ``spine.py`` sets out why each of those
two sentences is a security property rather than a tidiness one.

    from desk.spine import TrustSpine

    outcome = TrustSpine(identity, mandate, spend, freshness, trail).receive(request)
    if outcome.passed:
        ...        # outcome.remaining is what closing this deal would leave

Nothing here decides whether a deal happens. Passing the spine means a request is
authentic, authorised, affordable and fresh -- it does not mean the text inside it is
safe (check 5), that a price has been agreed (negotiation), or that anything has been
paid (settlement).
"""

from desk.spine.request import (
    AMOUNT,
    CHECKOUT,
    CURRENCY,
    ENQUIRY,
    ITEM_ID,
    PAYMENT,
    PurchaseRequest,
    read_purchase_request,
)
from desk.spine.spine import (
    IDENTITY,
    MANDATE_VALIDITY,
    ORDER,
    REPLAY_AND_FRESHNESS,
    SPEND_AUTHORITY,
    Check,
    SpineOutcome,
    SpineOutOfOrder,
    TrustSpine,
)

__all__ = [
    "AMOUNT",
    "CHECKOUT",
    "CURRENCY",
    "ENQUIRY",
    "IDENTITY",
    "ITEM_ID",
    "MANDATE_VALIDITY",
    "ORDER",
    "PAYMENT",
    "REPLAY_AND_FRESHNESS",
    "SPEND_AUTHORITY",
    "Check",
    "PurchaseRequest",
    "SpineOutOfOrder",
    "SpineOutcome",
    "TrustSpine",
    "read_purchase_request",
]

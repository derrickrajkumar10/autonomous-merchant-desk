"""Negotiation -- the part of the Desk that answers with something other than yes or no.

Everything before this decided whether the Desk is *allowed* to do business with whoever
is asking. Checks 1 to 4 said the request is authentic, authorised, inside a ceiling and
not a replay. The catalogue said what a deal would earn and whether that is enough. None
of it decided what to *say*.

A merchant that can only answer yes or no loses money twice over. It says yes to deals
beneath its floor, because it has nothing to test them against, and it says no to buyers
who were one small concession away, turning revenue into nothing. This package is the
alternative: the Desk holds its floor, reaches for a **lever** when the floor is in the
way, and **walks away** when nothing closes the gap.

Four ideas, and the last two are the ones that make it more than a haggling loop.

**The floor is never crossed.** Every offer the Desk puts forward is tested by
``margin_on`` before it is sent, and an offer that does not hold is never sent. There is
no path here that reaches agreement on an offer the floor refused -- not a lenient
branch, not a rounding, not a special case for a good customer.

**A refusal is not the end of the conversation.** The Desk can decline a discount and
offer a bundle in the same message (FR-5.3), which is the difference between a merchant
and a price list. Each lever is a trade rather than a gift: the buyer gets something it
said it wanted, and the Desk gets back the margin that pays for it.

**A walk-away is a success.** It is written to the trail as ``below_margin_floor`` under
its own event type, counted in the closed/walked breakdown, and never as an incident
(CONTEXT.md section 6 bans the word *failure* for it). Metrics that punished correct
refusals would quietly teach the Desk to close everything.

**Every message carries a rationale.** The margin, the floor, the gap and the lever, in
one machine-readable object recorded beside the message (FR-5.4). All of them, not the
interesting ones -- the question a reader has is usually *why did it agree to that*.

The lever choice here is a **fixed policy**, and it is not scaffolding. FR-6.3 makes it
the baseline the learned policy of ticket 21 is measured against over identical deals,
and a learned curve without a baseline is decoration that must not ship. It has to stay
runnable after the bandit exists.

    from desk.negotiation import Ask, Desk

    desk = Desk(catalogue, TERMS, trail, desk_key)
    deal = desk.open(spine_outcome, tier=TrustTier.NEW)
    reply = deal.receive(Ask(sku="SKU-COFFEE-1KG", quantity=2, target_unit_price=asked))
    reply.rationale.inside_floor      # why it said what it said
    reply.closed_mandate              # present exactly once, on agreement

**What is not here.** Which lever is *best* -- that is ticket 21, and this package
deliberately leaves the choice behind one substitutable object so the baseline survives
it. Settlement and receipts are ticket 09. The trust tier arrives as context and is
computed by ticket 12's ladder. And the buyer is not modelled at all: a reproducible
deal spec is ticket 19's, and until then a counterparty is whatever drives ``receive``.
"""

from desk.negotiation.ask import Ask
from desk.negotiation.lever import CONSIDERED, Lever
from desk.negotiation.rationale import Rationale
from desk.negotiation.terms import (
    CARRY,
    EXPRESS,
    HANDLING,
    Delivery,
    Payment,
    Terms,
    TermsSheet,
)

__all__ = [
    "CARRY",
    "CONSIDERED",
    "EXPRESS",
    "HANDLING",
    "Ask",
    "Delivery",
    "Lever",
    "Payment",
    "Rationale",
    "Terms",
    "TermsSheet",
]

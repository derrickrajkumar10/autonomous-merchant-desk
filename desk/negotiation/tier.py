"""How well the Desk knows a counterparty, as far as a negotiation needs to know.

Three rungs, because CONTEXT.md section 6 says a scrutiny tier is one of three discrete
levels, and because a ladder is legible in a trail entry and on a screen where a
continuous score is not.

**This declares the tier; it does not compute it.** Working out which rung an agent is
on is the reputation ladder's, and that is ticket 12 -- trust score, dwell time, decay
on inactivity, the lot. Until it lands, a tier arrives as context from whoever opened
the negotiation, and the honest reading of that is *the Desk was told*, not *the Desk
knows*.

It is declared this early for two reasons, and both are about not having to re-run
anything later. FR-6.1 requires every negotiation to log the buyer's trust level, and a
field added after a thousand deals have been recorded is a field those deals do not
have. And ticket 21's bandit takes trust tier as part of its context, so a policy trained
on deals that never recorded one could not be compared with the fixed baseline over the
same data.

**The fixed policy does not read it.** That is deliberate and slightly surprising, so it
is worth stating: this Desk negotiates the same way with a stranger as with a regular,
and the tier is recorded rather than acted on. What the ladder gates is the spend ceiling
and the scrutiny tier (FR-4.2), not the price -- and a fixed baseline that quietly priced
by reputation would make ticket 21's comparison meaningless, because the "fixed" policy
would already be doing half of what the learned one is supposed to discover.
"""

from __future__ import annotations

from enum import StrEnum


class TrustTier(StrEnum):
    """Which rung of the ladder a counterparty is on."""

    #: Registered and nothing more. Where every agent starts (FR-4.3).
    NEW = "new"
    #: Some clean completed deals behind it.
    KNOWN = "known"
    #: A long enough record, at the top of the ladder.
    TRUSTED = "trusted"

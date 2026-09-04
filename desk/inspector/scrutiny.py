"""How hard check 5 looks at a given agent, as far as this ticket needs to know.

Three levels, because CONTEXT.md section 6 says a scrutiny tier is one of three
discrete levels, and because a level is legible in a trail entry where a dial is not.

**This declares the tier; it does not compute it.** Which level an agent is on is a
function of its trust score, its dwell time on the ladder, and how recently it last
did anything -- and all of that is the reputation ladder's, which is a later ticket.
Until it lands, a tier arrives as an argument from whoever ran the check, and the
honest reading of that is *the Desk was told*, not *the Desk worked it out*.

**What it controls here is small, and deliberately so.** This ticket is the content
half of check 5 -- the Inspector reading message text. The one thing the tier changes
at this half is whether a request that carries *no* text still goes to the Inspector:

- ``CLOSE`` -- consult the Inspector on every request, empty enquiry included. A new
  agent (FR-4.2) gets this, and a message with nothing in it is still a message the
  Desk chose to look at.
- ``STANDARD`` and ``LIGHT`` -- a request with no enquiry text has nothing for the
  Inspector to read, so it passes check 5 without a model call.

``STANDARD`` and ``LIGHT`` behave alike at this half. They diverge once the
behavioural score arrives (the next ticket), which reads an agent's request history
rather than one message and has more to dial down for an agent the Desk knows well.
The tier is recorded on every check-5 entry regardless, so a policy trained on the
trail later has it on every row rather than only the rows where it mattered.
"""

from __future__ import annotations

from enum import StrEnum


class ScrutinyTier(StrEnum):
    """Which level of attention check 5 gives an agent."""

    #: The strictest level. Where every agent starts (FR-4.2), and where one stays
    #: until the ladder has reason to relax.
    CLOSE = "close"
    #: The middle level, for an agent with a clean record behind it.
    STANDARD = "standard"
    #: The most relaxed level, for an agent at the top of the ladder.
    LIGHT = "light"

    @property
    def inspects_empty_enquiry(self) -> bool:
        """Whether a request carrying no text is still sent to the Inspector."""
        return self is ScrutinyTier.CLOSE

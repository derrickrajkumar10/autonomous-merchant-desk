"""The one line that rides on every message the Desk sends.

FR-5.4 asks that each Desk message carry a machine-readable rationale: the current
margin, what was asked for, and whether it sits inside the floor. This is that object,
and it is designed once here because three consumers read it and none of them may be
given a different one -- the audit trail records it, the control room draws it beside
the speech bubble, and ticket 21's policy learns from it.

**Every message, not the interesting ones.** A rationale on refusals only would make the
record an account of when the Desk said no, and the question a reader actually has is
*why did it agree to that*. So an acceptance carries the same object as a walk-away, and
the suite asserts it on all of them rather than on a sample.

**Two verdicts, because a counter-offer is an answer to a question.** That the Desk's
own offer holds is one fact; whether *what the buyer asked for* held is a different one,
and it is the one FR-5.4 means by "whether it sits inside the floor". A counter that
reported only the first would record ``inside_floor: true`` on a message that had just
declined a below-floor request -- true, and an answer to a question nobody asked. So a
rationale carries the margin on the deal the message is about and, whenever the buyer
named a price, the verdict on that price beside it. On a walk-away the two are the same
deal, and the line does not say it twice.

**It reports and never decides.** The verdict is ``Margin.inside_floor``, computed by
exact subtraction over the offer; the percentages here are the same numbers rounded for
a human to read. A reader who compares the two rounded percentages will occasionally see
a deal that looks a hair inside and was a rupee short, and the exact ``surplus`` beside
them is the one that was acted on. That is not a defect to smooth over -- rounding a
margin to six places and then deciding on it is how a floor gets crossed by nobody's
decision.

**What it does not carry.** No cost, and no unit cost. The rationale goes to the trail
and the control room, both of which are the Desk's own; what does not go to the buyer is
the closed mandate's business, and that document carries no cost at all. Keeping the
distinction in one place would be neater and would also be wrong -- these are different
readers with different rights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desk.catalogue import Margin
from desk.negotiation.lever import Lever


@dataclass(frozen=True)
class Rationale:
    """Why the Desk said what it said, in a form a machine can aggregate."""

    #: What the buyer asked for, in its own terms, so that the record of the answer
    #: carries the question. Short: this is a log line, not a transcript.
    asked: str
    #: The margin on the deal this message is about: the agreed deal on an acceptance,
    #: the counter-offer on a counter, the refused deal on a walk-away. A real
    #: computation over a real offer in every case, never a placeholder.
    margin: Margin
    #: The margin the buyer's own price would have earned, whenever it named one. On a
    #: walk-away this is ``margin`` itself, because the deal the message is about *is*
    #: the one that was asked for. ``None`` on an opening ask that named no price, where
    #: there is no proposed deal to have a margin.
    on_the_ask: Margin | None = None
    #: Which lever, if any. Absent on a message that conceded nothing but price, on one
    #: that conceded nothing at all, and on a walk-away, where nothing was offered.
    lever: Lever | None = None

    @property
    def inside_floor(self) -> bool:
        """Whether the deal this message is about holds. Read off the offer, not restated."""
        return self.margin.inside_floor

    @property
    def ask_inside_floor(self) -> bool | None:
        """Whether what the buyer asked for held. ``None`` when it named no price.

        On a counter this is ``False`` while ``inside_floor`` is ``True``, and the pair is
        the whole of the message: *what you asked for does not hold, and here is something
        that does.*
        """
        return None if self.on_the_ask is None else self.on_the_ask.inside_floor

    def as_payload(self) -> dict[str, Any]:
        """The rationale as the trail carries it, and as the control room reads it."""
        return {
            "asked": self.asked,
            "ask_inside_floor": self.ask_inside_floor,
            "ask_surplus": None if self.on_the_ask is None else str(self.on_the_ask.surplus),
            "margin": None if self.margin.rate is None else str(self.margin.rate),
            "floor": None if self.margin.floor is None else str(self.margin.floor),
            "revenue": str(self.margin.revenue),
            "surplus": str(self.margin.surplus),
            "inside_floor": self.inside_floor,
            "lever": None if self.lever is None else self.lever.value,
        }

    def __str__(self) -> str:
        """One line, and ``Margin`` already knows how to say most of it."""
        lever = "" if self.lever is None else f", offering a {self.lever.value.replace('_', ' ')}"
        declined = (
            ""
            if self.on_the_ask is None or self.on_the_ask is self.margin
            else f" (which would earn {self.on_the_ask.surplus} against its floor)"
        )
        return f"asked {self.asked}{declined}; {self.margin}{lever}"

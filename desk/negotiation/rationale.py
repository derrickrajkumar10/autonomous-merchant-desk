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
    #: The margin on the offer the Desk is putting forward -- or, on a walk-away, on the
    #: offer it would have had to make. Either way it is a real computation over a real
    #: offer, never a placeholder.
    margin: Margin
    #: Which lever, if any. Absent on a message that conceded nothing but price, and on
    #: one that conceded nothing at all.
    lever: Lever | None = None

    @property
    def inside_floor(self) -> bool:
        """The verdict, taken from the offer rather than restated beside it."""
        return self.margin.inside_floor

    def as_payload(self) -> dict[str, Any]:
        """The rationale as the trail carries it, and as the control room reads it."""
        return {
            "asked": self.asked,
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
        return f"asked {self.asked}; {self.margin}{lever}"

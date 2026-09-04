"""The ladder itself: a short list of rungs, and the arithmetic that reads it.

A rung is a **discrete step**, not a point on a curve. CONTEXT.md section 10 fixes this
and section 6 says why: "a ladder is legible in the audit trail and on screen in a way
an arithmetic expression is not, and legibility is a requirement here rather than a
nicety". A trail entry that says *moved from regular to established* is something a
person reads at a glance; one that says *ceiling recomputed to 47,318.55* is not.

Each rung carries four things:

- a **spend ceiling** -- the most one deal may be worth for an agent on this rung. This
  is the number the standing gate refuses against, and it is separate from and smaller
  than any ceiling a principal's mandate sets. The mandate says what the *human* allows;
  the rung says what the *Desk* extends to an agent it does not yet know well.
- a **scrutiny tier** -- how hard check 5 looks (``desk.inspector.scrutiny``). Computed
  here, consumed there. A new agent gets the strictest; the top rung gets the most
  relaxed.
- a **score threshold** -- the trust score at or above which this rung becomes
  *available*. Available is not the same as *reached*: dwell time still applies.
- a **dwell time** -- the least an agent must sit on this rung before it may climb to
  the next, however high its score has gone. This is the anti-farming mechanism. Volume
  cannot buy it, because it is a cost paid in elapsed time and nothing else.

The numbers are deliberately round. They are tuning -- a reviewer should be arguing
about whether 15,000 is the right second-rung ceiling, not reverse-engineering where it
came from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from desk.inspector.scrutiny import ScrutinyTier
from desk.reputation.policy import ReputationPolicy
from desk.spend import Money

#: Every rung ceiling is written in this currency. The Desk is single-currency
#: (CONTEXT.md section 7a, "Multiple currencies are nobody's yet"), and a rung ceiling
#: is the Desk's own number rather than a counterparty's, so there is no exchange-rate
#: question to answer here -- a request in another currency is refused for that reason
#: before its amount is ever compared to a rung.
LADDER_CURRENCY = "INR"


@dataclass(frozen=True)
class Rung:
    """One step on the ladder: what it lets an agent spend, and how it is watched."""

    index: int
    name: str
    ceiling: Money
    scrutiny: ScrutinyTier
    #: The trust score at or above which this rung is available to climb onto.
    available_at: float
    #: The least time an agent must spend on this rung before climbing off it.
    dwell: timedelta

    def __str__(self) -> str:
        return f"rung {self.index} ({self.name})"


def _rung(
    index: int, name: str, ceiling: str, scrutiny: ScrutinyTier, at: float, days: int
) -> Rung:
    return Rung(
        index=index,
        name=name,
        ceiling=Money.of(ceiling, LADDER_CURRENCY),
        scrutiny=scrutiny,
        available_at=at,
        dwell=timedelta(days=days),
    )


#: The ladder, lowest rung first. Written once and read everywhere: the gate reads a
#: ceiling off it, check 5 reads a scrutiny tier off it, the store walks it to decide
#: whether a score has earned a climb. Reordering it or changing a number is a visible
#: edit to a named list rather than a constant buried in a method.
LADDER: tuple[Rung, ...] = (
    _rung(0, "newcomer", "2000.00", ScrutinyTier.CLOSE, 0.0, 1),
    _rung(1, "regular", "15000.00", ScrutinyTier.STANDARD, 0.30, 3),
    _rung(2, "established", "75000.00", ScrutinyTier.STANDARD, 0.55, 7),
    _rung(3, "principal", "300000.00", ScrutinyTier.LIGHT, 0.80, 14),
)

#: Where every agent starts (FR-4.2): the lowest rung, under the strictest scrutiny.
LOWEST_RUNG = LADDER[0]


def rung(index: int, ladder: tuple[Rung, ...] = LADDER) -> Rung:
    """The rung at ``index``, clamped into ``ladder``.

    ``ladder`` defaults to the real ``LADDER`` but is a parameter -- not read off the
    module directly -- so a caller running against an injected ladder (a test, or a
    ``ReputationLadder`` built with one) gets a clamp consistent with the one it is
    actually walking. Clamped rather than raising, because a stored index is only ever
    written by this module and the clamp is a belt-and-braces against a ladder that got
    shorter between a write and a read -- a shortened ladder should land an agent on
    the new top rung, not crash the next request it makes.
    """
    return ladder[max(0, min(index, len(ladder) - 1))]


def highest_available(score: float, ladder: tuple[Rung, ...] = LADDER) -> int:
    """The index of the highest rung in ``ladder`` this score makes *available*.

    Available, not reached: the store still holds an agent below this if it has not
    dwelt long enough on the rung it is on. A score at or below the lowest threshold
    yields rung 0, which every score does, because rung 0's threshold is zero.

    ``ladder`` defaults to the real ``LADDER``, and a caller walking an injected one
    passes it explicitly -- there is no module-level ladder to fall back on silently
    once a caller has said it wants a different one.
    """
    reached = 0
    for step in ladder:
        if score + 1e-9 >= step.available_at:
            reached = step.index
    return reached


def decayed(score: float, idle: timedelta, policy: ReputationPolicy) -> float:
    """``score`` after ``idle`` time with no activity. Never above where it started.

    Only a score above baseline moves, and it only moves down. A score at or below
    baseline -- a fresh agent, a blocked one, one already decayed all the way back --
    is returned unchanged, because decay that raised a score would be decay handing out
    trust for doing nothing, which is the opposite of the point.
    """
    if score <= policy.baseline or idle <= timedelta(0):
        return score
    days = idle.total_seconds() / 86400.0
    return max(policy.baseline, score - policy.decay_per_day * days)

"""The constants the ladder is tuned with. Tuning, not design.

CONTEXT.md section 10 settled the *shape* of the trust-score update and left the
numbers open: "Exact constants are tuning, not design." This is where the numbers
live, in one frozen object a test can replace wholesale, so that nothing downstream
reads a bare ``0.04`` and no rung threshold is written twice.

The one property that is **not** tuning, and is asserted in the suite rather than left
to a reviewer's eye, is the asymmetry: a check-5 signal has to cost strictly more than
a clean deal earns (``signal_fall > clean_deal_rise``). Trust that fell as slowly as it
rose would make farming a break-even game rather than a losing one, and the whole
ladder exists to make it a losing one.

Decay is the third number and the quietest. A score above baseline drifts back down
toward it over wall-clock time, so a high-trust identity left dormant is not a standing
liability -- it is an ordinary agent again by the time anyone uses it. Decay never
moves a score *up*: an agent that has been blocked, or one sitting at baseline, is left
exactly where it is.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReputationPolicy:
    """Every number the reputation ladder is tuned with, in one replaceable object."""

    #: Where a newly seen agent's score starts, and the value decay pulls a higher
    #: score back toward. One number for both, because "a dormant agent is an ordinary
    #: agent" and "an unknown agent is an ordinary agent" are the same statement.
    start_score: float = 0.10
    baseline: float = 0.10

    #: The score can go no lower and no higher than this. Bounded in ``[0, 1]`` as
    #: CONTEXT.md section 10 fixes it; the database enforces the same bound.
    minimum_score: float = 0.0
    maximum_score: float = 1.0

    #: What one clean completed deal adds to the score (FR-4.3).
    clean_deal_rise: float = 0.04

    #: What one check-5 signal subtracts, as a multiple of ``clean_deal_rise`` (FR-4.4,
    #: "several times that"). The multiple rather than an absolute number so the
    #: asymmetry cannot be tuned away by editing one line and forgetting the other.
    signal_fall_multiple: float = 5.0

    #: How much of the gap to baseline an idle score closes per day above it. At
    #: 0.01/day a score sitting a full 0.5 above baseline is halfway back in roughly
    #: seven weeks -- slow enough that an active agent never feels it, fast enough that
    #: a captured high-trust identity is worthless within a season.
    decay_per_day: float = 0.01

    #: How many check-5 signals it takes to block an agent (FR-4.4, "sufficiently bad
    #: behaviour blocks the agent"). Counted over the agent's whole life, because a
    #: signal that aged out of the count would let a patient attacker earn three
    #: refusals a month apart for free.
    block_after_signals: int = 3

    def __post_init__(self) -> None:
        if not 0.0 <= self.minimum_score <= self.baseline <= self.maximum_score <= 1.0:
            raise ValueError(
                f"the score bounds have to satisfy 0 <= minimum <= baseline <= maximum "
                f"<= 1; got minimum {self.minimum_score}, baseline {self.baseline}, "
                f"maximum {self.maximum_score}"
            )
        if not self.start_score >= self.minimum_score or not self.start_score <= self.maximum_score:
            raise ValueError(f"the start score {self.start_score} is outside the score bounds")
        if self.clean_deal_rise <= 0:
            raise ValueError(
                f"a clean deal has to raise the score by something positive; "
                f"{self.clean_deal_rise} does not"
            )
        if self.signal_fall_multiple <= 1.0:
            raise ValueError(
                f"a check-5 signal has to cost strictly more than a clean deal earns, "
                f"or farming is a break-even game; the multiple is {self.signal_fall_multiple}"
            )
        if self.decay_per_day < 0:
            raise ValueError(f"decay cannot be negative; {self.decay_per_day} is")
        if self.block_after_signals < 1:
            raise ValueError(
                f"an agent has to be blockable in a finite number of signals; "
                f"{self.block_after_signals} is not finite and positive"
            )

    @property
    def signal_fall(self) -> float:
        """What one check-5 signal subtracts from the score."""
        return self.clean_deal_rise * self.signal_fall_multiple

    @classmethod
    def default(cls) -> ReputationPolicy:
        return cls()

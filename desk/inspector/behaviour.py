"""Check 5, the behavioural half -- has this agent started acting unlike itself?

The Inspector reads one message. This reads the *shape of a sequence*. An agent can
send nothing but valid, well-inside-budget requests and still be doing something wrong
that no single request reveals: a long run of small clean buys and then one
disproportionate grab (trust farming), a spend that creeps up request by request
(escalation), a burst of fast probing, a sudden spread across categories it never
touched.

**It is scored against the agent's own history, not against a list of known attacks**
(ADR-0009). There are no attack labels anywhere in here. The reason is not stylistic:
labels we wrote would teach a detector the attacks we wrote, and the held-out classes
(RT-3) exist precisely to catch a detector that has learned our imagination. "Unlike
itself" generalises; "like attack #7" does not.

Five signals, each a non-negative number where zero is business as usual:

- **amount over its own mean** -- this request against the average of recent ones.
- **amount over its own ceiling** -- this request against the largest it has made.
  This is the trust-farming tell: the mean moves slowly, the ceiling not at all.
- **interval speed-up** -- how much faster than usual this request arrived. Probing
  comes in bursts.
- **category churn** -- how much of its recent buying has been in categories new to
  it. An agent ranging outside its established behaviour.
- **refusal rate** -- how often it has been refused lately. Repeated near-misses
  accumulate rather than resetting.

They combine into one anomaly score by a weighted sum. **The weights and the threshold
are tuning; the five signals and the "against its own baseline" framing are the
design.** Scrutiny tier scales the threshold -- a new agent's drift is caught sooner
than a trusted one's.

Like the content half, this can only refuse (ADR-0005). ``BehaviourOutcome`` carries a
score and the signals behind it and nothing that could be read as authority. A
sufficiently deviant sequence is refused under ``escalation_pattern_detected``; the
score itself is a signal the reputation ladder consumes, and this check moves no score
of its own.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.inspector.history import DEFAULT_WINDOW, RequestEvent, read_history
from desk.inspector.scrutiny import ScrutinyTier
from desk.spine import SpineOutcome

#: The fewest prior requests the score will form an opinion on. Below this an agent has
#: no baseline to depart from, and every second-ever request would look like an
#: escalation off a sample of one.
DEFAULT_BASELINE_MIN = 4

#: How far back "category churn" and "refusal rate" look. Shorter than the amount
#: window: a spread of categories is a recent-behaviour question, and averaging it over
#: thirty requests would wash out exactly the burst it is meant to see.
RECENT = 8

#: Below this, an agent's usual gap between requests is too short for "faster than
#: usual" to mean anything -- a run of requests a few milliseconds apart is a batch,
#: not a probe. One second, in seconds.
MIN_RHYTHM_SECONDS = 1.0


@dataclass(frozen=True)
class BehaviourPolicy:
    """The weights and thresholds. Tuning, not design -- see the module docstring."""

    amount_over_mean: float = 1.0
    amount_over_max: float = 1.4
    interval_speedup: float = 0.5
    category_churn: float = 0.6
    refusal_rate: float = 1.2

    #: The score at or above which a request is refused, at ``STANDARD`` scrutiny.
    refuse_at: float = 1.5
    window: int = DEFAULT_WINDOW
    baseline_min: int = DEFAULT_BASELINE_MIN

    def threshold_for(self, scrutiny: ScrutinyTier) -> float:
        """The refuse-at score for this level of scrutiny. Closer watch, lower bar."""
        return self.refuse_at * {
            ScrutinyTier.CLOSE: 0.75,
            ScrutinyTier.STANDARD: 1.0,
            ScrutinyTier.LIGHT: 1.5,
        }[scrutiny]

    @classmethod
    def default(cls) -> BehaviourPolicy:
        return cls()


@dataclass(frozen=True)
class Signals:
    """The five signals for one request, and the score they combine into.

    ``sample_size`` is how many prior requests the baseline was formed from. A score
    computed off too small a sample is reported as zero, and ``sample_size`` says why.
    """

    amount_over_mean: float
    amount_over_max: float
    interval_speedup: float
    category_churn: float
    refusal_rate: float
    score: float
    sample_size: int

    def as_evidence(self) -> dict[str, Any]:
        return {
            "amount_over_mean": round(self.amount_over_mean, 4),
            "amount_over_max": round(self.amount_over_max, 4),
            "interval_speedup": round(self.interval_speedup, 4),
            "category_churn": round(self.category_churn, 4),
            "refusal_rate": round(self.refusal_rate, 4),
            "score": round(self.score, 4),
            "sample_size": self.sample_size,
        }


@dataclass(frozen=True)
class BehaviourOutcome:
    """What the behavioural half concluded, and the entry it wrote.

    ``refused`` / not, the ``score``, the ``signals`` behind it, the entry. No
    identity, no ceiling, no balance: this half can only withhold (ADR-0005), and an
    outcome that carried something grantable would be the first crack in that.
    """

    refused: bool
    reason_code: ReasonCode | None
    signals: Signals
    entry: AuditEntry

    @property
    def passed(self) -> bool:
        return not self.refused

    @property
    def score(self) -> float:
        return self.signals.score


class BehaviourCheck:
    """Score one request against the agent's own history, refuse if it has drifted."""

    def __init__(self, trail: AuditTrail, policy: BehaviourPolicy | None = None) -> None:
        self._trail = trail
        self._policy = BehaviourPolicy.default() if policy is None else policy

    @property
    def policy(self) -> BehaviourPolicy:
        return self._policy

    def assess(self, outcome: SpineOutcome, *, scrutiny: ScrutinyTier) -> BehaviourOutcome:
        """The behavioural half of check 5, on a request that cleared checks 1 to 4.

        ``outcome`` is the spine's own output. One that did not pass has been answered
        already; assessing it would record a judgement after the refusal that ended it,
        so it raises rather than running.
        """
        if not outcome.passed or outcome.identity is None:
            raise ValueError(
                "the behavioural half of check 5 runs on a request that passed checks 1 "
                "to 4; a refused one has nothing left to assess"
            )

        agent_id = outcome.identity.agent_id
        history = read_history(self._trail, agent_id, window=self._policy.window)
        signals = score_history(history, self._policy)
        threshold = self._policy.threshold_for(scrutiny)

        if signals.score >= threshold and signals.sample_size >= self._policy.baseline_min:
            return self._refuse(agent_id, scrutiny, signals, threshold)
        return self._pass(agent_id, scrutiny, signals, threshold)

    def _pass(
        self, agent_id: str, scrutiny: ScrutinyTier, signals: Signals, threshold: float
    ) -> BehaviourOutcome:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_5_BEHAVIOUR_PASSED,
            subject_id=agent_id,
            payload={
                "check": 5,
                "reasoning": _reasoning(
                    signals, threshold, self._policy.baseline_min, refused=False
                ),
                "evidence": {"scrutiny": scrutiny.value, "threshold": round(threshold, 4)}
                | signals.as_evidence(),
                "state_change": {"request": "not refused by check 5"},
            },
        )
        return BehaviourOutcome(refused=False, reason_code=None, signals=signals, entry=entry)

    def _refuse(
        self, agent_id: str, scrutiny: ScrutinyTier, signals: Signals, threshold: float
    ) -> BehaviourOutcome:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_5_BEHAVIOUR_REFUSED,
            subject_id=agent_id,
            reason_code=ReasonCode.ESCALATION_PATTERN_DETECTED,
            payload={
                "check": 5,
                "reasoning": _reasoning(
                    signals, threshold, self._policy.baseline_min, refused=True
                ),
                "evidence": {"scrutiny": scrutiny.value, "threshold": round(threshold, 4)}
                | signals.as_evidence(),
                "state_change": {"request": "refused"},
            },
        )
        return BehaviourOutcome(
            refused=True,
            reason_code=ReasonCode.ESCALATION_PATTERN_DETECTED,
            signals=signals,
            entry=entry,
        )


def score_history(history: list[RequestEvent], policy: BehaviourPolicy) -> Signals:
    """The five signals for the most recent request in ``history``, and their sum.

    ``history`` is oldest first and its last element is the request being assessed. A
    history too short to have a baseline scores zero -- the signals are still reported,
    so a reader can see it was sample size and not calm that produced the pass.
    """
    if not history:
        return _empty(0)
    current, prior = history[-1], history[:-1]
    if len(prior) < policy.baseline_min:
        return _empty(len(prior))

    over_mean = _amount_over_mean(current, prior)
    over_max = _amount_over_max(current, prior)
    speedup = _interval_speedup(history)
    churn = _category_churn(history)
    refusals = _refusal_rate(prior)

    score = (
        policy.amount_over_mean * over_mean
        + policy.amount_over_max * over_max
        + policy.interval_speedup * speedup
        + policy.category_churn * churn
        + policy.refusal_rate * refusals
    )
    return Signals(
        amount_over_mean=over_mean,
        amount_over_max=over_max,
        interval_speedup=speedup,
        category_churn=churn,
        refusal_rate=refusals,
        score=score,
        sample_size=len(prior),
    )


def _empty(sample_size: int) -> Signals:
    return Signals(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, sample_size)


def _amounts(events: list[RequestEvent]) -> list[Decimal]:
    """The amounts of the agent's requests that were *allowed*.

    Refused requests are left out. Their amount is a number the agent named, not one it
    got to spend -- and counting it would let an agent lift its own baseline for free by
    firing off cheap requests it knows will be refused, then slipping a real one in
    under the raised ceiling.
    """
    return [event.amount for event in events if event.amount is not None and not event.refused]


def _amount_over_mean(current: RequestEvent, prior: list[RequestEvent]) -> float:
    if current.amount is None:
        return 0.0
    amounts = _amounts(prior)
    if not amounts:
        return 0.0
    mean = statistics.fmean(float(a) for a in amounts)
    if mean <= 0:
        return 0.0
    return max(0.0, float(current.amount) / mean - 1.0)


def _amount_over_max(current: RequestEvent, prior: list[RequestEvent]) -> float:
    if current.amount is None:
        return 0.0
    amounts = _amounts(prior)
    if not amounts:
        return 0.0
    ceiling = float(max(amounts))
    if ceiling <= 0:
        return 0.0
    return max(0.0, float(current.amount) / ceiling - 1.0)


def _interval_speedup(history: list[RequestEvent]) -> float:
    """How much faster than its own recent rhythm this request arrived.

    Capped: a request arriving a millisecond after the last one would otherwise be an
    unbounded spike, and the signal is "much faster than usual", not "how much".

    ``this_gap`` is the interval between the last two requests specifically -- not
    ``gaps[-1]`` after non-positive gaps have been filtered out, which would silently
    substitute an older interval exactly when the newest one is zero or negative (equal
    timestamps, a clock step). If that interval is not positive, there is nothing to say
    about it and the signal is zero.
    """
    if len(history) < 3:
        return 0.0
    this_gap = (history[-1].at - history[-2].at).total_seconds()
    earlier = [
        (b.at - a.at).total_seconds()
        for a, b in zip(history[:-1], history[1:-1], strict=False)
        if (b.at - a.at).total_seconds() > 0
    ]
    if this_gap <= 0 or len(earlier) < 2:
        return 0.0
    typical = statistics.median(earlier)
    if typical < MIN_RHYTHM_SECONDS:
        return 0.0
    return min(5.0, max(0.0, typical / this_gap - 1.0))


def _category_churn(history: list[RequestEvent]) -> float:
    """The share of recent requests whose category the agent had not bought before.

    Looks at the last ``RECENT`` requests. For each, "new" means its sku had not
    appeared in any earlier request in the whole history. An agent that has always
    bought coffee and suddenly buys a laptop, then a monitor, then a chair scores high;
    one that has always ranged widely scores low, because nothing is new to it.

    The oldest sku in the window is never itself scored as new -- there is nothing
    before it to compare against. Without that, a brand-new agent that has only ever
    bought one thing would score a positive churn on its own first request, which is
    exactly the short-history agent most likely to be under close scrutiny.
    """
    skus = [event.sku for event in history if event.sku]
    if len(skus) < 2:
        return 0.0
    recent = skus[-RECENT:]
    seen: set[str] = set(skus[: len(skus) - len(recent)])
    considered = 0
    fresh = 0
    for index, sku in enumerate(recent):
        if not seen and index == 0:
            seen.add(sku)  # the first sku with no history behind it is the baseline
            continue
        considered += 1
        if sku not in seen:
            fresh += 1
        seen.add(sku)
    return fresh / considered if considered else 0.0


def _refusal_rate(prior: list[RequestEvent]) -> float:
    recent = prior[-RECENT:]
    if not recent:
        return 0.0
    return sum(1 for event in recent if event.refused) / len(recent)


def _reasoning(signals: Signals, threshold: float, baseline_min: int, *, refused: bool) -> str:
    if signals.sample_size < baseline_min:
        return (
            f"only {signals.sample_size} earlier requests from this agent, too few to "
            f"say what is normal for it; nothing is scored yet"
        )
    top = max(
        ("amount above its own recent mean", signals.amount_over_mean),
        ("amount above its own previous ceiling", signals.amount_over_max),
        ("requests arriving faster than its own rhythm", signals.interval_speedup),
        ("buying in categories new to it", signals.category_churn),
        ("a rising rate of refusals", signals.refusal_rate),
        key=lambda pair: pair[1],
    )
    where = f"score {signals.score:.2f} against a threshold of {threshold:.2f}"
    if refused:
        return (
            f"this agent's recent pattern has departed from its own baseline: {where}, "
            f"driven most by {top[0]}"
        )
    return f"this agent's recent pattern is within its own baseline: {where}"

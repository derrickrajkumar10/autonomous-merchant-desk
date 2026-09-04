"""The behavioural score, on synthesised histories with known shapes.

No database and no front door here -- ``score_history`` is a pure function of a list of
``RequestEvent``, and this file feeds it the four shapes the ticket names (steady,
escalating, trust-farming, probing) plus the category and refusal signals.

**The assertions are about relative ordering, never absolute thresholds.** A test that
pinned "escalating scores 2.7" would break every time a weight was tuned, and the
weights are explicitly tuning. What must stay true is that a departure scores above
calm, and far enough above to be refused.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from desk.inspector import BehaviourPolicy, RequestEvent, score_history

START = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
POLICY = BehaviourPolicy.default()


def _event(
    minute: float,
    *,
    amount: str | None = "700",
    sku: str | None = "SKU-COFFEE-1KG",
    refused: bool = False,
) -> RequestEvent:
    return RequestEvent(
        at=START + timedelta(minutes=minute),
        amount=None if amount is None else Decimal(amount),
        currency=None if amount is None else "INR",
        sku=sku,
        refused=refused,
        reason_code="request_stale" if refused else None,
    )


def _steady(n: int = 12) -> list[RequestEvent]:
    """Same product, similar amount, an even ten-minute rhythm."""
    return [_event(i * 10, amount=str(680 + (i % 3) * 20)) for i in range(n)]


def test_a_steady_history_scores_near_zero_and_below_threshold() -> None:
    signals = score_history(_steady(), POLICY)
    assert signals.score < POLICY.refuse_at
    assert signals.sample_size == 11


def test_an_escalating_history_scores_materially_above_steady() -> None:
    """Spend that climbs request on request, each step larger than the last."""
    ramp = [_event(i * 10, amount=str(round(400 * 1.35**i))) for i in range(12)]
    escalating = score_history(ramp, POLICY).score
    steady = score_history(_steady(), POLICY).score
    assert escalating > steady * 5
    assert escalating >= POLICY.refuse_at


def test_a_gentle_creep_scores_above_steady_but_need_not_yet_be_refused() -> None:
    """A slow linear rise is above calm but not necessarily over the bar -- the score
    is a signal the ladder also consumes, not only a gate."""
    creep = [_event(i * 10, amount=str(500 + i * 60)) for i in range(12)]
    assert score_history(creep, POLICY).score > score_history(_steady(), POLICY).score


def test_trust_farming_scores_above_steady_and_is_driven_by_the_ceiling_signal() -> None:
    """Eleven small clean buys, then one an order of magnitude larger."""
    farming = [_event(i * 10, amount="600") for i in range(11)] + [_event(120, amount="9000")]
    signals = score_history(farming, POLICY)
    steady = score_history(_steady(), POLICY).score
    assert signals.score > steady
    assert signals.score >= POLICY.refuse_at
    assert signals.amount_over_max > signals.interval_speedup
    assert signals.amount_over_max > signals.category_churn


def test_probing_scores_on_the_interval_signal() -> None:
    """A settled rhythm of ten minutes, then requests arriving seconds apart."""
    calm = [_event(i * 10) for i in range(10)]
    burst = [_event(100 + s / 60.0) for s in (0, 3, 6)]
    probing = score_history(calm + burst, POLICY)
    steady = score_history(_steady(), POLICY)
    assert probing.interval_speedup > 0.0
    assert probing.score > steady.score


def test_category_churn_rises_when_an_agent_ranges_outside_its_history() -> None:
    coffee_only = [_event(i * 10) for i in range(10)]
    then_everything = coffee_only + [
        _event(110, sku="SKU-LAPTOP-14"),
        _event(120, sku="SKU-GRINDER-BURR"),
        _event(130, sku="SKU-DESK-OAK"),
    ]
    ranged = score_history(then_everything, POLICY)
    settled = score_history(coffee_only + [_event(110), _event(120), _event(130)], POLICY)
    assert ranged.category_churn > settled.category_churn
    assert ranged.score > settled.score


def test_a_rising_refusal_rate_contributes() -> None:
    clean = [_event(i * 10) for i in range(12)]
    near_misses = (
        [_event(i * 10) for i in range(6)]
        + [_event(i * 10, refused=True) for i in range(6, 11)]
        + [_event(110)]
    )
    assert score_history(near_misses, POLICY).refusal_rate > 0.0
    assert score_history(near_misses, POLICY).score > score_history(clean, POLICY).score


def test_refused_requests_do_not_inflate_the_amount_baseline() -> None:
    """An agent cannot lift its own ceiling for free by firing off doomed big requests."""
    honest = [_event(i * 10, amount="600") for i in range(8)]
    padded = honest + [
        _event(80, amount="9000", refused=True),
        _event(90, amount="9000", refused=True),
    ]
    grab = [_event(100, amount="3000")]

    with_padding = score_history(padded + grab, POLICY)
    without = score_history(honest + grab, POLICY)
    assert with_padding.amount_over_max == without.amount_over_max
    assert with_padding.score >= POLICY.refuse_at


def test_a_history_too_short_for_a_baseline_scores_zero() -> None:
    signals = score_history([_event(0), _event(10), _event(20)], POLICY)
    assert signals.score == 0.0
    assert signals.sample_size == 2
    # The signals are still all present, so a reader can see it was sample size.
    assert signals.amount_over_mean == 0.0


def test_only_the_newest_request_is_judged_not_an_old_spike() -> None:
    """A big request early in an otherwise calm history does not keep tripping the score."""
    calm_after_old_spike = (
        [_event(0), _event(10)]
        + [_event(20, amount="9000")]
        + [_event(i * 10) for i in range(3, 13)]
    )
    assert score_history(calm_after_old_spike, POLICY).score < POLICY.refuse_at

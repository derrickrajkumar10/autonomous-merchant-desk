"""The worked example in ticket 11's explainer, section 6, as a test.

Four agents, four shapes of history, one scoring function. The explainer quotes this
table verbatim, so it is asserted here: if a weight changes enough to reorder the
shapes, or to stop a departure being refused, this fails rather than the explainer
going quietly wrong.

To see the table rather than assert it::

    .venv/bin/python -m pytest tests/inspector/test_behaviour_walkthrough.py -s
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from desk.inspector import BehaviourPolicy, RequestEvent, ScrutinyTier, score_history

START = datetime(2026, 9, 1, 9, 0, 0, tzinfo=UTC)
POLICY = BehaviourPolicy.default()


def _event(
    minute: float, amount: str, sku: str = "SKU-COFFEE-1KG", *, refused: bool = False
) -> RequestEvent:
    return RequestEvent(
        at=START + timedelta(minutes=minute),
        amount=Decimal(amount),
        currency="INR",
        sku=sku,
        refused=refused,
        reason_code="request_stale" if refused else None,
    )


def _row(label: str, history: list[RequestEvent]) -> str:
    signals = score_history(history, POLICY)
    threshold = POLICY.threshold_for(ScrutinyTier.STANDARD)
    verdict = "refused" if signals.score >= threshold else "passed"
    return f"  {label:<16} score {signals.score:5.2f}  -> {verdict}"


def test_the_walkthrough_in_the_explainer_still_does_what_it_says() -> None:
    steady = [_event(i * 10, str(680 + (i % 3) * 20)) for i in range(12)]
    escalating = [_event(i * 10, str(round(400 * 1.35**i))) for i in range(12)]
    farming = [_event(i * 10, "600") for i in range(11)] + [_event(120, "3000")]
    probing = [_event(i * 10, "700") for i in range(10)] + [
        _event(100 + s / 60.0, "700") for s in (0, 3, 6)
    ]

    rows = [
        _row("steady", steady),
        _row("escalating", escalating),
        _row("trust farming", farming),
        _row("probing", probing),
    ]
    print("\nFour agents, four shapes, one score (threshold 1.50 at standard scrutiny):")
    for row in rows:
        print(row)

    assert rows == [
        "  steady           score  0.03  -> passed",
        "  escalating       score  3.49  -> refused",
        "  trust farming    score  9.60  -> refused",
        "  probing          score  2.50  -> refused",
    ]

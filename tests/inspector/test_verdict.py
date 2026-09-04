"""The Inspector's output is pinned to a verdict, and anything off that shape is refused.

``read_verdict`` is the narrow gate every Inspector answer passes through. These tests
are about that gate: a clean verdict goes through, and every way of being not-a-verdict
raises ``MalformedVerdict`` rather than being coerced. The wiring that turns that raise
into a check-5 refusal is in ``test_check_five.py``.
"""

from __future__ import annotations

import pytest

from desk.inspector import Finding, MalformedVerdict, Verdict, read_verdict
from desk.inspector.verdict import MAX_REASON


def test_a_clean_verdict_round_trips() -> None:
    verdict = read_verdict({"finding": "prompt_injection", "reason": "asks the Desk to drop it"})
    assert verdict.finding is Finding.PROMPT_INJECTION
    assert verdict.is_injection
    assert verdict.reason == "asks the Desk to drop it"


def test_a_verdict_object_passes_through_unchanged() -> None:
    verdict = Verdict(finding=Finding.CLEAR, reason="a plain question about stock")
    assert read_verdict(verdict) is verdict


def test_clear_is_not_an_injection() -> None:
    assert not Verdict(finding=Finding.CLEAR, reason="just asking").is_injection


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ({"finding": "clear"}, "no reason"),
        ({"reason": "some text"}, "no finding"),
        ({"finding": "clear", "reason": "ok", "note": "extra"}, "an extra key"),
        ({"finding": "maybe", "reason": "hedging"}, "a finding outside the set"),
        ({"finding": "clear", "reason": ""}, "an empty reason"),
        ({"finding": "clear", "reason": "   "}, "a whitespace reason"),
        ("prompt_injection", "a bare string"),
        (None, "nothing at all"),
        (["clear", "reason"], "a list"),
    ],
)
def test_anything_that_is_not_a_verdict_is_refused(value: object, why: str) -> None:
    """The point of pinning the output is lost the moment something off-shape gets in."""
    with pytest.raises(MalformedVerdict):
        read_verdict(value)


def test_a_reason_longer_than_the_cap_is_refused() -> None:
    """A model returning a page of prose is confused or steered; the Desk stores neither."""
    with pytest.raises(MalformedVerdict):
        read_verdict({"finding": "clear", "reason": "x" * (MAX_REASON + 1)})


def test_a_reason_at_the_cap_is_allowed() -> None:
    verdict = read_verdict({"finding": "clear", "reason": "x" * MAX_REASON})
    assert len(verdict.reason) == MAX_REASON

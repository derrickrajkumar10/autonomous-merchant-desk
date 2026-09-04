"""Scrutiny tier: three levels, consumed here, and one behaviour it controls.

This ticket is the content half of check 5. The only thing the tier changes here is
whether a request with no text still goes to the Inspector -- ``CLOSE`` says yes, the
other two say there is nothing to read. The wiring test in ``test_check_five.py``
proves that end to end; this file is just the enum's own contract.
"""

from __future__ import annotations

from desk.inspector import ScrutinyTier


def test_there_are_exactly_three_levels() -> None:
    assert [tier.value for tier in ScrutinyTier] == ["close", "standard", "light"]


def test_only_close_inspects_an_empty_enquiry() -> None:
    assert ScrutinyTier.CLOSE.inspects_empty_enquiry
    assert not ScrutinyTier.STANDARD.inspects_empty_enquiry
    assert not ScrutinyTier.LIGHT.inspects_empty_enquiry

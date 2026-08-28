"""A payload must hash to the same thing after Postgres has held it.

The chain is taken over the entry as stored, so anything ``jsonb`` normalises has to
be normalised *before* the hash is computed. It is not a hypothetical: Postgres
stores the float ``1e+16`` as ``10000000000000000``, so hashing the Python form
writes an entry that verifies at the moment of writing and then fails verification
for ever after — a trail accusing itself of tampering when nothing tampered.

That is the worst failure this component has, because it is silent, it is delayed,
and it discredits the one thing the trail exists to prove.
"""

from __future__ import annotations

import pytest

from desk.audit import AuditTrail, EventType

# Values whose JSON text differs between Python and jsonb, alongside ones that agree.
AWKWARD_NUMBERS = {
    "large_float": 1e16,
    "huge_float": 1.5e300,
    "exponent_float": 1e22,
    "small_float": 1e-5,
    "plain_float": 0.1,
    "whole_float": 100.0,
    "big_int": 10**20,
    "negative": -1e18,
    "zero": 0.0,
}


@pytest.mark.parametrize(("name", "value"), sorted(AWKWARD_NUMBERS.items()))
def test_an_awkward_number_still_verifies(trail: AuditTrail, name: str, value: float) -> None:
    trail.record(
        actor="desk",
        event_type=EventType.DEAL_CLOSED,
        subject_id="deal-1",
        payload={name: value},
    )

    assert trail.verify().ok


def test_a_payload_of_awkward_numbers_still_verifies(trail: AuditTrail) -> None:
    trail.record(
        actor="desk",
        event_type=EventType.MATCH_FOUND,
        subject_id="bank-line-1",
        payload={"evidence": dict(AWKWARD_NUMBERS), "nested": [1e16, {"deep": 1.5e300}]},
    )

    assert trail.verify().ok


def test_what_record_returns_is_what_the_trail_holds(trail: AuditTrail) -> None:
    """The returned entry is the stored one, not the one the caller hoped for."""
    written = trail.record(
        actor="desk",
        event_type=EventType.DEAL_CLOSED,
        subject_id="deal-1",
        payload={"amount": 1e16},
    )

    (read,) = trail.query()
    assert read == written
    assert written.recompute_hash() == written.hash


def test_unicode_and_awkward_strings_survive(trail: AuditTrail) -> None:
    payload = {"note": "café — 1 200 ₹", "emoji": "🧵", "quote": 'he said "no"', "tab": "a\tb"}

    trail.record(
        actor="desk",
        event_type=EventType.NEGOTIATION_MESSAGE_SENT,
        subject_id="deal-1",
        payload=payload,
    )

    (read,) = trail.query()
    assert read.payload == payload
    assert trail.verify().ok

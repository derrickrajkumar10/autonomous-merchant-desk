"""Writing entries.

Acceptance criterion: an entry writes with actor, event type, subject, reason code,
payload and chain hashes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from desk.audit import GENESIS_HASH, AuditTrail, EventType, ReasonCode


def test_an_entry_writes_with_every_part_populated(trail: AuditTrail) -> None:
    before = datetime.now(UTC) - timedelta(seconds=5)

    entry = trail.record(
        actor="desk",
        event_type=EventType.CHECK_3_SPEND_AUTHORITY_REFUSED,
        subject_id="agent-7",
        reason_code=ReasonCode.EXCEEDS_REMAINING_BALANCE,
        payload={
            "check": 3,
            "reasoning": "requested 2400 against 1800 remaining on the open mandate",
            "evidence": {"requested_minor": 240000, "remaining_minor": 180000},
            "state_change": {"deal": "refused"},
        },
    )

    assert entry.seq == 1
    assert entry.actor == "desk"
    assert entry.event_type is EventType.CHECK_3_SPEND_AUTHORITY_REFUSED
    assert entry.subject_id == "agent-7"
    assert entry.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE
    assert entry.payload["evidence"] == {"requested_minor": 240000, "remaining_minor": 180000}
    assert entry.prev_hash == GENESIS_HASH
    assert len(entry.hash) == 64
    assert before <= entry.ts <= datetime.now(UTC) + timedelta(seconds=5)


def test_an_entry_needs_no_reason_code(trail: AuditTrail) -> None:
    entry = trail.record(
        actor="agent-7",
        event_type=EventType.REQUEST_RECEIVED,
        subject_id="agent-7",
        payload={"sku": "COFFEE-1KG"},
    )

    assert entry.reason_code is None


def test_the_written_entry_is_what_comes_back_out(trail: AuditTrail) -> None:
    written = trail.record(
        actor="desk",
        event_type=EventType.LEVER_OFFERED,
        subject_id="deal-3",
        payload={"lever": "quantity_break", "margin": 0.185, "units": [12, 24], "note": "café"},
    )

    (read,) = trail.query()
    assert read == written


def test_each_entry_links_to_the_one_before_it(trail: AuditTrail) -> None:
    first = trail.record(
        actor="desk", event_type=EventType.REQUEST_RECEIVED, subject_id="a", payload={}
    )
    second = trail.record(
        actor="desk", event_type=EventType.DEAL_CLOSED, subject_id="a", payload={}
    )

    assert (first.seq, second.seq) == (1, 2)
    assert second.prev_hash == first.hash
    assert second.hash != first.hash


def test_the_head_is_the_last_entry_written(trail: AuditTrail) -> None:
    assert trail.head() is None

    trail.record(actor="desk", event_type=EventType.REQUEST_RECEIVED, subject_id="a", payload={})
    last = trail.record(actor="desk", event_type=EventType.WALKED_AWAY, subject_id="a", payload={})

    assert trail.head() == last


def test_an_actor_is_required(trail: AuditTrail) -> None:
    with pytest.raises(ValueError):
        trail.record(actor="  ", event_type=EventType.REQUEST_RECEIVED, subject_id="a", payload={})


def test_a_subject_is_required(trail: AuditTrail) -> None:
    with pytest.raises(ValueError):
        trail.record(actor="desk", event_type=EventType.REQUEST_RECEIVED, subject_id="", payload={})


def test_a_payload_that_will_not_serialise_is_rejected(trail: AuditTrail) -> None:
    with pytest.raises(ValueError):
        trail.record(
            actor="desk",
            event_type=EventType.REQUEST_RECEIVED,
            subject_id="a",
            payload={"when": datetime.now(UTC)},
        )

    assert trail.query() == []

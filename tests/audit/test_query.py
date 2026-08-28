"""Querying the trail.

Acceptance criterion: queries by reason code, by subject and by time window return
the right entries. FR-10.2: the trail is queryable, not just a log file.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from desk.audit import AuditTrail, EventType, ReasonCode


@pytest.fixture
def populated(trail: AuditTrail) -> AuditTrail:
    trail.record(
        actor="desk",
        event_type=EventType.CHECK_1_IDENTITY_REFUSED,
        subject_id="agent-a",
        reason_code=ReasonCode.AGENT_SIGNATURE_INVALID,
        payload={},
    )
    trail.record(
        actor="desk",
        event_type=EventType.CHECK_3_SPEND_AUTHORITY_REFUSED,
        subject_id="agent-b",
        reason_code=ReasonCode.EXCEEDS_REMAINING_BALANCE,
        payload={},
    )
    trail.record(
        actor="desk",
        event_type=EventType.CHECK_1_IDENTITY_REFUSED,
        subject_id="agent-b",
        reason_code=ReasonCode.AGENT_SIGNATURE_INVALID,
        payload={},
    )
    trail.record(
        actor="desk",
        event_type=EventType.DEAL_CLOSED,
        subject_id="agent-a",
        payload={"margin": 0.21},
    )
    return trail


def test_query_by_reason_code(populated: AuditTrail) -> None:
    entries = populated.query(reason_code=ReasonCode.AGENT_SIGNATURE_INVALID)

    assert [entry.seq for entry in entries] == [1, 3]


def test_query_by_reason_code_accepts_its_string_value(populated: AuditTrail) -> None:
    assert populated.query(reason_code="agent_signature_invalid") == populated.query(
        reason_code=ReasonCode.AGENT_SIGNATURE_INVALID
    )


def test_query_by_an_unrecognised_reason_code_is_rejected(populated: AuditTrail) -> None:
    from desk.audit import UnknownReasonCode

    with pytest.raises(UnknownReasonCode):
        populated.query(reason_code="mandate_smelled_wrong")


def test_query_by_subject(populated: AuditTrail) -> None:
    entries = populated.query(subject_id="agent-b")

    assert [entry.seq for entry in entries] == [2, 3]


def test_query_by_event_type(populated: AuditTrail) -> None:
    entries = populated.query(event_type=EventType.CHECK_1_IDENTITY_REFUSED)

    assert [entry.seq for entry in entries] == [1, 3]


def test_query_by_time_window_is_inclusive_of_since_and_exclusive_of_until(
    populated: AuditTrail,
) -> None:
    all_entries = populated.query()
    second, third = all_entries[1], all_entries[2]

    entries = populated.query(since=second.ts, until=third.ts)

    assert [entry.seq for entry in entries] == [2]


def test_query_by_time_window_spanning_everything(populated: AuditTrail) -> None:
    all_entries = populated.query()
    span = timedelta(minutes=5)

    entries = populated.query(since=all_entries[0].ts - span, until=all_entries[-1].ts + span)

    assert [entry.seq for entry in entries] == [1, 2, 3, 4]


def test_query_by_time_window_matching_nothing(populated: AuditTrail) -> None:
    first = populated.query()[0]

    assert populated.query(until=first.ts) == []


def test_filters_combine(populated: AuditTrail) -> None:
    entries = populated.query(subject_id="agent-b", reason_code=ReasonCode.AGENT_SIGNATURE_INVALID)

    assert [entry.seq for entry in entries] == [3]


def test_query_returns_entries_in_sequence_order(populated: AuditTrail) -> None:
    assert [entry.seq for entry in populated.query()] == [1, 2, 3, 4]


def test_query_can_resume_after_a_sequence_number(populated: AuditTrail) -> None:
    """How the control room tails the trail without re-reading it."""
    assert [entry.seq for entry in populated.query(after_seq=2)] == [3, 4]


def test_query_can_be_limited(populated: AuditTrail) -> None:
    assert [entry.seq for entry in populated.query(limit=2)] == [1, 2]


def test_query_over_an_empty_trail(trail: AuditTrail) -> None:
    assert trail.query() == []

"""Nothing updates or deletes from this table.

ADR-0006: append-only means corrections are new entries, never updates. That is a
property to enforce structurally, so it is enforced by the database and tested
against the database rather than trusted to reviewers.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode


@pytest.fixture
def written(trail: AuditTrail) -> AuditTrail:
    trail.record(
        actor="desk",
        event_type=EventType.CHECK_5_INSPECTION_REFUSED,
        subject_id="agent-1",
        reason_code=ReasonCode.PROMPT_INJECTION_DETECTED,
        payload={"reasoning": "the enquiry carried an instruction aimed at the Desk"},
    )
    return trail


def test_an_entry_cannot_be_updated(written: AuditTrail, pool: ConnectionPool) -> None:
    with pytest.raises(psycopg.errors.RestrictViolation), pool.connection() as conn:
        conn.execute("UPDATE audit_entry SET actor = 'someone else' WHERE seq = 1")


def test_an_entry_cannot_be_deleted(written: AuditTrail, pool: ConnectionPool) -> None:
    with pytest.raises(psycopg.errors.RestrictViolation), pool.connection() as conn:
        conn.execute("DELETE FROM audit_entry WHERE seq = 1")


def test_the_table_cannot_be_truncated(written: AuditTrail, pool: ConnectionPool) -> None:
    with pytest.raises(psycopg.errors.RestrictViolation), pool.connection() as conn:
        conn.execute("TRUNCATE audit_entry")


def test_a_refused_write_leaves_the_trail_intact(written: AuditTrail, pool: ConnectionPool) -> None:
    for statement in (
        "UPDATE audit_entry SET actor = 'someone else'",
        "DELETE FROM audit_entry",
    ):
        with pytest.raises(psycopg.errors.RestrictViolation), pool.connection() as conn:
            conn.execute(statement)

    assert len(written.query()) == 1
    assert written.verify().ok


def test_a_correction_is_a_new_entry(written: AuditTrail) -> None:
    correction = written.record(
        actor="desk",
        event_type=EventType.TRUST_SCORE_CHANGED,
        subject_id="agent-1",
        payload={
            "corrects_seq": 1,
            "reasoning": "the enquiry was quoting a customer, not the Desk",
        },
    )

    assert correction.seq == 2
    assert len(written.query(subject_id="agent-1")) == 2
    assert written.verify().ok

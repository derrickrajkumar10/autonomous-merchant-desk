"""The hash chain.

Acceptance criteria: the chain verifies in one forward pass over a clean run, and
verification fails when an entry is altered or removed.

Tampering here is done with the append-only triggers switched off, because that is
the only adversary the chain is there to catch. The triggers stop the Desk from
editing history (see test_append_only.py); the chain is what answers "could an
operator with database access have doctored this?", and an operator can drop a
trigger. So these tests take that power and show the chain still tells.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, ChainBreak, EventType, ReasonCode


@contextmanager
def triggers_off(pool: ConnectionPool) -> Iterator[ConnectionPool]:
    """Act as an operator who has gone around the append-only guard."""
    with pool.connection() as conn:
        conn.execute("ALTER TABLE audit_entry DISABLE TRIGGER USER")
    try:
        yield pool
    finally:
        with pool.connection() as conn:
            conn.execute("ALTER TABLE audit_entry ENABLE TRIGGER USER")


def write_a_clean_run(trail: AuditTrail, count: int = 6) -> None:
    for index in range(count):
        trail.record(
            actor="desk",
            event_type=EventType.CHECK_1_IDENTITY_REFUSED,
            subject_id=f"agent-{index}",
            reason_code=ReasonCode.AGENT_SIGNATURE_INVALID,
            payload={"attempt": index},
        )


def test_the_chain_verifies_over_a_clean_run(trail: AuditTrail) -> None:
    write_a_clean_run(trail)

    report = trail.verify()

    assert report.ok
    assert report.entries_checked == 6
    assert report.break_at is None
    assert report.break_kind is None


def test_an_empty_trail_verifies(trail: AuditTrail) -> None:
    report = trail.verify()

    assert report.ok
    assert report.entries_checked == 0


def test_verification_fails_when_a_payload_is_altered(
    trail: AuditTrail, pool: ConnectionPool
) -> None:
    write_a_clean_run(trail)

    with triggers_off(pool), pool.connection() as conn:
        conn.execute("UPDATE audit_entry SET payload = '{\"attempt\": 99}'::jsonb WHERE seq = 3")

    report = trail.verify()

    assert not report.ok
    assert report.break_at == 3
    assert report.break_kind is ChainBreak.CONTENT_ALTERED


def test_verification_fails_when_a_reason_code_is_altered(
    trail: AuditTrail, pool: ConnectionPool
) -> None:
    write_a_clean_run(trail)

    with triggers_off(pool), pool.connection() as conn:
        conn.execute("UPDATE audit_entry SET reason_code = 'agent_blocked' WHERE seq = 4")

    report = trail.verify()

    assert not report.ok
    assert report.break_at == 4
    assert report.break_kind is ChainBreak.CONTENT_ALTERED


def test_verification_fails_when_an_entry_is_removed(
    trail: AuditTrail, pool: ConnectionPool
) -> None:
    write_a_clean_run(trail)

    with triggers_off(pool), pool.connection() as conn:
        conn.execute("DELETE FROM audit_entry WHERE seq = 4")

    report = trail.verify()

    assert not report.ok
    assert report.break_at == 4
    assert report.break_kind is ChainBreak.ENTRY_MISSING


def test_verification_fails_when_an_entry_is_replaced_wholesale(
    trail: AuditTrail, pool: ConnectionPool
) -> None:
    """Rewriting an entry and its own hash still breaks the link to the next one."""
    write_a_clean_run(trail)

    with triggers_off(pool), pool.connection() as conn:
        entry = trail.query(after_seq=2, limit=1)[0]
        forged = dataclasses.replace(entry, payload={"attempt": 99}).recompute_hash()
        conn.execute(
            "UPDATE audit_entry SET payload = '{\"attempt\": 99}'::jsonb, hash = %s WHERE seq = 3",
            (forged,),
        )

    report = trail.verify()

    assert not report.ok
    assert report.break_at == 4
    assert report.break_kind is ChainBreak.LINK_BROKEN


def test_verification_fails_when_the_trail_is_truncated_from_the_head(
    trail: AuditTrail, pool: ConnectionPool
) -> None:
    """Lopping off the tail leaves a chain that is internally consistent.

    A hash chain cannot see that on its own, so verification takes the head hash a
    caller already knew and checks the trail still ends there.
    """
    write_a_clean_run(trail)
    known_head = trail.head()
    assert known_head is not None

    with triggers_off(pool), pool.connection() as conn:
        conn.execute("DELETE FROM audit_entry WHERE seq > 4")

    assert trail.verify().ok
    report = trail.verify(expected_head_hash=known_head.hash)

    assert not report.ok
    assert report.break_at == 4
    assert report.break_kind is ChainBreak.HEAD_UNEXPECTED


def test_verification_fails_when_the_first_entry_is_removed(
    trail: AuditTrail, pool: ConnectionPool
) -> None:
    write_a_clean_run(trail)

    with triggers_off(pool), pool.connection() as conn:
        conn.execute("DELETE FROM audit_entry WHERE seq = 1")

    report = trail.verify()

    assert not report.ok
    assert report.break_at == 1
    assert report.break_kind is ChainBreak.ENTRY_MISSING


def test_a_broken_link_cannot_be_appended_in_the_first_place(
    trail: AuditTrail, pool: ConnectionPool
) -> None:
    """Linkage is enforced on insert, so the chain cannot be broken by a rogue write."""
    write_a_clean_run(trail, count=2)

    with pytest.raises(psycopg.errors.RaiseException), pool.connection() as conn:
        conn.execute(
            "INSERT INTO audit_entry"
            " (seq, ts, actor, event_type, subject_id, reason_code, payload, prev_hash, hash)"
            " VALUES (3, now(), 'desk', 'deal_closed', 'agent-1', NULL, '{}'::jsonb,"
            " repeat('b', 64), repeat('c', 64))"
        )

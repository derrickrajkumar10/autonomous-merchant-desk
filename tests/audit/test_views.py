"""Views per consumer sit over the table.

ADR-0006 puts views over the trail "with views per consumer (control room, metrics,
per-agent detail panels)", and Spec 01 repeats it: "Views sit over it per consumer
rather than each consumer querying raw." The point is that a consumer depends on a
named contract, so the table underneath can change shape without breaking it.
"""

from __future__ import annotations

from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode

CONSUMER_COLUMNS = ["seq", "ts", "actor", "event_type", "subject_id", "reason_code", "payload"]


def rows(pool: ConnectionPool, statement: str) -> list[tuple[object, ...]]:
    with pool.connection() as conn:
        return conn.execute(statement).fetchall()


def write_a_refusal_and_a_close(trail: AuditTrail) -> None:
    trail.record(
        actor="desk",
        event_type=EventType.CHECK_5_INSPECTION_REFUSED,
        subject_id="agent-1",
        reason_code=ReasonCode.PROMPT_INJECTION_DETECTED,
        payload={"check": 5},
    )
    trail.record(
        actor="desk",
        event_type=EventType.DEAL_CLOSED,
        subject_id="agent-2",
        payload={"margin": 0.21},
    )


def test_the_control_room_view_carries_every_entry(trail: AuditTrail, pool: ConnectionPool) -> None:
    write_a_refusal_and_a_close(trail)

    assert [row[0] for row in rows(pool, "SELECT seq FROM audit_control_room ORDER BY seq")] == [
        1,
        2,
    ]


def test_the_refusals_view_carries_only_refusals(trail: AuditTrail, pool: ConnectionPool) -> None:
    write_a_refusal_and_a_close(trail)

    found = rows(pool, "SELECT seq, reason_code FROM audit_refusals ORDER BY seq")

    assert found == [(1, "prompt_injection_detected")]


def test_the_views_do_not_expose_the_chain(trail: AuditTrail, pool: ConnectionPool) -> None:
    """The hashes are how the trail proves itself, not something a consumer draws."""
    for view in ("audit_control_room", "audit_refusals"):
        columns = [
            row[0]
            for row in rows(
                pool,
                "SELECT column_name FROM information_schema.columns"
                f" WHERE table_name = '{view}' ORDER BY ordinal_position",
            )
        ]
        assert columns == CONSUMER_COLUMNS


def test_installing_twice_is_harmless(trail: AuditTrail, pool: ConnectionPool) -> None:
    from desk.audit import install_schema

    write_a_refusal_and_a_close(trail)
    with pool.connection() as conn:
        install_schema(conn)

    assert len(trail.query()) == 2
    assert trail.verify().ok

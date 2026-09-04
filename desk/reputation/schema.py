"""One row per agent the Desk has formed an opinion of, and the bounds the database holds.

The reputation of an agent is small: a score, which rung it sits on, when it landed
there, when it last did anything, how many check-5 signals it has collected, and
whether it is blocked. Everything else -- the ceiling, the scrutiny tier, whether a
climb is due -- is derived from those by walking the ladder, so there is nothing here
to keep in step with the ladder if the ladder changes.

Two properties are the database's rather than the code's, following the audit trail's
append-only trigger and the accumulator's ceiling constraint:

- ``score`` is held in ``[0, 1]`` by a CHECK. CONTEXT.md section 10 fixes that bound,
  and a bound the code clamps to is a bound one wrong ``+=`` slips past; a bound the
  column refuses is not.
- ``blocked`` only ever goes from false to true. Unblocking a blocked agent is out of
  scope for the build (Spec 08), and a trigger that refuses the transition back is
  cheaper than trusting every future writer to remember that.

The row is created lazily -- the first time anything asks about an agent -- at the
lowest rung and the starting score. A registered agent that has never transacted has
no row and needs none; asked about, it is reported as a newcomer, which is exactly
what the lazily-created row would say.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

TABLE = "agent_reputation"


def install_schema(conn: Connection[Any]) -> None:
    """Create the reputation table if it is not there. Idempotent."""
    conn.execute(_TABLE_DDL)
    for statement in _GUARD_DDL:
        conn.execute(statement)
    for statement in _INDEX_DDL:
        conn.execute(statement)


_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    agent_id        text PRIMARY KEY,
    score           numeric NOT NULL,
    scored_at       timestamptz NOT NULL,
    rung            integer NOT NULL,
    rung_since      timestamptz NOT NULL,
    last_active_at  timestamptz NOT NULL,
    signal_count    integer NOT NULL DEFAULT 0,
    blocked         boolean NOT NULL DEFAULT false,
    created_at      timestamptz NOT NULL,
    CONSTRAINT agent_reputation_agent_is_named
        CHECK (length(btrim(agent_id)) > 0),
    -- CONTEXT.md section 10: the score is a bounded value in [0, 1].
    CONSTRAINT agent_reputation_score_in_range
        CHECK (score >= 0 AND score <= 1),
    CONSTRAINT agent_reputation_rung_is_not_negative
        CHECK (rung >= 0),
    CONSTRAINT agent_reputation_signals_not_negative
        CHECK (signal_count >= 0)
)
"""

_GUARD_DDL = (
    f"""
CREATE OR REPLACE FUNCTION {TABLE}_no_unblock() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.blocked AND NOT NEW.blocked THEN
        RAISE EXCEPTION
            'a blocked agent stays blocked; unblocking is out of scope (Spec 08)'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$
""",
    f"DROP TRIGGER IF EXISTS {TABLE}_stays_blocked ON {TABLE}",
    f"""
CREATE TRIGGER {TABLE}_stays_blocked
    BEFORE UPDATE ON {TABLE}
    FOR EACH ROW EXECUTE FUNCTION {TABLE}_no_unblock()
""",
)

_INDEX_DDL = (
    # The control room's question is "which agents are near the top, and which are
    # blocked". Answered by a scan ordered by rung, with the blocked ones grouped.
    f"CREATE INDEX IF NOT EXISTS {TABLE}_rung_idx ON {TABLE} (blocked, rung DESC)",
)

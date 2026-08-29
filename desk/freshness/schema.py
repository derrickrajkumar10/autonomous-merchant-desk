"""The nonce store: one row per presentation the Desk has already honoured.

Small on purpose. The only question it answers is *have I seen this before*, and the
only way it may answer is from durable storage -- a set in memory forgets everything a
restart touches, and "the Desk was restarted" is not a reason a replay should work
(FR-3.4).

Two properties are the database's rather than the code's, following the audit trail's
append-only trigger and the accumulator's ceiling constraint:

- The primary key **is** the uniqueness rule. Claiming a nonce is one ``INSERT ... ON
  CONFLICT DO NOTHING``, so two requests racing with the same nonce are settled by the
  index rather than by a read followed by a write. That read-then-write is the replay
  hole in miniature, and there is no way to lose a race that is never run.
- The key is ``(agent_id, nonce)`` rather than ``nonce`` alone. Nonces are chosen by
  the agent, so a global key would let one agent burn a value another was about to use.
  Scoping loses nothing: a hop captured from another agent is signed by that agent's
  key, and check 2 refuses it against the mandate's ``cnf`` long before check 4 reads a
  nonce out of it.

``audience`` is stored beside the nonce as evidence rather than as part of the key. Two
Desks sharing a database would each refuse their own replays and would not shield each
other's, which is the safe direction to be wrong in.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

from desk.freshness.key_binding import MAX_CLAIM_CHARS

TABLE = "seen_nonce"


def install_schema(conn: Connection[Any]) -> None:
    """Create the nonce store if it is not there. Idempotent."""
    conn.execute(_TABLE_DDL)
    for statement in _INDEX_DDL:
        conn.execute(statement)


_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    agent_id       text NOT NULL,
    nonce          text NOT NULL,
    audience       text NOT NULL,
    presented_at   timestamptz NOT NULL,
    first_seen_at  timestamptz NOT NULL,
    PRIMARY KEY (agent_id, nonce),
    CONSTRAINT seen_nonce_agent_is_named
        CHECK (length(btrim(agent_id)) > 0),
    CONSTRAINT seen_nonce_is_not_blank
        CHECK (length(btrim(nonce)) > 0),
    CONSTRAINT seen_nonce_audience_is_named
        CHECK (length(btrim(audience)) > 0),
    -- The same ceiling ``key_binding._required`` refuses at, said a second time by the
    -- database. A row this table cannot hold is a request the Desk must not have
    -- honoured, and only one of those two statements survives a bug in the other.
    CONSTRAINT seen_nonce_is_bounded
        CHECK (length(nonce) <= {MAX_CLAIM_CHARS}),
    CONSTRAINT seen_nonce_audience_is_bounded
        CHECK (length(audience) <= {MAX_CLAIM_CHARS})
)
"""

_INDEX_DDL = (
    # The question the primary key cannot answer: which nonces are old enough to
    # forget. ``presented_at`` is the hop's own ``iat`` and not the instant of the
    # write, because it is the hop's age that the freshness window bounds.
    f"CREATE INDEX IF NOT EXISTS {TABLE}_presented_idx ON {TABLE} (presented_at)",
)

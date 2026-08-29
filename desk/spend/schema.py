"""The accumulator table, and the ceiling the database enforces rather than the code.

One row per open Payment Mandate the Desk has ever spent against. It holds what AP2
calls "the accumulated total": the sum of the amounts of deals closed under that
mandate, which the specification makes the *verifier's* state rather than anything
carried in the credential (ADR-0004). The mandate is signed and immutable; this table
is the only thing that changes as it is drawn down.

Two properties are the database's rather than the code's, for the same reason the
audit trail's append-only rule is a trigger:

- ``spent <= ceiling`` is a CHECK constraint. If every line of Python in ``check.py``
  were wrong, the ceiling a human signed would still hold, because the row that
  breached it could not be written.
- ``ceiling`` and ``currency`` are written once from the mandate and never updated.
  The row is keyed by the mandate's digest, so its ceiling is a *function* of its key:
  a stored ceiling that disagreed with the presented mandate would mean the Desk had
  two different mandates under one digest, which is a contradiction and not a refusal.

``ceiling`` and ``spent`` are ``numeric``, which psycopg reads back as ``Decimal``.
Money never becomes a float on the way to Postgres or on the way back.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

TABLE = "mandate_spend"


def install_schema(conn: Connection[Any]) -> None:
    """Create the accumulator if it is not there. Idempotent."""
    conn.execute(_TABLE_DDL)
    for statement in _INDEX_DDL:
        conn.execute(statement)


_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    mandate_id        text PRIMARY KEY,
    digest_algorithm  text NOT NULL,
    currency          text NOT NULL,
    ceiling           numeric NOT NULL,
    spent             numeric NOT NULL DEFAULT 0,
    first_seen_at     timestamptz NOT NULL,
    updated_at        timestamptz NOT NULL,
    CONSTRAINT mandate_spend_id_is_a_digest
        CHECK (mandate_id ~ '^[A-Za-z0-9_-]{{16,}}$'),
    CONSTRAINT mandate_spend_algorithm_is_named
        CHECK (length(btrim(digest_algorithm)) > 0),
    CONSTRAINT mandate_spend_currency_is_iso4217
        CHECK (currency ~ '^[A-Z]{{3}}$'),
    CONSTRAINT mandate_spend_ceiling_authorises_something
        CHECK (ceiling > 0),
    CONSTRAINT mandate_spend_is_not_negative
        CHECK (spent >= 0),
    -- The ceiling the principal signed, enforced by the database and not by us.
    CONSTRAINT mandate_spend_within_ceiling
        CHECK (spent <= ceiling)
)
"""

_INDEX_DDL = (
    # The control room's question is "what is this mandate's remaining balance",
    # answered by the primary key. This one answers the other question anyone asks of
    # a ledger: which mandates were drawn down, most recently first.
    f"CREATE INDEX IF NOT EXISTS {TABLE}_updated_idx ON {TABLE} (updated_at DESC)",
)

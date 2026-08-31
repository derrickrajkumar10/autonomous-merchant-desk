"""The receipt table, and the two questions it is shaped around.

**The signed receipt is the truth; the columns are an index into it.** Every column
here except ``receipt`` is a copy of something already inside the signed document, put
in a column so it can be searched. Nothing reads a column and believes it: ``store.py``
verifies the JWS on the way back out, so a row somebody edited stops verifying rather
than quietly answering a query with a number nobody signed.

**Queryable by amount and by date, which is the shape settlement proof needs.** Bank
line matching (ticket 17) arrives with a credit and a date and asks which receipts
could add up to it. That is a range scan over ``(currency, amount)`` and a range scan
over ``issued_at``, and designing for it now costs one index each and avoids a
migration against a table of signed artefacts later.

**One receipt per closed deal, enforced by the primary key.** ``receipt_id`` is the
closed Checkout Mandate's hash, so settling one deal twice cannot produce two receipts
even if something upstream tried -- and a treasury summing receipts cannot double-count
a deal. ``store.py`` looks for the existing row before charging, so the ordinary retry
never reaches this constraint; the constraint is what holds if it did.

``amount`` is ``numeric``, which psycopg reads back as ``Decimal``. Money never becomes
a float on the way to Postgres or on the way back.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

TABLE = "receipt"


def install_schema(conn: Connection[Any]) -> None:
    """Create the receipt table if it is not there. Idempotent."""
    conn.execute(_TABLE_DDL)
    for statement in _INDEX_DDL:
        conn.execute(statement)


_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    receipt_id      text PRIMARY KEY,
    agent_id        text NOT NULL,
    open_checkout   text NOT NULL,
    open_payment    text NOT NULL,
    currency        text NOT NULL,
    amount          numeric NOT NULL,
    issued_at       timestamptz NOT NULL,
    rail            text NOT NULL,
    charge_id       text NOT NULL,
    receipt         text NOT NULL,
    CONSTRAINT receipt_id_is_a_digest
        CHECK (receipt_id ~ '^[A-Za-z0-9_-]{{16,}}$'),
    CONSTRAINT receipt_agent_is_named
        CHECK (length(btrim(agent_id)) > 0),
    CONSTRAINT receipt_chain_is_complete
        CHECK (length(btrim(open_checkout)) > 0 AND length(btrim(open_payment)) > 0),
    CONSTRAINT receipt_currency_is_iso4217
        CHECK (currency ~ '^[A-Z]{{3}}$'),
    -- A receipt for nothing is not a receipt. The rail was asked for a positive
    -- amount and said it took one; a row saying otherwise is a contradiction.
    CONSTRAINT receipt_is_for_something
        CHECK (amount > 0),
    CONSTRAINT receipt_names_the_rail
        CHECK (length(btrim(rail)) > 0 AND length(btrim(charge_id)) > 0),
    -- A compact JWS is three base64url segments. Not a signature check -- that is
    -- store.py's, against the Desk's key -- but it keeps a truncated row out.
    CONSTRAINT receipt_is_a_compact_jws
        CHECK (receipt ~ '^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$')
)
"""

_INDEX_DDL = (
    # The two settlement proof reads for, and nothing else. A bank line arrives as an
    # amount and a date; these are the two range scans that answers.
    f"CREATE INDEX IF NOT EXISTS {TABLE}_amount_idx ON {TABLE} (currency, amount)",
    f"CREATE INDEX IF NOT EXISTS {TABLE}_issued_idx ON {TABLE} (issued_at)",
    # And the control room's: what has this agent been charged.
    f"CREATE INDEX IF NOT EXISTS {TABLE}_agent_idx ON {TABLE} (agent_id, issued_at)",
)

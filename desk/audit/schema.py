"""The table, and the two properties the database enforces rather than the code.

Append-only is a trigger, not a convention: nothing in the system may ``UPDATE``,
``DELETE`` or ``TRUNCATE`` here (ADR-0006), and a reviewer should not have to be the
thing that catches an attempt. Chain linkage is a trigger too, so an entry that does
not chain onto the one before it cannot be inserted at all.

The two enum types are generated from the Python enums, so the vocabularies cannot
drift apart. If a type already exists with different members, installing raises
rather than silently leaving the database a version behind.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from psycopg import Connection, sql

from desk.audit.entry import GENESIS_HASH
from desk.audit.vocabulary import EventType, ReasonCode

EVENT_TYPE_TYPE = "audit_event_type"
REASON_CODE_TYPE = "audit_reason_code"
TABLE = "audit_entry"


class SchemaDrift(RuntimeError):
    """A database enum no longer matches its Python enum. Growing one is deliberate."""


def install_schema(conn: Connection[Any]) -> None:
    """Create the trail if it is not there. Idempotent."""
    _install_enum(conn, EVENT_TYPE_TYPE, [event.value for event in EventType])
    _install_enum(conn, REASON_CODE_TYPE, [reason.value for reason in ReasonCode])
    conn.execute(_TABLE_DDL)
    for statement in _GUARD_DDL:
        conn.execute(statement)
    for statement in _INDEX_DDL:
        conn.execute(statement)
    for statement in _VIEW_DDL:
        conn.execute(statement)


def _install_enum(conn: Connection[Any], type_name: str, values: Sequence[str]) -> None:
    installed = {
        row[0]
        for row in conn.execute(
            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"
            " WHERE t.typname = %s",
            (type_name,),
        ).fetchall()
    }
    if not installed:
        conn.execute(
            sql.SQL("CREATE TYPE {} AS ENUM ({})").format(
                sql.Identifier(type_name),
                sql.SQL(", ").join(sql.Literal(value) for value in values),
            )
        )
        return

    wanted = set(values)
    if installed != wanted:
        raise SchemaDrift(
            f"the {type_name} database type does not match its Python enum: "
            f"missing {sorted(wanted - installed)}, unexpected {sorted(installed - wanted)}. "
            f"Growing a closed vocabulary is a deliberate act and needs a migration."
        )


_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    seq         bigint PRIMARY KEY,
    ts          timestamptz NOT NULL,
    actor       text NOT NULL,
    event_type  {EVENT_TYPE_TYPE} NOT NULL,
    subject_id  text NOT NULL,
    reason_code {REASON_CODE_TYPE},
    payload     jsonb NOT NULL,
    prev_hash   text NOT NULL,
    hash        text NOT NULL UNIQUE,
    CONSTRAINT audit_entry_seq_is_positive CHECK (seq > 0),
    CONSTRAINT audit_entry_actor_is_named CHECK (length(btrim(actor)) > 0),
    CONSTRAINT audit_entry_subject_is_named CHECK (length(btrim(subject_id)) > 0),
    CONSTRAINT audit_entry_payload_is_an_object CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT audit_entry_prev_hash_is_a_digest CHECK (prev_hash ~ '^[0-9a-f]{{64}}$'),
    CONSTRAINT audit_entry_hash_is_a_digest CHECK (hash ~ '^[0-9a-f]{{64}}$')
)
"""

_GUARD_DDL = (
    f"""
CREATE OR REPLACE FUNCTION {TABLE}_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        '{TABLE} is append-only; % is not permitted. A correction is a new entry.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$
""",
    f"""
CREATE OR REPLACE FUNCTION {TABLE}_chain_link() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    previous_hash text;
BEGIN
    IF NEW.seq = 1 THEN
        IF NEW.prev_hash <> '{GENESIS_HASH}' THEN
            RAISE EXCEPTION 'the first audit entry must chain onto the genesis hash';
        END IF;
        RETURN NEW;
    END IF;

    SELECT hash INTO previous_hash FROM {TABLE} WHERE seq = NEW.seq - 1;
    IF previous_hash IS NULL THEN
        RAISE EXCEPTION 'audit entry % has no entry % to chain onto', NEW.seq, NEW.seq - 1;
    END IF;
    IF previous_hash <> NEW.prev_hash THEN
        RAISE EXCEPTION 'audit entry % does not chain onto entry %', NEW.seq, NEW.seq - 1;
    END IF;
    RETURN NEW;
END;
$$
""",
    f"DROP TRIGGER IF EXISTS {TABLE}_no_change ON {TABLE}",
    f"""
CREATE TRIGGER {TABLE}_no_change
    BEFORE UPDATE OR DELETE ON {TABLE}
    FOR EACH STATEMENT EXECUTE FUNCTION {TABLE}_append_only()
""",
    f"DROP TRIGGER IF EXISTS {TABLE}_no_truncate ON {TABLE}",
    f"""
CREATE TRIGGER {TABLE}_no_truncate
    BEFORE TRUNCATE ON {TABLE}
    FOR EACH STATEMENT EXECUTE FUNCTION {TABLE}_append_only()
""",
    f"DROP TRIGGER IF EXISTS {TABLE}_chain ON {TABLE}",
    f"""
CREATE TRIGGER {TABLE}_chain
    BEFORE INSERT ON {TABLE}
    FOR EACH ROW EXECUTE FUNCTION {TABLE}_chain_link()
""",
)

# ADR-0006 puts views per consumer over the table "rather than each consumer querying
# raw", so that the table can change shape without every consumer changing with it.
# Only the two consumers whose shape is knowable now get one. A per-agent detail panel
# reads `audit_control_room` filtered by subject_id, and a view that only hard-codes a
# WHERE clause a caller must supply anyway would earn nothing.
_VIEW_DDL = (
    f"""
CREATE OR REPLACE VIEW audit_control_room AS
    SELECT seq, ts, actor, event_type, subject_id, reason_code, payload
    FROM {TABLE}
""",
    f"""
CREATE OR REPLACE VIEW audit_refusals AS
    SELECT seq, ts, actor, event_type, subject_id, reason_code, payload
    FROM {TABLE}
    WHERE reason_code IS NOT NULL
""",
)

_INDEX_DDL = (
    f"CREATE INDEX IF NOT EXISTS {TABLE}_subject_idx ON {TABLE} (subject_id, seq)",
    f"CREATE INDEX IF NOT EXISTS {TABLE}_reason_idx ON {TABLE} (reason_code, seq)"
    " WHERE reason_code IS NOT NULL",
    f"CREATE INDEX IF NOT EXISTS {TABLE}_event_idx ON {TABLE} (event_type, seq)",
    f"CREATE INDEX IF NOT EXISTS {TABLE}_ts_idx ON {TABLE} (ts, seq)",
)

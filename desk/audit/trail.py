"""The audit trail: write an entry, read entries back, prove nothing was altered.

This is the surface every later ticket writes to and the only source the control
room, the published metrics and the test suite read from. One contract, exercised
three ways.

Writing is synchronous with the decision it records. A decision that happened but
was not recorded is worse than no decision, because every downstream consumer then
disagrees with reality.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from desk.audit.entry import GENESIS_HASH, AuditEntry, canonical_payload
from desk.audit.schema import TABLE
from desk.audit.vocabulary import (
    EventType,
    ReasonCode,
    coerce_event_type,
    coerce_reason_code,
)

_COLUMNS = "seq, ts, actor, event_type, subject_id, reason_code, payload, prev_hash, hash"

# Appends serialise on one advisory lock so that the sequence stays gapless and each
# entry chains onto the entry that really precedes it. Derived from the table name so
# it cannot collide with another subsystem's lock by accident.
_CHAIN_LOCK_KEY = int.from_bytes(
    hashlib.sha256(f"stitchai.{TABLE}".encode()).digest()[:8], "big", signed=True
)


class ChainBreak(StrEnum):
    """How a chain failed to verify."""

    ENTRY_MISSING = "entry_missing"
    LINK_BROKEN = "link_broken"
    CONTENT_ALTERED = "content_altered"
    HEAD_UNEXPECTED = "head_unexpected"


@dataclass(frozen=True)
class ChainVerification:
    """The result of one forward pass over the chain."""

    ok: bool
    entries_checked: int
    break_at: int | None = None
    break_kind: ChainBreak | None = None
    detail: str | None = None


class AuditTrail:
    """Append-only, hash-chained record of every decision the Desk makes.

    Install the schema once with ``install_schema``; this class does not migrate.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def record(
        self,
        *,
        actor: str,
        event_type: EventType | str,
        subject_id: str,
        payload: Mapping[str, Any],
        reason_code: ReasonCode | str | None = None,
    ) -> AuditEntry:
        """Write one entry and return it as written.

        ``payload`` carries the reasoning, the evidence and the resulting state change
        (FR-10.1). Everything is validated before a connection is taken, so a rejected
        write leaves no trace and no gap in the sequence.
        """
        event = coerce_event_type(event_type)
        reason = None if reason_code is None else coerce_reason_code(reason_code)
        actor = _required(actor, "actor")
        subject_id = _required(subject_id, "subject_id")
        body = canonical_payload(payload)

        with self._pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (_CHAIN_LOCK_KEY,))
            head = conn.execute(
                f"SELECT seq, hash FROM {TABLE} ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            prev_seq, prev_hash = head if head is not None else (0, GENESIS_HASH)
            clock = conn.execute("SELECT clock_timestamp()").fetchone()
            assert clock is not None

            draft = AuditEntry(
                seq=prev_seq + 1,
                ts=clock[0],
                actor=actor,
                event_type=event,
                subject_id=subject_id,
                reason_code=reason,
                payload=body,
                prev_hash=prev_hash,
                hash="",
            )
            entry = dataclasses.replace(draft, hash=draft.recompute_hash())

            conn.execute(
                f"INSERT INTO {TABLE} ({_COLUMNS}) VALUES"
                f" (%s, %s, %s, %s::audit_event_type, %s, %s::audit_reason_code, %s, %s, %s)",
                (
                    entry.seq,
                    entry.ts,
                    entry.actor,
                    entry.event_type.value,
                    entry.subject_id,
                    None if entry.reason_code is None else entry.reason_code.value,
                    Jsonb(entry.payload),
                    entry.prev_hash,
                    entry.hash,
                ),
            )
        return entry

    def query(
        self,
        *,
        subject_id: str | None = None,
        event_type: EventType | str | None = None,
        reason_code: ReasonCode | str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        after_seq: int | None = None,
        limit: int | None = None,
    ) -> list[AuditEntry]:
        """Entries matching every filter given, in sequence order.

        ``since`` is inclusive and ``until`` exclusive, so adjacent windows tile
        without double-counting. ``after_seq`` is exclusive, which is how the control
        room tails the trail without re-reading what it has already drawn.
        """
        conditions: list[sql.Composable] = []
        params: list[Any] = []

        if subject_id is not None:
            conditions.append(sql.SQL("subject_id = %s"))
            params.append(subject_id)
        if event_type is not None:
            conditions.append(sql.SQL("event_type = %s::audit_event_type"))
            params.append(coerce_event_type(event_type).value)
        if reason_code is not None:
            conditions.append(sql.SQL("reason_code = %s::audit_reason_code"))
            params.append(coerce_reason_code(reason_code).value)
        if since is not None:
            conditions.append(sql.SQL("ts >= %s"))
            params.append(since)
        if until is not None:
            conditions.append(sql.SQL("ts < %s"))
            params.append(until)
        if after_seq is not None:
            conditions.append(sql.SQL("seq > %s"))
            params.append(after_seq)

        statement = sql.SQL("SELECT {columns} FROM {table}").format(
            columns=sql.SQL(_COLUMNS), table=sql.Identifier(TABLE)
        )
        if conditions:
            statement = statement + sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
        statement = statement + sql.SQL(" ORDER BY seq")
        if limit is not None:
            statement = statement + sql.SQL(" LIMIT %s")
            params.append(limit)

        with self._pool.connection() as conn:
            rows = conn.execute(statement, params).fetchall()
        return [_to_entry(row) for row in rows]

    def head(self) -> AuditEntry | None:
        """The last entry written, or ``None`` on an empty trail."""
        with self._pool.connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM {TABLE} ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return None if row is None else _to_entry(row)

    def verify(self, *, expected_head_hash: str | None = None) -> ChainVerification:
        """Walk the chain once, forward, and report the first break.

        Streams, so this is cheap enough to run in tests and after a batch run.

        A hash chain cannot see history lopped off its own head: what is left is
        internally consistent. Pass ``expected_head_hash`` — a head a caller recorded
        earlier — to catch that too.
        """
        expected_seq = 1
        prev_hash = GENESIS_HASH
        checked = 0

        with self._pool.connection() as conn, conn.cursor(name=f"{TABLE}_scan") as cursor:
            cursor.itersize = 1000
            cursor.execute(f"SELECT {_COLUMNS} FROM {TABLE} ORDER BY seq")
            for row in cursor:
                entry = _to_entry(row)

                if entry.seq != expected_seq:
                    return ChainVerification(
                        ok=False,
                        entries_checked=checked,
                        break_at=expected_seq,
                        break_kind=ChainBreak.ENTRY_MISSING,
                        detail=f"entry {expected_seq} is missing; the trail jumps to {entry.seq}",
                    )
                if entry.prev_hash != prev_hash:
                    return ChainVerification(
                        ok=False,
                        entries_checked=checked,
                        break_at=entry.seq,
                        break_kind=ChainBreak.LINK_BROKEN,
                        detail=f"entry {entry.seq} does not chain onto entry {entry.seq - 1}",
                    )
                if entry.recompute_hash() != entry.hash:
                    return ChainVerification(
                        ok=False,
                        entries_checked=checked,
                        break_at=entry.seq,
                        break_kind=ChainBreak.CONTENT_ALTERED,
                        detail=f"entry {entry.seq} does not hash to its recorded hash",
                    )

                checked += 1
                expected_seq += 1
                prev_hash = entry.hash

        if expected_head_hash is not None and prev_hash != expected_head_hash:
            return ChainVerification(
                ok=False,
                entries_checked=checked,
                break_at=checked,
                break_kind=ChainBreak.HEAD_UNEXPECTED,
                detail=(
                    f"the trail ends at {prev_hash}, not at the expected "
                    f"{expected_head_hash}; entries after it have been removed"
                ),
            )
        return ChainVerification(ok=True, entries_checked=checked)


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"an audit entry needs a {field}")
    return value


def _to_entry(row: Sequence[Any]) -> AuditEntry:
    seq, ts, actor, event_type, subject_id, reason_code, payload, prev_hash, digest = row
    return AuditEntry(
        seq=seq,
        ts=ts,
        actor=actor,
        event_type=EventType(event_type),
        subject_id=subject_id,
        reason_code=None if reason_code is None else ReasonCode(reason_code),
        payload=payload,
        prev_hash=prev_hash,
        hash=digest,
    )

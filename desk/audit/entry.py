"""One entry, and the hash that binds it to the one before it.

The chain is the answer to "could you have doctored this?". Each entry hashes its
own contents together with the previous entry's hash, so altering or removing
history is visible on a single forward pass.

Hashing is defined here rather than in the database so that anyone holding the
entries — the control room, the metrics, a judge with a dump of the table — can
recompute it without Postgres.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from desk.audit.vocabulary import EventType, ReasonCode

#: What the first entry chains onto. Sixty-four zeroes, so it is the right shape for
#: the column and unmistakable on sight.
GENESIS_HASH = "0" * 64


def _dumps(document: Any) -> str:
    """One canonical JSON form: keys sorted, no incidental whitespace, no NaN."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def json_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Check a payload is storable, and return it as plain JSON types.

    Raises ``ValueError`` rather than letting an unstorable payload through, because
    a write that fails now is better than an entry that fails to verify later.

    This is not the last word on the payload's shape: Postgres normalises ``jsonb``
    further, and the hash is taken over *that* form. See ``AuditTrail.record``.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(f"an audit payload must be a mapping, not {type(payload).__name__}")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("audit payload keys must be strings")
    try:
        text = _dumps(dict(payload))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"an audit payload must be JSON-serialisable: {exc}") from exc
    plain: dict[str, Any] = json.loads(text)
    return plain


def _canonical_bytes(entry: AuditEntry) -> bytes:
    """The exact bytes an entry's hash is taken over.

    Sorted keys, no incidental whitespace, timestamps normalised to UTC — so that two
    readers of the same entry always hash the same bytes.
    """
    if entry.ts.tzinfo is None:
        raise ValueError("an audit timestamp must carry a timezone")
    document = {
        "seq": entry.seq,
        "ts": entry.ts.astimezone(UTC).isoformat(),
        "actor": entry.actor,
        "event_type": EventType(entry.event_type).value,
        "subject_id": entry.subject_id,
        "reason_code": (None if entry.reason_code is None else ReasonCode(entry.reason_code).value),
        "payload": dict(entry.payload),
        "prev_hash": entry.prev_hash,
    }
    return _dumps(document).encode("utf-8")


@dataclass(frozen=True)
class AuditEntry:
    """One decision the Desk made.

    ``payload`` carries the parts FR-10.1 asks for beyond the columns: the reasoning,
    the evidence behind it, and the resulting state change. It is one free-shaped
    object rather than a column each, so that every subsystem writes the same entry
    shape and a new consumer has one format to learn.
    """

    seq: int
    ts: datetime
    actor: str
    event_type: EventType
    subject_id: str
    reason_code: ReasonCode | None
    payload: Mapping[str, Any]
    prev_hash: str
    hash: str

    def recompute_hash(self) -> str:
        """The hash this entry's own contents imply. Equals ``hash`` unless altered.

        This is how anyone holding the entries verifies them — the control room, the
        metrics, or a judge with a dump of the table and no Postgres to hand.
        """
        return hashlib.sha256(_canonical_bytes(self)).hexdigest()

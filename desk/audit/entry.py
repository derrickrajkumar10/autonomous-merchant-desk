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


def canonical_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a payload to what will survive a round trip through ``jsonb``.

    Raises ``ValueError`` if the payload could not be stored and read back unchanged,
    because an entry that does not verify later is worse than a write that fails now.
    """
    if not isinstance(payload, Mapping):
        raise ValueError(f"an audit payload must be a mapping, not {type(payload).__name__}")
    if any(not isinstance(key, str) for key in payload):
        raise ValueError("audit payload keys must be strings")
    try:
        text = _dumps(dict(payload))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"an audit payload must be JSON-serialisable: {exc}") from exc
    normalised: dict[str, Any] = json.loads(text)
    return normalised


def canonical_bytes(
    *,
    seq: int,
    ts: datetime,
    actor: str,
    event_type: EventType,
    subject_id: str,
    reason_code: ReasonCode | None,
    payload: Mapping[str, Any],
    prev_hash: str,
) -> bytes:
    """The exact bytes an entry's hash is taken over."""
    if ts.tzinfo is None:
        raise ValueError("an audit timestamp must carry a timezone")
    document = {
        "seq": seq,
        "ts": ts.astimezone(UTC).isoformat(),
        "actor": actor,
        "event_type": EventType(event_type).value,
        "subject_id": subject_id,
        "reason_code": None if reason_code is None else ReasonCode(reason_code).value,
        "payload": dict(payload),
        "prev_hash": prev_hash,
    }
    return _dumps(document).encode("utf-8")


def compute_hash(
    *,
    seq: int,
    ts: datetime,
    actor: str,
    event_type: EventType,
    subject_id: str,
    reason_code: ReasonCode | None,
    payload: Mapping[str, Any],
    prev_hash: str,
) -> str:
    return hashlib.sha256(
        canonical_bytes(
            seq=seq,
            ts=ts,
            actor=actor,
            event_type=event_type,
            subject_id=subject_id,
            reason_code=reason_code,
            payload=payload,
            prev_hash=prev_hash,
        )
    ).hexdigest()


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
        """The hash this entry's own contents imply. Equals ``hash`` unless altered."""
        return compute_hash(
            seq=self.seq,
            ts=self.ts,
            actor=self.actor,
            event_type=self.event_type,
            subject_id=self.subject_id,
            reason_code=self.reason_code,
            payload=self.payload,
            prev_hash=self.prev_hash,
        )

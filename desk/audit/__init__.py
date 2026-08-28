"""The audit trail — the Desk's record of every decision it makes.

One append-only, hash-chained table. Every decision the Desk makes is written here
with the check or policy that fired, the reasoning, the evidence and the resulting
state change, and is queryable afterwards (FR-10.1, FR-10.2). Refusal reasons come
from a closed set so they aggregate into metrics instead of scattering into free
text. Nothing updates or deletes; a correction is a new entry.

See ADR-0006 for the decision, and CONTEXT.md §5 principle 5 for why it exists.

    from psycopg_pool import ConnectionPool
    from desk.audit import AuditTrail, EventType, ReasonCode, install_schema

    with ConnectionPool(dsn) as pool:
        with pool.connection() as conn:
            install_schema(conn)

        trail = AuditTrail(pool)
        trail.record(
            actor="desk",
            event_type=EventType.CHECK_2_MANDATE_VALIDITY_REFUSED,
            subject_id="agent-7",
            reason_code=ReasonCode.MANDATE_EXPIRED,
            payload={
                "check": 2,
                "reasoning": "the open mandate expired before the request arrived",
                "evidence": {"expires_at": "...", "received_at": "..."},
                "state_change": {"deal": "refused"},
            },
        )
        assert trail.verify().ok
"""

from desk.audit.entry import (
    GENESIS_HASH,
    AuditEntry,
    canonical_bytes,
    canonical_payload,
    compute_hash,
)
from desk.audit.schema import SchemaDrift, install_schema
from desk.audit.trail import AuditTrail, ChainBreak, ChainVerification
from desk.audit.vocabulary import (
    EventType,
    ReasonCode,
    UnknownEventType,
    UnknownReasonCode,
)

__all__ = [
    "GENESIS_HASH",
    "AuditEntry",
    "AuditTrail",
    "ChainBreak",
    "ChainVerification",
    "EventType",
    "ReasonCode",
    "SchemaDrift",
    "UnknownEventType",
    "UnknownReasonCode",
    "canonical_bytes",
    "canonical_payload",
    "compute_hash",
    "install_schema",
]

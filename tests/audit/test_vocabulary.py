"""The closed vocabularies: reason codes and event types.

Acceptance criteria: an unrecognised reason code is rejected rather than stored as
free text; the event type vocabulary covers every event named in Spec 01.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode, UnknownEventType, UnknownReasonCode

# The seventeen members ADR-0006 names as the starting vocabulary. Growing this list
# is a deliberate act, so it is spelled out here rather than derived from the enum.
ADR_0006_REASON_CODES = {
    "agent_signature_invalid",
    "mandate_signature_invalid",
    "mandate_expired",
    "agent_mandate_mismatch",
    "exceeds_remaining_balance",
    "category_not_authorised",
    "outside_validity_window",
    "nonce_replayed",
    "request_stale",
    "prompt_injection_detected",
    "escalation_pattern_detected",
    "below_margin_floor",
    "agent_blocked",
    "ceiling_exceeded_for_tier",
    "treasury_buffer_insufficient",
    "bank_line_unmatched",
    "bank_line_ambiguous",
}

# Every event Spec 01 names. Checks are listed per check, because §9 requires
# refusals broken down by check and FR-10.1 requires the entry to name which check
# fired. Spec 01 says "at least" these, so the enum may hold more but never fewer.
SPEC_01_EVENT_TYPES = {
    "agent_registered",
    "request_received",
    "check_1_identity_passed",
    "check_1_identity_refused",
    "check_2_mandate_validity_passed",
    "check_2_mandate_validity_refused",
    "check_3_spend_authority_passed",
    "check_3_spend_authority_refused",
    "check_4_replay_freshness_passed",
    "check_4_replay_freshness_refused",
    "check_5_inspection_passed",
    "check_5_inspection_refused",
    "negotiation_message_sent",
    "lever_offered",
    "deal_closed",
    "walked_away",
    "receipt_issued",
    "procurement_triggered",
    "quote_received",
    "supplier_selected",
    "order_placed",
    "treasury_gate_evaluated",
    "bank_line_received",
    "match_found",
    "exception_recorded",
    "trust_score_changed",
    "rung_changed",
}


# Members added since, each beside the ticket that added it and why. A code arriving
# without a line here means the vocabulary grew without anyone deciding it should.
ADDED_SINCE = {
    # Ticket 02: a registered key re-presented naming a different principal, which is an
    # attempt to move an identity's stated source of authority.
    "agent_principal_mismatch",
}


def test_reason_codes_are_the_adr_0006_vocabulary_and_what_was_added_deliberately() -> None:
    assert {code.value for code in ReasonCode} == ADR_0006_REASON_CODES | ADDED_SINCE


def test_event_types_cover_every_event_named_in_spec_01() -> None:
    assert {event.value for event in EventType} >= SPEC_01_EVENT_TYPES


def test_an_unrecognised_reason_code_is_rejected(trail: AuditTrail) -> None:
    with pytest.raises(UnknownReasonCode) as raised:
        trail.record(
            actor="desk",
            event_type=EventType.CHECK_2_MANDATE_VALIDITY_REFUSED,
            subject_id="agent-1",
            reason_code="mandate_smelled_wrong",
            payload={},
        )

    assert "mandate_smelled_wrong" in str(raised.value)
    assert trail.query() == []


def test_an_unrecognised_event_type_is_rejected(trail: AuditTrail) -> None:
    with pytest.raises(UnknownEventType):
        trail.record(
            actor="desk",
            event_type="agent_did_something",
            subject_id="agent-1",
            payload={},
        )

    assert trail.query() == []


def test_known_codes_may_be_named_by_their_string_value(trail: AuditTrail) -> None:
    entry = trail.record(
        actor="desk",
        event_type="check_2_mandate_validity_refused",
        subject_id="agent-1",
        reason_code="mandate_expired",
        payload={},
    )

    assert entry.event_type is EventType.CHECK_2_MANDATE_VALIDITY_REFUSED
    assert entry.reason_code is ReasonCode.MANDATE_EXPIRED


def test_the_database_itself_refuses_free_text(pool: ConnectionPool, trail: AuditTrail) -> None:
    """The closed enum is a database type, not merely a convention in Python.

    A write that goes around the trail cannot smuggle in a novel reason string.
    """
    trail.record(
        actor="desk",
        event_type=EventType.REQUEST_RECEIVED,
        subject_id="agent-1",
        payload={},
    )

    with pytest.raises(psycopg.errors.InvalidTextRepresentation), pool.connection() as conn:
        conn.execute(
            "INSERT INTO audit_entry"
            " (seq, ts, actor, event_type, subject_id, reason_code, payload, prev_hash, hash)"
            " VALUES (2, now(), 'desk', 'request_received', 'agent-1',"
            " 'mandate_smelled_wrong', '{}'::jsonb, repeat('0', 64), repeat('a', 64))"
        )

"""The two closed vocabularies the trail is written in.

Both are closed on purpose. A refusal reason drawn from a fixed set aggregates into
a metric; a free-text one scatters (ADR-0006). An event type drawn from a fixed set
is something the control room can subscribe to; a novel string is a bug that only
shows up on screen. Adding a member to either is a deliberate act, visible in
review, and needs a matching change to the database type (see ``schema.py``).
"""

from __future__ import annotations

from enum import StrEnum


class UnknownReasonCode(ValueError):
    """A reason code outside the closed set. Refused rather than stored as free text."""


class UnknownEventType(ValueError):
    """An event type outside the closed set."""


class ReasonCode(StrEnum):
    """Why the Desk refused, or what a settlement proof concluded.

    The seventeen members ADR-0006 names as the starting vocabulary: the four
    deterministic checks' refusals, the two judgment refusals, the margin floor, the
    blocked agent, the tier ceiling, the treasury buffer, and the two settlement-proof
    outcomes. Members added since are grouped and dated by the ticket that added them,
    so growth stays a deliberate act rather than a drift.
    """

    # Registration (Ticket 02)
    AGENT_PRINCIPAL_MISMATCH = "agent_principal_mismatch"

    # Check 1 - identity
    AGENT_SIGNATURE_INVALID = "agent_signature_invalid"

    # Check 2 - mandate validity
    MANDATE_SIGNATURE_INVALID = "mandate_signature_invalid"
    MANDATE_EXPIRED = "mandate_expired"
    AGENT_MANDATE_MISMATCH = "agent_mandate_mismatch"

    # Check 3 - spend authority
    EXCEEDS_REMAINING_BALANCE = "exceeds_remaining_balance"
    CATEGORY_NOT_AUTHORISED = "category_not_authorised"
    OUTSIDE_VALIDITY_WINDOW = "outside_validity_window"

    # Check 4 - replay and freshness
    NONCE_REPLAYED = "nonce_replayed"
    REQUEST_STALE = "request_stale"

    # Check 5 - content and behaviour inspection
    PROMPT_INJECTION_DETECTED = "prompt_injection_detected"
    ESCALATION_PATTERN_DETECTED = "escalation_pattern_detected"

    # Negotiation and the reputation ladder
    BELOW_MARGIN_FLOOR = "below_margin_floor"
    AGENT_BLOCKED = "agent_blocked"
    CEILING_EXCEEDED_FOR_TIER = "ceiling_exceeded_for_tier"

    # Treasury
    TREASURY_BUFFER_INSUFFICIENT = "treasury_buffer_insufficient"

    # Settlement proof
    BANK_LINE_UNMATCHED = "bank_line_unmatched"
    BANK_LINE_AMBIGUOUS = "bank_line_ambiguous"


class EventType(StrEnum):
    """What happened.

    Designed here and not grown ad hoc, because the control room subscribes to it and
    every subsequent ticket writes to it. Each of the five checks passes or refuses
    under its own member, so that refusals break down by check (§9) without reading
    into a payload.
    """

    AGENT_REGISTERED = "agent_registered"
    AGENT_REGISTRATION_REFUSED = "agent_registration_refused"
    REQUEST_RECEIVED = "request_received"

    CHECK_1_IDENTITY_PASSED = "check_1_identity_passed"
    CHECK_1_IDENTITY_REFUSED = "check_1_identity_refused"
    CHECK_2_MANDATE_VALIDITY_PASSED = "check_2_mandate_validity_passed"
    CHECK_2_MANDATE_VALIDITY_REFUSED = "check_2_mandate_validity_refused"
    CHECK_3_SPEND_AUTHORITY_PASSED = "check_3_spend_authority_passed"
    CHECK_3_SPEND_AUTHORITY_REFUSED = "check_3_spend_authority_refused"
    CHECK_4_REPLAY_FRESHNESS_PASSED = "check_4_replay_freshness_passed"
    CHECK_4_REPLAY_FRESHNESS_REFUSED = "check_4_replay_freshness_refused"
    CHECK_5_INSPECTION_PASSED = "check_5_inspection_passed"
    CHECK_5_INSPECTION_REFUSED = "check_5_inspection_refused"
    # Check 5 has two halves (Spec 07). The Inspector reads one message's text
    # (``inspection``, Ticket 10); the behavioural score reads the agent's own request
    # history (``behaviour``, Ticket 11). They are separate members and not a payload
    # flag because the control room subscribes by event type, and "an escalation
    # pattern was seen" is a different thing on screen from "this message was an
    # injection".
    CHECK_5_BEHAVIOUR_PASSED = "check_5_behaviour_passed"
    CHECK_5_BEHAVIOUR_REFUSED = "check_5_behaviour_refused"

    NEGOTIATION_MESSAGE_SENT = "negotiation_message_sent"
    LEVER_OFFERED = "lever_offered"
    DEAL_CLOSED = "deal_closed"
    WALKED_AWAY = "walked_away"

    # Settlement (Ticket 09). Three members and not two: an attempt written before the
    # rail is called is the only thing that shows a charge the Desk never heard back
    # about, and a pair of members that only ever appear after an answer could not.
    # ``receipt_issued`` is the third -- the succeeded case, named for its artefact
    # because the artefact is the point.
    SETTLEMENT_ATTEMPTED = "settlement_attempted"
    SETTLEMENT_INCOMPLETE = "settlement_incomplete"
    RECEIPT_ISSUED = "receipt_issued"

    PROCUREMENT_TRIGGERED = "procurement_triggered"
    QUOTE_RECEIVED = "quote_received"
    SUPPLIER_SELECTED = "supplier_selected"
    ORDER_PLACED = "order_placed"

    TREASURY_GATE_EVALUATED = "treasury_gate_evaluated"
    BANK_LINE_RECEIVED = "bank_line_received"
    MATCH_FOUND = "match_found"
    EXCEPTION_RECORDED = "exception_recorded"

    # Reputation ladder (Ticket 12). A score change and a rung change are separate
    # members, not one with a flag, because the control room subscribes by event type
    # and "this agent moved up a rung" is a different thing on screen from "its score
    # ticked". The standing gate -- reputation's one refusal, run after the spine --
    # passes or refuses under its own pair, so refusals still break down by the step
    # that made them (CONTEXT.md section 9). ``agent_blocked`` marks the moment an
    # agent crosses the bad-behaviour threshold; its reason code has the same string.
    TRUST_SCORE_CHANGED = "trust_score_changed"
    RUNG_CHANGED = "rung_changed"
    STANDING_GATE_PASSED = "standing_gate_passed"
    STANDING_GATE_REFUSED = "standing_gate_refused"
    AGENT_BLOCKED = "agent_blocked"


def coerce_reason_code(value: ReasonCode | str) -> ReasonCode:
    try:
        return ReasonCode(value)
    except ValueError:
        raise UnknownReasonCode(
            f"{value!r} is not a reason code. The set is closed; adding one means adding "
            f"a member to ReasonCode and migrating the audit_reason_code database type."
        ) from None


def coerce_event_type(value: EventType | str) -> EventType:
    try:
        return EventType(value)
    except ValueError:
        raise UnknownEventType(
            f"{value!r} is not an event type. The set is closed; adding one means adding "
            f"a member to EventType and migrating the audit_event_type database type."
        ) from None

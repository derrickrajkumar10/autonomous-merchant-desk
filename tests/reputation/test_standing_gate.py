"""The standing gate, on requests that really cleared checks 1 to 4.

Every request here is built and signed the way a buyer agent's would be and sent
through ``TrustSpine.receive``; the gate then reads the passed ``SpineOutcome``. The
ladder is moved with a controlled clock so an agent can be stood on a known rung before
the gate is asked about it.
"""

from __future__ import annotations

import pytest

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.identity import AgentIdentity
from desk.reputation import ReputationLadder, StandingGate
from desk.spine import TrustSpine
from tests.reputation.conftest import START, authorised, day
from tests.spine.conftest import a_request, checks_recorded
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def _climb_to_regular(ladder: ReputationLadder, agent_id: str) -> None:
    """Six clean deals same-day, then one two days on -- lands the agent on rung 1."""
    for _ in range(6):
        ladder.record_clean_deal(agent_id, now=START)
    ladder.record_clean_deal(agent_id, now=day(2))
    assert ladder.standing(agent_id, now=day(2)).rung.name == "regular"


def test_a_disproportionate_deal_after_small_clean_ones_is_stopped_by_the_rung_ceiling(
    spine: TrustSpine,
    gate: StandingGate,
    ladder: ReputationLadder,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Trust farming, refused: the mandate permits it, the rung does not (FR-4.5)."""
    _climb_to_regular(ladder, identity.agent_id)

    grab = authorised(spine, wallet, agent, identity, amount="50000.00")
    outcome = gate.admit(grab, now=day(2))

    assert outcome.refused
    assert outcome.reason_code is ReasonCode.CEILING_EXCEEDED_FOR_TIER
    assert outcome.standing.rung.name == "regular"

    entry = trail.query(event_type=EventType.STANDING_GATE_REFUSED)[-1]
    assert entry.reason_code is ReasonCode.CEILING_EXCEEDED_FOR_TIER
    assert entry.payload["evidence"]["rung_ceiling"] == "15000.00 INR"
    assert entry.payload["evidence"]["requested_amount"] == "50000.00 INR"
    assert entry.payload["state_change"] == {"request": "refused"}


def test_a_request_within_the_rung_ceiling_is_admitted_and_recorded(
    spine: TrustSpine,
    gate: StandingGate,
    ladder: ReputationLadder,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    _climb_to_regular(ladder, identity.agent_id)

    ok = authorised(spine, wallet, agent, identity, amount="750.00")
    outcome = gate.admit(ok, now=day(2))

    assert outcome.passed
    assert outcome.reason_code is None
    entry = trail.query(event_type=EventType.STANDING_GATE_PASSED)[-1]
    assert entry.payload["evidence"]["requested_amount"] == "750.00 INR"
    assert entry.payload["evidence"]["scrutiny"] == "standard"


def test_a_new_agent_is_held_to_the_lowest_rung_ceiling(
    spine: TrustSpine,
    gate: StandingGate,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """No clean history, so the mandate's generous ceiling counts for nothing here."""
    over = authorised(spine, wallet, agent, identity, amount="5000.00")
    outcome = gate.admit(over, now=START)

    assert outcome.refused
    assert outcome.reason_code is ReasonCode.CEILING_EXCEEDED_FOR_TIER
    assert outcome.standing.rung.name == "newcomer"
    assert outcome.standing.ceiling.amount == pytest.approx(2000)


def test_a_blocked_agent_is_refused_here_however_valid_the_request(
    spine: TrustSpine,
    gate: StandingGate,
    ladder: ReputationLadder,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    for _ in range(ladder.policy.block_after_signals):
        ladder.record_check5_signal(
            identity.agent_id, reason_code=ReasonCode.PROMPT_INJECTION_DETECTED, now=START
        )

    tiny = authorised(spine, wallet, agent, identity, amount="100.00")
    outcome = gate.admit(tiny, now=START)

    assert outcome.refused
    assert outcome.reason_code is ReasonCode.AGENT_BLOCKED
    assert trail.query(event_type=EventType.STANDING_GATE_REFUSED)[-1].reason_code is (
        ReasonCode.AGENT_BLOCKED
    )


def test_no_rung_however_high_causes_a_deterministic_check_to_be_skipped(
    spine: TrustSpine,
    gate: StandingGate,
    ladder: ReputationLadder,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    agent_id = identity.agent_id
    for _ in range(12):
        ladder.record_clean_deal(agent_id, now=START)
    ladder.record_clean_deal(agent_id, now=day(1.1))  # -> rung 1
    ladder.record_clean_deal(agent_id, now=day(4.2))  # -> rung 2
    assert ladder.standing(agent_id, now=day(4.2)).rung.name == "established"

    ok = authorised(spine, wallet, agent, identity, amount="750.00")

    # Every deterministic check still ran and left its entry, exactly as for a newcomer.
    assert set(checks_recorded(trail)) == {1, 2, 3, 4}
    assert gate.admit(ok, now=day(4.2)).passed


def test_the_gate_will_not_run_on_a_request_the_spine_refused(
    spine: TrustSpine,
    gate: StandingGate,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    refused = spine.receive(a_request(wallet, agent, identity, item_id="SKU-NOT-YOURS"))
    assert not refused.passed

    with pytest.raises(ValueError, match="passed checks 1 to 4"):
        gate.admit(refused, now=START)

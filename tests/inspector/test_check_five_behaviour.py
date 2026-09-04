"""The behavioural half of check 5, wired through the real front door.

Every test builds a history by sending real signed requests through
``TrustSpine.receive`` -- so the trail these read back is the one a running Desk would
have -- and then calls ``BehaviourCheck.assess`` on the latest passed outcome.
"""

from __future__ import annotations

import dataclasses

import pytest

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.identity import AgentIdentity
from desk.inspector import BehaviourCheck, BehaviourOutcome, ScrutinyTier
from desk.spine import TrustSpine
from tests.inspector.conftest import authorised, check_five_entries
from tests.spine.conftest import a_request
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

STEADY = ("320.00", "350.00", "300.00", "360.00", "330.00", "340.00")


def _history(
    spine: TrustSpine,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
    amounts: tuple[str, ...],
) -> None:
    for amount in amounts:
        authorised(spine, wallet, agent, identity, amount=amount)


def test_a_disproportionate_request_after_a_calm_history_is_refused(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    _history(spine, wallet, agent, identity, STEADY)
    grab = authorised(spine, wallet, agent, identity, amount="1900.00")

    outcome = BehaviourCheck(trail).assess(grab, scrutiny=ScrutinyTier.STANDARD)

    assert outcome.refused
    assert not outcome.passed
    assert outcome.reason_code is ReasonCode.ESCALATION_PATTERN_DETECTED
    assert outcome.score >= BehaviourCheck(trail).policy.refuse_at

    entry = check_five_entries(trail)[-1]
    assert entry.event_type is EventType.CHECK_5_BEHAVIOUR_REFUSED
    assert entry.reason_code is ReasonCode.ESCALATION_PATTERN_DETECTED
    assert entry.payload["evidence"]["amount_over_max"] > 0
    assert entry.payload["state_change"] == {"request": "refused"}


def test_another_ordinary_request_passes_and_is_recorded(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    _history(spine, wallet, agent, identity, STEADY)
    ordinary = authorised(spine, wallet, agent, identity, amount="345.00")

    outcome = BehaviourCheck(trail).assess(ordinary, scrutiny=ScrutinyTier.STANDARD)

    assert outcome.passed
    assert outcome.reason_code is None
    entry = check_five_entries(trail)[-1]
    assert entry.event_type is EventType.CHECK_5_BEHAVIOUR_PASSED
    assert entry.reason_code is None
    assert entry.payload["evidence"]["score"] < entry.payload["evidence"]["threshold"]


def test_a_new_agent_with_no_baseline_is_not_scored(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A second-ever request cannot be an escalation off a sample of one."""
    authorised(spine, wallet, agent, identity, amount="300.00")
    second = authorised(spine, wallet, agent, identity, amount="1900.00")

    outcome = BehaviourCheck(trail).assess(second, scrutiny=ScrutinyTier.CLOSE)

    assert outcome.passed
    assert outcome.score == 0.0
    assert outcome.signals.sample_size < BehaviourCheck(trail).policy.baseline_min
    assert "too few" in check_five_entries(trail)[-1].payload["reasoning"]


def test_scrutiny_tier_moves_the_bar(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The same drift is caught under close scrutiny and let through under light."""
    _history(spine, wallet, agent, identity, ("400.00",) * 6)
    drift = authorised(spine, wallet, agent, identity, amount="720.00")

    close = BehaviourCheck(trail).assess(drift, scrutiny=ScrutinyTier.CLOSE)
    assert close.refused

    light = BehaviourCheck(trail).assess(drift, scrutiny=ScrutinyTier.LIGHT)
    assert light.passed
    assert light.score == close.score  # same score, different threshold


def test_the_behaviour_half_does_not_run_on_a_refused_request(
    spine: TrustSpine,
    trail: AuditTrail,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    refused = spine.receive(a_request(wallet, agent, identity, item_id="SKU-NOT-YOURS"))
    assert not refused.passed

    with pytest.raises(ValueError, match="passed checks 1"):
        BehaviourCheck(trail).assess(refused, scrutiny=ScrutinyTier.CLOSE)


def test_a_behaviour_outcome_carries_nothing_that_could_grant_anything() -> None:
    """ADR-0005 again: the behavioural half can only withhold."""
    fields = {f.name for f in dataclasses.fields(BehaviourOutcome)}
    assert fields == {"refused", "reason_code", "signals", "entry"}
    assert not fields & {"identity", "remaining", "ceiling", "outcome", "approved", "granted"}


def test_no_attack_labels_anywhere_in_the_module() -> None:
    """The score is unsupervised (ADR-0009). Nothing in it names a known attack."""
    from pathlib import Path

    import desk.inspector.behaviour as module

    source = Path(module.__file__).read_text(encoding="utf-8").lower()
    # 'attack' appears once, in the docstring, only to say labels are NOT used.
    assert source.count("label") <= 2  # the ADR reference in prose
    assert "known_attacks" not in source
    assert "attack_signature" not in source

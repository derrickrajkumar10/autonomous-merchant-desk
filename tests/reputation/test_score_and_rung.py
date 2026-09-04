"""The ladder's arithmetic: score up slowly, down quickly, rungs gated by dwell and time.

These drive ``ReputationLadder`` directly with a controlled clock. The trail is the
assertion surface -- every score and rung change has to appear on it with a cause
(Spec 08 stories 10 and 11) -- so most tests read entries back rather than trusting the
returned ``Standing``.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.inspector import ScrutinyTier
from desk.reputation import AgentIsBlocked, ReputationLadder, Rung
from desk.spend import Money
from tests.reputation.conftest import START, day, reputation_entries

AGENT = "agent-under-test"


def test_a_new_agent_starts_at_the_lowest_rung_under_the_strictest_scrutiny(
    ladder: ReputationLadder,
) -> None:
    standing = ladder.standing(AGENT, now=START)

    assert standing.score == pytest.approx(0.10)
    assert standing.rung.index == 0
    assert standing.rung.name == "newcomer"
    assert standing.scrutiny is ScrutinyTier.CLOSE
    assert standing.ceiling.amount == pytest.approx(2000)
    assert not standing.blocked


def test_a_clean_deal_raises_the_score_and_the_trail_says_why(
    ladder: ReputationLadder, trail: AuditTrail
) -> None:
    ladder.record_clean_deal(AGENT, now=START)

    standing = ladder.standing(AGENT, now=START)
    assert standing.score == pytest.approx(0.14)

    changed = trail.query(event_type=EventType.TRUST_SCORE_CHANGED)
    assert len(changed) == 1
    assert changed[0].payload["evidence"]["cause"] == "clean_deal"
    assert changed[0].payload["evidence"]["increment"] == pytest.approx(0.04)
    assert changed[0].payload["state_change"] == {"trust_score": "0.1 -> 0.14"}


def test_a_check_5_signal_lowers_the_score_by_more_than_a_clean_deal_raises_it(
    ladder: ReputationLadder, trail: AuditTrail
) -> None:
    for _ in range(5):  # up to 0.30
        ladder.record_clean_deal(AGENT, now=START)
    ladder.record_clean_deal(AGENT, now=START)  # one more clean deal: +0.04
    after_deal = ladder.standing(AGENT, now=START).score

    ladder.record_check5_signal(
        AGENT, reason_code=ReasonCode.ESCALATION_PATTERN_DETECTED, now=START
    )
    after_signal = ladder.standing(AGENT, now=START).score

    rise = ladder.policy.clean_deal_rise
    fall = after_deal - after_signal
    assert fall > rise
    assert fall == pytest.approx(ladder.policy.signal_fall)

    signal_entry = trail.query(event_type=EventType.TRUST_SCORE_CHANGED)[-1]
    assert signal_entry.payload["evidence"]["cause"] == "check_5_signal"
    assert signal_entry.payload["evidence"]["signal"] == "escalation_pattern_detected"


def test_dwell_time_holds_an_agent_on_a_rung_even_once_its_score_qualifies(
    ladder: ReputationLadder,
) -> None:
    for _ in range(5):  # score reaches 0.30, which is rung 1's threshold
        ladder.record_clean_deal(AGENT, now=START)

    held = ladder.standing(AGENT, now=START)
    assert held.score == pytest.approx(0.30)
    assert held.rung.index == 0, "score qualifies for rung 1 but the 1-day dwell is not served"

    climbed = ladder.record_clean_deal(AGENT, now=day(1.5))
    assert climbed.rung.index == 1
    assert climbed.rung.name == "regular"


def test_a_climb_is_one_rung_per_deal_however_far_the_score_has_run_ahead(
    ladder: ReputationLadder,
) -> None:
    for _ in range(12):  # score 0.58 -- past rung 2's threshold of 0.55
        ladder.record_clean_deal(AGENT, now=START)

    assert ladder.standing(AGENT, now=START).rung.index == 0
    assert ladder.record_clean_deal(AGENT, now=day(1.1)).rung.index == 1
    assert ladder.record_clean_deal(AGENT, now=day(1.2)).rung.index == 1, "rung 1 dwell is 3 days"
    assert ladder.record_clean_deal(AGENT, now=day(4.2)).rung.index == 2


def test_rung_changes_are_written_to_the_trail_with_a_cause(
    ladder: ReputationLadder, trail: AuditTrail
) -> None:
    for _ in range(5):
        ladder.record_clean_deal(AGENT, now=START)
    ladder.record_clean_deal(AGENT, now=day(1.5))

    rung_changes = trail.query(event_type=EventType.RUNG_CHANGED)
    assert len(rung_changes) == 1
    assert rung_changes[0].payload["evidence"]["cause"] == "dwell_served_and_score_met"
    assert rung_changes[0].payload["state_change"] == {"rung": "newcomer -> regular"}
    assert rung_changes[0].payload["evidence"]["ceiling_after"] == "15000.00 INR"


def test_inactivity_decays_the_score_toward_baseline(
    ladder: ReputationLadder, trail: AuditTrail
) -> None:
    for _ in range(10):  # score 0.50
        ladder.record_clean_deal(AGENT, now=START)
    assert ladder.standing(AGENT, now=START).score == pytest.approx(0.50)

    # 0.50, minus 0.01/day for 30 days, is 0.20 -- still above baseline.
    faded = ladder.standing(AGENT, now=day(30))
    assert faded.score == pytest.approx(0.20)

    # And far enough out it stops at baseline and goes no lower.
    floored = ladder.standing(AGENT, now=day(400))
    assert floored.score == pytest.approx(ladder.policy.baseline)

    decay = [
        entry
        for entry in trail.query(event_type=EventType.TRUST_SCORE_CHANGED)
        if entry.payload["evidence"]["cause"] == "inactivity_decay"
    ]
    assert decay, "a decay has to be recorded, not applied silently"
    assert decay[0].payload["evidence"]["increment"] < 0


def test_decay_never_raises_a_score_and_never_a_rung(ladder: ReputationLadder) -> None:
    # A fresh agent sits at baseline; time alone does nothing to it.
    assert ladder.standing("dormant-newcomer", now=day(1000)).score == pytest.approx(0.10)
    assert ladder.standing("dormant-newcomer", now=day(2000)).rung.index == 0

    # An agent that climbed drops back down as its score decays -- never the other way.
    for _ in range(12):
        ladder.record_clean_deal(AGENT, now=START)
    ladder.record_clean_deal(AGENT, now=day(1.1))  # -> rung 1
    ladder.record_clean_deal(AGENT, now=day(4.2))  # -> rung 2
    assert ladder.standing(AGENT, now=day(4.2)).rung.index == 2

    dropped = ladder.standing(AGENT, now=day(400))
    assert dropped.score == pytest.approx(0.10)
    assert dropped.rung.index == 0


def test_enough_bad_behaviour_blocks_the_agent(
    ladder: ReputationLadder, trail: AuditTrail
) -> None:
    for _ in range(ladder.policy.block_after_signals):
        ladder.record_check5_signal(
            AGENT, reason_code=ReasonCode.PROMPT_INJECTION_DETECTED, now=START
        )

    standing = ladder.standing(AGENT, now=START)
    assert standing.blocked

    blocked = trail.query(event_type=EventType.AGENT_BLOCKED)
    assert len(blocked) == 1
    assert blocked[0].reason_code is ReasonCode.AGENT_BLOCKED
    assert blocked[0].payload["evidence"]["signal_count"] == ladder.policy.block_after_signals
    assert blocked[0].payload["state_change"] == {"agent": "blocked"}


def test_a_blocked_agent_stays_blocked_and_a_clean_deal_for_it_is_a_contradiction(
    ladder: ReputationLadder,
) -> None:
    for _ in range(ladder.policy.block_after_signals):
        ladder.record_check5_signal(
            AGENT, reason_code=ReasonCode.PROMPT_INJECTION_DETECTED, now=START
        )

    # Another signal is absorbed -- there is nothing left to do to a blocked agent.
    ladder.record_check5_signal(
        AGENT, reason_code=ReasonCode.PROMPT_INJECTION_DETECTED, now=day(10)
    )
    assert ladder.standing(AGENT, now=day(10)).blocked

    # A clean deal, though, means something upstream transacted with it: loud, not quiet.
    with pytest.raises(AgentIsBlocked):
        ladder.record_clean_deal(AGENT, now=day(11))


def test_every_score_and_rung_change_is_reconstructable_from_the_trail_alone(
    ladder: ReputationLadder, trail: AuditTrail
) -> None:
    """The sequence of causes tells the whole story of the agent's standing."""
    for _ in range(6):
        ladder.record_clean_deal(AGENT, now=START)
    ladder.record_clean_deal(AGENT, now=day(2))  # climbs to rung 1
    ladder.record_check5_signal(
        AGENT, reason_code=ReasonCode.ESCALATION_PATTERN_DETECTED, now=day(2)
    )  # score falls back under rung 1's threshold -> drops to rung 0

    # Decay entries interleave whenever there is a gap between deals; they have their
    # own test. What this asserts is that the deliberate movers appear in order.
    kinds = [
        (str(e.event_type), e.payload["evidence"]["cause"])
        for e in reputation_entries(trail)
        if e.payload["evidence"]["cause"] != "inactivity_decay"
    ]
    assert kinds == [
        ("trust_score_changed", "clean_deal"),
        ("trust_score_changed", "clean_deal"),
        ("trust_score_changed", "clean_deal"),
        ("trust_score_changed", "clean_deal"),
        ("trust_score_changed", "clean_deal"),
        ("trust_score_changed", "clean_deal"),
        ("trust_score_changed", "clean_deal"),
        ("rung_changed", "dwell_served_and_score_met"),
        ("trust_score_changed", "check_5_signal"),
        ("rung_changed", "score_fell"),
    ]


def test_an_injected_ladder_is_the_one_rung_drops_are_settled_against(
    pool: ConnectionPool, trail: AuditTrail
) -> None:
    """A custom ladder governs a drop the same way it governs a climb.

    Two rungs, both reachable well before the default ladder's own thresholds: rung 1
    is available at a score of 0.05, far below the default ladder's 0.30. An agent that
    climbs onto this custom rung 1 and is then merely re-settled, with no signal and no
    time passed, must stay there -- and would wrongly be dropped back to rung 0 if a
    drop were ever settled against the *default* ladder instead of the one this
    ``ReputationLadder`` was built with.
    """
    custom: tuple[Rung, ...] = (
        Rung(0, "low", Money.of("100.00", "INR"), ScrutinyTier.CLOSE, 0.0, timedelta(0)),
        Rung(1, "high", Money.of("999.00", "INR"), ScrutinyTier.LIGHT, 0.05, timedelta(0)),
    )
    ladder = ReputationLadder(pool, trail, ladder=custom)

    climbed = ladder.record_clean_deal(AGENT, now=START)  # score 0.14, past 0.05, no dwell
    assert climbed.rung.index == 1

    settled = ladder.standing(AGENT, now=START)  # no signal, no time passed: nothing should move
    assert settled.rung.index == 1
    assert settled.rung.name == "high"

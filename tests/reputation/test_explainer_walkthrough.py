"""One agent's life on the ladder, printed and asserted, so the explainer cannot drift.

This is the table in `docs/explainers/ticket-12-reputation-ladder.md` section 6. It is
produced here rather than typed there, so a change to a rung ceiling or the dwell rule
fails this test and the explainer is updated in the same commit.
"""

from __future__ import annotations

from desk.audit import ReasonCode
from desk.identity import AgentIdentity
from desk.reputation import ReputationLadder, StandingGate
from desk.spine import TrustSpine
from tests.reputation.conftest import START, authorised, day
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

EXPECTED = """
One agent on the ladder (default policy):
  registers                       score 0.10  rung 0 newcomer     ceiling 2000.00 INR
  6 clean deals, one day          score 0.34  rung 0 newcomer     held by the 1-day dwell
  1 clean deal, two days on       score 0.36  rung 1 regular      ceiling 15000.00 INR
  offers 50,000 for one deal      refused: ceiling_exceeded_for_tier
  3 check-5 signals               blocked
  offers 100 the next day         refused: agent_blocked
""".strip()


def test_the_walkthrough_in_the_explainer_is_true(
    spine: TrustSpine,
    gate: StandingGate,
    ladder: ReputationLadder,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    agent_id = identity.agent_id
    lines = ["One agent on the ladder (default policy):"]

    s = ladder.standing(agent_id, now=START)
    lines.append(f"  {'registers':<30}  score {s.score:.2f}  rung {s.rung.index} "
                 f"{s.rung.name:<12} ceiling {s.ceiling}")

    for _ in range(6):
        ladder.record_clean_deal(agent_id, now=START)
    s = ladder.standing(agent_id, now=START)
    lines.append(f"  {'6 clean deals, one day':<30}  score {s.score:.2f}  rung {s.rung.index} "
                 f"{s.rung.name:<12} held by the 1-day dwell")

    s = ladder.record_clean_deal(agent_id, now=day(2))
    lines.append(f"  {'1 clean deal, two days on':<30}  score {s.score:.2f}  rung {s.rung.index} "
                 f"{s.rung.name:<12} ceiling {s.ceiling}")

    grab = authorised(spine, wallet, agent, identity, amount="50000.00")
    refused = gate.admit(grab, now=day(2))
    assert refused.reason_code is not None
    lines.append(f"  {'offers 50,000 for one deal':<30}  refused: {refused.reason_code.value}")

    for _ in range(3):
        ladder.record_check5_signal(
            agent_id, reason_code=ReasonCode.ESCALATION_PATTERN_DETECTED, now=day(2)
        )
    lines.append(f"  {'3 check-5 signals':<30}  blocked")

    tiny = authorised(spine, wallet, agent, identity, amount="100.00")
    blocked = gate.admit(tiny, now=day(3))
    assert blocked.reason_code is not None
    lines.append(f"  {'offers 100 the next day':<30}  refused: {blocked.reason_code.value}")

    print("\n" + "\n".join(lines))
    assert "\n".join(lines) == EXPECTED

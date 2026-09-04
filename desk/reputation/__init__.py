"""The reputation ladder -- what an agent's record buys it, and why volume cannot rush it.

Every agent got identical treatment before this. One that had closed fifty clean deals
was scrutinised as hard as one that registered a minute ago, and -- worse -- was
extended exactly as much spending room. That wastes attention on known-good parties and
hands full authority to unknown ones.

The obvious fix, letting good behaviour raise limits, is the attack it is meant to
prevent. An agent that understands the rule builds a clean record with small deals and
then reaches for one disproportionate purchase at the moment its limit is highest.
**Trust farming** is the rational strategy against a naive reputation system, and the
red team will play it.

So each agent carries a trust score in ``[0, 1]``, starting at ``0.1``, that gates two
things:

- a **spend ceiling**, expressed as a discrete **ladder** of rungs rather than a
  continuous function of the score. Each rung carries a **minimum dwell time**, and the
  dwell time is the anti-farming mechanism: an agent cannot buy its way up quickly
  because time on a rung is a cost volume cannot pay.
- a **scrutiny tier**, one of three, consumed by check 5.

Trust rises slowly and falls quickly -- a clean deal adds a small increment, a check-5
signal subtracts several times that, and enough signals block the agent. A score above
baseline decays back toward it during inactivity, so a dormant high-trust identity is
not a standing liability; decay never raises a score.

This is what makes the five checks a **cycle rather than a pipeline** (FR-4.6):
behaviour feeds reputation, and reputation gates authority.

- ``policy`` -- every tuned number in one replaceable object. The asymmetry (a signal
  costs more than a deal earns) is asserted, not merely configured.
- ``ladder`` -- the rungs: a ceiling, a scrutiny tier, a score threshold and a dwell
  time each, plus the decay and rung arithmetic as pure functions.
- ``schema`` -- one row per agent, with the score bound and the no-unblock rule held by
  the database.
- ``store`` -- ``ReputationLadder``: ``standing``, ``record_clean_deal``,
  ``record_check5_signal``. Every score and rung change is written to the trail with its
  cause, in the same transaction as the change.
- ``gate`` -- ``StandingGate``: the one refusal, ``ceiling_exceeded_for_tier`` (and
  ``agent_blocked``), run after the spine and skipping nothing.

    from desk.reputation import ReputationLadder, StandingGate, install_schema

    with pool.connection() as conn:
        install_schema(conn)

    ladder = ReputationLadder(pool, trail)
    admitted = StandingGate(ladder, trail).admit(spine_outcome)
    if admitted.passed:
        ...                                   # negotiate under admitted.standing.ceiling
        ladder.record_clean_deal(agent_id)    # a clean close feeds back in

    # and check 5's refusals feed back the other way:
    ladder.record_check5_signal(agent_id, reason_code=behaviour.reason_code)

**What is not here.** Computing check-5 signals (consumed here, produced in
``desk.inspector``). Manual overrides or an admin interface for scores. Cross-agent
reputation or shared blocklists. Unblocking a blocked agent. And the request pipeline
that chains spine -> gate -> check 5 -> negotiation -> settlement -> ``record_clean_deal``
is assembled by the batch runner and the control-room fork; this ticket delivers the
ladder, the gate and their seam.
"""

from desk.reputation.gate import GateOutcome, StandingGate
from desk.reputation.ladder import (
    LADDER,
    LADDER_CURRENCY,
    LOWEST_RUNG,
    Rung,
    decayed,
    highest_available,
    rung,
)
from desk.reputation.policy import ReputationPolicy
from desk.reputation.schema import TABLE, install_schema
from desk.reputation.store import AgentIsBlocked, ReputationLadder, Standing

__all__ = [
    "LADDER",
    "LADDER_CURRENCY",
    "LOWEST_RUNG",
    "TABLE",
    "AgentIsBlocked",
    "GateOutcome",
    "ReputationLadder",
    "ReputationPolicy",
    "Rung",
    "Standing",
    "StandingGate",
    "decayed",
    "highest_available",
    "install_schema",
    "rung",
]

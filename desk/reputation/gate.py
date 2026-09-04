"""The standing gate: reputation's one refusal, sitting after the spine and before terms.

The four deterministic checks proved a request is authentic, authorised, affordable and
fresh. Check 3 among them proved the amount is inside the ceiling *the principal's
mandate* set. None of that reads the ceiling *the Desk* extends to an agent by its rung,
and that is what this does: one comparison, ``amount`` against the rung ceiling, and one
refusal, ``ceiling_exceeded_for_tier``.

**This is where trust farming is stopped.** An agent that has run up a clean record with
small deals and then reaches for a disproportionate one has a mandate that permits it
(the human set a generous budget) and a check-5 behavioural score that may or may not
have caught the shape -- but its rung ceiling has not moved, because rungs move on
elapsed time and this agent has not spent the time. The grab lands here.

**A blocked agent is refused here too**, under ``agent_blocked``, before any negotiation
opens. Blocking is the reputation ladder's (``store.py``); acting on it is this.

**It skips nothing.** The gate runs *after* all four deterministic checks, every time,
whatever the agent's rung. A high rung buys a larger ceiling and lighter check-5
scrutiny; it never buys a check that does not run. This is the same inversion the trust
spine warns about, seen from the reputation side (CONTEXT.md section 10).

    from desk.reputation import ReputationLadder, StandingGate

    gate = StandingGate(ReputationLadder(pool, trail), trail)
    admitted = gate.admit(spine_outcome)
    if not admitted.passed:
        ...        # ceiling_exceeded_for_tier, or agent_blocked

    # a deal that then closes cleanly feeds back into the ladder:
    ladder.record_clean_deal(spine_outcome.identity.agent_id)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.reputation.store import ReputationLadder, Standing
from desk.spend import Money
from desk.spine import SpineOutcome


@dataclass(frozen=True)
class GateOutcome:
    """What the standing gate concluded, and the entry it wrote concluding it.

    ``standing`` is the agent's standing as the gate saw it -- the score, the rung, the
    ceiling that was compared against. Present on a pass and a refusal both, because the
    control room shows an agent's standing either way.
    """

    refused: bool
    reason_code: ReasonCode | None
    standing: Standing
    entry: AuditEntry

    @property
    def passed(self) -> bool:
        return not self.refused


class StandingGate:
    """Refuse a request that a passed agent's rung does not have room for."""

    def __init__(self, ladder: ReputationLadder, trail: AuditTrail) -> None:
        self._ladder = ladder
        self._trail = trail

    def admit(self, outcome: SpineOutcome, *, now: datetime | None = None) -> GateOutcome:
        """The standing gate on a request that cleared checks 1 to 4.

        ``outcome`` is the spine's own output. One that did not pass has been answered
        already, and one with no identity or no readable amount never reached the point
        this gate runs at, so either raises rather than being refused a second time.
        """
        if not outcome.passed or outcome.identity is None or outcome.request is None:
            raise ValueError(
                "the standing gate runs on a request that passed checks 1 to 4; a "
                "refused one has been answered already"
            )
        amount = outcome.request.amount
        if amount is None:  # pragma: no cover - the spine refuses a priceless request at check 3
            raise ValueError("the standing gate compares an amount, and this request states none")

        agent_id = outcome.identity.agent_id
        standing = self._ladder.standing(agent_id, now=now)

        if standing.blocked:
            return self._refuse(
                standing,
                ReasonCode.AGENT_BLOCKED,
                reasoning=(
                    "this agent is blocked; the Desk does not transact with it, and a "
                    "request that passed every earlier check is refused here regardless"
                ),
                evidence={"signal_count": standing.signal_count},
                amount=amount,
            )

        ceiling = standing.ceiling
        if amount.currency != ceiling.currency:
            return self._refuse(
                standing,
                ReasonCode.CEILING_EXCEEDED_FOR_TIER,
                reasoning=(
                    f"the rung ceiling is written in {ceiling.currency} and this request "
                    f"is in {amount.currency}; the Desk holds no exchange rate and will "
                    f"not compare one against the other"
                ),
                evidence={"rung_ceiling": str(ceiling)},
                amount=amount,
            )
        if amount > ceiling:
            return self._refuse(
                standing,
                ReasonCode.CEILING_EXCEEDED_FOR_TIER,
                reasoning=(
                    f"{amount} is past the {ceiling} ceiling of {standing.rung}; the "
                    f"agent's rung rises on elapsed time, not on volume, so a "
                    f"disproportionate deal after a run of small clean ones lands here"
                ),
                evidence={"rung_ceiling": str(ceiling)},
                amount=amount,
            )

        entry = self._trail.record(
            actor="desk",
            event_type=EventType.STANDING_GATE_PASSED,
            subject_id=agent_id,
            payload={
                "reasoning": (
                    f"{amount} is within the {ceiling} ceiling of {standing.rung}, and "
                    f"the agent is not blocked"
                ),
                "evidence": _standing_evidence(standing) | {"requested_amount": str(amount)},
                "state_change": {"request": "within the rung ceiling"},
            },
        )
        return GateOutcome(refused=False, reason_code=None, standing=standing, entry=entry)

    def _refuse(
        self,
        standing: Standing,
        reason: ReasonCode,
        *,
        reasoning: str,
        evidence: dict[str, Any],
        amount: Money,
    ) -> GateOutcome:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.STANDING_GATE_REFUSED,
            subject_id=standing.agent_id,
            reason_code=reason,
            payload={
                "reasoning": reasoning,
                "evidence": _standing_evidence(standing)
                | {"requested_amount": str(amount)}
                | evidence,
                "state_change": {"request": "refused"},
            },
        )
        return GateOutcome(refused=True, reason_code=reason, standing=standing, entry=entry)


def _standing_evidence(standing: Standing) -> dict[str, Any]:
    return {
        "trust_score": round(standing.score, 4),
        "rung": str(standing.rung),
        "rung_ceiling": str(standing.ceiling),
        "scrutiny": standing.scrutiny.value,
        "blocked": standing.blocked,
    }

"""The ladder's state: one agent's score and rung, and the four things that move them.

Everything here is bookkeeping around two numbers -- a score and a rung index -- and the
rule that they move slowly up and quickly down. The four movers:

- **a clean deal** raises the score a little, and may earn a climb of one rung if the
  score now reaches the next threshold *and* the agent has dwelt long enough on the one
  it is on. One rung per deal, never two, however far the score has run ahead.
- **a check-5 signal** lowers the score by several times what a clean deal raises it,
  drops the rung immediately if the score no longer reaches its threshold, and -- once
  enough signals have accumulated -- blocks the agent for good.
- **inactivity** lets a score above baseline drift back down toward it. This is applied
  lazily: the next time anything asks about the agent, the gap since the score was last
  written is turned into decay, recorded, and the score is brought down. A dormant agent
  costs nothing to hold because nothing holds it.
- **being asked about** (``standing``) settles any pending decay first, so a reader
  never sees a stale high score that a write would immediately have corrected.

Every score change and every rung change is written to the trail with its cause
(FR-4.6, Spec 08 user stories 10 and 11), in the same transaction as the state change,
so an agent's standing at any past moment can be reconstructed from the trail alone.

**Nothing here grants anything.** It is consulted by the standing gate, which refuses;
it is fed by check 5, which refuses; it never sits in the path of a deterministic check
and never shortens one. Reputation decides how much an agent may do, never whether the
checks run (CONTEXT.md section 10).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail, EventType, ReasonCode
from desk.inspector.scrutiny import ScrutinyTier
from desk.reputation.ladder import LADDER, Rung, decayed, highest_available
from desk.reputation.ladder import rung as rung_at
from desk.reputation.policy import ReputationPolicy
from desk.reputation.schema import TABLE
from desk.spend import Money

_COLUMNS = (
    "agent_id, score, scored_at, rung, rung_since, last_active_at, "
    "signal_count, blocked, created_at"
)

#: Score changes smaller than this are treated as no change -- no trail entry, no write.
#: A clean deal recorded against an agent already at the ceiling score, or a signal
#: against one already at the floor, moves nothing and should say nothing.
_NEGLIGIBLE = 1e-9

#: The least decay worth writing an entry for. Decay is continuous, so realising it on
#: every read would fill the trail with sub-rupee drops between two deals an hour apart.
#: Below this it is left to accumulate against the same ``scored_at`` and realised in
#: one entry once it crosses the line -- roughly every twelve hours of true inactivity
#: at the default rate. An agent doing regular business never triggers it, because each
#: deal's own score write moves ``scored_at`` forward.
_DECAY_FLOOR = 0.005


class AgentIsBlocked(RuntimeError):
    """A clean deal was recorded for an agent the Desk has already blocked.

    Not a refusal -- refusals are the standing gate's and carry a reason code. Reaching
    this means something upstream opened a negotiation with a blocked agent and closed
    it, which the gate exists to prevent before a negotiation ever starts. Raised so the
    contradiction is loud rather than folded into a score bump nobody should receive.
    """


@dataclass(frozen=True)
class Standing:
    """An agent's standing as the Desk would act on it right now.

    Carries a ceiling and a scrutiny tier because acting on those is the whole point of
    this subsystem -- unlike a check-5 outcome, which must carry nothing grantable. The
    gate reads ``ceiling`` and ``blocked``; check 5 reads ``scrutiny``.
    """

    agent_id: str
    score: float
    rung: Rung
    blocked: bool
    signal_count: int
    on_rung_since: datetime
    last_active_at: datetime

    @property
    def ceiling(self) -> Money:
        """The most one deal may be worth for this agent, set by its rung."""
        return self.rung.ceiling

    @property
    def scrutiny(self) -> ScrutinyTier:
        """How hard check 5 looks at this agent, set by its rung."""
        return self.rung.scrutiny


@dataclass(frozen=True)
class _State:
    """The stored row, as Python. ``score`` is a float here and ``numeric`` in the table."""

    agent_id: str
    score: float
    scored_at: datetime
    rung: int
    rung_since: datetime
    last_active_at: datetime
    signal_count: int
    blocked: bool
    created_at: datetime


def _clock(now: datetime | None) -> datetime:
    """Now, or the instant a caller supplied so a test does not have to wait for one."""
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("the reputation ladder needs a timezone-aware instant")
    return now


def _q(score: float) -> Decimal:
    """A score as the ``numeric`` column should hold it: six places, no float tail."""
    return Decimal(str(round(score, 6)))


class ReputationLadder:
    """Each agent's trust score and rung, moved by clean deals, check-5 signals and time.

    Install the schema once with ``install_schema``; this class does not migrate. Every
    method takes an optional ``now`` so dwell time and decay are testable without a
    clock that actually advances.
    """

    def __init__(
        self,
        pool: ConnectionPool,
        trail: AuditTrail,
        policy: ReputationPolicy | None = None,
        ladder: tuple[Rung, ...] = LADDER,
    ) -> None:
        self._pool = pool
        self._trail = trail
        self._policy = ReputationPolicy.default() if policy is None else policy
        self._ladder = ladder

    @property
    def policy(self) -> ReputationPolicy:
        return self._policy

    # -- the three things a caller does ------------------------------------------------

    def standing(self, agent_id: str, *, now: datetime | None = None) -> Standing:
        """This agent's standing, with any pending inactivity decay settled first.

        A read that writes: an agent whose score has decayed since it was last touched
        has that decay recorded and applied here, so the ceiling the gate enforces a
        moment later is the real one and not one a write would immediately have lowered.
        """
        at = _clock(now)
        with self._pool.connection() as conn:
            state = self._settle(conn, agent_id, at)
        return self._standing(state)

    def record_clean_deal(self, agent_id: str, *, now: datetime | None = None) -> Standing:
        """A clean completed deal. Raises the score, and may earn one rung (FR-4.3).

        The climb is gated twice: the score has to reach the next rung's threshold, and
        the agent has to have sat on its current rung for that rung's dwell time. Either
        one short and the agent stays put -- the score is still recorded, so the climb
        happens on a later deal once the dwell is served.
        """
        at = _clock(now)
        with self._pool.connection() as conn:
            state = self._settle(conn, agent_id, at)
            if state.blocked:
                raise AgentIsBlocked(
                    f"{agent_id} is blocked; a deal should not have been negotiated with "
                    f"it, and the standing gate is what stops that before it happens"
                )
            raised = min(self._policy.maximum_score, state.score + self._policy.clean_deal_rise)
            state = self._change_score(
                conn,
                state,
                raised,
                at,
                cause="clean_deal",
                reasoning="a clean completed deal; trust rises by a small fixed increment",
                extra_evidence={},
            )
            state = self._touch_active(conn, state, at)
            state = self._maybe_climb(conn, state, at)
        return self._standing(state)

    def record_check5_signal(
        self,
        agent_id: str,
        *,
        reason_code: ReasonCode,
        source_seq: int | None = None,
        now: datetime | None = None,
    ) -> Standing:
        """A signal from check 5. Lowers the score by more than a clean deal raises it.

        ``reason_code`` is the check-5 refusal that produced the signal
        (``prompt_injection_detected`` or ``escalation_pattern_detected``) and
        ``source_seq`` the trail entry it was written on, both recorded as evidence so
        the score change points back at what caused it. A rung whose threshold the
        lowered score no longer reaches is dropped at once -- no dwell on the way down.
        Once ``block_after_signals`` signals have accrued the agent is blocked for good.
        """
        at = _clock(now)
        with self._pool.connection() as conn:
            state = self._settle(conn, agent_id, at)
            if state.blocked:
                return self._standing(state)
            lowered = max(self._policy.minimum_score, state.score - self._policy.signal_fall)
            state = self._change_score(
                conn,
                state,
                lowered,
                at,
                cause="check_5_signal",
                reasoning=(
                    "a check-5 signal; trust is slow to earn and fast to lose, so this "
                    "subtracts several times what a clean deal adds"
                ),
                extra_evidence={
                    "signal": reason_code.value,
                    "source_seq": source_seq,
                },
            )
            state = self._touch_active(conn, state, at)
            state = self._add_signal(conn, state)
            state = self._settle_rung_down(conn, state, at)
            if state.signal_count >= self._policy.block_after_signals and not state.blocked:
                state = self._block(conn, state, at)
        return self._standing(state)

    # -- settling --------------------------------------------------------------------

    def _settle(self, conn: Connection[Any], agent_id: str, now: datetime) -> _State:
        """Lock the agent's row (creating it as a newcomer if absent) and apply decay."""
        state = self._lock_or_create(conn, agent_id, now)
        idle = now - state.scored_at
        faded = decayed(state.score, idle, self._policy)
        if state.score - faded < _DECAY_FLOOR:
            return self._settle_rung_down(conn, state, now)
        state = self._change_score(
            conn,
            state,
            faded,
            now,
            cause="inactivity_decay",
            reasoning=(
                "time has passed with no activity, so the score has drifted back toward "
                "baseline; decay never raises a score"
            ),
            extra_evidence={"idle_days": round(idle.total_seconds() / 86400.0, 2)},
        )
        return self._settle_rung_down(conn, state, now)

    def _settle_rung_down(self, conn: Connection[Any], state: _State, now: datetime) -> _State:
        """Drop the rung to the highest one the current score still reaches, if lower.

        Only ever downward. A score that has run ahead of the agent's rung is held there
        by dwell time, and closing that gap is ``_maybe_climb``'s job on the next deal.
        """
        target = highest_available(state.score, self._ladder)
        if target >= state.rung:
            return state
        return self._change_rung(
            conn,
            state,
            target,
            now,
            cause="score_fell",
            reasoning="the score no longer reaches the threshold of the rung the agent was on",
        )

    def _maybe_climb(self, conn: Connection[Any], state: _State, now: datetime) -> _State:
        """Climb one rung if the score reaches the next threshold and the dwell is served."""
        if state.rung >= len(self._ladder) - 1:
            return state
        here = self._ladder[state.rung]
        nxt = self._ladder[state.rung + 1]
        if state.score + _NEGLIGIBLE < nxt.available_at:
            return state
        if now - state.rung_since < here.dwell:
            return state
        return self._change_rung(
            conn,
            state,
            state.rung + 1,
            now,
            cause="dwell_served_and_score_met",
            reasoning=(
                f"{_days(now - state.rung_since)} on {here}, at or over its dwell of "
                f"{_days(here.dwell)}, and the score reaches {nxt}'s threshold of "
                f"{nxt.available_at:.2f}"
            ),
        )

    # -- primitive writes, each its own trail entry ---------------------------------

    def _change_score(
        self,
        conn: Connection[Any],
        state: _State,
        new_score: float,
        now: datetime,
        *,
        cause: str,
        reasoning: str,
        extra_evidence: dict[str, Any],
    ) -> _State:
        if abs(new_score - state.score) < _NEGLIGIBLE:
            return state
        self._trail.record(
            actor="desk",
            event_type=EventType.TRUST_SCORE_CHANGED,
            subject_id=state.agent_id,
            payload={
                "reasoning": reasoning,
                "evidence": {
                    "cause": cause,
                    "score_before": round(state.score, 4),
                    "score_after": round(new_score, 4),
                    "increment": round(new_score - state.score, 4),
                }
                | extra_evidence,
                "state_change": {
                    "trust_score": f"{round(state.score, 4)} -> {round(new_score, 4)}"
                },
            },
            conn=conn,
        )
        conn.execute(
            f"UPDATE {TABLE} SET score = %s, scored_at = %s WHERE agent_id = %s",
            (_q(new_score), now, state.agent_id),
        )
        return replace(state, score=new_score, scored_at=now)

    def _change_rung(
        self,
        conn: Connection[Any],
        state: _State,
        new_index: int,
        now: datetime,
        *,
        cause: str,
        reasoning: str,
    ) -> _State:
        if new_index == state.rung:
            return state
        before, after = self._ladder[state.rung], self._ladder[new_index]
        self._trail.record(
            actor="desk",
            event_type=EventType.RUNG_CHANGED,
            subject_id=state.agent_id,
            payload={
                "reasoning": reasoning,
                "evidence": {
                    "cause": cause,
                    "from": str(before),
                    "to": str(after),
                    "ceiling_before": str(before.ceiling),
                    "ceiling_after": str(after.ceiling),
                    "scrutiny_after": after.scrutiny.value,
                    "score": round(state.score, 4),
                },
                "state_change": {"rung": f"{before.name} -> {after.name}"},
            },
            conn=conn,
        )
        conn.execute(
            f"UPDATE {TABLE} SET rung = %s, rung_since = %s WHERE agent_id = %s",
            (new_index, now, state.agent_id),
        )
        return replace(state, rung=new_index, rung_since=now)

    def _block(self, conn: Connection[Any], state: _State, now: datetime) -> _State:
        self._trail.record(
            actor="desk",
            event_type=EventType.AGENT_BLOCKED,
            subject_id=state.agent_id,
            reason_code=ReasonCode.AGENT_BLOCKED,
            payload={
                "reasoning": (
                    "enough check-5 signals have accrued against this agent that it is "
                    "no longer worth the Desk's attention; it is blocked, and every "
                    "further request from it is refused"
                ),
                "evidence": {
                    "signal_count": state.signal_count,
                    "block_after_signals": self._policy.block_after_signals,
                    "score": round(state.score, 4),
                },
                "state_change": {"agent": "blocked"},
            },
            conn=conn,
        )
        conn.execute(
            f"UPDATE {TABLE} SET blocked = true WHERE agent_id = %s", (state.agent_id,)
        )
        return replace(state, blocked=True)

    def _touch_active(self, conn: Connection[Any], state: _State, now: datetime) -> _State:
        """Record that the agent just did something. Not a decision, so not a trail entry."""
        conn.execute(
            f"UPDATE {TABLE} SET last_active_at = %s WHERE agent_id = %s",
            (now, state.agent_id),
        )
        return replace(state, last_active_at=now)

    def _add_signal(self, conn: Connection[Any], state: _State) -> _State:
        conn.execute(
            f"UPDATE {TABLE} SET signal_count = signal_count + 1 WHERE agent_id = %s",
            (state.agent_id,),
        )
        return replace(state, signal_count=state.signal_count + 1)

    # -- row access ----------------------------------------------------------------

    def _lock_or_create(self, conn: Connection[Any], agent_id: str, now: datetime) -> _State:
        if not agent_id or not agent_id.strip():
            raise ValueError("an agent id is needed to read or move a reputation")
        conn.execute(
            f"INSERT INTO {TABLE} ({_COLUMNS}) VALUES (%s, %s, %s, 0, %s, %s, 0, false, %s)"
            f" ON CONFLICT (agent_id) DO NOTHING",
            (agent_id, _q(self._policy.start_score), now, now, now, now),
        )
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {TABLE} WHERE agent_id = %s FOR UPDATE", (agent_id,)
        ).fetchone()
        if row is None:  # pragma: no cover - the insert above put it there
            raise RuntimeError(f"{agent_id} was created in {TABLE} and is not there")
        return _to_state(row)

    def _standing(self, state: _State) -> Standing:
        return Standing(
            agent_id=state.agent_id,
            score=state.score,
            rung=rung_at(state.rung, self._ladder),
            blocked=state.blocked,
            signal_count=state.signal_count,
            on_rung_since=state.rung_since,
            last_active_at=state.last_active_at,
        )


def _to_state(row: tuple[Any, ...]) -> _State:
    return _State(
        agent_id=row[0],
        score=float(row[1]),
        scored_at=row[2],
        rung=int(row[3]),
        rung_since=row[4],
        last_active_at=row[5],
        signal_count=int(row[6]),
        blocked=row[7],
        created_at=row[8],
    )


def _days(span: timedelta) -> str:
    return f"{span.total_seconds() / 86400.0:.1f} days"

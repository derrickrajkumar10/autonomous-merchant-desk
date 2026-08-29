"""Check 4 -- replay and freshness. Is this happening now, or did it already happen?

Checks 1 to 3 read a request for what it says, and every one of them gives the same
answer to a perfect copy of a request the Desk honoured an hour ago. The signature
still verifies. The mandate is still signed, still unexpired, still bound to the same
agent. The item is still authorised and the ceiling still has room. Nothing in any of
those three questions is about *time*, so a recording of a valid request is a valid
request, and can be played until the budget is gone.

This check is where that stops, and it takes two layers to stop it because the
authorisation and the handover are two different artefacts with two different clocks:

- The **mandate** carries ``iat`` and ``exp`` -- when the human authorised, and until
  when. Signed once, and true for as long as it says.
- The **key-binding hop** carries ``nonce``, ``aud`` and its own ``iat`` -- who handed
  this over, to whom, and when. Signed by the agent, per presentation.

Neither layer alone closes the hole. A fresh hop over a lapsed mandate is an agent
proving, very recently, that it holds authority it no longer has. A stale hop over a
live mandate is a recording. So check 4 reads both, and the cross-layer question --
whether the hop sits inside the mandate's life at all -- is the one neither layer can
ask of itself.

Six questions, deterministic every one of them (FR-3.1), ordered so the five the Desk
can answer from the presentation in front of it run before the one that reads state:

1. **Is there a hop, and does it verify?** Against the key the mandate endorses,
   over this exact presentation (``sd_hash``), signed as a ``kb+jwt``.
2. **Was it addressed to us?** ``aud``. A proof of possession made for another
   verifier is a real signature by the right key, and still not ours.
3. **Was it made recently?** The hop's ``iat``, inside the configured window.
4. **Was it made after the human authorised?** A proof of possession dated before the
   mandate it presents proves possession of nothing that existed yet.
5. **Was it made while the authorisation was still live?** The hop's ``iat`` against
   the mandate's ``exp``. Distinct from check 2's expiry test, which compares ``exp``
   to *now*: this catches a hop minted after authority had already lapsed.
6. **Has this nonce been spent?** The only question that touches the database, which
   is the whole reason it is last.

**Two reason codes, and every refusal is one of them.** ``nonce_replayed`` is question
6 alone. Everything else leaves under ``request_stale``, which reads as *the Desk could
not establish that this request is current and meant for it* -- an unreadable hop, a
hop for another audience and a hop from last week are one answer on the wire. That
follows check 1, where an unregistered key and a forged signature are both
``agent_signature_invalid``, and the trail is where they are told apart. It is also
what ticket 06 requires: nine reachable refusal reasons across checks 1 to 4, which a
new member here would contradict.

Passing spends the nonce. The presentation cannot be made again even if check 5 goes on
to refuse it, and that is correct -- a retry is a new request and needs a new proof.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from psycopg import Connection

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.freshness.key_binding import KeyBinding, NotFresh, read_key_binding
from desk.freshness.nonces import NonceStore
from desk.freshness.policy import FreshnessPolicy
from desk.identity import AgentIdentity
from desk.mandate import MandateDigest, MandateOutcome, OpenMandate

M = TypeVar("M", bound=OpenMandate)


@dataclass(frozen=True)
class FreshnessOutcome:
    """What check 4 concluded, and the entry it wrote concluding it.

    ``key_binding`` is present only on a pass, and its nonce is spent by the time this
    is returned. On a refusal there is none, because either the hop did not verify or
    it was one the Desk has already honoured -- and in neither case is there a proof of
    possession this request may be credited with.
    """

    key_binding: KeyBinding | None
    reason_code: ReasonCode | None
    entry: AuditEntry

    @property
    def passed(self) -> bool:
        return self.key_binding is not None


class FreshnessCheck:
    """Evaluate one presentation for replay and freshness, against a stated policy."""

    def __init__(
        self, nonces: NonceStore, trail: AuditTrail, policy: FreshnessPolicy | None = None
    ) -> None:
        self._nonces = nonces
        self._trail = trail
        # Read once at construction rather than per request, so that every request in
        # one run is judged under one window. A policy that could change under a
        # sequence of requests would make a refusal impossible to reproduce.
        self._policy = FreshnessPolicy.from_environment() if policy is None else policy

    @property
    def policy(self) -> FreshnessPolicy:
        """The window, skew and audience this check is enforcing."""
        return self._policy

    def evaluate(
        self, mandate: MandateOutcome[M], *, presented_by: AgentIdentity
    ) -> FreshnessOutcome:
        """Check 4 on one presentation. Every outcome, pass or refusal, is recorded.

        ``mandate`` is check 2's output, not a claim. The key the hop must be signed by
        is the key check 2 proved the mandate endorses, and the presentation the hop
        must be made over is the one check 2 verified -- so evaluating a mandate that
        did not verify would be checking a proof of possession against a key nobody had
        established, and raises rather than refusing again.

        One presentation, not both of an agent's mandates. ``sd_hash`` binds a hop to
        exactly one, so a Checkout Mandate and a Payment Mandate carry a hop each and
        get a verdict each; running the spine over both is ticket 06's.
        """
        presentation, digest, verified = _verified(mandate)
        now = datetime.now(UTC)

        try:
            binding = read_key_binding(
                presentation,
                endorsed_key=presented_by.public_key,
                algorithm=digest.algorithm,
            )
        except NotFresh as refused:
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.REQUEST_STALE,
                reasoning=str(refused),
                evidence=_mandate_evidence(verified, now),
            )

        if binding.audience != self._policy.audience:
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.REQUEST_STALE,
                reasoning=(
                    f"the proof of possession is addressed to {binding.audience!r} and this "
                    f"is {self._policy.audience!r}; a proof made for another verifier is a "
                    f"real signature the Desk was never given"
                ),
                evidence=binding.evidence() | _mandate_evidence(verified, now),
            )

        if not self._policy.covers(binding.issued_at, now=now):
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.REQUEST_STALE,
                reasoning=(
                    f"the proof of possession is stamped {binding.issued_at.isoformat()} and "
                    f"the Desk honours one made within {int(self._policy.window.total_seconds())} "
                    f"seconds of now; captured traffic goes stale, which is the point"
                ),
                evidence=binding.evidence() | _mandate_evidence(verified, now),
            )

        if verified.issued_at is not None and binding.issued_at + self._policy.clock_skew < (
            verified.issued_at
        ):
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.REQUEST_STALE,
                reasoning=(
                    "the proof of possession is dated before the mandate it presents, so it "
                    "was made before there was any authority to present"
                ),
                evidence=binding.evidence() | _mandate_evidence(verified, now),
            )

        if verified.has_expired(at=binding.issued_at):
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.REQUEST_STALE,
                reasoning=(
                    "the proof of possession was made after the mandate had lapsed; the "
                    "handover is recent and what was handed over had already expired"
                ),
                evidence=binding.evidence() | _mandate_evidence(verified, now),
            )

        return self._spend(binding, presented_by=presented_by, mandate=verified, now=now)

    def forget_spent_nonces(self, *, now: datetime | None = None) -> int:
        """Drop nonces whose presentations the window would refuse anyway.

        The horizon is the policy's and not a caller's, because the two are one number:
        forgetting further back than the window is safe, forgetting less far is not.
        ``NonceStore.forget`` sets out why.
        """
        at = datetime.now(UTC) if now is None else now
        return self._nonces.forget(presented_before=self._policy.stale_before(at))

    def _spend(
        self,
        binding: KeyBinding,
        *,
        presented_by: AgentIdentity,
        mandate: OpenMandate,
        now: datetime,
    ) -> FreshnessOutcome:
        """Claim the nonce, and record the outcome on the transaction that claimed it.

        Both outcomes are written here, on one connection. A pass has to be, because
        spending the nonce and recording that it was spent are the same fact. A replay
        is written on it too rather than on a second transaction: the insert changed
        nothing, so there is no state for the entry to disagree with, and one path is
        easier to be sure of than two.
        """
        with self._nonces.transaction() as conn:
            claimed = self._nonces.claim(
                binding.nonce,
                agent_id=presented_by.agent_id,
                audience=binding.audience,
                presented_at=binding.issued_at,
                conn=conn,
            )
            if not claimed:
                return self._refuse(
                    presented_by=presented_by,
                    reason=ReasonCode.NONCE_REPLAYED,
                    reasoning=(
                        "the Desk has already honoured a presentation carrying this nonce "
                        "from this agent; everything else about this request is valid, "
                        "which is exactly what a replay looks like"
                    ),
                    evidence=binding.evidence() | _mandate_evidence(mandate, now),
                    conn=conn,
                )

            entry = self._trail.record(
                conn=conn,
                actor="desk",
                event_type=EventType.CHECK_4_REPLAY_FRESHNESS_PASSED,
                subject_id=presented_by.agent_id,
                payload={
                    "check": 4,
                    "reasoning": (
                        "the agent proved it holds its key over this exact presentation, "
                        "addressed to this Desk, within the freshness window and inside "
                        "the mandate's own life, under a nonce never seen before"
                    ),
                    "evidence": self._policy.describe()
                    | binding.evidence()
                    | _mandate_evidence(mandate, now),
                    # Fresh, not inspected. Whether the text inside the request is safe
                    # is check 5, which has not run.
                    "state_change": {"nonce": "spent", "request": "fresh"},
                },
            )
        return FreshnessOutcome(key_binding=binding, reason_code=None, entry=entry)

    def _refuse(
        self,
        *,
        presented_by: AgentIdentity,
        reason: ReasonCode,
        reasoning: str,
        evidence: dict[str, Any],
        conn: Connection[Any] | None = None,
    ) -> FreshnessOutcome:
        entry = self._trail.record(
            conn=conn,
            actor="desk",
            event_type=EventType.CHECK_4_REPLAY_FRESHNESS_REFUSED,
            subject_id=presented_by.agent_id,
            reason_code=reason,
            payload={
                "check": 4,
                "reasoning": reasoning,
                "evidence": self._policy.describe() | evidence,
                "state_change": {"request": "refused"},
            },
        )
        return FreshnessOutcome(key_binding=None, reason_code=reason, entry=entry)


def _verified(outcome: MandateOutcome[M]) -> tuple[str, MandateDigest, M]:
    """What is inside a check-2 outcome, or a raise saying there is nothing inside it."""
    if outcome.mandate is None or outcome.digest is None or outcome.presentation is None:
        raise ValueError(
            f"check 4 reads the key-binding hop on a presentation check 2 verified, and "
            f"this mandate did not verify ({outcome.reason_code}). A refusal is an answer "
            f"already; running a later check on it would invent a second one."
        )
    return outcome.presentation, outcome.digest, outcome.mandate


def _mandate_evidence(mandate: OpenMandate, now: datetime) -> dict[str, Any]:
    """The other layer's dates, on every outcome.

    Both are here even on a refusal that never reached them, because "stale" is an
    assertion until the two instants it was decided between are in the entry beside it.
    """
    return {
        "mandate_issued_at": (None if mandate.issued_at is None else mandate.issued_at.isoformat()),
        "mandate_expires_at": (
            None if mandate.expires_at is None else mandate.expires_at.isoformat()
        ),
        "presented_at": now.isoformat(),
    }

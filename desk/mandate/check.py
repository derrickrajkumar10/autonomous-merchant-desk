"""Check 2 -- mandate validity. Did a human really authorise this, and for this agent?

Check 1 proved *who is asking*. It proved nothing about *what they may ask for*, and
the gap between those two sentences is the whole reason this check exists. An agent
can be perfectly, provably itself and still be presenting an authorisation it was
never given.

Three questions, in this order, each cheap and certain (FR-3.1 -- no model decides any
of them):

1. **Does the principal's signature verify?** Against the key the Desk holds for the
   principal this agent registered under -- never against a key the mandate names for
   itself, which a forger would simply choose.
2. **Is the mandate still in date?** Its own ``exp``, if it set one.
3. **Does it name this agent?** The ``cnf`` claim carries a public key, and the
   presenting agent's registered key must be that key. This is what makes a *stolen*
   mandate worthless rather than merely stolen -- AP2 requires it, and we implement
   it (CONTEXT.md section 4).

The order is not arbitrary. Nothing a mandate says means anything before its signature
verifies, so reading an expiry or a key binding out of an unverified mandate would be
reading whatever the sender wanted us to read.

Two mandates, the same three questions. A buyer agent presents an open **Checkout**
Mandate saying what may be bought and an open **Payment** Mandate saying what may be
spent, because that is how AP2 v0.2 splits them; ``verify`` reads the first and
``verify_payment`` the second. Whether the two belong *together* is check 3's, since
the answer is a constraint inside one of them rather than a property of either.

Passing says one thing only: *a human the Desk knows authorised something, and this
agent is the one allowed to present it*. It says nothing about whether what is being
asked for is inside that authorisation -- that is check 3 -- nor whether this
presentation is a replay of an earlier one, which is check 4.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.identity import AgentIdentity, PrincipalDirectory
from desk.mandate.checkout import OpenCheckoutMandate, read_open_checkout_mandate
from desk.mandate.open_mandate import OpenMandate
from desk.mandate.payment import OpenPaymentMandate, read_open_payment_mandate
from desk.mandate.sdjwt import (
    MandateDigest,
    MandateHeader,
    MandateNotVerified,
    read_mandate_header,
    verify_presentation,
)

M = TypeVar("M", bound=OpenMandate)


@dataclass(frozen=True)
class MandateOutcome(Generic[M]):
    """What check 2 concluded, and the entry it wrote concluding it.

    The mandate is here because reading one is the check's own work: a caller that
    parsed it beforehand would have parsed an unverified mandate. On a refusal there
    is none, because nothing about it was proven.

    ``digest`` names the presentation the mandate was read from, and is what check 3
    compares against a ``payment.reference``. ``mandate_id`` names the bytes the
    signature covers, and is what any *state* keyed to this mandate must use --
    ``sdjwt.signed_digest_of`` explains why the two cannot be the same digest.

    ``presentation`` is the mandate as it arrived, kept so that check 3 can re-digest
    it under the other mandate's algorithm when AP2 requires that. Re-deriving it from
    anything else would mean digesting a string nobody had checked was the one that
    verified.
    """

    mandate: M | None
    digest: MandateDigest | None
    mandate_id: MandateDigest | None
    presentation: str | None
    reason_code: ReasonCode | None
    entry: AuditEntry

    @property
    def passed(self) -> bool:
        return self.mandate is not None


class MandateCheck:
    """Verify an open mandate against its principal and the agent presenting it."""

    def __init__(self, principals: PrincipalDirectory, trail: AuditTrail) -> None:
        self._principals = principals
        self._trail = trail

    def verify(
        self, mandate: str, *, presented_by: AgentIdentity
    ) -> MandateOutcome[OpenCheckoutMandate]:
        """Check 2 on one open Checkout Mandate -- *what may be bought*.

        ``presented_by`` is check 1's output, not a claim: the agent whose signature
        already verified on the request this mandate arrived in. Passing an identity
        the Desk has not just authenticated would make this check verify a binding to
        a name rather than to a key.
        """
        return self._verify(mandate, presented_by=presented_by, read=read_open_checkout_mandate)

    def verify_payment(
        self, mandate: str, *, presented_by: AgentIdentity
    ) -> MandateOutcome[OpenPaymentMandate]:
        """Check 2 on one open Payment Mandate -- *what may be spent*.

        The same three questions, because they are questions about a mandate rather
        than about a kind of mandate. A Payment Mandate that verifies here is one a
        human signed and this agent may present; whether its budget covers the deal,
        and whether it even refers to the checkout being asked for, is check 3.
        """
        return self._verify(mandate, presented_by=presented_by, read=read_open_payment_mandate)

    def _verify(
        self,
        mandate: str,
        *,
        presented_by: AgentIdentity,
        read: Callable[[Mapping[str, Any]], M],
    ) -> MandateOutcome[M]:
        """The three questions, over whichever open mandate ``read`` knows how to read."""
        claimed = _header(mandate)

        principal = self._principals.find(presented_by.principal_id)
        if principal is None:
            return self._refuse(
                presented_by=presented_by,
                claimed=claimed,
                reason=ReasonCode.MANDATE_SIGNATURE_INVALID,
                reasoning=(
                    f"{presented_by.agent_id} acts for {presented_by.principal_id!r}, and the "
                    f"Desk holds no key for that principal, so nothing can establish that a "
                    f"human authorised this"
                ),
            )

        try:
            presentation = verify_presentation(mandate, principal.public_key)
            verified = read(presentation.claims)
        except MandateNotVerified as refused:
            return self._refuse(
                presented_by=presented_by,
                claimed=claimed,
                reason=ReasonCode.MANDATE_SIGNATURE_INVALID,
                reasoning=str(refused),
                principal_id=principal.principal_id,
            )

        now = datetime.now(UTC)
        if verified.has_expired(at=now):
            return self._refuse(
                presented_by=presented_by,
                claimed=claimed,
                reason=ReasonCode.MANDATE_EXPIRED,
                reasoning=(
                    "the mandate expired before it was presented; what the principal "
                    "authorised has lapsed, whoever is presenting it"
                ),
                principal_id=principal.principal_id,
                mandate=verified,
                now=now,
            )

        if not verified.binds(presented_by.public_key):
            return self._refuse(
                presented_by=presented_by,
                claimed=claimed,
                reason=ReasonCode.AGENT_MANDATE_MISMATCH,
                reasoning=(
                    f"the mandate binds a different key to the one {presented_by.agent_id} "
                    f"registered, so this agent is not the one the principal authorised "
                    f"to present it"
                ),
                principal_id=principal.principal_id,
                mandate=verified,
                now=now,
            )

        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_2_MANDATE_VALIDITY_PASSED,
            subject_id=presented_by.agent_id,
            payload={
                "check": 2,
                "reasoning": (
                    "the mandate carries the principal's signature, has not expired, and "
                    "binds the key this agent registered, so a human authorised this agent "
                    "to ask"
                ),
                "evidence": _evidence(claimed, principal.principal_id, verified, now)
                | {"mandate_digest": presentation.digest.value},
                # Authorised, not yet in budget. Whether what is being asked for is
                # inside the mandate's constraints is check 3, which has not run.
                "state_change": {"mandate": "valid"},
            },
        )
        return MandateOutcome(
            mandate=verified,
            digest=presentation.digest,
            mandate_id=presentation.mandate_id,
            presentation=mandate,
            reason_code=None,
            entry=entry,
        )

    def _refuse(
        self,
        *,
        presented_by: AgentIdentity,
        claimed: MandateHeader | None,
        reason: ReasonCode,
        reasoning: str,
        principal_id: str | None = None,
        mandate: OpenMandate | None = None,
        now: datetime | None = None,
    ) -> MandateOutcome[Any]:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_2_MANDATE_VALIDITY_REFUSED,
            subject_id=presented_by.agent_id,
            reason_code=reason,
            payload={
                "check": 2,
                "reasoning": reasoning,
                "evidence": _evidence(claimed, principal_id, mandate, now),
                "state_change": {"request": "refused"},
            },
        )
        return MandateOutcome(
            mandate=None,
            digest=None,
            mandate_id=None,
            presentation=None,
            reason_code=reason,
            entry=entry,
        )


def _header(mandate: str) -> MandateHeader | None:
    """What the mandate claimed about itself, or nothing if it claimed nothing.

    Read before any verification and recorded on every outcome, so that a mandate
    naming the wrong algorithm or the wrong principal is visible in the trail rather
    than merely refused. Never used to choose a key.
    """
    try:
        return read_mandate_header(mandate)
    except MandateNotVerified:
        return None


def _evidence(
    claimed: MandateHeader | None,
    principal_id: str | None,
    mandate: OpenMandate | None,
    now: datetime | None,
) -> dict[str, Any]:
    """What the mandate claimed, whose key was used, and the dates the check compared.

    ``claimed_principal_id`` is the mandate's own ``kid`` and ``verified_against`` is
    the principal the Desk actually resolved. They are recorded separately and side by
    side, because a mandate claiming to be one principal's while being checked against
    another's is exactly the shape of an attempt worth being able to find later.
    """
    evidence: dict[str, Any] = {
        "claimed_principal_id": None if claimed is None else claimed.claimed_principal_id,
        "algorithm": None if claimed is None else claimed.algorithm,
        "verified_against": principal_id,
    }
    if mandate is not None:
        evidence |= {
            "key_binding": dict(mandate.key_binding),
            "expires_at": None if mandate.expires_at is None else mandate.expires_at.isoformat(),
            "presented_at": None if now is None else now.isoformat(),
        }
    return evidence

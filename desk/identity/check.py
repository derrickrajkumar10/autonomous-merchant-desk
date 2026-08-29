"""Check 1 -- identity. Is this request from an agent the Desk has registered?

The first and cheapest question in the trust spine, and the one that eliminates the
largest class of traffic. It is pure deterministic code: cryptography decides it, and
no model may (FR-3.1, CONTEXT.md section 5 principle 1).

Passing says one thing only: *this request came from this registered agent and was
not altered in flight*. It says nothing about whether a human authorised the spend,
whether the request is fresh, or whether the text inside it is safe. Those are checks
2 through 5, and this check must never be read as standing in for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.identity.jws import RequestHeader, RequestNotVerified, read_header, verify_request
from desk.identity.registry import AgentIdentity, AgentRegistry

#: What a refusal is recorded against when the request never named an agent. Subjects
#: are never blank, and every refusal has to be findable in the trail.
UNIDENTIFIED_AGENT = "unidentified-agent"


@dataclass(frozen=True)
class IdentityOutcome:
    """What check 1 concluded, and the entry it wrote concluding it.

    The body is here because it arrives inside the signature: a caller that read the
    request before the check would be reading unverified bytes. On a refusal there is
    no body, because nothing about the request was proven.
    """

    identity: AgentIdentity | None
    body: dict[str, Any] | None
    reason_code: ReasonCode | None
    entry: AuditEntry

    @property
    def passed(self) -> bool:
        return self.identity is not None


class IdentityCheck:
    """Verify a signed request against the registered public key it claims."""

    def __init__(self, registry: AgentRegistry, trail: AuditTrail) -> None:
        self._registry = registry
        self._trail = trail

    def verify(self, request: str) -> IdentityOutcome:
        """Check 1 on one signed request. Every outcome, pass or refusal, is recorded.

        A refusal always leaves under ``agent_signature_invalid``: from outside, an
        unregistered key, a forged signature and a body altered in flight are one
        answer -- *that signature does not belong to a registered agent* -- and telling
        them apart on the wire would tell a prober which half of the lie was believed.
        The trail is where they are told apart, because that is a reader we trust.
        """
        try:
            header = read_header(request)
        except RequestNotVerified as unreadable:
            return self._refuse(
                subject_id=UNIDENTIFIED_AGENT, claimed=None, reasoning=str(unreadable)
            )

        claimed_agent_id = header.claimed_agent_id
        identity = None if claimed_agent_id is None else self._registry.find(claimed_agent_id)
        if identity is None:
            return self._refuse(
                subject_id=claimed_agent_id or UNIDENTIFIED_AGENT,
                claimed=header,
                reasoning=(
                    "no agent is registered under the key this request claims to be signed by"
                ),
            )

        try:
            body = verify_request(request, identity.public_key)
        except RequestNotVerified as invalid:
            return self._refuse(
                subject_id=identity.agent_id, claimed=header, reasoning=str(invalid)
            )

        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_1_IDENTITY_PASSED,
            subject_id=identity.agent_id,
            payload={
                "check": 1,
                "reasoning": (
                    "the signature verifies against the public key this agent registered, "
                    "so the request is from it and reached the Desk unaltered"
                ),
                "evidence": _evidence(header) | {"public_key": identity.public_key.base64url()},
                # Identified, not authorised. Whether this agent may spend is checks 2
                # and 3, and neither has run.
                "state_change": {"request": "identified"},
            },
        )
        return IdentityOutcome(identity=identity, body=body, reason_code=None, entry=entry)

    def _refuse(
        self, *, subject_id: str, claimed: RequestHeader | None, reasoning: str
    ) -> IdentityOutcome:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_1_IDENTITY_REFUSED,
            subject_id=subject_id,
            reason_code=ReasonCode.AGENT_SIGNATURE_INVALID,
            payload={
                "check": 1,
                "reasoning": reasoning,
                "evidence": _evidence(claimed),
                "state_change": {"request": "refused"},
            },
        )
        return IdentityOutcome(
            identity=None,
            body=None,
            reason_code=ReasonCode.AGENT_SIGNATURE_INVALID,
            entry=entry,
        )


def _evidence(claimed: RequestHeader | None) -> dict[str, Any]:
    """What the request claimed about itself, recorded on every outcome.

    The algorithm is here on a pass as well as a refusal, so a wrong-algorithm path is
    visible in the trail rather than silent (ADR-0002). Both are ``None`` when the
    request was not readable enough to claim anything.
    """
    if claimed is None:
        return {"claimed_agent_id": None, "algorithm": None}
    return {"claimed_agent_id": claimed.claimed_agent_id, "algorithm": claimed.algorithm}

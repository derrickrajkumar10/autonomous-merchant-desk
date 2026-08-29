"""What the two open mandates have in common, and the reading they share.

AP2 v0.2 defines two **open** mandates -- an open Checkout Mandate and an open
Payment Mandate -- and they agree on more than they differ. Both are SD-JWTs whose
claims name a ``vct``, carry an array of ``constraints``, bind exactly one agent's
key in ``cnf``, and may set ``iat`` and ``exp``. What differs is which constraint
types are legal inside the array, which of them the schema makes mandatory, and what
each one means.

So the *reading* lives here and the *meaning* lives next door: ``checkout.py`` says
what a checkout constraint is for, ``payment.py`` says what a payment constraint is
for, and neither repeats how to get a timestamp out of a claim.

Field structure read from AP2 v0.2's canonical JSON Schemas,
``code/sdk/schemas/ap2/open_checkout_mandate.json`` and
``code/sdk/schemas/ap2/open_payment_mandate.json`` at commit ``e1ea56d``. Both list
``["vct", "constraints", "cnf"]`` as required.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from desk.identity import AgentPublicKey
from desk.mandate.sdjwt import MandateNotVerified

#: AP2's SDK nests the mandate's claims one level down under this name, so that the
#: same disclosure resolver serves a root mandate and a later delegation hop alike.
#: The specification's own prose lists the claims at the top level. Both shapes are
#: things a stranger might send, so both are read.
DELEGATE_PAYLOAD_CLAIM = "delegate_payload"


@dataclass(frozen=True)
class OpenMandate:
    """One principal's forward-looking authorisation, as the Desk reads it.

    Holds no verdict. Whether the mandate is still in date, whether it names the agent
    presenting it, and whether what is being asked for is inside its constraints are
    check 2's and check 3's questions; this is the thing they ask them about.
    """

    constraints: tuple[Mapping[str, Any], ...]
    key_binding: Mapping[str, Any]
    issued_at: datetime | None
    expires_at: datetime | None

    def binds(self, key: AgentPublicKey) -> bool:
        """Whether this mandate's ``cnf`` names exactly this agent's key.

        Compared by RFC 7638 thumbprint rather than by encoded bytes, so a key that
        arrives with its members in another order or with extra ones still matches
        itself. A ``cnf`` holding anything that is not an Ed25519 key matches no agent
        the Desk has registered, and says so by returning ``False`` -- it is not the
        signature that is wrong, it is the binding.
        """
        try:
            bound = AgentPublicKey.from_jwk(self.key_binding.get("jwk"))
        except ValueError:
            return False
        return bound.thumbprint() == key.thumbprint()

    def has_expired(self, *, at: datetime) -> bool:
        """Whether the mandate's own expiry has passed.

        A mandate with no ``exp`` never expires by this test. AP2 leaves the claim
        optional -- only RECOMMENDED -- so refusing one for its absence would refuse a
        conformant mandate. What bounds such a mandate instead is the freshness window
        on the presentation itself, which is check 4 and ticket 05's to build.
        """
        return self.expires_at is not None and at >= self.expires_at

    def constraint(self, constraint_type: str) -> Mapping[str, Any] | None:
        """The one constraint of this type, or ``None`` when the mandate sets none.

        Two constraints of one type is a refusal rather than a choice. AP2's schemas
        do not forbid the shape, but every constraint the Desk reads carries a single
        value -- one ceiling, one window -- and taking whichever came first would be
        taking whichever the sender put first.
        """
        found = [
            constraint
            for constraint in self.constraints
            if constraint.get("type") == constraint_type
        ]
        if len(found) > 1:
            raise MandateNotVerified(
                f"the mandate carries {len(found)} {constraint_type} constraints and the "
                f"Desk will not choose between them"
            )
        return found[0] if found else None


def read_open_mandate(claims: Mapping[str, Any], *, vct: str) -> OpenMandate:
    """The open mandate these verified claims describe, or a refusal saying why not.

    Every refusal names the field, because "malformed mandate" tells a counterparty
    nothing it can fix and tells the trail nothing worth aggregating.
    """
    content = mandate_content(claims)

    claimed_vct = content.get("vct")
    if claimed_vct != vct:
        raise MandateNotVerified(
            f"the Desk reads {vct} mandates here; this one is a {claimed_vct!r}"
        )

    key_binding = content.get("cnf")
    if not isinstance(key_binding, Mapping) or "jwk" not in key_binding:
        raise MandateNotVerified(
            "the mandate carries no cnf key binding, which AP2 requires on an open "
            "mandate; without it any agent could present it"
        )

    return OpenMandate(
        constraints=read_constraints(content.get("constraints")),
        key_binding=dict(key_binding),
        issued_at=epoch(content.get("iat"), "iat"),
        expires_at=epoch(content.get("exp"), "exp"),
    )


def mandate_content(claims: Mapping[str, Any]) -> Mapping[str, Any]:
    """The mandate's own claims, whichever of the two shapes they arrived in."""
    nested = claims.get(DELEGATE_PAYLOAD_CLAIM)
    if nested is None:
        return claims
    if not isinstance(nested, Sequence) or isinstance(nested, str | bytes) or len(nested) != 1:
        raise MandateNotVerified(
            f"the mandate's {DELEGATE_PAYLOAD_CLAIM} holds "
            f"{'nothing' if not nested else 'more than one mandate'}, and the Desk "
            f"reads one mandate at a time"
        )
    content = nested[0]
    if not isinstance(content, Mapping):
        raise MandateNotVerified(f"the mandate's {DELEGATE_PAYLOAD_CLAIM} is not a mandate")
    return content


def read_constraints(claimed: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(claimed, Sequence) or isinstance(claimed, str | bytes):
        raise MandateNotVerified("the mandate's constraints must be a list")
    if any(not isinstance(constraint, Mapping) for constraint in claimed):
        raise MandateNotVerified("every constraint in a mandate is an object with a type")
    return tuple(dict(constraint) for constraint in claimed)


def epoch(claimed: Any, name: str) -> datetime | None:
    """One of AP2's Unix-epoch timestamps, as an instant.

    ``bool`` is a subclass of ``int`` and would otherwise read as 1970; a mandate
    claiming ``exp: true`` is malformed, not ancient.
    """
    if claimed is None:
        return None
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise MandateNotVerified(f"the mandate's {name} must be a Unix epoch second")
    try:
        return datetime.fromtimestamp(claimed, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise MandateNotVerified(f"the mandate's {name} is not a usable instant: {exc}") from exc


def iso8601(claimed: Any, name: str) -> datetime:
    """One of AP2's ISO 8601 date-times, as an instant.

    A value carrying no offset is read as UTC rather than refused. AP2's own examples
    are stamped ``Z``, but ``not_after: "2026-04-30"`` is valid ISO 8601 and is what a
    wallet writing a date rather than an instant would send; refusing it would refuse a
    conformant mandate over a formatting choice.
    """
    if not isinstance(claimed, str):
        raise MandateNotVerified(f"the mandate's {name} must be an ISO 8601 date-time")
    try:
        read = datetime.fromisoformat(claimed)
    except ValueError as exc:
        raise MandateNotVerified(
            f"the mandate's {name} is not an ISO 8601 date-time: {exc}"
        ) from exc
    return read if read.tzinfo is not None else read.replace(tzinfo=UTC)

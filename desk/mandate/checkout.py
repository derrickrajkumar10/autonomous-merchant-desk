"""The open Checkout Mandate: what a principal signs, and what makes it well formed.

This is the artefact behind the sentence the whole project exists for -- *"restock my
coffee, keep it under 2,000 rupees"*. A human says it, their wallet turns it into
constraints, signs them, and names the one agent allowed to present the result. The
Desk reads it here.

**Open** is AP2's own word for the human-not-present case: the principal is not at the
keyboard when the purchase happens, so what they signed is a set of forward-looking
constraints rather than one agreed basket. The matching **closed** variant -- the
specific negotiated deal -- is a later ticket's work and is not read here.

Three fields carry the weight, and AP2 v0.2 makes each of them required:

- ``vct`` names which of the four mandate shapes this is. A Payment Mandate arriving
  where a Checkout Mandate belongs is refused rather than read hopefully.
- ``constraints`` is what the principal actually authorised. At least one
  ``checkout.line_items`` constraint is mandatory in the schema; the Desk enforces
  that, and leaves *evaluating* the constraints to check 3.
- ``cnf`` carries the presenting agent's own public key (RFC 7800). This is the thing
  that makes a stolen mandate worthless: whoever took it still cannot produce a
  signature under the key the mandate names. **AP2 requires this; we did not invent
  it** (CONTEXT.md section 4).

Field structure read from AP2 v0.2's canonical JSON Schema,
``code/sdk/schemas/ap2/open_checkout_mandate.json`` at commit ``e1ea56d``. See
[the research note](../../docs/research/ap2-mandate-model.md) section 1a.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from desk.identity import AgentPublicKey
from desk.mandate.sdjwt import MandateNotVerified

#: The ``vct`` an open Checkout Mandate carries, and only it. ``mandate.checkout.1``
#: is the closed variant, and the two Payment Mandates are a different artefact again.
OPEN_CHECKOUT_VCT = "mandate.checkout.open.1"

#: The one constraint AP2's schema makes mandatory on this mandate: a ``contains``
#: rule, so a mandate authorising nothing in particular is not a mandate.
LINE_ITEMS_CONSTRAINT = "checkout.line_items"

#: AP2's SDK nests the mandate's claims one level down under this name, so that the
#: same disclosure resolver serves a root mandate and a later delegation hop alike.
#: The specification's own prose lists the claims at the top level. Both shapes are
#: things a stranger might send, so both are read.
DELEGATE_PAYLOAD_CLAIM = "delegate_payload"


@dataclass(frozen=True)
class OpenCheckoutMandate:
    """One principal's forward-looking authorisation, as the Desk reads it.

    Holds no verdict. Whether the mandate is still in date, whether it names the agent
    presenting it, and whether the amount asked for is inside its constraints are
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


def read_open_checkout_mandate(claims: Mapping[str, Any]) -> OpenCheckoutMandate:
    """The mandate these verified claims describe, or a refusal saying why they do not.

    Every refusal names the field, because "malformed mandate" tells a counterparty
    nothing it can fix and tells the trail nothing worth aggregating.
    """
    content = _mandate_content(claims)

    vct = content.get("vct")
    if vct != OPEN_CHECKOUT_VCT:
        raise MandateNotVerified(
            f"the Desk reads {OPEN_CHECKOUT_VCT} mandates; this one is a {vct!r}"
        )

    constraints = _constraints(content.get("constraints"))
    if not any(constraint.get("type") == LINE_ITEMS_CONSTRAINT for constraint in constraints):
        raise MandateNotVerified(
            f"the mandate carries no {LINE_ITEMS_CONSTRAINT} constraint, which AP2 "
            f"requires; it authorises nothing in particular"
        )

    key_binding = content.get("cnf")
    if not isinstance(key_binding, Mapping) or "jwk" not in key_binding:
        raise MandateNotVerified(
            "the mandate carries no cnf key binding, which AP2 requires on an open "
            "mandate; without it any agent could present it"
        )

    return OpenCheckoutMandate(
        constraints=constraints,
        key_binding=dict(key_binding),
        issued_at=_epoch(content.get("iat"), "iat"),
        expires_at=_epoch(content.get("exp"), "exp"),
    )


def _mandate_content(claims: Mapping[str, Any]) -> Mapping[str, Any]:
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


def _constraints(claimed: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(claimed, Sequence) or isinstance(claimed, str | bytes):
        raise MandateNotVerified("the mandate's constraints must be a list")
    if any(not isinstance(constraint, Mapping) for constraint in claimed):
        raise MandateNotVerified("every constraint in a mandate is an object with a type")
    return tuple(dict(constraint) for constraint in claimed)


def _epoch(claimed: Any, name: str) -> datetime | None:
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

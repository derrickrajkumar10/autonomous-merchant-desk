"""The receipt: what the Desk charged, bound to what it was allowed to charge for.

A record in the Desk's own database says "we charged you 1,500 rupees" and proves
nothing to anybody. The buyer has to take the Desk's word for it, and so does the
buyer's principal, and so does anyone the two of them disagree in front of. A receipt
is the alternative: a document the Desk signed, which anyone holding the Desk's public
key can check without asking the Desk anything.

**Four things bound together, and the binding is the point** (FR-7.2). Any one of them
alone is arguable:

- the **mandate chain** -- which authorisation this charge was made under. A charge
  without it is money moved for no stated reason.
- the **agreed terms** -- the closed Checkout Mandate's payload, carried verbatim. A
  chain without terms proves a human authorised *something*, not this.
- the **amount charged** -- which is what stops the charge and the agreement being
  separated. Terms saying 1,500 beside a charge of 15,000 is the case this closes.
- the **timestamp**, plus the rail's own identifiers, so the charge can be traced back
  to the rail's record of it.

**A plain JWS, and its claims are the registered ones where registered ones exist.**
``iss``, ``sub``, ``jti`` and ``iat`` rather than names of our own, because the claim
being made is that a stranger's library can read this. Anything a stranger's library
already knows how to read should not be spelled our way.

**Ed25519, not ES256.** The closed Checkout Mandate is ``ES256`` because AP2's SDK can
read nothing else (ADR-0002's known exception). A receipt is not an AP2 document and
never goes through AP2's SDK, so the exception does not follow it and ADR-0002's
default stands. ``DeskReceiptKeypair`` is therefore a second key, not a second method
on the first.

**A receipt is named by the deal it settles.** ``jti`` is the closed Checkout Mandate's
hash, so one closed deal has one receipt and asking for "the receipt for this deal" is
answerable without a lookup table. There is no revocation and no correction: a receipt
records something that happened.

    from desk.settlement import issue_receipt, read_receipt

    signed = issue_receipt(closed, charge=rail_charge, ...)
    receipt = read_receipt(signed, key=vault.published().receipt)
    receipt.charged            # what actually moved
    receipt.agreed["total"]    # what was agreed it would be
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from jwt.api_jws import decode_complete as jws_decode_complete
from jwt.exceptions import PyJWTError

from desk.identity import (
    DESK_RECEIPT_ALG,
    DESK_RECEIPT_KEY_ID,
    DeskReceiptKeypair,
    DeskReceiptPublicKey,
)
from desk.mandate import ClosedCheckoutMandate, MandateDigest
from desk.settlement.rail import RailCharge
from desk.spend.money import Money

#: The ``typ`` a receipt carries. Not an SD-JWT and not a mandate -- saying so in the
#: header stops a reader handing it to a routine that expects either.
RECEIPT_TYP = "receipt+jwt"

#: Who issued it. The same word the Desk calls itself by inside a Checkout payload.
ISSUER = "desk"

#: Where the chain, the terms, the amount and the rail sit in the claims.
CHAIN_CLAIM = "mandate_chain"
AGREED_CLAIM = "agreed"
CHARGED_CLAIM = "charged"
RAIL_CLAIM = "rail"


class ReceiptNotVerified(ValueError):
    """A receipt the Desk cannot prove it issued, or one it cannot read back.

    One exception for both, deliberately. A reader must not be able to tell a forged
    signature from a malformed claim, because the honest answer in either case is the
    same: this is not a receipt the Desk will stand behind.
    """


@dataclass(frozen=True)
class MandateChain:
    """The three links from a human's authorisation to the money that moved.

    - ``open_checkout``: the open Checkout Mandate -- what the human was willing to buy.
    - ``open_payment``: the open Payment Mandate -- what the human was willing to spend.
    - ``closed_checkout``: the closed Checkout Mandate -- the one deal that was agreed.

    All three are digests rather than the credentials themselves. A receipt is evidence
    about a charge, not a place to republish a mandate, and a digest is enough for the
    holder of the mandate to prove the receipt is about theirs.
    """

    open_checkout: str
    open_payment: str
    closed_checkout: str

    def __post_init__(self) -> None:
        for name, link in (
            ("open_checkout", self.open_checkout),
            ("open_payment", self.open_payment),
            ("closed_checkout", self.closed_checkout),
        ):
            if not isinstance(link, str) or not link.strip():
                raise ReceiptNotVerified(f"a mandate chain names its {name}")

    def as_claim(self) -> dict[str, str]:
        return {
            "open_checkout": self.open_checkout,
            "open_payment": self.open_payment,
            "closed_checkout": self.closed_checkout,
        }


@dataclass(frozen=True)
class Receipt:
    """One receipt, read back and verified. What the Desk will stand behind.

    ``agreed`` is the closed Checkout Mandate's own payload, carried through unchanged
    rather than re-modelled here. Re-modelling it would mean this file had an opinion
    about what a deal's terms look like, and a lever added in ticket 21 would need a
    change here to appear on a receipt.
    """

    receipt_id: str
    agent_id: str
    chain: MandateChain
    agreed: Mapping[str, Any]
    charged: Money
    charge: RailCharge
    issued_at: datetime


def issue_receipt(
    closed: ClosedCheckoutMandate,
    *,
    payment_mandate: MandateDigest,
    charge: RailCharge,
    charged: Money,
    agent_id: str,
    signed_by: DeskReceiptKeypair,
    issued_at: datetime | None = None,
) -> str:
    """Sign one receipt for a charge that completed.

    Takes the closed mandate the Desk read back rather than the terms as some caller
    remembers them, so the terms on the receipt are the terms the Desk's own signature
    already covers. Two documents that disagree about a deal would be worse than one.

    Refuses to sign for a charge that did not complete. That refusal is the acceptance
    criterion "a charge that does not complete produces no receipt", held here as well
    as in ``settle.py`` -- the caller decides *when* to issue one, and this decides that
    there is no way to ask for one that is not about money that actually moved.
    """
    if not charge.completed:
        raise ReceiptNotVerified(
            f"the rail did not complete this charge ({charge.status}), so there is "
            f"nothing to receipt. A receipt records something that happened."
        )
    at = datetime.now(UTC) if issued_at is None else issued_at
    chain = MandateChain(
        open_checkout=closed.checkout.open_checkout,
        open_payment=payment_mandate.value,
        closed_checkout=closed.checkout_hash.value,
    )
    return signed_by.sign(
        {
            "iss": ISSUER,
            "jti": chain.closed_checkout,
            "sub": agent_id,
            "iat": int(at.timestamp()),
            CHAIN_CLAIM: chain.as_claim(),
            AGREED_CLAIM: closed.checkout.as_claims(),
            CHARGED_CLAIM: {"amount": str(charged.amount), "currency": charged.currency},
            RAIL_CLAIM: charge.as_claim(),
        },
        typ=RECEIPT_TYP,
    )


def read_receipt(signed: str, *, key: DeskReceiptPublicKey) -> Receipt:
    """Read one back, refusing anything the Desk cannot prove it issued.

    This is the Desk's own path, and it is deliberately not the one FR-7.3 is about.
    The claim there is that a *stranger* can verify a receipt with an off-the-shelf
    library and the published key, so the suite proves that with somebody else's
    library rather than this function -- checking our signatures with our own verifier
    would only show the two halves agree with each other.
    """
    try:
        decoded = jws_decode_complete(signed, key=key.verifier(), algorithms=[DESK_RECEIPT_ALG])
    except PyJWTError as exc:
        raise ReceiptNotVerified(f"this is not a receipt the Desk signed: {exc}") from exc

    header = decoded["header"]
    if header.get("typ") != RECEIPT_TYP:
        raise ReceiptNotVerified(
            f"a receipt carries typ {RECEIPT_TYP!r}; this carries {header.get('typ')!r}"
        )
    if header.get("kid") != DESK_RECEIPT_KEY_ID:
        raise ReceiptNotVerified(
            f"a receipt is signed under {DESK_RECEIPT_KEY_ID!r}, not {header.get('kid')!r}"
        )

    claims = _claims(decoded["payload"])
    if claims.get("iss") != ISSUER:
        raise ReceiptNotVerified(f"a receipt is issued by {ISSUER!r}, not {claims.get('iss')!r}")

    chain = _chain(claims.get(CHAIN_CLAIM))
    receipt_id = _text(claims.get("jti"), "jti")
    if receipt_id != chain.closed_checkout:
        raise ReceiptNotVerified(
            "a receipt is named by the closed Checkout Mandate it settles, and this "
            "one's jti names something else"
        )

    agreed = claims.get(AGREED_CLAIM)
    if not isinstance(agreed, Mapping):
        raise ReceiptNotVerified("a receipt carries the terms that were agreed")

    return Receipt(
        receipt_id=receipt_id,
        agent_id=_text(claims.get("sub"), "sub"),
        chain=chain,
        agreed=dict(agreed),
        charged=_charged(claims.get(CHARGED_CLAIM)),
        charge=_charge(claims.get(RAIL_CLAIM)),
        issued_at=_issued_at(claims.get("iat")),
    )


def _claims(payload: bytes) -> Mapping[str, Any]:
    """The signed bytes as claims, with exact decimals kept exact.

    ``parse_float=Decimal`` for the reason it is used on mandates: an amount that
    round-tripped through a float would be a different number from the one signed, and
    the whole value of a receipt is that it says exactly what was charged.
    """
    try:
        claims = json.loads(payload, parse_float=Decimal)
    except ValueError as exc:
        raise ReceiptNotVerified(f"a receipt's payload is JSON: {exc}") from exc
    if not isinstance(claims, dict):
        raise ReceiptNotVerified("a receipt's payload is a JSON object")
    return claims


def _text(claimed: Any, name: str) -> str:
    if not isinstance(claimed, str) or not claimed.strip():
        raise ReceiptNotVerified(f"a receipt carries a {name}")
    return claimed


def _chain(claimed: Any) -> MandateChain:
    if not isinstance(claimed, Mapping):
        raise ReceiptNotVerified("a receipt carries the mandate chain it was charged under")
    return MandateChain(
        open_checkout=_text(claimed.get("open_checkout"), "chain open_checkout"),
        open_payment=_text(claimed.get("open_payment"), "chain open_payment"),
        closed_checkout=_text(claimed.get("closed_checkout"), "chain closed_checkout"),
    )


def _charged(claimed: Any) -> Money:
    if not isinstance(claimed, Mapping):
        raise ReceiptNotVerified("a receipt carries the amount that was charged")
    currency = _text(claimed.get("currency"), "charged currency")
    try:
        return Money.of(_text(claimed.get("amount"), "charged amount"), currency)
    except (InvalidOperation, ValueError) as exc:
        raise ReceiptNotVerified(f"the amount on this receipt is not an amount: {exc}") from exc


def _charge(claimed: Any) -> RailCharge:
    if not isinstance(claimed, Mapping):
        raise ReceiptNotVerified("a receipt carries the rail's own identifiers for the charge")
    order_id = claimed.get("order_id")
    # ``completed`` is true by construction: ``issue_receipt`` refuses to sign for a
    # charge that did not complete, so a receipt that verifies is about one that did.
    return RailCharge(
        rail=_text(claimed.get("rail"), "rail"),
        completed=True,
        status=_text(claimed.get("status"), "rail status"),
        charge_id=_text(claimed.get("charge_id"), "rail charge_id"),
        order_id=None if order_id is None else _text(order_id, "rail order_id"),
    )


def _issued_at(claimed: Any) -> datetime:
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise ReceiptNotVerified("a receipt carries an iat, in whole seconds since the epoch")
    return datetime.fromtimestamp(claimed, tz=UTC)

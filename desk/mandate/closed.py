"""The closed Checkout Mandate: the deal, as agreed, signed by the party that agreed it.

An open Checkout Mandate says what a human is *willing* to buy. It is deliberately
vague about the particulars, because the human was asleep when the particulars got
settled. This is the other end: one specific basket, at one specific set of prices, on
one specific set of terms, fixed at the moment a negotiation closed.

Why it has to exist at all: without it, "what was agreed" is whatever the two parties
each remember, and the settlement step has nothing to charge against. FR-5.6 asks for
it and FR-7.2 will bind a receipt to it.

**Two nested signatures, and AP2 chose the nesting rather than us.** The schema at
``code/sdk/schemas/ap2/checkout_mandate.json`` gives the closed mandate three fields
that matter:

- ``checkout_jwt`` -- "base64url-encoded serialized **merchant-signed** JWT of the
  Checkout payload". The inner document. The merchant signs it because the merchant is
  the party stating the terms.
- ``checkout_hash`` -- the digest of that field's value, naming this checkout uniquely.
- ``vct`` -- ``mandate.checkout.1``, which is how a reader tells a closed mandate from
  an open one without inspecting anything else.

AP2 puts the *contents* of ``checkout_jwt`` deliberately out of scope
(``docs/ap2/checkout_mandate.md:30-33``), so the negotiated prices, charges and terms
live in a payload the specification does not constrain. That is what makes FR-5.6
answerable inside the standard rather than beside it.

**One divergence, stated plainly.** In AP2's autonomous mode the *agent* signs the
outer closed mandate, using the key the open mandate bound in ``cnf``
(``docs/ap2/specification.md:178-190``). Here the Desk signs both layers. The reason is
that a negotiation is a conversation, not a form: the Desk has to be able to say what it
agreed to whether or not the counterparty comes back to counter-sign, and the buyer's
acceptance is already in the trail. A stranger's client counter-signing the envelope is
ticket 30's, and the shape is ready for it -- the inner document is unchanged by a
second signature over the outer one. Until then, a closed mandate here proves what *the
Desk* committed to and does not prove the buyer agreed. Reading it as both would be the
overclaim, so nothing does.

**What is not in it.** No cost, and no margin. The buyer holds this document, and what
the Desk paid for the goods is not the buyer's business -- a charge appears as the
amount charged and nothing else. The margin position behind the deal goes to the audit
trail, where the Desk's own reader can see it and the counterparty cannot.

    from desk.identity import DeskKeypair
    from desk.mandate import AgreedItem, Checkout, close_checkout, read_closed_checkout

    desk_key = DeskKeypair.generate()
    signed = close_checkout(
        Checkout(
            open_checkout=digest_of(presented_open_mandate).value,
            currency="INR",
            items=(AgreedItem(item_id="SKU-COFFEE-1KG", quantity=2, unit_price=price),),
            charges=(),
            terms={"delivery": "standard", "payment": "prepaid"},
            agreed_at=now,
        ),
        signed_by=desk_key,
    )
    read_closed_checkout(signed, key=desk_key.public_key).checkout.total
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from jwt.utils import base64url_decode, base64url_encode

from desk.identity import DeskKeypair, DeskPublicKey
from desk.mandate.issue import SD_JWT_TYP, disclose, present, sd_jwt_claims
from desk.mandate.open_mandate import epoch, mandate_content
from desk.mandate.sdjwt import (
    DEFAULT_SD_ALG,
    MandateDigest,
    MandateNotVerified,
    verify_presentation,
)

# Reached through the module rather than through ``desk.spend`` because the spend
# accumulator imports this package: going in by the front door here would close a
# cycle. ``money`` imports nothing of ours, which is what makes it safe to reach for.
from desk.spend.money import Money

#: The ``vct`` a closed Checkout Mandate carries, and the one thing distinguishing it
#: from the open variant at a glance.
CLOSED_CHECKOUT_VCT = "mandate.checkout.1"

#: AP2's own field names on the closed mandate.
CHECKOUT_JWT_CLAIM = "checkout_jwt"
CHECKOUT_HASH_CLAIM = "checkout_hash"

#: The ``typ`` on the inner merchant-signed document. Not an SD-JWT -- it is a plain
#: JWS, and saying so in the header stops a reader treating it as a presentation.
CHECKOUT_TYP = "checkout+jwt"

#: What the Desk calls itself inside a Checkout payload.
MERCHANT = "desk"


@dataclass(frozen=True)
class AgreedItem:
    """One line of the agreed basket, at the price that was actually settled on."""

    item_id: str
    quantity: int
    unit_price: Money

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id:
            raise ValueError("an agreed item names what was bought")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError(f"a quantity is a whole count, not a {type(self.quantity).__name__}")
        if self.quantity < 1:
            raise ValueError(f"a line of {self.item_id} is for at least one of the thing")
        if not isinstance(self.unit_price, Money):
            raise TypeError(f"a unit price is Money, not a {type(self.unit_price).__name__}")

    @property
    def amount(self) -> Money:
        return self.unit_price * self.quantity

    def as_claim(self) -> dict[str, Any]:
        return {
            "id": self.item_id,
            "quantity": self.quantity,
            "unit_price": str(self.unit_price.amount),
        }


@dataclass(frozen=True)
class AgreedCharge:
    """Something charged that is not goods -- express delivery, say -- and its amount.

    The amount only. What it cost the Desk to provide is on the offer that produced this
    and in the trail entry beside it, and it is not in a document the buyer holds.
    """

    label: str
    amount: Money

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("an agreed charge is named")
        if not isinstance(self.amount, Money):
            raise TypeError(f"a charge amount is Money, not a {type(self.amount).__name__}")

    def as_claim(self) -> dict[str, Any]:
        return {"label": self.label, "amount": str(self.amount.amount)}


@dataclass(frozen=True)
class Checkout:
    """The merchant-signed payload: everything that was agreed, and nothing else.

    ``terms`` is a plain mapping of strings rather than a type from the negotiation,
    and that is on purpose. A mandate is a document; the words in it come from whatever
    settled the deal, and this module has no business knowing that the Desk's levers are
    called what they are called. Ticket 21 may add a lever and nothing here changes.
    """

    open_checkout: str
    currency: str
    items: tuple[AgreedItem, ...]
    charges: tuple[AgreedCharge, ...]
    terms: Mapping[str, str]
    agreed_at: datetime

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError(
                "a closed mandate with no items agrees to nothing, and a document that "
                "agrees to nothing is not evidence of a deal"
            )
        priced: tuple[Money, ...] = (
            *(item.unit_price for item in self.items),
            *(charge.amount for charge in self.charges),
        )
        for amount in priced:
            if amount.currency != self.currency:
                raise ValueError(
                    f"this checkout is in {self.currency} and part of it is in "
                    f"{amount.currency}; a total across two currencies is not a total"
                )

    @property
    def total(self) -> Money:
        """What the buyer pays: the goods and whatever the terms charged for."""
        running = Money(amount=Decimal(0), currency=self.currency)
        for item in self.items:
            running = running + item.amount
        for charge in self.charges:
            running = running + charge.amount
        return running

    def as_claims(self) -> dict[str, Any]:
        """The payload as it is signed. Written in a fixed order; see ``close_checkout``."""
        return {
            "merchant": MERCHANT,
            "open_checkout": self.open_checkout,
            "currency": self.currency,
            "line_items": [item.as_claim() for item in self.items],
            "charges": [charge.as_claim() for charge in self.charges],
            "terms": dict(self.terms),
            "total": str(self.total.amount),
            "agreed_at": int(self.agreed_at.timestamp()),
        }


@dataclass(frozen=True)
class ClosedCheckoutMandate:
    """A closed Checkout Mandate the Desk has verified: both layers, and their digest."""

    checkout: Checkout
    checkout_hash: MandateDigest
    issued_at: datetime | None


def close_checkout(
    checkout: Checkout, *, signed_by: DeskKeypair, issued_at: int | None = None
) -> str:
    """Sign one closed Checkout Mandate over these agreed terms.

    Two signatures, inner first. The Checkout payload is signed on its own so that its
    digest names *this* set of terms and nothing else -- which is what
    ``checkout_hash`` is for, and what a receipt will point at. Wrapping it and signing
    again would leave the terms nameable only through the envelope, and a re-issued
    envelope would rename a deal that had not changed.
    """
    checkout_jws = signed_by.sign(checkout.as_claims(), typ=CHECKOUT_TYP)
    # base64url of the compact JWS, which is what AP2's field says it holds: "the
    # base64url-encoded serialized merchant-signed JWT". Encoded again rather than
    # carried raw, so the field is opaque to anything reading the outer claims.
    encoded = base64url_encode(checkout_jws.encode("ascii")).decode("ascii")
    content: dict[str, Any] = {
        "vct": CLOSED_CHECKOUT_VCT,
        CHECKOUT_JWT_CLAIM: encoded,
        # AP2: the hash of the *field value*, under the SD-JWT's own _sd_alg.
        CHECKOUT_HASH_CLAIM: _digest(encoded),
    }
    if issued_at is not None:
        content["iat"] = issued_at
    disclosure = disclose(content)
    envelope = signed_by.sign(sd_jwt_claims(disclosure), typ=SD_JWT_TYP)
    return present(envelope, disclosure)


def read_closed_checkout(mandate: str, *, key: DeskPublicKey) -> ClosedCheckoutMandate:
    """Read one back, refusing anything the Desk cannot prove it wrote.

    Both signatures are checked against the same key, and the hash binding them is
    checked too. That last one is the part worth having: without it, the envelope's
    signature says only that the Desk signed *an* envelope, and a different Checkout
    payload could be swapped into a field the outer signature does not reach.
    """
    claims = mandate_content(verify_presentation(mandate, key).claims)

    if claims.get("vct") != CLOSED_CHECKOUT_VCT:
        raise MandateNotVerified(
            f"a closed Checkout Mandate carries vct {CLOSED_CHECKOUT_VCT!r}; this one "
            f"carries {claims.get('vct')!r}"
        )

    encoded = claims.get(CHECKOUT_JWT_CLAIM)
    if not isinstance(encoded, str) or not encoded:
        raise MandateNotVerified(f"the mandate carries no {CHECKOUT_JWT_CLAIM}")

    claimed_hash = claims.get(CHECKOUT_HASH_CLAIM)
    if claimed_hash != _digest(encoded):
        raise MandateNotVerified(
            f"the mandate's {CHECKOUT_HASH_CLAIM} does not name the {CHECKOUT_JWT_CLAIM} "
            f"it carries, so the two layers are not one document"
        )

    checkout = _read_checkout(_decode(encoded), key=key)
    return ClosedCheckoutMandate(
        checkout=checkout,
        checkout_hash=MandateDigest(algorithm=DEFAULT_SD_ALG, value=_digest(encoded)),
        issued_at=epoch(claims.get("iat"), "iat"),
    )


def _read_checkout(checkout_jws: str, *, key: DeskPublicKey) -> Checkout:
    """The inner merchant-signed payload, verified and read back into its parts."""
    # A bare JWS rather than a presentation, so it is verified through the same routine
    # with an empty disclosure list appended -- the shape ``verify_presentation`` reads.
    claims = verify_presentation(f"{checkout_jws}~", key).claims

    agreed_at = epoch(claims.get("agreed_at"), "agreed_at")
    if agreed_at is None:
        raise MandateNotVerified("the checkout payload does not say when it was agreed")

    currency = claims.get("currency")
    if not isinstance(currency, str):
        raise MandateNotVerified("the checkout payload names no currency")

    checkout = Checkout(
        open_checkout=_text(claims.get("open_checkout"), "open_checkout"),
        currency=currency,
        items=tuple(_item(claim, currency) for claim in _list(claims.get("line_items"))),
        charges=tuple(_charge(claim, currency) for claim in _list(claims.get("charges"))),
        terms={
            str(name): str(value) for name, value in _mapping(claims.get("terms")).items()
        },
        agreed_at=agreed_at,
    )

    stated = claims.get("total")
    if stated != str(checkout.total.amount):
        raise MandateNotVerified(
            f"the checkout payload totals {stated!r} and its parts come to "
            f"{checkout.total.amount}; a total that is not the sum is not a total"
        )
    return checkout


def _digest(value: str) -> str:
    return base64url_encode(hashlib.sha256(value.encode("ascii")).digest()).decode("ascii")


def _decode(encoded: str) -> str:
    try:
        return base64url_decode(encoded).decode("ascii")
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise MandateNotVerified(f"the {CHECKOUT_JWT_CLAIM} is not base64url: {exc}") from exc


def _list(claimed: Any) -> Sequence[Any]:
    if not isinstance(claimed, Sequence) or isinstance(claimed, str | bytes):
        raise MandateNotVerified("a checkout payload's line items and charges are lists")
    return claimed


def _mapping(claimed: Any) -> Mapping[str, Any]:
    if not isinstance(claimed, Mapping):
        raise MandateNotVerified("a checkout payload's terms are an object")
    return claimed


def _text(claimed: Any, name: str) -> str:
    if not isinstance(claimed, str):
        raise MandateNotVerified(f"a checkout payload's {name} is a string")
    return claimed


def _money(claimed: Any, currency: str, name: str) -> Money:
    if not isinstance(claimed, str | int | Decimal):
        raise MandateNotVerified(f"a checkout payload's {name} is an amount")
    try:
        return Money.of(claimed, currency)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MandateNotVerified(f"a checkout payload's {name} is not an amount: {exc}") from exc


def _item(claimed: Any, currency: str) -> AgreedItem:
    if not isinstance(claimed, Mapping):
        raise MandateNotVerified("a checkout payload's line item is an object")
    quantity = claimed.get("quantity")
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise MandateNotVerified("a checkout payload's quantity is a whole count")
    return AgreedItem(
        item_id=_text(claimed.get("id"), "line item id"),
        quantity=quantity,
        unit_price=_money(claimed.get("unit_price"), currency, "unit price"),
    )


def _charge(claimed: Any, currency: str) -> AgreedCharge:
    if not isinstance(claimed, Mapping):
        raise MandateNotVerified("a checkout payload's charge is an object")
    return AgreedCharge(
        label=_text(claimed.get("label"), "charge label"),
        amount=_money(claimed.get("amount"), currency, "charge amount"),
    )

"""The closed Checkout Mandate: what was agreed, in a document that outlives the room.

The open mandate said what a human was willing to buy. This says what was actually
settled on, and it has to survive being read later by somebody who was not there --
which is the whole of what these tests check. Both signatures hold, the two layers name
each other, and nothing that was agreed comes back different.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

import pytest
from jwt.utils import base64url_encode

from desk.identity import DeskKeypair
from desk.mandate import (
    CHECKOUT_HASH_CLAIM,
    CHECKOUT_JWT_CLAIM,
    CHECKOUT_TYP,
    CLOSED_CHECKOUT_VCT,
    OPEN_CHECKOUT_VCT,
    SD_JWT_TYP,
    AgreedCharge,
    AgreedItem,
    Checkout,
    MandateNotVerified,
    close_checkout,
    disclose,
    present,
    read_closed_checkout,
    read_mandate_header,
    sd_jwt_claims,
    verify_sd_jwt,
)
from desk.spend import Money
from world.wallet import PrincipalKeypair

AGREED_AT = datetime.fromtimestamp(1_800_000_000, tz=UTC)

#: Stands in for the digest of the open Checkout Mandate a deal was negotiated under.
#: Its value does not matter here; that it survives the round trip does.
OPEN_DIGEST = "wbLBDL8Jh0jaKX7HDvSTlPETzu8VGCE3ExEfUlIRSp8"


@pytest.fixture
def desk_key() -> DeskKeypair:
    return DeskKeypair.generate()


def a_checkout(*, charges: tuple[AgreedCharge, ...] = ()) -> Checkout:
    return Checkout(
        open_checkout=OPEN_DIGEST,
        currency="INR",
        items=(
            AgreedItem(
                item_id="SKU-COFFEE-1KG", quantity=2, unit_price=Money.of("809.10", "INR")
            ),
        ),
        charges=charges,
        terms={"delivery": "standard", "payment": "prepaid"},
        agreed_at=AGREED_AT,
    )


def test_what_was_agreed_reads_back_exactly(desk_key: DeskKeypair) -> None:
    express = AgreedCharge(label="express delivery", amount=Money.of("400.00", "INR"))
    signed = close_checkout(a_checkout(charges=(express,)), signed_by=desk_key)

    read = read_closed_checkout(signed, key=desk_key.public_key)

    assert read.checkout.items[0].item_id == "SKU-COFFEE-1KG"
    assert read.checkout.items[0].quantity == 2
    assert read.checkout.items[0].unit_price == Money.of("809.10", "INR")
    assert read.checkout.charges == (express,)
    assert read.checkout.terms == {"delivery": "standard", "payment": "prepaid"}
    assert read.checkout.open_checkout == OPEN_DIGEST
    assert read.checkout.agreed_at == AGREED_AT


def test_the_total_is_the_goods_and_the_charges(desk_key: DeskKeypair) -> None:
    express = AgreedCharge(label="express", amount=Money.of("400.00", "INR"))

    signed = close_checkout(a_checkout(charges=(express,)), signed_by=desk_key)

    read = read_closed_checkout(signed, key=desk_key.public_key)
    assert read.checkout.total == Money.of("2018.20", "INR")


def test_it_is_a_closed_mandate_and_says_so(desk_key: DeskKeypair) -> None:
    """``vct`` is how a reader tells the two variants apart before reading anything else."""
    signed = close_checkout(a_checkout(), signed_by=desk_key)

    content = verify_sd_jwt(signed, desk_key.public_key)["delegate_payload"][0]

    assert content["vct"] == CLOSED_CHECKOUT_VCT
    assert content["vct"] != OPEN_CHECKOUT_VCT


def test_the_inner_document_is_named_by_its_own_digest(desk_key: DeskKeypair) -> None:
    """Two signatures, and the inner one is what a receipt will eventually point at."""
    signed = close_checkout(a_checkout(), signed_by=desk_key)

    read = read_closed_checkout(signed, key=desk_key.public_key)

    assert read.checkout_hash.algorithm == "sha-256"
    assert read.checkout_hash.value


def test_it_carries_an_issue_time_when_one_is_given(desk_key: DeskKeypair) -> None:
    issued = int(time.time())

    read = read_closed_checkout(
        close_checkout(a_checkout(), signed_by=desk_key, issued_at=issued),
        key=desk_key.public_key,
    )

    assert read.issued_at is not None
    assert int(read.issued_at.timestamp()) == issued


def test_the_signature_names_the_desk(desk_key: DeskKeypair) -> None:
    header = read_mandate_header(close_checkout(a_checkout(), signed_by=desk_key))

    assert header.claimed_principal_id == "desk"
    assert header.algorithm == "ES256"


def test_another_desks_key_does_not_read_it(desk_key: DeskKeypair) -> None:
    signed = close_checkout(a_checkout(), signed_by=desk_key)

    with pytest.raises(MandateNotVerified, match="does not verify"):
        read_closed_checkout(signed, key=DeskKeypair.generate().public_key)


def test_a_principals_key_does_not_read_it(desk_key: DeskKeypair) -> None:
    """A merchant's commitment must never be readable as a human's authorisation."""
    signed = close_checkout(a_checkout(), signed_by=desk_key)
    wallet = PrincipalKeypair.generate()

    with pytest.raises(MandateNotVerified):
        read_closed_checkout(signed, key=wallet.public_key)  # type: ignore[arg-type]


def test_two_layers_that_name_different_documents_are_refused(desk_key: DeskKeypair) -> None:
    """The hash binding the two layers is what this test is about.

    Rewriting a disclosure is already refused a layer down -- RFC 9901 has the envelope
    signature cover its digest, so an altered one is material the claims make no room
    for. What that does *not* catch is an envelope assembled around a hash of one
    document and a ``checkout_jwt`` of another, both signed and both valid on their own.
    Reading has to notice that the two do not name each other.
    """
    agreed = a_checkout()
    giveaway = Checkout(
        open_checkout=OPEN_DIGEST,
        currency="INR",
        items=(
            AgreedItem(item_id="SKU-LAPTOP-14", quantity=1, unit_price=Money.of("1.00", "INR")),
        ),
        charges=(),
        terms={},
        agreed_at=AGREED_AT,
    )

    mismatched = _closed_mandate(
        {
            "vct": CLOSED_CHECKOUT_VCT,
            CHECKOUT_JWT_CLAIM: _encoded(desk_key.sign(giveaway.as_claims(), typ=CHECKOUT_TYP)),
            CHECKOUT_HASH_CLAIM: _sha256(
                _encoded(desk_key.sign(agreed.as_claims(), typ=CHECKOUT_TYP))
            ),
        },
        desk_key,
    )

    with pytest.raises(MandateNotVerified, match="not one document"):
        read_closed_checkout(mismatched, key=desk_key.public_key)


def test_a_total_that_is_not_the_sum_is_refused(desk_key: DeskKeypair) -> None:
    """The one number a reader could otherwise take on trust.

    Every signature here holds; what is wrong is the arithmetic inside them. Reading
    recomputes the total from the parts rather than believing the number written down,
    which is the same move ``margin_on`` makes about a floor.
    """
    claims = dict(a_checkout().as_claims())
    claims["total"] = "1.00"
    inner = _encoded(desk_key.sign(claims, typ=CHECKOUT_TYP))

    signed = _closed_mandate(
        {
            "vct": CLOSED_CHECKOUT_VCT,
            CHECKOUT_JWT_CLAIM: inner,
            CHECKOUT_HASH_CLAIM: _sha256(inner),
        },
        desk_key,
    )

    with pytest.raises(MandateNotVerified, match="is not a total"):
        read_closed_checkout(signed, key=desk_key.public_key)


def test_an_open_mandate_is_not_read_as_a_closed_one(desk_key: DeskKeypair) -> None:
    """``vct`` is checked rather than assumed, the way check 2 checks the open variant."""
    inner = _encoded(desk_key.sign(a_checkout().as_claims(), typ=CHECKOUT_TYP))

    wrong_kind = _closed_mandate(
        {
            "vct": OPEN_CHECKOUT_VCT,
            CHECKOUT_JWT_CLAIM: inner,
            CHECKOUT_HASH_CLAIM: _sha256(inner),
        },
        desk_key,
    )

    with pytest.raises(MandateNotVerified, match="carries vct"):
        read_closed_checkout(wrong_kind, key=desk_key.public_key)


def test_a_checkout_with_no_items_is_not_a_deal() -> None:
    with pytest.raises(ValueError, match="agrees to nothing"):
        Checkout(
            open_checkout=OPEN_DIGEST,
            currency="INR",
            items=(),
            charges=(),
            terms={},
            agreed_at=AGREED_AT,
        )


def test_a_checkout_refuses_a_part_in_another_currency() -> None:
    with pytest.raises(ValueError, match="not a total"):
        Checkout(
            open_checkout=OPEN_DIGEST,
            currency="INR",
            items=(
                AgreedItem(
                    item_id="SKU-COFFEE-1KG", quantity=1, unit_price=Money.of("9.99", "USD")
                ),
            ),
            charges=(),
            terms={},
            agreed_at=AGREED_AT,
        )


def _encoded(compact_jws: str) -> str:
    return base64url_encode(compact_jws.encode("ascii")).decode("ascii")


def _sha256(value: str) -> str:
    return base64url_encode(hashlib.sha256(value.encode("ascii")).digest()).decode("ascii")


def _closed_mandate(content: dict[str, str], key: DeskKeypair) -> str:
    """A closed mandate assembled by hand: every signature valid, the contents ours.

    ``close_checkout`` cannot build a mandate whose layers disagree, which is the point
    of it. Reaching past it here is how the reader's own checks get exercised.
    """
    disclosure = disclose(content)
    return present(key.sign(sd_jwt_claims(disclosure), typ=SD_JWT_TYP), disclosure)

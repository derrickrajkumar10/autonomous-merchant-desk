"""The Desk's own key: the one private half that belongs inside ``desk/``.

Two properties, and the second is the one worth having. The Desk can sign something a
third party checks against nothing but its published key, which is what a closed
Checkout Mandate needs and what FR-7.3 will ask of a receipt. And the Desk's key is not
a principal's -- same curve, same scheme, and still no path by which one stands in for
the other, because a signature is only ever checked against the key its reader chose.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP384R1, generate_private_key

from desk.identity import DESK_KEY_ID, DeskKeypair, DeskPublicKey, PrincipalPublicKey
from desk.mandate import MandateNotVerified, read_mandate_header, verify_sd_jwt
from world.wallet import PrincipalKeypair

#: The ``typ`` an SD-JWT carries. A bare signature plus a trailing separator is a
#: presentation with no disclosures, which is the smallest thing this verifier reads.
TYP = "example+sd-jwt"


def _presented(signed: str) -> str:
    return f"{signed}~"


def test_the_desk_signs_something_its_published_key_verifies() -> None:
    desk = DeskKeypair.generate()

    signed = desk.sign({"agreed": "yes"}, typ=TYP)

    assert verify_sd_jwt(_presented(signed), desk.public_key) == {"agreed": "yes"}


def test_a_signed_artefact_names_the_desk_and_its_scheme() -> None:
    """A reader can tell who signed before it has fetched anybody's key."""
    header = read_mandate_header(_presented(DeskKeypair.generate().sign({}, typ=TYP)))

    assert header.claimed_principal_id == DESK_KEY_ID
    assert header.algorithm == "ES256"


def test_the_desks_signature_does_not_verify_against_a_principals_key() -> None:
    desk = DeskKeypair.generate()
    wallet = PrincipalKeypair.generate()

    with pytest.raises(MandateNotVerified, match="does not verify"):
        verify_sd_jwt(_presented(desk.sign({"agreed": "yes"}, typ=TYP)), wallet.public_key)


def test_a_principals_signature_does_not_verify_against_the_desks_key() -> None:
    """The other direction, which is the one that would matter if it were possible.

    A mandate the Desk signed for itself must never be readable as a human's
    authorisation. Nothing resolves a principal to the Desk's key, and this is the
    arithmetic underneath that: the signatures simply do not check out.
    """
    desk = DeskKeypair.generate()
    wallet = PrincipalKeypair.generate()
    mandate = wallet.sign_mandate_content({"vct": "anything"}, principal_id="principal-asha")

    with pytest.raises(MandateNotVerified, match="does not verify"):
        verify_sd_jwt(mandate, desk.public_key)


def test_the_desks_key_is_not_a_principals_key() -> None:
    """Same bytes on the wire, and two types that no assignment crosses between."""
    desk = DeskKeypair.generate().public_key

    assert DeskPublicKey.from_jwk(desk.jwk()) == desk
    assert not isinstance(desk, PrincipalPublicKey)
    # The ignore is the assertion. mypy calls this comparison non-overlapping, which is
    # exactly the separation the module docstring claims: the same sixty-five bytes read
    # as one type are not the other, and nothing assigns between them.
    same_bytes = PrincipalPublicKey.from_base64url(desk.base64url())
    assert same_bytes != desk  # type: ignore[comparison-overlap]


def test_the_desks_key_refuses_a_key_on_another_curve() -> None:
    with pytest.raises(ValueError, match="a desk key is P-256"):
        DeskPublicKey.from_public_key(generate_private_key(SECP384R1()).public_key())


def test_the_desks_key_refuses_a_point_that_is_not_on_the_curve() -> None:
    off_curve = b"\x04" + bytes(64)

    with pytest.raises(ValueError, match="not a point on P-256"):
        DeskPublicKey(off_curve)

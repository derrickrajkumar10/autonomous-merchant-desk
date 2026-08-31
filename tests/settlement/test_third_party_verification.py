"""Verifying a receipt without any of our code, which is the whole claim.

FR-7.3 is not "the Desk can check its own signatures". It is that a **stranger** --
a judge, an auditor, the buyer's principal -- can hold a receipt and the Desk's
published public key and satisfy themselves, with an off-the-shelf library, without
access to our systems and without trusting our account of anything.

So every test in this file verifies with **jwcrypto**, a JOSE implementation that is
not ours and that we do not sign with. ``read_receipt`` is deliberately never called
here. Checking our own signatures with our own verifier would show only that the two
halves agree with each other, which is not the claim being made.

The published key arrives the way a stranger would receive it: as a JWK, out of
``DeskKeyVault.published()``. Nothing here imports a private key or a signing routine.
"""

from __future__ import annotations

import base64
import json

import pytest
from jwcrypto.jwk import JWK, JWKSet
from jwcrypto.jws import JWS, InvalidJWSSignature

from desk.identity import DESK_RECEIPT_KEY_ID, AgentIdentity, DeskKeyVault
from desk.negotiation import Desk
from desk.settlement import RECEIPT_TYP, Settlement
from desk.spine import TrustSpine
from tests.settlement.conftest import closed_deal, settle
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

AGREED = "1500.00"


def a_receipt(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> str:
    """One settled deal's signed receipt, and nothing else about it."""
    deal = closed_deal(spine, selling, wallet, agent, identity)
    settled = settle(settlement, deal, identity)
    assert settled.receipt is not None
    return settled.receipt.signed


def published(vault: DeskKeyVault) -> JWK:
    """The Desk's receipt key as a stranger's library takes it: an RFC 8037 JWK."""
    return JWK(**vault.published().receipt.jwk())


def test_a_stranger_verifies_a_receipt_with_a_standard_jose_library(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The acceptance criterion, with somebody else's implementation of JOSE.

    Reading the claims out of ``jws.payload`` rather than out of a ``Receipt`` matters:
    what a stranger gets is the bytes the signature covers, and everything they need has
    to be in there.
    """
    signed = a_receipt(spine, selling, settlement, wallet, agent, identity)

    jws = JWS()
    jws.deserialize(signed)
    jws.verify(published(vault))

    assert jws.jose_header["alg"] == "EdDSA"
    assert jws.jose_header["typ"] == RECEIPT_TYP

    claims = json.loads(jws.payload)
    assert claims["iss"] == "desk"
    assert claims["charged"] == {"amount": AGREED, "currency": "INR"}
    assert claims["agreed"]["total"] == AGREED
    assert set(claims["mandate_chain"]) == {"open_checkout", "open_payment", "closed_checkout"}
    assert claims["rail"]["charge_id"] == "pay_TESTMODE0000001"
    assert isinstance(claims["iat"], int)


def test_a_stranger_finds_the_right_key_by_the_kid_on_the_receipt(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The whole standard flow, with nothing handed over out of band.

    A stranger has two things: the receipt, and the Desk's published key set. They read
    the ``kid`` off the header, look it up, and verify. That only works if the name the
    set publishes a key under is the name that key actually signs with -- so this is the
    test that would catch a key set which looked tidy and answered nothing.

    The Desk signs two kinds of document under two different keys, which is exactly the
    situation ``kid`` exists for.
    """
    signed = a_receipt(spine, selling, settlement, wallet, agent, identity)
    keys = JWKSet.from_json(json.dumps(vault.published().as_jwks()))

    jws = JWS()
    jws.deserialize(signed)
    found = keys.get_key(jws.jose_header["kid"])

    assert found is not None, jws.jose_header["kid"]
    assert jws.jose_header["kid"] == DESK_RECEIPT_KEY_ID
    jws.verify(found)
    assert json.loads(jws.payload)["charged"]["amount"] == AGREED

    # And the other key in the set is the mandate key, which must not verify a receipt.
    mandate_key = keys.get_key("desk")
    assert mandate_key is not None
    assert mandate_key["kty"] == "EC"


def test_an_altered_receipt_does_not_verify(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """The amount is changed to ten times itself and the signature stops holding.

    The tamper is done on the wire format, the way somebody with a receipt and a text
    editor would do it -- not by re-signing different claims, which would prove nothing.
    """
    signed = a_receipt(spine, selling, settlement, wallet, agent, identity)
    header, payload, signature = signed.split(".")

    claims = json.loads(_b64url_decode(payload))
    assert claims["charged"]["amount"] == AGREED
    claims["charged"]["amount"] = "150.00"
    forged = f"{header}.{_b64url_encode(json.dumps(claims).encode())}.{signature}"

    jws = JWS()
    jws.deserialize(forged)
    with pytest.raises(InvalidJWSSignature):
        jws.verify(published(vault))


def test_a_receipt_does_not_verify_against_a_different_key(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Anyone can generate an Ed25519 key. What matters is whose key it verifies under.

    Without this, "the receipt verifies" would be a claim about the algorithm rather
    than about the Desk.
    """
    signed = a_receipt(spine, selling, settlement, wallet, agent, identity)

    jws = JWS()
    jws.deserialize(signed)
    with pytest.raises(InvalidJWSSignature):
        jws.verify(JWK.generate(kty="OKP", crv="Ed25519"))


def test_the_agreed_terms_a_stranger_reads_are_the_ones_the_desk_signed(
    spine: TrustSpine,
    selling: Desk,
    settlement: Settlement,
    vault: DeskKeyVault,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """A receipt whose terms had to be fetched from us would not be evidence about us.

    Everything a dispute turns on -- the items, their prices, the levers that were
    traded, the total -- is inside the signed bytes.
    """
    signed = a_receipt(spine, selling, settlement, wallet, agent, identity)

    jws = JWS()
    jws.deserialize(signed)
    jws.verify(published(vault))
    agreed = json.loads(jws.payload)["agreed"]

    assert agreed["merchant"] == "desk"
    assert agreed["line_items"] == [
        {"id": "SKU-COFFEE-1KG", "quantity": 2, "unit_price": "750.00"}
    ]
    assert agreed["terms"] == {"delivery": "standard", "payment": "on_delivery"}
    assert agreed["currency"] == "INR"
    assert agreed["total"] == AGREED


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

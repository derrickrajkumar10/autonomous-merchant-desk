"""The SD-JWT layer: what a holder may do to a mandate between signing and presenting.

Selective disclosure is a real capability, not a formality -- the holder is *supposed*
to be able to drop parts of a signed mandate and have it still verify. That makes the
boundary between "withheld" and "altered" load-bearing, and these tests sit on it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

import pytest

from desk.identity import PrincipalPublicKey
from desk.mandate import MandateNotVerified, read_mandate_header, verify_sd_jwt
from tests.mandate.conftest import PRINCIPAL_ID, line_items
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(segment: str) -> Any:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def _array_disclosure(value: Any) -> str:
    """One RFC 9901 array-element disclosure, encoded the way the format hashes it."""
    return _b64u(
        json.dumps(["saltsaltsaltsalt" + str(id(value)), value], separators=(", ", ": ")).encode()
    )


def _sha256(disclosure: str) -> str:
    return _b64u(hashlib.sha256(disclosure.encode("ascii")).digest())


def _sign_claims(wallet: PrincipalKeypair, claims: dict[str, Any]) -> str:
    """An issuer JWS over claims exactly as given.

    The wallet always nests a mandate under ``delegate_payload`` and always digests
    with sha-256, which is right for a wallet and useless for testing what happens
    when an issuer does neither.
    """
    from jwt.api_jws import encode as jws_encode

    return jws_encode(
        json.dumps(claims).encode("utf-8"),
        wallet._signing_key,  # noqa: SLF001 - standing in for an issuer that is not ours
        algorithm="ES256",
        headers={"kid": PRINCIPAL_ID, "typ": "example+sd-jwt"},
    )


def _mandate(wallet: PrincipalKeypair, agent: AgentKeypair) -> str:
    now = int(time.time())
    return wallet.sign_open_checkout_mandate(
        principal_id=PRINCIPAL_ID,
        agent_key=agent.public_key,
        constraints=[line_items()],
        issued_at=now,
        expires_at=now + 3600,
    )


def test_the_claims_come_back_with_the_disclosure_resolved_into_place(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    claims = verify_sd_jwt(_mandate(wallet, agent), wallet.public_key)

    content = claims["delegate_payload"][0]
    assert content["vct"] == "mandate.checkout.open.1"
    assert content["constraints"] == [line_items()]
    assert content["cnf"] == {"jwk": agent.public_key.jwk()}


def test_a_mandate_verified_against_another_key_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    somebody_else = PrincipalKeypair.generate()

    with pytest.raises(MandateNotVerified, match="does not verify"):
        verify_sd_jwt(_mandate(wallet, agent), somebody_else.public_key)


def test_a_disclosure_the_signed_claims_make_no_room_for_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The hole this closes: stapling material onto a mandate nobody signed a place for.

    The issuer JWS is untouched, so the signature still verifies. What does not verify
    is the mandate as a whole, because a disclosure arrived that no digest asked for.
    """
    mandate = _mandate(wallet, agent)
    stowaway = _b64u(json.dumps(["saltsaltsaltsalt", {"smuggled": True}]).encode())

    with pytest.raises(MandateNotVerified, match="makes? no room for"):
        verify_sd_jwt(f"{mandate}{stowaway}~", wallet.public_key)


def test_an_altered_disclosure_is_refused(wallet: PrincipalKeypair, agent: AgentKeypair) -> None:
    """Raise the quantity in the disclosure and its digest stops matching.

    The mandate then reads as one whose only claim was withheld -- and a mandate with
    no ``vct`` at all is refused a layer up. Here it is refused sooner: the altered
    disclosure is one nothing asked for.
    """
    issuer_jws, disclosure, _ = _mandate(wallet, agent).split("~")
    salt, content = _decode(disclosure)
    content["constraints"][0]["items"][0]["quantity"] = 9_999
    altered = _b64u(json.dumps([salt, content], separators=(", ", ": ")).encode())

    with pytest.raises(MandateNotVerified):
        verify_sd_jwt(f"{issuer_jws}~{altered}~", wallet.public_key)


def test_a_withheld_disclosure_is_refused(wallet: PrincipalKeypair, agent: AgentKeypair) -> None:
    """The format permits this. The Desk does not, and that is a deliberate narrowing.

    Nothing is altered here -- the holder simply sends less. RFC 9901 says the result
    still verifies, and it does. But a verifier that has to evaluate every constraint
    cannot accept a mandate with parts missing, so this one is refused.
    """
    issuer_jws = _mandate(wallet, agent).split("~")[0]

    with pytest.raises(MandateNotVerified, match="were withheld"):
        verify_sd_jwt(f"{issuer_jws}~", wallet.public_key)


def test_withholding_one_constraint_cannot_widen_a_mandate(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The attack the rule above exists to stop, spelled out.

    A mandate authorising coffee *from one merchant* is disclosed per constraint, the
    way AP2's SDK discloses arrays. Drop the merchant constraint's disclosure and what
    is left still carries the principal's signature, still has line items, and no
    longer says where the coffee may be bought -- so check 3 would evaluate a strictly
    weaker mandate than the human signed.
    """
    only_us = {"type": "checkout.allowed_merchants", "allowed": [{"id": "stitchai"}]}
    disclosures = [_array_disclosure(line_items()), _array_disclosure(only_us)]
    content = {
        "vct": "mandate.checkout.open.1",
        "constraints": [{"...": _sha256(each)} for each in disclosures],
        "cnf": {"jwk": agent.public_key.jwk()},
        "exp": int(time.time()) + 3600,
    }
    outer = _array_disclosure(content)
    signed = _sign_claims(
        wallet, {"delegate_payload": [{"...": _sha256(outer)}], "_sd_alg": "sha-256"}
    )

    whole = f"{signed}~{outer}~{disclosures[0]}~{disclosures[1]}~"
    assert verify_sd_jwt(whole, wallet.public_key)["delegate_payload"][0]["constraints"] == [
        line_items(),
        only_us,
    ]

    narrowed = f"{signed}~{outer}~{disclosures[0]}~"
    with pytest.raises(MandateNotVerified, match="were withheld"):
        verify_sd_jwt(narrowed, wallet.public_key)


def test_a_disclosure_that_is_not_ascii_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """Base64url is ASCII, and this runs after the signature has already verified.

    Left to raise ``UnicodeEncodeError`` it would escape check 2 entirely, which
    catches only refusals -- leaving no trail entry that the mandate was ever
    presented.
    """
    with pytest.raises(MandateNotVerified, match="not base64url"):
        verify_sd_jwt(f"{_mandate(wallet, agent)}é~", wallet.public_key)


def test_the_same_disclosure_sent_twice_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    issuer_jws, disclosure, _ = _mandate(wallet, agent).split("~")

    with pytest.raises(MandateNotVerified, match="same disclosure twice"):
        verify_sd_jwt(f"{issuer_jws}~{disclosure}~{disclosure}~", wallet.public_key)


def test_a_digest_algorithm_the_desk_does_not_implement_is_refused(
    wallet: PrincipalKeypair,
) -> None:
    """Never a silent fall back to the default, which would resolve nothing quietly.

    A verifier that shrugged and hashed with sha-256 anyway would find that no
    disclosure matched any digest, and read a fully disclosed mandate as one whose
    every claim had been withheld.
    """
    signed = _sign_claims(wallet, {"delegate_payload": [], "_sd_alg": "sha3-256"})

    with pytest.raises(MandateNotVerified, match="does not implement"):
        verify_sd_jwt(f"{signed}~", wallet.public_key)


def test_a_mandate_signed_with_the_wrong_algorithm_is_refused(
    agent: AgentKeypair,
) -> None:
    """Ed25519 is right for an agent request and wrong for a mandate (ADR-0002)."""
    from jwt.api_jws import encode as jws_encode

    claims = json.dumps({"delegate_payload": [], "_sd_alg": "sha-256"}).encode()
    signed = jws_encode(
        claims,
        AgentKeypair.generate()._signing_key,  # noqa: SLF001 - the red team would do this
        algorithm="EdDSA",
        headers={"kid": PRINCIPAL_ID, "typ": "example+sd-jwt"},
    )

    with pytest.raises(MandateNotVerified, match="mandates are signed ES256"):
        verify_sd_jwt(f"{signed}~", PrincipalKeypair.generate().public_key)


def test_something_that_is_not_an_sd_jwt_is_refused() -> None:
    key = PrincipalKeypair.generate().public_key

    with pytest.raises(MandateNotVerified, match="no disclosure separator"):
        verify_sd_jwt("just.a.jwt", key)
    with pytest.raises(MandateNotVerified, match="no mandate was presented"):
        verify_sd_jwt("   ", key)
    with pytest.raises(MandateNotVerified, match="no issuer JWS"):
        verify_sd_jwt("~disclosure~", key)


def test_a_presentation_the_desk_does_not_read_yet_says_so(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """A conformant AP2 presentation the Desk cannot follow yet is told which, and why.

    Both shapes end in a JWT rather than a disclosure. Left unrecognised they were
    refused for "not readable" -- true of a disclosure, misleading about a mandate that
    is perfectly well formed and simply one ticket ahead of us.
    """
    mandate = _mandate(wallet, agent)
    key_bound = mandate + "eyJhbGciOiJFUzI1NiJ9.eyJub25jZSI6Ing"

    with pytest.raises(MandateNotVerified, match="key-binding JWT"):
        verify_sd_jwt(key_bound, wallet.public_key)
    with pytest.raises(MandateNotVerified, match="delegation chain"):
        verify_sd_jwt(f"{mandate}~{mandate}", wallet.public_key)


def test_the_signer_hint_is_read_without_being_believed(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """What the mandate says about itself, available as evidence and nothing more."""
    hint = read_mandate_header(_mandate(wallet, agent))

    assert hint.claimed_principal_id == PRINCIPAL_ID
    assert hint.algorithm == "ES256"
    assert hint.typ == "example+sd-jwt"


def test_a_principal_key_is_p256_and_an_agent_key_is_not(agent: AgentKeypair) -> None:
    """The two roles differ by scheme now, so neither can stand in for the other."""
    with pytest.raises(ValueError, match="P-256 point"):
        PrincipalPublicKey(agent.public_key.material)
    with pytest.raises(ValueError, match="kty EC, crv P-256"):
        PrincipalPublicKey.from_jwk(agent.public_key.jwk())


def test_an_object_property_disclosure_is_resolved(wallet: PrincipalKeypair) -> None:
    """The other RFC 9901 shape: ``_sd`` digests over ``[salt, name, value]``.

    Our wallet does not emit these -- it discloses one array element -- but AP2's SDK
    can, and a mandate the Desk cannot read is a mandate it wrongly refuses.
    """
    disclosure = _b64u(
        json.dumps(
            ["saltsaltsaltsalt", "vct", "mandate.checkout.open.1"], separators=(", ", ": ")
        ).encode()
    )
    digest = _b64u(hashlib.sha256(disclosure.encode("ascii")).digest())
    signed = _sign_claims(wallet, {"_sd": [digest], "_sd_alg": "sha-256"})

    claims = verify_sd_jwt(f"{signed}~{disclosure}~", wallet.public_key)

    assert claims == {"vct": "mandate.checkout.open.1"}

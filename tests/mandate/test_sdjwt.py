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
from desk.mandate import (
    MandateNotVerified,
    digest_of,
    read_mandate_header,
    sd_hash_of,
    split_presentation,
    verify_presentation,
    verify_sd_jwt,
)
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


def test_a_key_binding_hop_is_set_aside_rather_than_read(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """Check 2 reads the issuer's signature; the hop after it is check 4's to read.

    The hop is not a disclosure and must not be treated as one -- material the signed
    claims make no room for is refused, and refusing a conformant presentation for
    carrying its proof of possession would make key binding unusable. It is also not
    verified here: this layer has no idea whose key it should be signed by.
    """
    mandate = _mandate(wallet, agent)
    key_bound = mandate + "eyJhbGciOiJFZERTQSJ9.eyJub25jZSI6Ing.c2ln"

    assert verify_sd_jwt(key_bound, wallet.public_key) == verify_sd_jwt(mandate, wallet.public_key)


def test_the_digest_naming_a_mandate_does_not_move_when_a_hop_is_attached(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The two digests answer two questions, and only one of them is per-presentation.

    ``digest_of`` names the mandate, which is what AP2 pairs by and what the spend
    accumulator is keyed by. If it moved when a hop was appended, an agent would get a
    fresh ceiling for every presentation -- so it is taken over the issuer JWS, which a
    hop does not touch. ``sd_hash_of`` is the one that must move, because binding a hop
    to the exact bytes it was made over is its whole job.
    """
    mandate = _mandate(wallet, agent)
    key_bound = mandate + "eyJhbGciOiJFZERTQSJ9.eyJub25jZSI6Ing.c2ln"

    assert digest_of(key_bound) == digest_of(mandate)
    assert sd_hash_of(key_bound) == sd_hash_of(mandate)
    assert sd_hash_of(mandate) != digest_of(mandate)


def test_a_delegation_chain_says_which_shape_the_desk_does_not_read(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """A conformant AP2 chain is told what the Desk cannot follow, rather than mis-parsed.

    Left unrecognised it was refused for "not readable" -- true of a disclosure, and
    misleading about a presentation that is perfectly well formed.
    """
    mandate = _mandate(wallet, agent)

    with pytest.raises(MandateNotVerified, match="delegation chain"):
        verify_sd_jwt(f"{mandate}~{mandate}", wallet.public_key)


def test_a_presentation_split_where_rfc_9901_splits_one(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """Ending in the separator or not is the whole rule, and it is the whole rule twice.

    Without a hop the trailing segment is empty and there is nothing to mistake for one.
    With a hop, everything up to and including the last separator is what ``sd_hash``
    covers -- so the split has to put the separator on the SD-JWT side of the cut.
    """
    mandate = _mandate(wallet, agent)

    plain = split_presentation(mandate)
    assert plain.sd_jwt == mandate
    assert plain.key_binding_jwt is None

    bound = split_presentation(mandate + "a.b.c")
    assert bound.sd_jwt == mandate
    assert bound.key_binding_jwt == "a.b.c"


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


def test_re_ordering_the_disclosures_does_not_change_the_mandates_digest(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The digest names the mandate, not the order its parts arrived in.

    Disclosures are a set, and which order they go on the wire in is the holder's to
    choose. A digest taken over the whole presentation would therefore differ between
    two presentations of *one signed mandate* whose parts were swapped -- and since the
    Desk keys a mandate's accumulated spend by that digest, each ordering would come
    with a fresh ceiling. That is a double spend, ``n!`` times over, on exactly the
    multi-disclosure mandates AP2's own SDK emits.

    Both orderings below verify to identical claims. They must therefore be one mandate
    to the accumulator as well.
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

    one = verify_presentation(
        f"{signed}~{outer}~{disclosures[0]}~{disclosures[1]}~", wallet.public_key
    )
    swapped = verify_presentation(
        f"{signed}~{outer}~{disclosures[1]}~{disclosures[0]}~", wallet.public_key
    )

    assert one.claims == swapped.claims
    assert one.digest == swapped.digest


def test_two_mandates_the_principal_signed_separately_have_different_digests(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The other half. A digest that collapsed onto the signed part too far would key
    two genuinely separate authorisations to one accumulator row, and the second would
    inherit the first's spending."""
    first = _mandate(wallet, agent)
    second = _mandate(wallet, agent)

    assert digest_of(first) != digest_of(second)

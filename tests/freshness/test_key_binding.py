"""Reading a key-binding JWT: the shapes that are refused, and the sentence each gets.

Check 4 folds all of these into one reason code, so the sentence is the only thing that
tells them apart in the trail. That makes the sentences worth testing rather than
merely the raising.
"""

from __future__ import annotations

import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from jwt.api_jws import encode as jws_encode
from jwt.utils import base64url_encode

from desk.freshness import MAX_CLAIM_CHARS, NotFresh, read_key_binding
from desk.identity import AgentPublicKey
from desk.mandate import sd_hash_of
from tests.freshness.conftest import DESK
from tests.mandate.conftest import a_mandate
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair


def _hop(
    agent: AgentKeypair,
    sd_jwt: str,
    *,
    typ: str = "kb+jwt",
    drop: str | None = None,
    **claims: object,
) -> str:
    """A hop with whatever claims a test wants, honest ones by default.

    Reaches past ``AgentKeypair.present`` on purpose: an honest agent has no way to
    produce a hop with no ``aud``, and these are the presentations that arrive anyway.
    """
    payload: dict[str, object] = {
        "nonce": "n",
        "aud": DESK,
        "iat": int(time.time()),
        "sd_hash": sd_hash_of(sd_jwt).value,
    } | claims
    if drop is not None:
        payload.pop(drop)
    body = json.dumps(payload)
    return f"{sd_jwt}{agent.sign(body.encode('utf-8'), agent_id='agent-under-test', typ=typ)}"


def _read(presentation: str, key: AgentPublicKey) -> None:
    read_key_binding(presentation, endorsed_key=key, algorithm="sha-256")


def test_an_honest_hop_reads_back_as_what_was_signed(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    mandate = a_mandate(wallet, agent)
    presented = agent.present(mandate, audience=DESK, nonce="n-1", issued_at=1_700_000_000)

    binding = read_key_binding(presented, endorsed_key=agent.public_key, algorithm="sha-256")

    assert binding.nonce == "n-1"
    assert binding.audience == DESK
    assert binding.issued_at.timestamp() == 1_700_000_000
    assert binding.binds == sd_hash_of(mandate).value
    assert binding.evidence()["nonce"] == "n-1"


@pytest.mark.parametrize(
    ("claim", "expected"),
    [("nonce", "carries no nonce"), ("aud", "carries no aud"), ("sd_hash", "carries no sd_hash")],
)
def test_a_claim_the_hop_may_not_leave_out(
    wallet: PrincipalKeypair, agent: AgentKeypair, claim: str, expected: str
) -> None:
    """Absent is refused, never defaulted.

    A hop with no ``aud`` is not a hop addressed to everyone, and a hop with no
    ``nonce`` is not one the Desk may honour once.
    """
    mandate = a_mandate(wallet, agent)

    with pytest.raises(NotFresh, match=expected):
        _read(_hop(agent, mandate, drop=claim), agent.public_key)


def test_an_iat_that_is_not_a_timestamp_is_malformed_rather_than_ancient(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """``bool`` is an ``int`` in Python, and ``iat: true`` would otherwise read as 1970.

    Refused as stale, which is a true verdict reached for a false reason -- and the
    sentence in the trail would say the agent's clock was wrong when it was not.
    """
    mandate = a_mandate(wallet, agent)

    with pytest.raises(NotFresh, match="must be a Unix epoch second"):
        _read(_hop(agent, mandate, iat=True), agent.public_key)
    with pytest.raises(NotFresh, match="must be a Unix epoch second"):
        _read(_hop(agent, mandate, iat="yesterday"), agent.public_key)


def test_a_hop_that_is_not_a_kb_jwt_is_named_for_what_it_is(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """AP2's ``kb+sd-jwt`` is a delegation hop or a closed mandate, not a presentation.

    A closed mandate is a negotiated deal. Reading one as proof that an *open* mandate
    is being handed over now would be reading a different artefact for a fact it does
    not carry.
    """
    mandate = a_mandate(wallet, agent)

    with pytest.raises(NotFresh, match="not a kb\\+jwt"):
        _read(_hop(agent, mandate, typ="kb+sd-jwt"), agent.public_key)


def test_a_hop_signed_under_the_wrong_algorithm_says_which(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The algorithm is named in the refusal, so a wrong-scheme path is visible.

    AP2 advertises ES256 for key-binding JWTs and ours are EdDSA, because the key a hop
    proves possession of is the agent's Ed25519 key (ADR-0002's known exception). An
    ES256 hop is therefore a thing a conformant stranger might send, and it deserves a
    sentence rather than "signature verification failed".
    """
    mandate = a_mandate(wallet, agent)
    signed = jws_encode(
        b'{"nonce":"n"}',
        generate_private_key(SECP256R1()),
        algorithm="ES256",
        headers={"typ": "kb+jwt"},
    )

    with pytest.raises(NotFresh, match="names 'ES256'"):
        _read(f"{mandate}{signed}", agent.public_key)


def test_something_that_is_not_a_jws_at_all_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    mandate = a_mandate(wallet, agent)

    with pytest.raises(NotFresh, match="not a readable JWS"):
        _read(f"{mandate}not-a-jwt", agent.public_key)


def test_a_payload_that_is_not_a_set_of_claims_is_refused(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """The hop's payload is a JWS body, so it is bytes until something insists otherwise."""
    mandate = a_mandate(wallet, agent)
    signed = agent.sign(b"[1, 2, 3]", agent_id="agent-under-test", typ="kb+jwt")

    with pytest.raises(NotFresh, match="not a set of claims"):
        _read(f"{mandate}{signed}", agent.public_key)


def test_a_claim_the_desk_would_have_to_store_is_bounded(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """An authenticated agent must not be able to grow the trail by asking politely.

    The nonce is kept for ever so it can be refused next time, and all three claims are
    written into hash-chained entries on refusal paths as well as on the pass. Unbounded,
    that is a megabyte per request in two places that never shrink -- available to anyone
    who has registered a key, which costs nothing.
    """
    mandate = a_mandate(wallet, agent)

    assert _hop(agent, mandate, nonce="n" * MAX_CLAIM_CHARS)
    with pytest.raises(NotFresh, match="the Desk stores"):
        _read(_hop(agent, mandate, nonce="n" * (MAX_CLAIM_CHARS + 1)), agent.public_key)
    with pytest.raises(NotFresh, match="the Desk stores"):
        _read(_hop(agent, mandate, aud="a" * (MAX_CLAIM_CHARS + 1)), agent.public_key)


def test_the_sd_hash_is_taken_over_the_disclosures_and_not_only_the_signature(
    wallet: PrincipalKeypair, agent: AgentKeypair
) -> None:
    """Reordering the disclosures of one mandate produces a different presentation.

    That is the difference between ``sd_hash_of`` and ``digest_of``, and it is the
    property that makes a hop bind the bytes that arrived rather than the credential
    they came from.
    """
    mandate = a_mandate(wallet, agent)
    tampered = mandate + base64url_encode(b'["salt", "extra"]').decode("ascii") + "~"

    assert sd_hash_of(tampered) != sd_hash_of(mandate)

    with pytest.raises(NotFresh, match="different presentation"):
        _read(tampered + _hop(agent, mandate).rpartition("~")[2], agent.public_key)

"""The key-binding JWT: a second signature, over this presentation, made just now.

A mandate proves a human authorised something. It proves nothing about *when* it was
handed over, and that gap is the replay hole: a mandate copied off the wire is still a
valid mandate, still bound to the same agent, still inside its expiry. Presenting it
again is not forgery. It is repetition, and nothing inside the credential can tell the
two apart.

RFC 9901's answer is to make the holder sign something as well. Appended to the
presentation, after the last separator, is a small JWT signed by the key the mandate's
``cnf`` claim endorses. Four claims in it do the work:

- ``sd_hash`` -- the digest of the presentation it is attached to, so the hop cannot be
  lifted onto a different one.
- ``aud`` -- who it was made for, so a proof addressed to another verifier is not ours.
- ``iat`` -- when it was made, which is what the freshness window is compared against.
- ``nonce`` -- a value that tells this presentation apart from the next one, and which
  the Desk refuses to honour twice.

This module reads that hop and nothing else. It knows nothing about which nonces have
been seen (``nonces.py``) and nothing about what counts as fresh (``policy.py``); it
turns a string into four verified claims, or a sentence saying why it could not.

**The hop is signed EdDSA, not ES256.** AP2's OpenID4VP request advertises
``"kb-jwt_alg_values": ["ES256"]``, but the key a hop proves possession of is whichever
key the mandate's ``cnf`` endorses, and ours are Ed25519 agent keys (ADR-0011). This is
ADR-0002's known exception seen from the other side rather than a second exception: the
issuer signs ES256 so that a stranger's library can read the mandate, and the holder
signs Ed25519 because that is the key the holder has. The cost is real and worth
naming -- AP2's own ``kb_sd_jwt`` helper cannot produce our hop. Nor could it have
consumed our ``cnf``, so the interoperability being traded away here was already spent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jwt.api_jws import decode as jws_decode
from jwt.api_jws import get_unverified_header
from jwt.exceptions import PyJWTError

from desk.identity import AgentPublicKey
from desk.mandate import MandateNotVerified, sd_hash_of, split_presentation

#: Ed25519, for the reason the module docstring gives.
KEY_BINDING_ALG = "EdDSA"

#: The longest a claim the Desk stores or writes to the trail may be. AP2 is silent on
#: nonce length and RFC 9901's examples are a couple of dozen characters, so this is
#: ours. Without it an authenticated agent can hand the Desk a megabyte of nonce on every
#: request and grow both the nonce store and the hash-chained trail without bound -- the
#: same reason ``mandate_spend`` constrains the shape of what it keys rows by.
MAX_CLAIM_CHARS = 256

#: What RFC 9901 section 4.3 stamps on a key-binding JWT. AP2's ``kb+sd-jwt`` is a
#: different artefact -- a delegation hop, or a closed mandate -- and is refused here
#: rather than read, because a closed mandate is a negotiated deal and not a proof that
#: an open one is being presented now.
KEY_BINDING_TYP = "kb+jwt"


class NotFresh(ValueError):
    """A presentation whose freshness the Desk could not establish, and why.

    One exception rather than a hierarchy, mirroring ``RequestNotVerified`` and
    ``MandateNotVerified``: every refusal raised here leaves check 4 under
    ``request_stale`` and differs only in the sentence written beside it.
    """


@dataclass(frozen=True)
class KeyBinding:
    """One verified hop: what the holder signed, now that the signature has verified.

    Holds no verdict. Whether the nonce has been seen and whether ``issued_at`` is
    inside the window are check 4's questions; this is the thing it asks them about.
    """

    nonce: str
    audience: str
    issued_at: datetime
    binds: str

    def evidence(self) -> dict[str, Any]:
        """The hop as trail evidence.

        The nonce is written down deliberately. It is spent the moment it is honoured,
        so recording it costs nothing -- and it is the whole of the evidence behind a
        ``nonce_replayed`` refusal, which is an assertion without it.
        """
        return {
            "nonce": self.nonce,
            "audience": self.audience,
            "key_binding_issued_at": self.issued_at.isoformat(),
            "binds_presentation": self.binds,
        }


def read_key_binding(
    presentation: str, *, endorsed_key: AgentPublicKey, algorithm: str
) -> KeyBinding:
    """The hop on this presentation, verified against the key it has to be signed by.

    ``endorsed_key`` is the key the mandate's ``cnf`` claim names -- reached through the
    Desk's own registry rather than through the credential, because check 2 has already
    proven the two are the same key. Reading it out of the mandate again would be
    reading one fact from the less trustworthy of the two places it is written.

    ``algorithm`` is the mandate's own ``_sd_alg``, which is what RFC 9901 takes
    ``sd_hash`` under. It comes from the presentation check 2 verified rather than from
    the hop, so a holder cannot name the hash its own digest was computed under.
    """
    hop = split_presentation(presentation).key_binding_jwt
    if hop is None:
        raise NotFresh(
            "the presentation carries no key-binding JWT, so nothing in it says when it "
            "was handed over or who it was handed to; a mandate on its own is as true "
            "the tenth time it is presented as the first"
        )

    _reject_wrong_shape(hop)

    try:
        payload = jws_decode(hop, key=endorsed_key.verifier(), algorithms=[KEY_BINDING_ALG])
    except PyJWTError as exc:
        raise NotFresh(
            f"the key-binding JWT does not verify against the key the mandate endorses: {exc}"
        ) from exc

    claims = _claims(payload)
    binding = KeyBinding(
        nonce=_required(claims, "nonce"),
        audience=_required(claims, "aud"),
        issued_at=_issued_at(claims),
        binds=_required(claims, "sd_hash"),
    )

    try:
        presented = sd_hash_of(presentation, algorithm=algorithm)
    except MandateNotVerified as exc:  # pragma: no cover - check 2 verified this algorithm
        raise NotFresh(str(exc)) from exc
    if binding.binds != presented.value:
        raise NotFresh(
            "the key-binding JWT was made over a different presentation to the one it "
            "arrived on, so it proves the agent held its key at some other moment and "
            "says nothing about this one"
        )
    return binding


def _reject_wrong_shape(hop: str) -> None:
    """The header, before the signature. Nothing here is trusted; it chooses no key.

    Refusing the algorithm by name rather than leaving it to ``jws_decode`` keeps the
    sentence in the trail specific: "names 'ES256'" is a fact worth reading a month
    later, and "signature verification failed" is not.
    """
    try:
        header = get_unverified_header(hop)
    except PyJWTError as exc:
        raise NotFresh(f"the key-binding JWT is not a readable JWS: {exc}") from exc

    algorithm = header.get("alg")
    if algorithm != KEY_BINDING_ALG:
        raise NotFresh(
            f"a key-binding JWT proves possession of the agent's Ed25519 key and is "
            f"signed {KEY_BINDING_ALG}; this one names {algorithm!r}"
        )
    typ = header.get("typ")
    if typ != KEY_BINDING_TYP:
        raise NotFresh(f"the signature is over a {typ!r}, not a {KEY_BINDING_TYP}")


def _claims(payload: bytes) -> dict[str, Any]:
    try:
        claims = json.loads(payload)
    except ValueError as exc:
        raise NotFresh(f"the key-binding JWT's payload is not JSON: {exc}") from exc
    if not isinstance(claims, dict):
        raise NotFresh("the key-binding JWT's payload is not a set of claims")
    return claims


def _required(claims: dict[str, Any], name: str) -> str:
    """One claim the hop may not leave out, insisting it is a bounded, non-empty string.

    Absent is refused rather than defaulted, for all three. A hop with no ``aud`` is not
    a hop addressed to everyone, and a hop with no ``nonce`` is not a hop the Desk may
    honour once. AP2 makes both mandatory at every hop, and RFC 9901 requires
    ``sd_hash``.

    Bounded because all three are written down. The nonce is stored so that it can be
    refused next time, and every one of them lands in a trail entry -- on the refusal
    paths as much as on the pass -- so an unbounded claim is unbounded growth in two
    places that are meant to be permanent.
    """
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise NotFresh(f"the key-binding JWT carries no {name}, which it may not leave out")
    if len(value) > MAX_CLAIM_CHARS:
        raise NotFresh(
            f"the key-binding JWT's {name} is {len(value)} characters; the Desk stores "
            f"what a hop carries, so it honours one up to {MAX_CLAIM_CHARS}"
        )
    return value


def _issued_at(claims: dict[str, Any]) -> datetime:
    """The hop's ``iat``, as an instant.

    ``bool`` is a subclass of ``int`` and would otherwise read as 1970, which would be
    refused as stale for the wrong reason -- a hop claiming ``iat: true`` is malformed,
    not old.
    """
    claimed = claims.get("iat")
    if isinstance(claimed, bool) or not isinstance(claimed, int):
        raise NotFresh("the key-binding JWT's iat must be a Unix epoch second")
    try:
        return datetime.fromtimestamp(claimed, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise NotFresh(f"the key-binding JWT's iat is not a usable instant: {exc}") from exc

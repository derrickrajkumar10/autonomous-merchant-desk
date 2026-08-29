"""The wire format of a signed agent request, and how the Desk reads one.

JWS compact serialisation over Ed25519, as ADR-0002 requires: a standard wrapper a
stranger's library already speaks, which is what makes "a judge writes their own
buyer agent and it transacts" (FR-11.1) a claim rather than a hope.

The request body travels **inside** the signature. There is no envelope around it and
nothing beside it, so there is nothing about a request that a signature does not
cover. The claimed identity rides in the JWS ``kid`` header, which is the ordinary
JOSE place for it.

Signing and verification are an off-the-shelf library's work, not ours (ADR-0011).
This module is the format and the refusal reasons; the cryptography is PyJWT's.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from jwt.api_jws import decode as jws_decode
from jwt.api_jws import get_unverified_header
from jwt.exceptions import PyJWTError

from desk.identity.keys import AgentPublicKey

#: Ed25519 for agent requests. The ES256 exception in ADR-0002 is the Checkout JWT
#: alone; do not over-apply it. A request naming any other algorithm is refused, and
#: the algorithm it named is written to the trail so the path is visible, not silent.
AGENT_REQUEST_ALG = "EdDSA"

#: What the signature says it is over. A signature on a receipt is not a signature on
#: a request, however valid it is, so the type is inside the protected header.
AGENT_REQUEST_TYP = "stitchai-request+jws"


class RequestNotVerified(ValueError):
    """A request the Desk will not accept, carrying the reason it will state.

    One exception rather than a hierarchy, because every one of these refusals leaves
    under the same reason code (``agent_signature_invalid``) and differs only in the
    reasoning written beside it. Keeping the sentence next to the condition that
    produced it is what makes the trail specific.
    """


@dataclass(frozen=True)
class RequestHeader:
    """What a request claims before anything about it has been proven."""

    claimed_agent_id: str | None
    algorithm: str | None
    typ: str | None


def read_header(request: str) -> RequestHeader:
    """The unverified claims, so the Desk knows whose key to check the signature with.

    Nothing here is trusted. It is read first only because a signature cannot be
    verified without knowing which key to verify it against.
    """
    try:
        header = get_unverified_header(request)
    except PyJWTError as exc:
        raise RequestNotVerified(f"the request is not a readable JWS: {exc}") from exc

    return RequestHeader(
        claimed_agent_id=_text(header.get("kid")),
        algorithm=_text(header.get("alg")),
        typ=_text(header.get("typ")),
    )


def verify_request(request: str, public_key: AgentPublicKey) -> dict[str, Any]:
    """The body this signature actually covers, or a refusal saying why it does not.

    Re-reads the header rather than trusting one it was handed, so that verifying is
    safe wherever it is called from.
    """
    header = read_header(request)

    if header.algorithm != AGENT_REQUEST_ALG:
        raise RequestNotVerified(
            f"agent requests are signed {AGENT_REQUEST_ALG}; this one names {header.algorithm!r}"
        )
    if header.typ != AGENT_REQUEST_TYP:
        raise RequestNotVerified(
            f"the signature is over a {header.typ!r}, not a {AGENT_REQUEST_TYP}"
        )

    try:
        payload = jws_decode(request, key=public_key.verifier(), algorithms=[AGENT_REQUEST_ALG])
    except PyJWTError as exc:
        raise RequestNotVerified(
            f"the signature does not verify against the registered public key: {exc}"
        ) from exc

    try:
        # parse_float, because a request body carries money. AP2 types an amount as a
        # JSON number, and 1000.10 read as a float is not 1000.10 -- the mandate reader
        # takes the same precaution for the same reason, and a ceiling drawn down by a
        # number nobody wrote is the kind of defect noticed after the money has moved.
        body = json.loads(payload, parse_float=Decimal)
    except ValueError as exc:
        raise RequestNotVerified(f"the signed payload is not JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise RequestNotVerified("the signed payload is not a request body")
    return body


def _text(claim: Any) -> str | None:
    """A header claim, but only if it is a string. Anything else is not a claim."""
    return claim if isinstance(claim, str) else None

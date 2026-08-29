"""A buyer agent's own keypair -- the agent's half of the agent protocol.

This is what an external agent does before it can talk to the Desk: generate a
keypair, register the public half, sign every request with the private half. It lives
in ``world/`` because a buyer agent is environment rather than product, and because
the private key must never be somewhere ``desk/`` could reach it.

Our tests enter through here for the same reason a judge's agent would: it is the
only surface an external agent has.

Two things get signed with this key and they are not the same thing. A **request** is
what the agent is asking for. A **key-binding JWT** is the agent saying *I am handing
this mandate over, to you, now* -- the proof of possession RFC 9901 appends to a
presentation, and what check 4 reads. A mandate without one is a mandate that is as
true the tenth time it is presented as the first.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Mapping
from typing import Any, Self

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jwt.api_jws import encode as jws_encode

from desk.freshness import KEY_BINDING_TYP
from desk.identity import AGENT_REQUEST_ALG, AGENT_REQUEST_TYP, AgentPublicKey
from desk.mandate import sd_hash_of, split_presentation

#: Sixteen bytes, which is what RFC 9901's examples salt a disclosure with and is far
#: past any birthday bound that matters here. The specification sets no length: it
#: assumes the *verifier* issues the nonce as a challenge, and until the Desk has a
#: request/response boundary to issue one over (ticket 30), the holder chooses it.
NONCE_BYTES = 16


class AgentKeypair:
    """An agent's Ed25519 keypair. The Desk only ever sees ``public_key``."""

    def __init__(self, signing_key: Ed25519PrivateKey) -> None:
        self._signing_key = signing_key

    @classmethod
    def generate(cls) -> Self:
        return cls(Ed25519PrivateKey.generate())

    @property
    def public_key(self) -> AgentPublicKey:
        """The half that is registered, and the only half that ever leaves this object."""
        return AgentPublicKey.from_public_key(self._signing_key.public_key())

    def sign_request(self, body: Mapping[str, Any], *, agent_id: str) -> str:
        """One signed request: the body, inside a JWS, under the identity claimed.

        ``agent_id`` is the identity the Desk issued at registration. It is a parameter
        rather than something this object knows, because claiming an identity and
        holding the key that proves it are exactly the two things a forged request
        separates -- and the tests need to separate them too.
        """
        return self.sign(json.dumps(body, sort_keys=True).encode("utf-8"), agent_id=agent_id)

    def sign(self, payload: bytes, *, agent_id: str, typ: str = AGENT_REQUEST_TYP) -> str:
        """The signing primitive underneath ``sign_request``.

        Signs whatever bytes it is given under whatever type it is told, which is how
        the red team and the tests produce things that are validly signed and still not
        requests. An honest agent has no reason to reach past ``sign_request``.
        """
        return jws_encode(
            payload,
            self._signing_key,
            algorithm=AGENT_REQUEST_ALG,
            headers={"kid": agent_id, "typ": typ},
        )

    def present(
        self,
        mandate: str,
        *,
        audience: str,
        nonce: str | None = None,
        issued_at: int | None = None,
        sd_alg: str = "sha-256",
        typ: str = KEY_BINDING_TYP,
    ) -> str:
        """This mandate, with a key-binding JWT appended: *handed to you, now*.

        The hop is signed over ``sd_hash`` -- the digest of the presentation as it will
        travel, disclosures included -- which is what stops it being lifted onto a
        different one. So it has to be computed after the disclosures are fixed and
        cannot be prepared in advance, which is the point.

        ``nonce`` defaults to a fresh random value, because that is what an honest agent
        does. It is a parameter so that the red team and the tests can present the same
        one twice, which is the replay check 4 exists to refuse.

        ``sd_alg`` is the hash the mandate's own ``_sd_alg`` names, since RFC 9901 takes
        ``sd_hash`` under it. It defaults to what our wallet signs under; an agent
        holding a mandate from some other issuer reads it out of that mandate.
        """
        sd_jwt = split_presentation(mandate).sd_jwt
        claims = {
            "nonce": secrets.token_urlsafe(NONCE_BYTES) if nonce is None else nonce,
            "aud": audience,
            "iat": int(time.time()) if issued_at is None else issued_at,
            "sd_hash": sd_hash_of(sd_jwt, algorithm=sd_alg).value,
        }
        hop = jws_encode(
            json.dumps(claims, separators=(",", ":")).encode("utf-8"),
            self._signing_key,
            algorithm=AGENT_REQUEST_ALG,
            headers={"typ": typ},
        )
        return f"{sd_jwt}{hop}"

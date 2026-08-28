"""A buyer agent's own keypair -- the client side of the agent protocol.

This is what an external agent does before it can talk to the Desk: generate a
keypair, register the public half, sign every request with the private half. It lives
in ``world/`` because a buyer agent is environment rather than product, and because
the private key must never be somewhere ``desk/`` could reach it.

Our tests enter through here for the same reason a judge's agent would: it is the
only surface an external agent has.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Self

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jwt.api_jws import encode as jws_encode

from desk.identity import AGENT_REQUEST_ALG, AGENT_REQUEST_TYP, AgentPublicKey


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
        """The signing primitive underneath ``sign_request``, for anything else signed."""
        return jws_encode(
            payload,
            self._signing_key,
            algorithm=AGENT_REQUEST_ALG,
            headers={"kid": agent_id, "typ": typ},
        )

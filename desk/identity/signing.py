"""The Desk's own keypair -- the one private key that belongs inside ``desk/``.

Everything else in this subsystem is about believing somebody else. This is the one
place the Desk speaks for itself: when a negotiation closes, the Desk signs a statement
of the terms it agreed to, and that statement has to be checkable later by a party that
was not in the conversation -- a buyer disputing what was agreed, a settlement step
binding a receipt to it (ticket 09), a panel reading the trail.

**Why the Desk holds a private key when the principal's lives in a separate process.**
The rule in CONTEXT.md section 7 is about *authority*: the principal's key says a human
authorised a purchase, so an agent holding it could authorise purchases for that human.
The Desk's key says nothing about authority. It says "the Desk agreed to this", which
the Desk is the only party entitled to say and is saying anyway. A stolen Desk key
lets an attacker forge the Desk's own commitments, which is bad and is an ordinary
server-key problem -- not the delegation hole the wallet exists to close.

``ES256``, not Ed25519. The artefact this signs is an AP2 mandate, and AP2's SDK can
neither produce nor consume Ed25519 (ADR-0002's known exception, the same one the
wallet lives under). The Desk therefore runs two schemes: ``EdDSA`` when it verifies an
agent's request, ``ES256`` when it signs a mandate.

Generated per process here, and that is a real limit worth naming: restart the Desk and
yesterday's closed mandates no longer verify against today's published key. Ticket 09
needs the key to outlive a process, because a receipt is verifiable "given the Desk's
public key" (FR-7.3) and a key nobody can look up is not one. Persisting it is that
ticket's, and doing it here would be storing a key with nothing yet reading it back.

    from desk.identity import DeskKeypair

    desk_key = DeskKeypair.generate()
    closed = sign_closed_checkout_mandate(..., signed_by=desk_key)
    verify_presentation(closed, desk_key.public_key)
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Self

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from jwt.api_jws import encode as jws_encode

from desk.identity.keys import DeskPublicKey

#: What the Desk calls itself in a ``kid`` header, so a reader of a signed artefact can
#: tell at a glance which party signed it without first fetching a key.
DESK_KEY_ID = "desk"

#: The one signature scheme AP2 mandates travel under. See the module docstring.
DESK_ALG = "ES256"


class DeskKeypair:
    """The Desk's ECDSA P-256 keypair. Only ``public_key`` ever leaves the process."""

    def __init__(self, signing_key: Any) -> None:
        self._signing_key = signing_key

    @classmethod
    def generate(cls) -> Self:
        return cls(generate_private_key(SECP256R1()))

    @property
    def public_key(self) -> DeskPublicKey:
        """The half the Desk publishes, and the only half anything outside sees."""
        return DeskPublicKey.from_public_key(self._signing_key.public_key())

    def sign(self, claims: Mapping[str, Any], *, typ: str) -> str:
        """One compact JWS over these claims, signed ``ES256`` under the Desk's key.

        The signing primitive and nothing more. What claims belong in a closed Checkout
        Mandate is ``desk/mandate/closed.py``'s question, and keeping it there is what
        stops this module growing an opinion about commerce.

        Separators are tight and the members are written in the order the caller wrote
        them, because the digest that names a signed artefact is taken over these exact
        bytes -- a re-encoding elsewhere would produce a different name for the same
        mandate.
        """
        return jws_encode(
            json.dumps(dict(claims), separators=(",", ":")).encode("utf-8"),
            self._signing_key,
            algorithm=DESK_ALG,
            headers={"kid": DESK_KEY_ID, "typ": typ},
        )

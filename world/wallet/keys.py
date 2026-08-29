"""The principal's keypair, and how a mandate gets signed.

This is the human's half of the protocol: the key that says *yes, I authorise this*.
It lives in ``world/`` because it is the human edge rather than the merchant, and the
one rule that matters about it is in CONTEXT.md section 7 -- **the principal's private
key must never be in the buyer agent's process.** If it ever is, FR-1.3 and FR-1.4
become theatre and a panel will find it immediately.

What this module is not yet: the wallet as a *product*. Ticket 25 makes it a separate
process that renders a prompt playback and signs nothing without an explicit human
saying yes. Here it is a keypair and a signing routine, which is the least that lets
check 2 be tested against a real mandate rather than a fixture. The separation of
processes is asserted by construction in the meantime: nothing in ``desk/`` and
nothing in ``world/agents/`` imports this module.

Signing produces an **SD-JWT** (RFC 9901), because that is what AP2 v0.2 secures
mandates with. The claims are hidden behind a digest and sent alongside as a
*disclosure*, which is the format's whole point: a holder may drop any disclosure and
what remains still verifies. The wallet discloses everything it signs -- deciding what
to withhold is the holder's choice to make, not the issuer's.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping, Sequence
from typing import Any, Self

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from jwt.api_jws import encode as jws_encode
from jwt.utils import base64url_encode

from desk.identity import AgentPublicKey, PrincipalPublicKey
from desk.mandate import MANDATE_ALG, OPEN_CHECKOUT_VCT

#: The ``typ`` RFC 9901's own reference implementation stamps on an SD-JWT, and
#: therefore what AP2's SDK emits. Ours says the same thing so that a stranger's
#: verifier comparing against the reference finds what it expects.
SD_JWT_TYP = "example+sd-jwt"

#: Sixteen bytes of salt per disclosure, which is what RFC 9901's examples use. The
#: salt is why two disclosures of the same value do not digest alike.
SALT_BYTES = 16


class PrincipalKeypair:
    """A principal's ECDSA P-256 keypair. The Desk only ever sees ``public_key``.

    P-256 and not Ed25519 for one reason: AP2's SDK signs and verifies ``ES256`` only,
    and a mandate is the artefact a stranger's library has to read. ADR-0002 records
    the trade-off -- two schemes in the system instead of one, in exchange for the
    interoperability that is the whole reason for using a standard.
    """

    def __init__(self, signing_key: Any) -> None:
        self._signing_key = signing_key

    @classmethod
    def generate(cls) -> Self:
        return cls(generate_private_key(SECP256R1()))

    @property
    def public_key(self) -> PrincipalPublicKey:
        """The half that is enrolled, and the only half that ever leaves this object."""
        return PrincipalPublicKey.from_public_key(self._signing_key.public_key())

    def sign_open_checkout_mandate(
        self,
        *,
        principal_id: str,
        agent_key: AgentPublicKey,
        constraints: Sequence[Mapping[str, Any]],
        issued_at: int | None = None,
        expires_at: int | None = None,
    ) -> str:
        """One open Checkout Mandate: these constraints, bound to this agent's key.

        ``agent_key`` is the agent the principal is authorising, and it goes into the
        ``cnf`` claim AP2 requires. It is a parameter rather than something the wallet
        knows because binding the mandate to the *wrong* agent is precisely the attack
        check 2 exists to refuse, and the tests have to be able to do it.

        ``expires_at`` is optional because AP2 leaves ``exp`` optional, and a wallet
        that could not omit it could not produce every mandate a conformant one can.
        Omitting it in practice is a bad idea, and AP2 says so: set it to the smallest
        value that lets the agent finish the task.
        """
        content: dict[str, Any] = {
            "vct": OPEN_CHECKOUT_VCT,
            "constraints": [dict(constraint) for constraint in constraints],
            "cnf": {"jwk": agent_key.jwk()},
        }
        if issued_at is not None:
            content["iat"] = issued_at
        if expires_at is not None:
            content["exp"] = expires_at
        return self.sign_mandate_content(content, principal_id=principal_id)

    def sign_mandate_content(self, content: Mapping[str, Any], *, principal_id: str) -> str:
        """The signing primitive underneath ``sign_open_checkout_mandate``.

        Signs whatever claims it is handed, which is how the tests produce mandates
        that are validly signed and still not valid mandates -- a wrong ``vct``, a
        missing ``cnf``, no line items. An honest wallet has no reason to reach past
        the method above.
        """
        disclosure = _disclosure(content)
        claims = {
            # The claims sit one level down under ``delegate_payload``, matching what
            # AP2's SDK emits, so that a chain hop can be appended in a later ticket
            # without the shape changing underneath a verifier that already read one.
            "delegate_payload": [{"...": _digest(disclosure)}],
            "_sd_alg": "sha-256",
        }
        issuer_jws = jws_encode(
            json.dumps(claims, separators=(",", ":")).encode("utf-8"),
            self._signing_key,
            algorithm=MANDATE_ALG,
            headers={"kid": principal_id, "typ": SD_JWT_TYP},
        )
        return f"{issuer_jws}~{disclosure}~"


def _disclosure(content: Mapping[str, Any]) -> str:
    """One array-element disclosure: a fresh salt and the value, base64url encoded.

    The separators are RFC 9901's, not Python's defaults. The digest is taken over
    these exact characters, so a verifier that re-encoded the JSON would compute a
    different one -- which is why the encoded string, and not the value, is what
    travels.
    """
    salt = base64url_encode(secrets.token_bytes(SALT_BYTES)).decode("ascii")
    encoded = json.dumps([salt, dict(content)], separators=(", ", ": "))
    return base64url_encode(encoded.encode("utf-8")).decode("ascii")


def _digest(disclosure: str) -> str:
    return base64url_encode(hashlib.sha256(disclosure.encode("ascii")).digest()).decode("ascii")

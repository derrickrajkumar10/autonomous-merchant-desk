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

The mechanics of that -- salt, digest, and the shape on the wire -- are
``desk.mandate.issue``'s, shared with the one artefact the Desk signs for itself. What
stays here is the part that is the wallet's alone: the key, and what a principal's
authorisation may say.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Self

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from jwt.api_jws import encode as jws_encode

from desk.identity import AgentPublicKey, PrincipalPublicKey
from desk.mandate import (
    MANDATE_ALG,
    OPEN_CHECKOUT_VCT,
    OPEN_PAYMENT_VCT,
    PAYMENT_REFERENCE_CONSTRAINT,
    SALT_BYTES,
    SD_JWT_TYP,
    digest_of,
    disclose,
    present,
    sd_jwt_claims,
)

__all__ = ["SALT_BYTES", "SD_JWT_TYP", "PrincipalKeypair"]


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

    def sign_open_payment_mandate(
        self,
        *,
        principal_id: str,
        agent_key: AgentPublicKey,
        for_checkout: str,
        constraints: Sequence[Mapping[str, Any]] = (),
        issued_at: int | None = None,
        expires_at: int | None = None,
        execution_date: str | None = None,
    ) -> str:
        """One open Payment Mandate, paired to the Checkout Mandate it pays for.

        ``for_checkout`` is the *presented* open Checkout Mandate, not its digest. The
        wallet takes the digest itself and writes it into the ``payment.reference``
        constraint AP2 makes mandatory, because pairing the two is exactly the step a
        buyer agent must not be trusted to do: an agent that chose the reference could
        pair a generous budget with somebody else's shopping list.

        The digest is taken under sha-256, which is the ``_sd_alg`` this wallet signs
        under, satisfying AP2's rule that the hash match the SD-JWT the constraint sits
        in.

        ``constraints`` are the rest -- a ``payment.budget`` ceiling, a
        ``payment.execution_date`` window. None of them is required by the schema, and
        the wallet adds none on its own: what a principal did not authorise is not for
        their wallet to invent.
        """
        content: dict[str, Any] = {
            "vct": OPEN_PAYMENT_VCT,
            "constraints": [
                {
                    "type": PAYMENT_REFERENCE_CONSTRAINT,
                    "conditional_transaction_id": digest_of(for_checkout).value,
                },
                *(dict(constraint) for constraint in constraints),
            ],
            "cnf": {"jwk": agent_key.jwk()},
        }
        if issued_at is not None:
            content["iat"] = issued_at
        if expires_at is not None:
            content["exp"] = expires_at
        if execution_date is not None:
            content["execution_date"] = execution_date
        return self.sign_mandate_content(content, principal_id=principal_id)

    def sign_mandate_content(self, content: Mapping[str, Any], *, principal_id: str) -> str:
        """The signing primitive underneath ``sign_open_checkout_mandate``.

        Signs whatever claims it is handed, which is how the tests produce mandates
        that are validly signed and still not valid mandates -- a wrong ``vct``, a
        missing ``cnf``, no line items. An honest wallet has no reason to reach past
        the method above.
        """
        disclosure = disclose(content)
        issuer_jws = jws_encode(
            json.dumps(sd_jwt_claims(disclosure), separators=(",", ":")).encode("utf-8"),
            self._signing_key,
            algorithm=MANDATE_ALG,
            headers={"kid": principal_id, "typ": SD_JWT_TYP},
        )
        return present(issuer_jws, disclosure)

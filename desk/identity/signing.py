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

**Two keys, because the Desk signs two different things.** ``DeskKeypair`` signs
mandates, in ``ES256``, for the reason above. ``DeskReceiptKeypair`` signs receipts, in
``EdDSA``, because a receipt is not an AP2 document and never travels through AP2's
SDK -- so ADR-0002's exception does not reach it and its default of Ed25519 stands.
They are separate objects rather than one object with two methods, so that handing
something the receipt key does not also hand it the power to sign a mandate.

``generate`` makes a fresh key, which is right for a test and wrong for a running Desk:
restart it and yesterday's receipts no longer verify against today's published key,
and FR-7.3's "verifiable given the Desk's public key" would mean nothing. ``restore``
and ``secret`` are the pair that lets ``vault.py`` keep one key across restarts. They
are the only route to the private half, and nothing outside the vault calls them.

    from desk.identity import DeskKeyVault

    vault = DeskKeyVault(pool)
    closed = close_checkout(..., signed_by=vault.mandate_key())
    receipt = issue_receipt(..., signed_by=vault.receipt_key())
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Self

from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1,
    EllipticCurvePrivateKey,
    generate_private_key,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    load_der_private_key,
)
from jwt.api_jws import encode as jws_encode
from jwt.utils import base64url_decode, base64url_encode

from desk.identity.keys import DeskPublicKey, DeskReceiptPublicKey

#: What the Desk calls itself in a ``kid`` header, so a reader of a signed artefact can
#: tell at a glance which party signed it without first fetching a key.
DESK_KEY_ID = "desk"

#: And what it calls its *other* key. A ``kid`` names one key, not one party, and the
#: Desk signs under two -- so a receipt saying ``desk`` would leave a reader holding the
#: published JWK Set with two candidates and no way to choose. This is the name that set
#: publishes the receipt key under, and looking it up is the whole standard flow FR-7.3
#: is about. The mandate key keeps the bare ``desk`` it has always had, because that is
#: on artefacts already signed and an AP2 reader's.
DESK_RECEIPT_KEY_ID = "desk-receipt"

#: The one signature scheme AP2 mandates travel under. See the module docstring.
DESK_ALG = "ES256"

#: What a receipt is signed under. ADR-0002's default, which the AP2 exception does not
#: reach because a receipt is not an AP2 document.
DESK_RECEIPT_ALG = "EdDSA"


class DeskKeypair:
    """The Desk's ECDSA P-256 keypair. Only ``public_key`` ever leaves the process."""

    def __init__(self, signing_key: EllipticCurvePrivateKey) -> None:
        self._signing_key = signing_key

    @classmethod
    def generate(cls) -> Self:
        return cls(generate_private_key(SECP256R1()))

    @classmethod
    def restore(cls, secret: str) -> Self:
        """The key back from what ``secret`` stored. The vault's half of the pair."""
        restored = load_der_private_key(base64url_decode(secret), password=None)
        if not isinstance(restored, EllipticCurvePrivateKey):
            raise ValueError(
                f"the Desk's mandate key is an ECDSA P-256 key, and what was stored "
                f"is a {type(restored).__name__}"
            )
        return cls(restored)

    def secret(self) -> str:
        """The private half, base64url of its unencrypted PKCS#8 DER.

        The vault stores this and nothing else calls it. See ``DeskReceiptKeypair``
        for why it lives on the class rather than in the vault.
        """
        der = self._signing_key.private_bytes(
            encoding=Encoding.DER,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )
        return base64url_encode(der).decode("ascii")

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


class DeskReceiptKeypair:
    """The Desk's Ed25519 keypair, and the only thing that signs a receipt.

    Separate from ``DeskKeypair`` in type as well as in scheme. A receipt says money
    moved; a mandate says terms were agreed. Nothing should be able to produce one
    while holding only the authority to produce the other, and two unrelated classes
    is the cheapest way to make that a type error rather than a review comment.
    """

    def __init__(self, signing_key: Ed25519PrivateKey) -> None:
        self._signing_key = signing_key

    @classmethod
    def generate(cls) -> Self:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def restore(cls, secret: str) -> Self:
        """The key back from what ``secret`` stored. The vault's half of the pair."""
        return cls(Ed25519PrivateKey.from_private_bytes(base64url_decode(secret)))

    @property
    def public_key(self) -> DeskReceiptPublicKey:
        """The half the Desk publishes, and the only half a receipt's reader needs."""
        return DeskReceiptPublicKey.from_public_key(self._signing_key.public_key())

    def secret(self) -> str:
        """The private half, base64url of its raw thirty-two bytes.

        The vault stores this and nothing else calls it. It is on the class rather than
        in the vault so that the vault never handles a key object, only an opaque
        string it cannot accidentally sign with.
        """
        return base64url_encode(self._signing_key.private_bytes_raw()).decode("ascii")

    def sign(self, claims: Mapping[str, Any], *, typ: str) -> str:
        """One compact JWS over these claims, signed ``EdDSA`` under the Desk's key.

        Tight separators and the caller's own member order, for the reason
        ``DeskKeypair.sign`` gives: a receipt is named by the digest of these exact
        bytes, and a re-encoding elsewhere would give one receipt two names.
        """
        return jws_encode(
            json.dumps(dict(claims), separators=(",", ":")).encode("utf-8"),
            self._signing_key,
            algorithm=DESK_RECEIPT_ALG,
            headers={"kid": DESK_RECEIPT_KEY_ID, "typ": typ},
        )

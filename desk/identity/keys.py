"""Public keys, and the distinction this subsystem exists to protect.

**The principal's key authorises spending; the agent's key only proves who is
asking.** Conflating them is the mistake this whole area is built to prevent, and it
is nearly impossible to unpick once a single path has made it. So they are separate
types with no shared public base: passing one where the other is expected is a type
error at check time and a ``TypeError`` at run time, not a subtle bug in a year.

A key here is always an Ed25519 public key held as the raw thirty-two bytes JWS
carries (ADR-0002). Private halves live nowhere near this module: the agent keeps its
own, and the principal's is the wallet's alone (CONTEXT.md section 7).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Self

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jwt.utils import base64url_decode, base64url_encode

#: Raw Ed25519 public keys are thirty-two bytes; anything else is not one.
KEY_BYTES = 32

#: Agent identities are the key's thumbprint under this prefix, so an identifier is
#: recognisable on sight in a log line, a trail entry and a control-room panel.
AGENT_ID_PREFIX = "agent-"


@dataclass(frozen=True)
class _Ed25519PublicKey:
    """Shared encoding for the two key roles. Never used directly, never a parameter.

    Kept private so that no function can accept "either kind of key": a caller that
    wanted both would have to name both, which is exactly the review conversation
    that should happen if anyone ever tries.
    """

    material: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.material, bytes) or len(self.material) != KEY_BYTES:
            raise ValueError(f"an Ed25519 public key is {KEY_BYTES} bytes")

    @classmethod
    def from_base64url(cls, encoded: str) -> Self:
        """The form the key is stored and transmitted in: base64url, unpadded."""
        try:
            material = base64url_decode(encoded)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"not a base64url-encoded key: {exc}") from exc
        return cls(material)

    @classmethod
    def from_public_key(cls, key: Ed25519PublicKey) -> Self:
        return cls(key.public_bytes_raw())

    def base64url(self) -> str:
        return base64url_encode(self.material).decode("ascii")

    def jwk(self) -> dict[str, str]:
        """The key as an RFC 8037 OKP JWK, which is how a stranger would receive it."""
        return {"crv": "Ed25519", "kty": "OKP", "x": self.base64url()}

    def thumbprint(self) -> str:
        """RFC 7638 thumbprint: the canonical fingerprint of this key, and only this key."""
        canonical = json.dumps(self.jwk(), sort_keys=True, separators=(",", ":"))
        return base64url_encode(hashlib.sha256(canonical.encode("ascii")).digest()).decode("ascii")

    def verifier(self) -> Ed25519PublicKey:
        """The key as the signing library wants it."""
        return Ed25519PublicKey.from_public_bytes(self.material)


class AgentPublicKey(_Ed25519PublicKey):
    """A buyer agent's public key. Proves who is asking. Authorises nothing."""

    @property
    def agent_id(self) -> str:
        """The identity this key implies.

        Derived from the key rather than allocated, so one key is one identity for
        ever (ADR-0011). Knowable from the public key alone; it is registration, not
        derivation, that makes the identity real.
        """
        return f"{AGENT_ID_PREFIX}{self.thumbprint()}"


class PrincipalPublicKey(_Ed25519PublicKey):
    """A human principal's public key. Mandates verify against it; requests do not.

    The wallet holds the private half and nothing in ``desk/`` may ever receive it
    (CONTEXT.md section 7). Present from the first line of code so the two roles are
    never one type.
    """

"""Public keys, and the distinction this subsystem exists to protect.

**The principal's key authorises spending; the agent's key only proves who is
asking.** Conflating them is the mistake this whole area is built to prevent, and it
is nearly impossible to unpick once a single path has made it. So they are separate
types with no shared base: passing one where the other is expected is a type error at
check time and a ``TypeError`` at run time, not a subtle bug in a year.

The two roles now differ in signature scheme as well, which makes the separation
physical rather than merely nominal:

- **Agent keys are Ed25519**, held as the raw thirty-two bytes JWS carries. Agent
  requests are signed ``EdDSA`` (ADR-0002).
- **Principal keys are ECDSA P-256**, held as the sixty-five bytes of an uncompressed
  SEC1 point. Mandates are signed ``ES256``, because that is the only scheme AP2's own
  SDK can produce or consume -- see ADR-0002's known exception.

Private halves live nowhere near this module: the agent keeps its own, and the
principal's is the wallet's alone (CONTEXT.md section 7).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Self

from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, EllipticCurvePublicKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jwt.utils import base64url_decode, base64url_encode

#: Raw Ed25519 public keys are thirty-two bytes; anything else is not one.
KEY_BYTES = 32

#: An uncompressed P-256 point is an 0x04 tag and two thirty-two byte coordinates.
P256_POINT_BYTES = 65

#: Agent identities are the key's thumbprint under this prefix, so an identifier is
#: recognisable on sight in a log line, a trail entry and a control-room panel.
AGENT_ID_PREFIX = "agent-"


def _thumbprint(jwk: dict[str, str]) -> str:
    """RFC 7638 thumbprint: the canonical fingerprint of this key, and only this key.

    Sorting the members is what RFC 7638 calls for, and it happens to give the
    required lexicographic order for both key shapes this module carries.
    """
    canonical = json.dumps(jwk, sort_keys=True, separators=(",", ":"))
    return base64url_encode(hashlib.sha256(canonical.encode("ascii")).digest()).decode("ascii")


def _decode(encoded: str) -> bytes:
    try:
        return base64url_decode(encoded)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"not a base64url-encoded key: {exc}") from exc


def _member(jwk: Any, name: str) -> str:
    """One JWK member, insisting it is a string, so a malformed key stops here."""
    if not isinstance(jwk, dict):
        raise ValueError(f"a JWK is a JSON object, not {type(jwk).__name__}")
    value = jwk.get(name)
    if not isinstance(value, str):
        raise ValueError(f"a JWK needs a string {name!r} member")
    return value


@dataclass(frozen=True)
class AgentPublicKey:
    """A buyer agent's Ed25519 public key. Proves who is asking. Authorises nothing."""

    material: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.material, bytes) or len(self.material) != KEY_BYTES:
            raise ValueError(f"an Ed25519 public key is {KEY_BYTES} bytes")

    @classmethod
    def from_base64url(cls, encoded: str) -> Self:
        """The form the key is stored and transmitted in: base64url, unpadded."""
        return cls(_decode(encoded))

    @classmethod
    def from_public_key(cls, key: Ed25519PublicKey) -> Self:
        return cls(key.public_bytes_raw())

    @classmethod
    def from_jwk(cls, jwk: Any) -> Self:
        """The key as a stranger sends it, inside a mandate's ``cnf`` claim.

        Insists on the key type and curve rather than reading ``x`` from whatever
        arrives. A P-256 JWK also carries a thirty-two byte ``x``, so a reader that
        skipped this would turn one into a well-formed Ed25519 key nobody holds the
        private half of -- and then find it did not match, for the wrong reason.
        """
        if _member(jwk, "kty") != "OKP" or _member(jwk, "crv") != "Ed25519":
            raise ValueError("not an Ed25519 JWK: an agent key is kty OKP, crv Ed25519")
        return cls.from_base64url(_member(jwk, "x"))

    def base64url(self) -> str:
        return base64url_encode(self.material).decode("ascii")

    def jwk(self) -> dict[str, str]:
        """The key as an RFC 8037 OKP JWK, which is how a stranger would receive it."""
        return {"crv": "Ed25519", "kty": "OKP", "x": self.base64url()}

    def thumbprint(self) -> str:
        return _thumbprint(self.jwk())

    def verifier(self) -> Ed25519PublicKey:
        """The key as the signing library wants it."""
        return Ed25519PublicKey.from_public_bytes(self.material)

    @property
    def agent_id(self) -> str:
        """The identity this key implies.

        Derived from the key rather than allocated, so one key is one identity for
        ever (ADR-0011). Knowable from the public key alone; it is registration, not
        derivation, that makes the identity real.
        """
        return f"{AGENT_ID_PREFIX}{self.thumbprint()}"


@dataclass(frozen=True)
class PrincipalPublicKey:
    """A human principal's ECDSA P-256 public key. Mandates verify against it.

    Requests do not, and cannot: an agent request is Ed25519 and this key would refuse
    one before reaching the signature. The separation the module opens with is a
    difference of scheme now, not only of name.

    P-256 rather than Ed25519 because a mandate is the one artefact a stranger's
    library has to read. AP2's own SDK signs and verifies ``ES256`` only; handed an
    Ed25519 key it raises inside jwcrypto before any signature is attempted. See
    ADR-0002's known exception.

    The wallet holds the private half and nothing in ``desk/`` may ever receive it
    (CONTEXT.md section 7).
    """

    material: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.material, bytes) or len(self.material) != P256_POINT_BYTES:
            raise ValueError(f"an uncompressed P-256 point is {P256_POINT_BYTES} bytes")
        if self.material[0] != 0x04:
            raise ValueError("an uncompressed P-256 point starts with an 0x04 tag")
        # Two coordinates of the right length are not yet a point on the curve, and
        # nothing downstream would notice. Left unchecked, an off-curve key stores
        # cleanly -- it is the right number of base64url characters -- and then raises
        # from inside check 2, past the refusal path, on every mandate for ever after.
        # Constructing the verifier here is the cheapest place the curve is checked.
        try:
            EllipticCurvePublicKey.from_encoded_point(SECP256R1(), self.material)
        except ValueError as exc:
            raise ValueError(f"not a point on P-256: {exc}") from exc

    @classmethod
    def from_base64url(cls, encoded: str) -> Self:
        """The form the key is stored in: the uncompressed point, base64url, unpadded."""
        return cls(_decode(encoded))

    @classmethod
    def from_public_key(cls, key: EllipticCurvePublicKey) -> Self:
        numbers = key.public_numbers()
        if not isinstance(numbers.curve, SECP256R1):
            raise ValueError(f"a principal key is P-256, not {numbers.curve.name}")
        return cls(
            b"\x04" + numbers.x.to_bytes(KEY_BYTES, "big") + numbers.y.to_bytes(KEY_BYTES, "big")
        )

    @classmethod
    def from_jwk(cls, jwk: Any) -> Self:
        if _member(jwk, "kty") != "EC" or _member(jwk, "crv") != "P-256":
            raise ValueError("not a P-256 JWK: a principal key is kty EC, crv P-256")
        x = _decode(_member(jwk, "x"))
        y = _decode(_member(jwk, "y"))
        if len(x) != KEY_BYTES or len(y) != KEY_BYTES:
            raise ValueError(f"a P-256 coordinate is {KEY_BYTES} bytes")
        return cls(b"\x04" + x + y)

    def base64url(self) -> str:
        return base64url_encode(self.material).decode("ascii")

    def jwk(self) -> dict[str, str]:
        """The key as an RFC 7518 EC JWK, which is how AP2's SDK expects to receive it."""
        return {
            "crv": "P-256",
            "kty": "EC",
            "x": base64url_encode(self.material[1:33]).decode("ascii"),
            "y": base64url_encode(self.material[33:]).decode("ascii"),
        }

    def thumbprint(self) -> str:
        return _thumbprint(self.jwk())

    def verifier(self) -> EllipticCurvePublicKey:
        """The key as the signing library wants it. Cannot raise: ``__post_init__`` did this."""
        return EllipticCurvePublicKey.from_encoded_point(SECP256R1(), self.material)

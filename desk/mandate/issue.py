"""Writing an SD-JWT, which turned out to be two parties' job and not one.

``sdjwt.py`` is the verifier half and says, at the bottom, that issuing is the wallet's
alone. That was true until a negotiation had to close. The Desk now signs one artefact
of its own -- the closed Checkout Mandate that says what it agreed to -- and an AP2
mandate is an SD-JWT whoever holds the pen.

So the mechanics live here rather than in either signer: the salt, the digest, and the
two-part shape RFC 9901 puts on the wire.

    <issuer JWS>~<disclosure>~

Both signers use it and neither owns it. What differs between them is the key and the
``kid``, which is exactly the part that *should* differ -- a principal's authorisation
and a merchant's commitment are different statements, and nothing here blurs that.

Everything is disclosed. A holder may drop a disclosure and RFC 9901 will still verify
what remains, but neither of this project's issuers uses that: the Desk refuses a
mandate it cannot fully read (``sdjwt._resolve``), so issuing a partial one would only
produce something the Desk itself would turn away.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jwt.utils import base64url_encode

from desk.mandate.sdjwt import ARRAY_DIGEST_KEY, DEFAULT_SD_ALG, SD_ALG_CLAIM, SEPARATOR

#: The ``typ`` RFC 9901's own reference implementation stamps on an SD-JWT, and
#: therefore what AP2's SDK emits. Ours says the same thing so that a stranger's
#: verifier comparing against the reference finds what it expects.
SD_JWT_TYP = "example+sd-jwt"

#: Sixteen bytes of salt per disclosure, which is what RFC 9901's examples use. The
#: salt is why two disclosures of the same value do not digest alike.
SALT_BYTES = 16

#: The claim the content sits one level down under, matching what AP2's SDK emits, so
#: that a chain hop can be appended later without the shape changing underneath a
#: verifier that already read one.
DELEGATE_PAYLOAD = "delegate_payload"


@dataclass(frozen=True)
class Disclosure:
    """One disclosure as it travels, and the digest the signature will cover instead.

    ``encoded`` and not the value it came from, because the digest is taken over these
    exact characters. A verifier that re-encoded the JSON would compute a different one,
    which is why the string is what gets carried and the object is thrown away.
    """

    encoded: str
    digest: str


def disclose(content: Mapping[str, Any]) -> Disclosure:
    """One array-element disclosure: a fresh salt and the value, base64url encoded.

    The separators are RFC 9901's, not Python's defaults.
    """
    salt = base64url_encode(secrets.token_bytes(SALT_BYTES)).decode("ascii")
    encoded = base64url_encode(
        json.dumps([salt, dict(content)], separators=(", ", ": ")).encode("utf-8")
    ).decode("ascii")
    digest = base64url_encode(hashlib.sha256(encoded.encode("ascii")).digest()).decode("ascii")
    return Disclosure(encoded=encoded, digest=digest)


def sd_jwt_claims(disclosure: Disclosure) -> dict[str, Any]:
    """The claims an issuer signs: the digest, and which hash it was taken under."""
    return {
        DELEGATE_PAYLOAD: [{ARRAY_DIGEST_KEY: disclosure.digest}],
        SD_ALG_CLAIM: DEFAULT_SD_ALG,
    }


def present(issuer_jws: str, disclosure: Disclosure) -> str:
    """The signed claims and the disclosure they hid, joined the way RFC 9901 joins them.

    The trailing separator is not decoration. A presentation carrying no key-binding hop
    **ends in one**, and that is the positional rule ``split_presentation`` relies on to
    tell a hop from a disclosure before anything has been verified.
    """
    return f"{issuer_jws}{SEPARATOR}{disclosure.encoded}{SEPARATOR}"

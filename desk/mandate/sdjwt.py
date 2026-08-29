"""How the Desk reads an SD-JWT, the format AP2 v0.2 secures mandates with.

AP2 does not hand the Desk a plain signed blob. A mandate arrives as an **SD-JWT**
(RFC 9901): one issuer-signed JWS, then a run of *disclosures* -- the parts the
principal signed separately. The signature covers only digests of those parts, so in
the general format a holder may drop any of them and what remains still verifies. The
Desk does not allow that, for a reason ``_resolve`` sets out; the format still matters,
because reading a mandate at all means resolving digests back into claims.

    <issuer JWS>~<disclosure>~<disclosure>~

A presentation may also carry a trailing key-binding JWT, and AP2 may join several hops
of a delegation chain with ``~~``. Both are recognised here and refused with a sentence
saying so: reading them means reading a nonce and an audience, which is check 4.

This module is the verifier half and nothing else. It checks the issuer's signature,
resolves the disclosures the holder chose to send back into the claims they came
from, and returns the result. It does not know what a mandate is; that is
``checkout.py``, one layer up.

Four refusals here are less obvious than the rest and each closes a real hole:

- A disclosure the claims never asked for is **refused**, not ignored (RFC 9901
  section 7.3). Otherwise a holder could staple extra material onto a mandate it did
  not alter and have the signature still verify.
- A part the holder **withheld** is refused too. That one is a deliberate narrowing of
  the format rather than a reading of it, and ``_resolve`` explains why: dropping a
  constraint leaves a mandate that still verifies and authorises strictly more.
- A digest that resolves **twice** is refused, so one disclosure cannot be made to
  stand for two claims.
- A disclosure that would **overwrite** a claim already present is refused, so
  material sent later can never displace material the principal sent in the clear.

Writing SD-JWTs is not the Desk's job. The principal's wallet issues mandates
(``world/wallet/``); the Desk only ever reads them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jwt.api_jws import decode as jws_decode
from jwt.api_jws import get_unverified_header
from jwt.exceptions import PyJWTError
from jwt.utils import base64url_decode, base64url_encode

from desk.identity import PrincipalPublicKey

#: ES256 for mandates. Ed25519 everywhere else (ADR-0002): AP2's SDK is ES256-only,
#: and a mandate is the one artefact a stranger's library has to read.
MANDATE_ALG = "ES256"

#: The separator RFC 9901 joins an issuer JWS to its disclosures with.
SEPARATOR = "~"

#: AP2 joins the hops of a delegation chain with a doubled separator. The Desk reads a
#: root mandate only, so this is recognised in order to be refused clearly.
HOP_SEPARATOR = "~~"

#: The claim naming which hash the digests were taken under, and the default when it
#: is absent (RFC 9901 section 4.1.1).
SD_ALG_CLAIM = "_sd_alg"
DEFAULT_SD_ALG = "sha-256"

#: The claim carrying an object's withheld property digests, and the key an array
#: element's digest hides behind.
SD_CLAIM = "_sd"
ARRAY_DIGEST_KEY = "..."

_HASHES = {
    "sha-256": hashlib.sha256,
    "sha-384": hashlib.sha384,
    "sha-512": hashlib.sha512,
}

#: Claim names a disclosure may never introduce, because both are structural.
_RESERVED = frozenset({SD_CLAIM, ARRAY_DIGEST_KEY})


class MandateNotVerified(ValueError):
    """A mandate the Desk will not accept, carrying the reason it will state.

    One exception rather than a hierarchy, mirroring ``RequestNotVerified``: every
    refusal raised here leaves check 2 under one reason code and differs only in the
    sentence written beside it. Keeping that sentence next to the condition that
    produced it is what makes the trail specific rather than merely populated.
    """


@dataclass(frozen=True)
class MandateHeader:
    """What the issuer JWS claims about itself before anything has been proven.

    Recorded as evidence, never acted on. Which key a mandate is checked against comes
    from the principal directory, not from the mandate's own account of who signed it.
    """

    claimed_principal_id: str | None
    algorithm: str | None
    typ: str | None


def read_mandate_header(mandate: str) -> MandateHeader:
    """The unverified header of the issuer JWS. Nothing here is trusted."""
    try:
        header = get_unverified_header(_issuer_jws(mandate))
    except PyJWTError as exc:
        raise MandateNotVerified(f"the mandate is not a readable SD-JWT: {exc}") from exc

    return MandateHeader(
        claimed_principal_id=_text(header.get("kid")),
        algorithm=_text(header.get("alg")),
        typ=_text(header.get("typ")),
    )


def verify_sd_jwt(mandate: str, public_key: PrincipalPublicKey) -> dict[str, Any]:
    """The claims this mandate proves, with every disclosure resolved into place.

    Refuses rather than returns whenever the answer would be partly guessed: a
    signature that does not verify, a hash we do not implement, a disclosure that
    does not belong. The caller gets claims it can rely on or a sentence saying why
    there are none.
    """
    issuer_jws = _issuer_jws(mandate)
    header = read_mandate_header(mandate)
    if header.algorithm != MANDATE_ALG:
        raise MandateNotVerified(
            f"mandates are signed {MANDATE_ALG}; this one names {header.algorithm!r}"
        )

    try:
        signed = jws_decode(issuer_jws, key=public_key.verifier(), algorithms=[MANDATE_ALG])
    except PyJWTError as exc:
        raise MandateNotVerified(
            f"the mandate does not verify against the principal's registered key: {exc}"
        ) from exc

    try:
        claims = json.loads(signed)
    except ValueError as exc:
        raise MandateNotVerified(f"the signed mandate claims are not JSON: {exc}") from exc
    if not isinstance(claims, dict):
        raise MandateNotVerified("the signed mandate claims are not a JSON object")

    return _resolve(claims, _disclosures(mandate, _hash_for(claims.get(SD_ALG_CLAIM))))


def _issuer_jws(mandate: str) -> str:
    """The signed part: everything before the first separator."""
    if not isinstance(mandate, str) or not mandate.strip():
        raise MandateNotVerified("no mandate was presented")
    if SEPARATOR not in mandate:
        raise MandateNotVerified(
            "the mandate carries no disclosure separator, so it is not an SD-JWT"
        )
    issuer_jws = mandate.split(SEPARATOR, 1)[0]
    if not issuer_jws:
        raise MandateNotVerified("the mandate has no issuer JWS before its disclosures")

    # Two shapes RFC 9901 and AP2 both allow, and this ticket deliberately does not read.
    # Recognised so that a conformant presentation is told what the Desk cannot do yet,
    # rather than refused for failing to parse a JWT as though it were a disclosure.
    if HOP_SEPARATOR in mandate:
        raise MandateNotVerified(
            "the mandate is a delegation chain. The Desk reads the root mandate a "
            "principal signed; following key-binding hops is check 4's work and is "
            "not built yet."
        )
    if not mandate.endswith(SEPARATOR):
        raise MandateNotVerified(
            "the mandate ends in a key-binding JWT. Reading one -- and the nonce and "
            "audience it carries -- is check 4's work and is not built yet."
        )
    return issuer_jws


def _hash_for(claimed: Any) -> Any:
    """The hash the digests were taken under.

    An algorithm we do not implement is a refusal, never a fallback to the default:
    hashing the disclosures with the wrong function would resolve nothing and read as
    a holder who simply withheld everything.
    """
    if claimed is None:
        return _HASHES[DEFAULT_SD_ALG]
    if not isinstance(claimed, str) or claimed not in _HASHES:
        raise MandateNotVerified(
            f"the mandate's disclosure digests name {claimed!r}, which the Desk does "
            f"not implement; it understands {', '.join(sorted(_HASHES))}"
        )
    return _HASHES[claimed]


@dataclass(frozen=True)
class _Disclosure:
    """One withheld part, as sent and as it decodes."""

    #: An object property disclosure decodes to ``[salt, name, value]``; an array
    #: element's to ``[salt, value]``. ``name`` is ``None`` for the latter.
    name: str | None
    value: Any


def _disclosures(mandate: str, hash_alg: Any) -> dict[str, _Disclosure]:
    """The disclosures the holder sent, keyed by the digest each answers.

    Digested over the received characters rather than over anything re-encoded: RFC
    9901 takes the hash of the base64url string as it arrived, so a disclosure that
    round-trips differently still matches the digest the principal signed.
    """
    _, _, tail = mandate.partition(SEPARATOR)
    segments = [segment for segment in tail.split(SEPARATOR) if segment]

    by_digest: dict[str, _Disclosure] = {}
    for segment in segments:
        digest = _digest(segment, hash_alg)
        if digest in by_digest:
            raise MandateNotVerified("the mandate carries the same disclosure twice")
        by_digest[digest] = _parse_disclosure(segment)
    return by_digest


def _digest(segment: str, hash_alg: Any) -> str:
    """The digest a disclosure answers, taken over its characters exactly as received.

    Base64url is ASCII by construction, so a segment carrying anything else is not a
    disclosure. Refused rather than left to raise ``UnicodeEncodeError``: this runs
    after the signature has verified, and an exception check 2 does not expect would
    escape it and leave the trail with no record that the mandate was presented at all.
    """
    try:
        received = segment.encode("ascii")
    except UnicodeEncodeError:
        raise MandateNotVerified(
            "a disclosure in the mandate is not base64url, which is ASCII"
        ) from None
    return base64url_encode(hash_alg(received).digest()).decode("ascii")


def _parse_disclosure(segment: str) -> _Disclosure:
    try:
        decoded = json.loads(base64url_decode(segment))
    except (ValueError, TypeError) as exc:
        raise MandateNotVerified(f"a disclosure in the mandate is not readable: {exc}") from exc

    if not isinstance(decoded, list) or len(decoded) not in (2, 3):
        raise MandateNotVerified(
            "a disclosure is a salt with a value, or a salt with a name and a value"
        )
    if len(decoded) == 2:
        return _Disclosure(name=None, value=decoded[1])

    name = decoded[1]
    if not isinstance(name, str):
        raise MandateNotVerified("a disclosed claim name must be a string")
    if name in _RESERVED:
        raise MandateNotVerified(f"a disclosure may not introduce the structural claim {name!r}")
    return _Disclosure(name=name, value=decoded[2])


def _resolve(claims: Mapping[str, Any], available: dict[str, _Disclosure]) -> dict[str, Any]:
    """Put every disclosure back where its digest stands, and insist all of them do.

    Both halves are refusals. A *disclosure* with no digest is material nobody signed a
    place for. A *digest* with no disclosure is a part the holder chose not to send --
    and the Desk will not verify a mandate it can only partly see.

    That second rule is a deliberate narrowing of RFC 9901, and it is the one worth
    explaining. The format lets a holder drop whatever it likes, which is right for a
    holder proving one fact to one verifier. It is wrong here: the Desk's next question
    (check 3) is whether what is being asked for is inside *every* constraint the
    principal set, and a constraint it cannot see is a constraint it cannot honour.
    Withholding the disclosure for "and only from this merchant" would otherwise leave
    a mandate that still verifies and authorises strictly more.

    The cost, since it is real: an issuer scattering RFC 9901 decoy digests would have
    its mandates refused here. AP2's SDK does not use them (``add_decoy_claims``
    defaults off), and they buy nothing against a verifier that demands everything
    anyway -- but it is a trade, not a free win.
    """
    spent: set[str] = set()
    withheld: list[str] = []
    resolved = _walk(claims, available, spent, withheld)
    if not isinstance(resolved, dict):  # pragma: no cover - the input is a dict
        raise MandateNotVerified("the mandate's claims did not resolve to an object")

    unused = set(available) - spent
    if unused:
        raise MandateNotVerified(
            f"the mandate carries {len(unused)} disclosure(s) its signed claims make no "
            f"room for; nothing may be added to a mandate after it is signed"
        )
    if withheld:
        raise MandateNotVerified(
            f"{len(withheld)} part(s) of the mandate were withheld. The Desk has to "
            f"evaluate every constraint the principal set, so it verifies a mandate "
            f"only when the whole of it is disclosed."
        )
    resolved.pop(SD_ALG_CLAIM, None)
    return resolved


def _walk(
    value: Any, available: dict[str, _Disclosure], spent: set[str], withheld: list[str]
) -> Any:
    if isinstance(value, Mapping):
        return _walk_object(value, available, spent, withheld)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return _walk_array(value, available, spent, withheld)
    return value


def _walk_object(
    value: Mapping[str, Any],
    available: dict[str, _Disclosure],
    spent: set[str],
    withheld: list[str],
) -> Any:
    resolved = {
        name: _walk(child, available, spent, withheld)
        for name, child in value.items()
        if name != SD_CLAIM
    }

    for digest in _digest_list(value.get(SD_CLAIM), "_sd"):
        disclosure = available.get(digest)
        if disclosure is None:
            withheld.append(digest)
            continue
        if disclosure.name is None:
            raise MandateNotVerified(
                "a disclosure for an object property arrived without a claim name"
            )
        if disclosure.name in resolved:
            raise MandateNotVerified(
                f"a disclosure would overwrite the mandate's {disclosure.name!r} claim"
            )
        _spend(digest, spent)
        resolved[disclosure.name] = _walk(disclosure.value, available, spent, withheld)
    return resolved


def _walk_array(
    value: Sequence[Any],
    available: dict[str, _Disclosure],
    spent: set[str],
    withheld: list[str],
) -> Any:
    resolved: list[Any] = []
    for element in value:
        digest = _array_digest(element)
        if digest is None:
            resolved.append(_walk(element, available, spent, withheld))
            continue
        disclosure = available.get(digest)
        if disclosure is None:
            withheld.append(digest)
            continue
        if disclosure.name is not None:
            raise MandateNotVerified(
                f"a disclosure for the {disclosure.name!r} claim stands in an array, "
                f"where elements have no names"
            )
        _spend(digest, spent)
        resolved.append(_walk(disclosure.value, available, spent, withheld))
    return resolved


def _array_digest(element: Any) -> str | None:
    """The digest an array element hides behind, if it is a placeholder at all.

    A placeholder is an object whose only member is ``...``. An object that merely
    happens to carry that member alongside others is a value, not a placeholder, and
    substituting it would drop the rest.
    """
    if not isinstance(element, Mapping) or set(element) != {ARRAY_DIGEST_KEY}:
        return None
    digest = element[ARRAY_DIGEST_KEY]
    if not isinstance(digest, str):
        raise MandateNotVerified("an array element's digest must be a string")
    return digest


def _digest_list(claimed: Any, where: str) -> list[str]:
    if claimed is None:
        return []
    if not isinstance(claimed, list) or any(not isinstance(item, str) for item in claimed):
        raise MandateNotVerified(f"the mandate's {where} claim must be a list of digests")
    return claimed


def _spend(digest: str, spent: set[str]) -> None:
    if digest in spent:
        raise MandateNotVerified(
            "one disclosure in the mandate stands for two claims, which no honest issuer produces"
        )
    spent.add(digest)


def _text(claim: Any) -> str | None:
    """A header claim, but only if it is a string. Anything else is not a claim."""
    return claim if isinstance(claim, str) else None

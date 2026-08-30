"""How the Desk reads an SD-JWT, the format AP2 v0.2 secures mandates with.

AP2 does not hand the Desk a plain signed blob. A mandate arrives as an **SD-JWT**
(RFC 9901): one issuer-signed JWS, then a run of *disclosures* -- the parts the
principal signed separately. The signature covers only digests of those parts, so in
the general format a holder may drop any of them and what remains still verifies. The
Desk does not allow that, for a reason ``_resolve`` sets out; the format still matters,
because reading a mandate at all means resolving digests back into claims.

    <issuer JWS>~<disclosure>~<disclosure>~

A presentation may also carry a trailing **key-binding JWT**: a second signature, made
by the agent the mandate names, over this exact presentation. It is recognised and set
aside here rather than read, because what it carries -- a nonce, an audience and a
timestamp of its own -- is check 4's question rather than the issuer's signature.
``split_presentation`` is where the two are told apart, and it is the one place that
knows a hop is not a disclosure.

AP2 may also join several hops of a delegation chain with ``~~``. The Desk reads a root
mandate and the one hop presenting it, so a chain is recognised in order to be refused
with a sentence saying so.

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
from decimal import Decimal
from typing import Any

from jwt.api_jws import decode as jws_decode
from jwt.api_jws import get_unverified_header
from jwt.exceptions import PyJWTError
from jwt.utils import base64url_decode, base64url_encode

from desk.identity import ES256PublicKey

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


@dataclass(frozen=True)
class MandateDigest:
    """The digest naming one presentation, and the hash it was taken under.

    The algorithm travels with the value because AP2 says which one to use rather
    than fixing it: a ``payment.reference`` is hashed under "the ``_sd_alg``
    algorithm for the SD-JWT this constraint is in, or ``sha-256`` if undefined"
    (``docs/ap2/payment_mandate.md:231-235``). Two digests are only comparable when
    they were taken alike, and a bare string would not say whether they were.
    """

    algorithm: str
    value: str


@dataclass(frozen=True)
class Presentation:
    """One verified mandate: what it proves, and the digest that names it.

    The digest lives here rather than on the mandate because it is a fact about the
    bytes that arrived, not about what they said. It is used twice -- a
    ``payment.reference`` constraint names the open Checkout Mandate it belongs with by
    digest, and the Desk keys a mandate's accumulated spend by it -- and ``digest_of``
    explains why it is taken over the signed part alone.
    """

    claims: dict[str, Any]
    digest: MandateDigest
    mandate_id: MandateDigest


def verify_presentation(mandate: str, public_key: ES256PublicKey) -> Presentation:
    """The claims this mandate proves, with every disclosure resolved into place.

    The key is taken as a capability rather than as a role. A mandate the principal
    signed and one the Desk signed are read by the same RFC 9901 machinery, and
    making that explicit is what keeps ``PrincipalPublicKey`` and ``DeskPublicKey``
    two unrelated types everywhere it matters -- there is still no path by which a
    mandate presented as a principal's verifies against the Desk's own key, because
    the caller supplies the key and check 2 only ever resolves a principal's.

    Refuses rather than returns whenever the answer would be partly guessed: a
    signature that does not verify, a hash we do not implement, a disclosure that
    does not belong. The caller gets claims it can rely on or a sentence saying why
    there are none.

    Numbers arrive as ``Decimal`` rather than ``float``. A mandate's ceiling is money,
    and ``1000.10`` is not a float; parsing it as one would leave the Desk drawing a
    balance down by a number the principal did not sign.
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
            f"the mandate does not verify against the key it was presented under: {exc}"
        ) from exc

    try:
        claims = json.loads(signed, parse_float=Decimal)
    except ValueError as exc:
        raise MandateNotVerified(f"the signed mandate claims are not JSON: {exc}") from exc
    if not isinstance(claims, dict):
        raise MandateNotVerified("the signed mandate claims are not a JSON object")

    algorithm = _sd_alg(claims.get(SD_ALG_CLAIM))
    resolved = _resolve(claims, _disclosures(mandate, _HASHES[algorithm]))
    return Presentation(
        claims=resolved,
        digest=digest_of(mandate, algorithm=algorithm),
        mandate_id=signed_digest_of(mandate, algorithm=algorithm),
    )


def verify_sd_jwt(mandate: str, public_key: ES256PublicKey) -> dict[str, Any]:
    """The claims ``verify_presentation`` proves, for a caller with no use for a digest."""
    return verify_presentation(mandate, public_key).claims


def digest_of(mandate: str, *, algorithm: str = DEFAULT_SD_ALG) -> MandateDigest:
    """The digest that names this mandate, taken over its issuer JWS.

    **Over the signed part only, and this is load-bearing.** The obvious thing to hash
    is the whole presentation as received, which is what RFC 9901 does for a disclosure
    and for ``sd_hash``. It is wrong here, because the disclosures are a *set* and their
    order on the wire is the holder's to choose: two presentations of one signed mandate
    with the disclosures swapped verify to identical claims and would hash differently.

    The Desk keys a mandate's accumulated spend by this digest. A digest that varied
    with disclosure order would therefore hand a holder a fresh ceiling for each
    ordering -- an ``n!``-times-over double spend, on exactly the multi-disclosure
    mandates AP2's own SDK emits.

    The issuer JWS has no such freedom. It is the signature and what it covers, fixed
    at issuance. And because the Desk verifies a mandate only when it is *fully*
    disclosed (see ``_resolve``), the signed part determines the whole content: a
    disclosure missing, added or altered is refused rather than resolved. One issuer
    JWS is therefore one mandate, which is precisely what a spend accumulator needs to
    be keyed by.

    ``sd_hash`` on a key-binding JWT is a different job -- it binds one exact
    presentation on purpose -- and check 4, which reads those, computes its own.
    """
    if algorithm not in _HASHES:
        raise MandateNotVerified(
            f"the Desk does not digest mandates under {algorithm!r}; it understands "
            f"{', '.join(sorted(_HASHES))}"
        )
    return MandateDigest(
        algorithm=algorithm, value=_digest(_issuer_jws(mandate), _HASHES[algorithm])
    )


def signed_digest_of(mandate: str, *, algorithm: str = DEFAULT_SD_ALG) -> MandateDigest:
    """The digest of the bytes the principal's signature actually covers.

    ``digest_of`` above stops one kind of malleability -- disclosure order -- and not
    the other. A JWS is ``header.payload.signature``, and the signature is not part of
    what it covers, so it can be varied while the mandate still verifies: base64url
    leaves spare bits in the final character of a 64-byte ECDSA signature, and ECDSA
    admits a second valid signature for every one it produces. One signed mandate can
    therefore be presented under many issuer-JWS digests, every one of which passes
    check 2 and reads back the same ceiling.

    That is fatal for anything that keys *state*. An accumulated spend keyed by a
    digest a holder can vary is an accumulated spend a holder can reset, and the
    ceiling stops meaning anything. So the ledger is keyed by this instead: the signing
    input, which nobody but the principal can alter, because altering it is precisely
    what a signature check catches.

    Distinct per issuance as well as per authorisation, since the signing input carries
    the disclosure digests and every disclosure is freshly salted. A principal who
    signs the same constraints twice gets two mandates with two ceilings, which is
    right -- they authorised twice.

    ``digest_of`` remains the one to compare for AP2's ``payment.reference``, because
    the specification fixes what that names and we do not get to choose. Pairing is
    safe under it anyway: the reference sits *inside* the signed payment mandate, so a
    mangled checkout mandate fails to match and the pair is refused rather than
    accepted.
    """
    if algorithm not in _HASHES:
        raise MandateNotVerified(
            f"the Desk does not digest mandates under {algorithm!r}; it understands "
            f"{', '.join(sorted(_HASHES))}"
        )
    issuer_jws = _issuer_jws(mandate)
    signing_input, separator, _signature = issuer_jws.rpartition(".")
    if not separator or "." not in signing_input:
        raise MandateNotVerified(
            "the mandate's issuer JWS is not a header, a payload and a signature"
        )
    return MandateDigest(algorithm=algorithm, value=_digest(signing_input, _HASHES[algorithm]))


@dataclass(frozen=True)
class SplitPresentation:
    """One presentation, cut where RFC 9901 cuts one.

    ``sd_jwt`` is the issuer JWS, its disclosures and the separator that ends them --
    exactly the characters a key-binding JWT's ``sd_hash`` claim is taken over.
    ``key_binding_jwt`` is the proof of possession after it, or ``None`` when the
    holder attached none.
    """

    sd_jwt: str
    key_binding_jwt: str | None


def split_presentation(mandate: str) -> SplitPresentation:
    """Tell a key-binding hop from a disclosure, by RFC 9901's own rule.

    The rule is positional, which is what makes it safe to apply before anything has
    been verified: a presentation carrying no key binding **ends in the separator**, so
    a non-empty trailing segment is a hop and never a disclosure.

    Both ways of getting this wrong are holes rather than inconveniences. Read as a
    disclosure, a hop is refused as material the signed claims make no room for, and a
    conformant presentation never gets past check 2. Read as a hop, a disclosure is
    quietly dropped -- and dropping one leaves a mandate that still verifies and
    authorises strictly more, which is the exact hole ``_resolve`` exists to close.
    """
    if not isinstance(mandate, str) or not mandate.strip():
        raise MandateNotVerified("no mandate was presented")
    if SEPARATOR not in mandate:
        raise MandateNotVerified(
            "the mandate carries no disclosure separator, so it is not an SD-JWT"
        )
    # A shape AP2 allows and the Desk deliberately does not read. Recognised so that a
    # conformant chain is told what the Desk cannot do, rather than refused for failing
    # to parse a JWT as though it were a disclosure.
    if HOP_SEPARATOR in mandate:
        raise MandateNotVerified(
            "the mandate is a delegation chain. The Desk reads the root mandate a "
            "principal signed and the one key-binding hop that presents it; following "
            "further hops is not built."
        )
    if mandate.endswith(SEPARATOR):
        return SplitPresentation(sd_jwt=mandate, key_binding_jwt=None)
    sd_jwt, _, hop = mandate.rpartition(SEPARATOR)
    return SplitPresentation(sd_jwt=sd_jwt + SEPARATOR, key_binding_jwt=hop)


def sd_hash_of(mandate: str, *, algorithm: str = DEFAULT_SD_ALG) -> MandateDigest:
    """The digest a key-binding JWT's ``sd_hash`` claim has to carry.

    Over the issuer JWS **and** its disclosures as they arrived, which is the opposite
    choice to ``digest_of`` above and deliberately so. ``digest_of`` names a *mandate*
    and must not move when the holder reorders its disclosures. This names one
    *presentation* of that mandate, and binding the hop to the exact bytes it was made
    over is the entire point: a hop that covered only the signed part could be lifted
    onto a presentation of the same mandate with different disclosures.

    Taken over the received characters, for the reason ``_digest`` gives -- a hop signed
    over re-encoded bytes would bind nothing that arrived.
    """
    if algorithm not in _HASHES:
        raise MandateNotVerified(
            f"the Desk does not digest presentations under {algorithm!r}; it understands "
            f"{', '.join(sorted(_HASHES))}"
        )
    return MandateDigest(
        algorithm=algorithm, value=_digest(split_presentation(mandate).sd_jwt, _HASHES[algorithm])
    )


def _issuer_jws(mandate: str) -> str:
    """The signed part: everything before the first separator."""
    issuer_jws = split_presentation(mandate).sd_jwt.split(SEPARATOR, 1)[0]
    if not issuer_jws:
        raise MandateNotVerified("the mandate has no issuer JWS before its disclosures")
    return issuer_jws


def _sd_alg(claimed: Any) -> str:
    """Which hash the digests were taken under, by name.

    An algorithm we do not implement is a refusal, never a fallback to the default:
    hashing the disclosures with the wrong function would resolve nothing and read as
    a holder who simply withheld everything.
    """
    if claimed is None:
        return DEFAULT_SD_ALG
    if not isinstance(claimed, str) or claimed not in _HASHES:
        raise MandateNotVerified(
            f"the mandate's disclosure digests name {claimed!r}, which the Desk does "
            f"not implement; it understands {', '.join(sorted(_HASHES))}"
        )
    return claimed


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
    _, _, tail = split_presentation(mandate).sd_jwt.partition(SEPARATOR)
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
        decoded = json.loads(base64url_decode(segment), parse_float=Decimal)
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

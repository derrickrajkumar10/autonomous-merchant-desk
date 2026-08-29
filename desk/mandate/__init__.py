"""Mandates -- check 2 of the trust spine, and the library that reads them.

A **mandate** is a signed authorisation from a human principal. It is the answer to
the question a merchant has never had to ask before: *does a real human actually
authorise this spend?* The buyer agent proved who it was in check 1; here it produces
the human's authorisation and the Desk decides whether to believe it.

The shape is not ours. It is AP2 v0.2's **open Checkout Mandate**
(``mandate.checkout.open.1``), secured as an SD-JWT, carrying the presenting agent's
public key in a ``cnf`` claim. Adopting a specification rather than inventing one is
what makes "a judge writes their own buyer agent and it transacts" (FR-11.1) a claim
we can stand behind: the mandate our wallet produces verifies in Google's own SDK,
and a mandate that SDK produces verifies here.

Two layers, deliberately separate:

- ``sdjwt`` is RFC 9901 and knows nothing about commerce -- signature, disclosures,
  refusals.
- ``checkout`` is AP2 and knows nothing about cryptography -- ``vct``, constraints,
  ``cnf``, expiry.

``check`` sits on both and is the only part that writes to the trail.

    from desk.audit import AuditTrail
    from desk.identity import PrincipalDirectory
    from desk.mandate import MandateCheck

    outcome = MandateCheck(PrincipalDirectory(pool), trail).verify(
        mandate, presented_by=identity_outcome.identity
    )
    if outcome.passed:
        ...                          # outcome.mandate carries the constraints

See ADR-0002 for why a mandate is signed ES256 while everything else is Ed25519, and
[the AP2 research note](../../docs/research/ap2-mandate-model.md) for the field-level
citations behind every structural rule enforced here.
"""

from desk.mandate.check import MandateCheck, MandateOutcome
from desk.mandate.checkout import (
    DELEGATE_PAYLOAD_CLAIM,
    LINE_ITEMS_CONSTRAINT,
    OPEN_CHECKOUT_VCT,
    OpenCheckoutMandate,
    read_open_checkout_mandate,
)
from desk.mandate.sdjwt import (
    MANDATE_ALG,
    MandateHeader,
    MandateNotVerified,
    read_mandate_header,
    verify_sd_jwt,
)

__all__ = [
    "DELEGATE_PAYLOAD_CLAIM",
    "LINE_ITEMS_CONSTRAINT",
    "MANDATE_ALG",
    "OPEN_CHECKOUT_VCT",
    "MandateCheck",
    "MandateNotVerified",
    "MandateOutcome",
    "OpenCheckoutMandate",
    "MandateHeader",
    "read_open_checkout_mandate",
    "read_mandate_header",
    "verify_sd_jwt",
]

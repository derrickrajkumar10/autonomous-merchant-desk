"""Mandates -- check 2 of the trust spine, and the library that reads them.

A **mandate** is a signed authorisation from a human principal. It is the answer to
the question a merchant has never had to ask before: *does a real human actually
authorise this spend?* The buyer agent proved who it was in check 1; here it produces
the human's authorisation and the Desk decides whether to believe it.

The shape is not ours. It is AP2 v0.2's, secured as an SD-JWT. Adopting a
specification rather than inventing one is what makes "a judge writes their own buyer
agent and it transacts" (FR-11.1) a claim we can stand behind: the mandates our wallet
produces verify in Google's own SDK, and mandates that SDK produces verify here.

**Two mandates, because AP2 has two.** The open **Checkout** Mandate
(``mandate.checkout.open.1``) says what may be bought; the open **Payment** Mandate
(``mandate.payment.open.1``) says what may be spent, and carries the ``payment.budget``
ceiling. Both bind the presenting agent's public key in a ``cnf`` claim, and the
Payment Mandate names the Checkout Mandate it belongs with by digest, in a mandatory
``payment.reference`` constraint.

Four layers, deliberately separate:

- ``sdjwt`` is RFC 9901 and knows nothing about commerce -- signature, disclosures,
  digests, refusals.
- ``open_mandate`` is what the two open mandates share -- ``vct``, ``constraints``,
  ``cnf``, ``iat``, ``exp``.
- ``checkout`` and ``payment`` are AP2 and know nothing about cryptography: what each
  mandate's own constraints mean.

``check`` sits on all of them and is the only part that writes to the trail.

    from desk.audit import AuditTrail
    from desk.identity import PrincipalDirectory
    from desk.mandate import MandateCheck

    check = MandateCheck(PrincipalDirectory(pool), trail)
    checkout = check.verify(checkout_mandate, presented_by=identity_outcome.identity)
    payment = check.verify_payment(payment_mandate, presented_by=identity_outcome.identity)
    if checkout.passed and payment.passed:
        ...                          # both carry constraints for check 3 to evaluate

See ADR-0002 for why a mandate is signed ES256 while everything else is Ed25519, and
[the AP2 research note](../../docs/research/ap2-mandate-model.md) for the field-level
citations behind every structural rule enforced here.
"""

from desk.mandate.check import MandateCheck, MandateOutcome
from desk.mandate.checkout import (
    ALLOWED_MERCHANTS_CONSTRAINT,
    LINE_ITEMS_CONSTRAINT,
    OPEN_CHECKOUT_VCT,
    OpenCheckoutMandate,
    read_open_checkout_mandate,
)
from desk.mandate.open_mandate import DELEGATE_PAYLOAD_CLAIM, OpenMandate, read_open_mandate
from desk.mandate.payment import (
    BUDGET_CONSTRAINT,
    EXECUTION_DATE_CONSTRAINT,
    OPEN_PAYMENT_VCT,
    PAYMENT_REFERENCE_CONSTRAINT,
    Budget,
    ExecutionWindow,
    OpenPaymentMandate,
    read_open_payment_mandate,
)
from desk.mandate.sdjwt import (
    MANDATE_ALG,
    MandateDigest,
    MandateHeader,
    MandateNotVerified,
    Presentation,
    SplitPresentation,
    digest_of,
    read_mandate_header,
    sd_hash_of,
    signed_digest_of,
    split_presentation,
    verify_presentation,
    verify_sd_jwt,
)

__all__ = [
    "ALLOWED_MERCHANTS_CONSTRAINT",
    "BUDGET_CONSTRAINT",
    "DELEGATE_PAYLOAD_CLAIM",
    "EXECUTION_DATE_CONSTRAINT",
    "LINE_ITEMS_CONSTRAINT",
    "MANDATE_ALG",
    "OPEN_CHECKOUT_VCT",
    "OPEN_PAYMENT_VCT",
    "PAYMENT_REFERENCE_CONSTRAINT",
    "Budget",
    "ExecutionWindow",
    "MandateCheck",
    "MandateDigest",
    "MandateHeader",
    "MandateNotVerified",
    "MandateOutcome",
    "OpenCheckoutMandate",
    "OpenMandate",
    "OpenPaymentMandate",
    "Presentation",
    "SplitPresentation",
    "digest_of",
    "sd_hash_of",
    "signed_digest_of",
    "split_presentation",
    "read_mandate_header",
    "read_open_checkout_mandate",
    "read_open_mandate",
    "read_open_payment_mandate",
    "verify_presentation",
    "verify_sd_jwt",
]

"""Settlement -- where an agreed deal becomes money, and evidence that it did.

Everything before this was the Desk deciding. Checks 1 to 4 said the request was
authentic, authorised, inside a ceiling and not a replay. The negotiation reached terms
and signed a closed Checkout Mandate saying what they were. None of it moved a rupee,
and none of it produced anything a third party could check.

This package closes both gaps, and the second one is the larger.

**Execution.** Agreed terms become a charge against a real payment rail rather than a
state transition in our own database. The rail sits behind a one-method boundary
(``rail.py``), so the Desk's behaviour on a charge that completes, on one that does not,
and on the ledger underneath both is testable without a third party's server being up.
``razorpay_rail.py`` is one implementation of that boundary and says plainly what
Razorpay's test mode can and cannot do headlessly.

**Proof.** The Desk signs a **receipt** binding four things: the mandate chain that
authorised the purchase, the terms that were negotiated, the amount actually charged,
and when. Anyone holding the Desk's published Ed25519 key can verify it with an
off-the-shelf JOSE library, without access to our systems and without trusting our
account of anything. That is the difference between evidence and assertion, and it is
what makes the settlement-proof work of ticket 17 tractable at all -- both sides of that
join will be artefacts the Desk signed.

**The three things that must never come apart** -- the charge, the receipt, and the
mandate's accumulated total -- happen in one transaction. ``settle.py`` sets out why
that costs a lock held across a network call, and why that is the cheaper mistake.

    from desk.settlement import Receipts, Settlement, install_schema, read_receipt

    with pool.connection() as conn:
        install_schema(conn)

    receipts = Receipts(pool, vault.published().receipt)
    settlement = Settlement(
        rail, accumulator, receipts, trail, pool,
        receipt_key=vault.receipt_key(),
        mandate_key=vault.mandate_key().public_key,
    )

    settled = settlement.settle(
        reply.closed_mandate, checkout=checkout, payment=payment, presented_by=identity
    )
    settled.completed              # did the money move
    settled.receipt.signed         # the artefact, or None if it did not

    # And what a stranger does, with nothing but the published key:
    read_receipt(settled.receipt.signed, key=published_key)

**What is not here.** Refunds, chargebacks, reversals, adjustments and revocation -- a
receipt records something that happened. Bank lines, matching and Exceptions are
tickets 16 to 18; treasury is ticket 15. Multiple currencies are nobody's yet.
"""

from desk.settlement.rail import Charge, PaymentRail, RailCharge
from desk.settlement.razorpay_rail import (
    KEY_ID_VAR,
    KEY_SECRET_VAR,
    MINOR_UNITS,
    RAIL,
    RailNotConfigured,
    RazorpayRail,
    from_minor_units,
    in_minor_units,
)
from desk.settlement.receipt import (
    AGREED_CLAIM,
    CHAIN_CLAIM,
    CHARGED_CLAIM,
    ISSUER,
    RAIL_CLAIM,
    RECEIPT_TYP,
    MandateChain,
    Receipt,
    ReceiptNotVerified,
    issue_receipt,
    read_receipt,
)
from desk.settlement.schema import TABLE, install_schema
from desk.settlement.settle import NotSettleable, Settled, Settlement
from desk.settlement.store import IssuedReceipt, Receipts

__all__ = [
    "AGREED_CLAIM",
    "CHAIN_CLAIM",
    "CHARGED_CLAIM",
    "ISSUER",
    "KEY_ID_VAR",
    "KEY_SECRET_VAR",
    "MINOR_UNITS",
    "RAIL",
    "RAIL_CLAIM",
    "RECEIPT_TYP",
    "TABLE",
    "Charge",
    "IssuedReceipt",
    "MandateChain",
    "NotSettleable",
    "PaymentRail",
    "RailCharge",
    "RailNotConfigured",
    "RazorpayRail",
    "Receipt",
    "ReceiptNotVerified",
    "Receipts",
    "Settled",
    "Settlement",
    "from_minor_units",
    "in_minor_units",
    "install_schema",
    "issue_receipt",
    "read_receipt",
]

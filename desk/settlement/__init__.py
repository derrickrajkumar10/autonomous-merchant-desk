"""Settlement -- where an agreed deal becomes money, and evidence that it did.

Everything before this was the Desk deciding. Checks 1 to 4 said the request was
authentic, authorised, inside a ceiling and not a replay. The negotiation reached terms
and signed a closed Checkout Mandate saying what they were. None of it moved a rupee,
and none of it produced anything a third party could check.

This package closes both gaps, and the second one is the larger. It is being built up a
piece at a time; what is here so far is the boundary the payment rail sits behind, one
implementation of it, the receipt itself, and where receipts are kept.
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
    "PaymentRail",
    "RailCharge",
    "RailNotConfigured",
    "RazorpayRail",
    "Receipt",
    "ReceiptNotVerified",
    "Receipts",
    "from_minor_units",
    "in_minor_units",
    "install_schema",
    "issue_receipt",
    "read_receipt",
]

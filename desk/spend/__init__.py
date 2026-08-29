"""Spend authority -- check 3 of the trust spine, and the accumulator behind it.

Check 2 established that a human authorised *something* and that this agent may
present it. This is the check that finally reads the authorisation for what it says:
is this the thing that was authorised, in a currency that was authorised, inside the
window it was authorised for, for an amount the ceiling still has room for.

The ceiling comes from the mandate's own ``payment.budget`` constraint and never from
configuration the Desk holds out-of-band. That is the difference between a merchant a
stranger's agent can transact with and one that only works for agents who already know
about us (ADR-0004, FR-11.1).

The mandate stays immutable. What changes is one row in ``mandate_spend``, keyed by
the mandate's digest, holding the accumulated total AP2 asks the verifier to track.

    from desk.audit import AuditTrail
    from desk.spend import BudgetAccumulator, Money, SpendAuthorityCheck, SpendRequest
    from desk.spend import install_schema

    with pool.connection() as conn:
        install_schema(conn)

    accumulator = BudgetAccumulator(pool)
    outcome = SpendAuthorityCheck(accumulator, trail).evaluate(
        SpendRequest(item_id="SKU-COFFEE-1KG", amount=Money.of("750.00", "INR")),
        presented_by=identity,
        checkout=checkout_outcome,      # check 2 on the open Checkout Mandate
        payment=payment_outcome,        # check 2 on the open Payment Mandate
    )
    if outcome.passed:
        ...                             # outcome.remaining is what closing would leave

Nothing is drawn down by evaluating. When a deal closes, the negotiation records the
spend in the same transaction as the entry that explains it:

    accumulator.record_spend(payment_outcome, amount=amount, conn=conn)
"""

from desk.spend.accumulator import (
    BudgetAccumulator,
    CeilingExceeded,
    LedgerContradiction,
    MandateSpend,
)
from desk.spend.check import SpendAuthorityCheck, SpendOutcome, SpendRequest
from desk.spend.money import CURRENCY_CODE, CurrencyMismatch, Money
from desk.spend.schema import TABLE, install_schema

__all__ = [
    "CURRENCY_CODE",
    "TABLE",
    "BudgetAccumulator",
    "CeilingExceeded",
    "CurrencyMismatch",
    "LedgerContradiction",
    "MandateSpend",
    "Money",
    "SpendAuthorityCheck",
    "SpendOutcome",
    "SpendRequest",
    "install_schema",
]

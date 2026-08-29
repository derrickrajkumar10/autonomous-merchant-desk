"""How much of a mandate has been spent, and the one place that number changes.

AP2's evaluation rule for ``payment.budget``, verbatim
(``docs/ap2/payment_mandate.md:202-207``):

> Evaluating the budget requires tracking the total amount spent using this Payment
> Mandate. For this constraint to evaluate as true, the requested amount plus the
> total sum of amounts from previously closed Payment Mandates MUST be less than or
> equal to ``max``. After approval, the amount MUST be added to the accumulated total
> for future evaluation.

Two operations, and the split between them is the interesting part.

``spent_against`` is what check 3 asks: *how much has gone already?* It reads and
writes nothing, because a request that is merely being evaluated has not spent
anything, and a deal the buyer walks away from must not consume a rupee of the
principal's ceiling.

``record_spend`` is what a **closed deal** calls, and it is the arbiter rather than
the reporter. It takes the row's lock, re-evaluates the rule against the total as it
stands at that instant, and refuses if the deal would breach the ceiling. Check 3's
answer can go stale -- two deals may both pass it against the same remaining balance
and only then close -- so the check is the fast answer and this is the true one.
Underneath both, ``spent <= ceiling`` is a database CHECK, which is what holds if this
module is wrong too.

Nothing here writes to the audit trail. A spend is not an event in its own right --
it is a consequence of a deal closing, which is the negotiation ticket's event to
record -- so ``record_spend`` takes a caller's ``conn`` instead, and the ledger row
and the entry that explains it commit together or not at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from desk.mandate import Budget, MandateDigest, MandateOutcome, OpenPaymentMandate
from desk.spend.money import Money
from desk.spend.schema import TABLE

_COLUMNS = "mandate_id, digest_algorithm, currency, ceiling, spent, first_seen_at, updated_at"


class CeilingExceeded(RuntimeError):
    """A spend was recorded that would take a mandate past the ceiling it carries.

    Not a refusal -- refusals are check 3's and are recorded in the trail with a
    reason code. Reaching this means a deal closed for more than the mandate had
    left, which is either a race that check 3 could not see or a caller that never
    asked it. Either way the transaction fails rather than the ceiling bending.
    """


class LedgerContradiction(RuntimeError):
    """A stored ceiling that disagrees with the mandate presented under its digest.

    Impossible unless something is badly wrong: the row is keyed by the digest of the
    mandate, so the ceiling is a function of the key. Raised rather than reconciled,
    because there is no honest way to choose between two ceilings for one mandate.
    """


@dataclass(frozen=True)
class MandateSpend:
    """One mandate's ceiling and what has been drawn against it."""

    mandate_id: str
    ceiling: Money
    spent: Money
    first_seen_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def remaining(self) -> Money:
        """What is left. Never negative -- the database will not store a row that is."""
        return self.ceiling - self.spent

    def covers(self, amount: Money) -> bool:
        """AP2's rule: this amount plus what has gone already, at or under ``max``."""
        return self.spent + amount <= self.ceiling


class BudgetAccumulator:
    """The Desk's record of what has been spent against each open Payment Mandate.

    Install the schema once with ``install_schema``; this class does not migrate.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def spent_against(self, payment: MandateOutcome[OpenPaymentMandate]) -> MandateSpend:
        """This mandate's ceiling and accumulated total. Reads only; writes no row.

        A mandate nobody has spent against yet has no row, and is reported with a
        total of zero rather than being opened. Evaluating a request is not spending
        against it, and a table with a row per mandate ever *considered* would make
        "has this mandate been used" unanswerable.
        """
        digest, budget = _authorised(payment)
        with self._pool.connection() as conn:
            stored = self._find(conn, digest.value)
        if stored is None:
            return MandateSpend(
                mandate_id=digest.value,
                ceiling=_ceiling(budget),
                spent=Money(amount=Decimal(0), currency=budget.currency),
            )
        _agrees_with(stored, budget)
        return stored

    def record_spend(
        self,
        payment: MandateOutcome[OpenPaymentMandate],
        *,
        amount: Money,
        conn: Connection[Any] | None = None,
    ) -> MandateSpend:
        """Add a closed deal's amount to this mandate's accumulated total.

        Returns the ledger as it stands afterwards, so a caller can record the
        remaining balance in whatever entry explains the deal.

        Takes check 2's whole verified outcome rather than a digest and a ceiling
        separately, so that pairing the wrong two is not a thing a caller can express.
        The first spend against a mandate is what fixes its ceiling in the row, and a
        caller able to supply the two apart could fix it from some other mandate --
        which nothing afterwards would catch, because from then on the stored ceiling
        is the one everything is compared against.

        Pass ``conn`` to enlist this in the caller's own transaction. A deal recorded
        as closed whose spend was never accumulated would leave the next request
        evaluated against a ceiling that had already been drawn down further than the
        Desk believed.
        """
        digest, budget = _authorised(payment)
        if conn is not None:
            return self._accumulate(conn, digest, budget=budget, amount=amount)
        with self._pool.connection() as pooled:
            return self._accumulate(pooled, digest, budget=budget, amount=amount)

    def _accumulate(
        self, conn: Connection[Any], digest: MandateDigest, *, budget: Budget, amount: Money
    ) -> MandateSpend:
        ceiling = _ceiling(budget)
        if amount.currency != ceiling.currency:
            raise LedgerContradiction(
                f"a deal of {amount} cannot be drawn against a ceiling of {ceiling}; "
                f"check 3 refuses a request in another currency before it closes"
            )

        # Open the row if this is the mandate's first spend, then take its lock. The
        # insert is separate from the update so that concurrent closes against one
        # mandate serialise on SELECT ... FOR UPDATE rather than racing an upsert.
        conn.execute(
            f"INSERT INTO {TABLE} ({_COLUMNS})"
            f" VALUES (%s, %s, %s, %s, 0, clock_timestamp(), clock_timestamp())"
            f" ON CONFLICT (mandate_id) DO NOTHING",
            (digest.value, digest.algorithm, ceiling.currency, ceiling.amount),
        )
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {TABLE} WHERE mandate_id = %s FOR UPDATE", (digest.value,)
        ).fetchone()
        if row is None:  # pragma: no cover - the insert above put it there
            raise LedgerContradiction(
                f"{digest.value} was opened in the accumulator and is not there. Not a "
                f"refusal: the ledger contradicts itself."
            )

        stored = _to_spend(row)
        _agrees_with(stored, budget)
        if not stored.covers(amount):
            raise CeilingExceeded(
                f"a deal of {amount} would take this mandate to "
                f"{stored.spent + amount} against a ceiling of {stored.ceiling}, of "
                f"which {stored.remaining} is left"
            )

        updated = conn.execute(
            f"UPDATE {TABLE} SET spent = spent + %s, updated_at = clock_timestamp()"
            f" WHERE mandate_id = %s"
            f" RETURNING {_COLUMNS}",
            (amount.amount, digest.value),
        ).fetchone()
        if updated is None:  # pragma: no cover - the row is locked and cannot vanish
            raise LedgerContradiction(f"{digest.value} vanished from the accumulator mid-spend")
        return _to_spend(updated)

    @staticmethod
    def _find(conn: Connection[Any], mandate_id: str) -> MandateSpend | None:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM {TABLE} WHERE mandate_id = %s", (mandate_id,)
        ).fetchone()
        return None if row is None else _to_spend(row)


def _authorised(payment: MandateOutcome[OpenPaymentMandate]) -> tuple[MandateDigest, Budget]:
    """The key and the ceiling of one verified Payment Mandate, taken together.

    Together, because they are two halves of one fact. Both refusals are a caller's
    mistake rather than a counterparty's: a mandate that did not verify has been
    answered already, and one carrying no ``payment.budget`` is refused by check 3
    before any deal could close against it.

    The key is ``mandate_id`` and never ``digest``. ``digest`` names the issuer JWS,
    which a holder can vary without breaking the signature -- ECDSA admits a second
    valid signature for every one it makes, and base64url leaves spare bits in the last
    character of a 64-byte one. Keying the ledger by it would let a holder mint a fresh
    row, and a fresh ceiling, for one mandate. ``mandate_id`` names the signing input,
    which is the one thing about a mandate nobody but the principal can change.
    """
    if payment.mandate is None or payment.mandate_id is None:
        raise ValueError(
            f"the accumulator draws against mandates check 2 verified, and this one did "
            f"not ({payment.reason_code})"
        )
    if payment.mandate.budget is None:
        raise ValueError(
            "this payment mandate sets no payment.budget ceiling, so there is nothing to "
            "draw against. Check 3 refuses such a mandate rather than reading it as unlimited."
        )
    return payment.mandate_id, payment.mandate.budget


def _ceiling(budget: Budget) -> Money:
    return Money(amount=budget.maximum, currency=budget.currency)


def _agrees_with(stored: MandateSpend, budget: Budget) -> None:
    """The stored ceiling must be the one the mandate under that digest carries.

    Unreachable as the code stands, and kept deliberately. A digest names the *signed
    part* of a mandate the Desk verified only because it was fully disclosed, so it
    determines the ceiling; reaching this would mean two different mandates had
    produced one digest. It is here because a change to what ``digest_of`` hashes could
    quietly stop that being true, and the opening it would leave -- one mandate's
    spending drawn against another's ceiling -- is the one this module exists to close.
    """
    if stored.ceiling.currency != budget.currency or stored.ceiling.amount != budget.maximum:
        raise LedgerContradiction(  # pragma: no cover - while a digest names one mandate
            f"the accumulator holds a ceiling of {stored.ceiling} for {stored.mandate_id}, "
            f"and the mandate presented under that digest carries "
            f"{budget.maximum} {budget.currency}"
        )


def _to_spend(row: Sequence[Any]) -> MandateSpend:
    mandate_id, _algorithm, currency, ceiling, spent, first_seen_at, updated_at = row
    return MandateSpend(
        mandate_id=mandate_id,
        ceiling=Money(amount=ceiling, currency=currency),
        spent=Money(amount=spent, currency=currency),
        first_seen_at=first_seen_at,
        updated_at=updated_at,
    )

"""Turning an agreement into money, and the three things that must never come apart.

A negotiation ending in agreement has moved nothing. This is where it becomes a charge
against a real rail and a receipt anyone can check. Three state changes make that up:

1. the mandate's accumulated total goes up by what was charged,
2. the rail takes the money,
3. a signed receipt comes into being.

**Any two of those without the third is a defect, and two of them are serious.** A
charge with no receipt is money taken that the Desk cannot prove was owed. A receipt
with no charge is a document asserting something that did not happen -- the worst of
the three, because it is the artefact everything downstream trusts. An accumulator
advanced by a charge that never completed spends a human's authority on nothing, and
the next honest request gets refused for it.

So all three happen inside one transaction, and the rail call is *inside* it. That is
deliberate and it costs something worth naming: the mandate's ledger row stays locked
for as long as the rail takes to answer, which serialises concurrent settlements
against one mandate. The alternative -- charge first, record afterwards -- leaves a
window where the money has moved and the ledger row cannot be written, and there is no
honest recovery from that. A lock held across a network call is a performance problem.
Money charged that we cannot account for is a correctness one.

**Settling one deal twice is not possible.** A receipt is named by the closed Checkout
Mandate it settles, so the store's primary key already refuses a second one. This goes
further and looks for it *before* charging, under an advisory lock on the deal, so a
retry -- the ordinary reason anyone settles twice -- returns the receipt that already
exists rather than taking the money again and failing on the way to writing it down.

**The trail carries all three outcomes** (FR-10.1, FR-7.5). ``settlement_attempted`` is
written on its own transaction, so it survives the rollback, and then either
``receipt_issued`` or ``settlement_incomplete`` follows it. **Every settlement that
begins gets an ending**, including the ones the Desk stops itself -- a ceiling with
nothing left writes an ending as surely as a declined card does.

That rule buys one thing, and it is the reason for the bookkeeping: an attempt with
*nothing* after it then means exactly one thing, which is that the Desk called the rail
and never heard back. If a ceiling refusal could leave the same shape, the only case
where the Desk genuinely does not know would be unreadable among cases where it does.

The two endings are told apart by what is in the payload rather than by which event they
are: an ending the rail produced carries the rail's own identifiers and status, and one
the Desk produced carries none, because there was no call.

**And neither carries a reason code.** Reason codes are why the *Desk refused a
counterparty*, and the ``audit_refusals`` view is built on exactly that. A declined card
is not the Desk refusing anything at all, and a ceiling reached mid-settlement is the
Desk stopping *itself*. Giving either a code would put them in a view whose every
consumer reads it as "requests we turned away", and quietly change what that number
means.

    from desk.settlement import Settlement

    settlement = Settlement(rail, accumulator, receipts, trail,
                            receipt_key=vault.receipt_key(),
                            mandate_key=vault.mandate_key().public_key)

    settled = settlement.settle(reply.closed_mandate, checkout=..., payment=...,
                                presented_by=identity)
    settled.receipt.signed     # None if the charge did not complete
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from psycopg import Connection
from psycopg_pool import ConnectionPool

from desk.audit import AuditEntry, AuditTrail, EventType
from desk.identity import AgentIdentity, DeskPublicKey, DeskReceiptKeypair
from desk.mandate import (
    ClosedCheckoutMandate,
    MandateOutcome,
    OpenCheckoutMandate,
    OpenPaymentMandate,
    digest_of,
    read_closed_checkout,
)
from desk.settlement.rail import Charge, PaymentRail, RailCharge
from desk.settlement.receipt import issue_receipt
from desk.settlement.store import IssuedReceipt, Receipts
from desk.spend import BudgetAccumulator, CeilingExceeded, Money

#: What the Desk tells the rail a charge is for. The rail's dashboard is read by people.
DESCRIPTION = "StitchAI desk settlement"

#: Namespace for the per-deal advisory lock, so that a lock taken on a closed mandate
#: cannot collide with the audit trail's chain lock in the same 64-bit space.
_LOCK_NAMESPACE = b"stitchai.settlement."


class NotSettleable(ValueError):
    """A request to settle something the Desk cannot settle, raised rather than answered.

    Always a caller's mistake and never a counterparty's: a closed mandate the Desk did
    not sign, a mandate that check 2 refused, or a closed deal presented against an
    authorisation it was not negotiated under. None of these is a refusal to write to
    the trail, because none of them is a buyer agent doing something -- a buyer agent
    cannot reach this code at all.
    """


@dataclass(frozen=True)
class Settled:
    """What came of settling one closed deal.

    ``receipt`` is ``None`` exactly when the charge did not complete, which is the same
    condition as ``charge.completed`` being false. Two ways to ask one question, and
    they cannot disagree: the receipt is only ever built from a completed charge.
    """

    charge: RailCharge
    receipt: IssuedReceipt | None
    #: What the mandate has left afterwards. ``None`` when nothing was drawn down.
    remaining: Money | None
    entries: tuple[AuditEntry, ...]

    @property
    def completed(self) -> bool:
        return self.receipt is not None


class Settlement:
    """The one path from an agreed deal to money moved and a receipt to show for it."""

    def __init__(
        self,
        rail: PaymentRail,
        accumulator: BudgetAccumulator,
        receipts: Receipts,
        trail: AuditTrail,
        pool: ConnectionPool,
        *,
        receipt_key: DeskReceiptKeypair,
        mandate_key: DeskPublicKey,
    ) -> None:
        self._rail = rail
        self._accumulator = accumulator
        self._receipts = receipts
        self._trail = trail
        self._pool = pool
        self._receipt_key = receipt_key
        self._mandate_key = mandate_key

    def settle(
        self,
        closed_mandate: str,
        *,
        checkout: MandateOutcome[OpenCheckoutMandate],
        payment: MandateOutcome[OpenPaymentMandate],
        presented_by: AgentIdentity,
    ) -> Settled:
        """Charge for one closed deal, and issue the receipt for it.

        ``closed_mandate`` is the credential itself and not the ``DeskMessage`` that
        carried it, so the terms settled against are the ones the Desk's own signature
        covers rather than the ones some object in memory remembers. It is read back
        and verified here even though the Desk signed it moments ago -- the artefact is
        what a buyer holds and what a receipt will point at, so it is what should be
        charged against.

        Both open mandates come in as check 2 left them. The Payment Mandate is what the
        accumulator draws against; the Checkout Mandate is here so that the closed deal
        can be proved to have been negotiated *under this authorisation* rather than
        merely presented beside it.
        """
        closed = self._read(closed_mandate)
        self._chains_to(closed, checkout, payment)
        amount = closed.checkout.total
        deal = closed.checkout_hash.value

        settled = self._receipts.find(deal)
        if settled is not None:
            # Already charged, and the receipt proves it. Returning it rather than
            # refusing, because the caller asking twice is a retry and a retry should
            # be safe. Nothing is written: the trail already has this settlement.
            return Settled(
                charge=settled.receipt.charge, receipt=settled, remaining=None, entries=()
            )

        attempted = self._attempt(closed, amount, presented_by)

        completed: _Completed | None = None
        charge: RailCharge
        try:
            with self._pool.connection() as conn:
                completed = self._charge_and_record(
                    conn, closed, amount=amount, payment=payment, presented_by=presented_by
                )
        except _DidNotComplete as incomplete:
            # The ``try`` is outside the ``with`` and has to be. Leaving the connection
            # block by way of an exception is what rolls the accumulator back, so the
            # ceiling is untouched by a charge that did not happen; catching it inside
            # would let the block end normally and commit the draw-down.
            charge = incomplete.charge
        except (CeilingExceeded, NotSettleable) as refused:
            # The Desk's own rules, applied inside the transaction because that is where
            # the lock is. They end the settlement too, so they write an ending too: an
            # attempt with nothing after it has one meaning and it is not this one.
            self._incomplete(closed, amount, presented_by, reasoning=str(refused))
            raise

        if completed is not None:
            return Settled(
                charge=completed.charge,
                receipt=completed.receipt,
                remaining=completed.remaining,
                entries=(attempted, completed.entry),
            )

        incomplete_entry = self._incomplete(
            closed,
            amount,
            presented_by,
            reasoning=(
                f"the rail did not complete a charge of {amount}, so no money moved "
                f"and no receipt exists: {charge.status}"
            ),
            charge=charge,
        )
        return Settled(
            charge=charge, receipt=None, remaining=None, entries=(attempted, incomplete_entry)
        )

    def _attempt(
        self, closed: ClosedCheckoutMandate, amount: Money, presented_by: AgentIdentity
    ) -> AuditEntry:
        """Record that the Desk is about to try to settle, on its own transaction.

        Its own, so that it survives the rollback a charge that did not complete causes.
        Written *before* the transaction opens rather than inside it beside the rail
        call: taking a second connection from the pool while already holding a locked row
        is how a pool deadlocks under load, and this is the one path in the system where
        that would strand a charge.

        What that costs is that the ceiling refusal now happens after this line, so it
        has to write its own ending -- which ``_incomplete`` does. What it must not cost
        is the meaning of a *dangling* attempt: one with nothing after it says the Desk
        called the rail and never heard back, and every other path ends in something.
        """
        return self._trail.record(
            actor="desk",
            event_type=EventType.SETTLEMENT_ATTEMPTED,
            subject_id=presented_by.agent_id,
            payload={
                "reasoning": f"the deal closed at {amount}, so the Desk is charging for it",
                "evidence": _evidence(closed, amount),
                "state_change": {"settlement": "attempted"},
            },
        )

    def _incomplete(
        self,
        closed: ClosedCheckoutMandate,
        amount: Money,
        presented_by: AgentIdentity,
        *,
        reasoning: str,
        charge: RailCharge | None = None,
    ) -> AuditEntry:
        """One settlement that ended without money moving, whoever ended it.

        ``charge`` is there when the rail answered and absent when the Desk stopped
        before asking it, which is how a reader tells those apart -- rather than by a
        reason code, which would mean something this is not. See the module docstring.
        """
        evidence: dict[str, Any] = _evidence(closed, amount)
        if charge is not None:
            evidence["rail"] = charge.as_claim()
        return self._trail.record(
            actor="desk",
            event_type=EventType.SETTLEMENT_INCOMPLETE,
            subject_id=presented_by.agent_id,
            payload={
                "reasoning": reasoning,
                "evidence": evidence,
                "state_change": {"settlement": "did not complete"},
            },
        )

    def _read(self, closed_mandate: str) -> ClosedCheckoutMandate:
        try:
            return read_closed_checkout(closed_mandate, key=self._mandate_key)
        except ValueError as exc:
            raise NotSettleable(
                f"this is not a closed Checkout Mandate the Desk signed, so there is "
                f"nothing here it agreed to charge for: {exc}"
            ) from exc

    @staticmethod
    def _chains_to(
        closed: ClosedCheckoutMandate,
        checkout: MandateOutcome[OpenCheckoutMandate],
        payment: MandateOutcome[OpenPaymentMandate],
    ) -> None:
        """Both links, checked here, because a receipt is about to swear to all three.

        The chain a receipt binds is only evidence if the Desk *checked* that the three
        go together. It is handed them as three separate arguments, so nothing about
        being passed together makes them a chain.

        **Closed to open Checkout.** The closed mandate says which authorisation it was
        negotiated under, and that has to be the one in hand.

        **Payment to open Checkout.** AP2 pairs the two open mandates by the Payment
        Mandate's ``payment.reference``, and check 3 already checks it -- but check 3
        checked *its* pair, and this method is handed its own. A caller that supplied one
        deal's Checkout Mandate beside an unrelated Payment Mandate would otherwise get a
        signed receipt naming an authorisation that had nothing to do with the deal, and
        a ceiling drawn down on a human who never authorised any of it. So it is checked
        again rather than assumed, the same way and under the same algorithm.
        """
        if checkout.mandate is None or checkout.mandate_id is None or checkout.presentation is None:
            raise NotSettleable(
                f"settlement charges against a Checkout Mandate check 2 verified, and "
                f"this one did not ({checkout.reason_code})"
            )
        if payment.mandate is None or payment.digest is None:
            raise NotSettleable(
                f"settlement draws against a Payment Mandate check 2 verified, and this "
                f"one did not ({payment.reason_code})"
            )
        if closed.checkout.open_checkout != checkout.mandate_id.value:
            raise NotSettleable(
                "this closed deal was negotiated under a different open Checkout "
                "Mandate from the one presented with it, so the chain a receipt would "
                "bind is not a chain"
            )
        # Digested under the *payment* mandate's algorithm, which is what AP2 fixes the
        # reference to and need not be the checkout mandate's own. ``desk/spend/check.py``
        # sets out why re-digesting beats reusing whichever digest was already to hand.
        reference = digest_of(checkout.presentation, algorithm=payment.digest.algorithm)
        if payment.mandate.checkout_reference != reference.value:
            raise NotSettleable(
                "this Payment Mandate authorises spending for a different open Checkout "
                "Mandate from the one this deal was negotiated under, so charging "
                "against it would draw down a ceiling nobody granted for this purchase"
            )

    def _charge_and_record(
        self,
        conn: Connection[Any],
        closed: ClosedCheckoutMandate,
        *,
        amount: Money,
        payment: MandateOutcome[OpenPaymentMandate],
        presented_by: AgentIdentity,
    ) -> _Completed:
        """Everything that has to happen together, on one transaction.

        Ordered so that the cheap refusals come before the money. The advisory lock and
        the second look for an existing receipt close the concurrent case the primary
        key would otherwise catch only after a charge. The accumulator is drawn down
        before the rail is called so that its ceiling refusal -- which is the Desk's own
        rule -- happens while there is still nothing to unwind.
        """
        deal = closed.checkout_hash.value
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_lock_key(deal),))
        already = self._receipts.find(deal, conn=conn)
        if already is not None:
            raise NotSettleable(
                f"this deal was settled by another caller while this one was working. "
                f"Its receipt is {already.receipt_id}."
            )

        ledger = self._accumulator.record_spend(payment, amount=amount, conn=conn)

        charge = self._rail.charge(
            Charge(
                amount=amount,
                reference=deal,
                agent_id=presented_by.agent_id,
                description=DESCRIPTION,
            )
        )
        if not charge.completed:
            raise _DidNotComplete(charge)

        assert payment.mandate_id is not None, "record_spend refuses an unverified mandate"
        signed = issue_receipt(
            closed,
            payment_mandate=payment.mandate_id,
            charge=charge,
            charged=amount,
            agent_id=presented_by.agent_id,
            signed_by=self._receipt_key,
        )
        receipt = self._receipts.store(signed, conn=conn)
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.RECEIPT_ISSUED,
            subject_id=presented_by.agent_id,
            conn=conn,
            payload={
                "reasoning": (
                    f"the rail took {amount} and the Desk signed a receipt for it, "
                    f"leaving {ledger.remaining} on the mandate"
                ),
                "evidence": {
                    **_evidence(closed, amount),
                    "rail": charge.as_claim(),
                    "receipt_id": receipt.receipt_id,
                    "remaining": str(ledger.remaining.amount),
                },
                "state_change": {"settlement": "receipt issued"},
            },
        )
        return _Completed(
            charge=charge, receipt=receipt, remaining=ledger.remaining, entry=entry
        )


@dataclass(frozen=True)
class _Completed:
    """The four things a charge that completed produced, carried out of the transaction.

    Private, and one object rather than a tuple, because ``Settled`` is what a caller
    reads and this is only the shape the pieces travel in for the two statements
    between the commit and building it.
    """

    charge: RailCharge
    receipt: IssuedReceipt
    remaining: Money
    entry: AuditEntry


class _DidNotComplete(Exception):
    """Carries the rail's answer out of the transaction, rolling it back on the way.

    Private, and never seen by a caller. A charge that did not complete is an ordinary
    outcome reported in ``Settled``; this exists only because rolling a transaction back
    means leaving its block, and leaving it with a value would commit.
    """

    def __init__(self, charge: RailCharge) -> None:
        super().__init__(f"the rail did not complete the charge: {charge.status}")
        self.charge = charge


def _evidence(closed: ClosedCheckoutMandate, amount: Money) -> dict[str, Any]:
    """What every settlement entry carries, whichever way it went.

    The same fields on all three entries rather than the interesting ones on each, for
    the reason the negotiation's entries share a shape: a metric computed over the trail
    should not have to know which event type carries which field.
    """
    return {
        "mandate_chain": {
            "open_checkout": closed.checkout.open_checkout,
            "closed_checkout": closed.checkout_hash.value,
        },
        "agreed": {
            "total": str(closed.checkout.total.amount),
            "currency": closed.checkout.currency,
            "terms": dict(closed.checkout.terms),
        },
        "charged": str(amount.amount),
    }


def _lock_key(deal: str) -> int:
    """A stable 64-bit key for one deal, for ``pg_advisory_xact_lock``.

    Namespaced and hashed rather than taken from the digest's own bytes, so that this
    lock and any other advisory lock in the system are drawn from independent spaces.
    """
    digest = hashlib.blake2b(_LOCK_NAMESPACE + deal.encode("ascii"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)

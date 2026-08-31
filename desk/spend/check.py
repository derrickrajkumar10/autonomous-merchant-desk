"""Check 3 -- spend authority. Is what is being asked for inside what was authorised?

Check 2 proved a human authorised *something*, and that this agent is the one allowed
to present it. That is a smaller claim than it sounds: a mandate to buy two kilos of
coffee under 2,000 rupees is a perfectly valid mandate to present when asking for a
laptop, and check 2 would pass it. This check is where the authorisation is finally
read for what it says.

Six questions, deterministic every one of them (FR-3.1), and ordered so that the five
the Desk can answer from memory run before the one that reads state:

1. **Do these two mandates belong together?** The Payment Mandate's mandatory
   ``payment.reference`` constraint carries the digest of the Checkout Mandate it was
   signed for. Without this, an agent holding a generous budget for one errand could
   present it beside somebody else's shopping list.
2. **Is this the thing that was authorised?** The item's id must appear in some
   ``checkout.line_items`` requirement's ``acceptable_items``.
3. **Is there a ceiling at all?** A Payment Mandate with no ``payment.budget`` is
   refused. AP2 leaves the constraint optional, and a mandate without one bounds
   nothing; the Desk will not read *unbounded* as *authorised*.
4. **Is the request in the currency that ceiling is written in?** The Desk holds no
   exchange rate, and converting would manufacture authority nobody gave.
5. **Is the payment inside its execution window?** ``payment.execution_date``'s
   ``not_before`` and ``not_after``, against two instants: the date the mandate names
   for itself, and now. Distinct from the ``exp`` check 2 already ran, which cannot
   express *authorised, but not until Monday*.
6. **Is there enough left?** AP2's own rule -- the requested amount plus the
   accumulated total, at or under ``max``.

Only the last touches the database, which is the whole reason it is last.

Three of the refusals land on ``category_not_authorised`` -- the mismatched pairing,
the wrong product, the wrong currency. The reason set is closed (ADR-0006) and all
three are the same sentence about a different noun: *authority for one thing is not
authority for another*. This is the move check 2 already makes with
``mandate_signature_invalid``, and the specific reasoning is in the entry either way.

**The mandate is never rewritten.** Not here, not anywhere. It is a signed credential
and re-signing it would need the principal's key, which lives in the wallet and never
comes near the Desk (ADR-0004). The ceiling is read from the mandate; the running
total against it is the Desk's own state, which is what AP2 specifies too -- the
verifier tracks it.

Passing says the request is inside the authorisation. It says nothing about whether
this presentation is a replay (check 4) or whether the text carried with it is trying
to talk the Desk into something (check 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.identity import AgentIdentity

# From the submodules and not from ``desk.mandate`` itself; see the note on the same
# imports in ``accumulator.py`` for the cycle that makes the difference.
from desk.mandate.check import MandateOutcome
from desk.mandate.checkout import ALLOWED_MERCHANTS_CONSTRAINT, OpenCheckoutMandate
from desk.mandate.open_mandate import OpenMandate
from desk.mandate.payment import OpenPaymentMandate
from desk.mandate.sdjwt import MandateDigest, digest_of
from desk.spend.accumulator import BudgetAccumulator, MandateSpend
from desk.spend.money import Money

M = TypeVar("M", bound=OpenMandate)


@dataclass(frozen=True)
class SpendRequest:
    """What a buyer agent is asking to buy, and for how much.

    One item rather than a basket. AP2's full ``checkout.line_items`` evaluation is a
    maximal-flow match over a whole checkout -- quantities, and no requirement spent
    twice -- and it belongs with the closed mandate the negotiation produces. The
    question the PRD asks of check 3 is the narrower one: is this the *category* the
    principal authorised, for an amount inside the ceiling they set.
    """

    item_id: str
    amount: Money


@dataclass(frozen=True)
class SpendOutcome:
    """What check 3 concluded, and the entry it wrote concluding it.

    ``remaining`` is what would be left if this deal closed for the amount asked. It
    is present only on a pass, and it is a **forecast rather than a reservation**:
    nothing is drawn down until a deal actually closes and calls the accumulator, so
    two requests evaluated a moment apart can both be told the same number.
    """

    remaining: Money | None
    reason_code: ReasonCode | None
    entry: AuditEntry

    @property
    def passed(self) -> bool:
        return self.remaining is not None


class SpendAuthorityCheck:
    """Evaluate one request against the two mandates check 2 verified."""

    def __init__(self, accumulator: BudgetAccumulator, trail: AuditTrail) -> None:
        self._accumulator = accumulator
        self._trail = trail

    def evaluate(
        self,
        request: SpendRequest,
        *,
        presented_by: AgentIdentity,
        checkout: MandateOutcome[OpenCheckoutMandate],
        payment: MandateOutcome[OpenPaymentMandate],
    ) -> SpendOutcome:
        """Check 3 on one request. Every outcome, pass or refusal, is recorded.

        ``checkout`` and ``payment`` are check 2's outputs, not claims. Evaluating a
        request against a mandate that has not verified would be evaluating it against
        whatever the sender chose to write, so a refused outcome is a caller's
        mistake here and raises rather than refusing again.
        """
        checkout_mandate, _checkout_digest, checkout_presentation = _verified(checkout, "checkout")
        payment_mandate, payment_digest, _ = _verified(payment, "payment")

        # AP2 fixes the hash a payment.reference is taken under: "the _sd_alg algorithm
        # for the SD-JWT this constraint is in" (docs/ap2/payment_mandate.md:231-235).
        # The constraint sits in the *payment* mandate, whose _sd_alg need not be the one
        # the checkout mandate was digested under -- so the comparison digest is taken
        # here rather than reusing whichever one check 2 happened to compute. Requiring
        # the two mandates to agree on an algorithm instead would refuse a conformant
        # pair, and say something untrue about why.
        reference = digest_of(checkout_presentation, algorithm=payment_digest.algorithm)
        if payment_mandate.checkout_reference != reference.value:
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.CATEGORY_NOT_AUTHORISED,
                reasoning=(
                    "the payment mandate authorises spending for a different checkout "
                    "mandate to the one presented with it, so it is not authority for "
                    "this purchase"
                ),
                request=request,
                evidence={
                    "references_checkout": payment_mandate.checkout_reference,
                    "checkout_presented": reference.value,
                    "digest_algorithm": reference.algorithm,
                },
            )

        # A constraint the Desk cannot evaluate is a constraint it cannot honour, and
        # honouring a mandate by ignoring part of it is the one thing the disclosure
        # rule in sdjwt._resolve exists to prevent -- reached by ignoring a constraint
        # rather than by dropping one, which is the same hole from the other side.
        # Evaluating this needs the Desk's own merchant identity, which nothing models
        # yet; until it does, a mandate that sets it is refused rather than assumed to
        # allow us.
        if checkout_mandate.constraint(ALLOWED_MERCHANTS_CONSTRAINT) is not None:
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.CATEGORY_NOT_AUTHORISED,
                reasoning=(
                    f"the mandate restricts which merchants it may be spent with, and the "
                    f"Desk cannot yet evaluate {ALLOWED_MERCHANTS_CONSTRAINT}; it will not "
                    f"honour a mandate by ignoring one of the principal's constraints"
                ),
                request=request,
                evidence={"unevaluated_constraint": ALLOWED_MERCHANTS_CONSTRAINT},
            )

        if not checkout_mandate.authorises_item(request.item_id):
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.CATEGORY_NOT_AUTHORISED,
                reasoning=(
                    f"the mandate does not authorise {request.item_id!r}; authority for "
                    f"one thing is not authority for another"
                ),
                request=request,
                evidence={"authorised_items": list(checkout_mandate.authorised_item_ids())},
            )

        budget = payment_mandate.budget
        if budget is None:
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.EXCEEDS_REMAINING_BALANCE,
                reasoning=(
                    "the payment mandate sets no payment.budget ceiling, so nothing in "
                    "it bounds what may be spent; the Desk will not read an absent "
                    "ceiling as an unlimited one"
                ),
                request=request,
                evidence={"ceiling": None},
            )

        if budget.currency != request.amount.currency:
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.CATEGORY_NOT_AUTHORISED,
                reasoning=(
                    f"the mandate authorises spending in {budget.currency} and this "
                    f"request is in {request.amount.currency}; the Desk holds no "
                    f"exchange rate and will not convert one authority into another"
                ),
                request=request,
                evidence={"ceiling": f"{budget.maximum} {budget.currency}"},
            )

        now = datetime.now(UTC)
        executes_at = payment_mandate.execution_date or now
        window = payment_mandate.execution_window
        if window is not None:
            # Two instants, and the second is the one that matters. A mandate naming its
            # own execution_date would otherwise be checked only against dates written on
            # itself -- "is 1 April inside 1 to 30 April" -- which is a question about
            # whether the mandate agrees with itself, and has the same answer for ever. A
            # window compared to nothing but that is a window that never closes.
            if not window.contains(executes_at):
                return self._refuse(
                    presented_by=presented_by,
                    reason=ReasonCode.OUTSIDE_VALIDITY_WINDOW,
                    reasoning=(
                        "the mandate names an execution date outside the window it "
                        "authorises payment in, so it does not agree with itself"
                    ),
                    request=request,
                    evidence=_window_evidence(payment_mandate, executes_at, now),
                )
            if not window.contains(now):
                return self._refuse(
                    presented_by=presented_by,
                    reason=ReasonCode.OUTSIDE_VALIDITY_WINDOW,
                    reasoning=(
                        "the window the principal authorised this payment in is not open; "
                        "a date written on the mandate is not a date on the calendar"
                    ),
                    request=request,
                    evidence=_window_evidence(payment_mandate, executes_at, now),
                )

        ledger = self._accumulator.spent_against(payment)
        if not ledger.covers(request.amount):
            return self._refuse(
                presented_by=presented_by,
                reason=ReasonCode.EXCEEDS_REMAINING_BALANCE,
                reasoning=(
                    f"{request.amount} would take the total spent against this mandate "
                    f"to {ledger.spent + request.amount}, past the {ledger.ceiling} its "
                    f"principal authorised"
                ),
                request=request,
                evidence=_ledger_evidence(ledger),
            )

        remaining = ledger.remaining - request.amount
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_3_SPEND_AUTHORITY_PASSED,
            subject_id=presented_by.agent_id,
            payload={
                "check": 3,
                "reasoning": (
                    f"{request.item_id!r} is among the items the mandate authorises, and "
                    f"{request.amount} fits inside the {ledger.remaining} left of the "
                    f"{ledger.ceiling} its principal authorised"
                ),
                "evidence": _requested(request)
                | _ledger_evidence(ledger)
                | _window_evidence(payment_mandate, executes_at, now)
                | {"would_leave": str(remaining)},
                # Authorised, not yet spent. Nothing is drawn down until a deal closes,
                # and this request has not been checked for replay or inspected yet.
                "state_change": {"request": "within spend authority"},
            },
        )
        return SpendOutcome(remaining=remaining, reason_code=None, entry=entry)

    def _refuse(
        self,
        *,
        presented_by: AgentIdentity,
        reason: ReasonCode,
        reasoning: str,
        request: SpendRequest,
        evidence: dict[str, Any],
    ) -> SpendOutcome:
        entry = self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_3_SPEND_AUTHORITY_REFUSED,
            subject_id=presented_by.agent_id,
            reason_code=reason,
            payload={
                "check": 3,
                "reasoning": reasoning,
                "evidence": _requested(request) | evidence,
                "state_change": {"request": "refused"},
            },
        )
        return SpendOutcome(remaining=None, reason_code=reason, entry=entry)


def _verified(outcome: MandateOutcome[M], which: str) -> tuple[M, MandateDigest, str]:
    """What is inside a check-2 outcome, or a raise saying there is nothing inside it.

    The presentation comes back alongside the mandate because the digest that has to be
    compared is not always the digest check 2 happened to take -- see the pairing step.
    """
    if outcome.mandate is None or outcome.digest is None or outcome.presentation is None:
        raise ValueError(
            f"check 3 evaluates a request against mandates check 2 verified, and the "
            f"{which} mandate did not verify ({outcome.reason_code}). A refusal is an "
            f"answer already; running a later check on it would invent a second one."
        )
    return outcome.mandate, outcome.digest, outcome.presentation


def _requested(request: SpendRequest) -> dict[str, Any]:
    """What was asked for, on every outcome. Amounts as strings, because they are money.

    A ``Decimal`` is not JSON, and rendering one as a float on the way into the trail
    would put a number in the record that differs from the number that was evaluated.
    """
    return {"requested_item": request.item_id, "requested_amount": str(request.amount)}


def _ledger_evidence(ledger: MandateSpend) -> dict[str, Any]:
    """The three numbers behind every balance decision.

    "Exceeds the remaining balance" is an assertion until the ceiling, the accumulated
    total and what is left are all in the entry beside it.
    """
    return {
        "mandate_id": ledger.mandate_id,
        "ceiling": str(ledger.ceiling),
        "already_spent": str(ledger.spent),
        "remaining": str(ledger.remaining),
    }


def _window_evidence(
    mandate: OpenPaymentMandate, executes_at: datetime, now: datetime
) -> dict[str, Any]:
    """The window the mandate set and the two instants it was compared against.

    ``executes_at`` is the mandate's own ``execution_date`` where it set one, and
    otherwise now -- AP2's "when absent indicates immediate execution". ``evaluated_at``
    is when the Desk was asked. They are recorded separately because they answer two
    different questions, and a refusal is unreadable without knowing which one failed.
    """
    window = mandate.execution_window
    return {
        "executes_at": executes_at.isoformat(),
        "evaluated_at": now.isoformat(),
        "not_before": (
            None if window is None or window.not_before is None else window.not_before.isoformat()
        ),
        "not_after": (
            None if window is None or window.not_after is None else window.not_after.isoformat()
        ),
    }

"""The trust spine: four deterministic checks, in one order, stopping at the first no.

Each of checks 1 to 4 already knows how to answer its own question and write its own
entry. What none of them knows is *when it runs*, and that is the whole of this
module. It is short on purpose. There is nothing clever here, and there must not be.

**The order is a security property, not a performance tuning.** Identity, then mandate
validity, then spend authority, then replay and freshness -- cheapest and most certain
first (CONTEXT.md section 5, principle 2). Running them the other way round would spend
database work, and later a model call, on traffic that a signature check would have
eliminated; worse, it would let the expensive probabilistic parts of the Desk form
opinions about requests that were never authentic in the first place.

**A refusal stops everything after it.** Not as an optimisation -- as the thing the
trail has to be able to prove. If check 1 refuses, there is no check-2 entry, no
check-3 entry and no check-4 entry, because those checks did not happen. A later check
running anyway would put a sentence in the record about a request the Desk had already
declined to believe, and the record is the product here.

**Nothing here calls a model.** Not this module and not anything the four checks reach.
That is a claim made on camera and it is asserted in the suite rather than promised in
prose (``tests/spine/test_no_model_call.py``).

Two mandates and two hops. AP2 v0.2 splits an authorisation into a Checkout Mandate
saying what may be bought and a Payment Mandate saying what may be spent, so check 2
runs twice and check 4 runs twice -- once per presentation, because RFC 9901's
``sd_hash`` binds a proof of possession to exactly one. Both runs sit at the same
position, and a refusal in either is a refusal at that position. One consequence is
worth an agent author's attention: the two hops must carry **different nonces**, since
the Desk honours a nonce once per agent and a request reusing one across both mandates
refuses its own second half as a replay.

What passing means is deliberately small. Four checks passed, at one instant, for one
request whose nonces are now spent. It is not a pass to be presented later, not a
capability, and not something to cache and consult later: check 5 has not run, no
price has been agreed and no money has moved.

    from desk.spine import TrustSpine

    spine = TrustSpine(
        IdentityCheck(registry, trail),
        MandateCheck(principals, trail),
        SpendAuthorityCheck(BudgetAccumulator(pool), trail),
        FreshnessCheck(NonceStore(pool), trail),
        trail,
    )
    outcome = spine.receive(signed_request)
    if not outcome.passed:
        ...            # outcome.refused_at names the check, outcome.reason_code the reason
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.freshness import FreshnessCheck
from desk.identity import AgentIdentity, IdentityCheck
from desk.mandate import MandateCheck, MandateOutcome, OpenCheckoutMandate, OpenPaymentMandate
from desk.spend import Money, SpendAuthorityCheck, SpendRequest
from desk.spine.request import PurchaseRequest, read_purchase_request


@dataclass(frozen=True)
class Check:
    """One position in the spine: which check, and what it is called out loud."""

    position: int
    name: str

    def __str__(self) -> str:
        return f"check {self.position} ({self.name})"


#: The order. Written once, read by the trail's self-check below and by the suite, so
#: that reordering the spine is a visible edit to a named sequence rather than two
#: statements quietly swapped inside a method.
ORDER: tuple[Check, ...] = (
    Check(1, "identity"),
    Check(2, "mandate validity"),
    Check(3, "spend authority"),
    Check(4, "replay and freshness"),
)

IDENTITY, MANDATE_VALIDITY, SPEND_AUTHORITY, REPLAY_AND_FRESHNESS = ORDER


class SpineOutOfOrder(RuntimeError):
    """The checks did not run in ``ORDER``, so the Desk stopped rather than continue.

    Raised by the spine against its own work, never by a counterparty's doing. It is
    here because the ordering is the security property this module exists to hold, and
    a refactor that broke it would otherwise show up as nothing at all until someone
    read the trail months later.
    """


@dataclass(frozen=True)
class SpineOutcome:
    """What the four checks concluded about one request, and the entries they wrote.

    A report about a request that has already been spent, not an authority to spend it
    again. Its nonces are used up, and by the time anything reads this the moment it
    describes has passed -- so nothing downstream should keep it and treat "the checks
    passed" as still true later. Check 5 and negotiation take the *contents* -- the
    identity, the two verified mandates, the amount that fits -- and reach their own
    conclusions.
    """

    identity: AgentIdentity | None
    request: PurchaseRequest | None
    checkout: MandateOutcome[OpenCheckoutMandate] | None
    payment: MandateOutcome[OpenPaymentMandate] | None
    remaining: Money | None
    refused_at: Check | None
    reason_code: ReasonCode | None
    entries: tuple[AuditEntry, ...]

    def __post_init__(self) -> None:
        _in_order(self.positions, refused_at=self.refused_at)

    @property
    def passed(self) -> bool:
        """All four checks, in order, with nothing left to stop on."""
        return self.refused_at is None

    @property
    def positions(self) -> tuple[int, ...]:
        """Which check each entry came from, in the order the entries were written."""
        return tuple(int(entry.payload["check"]) for entry in self.entries)


class TrustSpine:
    """Run checks 1 to 4 over one signed request, in order, stopping at the first no."""

    def __init__(
        self,
        identity: IdentityCheck,
        mandate: MandateCheck,
        spend: SpendAuthorityCheck,
        freshness: FreshnessCheck,
        trail: AuditTrail,
    ) -> None:
        self._identity = identity
        self._mandate = mandate
        self._spend = spend
        self._freshness = freshness
        self._trail = trail

    def receive(self, request: str) -> SpineOutcome:
        """One signed request, all the way through the deterministic spine.

        The single entry point, and the seam the whole suite drives: everything a buyer
        agent can do to the Desk before negotiation, it does by handing a string to this
        method. Nothing here reads the request except through check 1, because until
        check 1 has run the bytes are a stranger's and not a request.
        """
        entries: list[AuditEntry] = []

        one = self._identity.verify(request)
        entries.append(one.entry)
        if one.identity is None or one.body is None:
            return self._refused(IDENTITY, one.reason_code, entries)
        identity = one.identity
        purchase = read_purchase_request(one.body)

        checkout = self._mandate.verify(purchase.checkout, presented_by=identity)
        entries.append(checkout.entry)
        if not checkout.passed:
            return self._refused(
                MANDATE_VALIDITY, checkout.reason_code, entries, identity=identity
            )

        payment = self._mandate.verify_payment(purchase.payment, presented_by=identity)
        entries.append(payment.entry)
        if not payment.passed:
            return self._refused(
                MANDATE_VALIDITY,
                payment.reason_code,
                entries,
                identity=identity,
                checkout=checkout,
            )

        if purchase.amount is None:
            entries.append(self._no_amount(purchase, presented_by=identity))
            return self._refused(
                SPEND_AUTHORITY,
                ReasonCode.EXCEEDS_REMAINING_BALANCE,
                entries,
                identity=identity,
                checkout=checkout,
                payment=payment,
            )

        three = self._spend.evaluate(
            SpendRequest(item_id=purchase.item_id, amount=purchase.amount),
            presented_by=identity,
            checkout=checkout,
            payment=payment,
        )
        entries.append(three.entry)
        if not three.passed:
            return self._refused(
                SPEND_AUTHORITY,
                three.reason_code,
                entries,
                identity=identity,
                checkout=checkout,
                payment=payment,
            )

        # Check 4 last, and both presentations here rather than one beside check 2, so
        # that a request refused for what it asks for never spends a nonce. A nonce is
        # spent once and never returned: honouring one on the way to a refusal would let
        # a prober burn an honest agent's presentations by sending requests it already
        # knew the Desk would decline.
        # Annotated because ``MandateOutcome`` is invariant: a Checkout outcome and a
        # Payment outcome have no common parameterisation, and check 4 reads either
        # through ``OpenMandate`` -- the hop is a property of the presentation, not of
        # which kind of mandate it presents.
        presentations: tuple[MandateOutcome[Any], ...] = (checkout, payment)
        for presented in presentations:
            four = self._freshness.evaluate(presented, presented_by=identity)
            entries.append(four.entry)
            if not four.passed:
                return self._refused(
                    REPLAY_AND_FRESHNESS,
                    four.reason_code,
                    entries,
                    identity=identity,
                    checkout=checkout,
                    payment=payment,
                )

        return SpineOutcome(
            identity=identity,
            request=purchase,
            checkout=checkout,
            payment=payment,
            remaining=three.remaining,
            refused_at=None,
            reason_code=None,
            entries=tuple(entries),
        )

    def _no_amount(self, purchase: PurchaseRequest, *, presented_by: AgentIdentity) -> AuditEntry:
        """Refuse, at check 3's position, a request that never said what it would spend.

        The spine writes this one and check 3 does not, because there is no amount for
        check 3 to evaluate: a check that reasons about money cannot be handed a request
        with no money in it, and inventing a zero to hand it would be inventing a request
        the agent did not send. It is recorded at check 3's position under check 3's
        reason code because it is check 3's question that goes unanswered -- the mirror
        of the refusal that check does write for a mandate setting no ceiling. Neither an
        absent ceiling nor an absent price is read as authority.
        """
        return self._trail.record(
            actor="desk",
            event_type=EventType.CHECK_3_SPEND_AUTHORITY_REFUSED,
            subject_id=presented_by.agent_id,
            reason_code=ReasonCode.EXCEEDS_REMAINING_BALANCE,
            payload={
                "check": SPEND_AUTHORITY.position,
                "reasoning": (
                    "the Desk cannot read a price out of this request; a price is an "
                    "amount and the currency it is in, and one of those is missing or is "
                    "not one the Desk reads. An unreadable price is not a free one"
                ),
                "evidence": {"item_id": purchase.item_id, "stated": dict(purchase.stated_price)},
                "state_change": {"request": "refused"},
            },
        )

    def _refused(
        self,
        at: Check,
        reason_code: ReasonCode | None,
        entries: Sequence[AuditEntry],
        *,
        identity: AgentIdentity | None = None,
        checkout: MandateOutcome[OpenCheckoutMandate] | None = None,
        payment: MandateOutcome[OpenPaymentMandate] | None = None,
    ) -> SpineOutcome:
        """The run as it stands, stopped at ``at``. What is carried is what was proven.

        Everything the refusing check had already established is kept -- the identity if
        check 1 passed, the checkout mandate if check 2 passed on it -- and everything
        after it is absent, because it was never established.
        """
        return SpineOutcome(
            identity=identity,
            request=None,
            checkout=checkout,
            payment=payment,
            remaining=None,
            refused_at=at,
            reason_code=reason_code,
            entries=tuple(entries),
        )


def _in_order(positions: Sequence[int], *, refused_at: Check | None) -> None:
    """Assert this run walked ``ORDER`` from the start and stopped where it says it did.

    Three things, and the last two are the ones worth having. The positions never go
    backwards and never skip: a run recording checks 1, 2 and 4 skipped spend authority,
    and one recording 1, 3, 2 evaluated a spend against a mandate not yet shown to be
    valid. Then the end of the run has to agree with the verdict -- a refusal stops at
    the position it names, and a pass reaches the last check rather than merely running
    out of statements.

    That last clause is the one a refactor needs. Dropping the freshness loop would leave
    every refusal test passing and every ordering test passing, and would report a
    request as having cleared a check that never ran.
    """
    reached = 0
    for position in positions:
        if position not in (reached, reached + 1):
            raise SpineOutOfOrder(
                f"the spine ran {list(positions)}, which is not "
                f"{[check.position for check in ORDER]} walked from the start; the order of "
                f"the checks is the property this module exists to hold, so the run is "
                f"stopped rather than recorded as sound"
            )
        reached = position

    stopped = ORDER[-1] if refused_at is None else refused_at
    if reached != stopped.position:
        raise SpineOutOfOrder(
            f"the spine ran {list(positions)} and reports stopping at {stopped}; a run "
            f"that reports passing has to reach {ORDER[-1]}, and one that reports a "
            f"refusal has to end on the check that refused"
        )

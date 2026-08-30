"""One negotiation, from the request that cleared the spine to a close or a walk-away.

This is the object that actually talks. The policy decides *what* to say; this decides
when the conversation is over, what gets written down, and what artefact comes out of
the end of it.

**A negotiation begins where the spine finished.** ``Desk.open`` takes a passed
``SpineOutcome`` and nothing else: the identity is check 1's, the items that may be
bought are read off the Checkout Mandate check 2 verified, and the amount that fits is
check 3's. Nothing here re-reads a mandate or believes a field a counterparty sent about
its own authority. An outcome that did not pass is a caller's mistake and raises, in the
same spirit as check 3 refusing to evaluate against an unverified mandate.

**A round carries no new authority, so it presents no new mandate.** The buyer proved
who it was, and that a human authorised this category of purchase, once -- at the front
door. Haggling does not need proving again, and re-presenting the mandates every round
would spend a nonce per round on a question already answered. The authority is spent at
the *end*, when the closed mandate names the open one it was negotiated under and the
settlement step draws the amount down.

**The bound exists for one counterparty.** ``ROUNDS`` is not a performance guard. An
adversarial buyer that never concedes would otherwise hold a conversation open for ever,
and the Desk cannot tell that buyer from a slow honest one -- so it counts, and at the
bound it walks with the same reason code and the same event type as any other walk-away.
There is no separate "timed out" outcome, because from the Desk's side there is no
separate thing that happened: nothing closed the gap.

**Both endings are terminal and both are recorded.** A closed deal writes
``deal_closed``; a walk-away writes ``walked_away`` under ``below_margin_floor``. Neither
is an incident. CONTEXT.md section 6 bans the word *failure* for the second one, and the
reason is not politeness: metrics that counted correct refusals as failures would teach
the Desk, and later the bandit, to close everything.

    deal = desk.open(outcome, tier=TrustTier.NEW)
    reply = deal.receive(Ask(sku="SKU-COFFEE-1KG", quantity=2))
    reply = deal.receive(Ask(sku="SKU-COFFEE-1KG", quantity=2, target_unit_price=asked))
    if reply.move is Move.COUNTER:
        closed = deal.accept()
        closed.closed_mandate      # the terms, signed
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from desk.audit import AuditEntry, AuditTrail, EventType, ReasonCode
from desk.catalogue import Catalogue, Margin, Product, UnknownProduct
from desk.identity import AgentIdentity, DeskKeypair
from desk.mandate import AgreedCharge, AgreedItem, Checkout, close_checkout
from desk.negotiation.ask import Ask
from desk.negotiation.lever import Lever
from desk.negotiation.policy import FixedPolicy, Move, Policy, Position, Proposal
from desk.negotiation.rationale import Rationale
from desk.negotiation.terms import Terms, TermsSheet
from desk.negotiation.tier import TrustTier
from desk.spend import Money
from desk.spine import SpineOutcome

#: How many buyer messages one negotiation will answer before the Desk walks. Six is
#: enough for an opening quote, three genuine exchanges, and a last word -- and short
#: enough that a counterparty which never moves finds out quickly. The bound is here
#: rather than in the policy because it is about the conversation, not the deal.
ROUNDS = 6


class NegotiationOver(RuntimeError):
    """A message arrived on a deal that has already closed or been walked away from.

    Not a refusal, because there is nobody left to refuse: the outcome is written, the
    trail has it, and answering again would put a second ending in the record for one
    negotiation.
    """


@dataclass(frozen=True)
class DeskMessage:
    """What the Desk said, why it said it, and what came out of it.

    ``rationale`` is on every one of these, not on the interesting ones (FR-5.4).
    ``closed_mandate`` appears exactly once per negotiation and only on an agreement.
    """

    move: Move
    #: On an acceptance or a counter, the price on the table. On a walk-away, the closest
    #: the Desk could have got -- which is not an offer, and is here so a reader can see
    #: how far apart the two parties were.
    offer_unit_price: Money
    quantity: int
    terms: Terms
    lever: Lever | None
    rationale: Rationale
    entry: AuditEntry
    closed_mandate: str | None = None

    @property
    def closed(self) -> bool:
        return self.move is Move.ACCEPT

    @property
    def walked_away(self) -> bool:
        return self.move is Move.WALK_AWAY


class Desk:
    """The selling half of the Desk: opens negotiations and holds what they need.

    One object per running Desk, sharing the catalogue, the terms it trades on, its own
    signing key and the trail. The policy is a constructor argument so that ticket 21 can
    hand it a bandit without this file changing, and so that the fixed one stays runnable
    beside it (FR-6.3).
    """

    def __init__(
        self,
        catalogue: Catalogue,
        sheet: TermsSheet,
        trail: AuditTrail,
        signing_key: DeskKeypair,
        *,
        policy: Policy | None = None,
        rounds: int = ROUNDS,
    ) -> None:
        if rounds < 1:
            raise ValueError("a negotiation that answers no messages is not a negotiation")
        self._catalogue = catalogue
        self._sheet = sheet
        self._trail = trail
        self._key = signing_key
        self._policy = FixedPolicy() if policy is None else policy
        self._rounds = rounds

    def open(self, outcome: SpineOutcome, *, tier: TrustTier) -> Negotiation:
        """Begin a negotiation with the agent whose request just cleared checks 1 to 4."""
        if not outcome.passed or outcome.identity is None or outcome.checkout is None:
            raise ValueError(
                "a negotiation opens on a request that passed the spine; one that was "
                "refused has nothing to negotiate about, and opening on it would put a "
                "conversation in the trail after a refusal that ended it"
            )
        mandate = outcome.checkout.mandate
        mandate_id = outcome.checkout.mandate_id
        assert mandate is not None and mandate_id is not None, (
            "a passed check-2 outcome carries its mandate and the digest naming it"
        )
        return Negotiation(
            catalogue=self._catalogue,
            sheet=self._sheet,
            trail=self._trail,
            key=self._key,
            policy=self._policy,
            rounds=self._rounds,
            identity=outcome.identity,
            authorised=mandate.authorised_item_ids(),
            # ``mandate_id`` and not ``digest``: the closed mandate names the open one
            # for ever, and a digest that varied with which disclosures a holder chose to
            # send would name the same authorisation differently on two presentations of
            # it. ``sdjwt.signed_digest_of`` sets out why the two digests differ.
            open_checkout=mandate_id.value,
            tier=tier,
        )


class Negotiation:
    """One deal in progress. Not constructed directly; ``Desk.open`` makes one."""

    def __init__(
        self,
        *,
        catalogue: Catalogue,
        sheet: TermsSheet,
        trail: AuditTrail,
        key: DeskKeypair,
        policy: Policy,
        rounds: int,
        identity: AgentIdentity,
        authorised: tuple[str, ...],
        open_checkout: str,
        tier: TrustTier,
    ) -> None:
        self._catalogue = catalogue
        self._sheet = sheet
        self._trail = trail
        self._key = key
        self._policy = policy
        self._rounds = rounds
        self._identity = identity
        self._authorised = authorised
        self._open_checkout = open_checkout
        self._tier = tier
        self._round = 0
        self._standing: Proposal | None = None
        self._over = False

    @property
    def rounds_used(self) -> int:
        """How many buyer messages have been answered. Read by tests and the trail."""
        return self._round

    @property
    def over(self) -> bool:
        return self._over

    def receive(self, ask: Ask) -> DeskMessage:
        """Answer one buyer message. Every answer is recorded, whatever it says."""
        if self._over:
            raise NegotiationOver("this negotiation has already ended")

        self._round += 1
        position = self._position(ask)
        proposal = self._policy.propose(position)

        # The bound. Checked after the policy has spoken so that a buyer whose last
        # message was acceptable still closes on it -- walking away from a deal the Desk
        # would have taken would be the bound costing money rather than saving time.
        if proposal.move is not Move.ACCEPT and self._round >= self._rounds:
            return self._walk(
                ask,
                proposal,
                reasoning=(
                    f"{self._rounds} rounds and the gap has not closed; the Desk stops "
                    f"rather than hold a conversation open indefinitely"
                ),
            )

        if proposal.move is Move.WALK_AWAY:
            return self._walk(
                ask,
                proposal,
                reasoning=(
                    "no arrangement the Desk can offer reaches what this buyer will pay, "
                    "so there is nothing further to put on the table"
                ),
            )

        if proposal.move is Move.ACCEPT:
            return self._close(ask, proposal)

        self._standing = proposal
        return self._counter(ask, proposal)

    def accept(self) -> DeskMessage:
        """Close on the offer standing on the table. The buyer's yes.

        Nothing is re-decided. The standing proposal was tested against the floor when it
        was made, and re-running the policy here would let a deal the buyer agreed to come
        back different -- which is the one thing an acceptance may not do.
        """
        if self._over:
            raise NegotiationOver("this negotiation has already ended")
        if self._standing is None:
            raise NegotiationOver(
                "there is nothing on the table to accept; the Desk has made no offer"
            )
        return self._close(None, self._standing)

    def _position(self, ask: Ask) -> Position:
        """What the policy is allowed to see, assembled from verified sources only."""
        try:
            product = self._catalogue.product(ask.sku)
        except UnknownProduct:
            raise
        return Position(
            ask=ask,
            product=product,
            companions=self._companions(ask.sku),
            sheet=self._sheet,
            tier=self._tier,
            round=self._round,
        )

    def _companions(self, sku: str) -> tuple[Product, ...]:
        """Stocked products the *principal* authorised, other than the one being asked for.

        Read off the verified mandate rather than off the ask. A bundle whose companion
        nobody authorised would be the Desk selling something a human never agreed to
        buy, arrived at through a lever -- which is check 3's refusal reached by a side
        door, and is why this filtering does not live in the policy.
        """
        stocked = {product.sku: product for product in self._catalogue.products()}
        return tuple(
            stocked[item_id]
            for item_id in self._authorised
            if item_id in stocked and item_id != sku
        )

    def _close(self, ask: Ask | None, proposal: Proposal) -> DeskMessage:
        """Agreement: sign what was agreed, record it, and end the negotiation."""
        self._over = True
        rationale = _rationale(ask, proposal, lever=proposal.lever)
        agreed_at = datetime.now(UTC)
        mandate = close_checkout(
            Checkout(
                open_checkout=self._open_checkout,
                currency=proposal.offer.currency,
                items=tuple(
                    AgreedItem(
                        item_id=line.product.sku,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                    )
                    for line in proposal.offer.lines
                ),
                charges=tuple(
                    AgreedCharge(label=charge.label, amount=charge.revenue)
                    for charge in proposal.offer.charges
                    if charge.revenue.amount > 0
                ),
                terms=proposal.terms.as_claims(),
                agreed_at=agreed_at,
            ),
            signed_by=self._key,
            issued_at=int(agreed_at.timestamp()),
        )
        entry = self._record(
            EventType.DEAL_CLOSED,
            reason_code=None,
            ask=ask,
            proposal=proposal,
            rationale=rationale,
            reasoning=(
                f"agreed at {proposal.unit_price} each, which the Desk can sell at: "
                f"{proposal.margin}"
            ),
            state_change={"deal": "closed"},
        )
        return DeskMessage(
            move=Move.ACCEPT,
            offer_unit_price=proposal.unit_price,
            quantity=proposal.offer.lines[0].quantity,
            terms=proposal.terms,
            lever=proposal.lever,
            rationale=rationale,
            entry=entry,
            closed_mandate=mandate,
        )

    def _counter(self, ask: Ask, proposal: Proposal) -> DeskMessage:
        """A counter-offer, and the lever entry beside it when one was offered.

        Two entries rather than one when a lever is on the table, because ``lever_offered``
        is what the metrics count and what ticket 21 learns from -- and reading it out of a
        message payload would make "how often did the Desk bundle" a query over free text.
        """
        rationale = _rationale(ask, proposal, lever=proposal.lever)
        entry = self._record(
            EventType.NEGOTIATION_MESSAGE_SENT,
            reason_code=None,
            ask=ask,
            proposal=proposal,
            rationale=rationale,
            reasoning=(
                f"the Desk can do {proposal.unit_price} each on these terms: {proposal.margin}"
            ),
            state_change={"deal": "in negotiation"},
        )
        if proposal.lever is not None:
            self._record(
                EventType.LEVER_OFFERED,
                reason_code=None,
                ask=ask,
                proposal=proposal,
                rationale=rationale,
                reasoning=(
                    f"a straight concession on price does not hold, so the Desk offered a "
                    f"{proposal.lever.value.replace('_', ' ')} instead"
                ),
                state_change={"lever": proposal.lever.value},
            )
        return DeskMessage(
            move=Move.COUNTER,
            offer_unit_price=proposal.unit_price,
            quantity=proposal.offer.lines[0].quantity,
            terms=proposal.terms,
            lever=proposal.lever,
            rationale=rationale,
            entry=entry,
        )

    def _walk(self, ask: Ask, proposal: Proposal, *, reasoning: str) -> DeskMessage:
        """A walk-away, recorded as the completed negotiation it is."""
        self._over = True
        # A walk-away's rationale is about the deal that was *refused* and not about the
        # one the Desk could have reached. ``below_margin_floor`` is a statement about the
        # buyer's number, and reporting the Desk's own reachable margin here would record
        # a walk-away as sitting comfortably inside its floor -- true of a deal that never
        # happened, and the opposite of an explanation.
        #
        # And no lever, for the same reason: the proposal carries the best arrangement
        # available, which is worth having in the evidence, but nothing was put on the
        # table and a rationale naming a lever would say something that did not happen.
        rationale = _rationale(
            ask, proposal, lever=None, margin=proposal.asked_margin or proposal.margin
        )
        entry = self._record(
            EventType.WALKED_AWAY,
            reason_code=ReasonCode.BELOW_MARGIN_FLOOR,
            ask=ask,
            proposal=proposal,
            rationale=rationale,
            reasoning=reasoning,
            # Not "refused" and not "aborted". The negotiation ran and reached an
            # outcome; the outcome is that no deal was worth doing.
            state_change={"deal": "walked away"},
        )
        return DeskMessage(
            move=Move.WALK_AWAY,
            offer_unit_price=proposal.unit_price,
            quantity=proposal.offer.lines[0].quantity,
            terms=proposal.terms,
            lever=proposal.lever,
            rationale=rationale,
            entry=entry,
        )

    def _record(
        self,
        event_type: EventType,
        *,
        reason_code: ReasonCode | None,
        ask: Ask | None,
        proposal: Proposal,
        rationale: Rationale,
        reasoning: str,
        state_change: dict[str, str],
    ) -> AuditEntry:
        """One entry, carrying everything FR-6.1 requires of a negotiation record.

        Product, trust tier, stated constraints, lever and realised margin, on every
        entry rather than spread across several. A later policy has to be trainable from
        the trail without a re-run, and a field that only appears on the closing entry is
        a field the rounds before it do not have.
        """
        return self._trail.record(
            actor="desk",
            event_type=event_type,
            subject_id=self._identity.agent_id,
            reason_code=reason_code,
            payload={
                "round": self._round,
                "reasoning": reasoning,
                "evidence": {
                    "product": proposal.offer.lines[0].product.sku,
                    "trust_tier": self._tier.value,
                    "stated": None if ask is None else ask.stated(),
                    "offered": {
                        "unit_price": str(proposal.unit_price),
                        "quantity": proposal.offer.lines[0].quantity,
                        "terms": proposal.terms.as_claims(),
                        "bundled": [line.product.sku for line in proposal.offer.lines[1:]],
                    },
                    "reachable": str(proposal.unit_price),
                    "rationale": rationale.as_payload(),
                },
                "state_change": state_change,
            },
        )


def _rationale(
    ask: Ask | None,
    proposal: Proposal,
    *,
    lever: Lever | None,
    margin: Margin | None = None,
) -> Rationale:
    """The FR-5.4 object for one message: what was asked, and where the margin landed."""
    if ask is None:
        asked = "the offer on the table"
    elif ask.target_unit_price is None:
        asked = f"a price for {ask.quantity} x {ask.sku}"
    else:
        asked = f"{ask.target_unit_price} each for {ask.quantity} x {ask.sku}"
    return Rationale(
        asked=asked, margin=proposal.margin if margin is None else margin, lever=lever
    )

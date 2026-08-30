"""The fixed policy: which lever to reach for, at what price, and when to stop talking.

This is the ticket's judgement, and it is deliberately a *fixed* one. FR-6.3 makes it the
baseline the learned policy of ticket 21 is measured against over identical deals, and a
learned curve with nothing beside it is decoration that must not ship. So it is built to
last rather than to be replaced: ``Policy`` is the seam the bandit slots into, and this
implementation has to remain runnable after it does.

**The shape of a deal, not just its price.** A negotiation position can be arranged
several ways -- alone, with a companion beside it, at a larger quantity, on faster
delivery, paid for up front. Each arrangement is a ``Shape``, and each has a different
least price it can be sold at, because each brings a different amount of margin with it.
The policy works out that least price for every shape available and reasons about the
resulting numbers rather than about the levers themselves.

**The least price is solved and then verified.** The algebra is exact -- the condition
``profit >= floor x revenue`` rearranges into a division, once. But the carry cost is
rounded to a real amount of money before it is charged, so the solved price can be a
paisa out. Rather than trust it, the policy rounds up to the scale the product is priced
at and then asks ``margin_on`` whether it actually holds, stepping up until it does. The
function that decides is the same one that decides everywhere else. A policy with its own
private notion of "just inside the floor" is how a floor gets crossed by nobody's
decision.

**Three answers and no fourth.** Accept what was asked, counter with something that
holds, or walk away. There is no "ask again later" and no "refer to a human" -- the Desk
is autonomous, and a fourth answer would be a place for one to hide.

**When it walks.** Not when the buyer is below the floor -- that is the ordinary case and
the whole reason levers exist. It walks when the buyer's number is below the best price
any available arrangement could reach, by more than ``REACH``. The reasoning is about the
conversation rather than about the deal: a buyer that far out is not one concession away,
and countering would spend rounds on an outcome that is already known. The engine walks
for a second reason -- the round bound -- and that one is about a counterparty that never
concedes at all.

**It does not read the trust tier.** See ``tier.py``: pricing by reputation in the
*fixed* policy would make ticket 21's comparison meaningless.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, localcontext
from enum import StrEnum
from typing import Protocol

from desk.catalogue import Line, Margin, Offer, Product, margin_on
from desk.negotiation.ask import Ask
from desk.negotiation.lever import CONSIDERED, Lever
from desk.negotiation.terms import Delivery, Payment, Terms, TermsSheet
from desk.negotiation.tier import TrustTier
from desk.spend import Money

#: How far below the Desk's best reachable price a buyer may sit and still be worth
#: talking to. A tenth: close enough that one concession plausibly closes it, far enough
#: that a buyer offering half is not strung along for six rounds. This is a judgement
#: about conversations rather than about margin, and it is the one number here that a
#: reasonable person could set differently.
REACH = Decimal("0.10")

#: Working precision for the solve. Headroom rather than a rounding policy, matching
#: ``desk.catalogue.margin``: an implausible number of digits raises rather than
#: silently rounding into a different price.
_PRECISION = 60

#: How many scale steps the verifier will take past the solved price before deciding
#: the solve and the margin function disagree about something other than rounding.
#: Reached only by a defect, never by a counterparty.
_STEPS = 4


class PriceUnreachable(RuntimeError):
    """The solved price and ``margin_on`` disagree by more than rounding could explain.

    Raised by the Desk against its own arithmetic, never by anything a counterparty
    sends. It is here because a policy that quietly returned a price the floor refuses
    would close deals under the floor, and that is the one thing this package may not do.
    """


class Move(StrEnum):
    """What the Desk is doing in this message. Three answers and no fourth."""

    ACCEPT = "accept"
    COUNTER = "counter"
    WALK_AWAY = "walk_away"


@dataclass(frozen=True)
class Shape:
    """One arrangement of a deal, and the lever that produced it.

    ``companions`` are priced at list and are not negotiated. That is what makes a
    bundle a lever rather than a second negotiation: the Desk is offering to sell
    something else at its ordinary price so that the pair carries a concession on the
    first thing.
    """

    lever: Lever | None
    quantity: int
    companions: tuple[Line, ...]
    terms: Terms

    def offer(self, product: Product, unit_price: Money, sheet: TermsSheet) -> Offer:
        """This arrangement, priced. The object ``margin_on`` decides about."""
        lines = (Line(product=product, quantity=self.quantity, unit_price=unit_price),) + (
            self.companions
        )
        goods = _total(line.revenue for line in lines)
        return Offer.of(*lines, charges=sheet.charges(self.terms, goods=goods))


@dataclass(frozen=True)
class Position:
    """Everything the policy is allowed to look at. Nothing here is unverified.

    ``companions`` have already been filtered to products the principal's mandate
    authorises, because the Desk will not put something in a bundle that nobody said it
    could buy. That filtering is the engine's, and doing it there rather than here is
    what stops a policy -- this one or a learned one -- reaching past a constraint.
    """

    ask: Ask
    product: Product
    companions: tuple[Product, ...]
    sheet: TermsSheet
    tier: TrustTier
    round: int


@dataclass(frozen=True)
class Proposal:
    """What the policy decided, and the offer it decided about.

    An offer is present on a walk-away too -- the best arrangement the Desk could have
    made, so that a reader can see how far apart the two parties actually were rather
    than only that they were apart.

    ``asked_margin`` is the other half of that, and it is the one a walk-away is
    *about*: the margin on the deal the buyer actually proposed, which is the thing
    sitting under the floor. Absent when the buyer named no price, because there is then
    no proposed deal for it to be the margin of.
    """

    move: Move
    offer: Offer
    terms: Terms
    lever: Lever | None
    unit_price: Money
    asked_margin: Margin | None = None

    @property
    def margin(self) -> Margin:
        return margin_on(self.offer)


class Policy(Protocol):
    """The seam ticket 21's bandit slots into, and the reason this file survives it."""

    def propose(self, position: Position) -> Proposal: ...


class FixedPolicy:
    """Reach for the first lever that works, in a fixed order, and never cross the floor."""

    def propose(self, position: Position) -> Proposal:
        shapes = _shapes(position)
        plain = shapes[0]

        # No number named. This is a request for a quote rather than a haggle, so the
        # Desk answers with one: list price, standard terms, no lever spent on a
        # conversation that has not started.
        if position.ask.target_unit_price is None:
            return self._quote(position, plain)

        asked = position.ask.target_unit_price
        if asked > position.product.list_price:
            # A buyer offering above list is answered at list. Taking the higher number
            # would be the Desk profiting from a mistake, and the trail would record it.
            return self._quote(position, plain)

        # What the buyer asked for, exactly as asked, with nothing traded for it. Its
        # margin is carried on every answer from here down, because it is the number a
        # refusal is about and the one FR-5.4 means by "whether it sits inside the floor".
        on_the_ask = margin_on(plain.offer(position.product, asked, position.sheet))
        if on_the_ask.inside_floor:
            return _proposal(Move.ACCEPT, position, plain, asked, asked_margin=on_the_ask)

        # It does not hold on its own. Does it hold inside some arrangement the buyer's
        # own stated constraints make available? This is FR-5.3's sentence: the discount
        # is declined and something else is offered in the same message.
        for shape in shapes[1:]:
            if margin_on(shape.offer(position.product, asked, position.sheet)).inside_floor:
                return _proposal(Move.COUNTER, position, shape, asked, asked_margin=on_the_ask)

        # Nothing reaches the buyer's number. Find the closest the Desk can get.
        best = _best(position, shapes)
        if best is None:
            # No arrangement holds at any price the Desk would name. Nothing to discuss.
            return _proposal(
                Move.WALK_AWAY,
                position,
                plain,
                position.product.list_price,
                asked_margin=on_the_ask,
            )

        shape, price = best
        move = Move.WALK_AWAY if _out_of_reach(asked, price) else Move.COUNTER
        return _proposal(move, position, shape, price, asked_margin=on_the_ask)

    def _quote(self, position: Position, plain: Shape) -> Proposal:
        """List price on ordinary terms -- and a walk-away if even that does not hold."""
        price = position.product.list_price
        offer = plain.offer(position.product, price, position.sheet)
        move = Move.COUNTER if margin_on(offer).inside_floor else Move.WALK_AWAY
        return _proposal(move, position, plain, price)


def _shapes(position: Position) -> tuple[Shape, ...]:
    """The plain arrangement first, then one per lever the position makes available.

    Availability is not the policy's judgement about what is *best* -- that is what
    ticket 21 learns. It is a fact about the position: a quantity break needs a buyer
    that would take more, a bundle needs a product the principal authorised, and the two
    that change the terms need a buyer that said it wanted them.
    """
    ask = position.ask
    shapes = [Shape(lever=None, quantity=ask.quantity, companions=(), terms=Terms())]

    for lever in CONSIDERED:
        if lever is Lever.BUNDLE:
            companion = _companion(position)
            if companion is not None:
                shapes.append(
                    Shape(
                        lever=lever,
                        quantity=ask.quantity,
                        companions=(
                            Line(product=companion, quantity=1, unit_price=companion.list_price),
                        ),
                        terms=Terms(),
                    )
                )
        elif lever is Lever.QUANTITY_BREAK:
            if ask.largest_quantity is not None and ask.largest_quantity > ask.quantity:
                shapes.append(
                    Shape(
                        lever=lever,
                        quantity=ask.largest_quantity,
                        companions=(),
                        terms=Terms(),
                    )
                )
        elif lever is Lever.DELIVERY_SPEED:
            if ask.wants_it_faster:
                shapes.append(
                    Shape(
                        lever=lever,
                        quantity=ask.quantity,
                        companions=(),
                        terms=Terms(delivery=Delivery.EXPRESS),
                    )
                )
        elif ask.can_prepay:
            shapes.append(
                Shape(
                    lever=lever,
                    quantity=ask.quantity,
                    companions=(),
                    terms=Terms(payment=Payment.PREPAID),
                )
            )
    return tuple(shapes)


def _companion(position: Position) -> Product | None:
    """Which authorised product to put beside this one, chosen the same way every time.

    Two rules, and the first one is what stops this lever being absurd.

    **A companion may not be worth more than the thing being asked for.** The arithmetic
    alone would happily sell a kilo of coffee at 300 rupees beside a 75,000 rupee laptop,
    because the pair clears the floor comfortably -- and it is a real answer to the wrong
    question. A buyer who asked for coffee is not one small concession away from buying a
    laptop, and an offer built on the assumption that it might be is a merchant not
    listening. A bundle is an add-on to a deal, not a deal with an add-on.

    **Then the most surplus at list, with the sku breaking a tie.** Surplus rather than
    margin rate, because what a bundle needs is *rupees* to carry the concession and a
    high rate on a cheap thing brings few of them. Deterministic because ticket 21
    replays identical deal specs against this policy as a baseline, and a companion
    chosen by iteration order would make two runs of the same deal different deals.
    """
    with localcontext() as context:
        context.prec = _PRECISION
        ceiling = position.product.list_price.amount * position.ask.quantity
    candidates = [
        product
        for product in position.companions
        if product.sku != position.product.sku and product.list_price.amount <= ceiling
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda product: (_surplus_at_list(product), product.sku))


def _surplus_at_list(product: Product) -> Decimal:
    return margin_on(
        Offer.of(Line(product=product, quantity=1, unit_price=product.list_price))
    ).surplus


def _best(position: Position, shapes: Sequence[Shape]) -> tuple[Shape, Money] | None:
    """The lowest unit price any available arrangement can be sold at, and which one.

    Ties go to the arrangement considered first, which is the plain one -- so the Desk
    only records a lever when the lever actually bought something.
    """
    found: tuple[Shape, Money] | None = None
    for shape in shapes:
        price = _least_price(position, shape)
        if price is None:
            continue
        if found is None or price < found[1]:
            found = (shape, price)
    return found


def _least_price(position: Position, shape: Shape) -> Money | None:
    """The least the Desk can charge per unit in this arrangement, or ``None``.

    Solved, then verified. The solve rearranges ``profit >= floor x revenue`` for the
    unit price; the verification asks ``margin_on``, because the carry cost is rounded
    to a real amount of money before it is charged and the solved price can be a paisa
    short of covering it.
    """
    product = position.product
    solved = _solve(position, shape)
    if solved is None:
        return None

    step = product.price_scale()
    candidate = max(solved.quantize(step, rounding=ROUND_CEILING), Decimal(0))

    for _ in range(_STEPS):
        if candidate > product.list_price.amount:
            # The arrangement cannot be sold below list, so list is the only price worth
            # naming. It holds, or this is not an arrangement the Desk can offer at all.
            return _if_it_holds(position, shape, product.list_price)
        held = _if_it_holds(position, shape, Money(amount=candidate, currency=product.currency))
        if held is not None:
            return held
        candidate = candidate + step
    raise PriceUnreachable(
        f"the solved price for {product.sku} in a {shape.lever or 'plain'} arrangement "
        f"still does not clear its floor {_STEPS} steps later; the solve and margin_on "
        f"disagree about something that is not rounding"
    )


def _if_it_holds(position: Position, shape: Shape, price: Money) -> Money | None:
    """This price, if the offer it makes clears the floor. The verification step."""
    offer = shape.offer(position.product, price, position.sheet)
    return price if margin_on(offer).inside_floor else None


def _solve(position: Position, shape: Shape) -> Decimal | None:
    """Rearrange ``profit >= floor x revenue`` for the unit price. The only division here.

    Writing the condition out, with ``p`` the unit price and ``q`` the quantity::

        (p.q + Rc + Er) - (k.q + Cc + H + Ec + c.(p.q + Rc))  >=  f.p.q + Fc

    where ``Rc``, ``Cc`` and ``Fc`` are the companions' revenue, cost and floor
    requirement, ``H`` is handling, ``Er`` and ``Ec`` the express premium and its
    courier bill, ``c`` the carry rate and ``k`` the unit cost. Collecting ``p``::

        p >= [ Fc - Rc.(1 - c) + k.q + Cc + H + Ec - Er ] / [ q.(1 - c - f) ]

    ``None`` when the denominator is not positive: the floor plus the cost of carrying
    the money asks for more of the revenue than the revenue has, so no price clears it
    and raising the price does not help.
    """
    product = position.product
    quantity = shape.quantity
    carry = position.sheet.carry[shape.terms.payment]

    companions = shape.companions
    companion_revenue = sum((line.revenue.amount for line in companions), Decimal(0))
    companion_cost = sum((line.cost.amount for line in companions), Decimal(0))
    companion_floor = sum(
        (line.product.margin_floor * line.revenue.amount for line in companions), Decimal(0)
    )

    express_revenue = Decimal(0)
    express_cost = Decimal(0)
    if shape.terms.delivery is Delivery.EXPRESS:
        express_revenue = position.sheet.express_premium.amount
        express_cost = position.sheet.express_cost.amount

    with localcontext() as context:
        context.prec = _PRECISION
        denominator = quantity * (Decimal(1) - carry - product.margin_floor)
        if denominator <= 0:
            return None
        numerator = (
            companion_floor
            - companion_revenue * (Decimal(1) - carry)
            + product.cost.amount * quantity
            + companion_cost
            + position.sheet.handling.amount
            + express_cost
            - express_revenue
        )
        return numerator / denominator


def _out_of_reach(asked: Money, best: Money) -> bool:
    """Whether the gap is too wide for a conversation rather than merely too wide today."""
    with localcontext() as context:
        context.prec = _PRECISION
        return asked.amount < best.amount * (Decimal(1) - REACH)


def _proposal(
    move: Move,
    position: Position,
    shape: Shape,
    price: Money,
    *,
    asked_margin: Margin | None = None,
) -> Proposal:
    return Proposal(
        move=move,
        offer=shape.offer(position.product, price, position.sheet),
        terms=shape.terms,
        lever=shape.lever,
        unit_price=price,
        asked_margin=asked_margin,
    )


def _total(amounts: Iterable[Money]) -> Money:
    """Add up money that is already known to be one currency."""
    running: Money | None = None
    for amount in amounts:
        running = amount if running is None else running + amount
    assert running is not None, "an offer has at least one line"
    return running

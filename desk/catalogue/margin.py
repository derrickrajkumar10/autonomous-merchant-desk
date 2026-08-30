"""Margin on a proposed deal, and the one comparison that decides whether it holds.

An **offer** is what the Desk is prepared to put on the table: one or more **lines**,
each a product, a quantity and a unit price it is proposing right now. The price is
the negotiable part and lives here rather than on the product, because the product is
what the Desk sells and the offer is what it is currently saying about it.

Three ideas, and the third is the one worth reading twice.

**Margin is a share of revenue, not a markup on cost.** Sell for 899 what cost 420 and
the margin is 479/899, about 53 percent -- not 479/420, about 114. Both numbers are
computable and only one of them makes a floor comparable across products, because only
one of them is bounded above by 1. The vocabulary says *margin floor* and this is what
it means.

**A bundle has one margin, not several.** A three-line offer is added up and decided
once. The alternative -- every line clearing its own floor -- would forbid exactly the
move FR-5.3 exists for: refusing a discount alone and granting it beside something
that carries the difference. So ``LineMargin`` deliberately has no verdict on it. The
breakdown is for explaining a decision, never for making one.

**A deal is not only goods.** Getting a thing to a buyer costs something; getting it
there by Friday costs more, and the buyer may pay for that. Those amounts belong to
this deal at these terms rather than to any product, so they ride on the offer as
``Charge`` -- revenue, cost, and no floor of their own. See that class for why the
floor is the lines' and not theirs.

The floor a bundle is held to is **what its lines ask for, added up**: each line wants
``floor x its own revenue``, and the offer must earn the total. Read back as a
percentage that is a revenue-weighted blend of the lines' floors. Two alternatives were
available and are worse. Taking the *strictest* line's floor punishes a bundle for
containing one careful product. Taking a plain average of the percentages ignores that
one line may be ninety percent of the money.

**Nothing divides.** Margin *rate* is a division, so it is the only inexact number in
this module -- reported to six places, and the decision never touches it. Whether an
offer holds is ``profit >= floor x revenue``, which is multiplication and subtraction
over exact decimals and has no rounding in it at all. The difference is not academic:
``tests/catalogue/test_margin.py`` carries a deal that reads as inside the floor on the
rounded rate and is a rupee short on the exact comparison.

Profit is a signed ``Decimal`` rather than ``Money``, because ``Money`` refuses to be
negative and a loss is not an amount the Desk holds. That the two types differ is the
useful part: a losing deal is expressible, and the type system stops the loss being
handed to the spend accumulator by accident.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from desk.catalogue.product import Product
from desk.spend import CurrencyMismatch, Money

#: Places the reported margin rate is rounded to. Display only -- see the module
#: docstring. Six is enough to read a basis point off and few enough to fit a line.
RATE_PLACES = Decimal("0.000001")

#: Places a percentage is rendered at in the rationale line, which is ``RATE_PLACES``
#: moved two along, so the printed number loses nothing the rate held.
PERCENT_PLACES = Decimal("0.0001")

#: Working precision for the exact comparison. Every operation under it is a
#: multiplication or a subtraction of two finite decimals, so this is headroom rather
#: than a rounding policy: it exists so that an amount with an implausible number of
#: digits raises out of the default 28-digit context instead of silently rounding into
#: a different verdict.
_PRECISION = 60


@dataclass(frozen=True)
class Line:
    """One product on an offer, at a quantity and at a price being proposed for it."""

    product: Product
    quantity: int
    unit_price: Money

    def __post_init__(self) -> None:
        if not isinstance(self.product, Product):
            raise TypeError(f"a line is about a Product, not a {type(self.product).__name__}")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError(f"a quantity is a whole count, not a {type(self.quantity).__name__}")
        if self.quantity < 1:
            raise ValueError(
                f"a line of {self.product.sku} is for at least one of the thing; a line "
                f"of none is not an offer to sell it, it is silence about it"
            )
        if not isinstance(self.unit_price, Money):
            raise TypeError(f"a unit price is Money, not a {type(self.unit_price).__name__}")
        if self.unit_price.currency != self.product.currency:
            raise CurrencyMismatch(
                f"{self.product.sku} is priced in {self.product.currency} and this line "
                f"offers it at {self.unit_price}; the Desk holds no exchange rate"
            )

    @property
    def revenue(self) -> Money:
        return self.unit_price * self.quantity

    @property
    def cost(self) -> Money:
        return self.product.cost * self.quantity


@dataclass(frozen=True)
class Charge:
    """Something on a deal that is not a product: express delivery, or handling.

    Two shapes, and the pair is what makes two of the negotiation's levers arithmetic
    rather than theatre:

    - **Revenue and cost.** Express delivery charged at a premium. The buyer pays more,
      the courier takes some of it, and the difference is margin the goods did not have
      to find.
    - **Cost and no revenue.** The fixed work of putting one deal out of the door, which
      does not double when the order does. A larger quantity spreads it thinner, which
      is why a quantity break can clear a floor that the same unit price on a single
      item cannot.

    **A charge carries no floor of its own.** A margin floor is a promise about what the
    Desk earns on what it *sells*, and a courier's share is not that. So a charge
    contributes its profit to what the lines already asked for and asks nothing itself,
    which is precisely how an express premium comes to fund a concession on the goods.

    The dilution this invites is closed by ownership rather than by arithmetic: charges
    are written by the Desk's own terms and are never read off a request, so no
    counterparty can add a zero-cost charge to lower the share its goods have to earn.
    """

    label: str
    revenue: Money
    cost: Money

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError(
                "a charge is named, because an unnamed amount on a deal is one nobody "
                "can explain afterwards"
            )
        for role, amount in (("revenue", self.revenue), ("cost", self.cost)):
            if not isinstance(amount, Money):
                raise TypeError(f"a charge's {role} is Money, not a {type(amount).__name__}")
        if self.revenue.currency != self.cost.currency:
            raise CurrencyMismatch(
                f"the {self.label} charge takes {self.revenue} and costs {self.cost}; the "
                f"Desk holds no exchange rate"
            )

    @classmethod
    def of(
        cls, label: str, *, revenue: Decimal | int | str, cost: Decimal | int | str, currency: str
    ) -> Charge:
        """A charge written the way a terms table writes one: strings, one currency."""
        return cls(
            label=label,
            revenue=Money.of(revenue, currency),
            cost=Money.of(cost, currency),
        )

    @property
    def currency(self) -> str:
        return self.revenue.currency


@dataclass(frozen=True)
class Offer:
    """What the Desk is proposing: one or more lines, all in one currency."""

    lines: tuple[Line, ...]
    charges: tuple[Charge, ...] = ()

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValueError(
                "an offer is at least one line; there is no margin on nothing, and "
                "reporting zero would be a claim about a deal that does not exist"
            )
        first = self.lines[0].product.currency
        for line in self.lines:
            if line.product.currency != first:
                raise CurrencyMismatch(
                    f"this offer mixes {first} and {line.product.currency}; a combined "
                    f"margin across two currencies would need an exchange rate the "
                    f"Desk does not hold"
                )
        for charge in self.charges:
            if not isinstance(charge, Charge):
                raise TypeError(f"a charge is a Charge, not a {type(charge).__name__}")
            if charge.currency != first:
                raise CurrencyMismatch(
                    f"this offer is in {first} and its {charge.label} charge is in "
                    f"{charge.currency}; the Desk holds no exchange rate"
                )

    @classmethod
    def of(cls, *lines: Line, charges: Sequence[Charge] = ()) -> Offer:
        """The readable constructor: ``Offer.of(one_line, another_line)``."""
        return cls(lines=tuple(lines), charges=tuple(charges))

    @property
    def currency(self) -> str:
        return self.lines[0].product.currency


@dataclass(frozen=True)
class LineMargin:
    """One line's contribution to an offer, and no verdict about it.

    There is no ``inside_floor`` here on purpose. A bundle in which one line sits
    below its own floor is the ordinary case rather than a problem, so anything that
    could ask a line whether it holds would eventually refuse an offer that was
    perfectly fine. This exists to explain a decision made elsewhere.
    """

    sku: str
    quantity: int
    unit_price: Money
    revenue: Money
    cost: Money
    floor: Decimal

    @property
    def profit(self) -> Decimal:
        """Signed: negative on a line the Desk is giving away or selling under cost."""
        return self.revenue.amount - self.cost.amount

    @property
    def required_profit(self) -> Decimal:
        """What this line's own floor asks of it. Exact, and never divided by."""
        with localcontext() as context:
            context.prec = _PRECISION
            return self.floor * self.revenue.amount

    @property
    def rate(self) -> Decimal | None:
        """This line's margin, rounded for reading. ``None`` on a line given away."""
        return _rate(self.profit, self.revenue.amount)


@dataclass(frozen=True)
class ChargeMargin:
    """One charge's contribution to an offer. Like ``LineMargin``, it holds no verdict.

    No ``floor`` and no ``required_profit``, because a charge asks for nothing -- see
    ``Charge``. What it has is a profit, and that profit is what the lines get to spend.
    """

    label: str
    revenue: Money
    cost: Money

    @property
    def profit(self) -> Decimal:
        """Signed: negative on a charge the Desk absorbs, which is the usual case."""
        return self.revenue.amount - self.cost.amount

    @property
    def rate(self) -> Decimal | None:
        """This charge's margin, rounded for reading. ``None`` on one that earns nothing."""
        return _rate(self.profit, self.revenue.amount)


@dataclass(frozen=True)
class Margin:
    """The margin on a whole offer. The only thing that carries a verdict."""

    currency: str
    lines: tuple[LineMargin, ...]
    charges: tuple[ChargeMargin, ...] = ()

    @property
    def revenue(self) -> Money:
        """Everything the buyer pays: the goods, and whatever the terms charge for."""
        return total(part.revenue for part in self._parts)

    @property
    def cost(self) -> Money:
        """Everything the deal costs the Desk: the goods, the courier, the handling."""
        return total(part.cost for part in self._parts)

    @property
    def _parts(self) -> tuple[LineMargin | ChargeMargin, ...]:
        return self.lines + self.charges

    @property
    def profit(self) -> Decimal:
        """What the offer earns, signed. Not ``Money``: ``Money`` cannot be negative."""
        return self.revenue.amount - self.cost.amount

    @property
    def required_profit(self) -> Decimal:
        """What the offer's lines ask for between them. Exact, and the charges ask nothing."""
        with localcontext() as context:
            context.prec = _PRECISION
            return sum((line.required_profit for line in self.lines), Decimal(0))

    @property
    def surplus(self) -> Decimal:
        """Profit less what was asked. Negative by exactly how far the offer is short."""
        with localcontext() as context:
            context.prec = _PRECISION
            return self.profit - self.required_profit

    @property
    def inside_floor(self) -> bool:
        """Whether this offer holds. Multiplication and subtraction, no division."""
        return self.surplus >= 0

    @property
    def rate(self) -> Decimal | None:
        """The offer's margin, rounded to ``RATE_PLACES``. Reported, never decided on.

        ``None`` when the offer is being given away, because a share of nothing is not
        a number and reporting zero would read as a break-even deal.
        """
        return _rate(self.profit, self.revenue.amount)

    @property
    def floor(self) -> Decimal | None:
        """The blended floor this offer was held to, as a share of its own revenue.

        For a single line it is that product's floor exactly. For a bundle it is the
        revenue-weighted blend, which is what "what the lines ask for, added up" comes
        to when read as a percentage.
        """
        return _rate(self.required_profit, self.revenue.amount)

    def __str__(self) -> str:
        """The one-line rationale FR-5.4 puts beside every Desk reply."""
        standing = "inside by" if self.inside_floor else "short by"
        gap = f"{standing} {abs(self.surplus)} {self.currency}"
        if self.rate is None or self.floor is None:
            return (
                f"no margin on {self.revenue} revenue, floor asks "
                f"{self.required_profit} {self.currency}, {gap}"
            )
        return (
            f"margin {_percent(self.rate)}% on {self.revenue} revenue, "
            f"floor {_percent(self.floor)}%, {gap}"
        )


def margin_on(offer: Offer) -> Margin:
    """The margin on one offer, decided once over all of its lines and charges."""
    return Margin(
        currency=offer.currency,
        lines=tuple(
            LineMargin(
                sku=line.product.sku,
                quantity=line.quantity,
                unit_price=line.unit_price,
                revenue=line.revenue,
                cost=line.cost,
                floor=line.product.margin_floor,
            )
            for line in offer.lines
        ),
        charges=tuple(
            ChargeMargin(label=charge.label, revenue=charge.revenue, cost=charge.cost)
            for charge in offer.charges
        ),
    )


def total(amounts: Iterable[Money]) -> Money:
    """Add up money that is already known to be one currency.

    Public because a negotiation adds up an offer's goods before the offer exists -- the
    charges its terms put on it are computed *from* that total -- so it cannot ask a
    ``Margin`` for the number and had grown its own copy of this loop.
    """
    running: Money | None = None
    for amount in amounts:
        running = amount if running is None else running + amount
    assert running is not None, "an offer has at least one line"
    return running


def _rate(part: Decimal, whole: Decimal) -> Decimal | None:
    """A share, rounded for reading. The only division in this module."""
    if whole == 0:
        return None
    return (part / whole).quantize(RATE_PLACES, rounding=ROUND_HALF_EVEN)


def _percent(share: Decimal) -> Decimal:
    return (share * 100).quantize(PERCENT_PLACES, rounding=ROUND_HALF_EVEN)

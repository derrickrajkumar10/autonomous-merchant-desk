"""What the Desk sells: a cost, an asking price, and the floor beneath both.

A merchant that knows only its prices cannot negotiate. Asked for ten percent off it
can say yes or no, but it cannot say *why*, and it cannot tell the difference between
ten percent off something it buys for a fifth of the sale price and ten percent off
something it barely marks up at all. Both look like "ten percent".

So every product carries three numbers instead of one:

- **cost** -- what the Desk pays to have the thing.
- **list price** -- what it asks for the thing.
- **margin floor** -- the least share of a sale that may be profit.

The floor is a **fraction of revenue and never a price** (CONTEXT.md section 6). The
distinction is the reason this module exists: a price floor set once is wrong for
every product whose cost differs, and a Desk-wide discount rule is a price floor
wearing a percentage sign. A margin floor travels with the product, so the same
request gets a different answer for coffee and for a laptop -- which is the behaviour
FR-5.2 asks for, arrived at rather than special-cased.

Nothing here is negotiable state. A ``Product`` is a frozen value read off the
catalogue table; what changes during a negotiation is the price being *proposed*,
which lives on the offer (``margin.py``) and never on the product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from desk.spend import CurrencyMismatch, Money

#: Uppercase, digits and hyphens, three to sixty-four characters. This is the same
#: string check 3 matches against a Checkout Mandate's ``acceptable_items``, so a
#: product whose id could not appear there is a product no mandate could authorise.
SKU = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,62}[A-Z0-9]\Z")

#: The coarsest scale a discounted price may be rounded to: whole units of the currency.
#: A list price recorded more coarsely than that -- ``Decimal("1E+3")`` is a legitimate
#: way to write one thousand -- must not drag the discount out to the nearest thousand
#: with it. See ``Product.discounted``.
_SMALLEST_SCALE = 0


@dataclass(frozen=True)
class Product:
    """One thing the Desk sells, priced so that a margin can be computed about it."""

    sku: str
    name: str
    cost: Money
    list_price: Money
    margin_floor: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.sku, str) or not SKU.match(self.sku):
            raise ValueError(
                f"{self.sku!r} is not a sku; a sku is uppercase letters, digits and "
                f"hyphens, and it is what a mandate names when it authorises this item"
            )
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"{self.sku} has no name, and an unnamed product cannot be offered")
        for role, amount in (("cost", self.cost), ("list price", self.list_price)):
            if not isinstance(amount, Money):
                raise TypeError(f"a {role} is Money, not a {type(amount).__name__}")
        # Reached deliberately here rather than by surprise inside a margin
        # subtraction three modules away.
        if self.cost.currency != self.list_price.currency:
            raise CurrencyMismatch(
                f"{self.sku} costs {self.cost} and is listed at {self.list_price}; a "
                f"margin across two currencies would need an exchange rate the Desk "
                f"does not hold"
            )
        if not isinstance(self.margin_floor, Decimal):
            raise TypeError(
                f"a margin floor is a Decimal, not a {type(self.margin_floor).__name__}"
            )
        if not self.margin_floor.is_finite() or not (0 <= self.margin_floor < 1):
            raise ValueError(
                f"{self.sku}'s margin floor is {self.margin_floor}; a floor is a "
                f"fraction of revenue in [0, 1), and 1 would ask the whole price to be "
                f"profit"
            )
        if self.list_price.amount <= 0:
            raise ValueError(f"{self.sku} asks {self.list_price}, which is not an asking price")
        if self.list_price.amount - self.cost.amount < self.margin_floor * self.list_price.amount:
            raise ValueError(
                f"{self.sku} cannot meet its own margin floor at its own asking price: "
                f"{self.list_price} less {self.cost} leaves less than "
                f"{self.margin_floor} of {self.list_price}. Nothing could ever be sold "
                f"on these numbers, which makes them a data error rather than a policy"
            )

    @classmethod
    def of(
        cls,
        *,
        sku: str,
        name: str,
        cost: Decimal | int | str,
        list_price: Decimal | int | str,
        margin_floor: Decimal | str,
        currency: str,
    ) -> Product:
        """A product written the way a seed file writes one: strings, one currency.

        Strings rather than numbers for the same reason ``Money.of`` prefers them --
        ``margin_floor=0.30`` as a float is 0.299999999999999988897769753748, and a
        floor that is not the number somebody wrote is a floor nobody set.
        """
        if isinstance(margin_floor, float):
            raise TypeError(
                "a margin floor cannot be built from a float; pass a string or a "
                "Decimal so the floor is the one that was written"
            )
        try:
            floor = Decimal(margin_floor)
        except InvalidOperation as exc:
            raise ValueError(f"{margin_floor!r} is not a margin floor") from exc
        return cls(
            sku=sku,
            name=name,
            cost=Money.of(cost, currency),
            list_price=Money.of(list_price, currency),
            margin_floor=floor,
        )

    @property
    def currency(self) -> str:
        """The one currency this product is bought and sold in."""
        return self.list_price.currency

    def discounted(self, fraction: Decimal | str) -> Money:
        """The list price with a share taken off it, as an exact amount of money.

        A discount is a *rate*, and a rate applied to a price has to land on a real
        amount somewhere. Two decisions make that landing explicit rather than
        accidental:

        **Where it lands** is the scale the list price is written at, or whole units,
        whichever is finer. A product priced ``899.00`` discounts to the paisa; one
        priced ``899`` discounts to the rupee. The catalogue's own price says how finely
        this product is priced, which saves this module carrying a table of how many
        minor units each currency has.

        The floor under that is why ``_SMALLEST_SCALE`` exists. ``Decimal`` keeps a
        scale coarser than whole units too -- ``Decimal("1E+3")`` is one thousand
        recorded to the nearest thousand -- and quantizing a discount to *that* would
        round every price under 1,500 rupees to either the full list price or zero. A
        discount silently becoming no discount is the worst failure this method has, so
        the scale is clamped and never read straight off the price.

        **Which way it goes on a tie** is up. Half a paisa between two prices resolves
        toward the Desk, because a concession is something the Desk grants
        deliberately, not something a rounding rule hands over on its behalf.

        This computes a *candidate* price and says nothing about whether it holds.
        That is ``margin_on``'s answer, and only ever about a whole offer.
        """
        if isinstance(fraction, float):
            raise TypeError("a discount cannot be built from a float; pass a string or a Decimal")
        try:
            share = Decimal(fraction)
        except InvalidOperation as exc:
            raise ValueError(f"{fraction!r} is not a discount") from exc
        if not share.is_finite() or not (0 <= share <= 1):
            raise ValueError(
                f"{share} is not a discount; a discount is a fraction of the list "
                f"price in [0, 1], where 1 is giving the thing away"
            )
        asked = self.list_price.amount * (Decimal(1) - share)
        return Money(
            amount=asked.quantize(self._price_scale(), rounding=ROUND_HALF_UP),
            currency=self.currency,
        )

    def _price_scale(self) -> Decimal:
        """The exponent a discounted price is rounded to: the list price's, or finer."""
        exponent = self.list_price.amount.as_tuple().exponent
        assert isinstance(exponent, int), "a finite Decimal has an integer exponent"
        return Decimal(1).scaleb(min(exponent, _SMALLEST_SCALE))

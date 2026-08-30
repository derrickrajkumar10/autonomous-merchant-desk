"""The catalogue -- what the Desk sells, what it cost, and the floor beneath a deal.

Checks 1 to 4 answered whether the Desk is *allowed* to do business with whoever is
asking. Nothing so far has any opinion about whether it *should*. This is the first
piece that does, and it is deliberately the smallest one that could: it does not
negotiate, it does not decide, it does not talk to anybody. It answers one question --
*what would this deal earn, and is that enough?* -- and it answers it the same way
every time.

The one idea, and it is the vocabulary's own: a **margin floor**, not a price floor.
Products differ in what they cost, so the same discount is generous on one and
ruinous on another. Coffee bought at 420 and asked at 899 absorbs a third off. A
laptop bought at 61,000 and asked at 74,999 absorbs about four percent -- on a floor
that is *half* the coffee's. No single Desk-wide discount rule can tell those two
apart, and a merchant that reasons about price alone has no way to see the difference.

A **bundle is one deal with one margin**. That is what makes FR-5.3's lever real: the
Desk can refuse ten percent off a grinder and grant the same ten percent beside a bag
of coffee at list, because it is deciding about the pair.

    from desk.catalogue import Catalogue, Line, Offer, margin_on, install_schema
    from world.storefront import PRODUCTS

    with pool.connection() as conn:
        install_schema(conn)

    catalogue = Catalogue(pool)
    catalogue.seed(PRODUCTS)

    grinder = catalogue.product("SKU-GRINDER-BURR")
    coffee = catalogue.product("SKU-COFFEE-1KG")

    margin = margin_on(Offer.of(
        Line(product=grinder, quantity=1, unit_price=grinder.discounted("0.10")),
        Line(product=coffee, quantity=1, unit_price=coffee.list_price),
    ))
    margin.inside_floor          # True -- alone, the grinder line would not be
    str(margin)                  # the one-line rationale FR-5.4 asks for

**Which products exist is the world's business, not the Desk's.** The seed lives in
``world/storefront`` (CONTEXT.md section 7). What lives here is the model, the
arithmetic and the table -- the part a panel would ask about.
"""

from desk.catalogue.margin import (
    PERCENT_PLACES,
    RATE_PLACES,
    Charge,
    ChargeMargin,
    Line,
    LineMargin,
    Margin,
    Offer,
    margin_on,
)
from desk.catalogue.product import SKU, Product
from desk.catalogue.schema import TABLE, install_schema
from desk.catalogue.store import Catalogue, UnknownProduct

__all__ = [
    "PERCENT_PLACES",
    "RATE_PLACES",
    "SKU",
    "TABLE",
    "Catalogue",
    "Charge",
    "ChargeMargin",
    "Line",
    "LineMargin",
    "Margin",
    "Offer",
    "Product",
    "UnknownProduct",
    "install_schema",
    "margin_on",
]

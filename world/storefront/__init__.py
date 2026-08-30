"""The storefront: which products exist, and at what cost.

Environment rather than merchant (CONTEXT.md section 7). The Desk owns the model, the
margin arithmetic and the table; this owns the *contents*, because what a merchant
happens to stock is not the defensible part and should not read as though it were.

Two files: what is stocked, and what the terms of a deal cost. Both are numbers a
different merchant would write differently, and neither is a claim the Desk defends.

    from desk.catalogue import Catalogue
    from world.storefront import PRODUCTS, TERMS

    Catalogue(pool).seed(PRODUCTS)
"""

from world.storefront.products import COFFEE, GRINDER, LAPTOP, PRODUCTS
from world.storefront.terms import CURRENCY, TERMS

__all__ = ["COFFEE", "CURRENCY", "GRINDER", "LAPTOP", "PRODUCTS", "TERMS"]

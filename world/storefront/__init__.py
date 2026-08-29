"""The storefront: which products exist, and at what cost.

Environment rather than merchant (CONTEXT.md section 7). The Desk owns the model, the
margin arithmetic and the table; this owns the *contents*, because what a merchant
happens to stock is not the defensible part and should not read as though it were.

    from desk.catalogue import Catalogue
    from world.storefront import PRODUCTS

    Catalogue(pool).seed(PRODUCTS)
"""

from world.storefront.products import COFFEE, GRINDER, LAPTOP, PRODUCTS

__all__ = ["COFFEE", "GRINDER", "LAPTOP", "PRODUCTS"]

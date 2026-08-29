"""The three things the Desk sells, and why it is exactly these three.

Environment, not product (CONTEXT.md section 7). Nothing defensible lives here -- swap
this file for a different one and the Desk works identically, which is the point of
keeping it out of ``desk/``. What it has to do is make the *behaviour* under test
visible, so the three were picked to answer the same question three different ways.

Ask each of them for fifteen percent off:

===================  =====  ==========  =====  =================================
Product               Cost   List price  Floor  Answer to "fifteen percent off?"
===================  =====  ==========  =====  =================================
Coffee                 420      899.00   30%   comfortably yes, and a third off too
Burr grinder         2,400    3,499.00   25%   no, and no to ten percent either
14-inch laptop      61,000   74,999.00   15%   no, and barely yes to four
===================  =====  ==========  =====  =================================

The laptop is the one that makes the argument. Its floor is *half* the coffee's, and
it is still the one that cannot move -- because it is bought at 81 percent of what it
is asked for, and there is nothing else in the price to give. A merchant reasoning
about discount percentages alone would treat these three the same and lose money on
one of them.

The grinder is the bundle case. Ten percent off it alone leaves 749.10 where its own
floor asks 787.28, so the Desk walks. Put a kilo of coffee at list beside it and the
pair earns 1,228.10 against a combined ask of 1,056.98 -- the same discount, granted,
because the offer is what is being decided about. That is FR-5.3's lever, and it is
the beat the pitch video shows (PRD section 12, minute 0:45).

Prices are in rupees to the paisa, which is the scale a discount off them lands on.
"""

from __future__ import annotations

from desk.catalogue import Product

#: Cheap to buy, dear to sell. The product with room to concede.
COFFEE = Product.of(
    sku="SKU-COFFEE-1KG",
    name="Single-origin filter coffee, 1 kg",
    cost="420.00",
    list_price="899.00",
    margin_floor="0.30",
    currency="INR",
)

#: The middle case, and the one a bundle rescues.
GRINDER = Product.of(
    sku="SKU-GRINDER-BURR",
    name="Conical burr grinder",
    cost="2400.00",
    list_price="3499.00",
    margin_floor="0.25",
    currency="INR",
)

#: Dear to buy, barely marked up. The lowest floor of the three and the least room.
LAPTOP = Product.of(
    sku="SKU-LAPTOP-14",
    name="14-inch laptop, 16 GB",
    cost="61000.00",
    list_price="74999.00",
    margin_floor="0.15",
    currency="INR",
)

#: What ``Catalogue.seed`` is handed on a fresh start (FR-11.5).
PRODUCTS: tuple[Product, ...] = (COFFEE, GRINDER, LAPTOP)

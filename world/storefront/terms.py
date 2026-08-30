"""What this merchant charges for delivery, and what waiting for money costs it.

Environment, not product (CONTEXT.md section 7). ``desk/negotiation/terms.py`` owns the
*shape* -- a flat handling cost, a delivery charge with two sides, a carry rate per
payment term -- and this file owns the numbers, exactly as the storefront owns which
products exist while the catalogue owns what a margin is.

Each number is here because it makes one lever visible rather than because it is
precise:

- **Handling, 60 rupees.** The fixed work of packing a deal and handing it to a courier.
  Flat, so a five-kilo order carries it once and a one-kilo order carries it once, which
  is the whole of why a quantity break is affordable. Small enough that a kilo of coffee
  still absorbs fifteen percent off, which is the behaviour ``world/storefront/products``
  is written around.
- **Express delivery, 400 charged against a 240 courier bill.** A hundred and sixty
  rupees of margin the goods did not have to find. That is what "at a premium" means in
  FR-5.3: the Desk is selling speed, not giving it away.
- **Carry: nothing prepaid, one percent on delivery, three percent at thirty days.**
  Roughly what money costs to wait for at a small merchant's cost of capital. A share
  rather than an amount, because waiting thirty days for a laptop ties up eighty times
  what waiting for a bag of coffee does -- and a flat figure would be the same mistake as
  a flat price floor.

Read together, the sheet is why *payment terms* is a modest lever and *delivery speed* is
a strong one. Prepaying a 3,499 rupee grinder frees about thirty-five rupees; taking
express delivery on it puts a hundred and sixty in. Neither number is tuned to make a
test pass, and the difference between them is the honest shape of the thing.
"""

from __future__ import annotations

from decimal import Decimal

from desk.negotiation import Payment, TermsSheet
from desk.spend import Money

#: The one currency this merchant trades in.
CURRENCY = "INR"

TERMS = TermsSheet(
    currency=CURRENCY,
    handling=Money.of("60.00", CURRENCY),
    express_premium=Money.of("400.00", CURRENCY),
    express_cost=Money.of("240.00", CURRENCY),
    carry={
        Payment.PREPAID: Decimal("0"),
        Payment.ON_DELIVERY: Decimal("0.01"),
        Payment.NET_30: Decimal("0.03"),
    },
)

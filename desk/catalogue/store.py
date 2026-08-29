"""The catalogue as the Desk holds it: seeded, read back, and never guessed at.

Two operations and one refusal.

``seed`` is **declarative**. It states what the catalogue is, and running it twice
leaves the same catalogue -- which matters because FR-11.4's ``docker compose up``
runs it on every start and FR-11.5 asks that a fresh clone come up already stocked. A
sku already present is updated to what the seed now says, so editing the storefront
and seeding again is the blunt way to move a cost. The sharp way arrives with
procurement (ticket 14), which will move costs from what suppliers actually charged.

``product`` **raises on a sku the Desk does not sell** rather than returning nothing.
The distinction is the whole reason it is spelled out: a missing product that came back
as ``None`` would be priced at nothing by the first caller that forgot to look, and a
line priced at nothing is a giveaway nobody decided on.

Nothing here writes to the audit trail. Stocking a product is configuration rather
than a decision about a counterparty, and the trail is for the second kind (ADR-0006).
The events that *use* these numbers -- an offer made, a deal closed, a walk-away --
belong to the negotiation and are ticket 08's to record.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from psycopg_pool import ConnectionPool

from desk.catalogue.margin import Line
from desk.catalogue.product import Product
from desk.catalogue.schema import TABLE
from desk.spend import Money

_COLUMNS = "sku, name, currency, cost, list_price, margin_floor"


class UnknownProduct(LookupError):
    """A sku the Desk does not sell.

    Not a refusal. A buyer agent asking for something unstocked is answered by the
    negotiation, with a reason; this is what the code raises when it is asked to price
    a line it has no numbers for, and there is no honest way to continue past it.
    """


class Catalogue:
    """What the Desk sells, and the prices it reasons from.

    Install the schema once with ``install_schema``; this class does not migrate.
    """

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def seed(self, products: Sequence[Product]) -> int:
        """State what the catalogue holds. Idempotent, and returns how many rows it set."""
        stocked_at = datetime.now(UTC)
        with self._pool.connection() as conn:
            for product in products:
                conn.execute(
                    f"INSERT INTO {TABLE} ({_COLUMNS}, stocked_at)"
                    f" VALUES (%s, %s, %s, %s, %s, %s, %s)"
                    f" ON CONFLICT (sku) DO UPDATE SET"
                    f" name = EXCLUDED.name,"
                    f" currency = EXCLUDED.currency,"
                    f" cost = EXCLUDED.cost,"
                    f" list_price = EXCLUDED.list_price,"
                    f" margin_floor = EXCLUDED.margin_floor,"
                    f" stocked_at = EXCLUDED.stocked_at",
                    (
                        product.sku,
                        product.name,
                        product.currency,
                        product.cost.amount,
                        product.list_price.amount,
                        product.margin_floor,
                        stocked_at,
                    ),
                )
        return len(products)

    def product(self, sku: str) -> Product:
        """One product by sku. Raises ``UnknownProduct`` rather than returning nothing."""
        with self._pool.connection() as conn:
            row = conn.execute(f"SELECT {_COLUMNS} FROM {TABLE} WHERE sku = %s", (sku,)).fetchone()
        if row is None:
            raise UnknownProduct(f"the Desk does not sell {sku}")
        return _product(row)

    def products(self) -> tuple[Product, ...]:
        """Everything the Desk sells, in sku order so the listing is stable."""
        with self._pool.connection() as conn:
            rows = conn.execute(f"SELECT {_COLUMNS} FROM {TABLE} ORDER BY sku").fetchall()
        return tuple(_product(row) for row in rows)

    def line(self, sku: str, *, quantity: int, unit_price: Money) -> Line:
        """A priced line, with the product resolved off the catalogue.

        The shape a negotiation works in: the sku arrives from a counterparty and the
        cost comes from here, never the other way around.
        """
        return Line(product=self.product(sku), quantity=quantity, unit_price=unit_price)


def _product(row: Sequence[Any]) -> Product:
    sku, name, currency, cost, list_price, margin_floor = row
    return Product(
        sku=sku,
        name=name,
        cost=Money(amount=Decimal(cost), currency=currency),
        list_price=Money(amount=Decimal(list_price), currency=currency),
        margin_floor=Decimal(margin_floor),
    )

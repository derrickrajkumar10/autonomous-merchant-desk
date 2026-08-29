"""The catalogue table, and the three things Postgres refuses rather than the code.

One row per product the Desk sells. Seven columns, and the shortness is the guarantee:
no stock level, no supplier, no reputation, no negotiation state. Each of those belongs
to a later ticket, and a column for one of them here would read as if the catalogue
owned it. A test asserts the column list for exactly that reason.

Three constraints carry real weight, and each of them is a row that cannot be written
rather than a check somebody has to remember to run:

- ``cost >= 0``. A cost is what the Desk paid, and it did not get paid to take stock.
- ``margin_floor`` in ``[0, 1)``. The floor is a share of revenue. A floor of 1 asks the
  whole price to be profit, which only a free product could ever meet.
- **the list price meets the product's own floor.** This is the interesting one. A row
  whose asking price already sits under its floor describes something nobody could sell
  at any price the Desk would name -- so it is a data error, and catching it at the
  insert beats discovering it halfway through a negotiation. It also subsumes
  ``list_price >= cost``, since a non-negative floor cannot be met by a loss.

``cost``, ``list_price`` and ``margin_floor`` are ``numeric``, which psycopg reads back
as ``Decimal``. A price is never a float on the way to Postgres or on the way back.

The ``< 'Infinity'`` clauses on the two amounts are not decoration. Postgres ``numeric``
holds ``NaN`` and ``Infinity``, and it deliberately orders ``NaN`` *above* every real
number -- so ``NaN >= 0`` is true, and a bare non-negativity check lets one straight in.
It would sit in the table until something read it back, and then raise out of ``Money``
in whatever code path happened to be listing products. ``x < 'Infinity'`` is false for
both ``NaN`` and ``Infinity`` and true for every real amount, so one clause closes both.
(``x = x``, the obvious guard, does *not* work here: ``numeric`` NaN compares equal to
itself, which is the opposite of the float rule most people are remembering.)
``margin_floor`` needs no such clause -- its ``< 1`` already excludes both.
"""

from __future__ import annotations

from typing import Any

from psycopg import Connection

TABLE = "product"


def install_schema(conn: Connection[Any]) -> None:
    """Create the catalogue if it is not there. Idempotent."""
    conn.execute(_TABLE_DDL)


_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    sku          text PRIMARY KEY,
    name         text NOT NULL,
    currency     text NOT NULL,
    cost         numeric NOT NULL,
    list_price   numeric NOT NULL,
    margin_floor numeric NOT NULL,
    stocked_at   timestamptz NOT NULL,
    CONSTRAINT product_sku_is_a_sku
        CHECK (sku ~ '^[A-Z0-9][A-Z0-9-]{{1,62}}[A-Z0-9]$'),
    CONSTRAINT product_is_named
        CHECK (length(btrim(name)) > 0),
    CONSTRAINT product_currency_is_iso4217
        CHECK (currency ~ '^[A-Z]{{3}}$'),
    CONSTRAINT product_cost_is_not_negative
        CHECK (cost >= 0 AND cost < 'Infinity'::numeric),
    CONSTRAINT product_asks_something
        CHECK (list_price > 0 AND list_price < 'Infinity'::numeric),
    CONSTRAINT product_margin_floor_is_a_fraction
        CHECK (margin_floor >= 0 AND margin_floor < 1),
    -- A product that cannot be sold at its own asking price is a data error.
    CONSTRAINT product_list_price_meets_its_own_floor
        CHECK (list_price - cost >= margin_floor * list_price)
)
"""

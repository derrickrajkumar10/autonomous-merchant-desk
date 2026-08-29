"""The three products the catalogue tests reason about.

They are the storefront's own -- imported from ``world/storefront`` rather than
invented here -- because a number that only exists in a test proves nothing about the
thing that will actually be seeded. If the seed changes, these tests change with it,
which is the point.

The three were chosen so that the *same* question gets three different answers:

- **Coffee** is cheap to buy and dear to sell, so it absorbs a third off list.
- **The laptop** is dear to buy and barely marked up, so it absorbs about four
  percent, on a floor that is *half* the coffee's.
- **The grinder** sits between them, and is the one that cannot take ten percent off
  alone but can inside a bundle.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from psycopg_pool import ConnectionPool

from desk.catalogue import Catalogue
from desk.catalogue import install_schema as install_catalogue_schema
from world.storefront import COFFEE, GRINDER, LAPTOP, PRODUCTS

__all__ = ["COFFEE", "GRINDER", "LAPTOP", "PRODUCTS"]


@pytest.fixture
def catalogue(pool: ConnectionPool) -> Iterator[Catalogue]:
    """An empty catalogue over a freshly installed table."""
    with pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS product")
        install_catalogue_schema(conn)
    yield Catalogue(pool)


@pytest.fixture
def storefront(catalogue: Catalogue) -> Catalogue:
    """The catalogue with the storefront's own products in it."""
    catalogue.seed(PRODUCTS)
    return catalogue

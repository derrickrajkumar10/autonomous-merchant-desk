"""What the negotiation suite negotiates over: the storefront's products and terms.

Imported from ``world/storefront`` rather than invented here, for the reason the
catalogue suite gives -- a number that exists only in a test proves nothing about the
thing that will actually be seeded. Change the seed and these tests change with it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from psycopg_pool import ConnectionPool

from desk.catalogue import Catalogue
from desk.catalogue import install_schema as install_catalogue_schema
from desk.identity import DeskKeypair
from world.storefront import COFFEE, GRINDER, LAPTOP, PRODUCTS, TERMS

__all__ = ["COFFEE", "GRINDER", "LAPTOP", "PRODUCTS", "TERMS"]


@pytest.fixture
def storefront(pool: ConnectionPool) -> Iterator[Catalogue]:
    """The catalogue with the storefront's own products in it."""
    with pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS product")
        install_catalogue_schema(conn)
    catalogue = Catalogue(pool)
    catalogue.seed(PRODUCTS)
    yield catalogue


@pytest.fixture
def desk_key() -> DeskKeypair:
    return DeskKeypair.generate()

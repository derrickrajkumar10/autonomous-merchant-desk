"""What the negotiation suite negotiates over: the storefront's products and terms.

Imported from ``world/storefront`` rather than invented here, for the reason the
catalogue suite gives -- a number that exists only in a test proves nothing about the
thing that will actually be seeded. Change the seed and these tests change with it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from psycopg_pool import ConnectionPool

from desk.audit import AuditTrail
from desk.catalogue import Catalogue
from desk.catalogue import install_schema as install_catalogue_schema
from desk.freshness import FreshnessCheck, FreshnessPolicy, NonceStore
from desk.identity import AgentRegistry, DeskKeypair, IdentityCheck, PrincipalDirectory
from desk.mandate import MandateCheck
from desk.spend import BudgetAccumulator, SpendAuthorityCheck
from desk.spine import TrustSpine
from tests.freshness.conftest import DESK, SKEW, WINDOW
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


@pytest.fixture
def spine(pool: ConnectionPool, trail: AuditTrail, principals: PrincipalDirectory) -> TrustSpine:
    """The four checks, wired the way a running Desk wires them.

    Duplicated from the spine suite rather than shared, and deliberately: a negotiation
    test that quietly depended on the spine suite's fixtures would break for reasons that
    had nothing to do with negotiating. What it needs is a real front door, and this is
    the smallest real one.
    """
    return TrustSpine(
        IdentityCheck(AgentRegistry(pool, trail), trail),
        MandateCheck(principals, trail),
        SpendAuthorityCheck(BudgetAccumulator(pool), trail),
        FreshnessCheck(
            NonceStore(pool), trail, FreshnessPolicy(window=WINDOW, clock_skew=SKEW, audience=DESK)
        ),
        trail,
    )

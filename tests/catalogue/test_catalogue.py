"""The catalogue as stored: seeded, read back, and constrained by the database.

Like every other table in this repo, the properties worth asserting are the ones
Postgres holds rather than the ones Python asks nicely for -- so these run against a
real server and several of them try to write rows that must not be writable.
"""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest
from psycopg_pool import ConnectionPool

from desk.catalogue import Catalogue, Line, Product, UnknownProduct, margin_on
from desk.catalogue import Offer as Offer
from desk.spend import Money
from tests.catalogue.conftest import COFFEE, PRODUCTS


def test_the_catalogue_is_seedable(catalogue: Catalogue) -> None:
    """The ticket's fifth acceptance criterion, and FR-11.5's self-seeding ``up``."""
    assert catalogue.products() == ()

    catalogue.seed(PRODUCTS)

    assert catalogue.products() == tuple(sorted(PRODUCTS, key=lambda p: p.sku))


def test_seeding_twice_leaves_the_catalogue_the_seed_describes(catalogue: Catalogue) -> None:
    """Idempotent, because ``docker compose up`` runs it every time (FR-11.4)."""
    catalogue.seed(PRODUCTS)
    catalogue.seed(PRODUCTS)

    assert len(catalogue.products()) == len(PRODUCTS)


def test_seeding_is_declarative_and_a_changed_cost_takes_effect(catalogue: Catalogue) -> None:
    """The seed states what the catalogue *is*, so re-seeding it says so again.

    Procurement will move a cost for real later (ticket 14). This is the blunter
    path: edit the storefront and seed again.
    """
    catalogue.seed(PRODUCTS)
    dearer = Product.of(
        sku=COFFEE.sku,
        name=COFFEE.name,
        cost="500.00",
        list_price=str(COFFEE.list_price.amount),
        margin_floor=str(COFFEE.margin_floor),
        currency=COFFEE.list_price.currency,
    )

    catalogue.seed([dearer])

    assert catalogue.product(COFFEE.sku).cost == Money.of("500.00", "INR")


def test_a_price_survives_the_round_trip_to_the_last_paisa(storefront: Catalogue) -> None:
    """``numeric`` in and ``Decimal`` out. A price is never a float in between."""
    coffee = storefront.product("SKU-COFFEE-1KG")

    assert coffee.cost == Money.of("420.00", "INR")
    assert coffee.list_price.amount == Decimal("899.00")
    assert coffee.margin_floor == Decimal("0.30")


def test_a_product_the_desk_does_not_sell_is_not_a_zero(storefront: Catalogue) -> None:
    """A missing sku raises. Silently returning nothing would price a deal at nothing."""
    with pytest.raises(UnknownProduct, match="SKU-UNSTOCKED"):
        storefront.product("SKU-UNSTOCKED")


def test_a_line_can_be_priced_straight_off_the_catalogue(storefront: Catalogue) -> None:
    """The shape a negotiation will use: a sku off the wire, a price off the table."""
    line = storefront.line("SKU-COFFEE-1KG", quantity=2, unit_price=Money.of("750.00", "INR"))
    margin = margin_on(Offer.of(line))

    assert margin.revenue == Money.of("1500.00", "INR")
    assert margin.inside_floor


def test_the_database_refuses_a_product_that_cannot_meet_its_own_floor(
    pool: ConnectionPool, catalogue: Catalogue
) -> None:
    """The Python constructor refuses it too. This is the wall behind that door."""
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="meets_its_own_floor"),
        pool.connection() as conn,
    ):
        conn.execute(
            "INSERT INTO product (sku, name, currency, cost, list_price, margin_floor,"
            " stocked_at) VALUES (%s, %s, %s, %s, %s, %s, now())",
            ("SKU-UNSELLABLE", "Unsellable", "INR", 900, 1000, Decimal("0.50")),
        )


def test_the_database_refuses_a_margin_floor_that_is_not_a_fraction(
    pool: ConnectionPool, catalogue: Catalogue
) -> None:
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="floor_is_a_fraction"),
        pool.connection() as conn,
    ):
        conn.execute(
            "INSERT INTO product (sku, name, currency, cost, list_price, margin_floor,"
            " stocked_at) VALUES (%s, %s, %s, %s, %s, %s, now())",
            ("SKU-IMPOSSIBLE", "All profit", "INR", 0, 1000, Decimal("1")),
        )


def test_the_database_refuses_a_negative_cost(pool: ConnectionPool, catalogue: Catalogue) -> None:
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="cost_is_not_negative"),
        pool.connection() as conn,
    ):
        conn.execute(
            "INSERT INTO product (sku, name, currency, cost, list_price, margin_floor,"
            " stocked_at) VALUES (%s, %s, %s, %s, %s, %s, now())",
            ("SKU-PAID-TO-TAKE", "Paid to take it", "INR", -1, 1000, Decimal("0.10")),
        )


def test_the_catalogue_holds_only_what_pricing_needs(pool: ConnectionPool) -> None:
    """The column list is the guarantee, so it is short on purpose.

    No stock level, no supplier, no reputation. Each of those belongs to a later
    ticket and would read here as if the catalogue owned it.
    """
    with pool.connection() as conn:
        columns = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'product'"
            ).fetchall()
        }

    assert columns == {
        "sku",
        "name",
        "currency",
        "cost",
        "list_price",
        "margin_floor",
        "stocked_at",
    }


def test_the_storefront_is_environment_and_the_margin_rule_is_not(storefront: Catalogue) -> None:
    """The split this ticket makes, asserted rather than only written down.

    Which products exist is the world's business: replace the seed and the Desk keeps
    working. How margin is computed is the Desk's, and no seed can move it.
    """
    only_one = Product.of(
        sku="SKU-INVENTED",
        name="A product no storefront file mentions",
        cost="10.00",
        list_price="100.00",
        margin_floor="0.50",
        currency="INR",
    )
    storefront.seed([only_one])

    margin = margin_on(
        Offer.of(
            Line(
                product=storefront.product("SKU-INVENTED"),
                quantity=3,
                unit_price=Money.of("40.00", "INR"),
            )
        )
    )

    assert margin.profit == Decimal("90.00")
    assert margin.required_profit == Decimal("60.0000")
    assert margin.inside_floor


def test_the_database_refuses_an_amount_that_is_not_a_number(
    pool: ConnectionPool, catalogue: Catalogue
) -> None:
    """Postgres ``numeric`` holds ``NaN``, and orders it *above* every real number.

    So ``cost >= 0`` passes for it, and so does the floor constraint -- a row that
    would sit in the table until something read it back and raised out of ``Money``,
    taking the whole product listing with it. ``< 'Infinity'`` is what actually
    excludes it.
    """
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="cost_is_not_negative"),
        pool.connection() as conn,
    ):
        conn.execute(
            "INSERT INTO product (sku, name, currency, cost, list_price, margin_floor,"
            " stocked_at) VALUES (%s, %s, %s, 'NaN'::numeric, %s, %s, now())",
            ("SKU-NOT-A-NUMBER", "Cost unknown to arithmetic", "INR", 1000, Decimal("0.10")),
        )


def test_the_database_refuses_an_asking_price_that_is_not_a_number(
    pool: ConnectionPool, catalogue: Catalogue
) -> None:
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="asks_something"),
        pool.connection() as conn,
    ):
        conn.execute(
            "INSERT INTO product (sku, name, currency, cost, list_price, margin_floor,"
            " stocked_at) VALUES (%s, %s, %s, %s, 'NaN'::numeric, %s, now())",
            ("SKU-PRICELESS", "Asking price unknown to arithmetic", "INR", 100, Decimal("0.10")),
        )


def test_the_database_refuses_an_infinite_asking_price(
    pool: ConnectionPool, catalogue: Catalogue
) -> None:
    """The other value ``numeric`` holds that no amount of money ever is."""
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="asks_something"),
        pool.connection() as conn,
    ):
        conn.execute(
            "INSERT INTO product (sku, name, currency, cost, list_price, margin_floor,"
            " stocked_at) VALUES (%s, %s, %s, %s, 'Infinity'::numeric, %s, now())",
            ("SKU-UNAFFORDABLE", "Asking everything", "INR", 100, Decimal("0.10")),
        )

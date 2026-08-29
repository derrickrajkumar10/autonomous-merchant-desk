"""Money is a number and a currency, and neither half is optional.

These are unit tests over a value object, which is unusual in this suite — everything
else goes through a real database because the property under test belongs to the
database. The properties here belong to the type, and they are the ones that make
every balance above trustworthy.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from desk.spend import CurrencyMismatch, Money


def test_money_is_never_built_from_a_float() -> None:
    """The bug this type exists to make impossible.

    ``0.1 + 0.2`` is not ``0.3``, and a ceiling that is not the number the principal
    signed is a ceiling nobody agreed to.
    """
    with pytest.raises(TypeError, match="cannot be built from a float"):
        Money.of(1999.95, "INR")  # type: ignore[arg-type]


def test_a_decimal_written_as_a_string_is_exact() -> None:
    assert Money.of("0.1", "INR") + Money.of("0.2", "INR") == Money.of("0.3", "INR")


def test_arithmetic_across_currencies_raises_rather_than_converting() -> None:
    """The Desk holds no exchange rate and has no business inventing one.

    Converting would manufacture authority the principal never gave — a mandate for
    2,000 rupees is not a mandate for 2,000 of anything else.
    """
    with pytest.raises(CurrencyMismatch, match="holds no exchange rate"):
        Money.of("100", "INR") + Money.of("100", "USD")

    with pytest.raises(CurrencyMismatch):
        assert Money.of("100", "INR") <= Money.of("100", "USD")


def test_a_negative_amount_is_refused() -> None:
    with pytest.raises(ValueError, match="nothing here spends backwards"):
        Money.of("-1", "INR")


def test_something_that_is_not_a_currency_is_refused() -> None:
    with pytest.raises(ValueError, match="ISO 4217"):
        Money.of("100", "rupees")


def test_a_float_amount_is_refused_even_by_the_constructor() -> None:
    """``Money.of`` is the door with a sign on it; this is the wall beside it."""
    with pytest.raises(TypeError, match="money is a Decimal"):
        Money(amount=1.0, currency="INR")  # type: ignore[arg-type]


def test_an_amount_that_is_not_finite_is_not_money() -> None:
    with pytest.raises(ValueError, match="is not an amount of money"):
        Money(amount=Decimal("NaN"), currency="INR")


def test_money_reads_as_an_amount_and_a_currency() -> None:
    """What every balance in the audit trail is rendered by."""
    assert str(Money.of("1250.00", "INR")) == "1250.00 INR"

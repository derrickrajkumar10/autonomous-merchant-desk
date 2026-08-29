"""An amount of money, which is a number *and* a currency and never just a number.

Two rules, and both exist because breaking either is how money software goes wrong
quietly rather than loudly.

**Never a float.** ``Decimal`` throughout. A ceiling of ``1000.10`` parsed as a float
is not 1000.10, and a balance drawn down by a number the principal did not sign is
the kind of thing that is only noticed after the money has moved.

**Never a bare number.** A currency travels with every amount, and arithmetic across
two currencies raises rather than converts. The Desk holds no exchange rate and has
no business inventing one: a mandate authorising 2,000 rupees does not authorise
2,000 of anything else, and quietly converting would manufacture authority the
principal never gave.

Units are the mandate's own. AP2's ``payment.budget`` types ``max`` as a JSON number
and its example is ``1000.00``, so amounts here are ordinary units -- rupees, not
paise. Its sibling ``payment.amount_range`` uses integer minor units instead, an
inconsistency inside the specification that [the research
note](../../docs/research/ap2-mandate-model.md) section 1c records. Converting between
the two is the payment rail's job, at the point a charge is actually created.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: ISO 4217 alpha-3, which is what AP2's money-carrying constraints name.
CURRENCY_CODE = re.compile(r"^[A-Z]{3}\Z")


class CurrencyMismatch(ValueError):
    """Two amounts in different currencies, asked to behave like one.

    Raised rather than converted, and never caught as a refusal: a currency mismatch
    the Desk reaches *arithmetically* is a bug in the Desk. One that arrives from a
    counterparty is refused by check 3 before it ever gets here.
    """


@dataclass(frozen=True, order=False)
class Money:
    """An exact amount in one currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError(
                f"money is a Decimal, not a {type(self.amount).__name__}. A float amount "
                f"is not the amount it was written as."
            )
        if not self.amount.is_finite():
            raise ValueError(f"{self.amount} is not an amount of money")
        if self.amount < 0:
            raise ValueError(f"{self.amount} is negative, and nothing here spends backwards")
        if not isinstance(self.currency, str) or not CURRENCY_CODE.match(self.currency):
            raise ValueError(
                f"a currency is an ISO 4217 alpha-3 code; {self.currency!r} is not one"
            )

    @classmethod
    def of(cls, amount: Decimal | int | str, currency: str) -> Money:
        """An amount from whatever a caller has to hand, except a float.

        A string is the safe way to write a literal -- ``Money.of("1999.95", "INR")``
        is exactly that, where a float literal would already have lost it before this
        method saw it.
        """
        if isinstance(amount, float):
            raise TypeError(
                "money cannot be built from a float; pass a string or a Decimal so the "
                "amount is the one that was written"
            )
        try:
            return cls(amount=Decimal(amount), currency=currency)
        except InvalidOperation as exc:
            raise ValueError(f"{amount!r} is not an amount of money") from exc

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def __mul__(self, count: int) -> Money:
        """This amount, that many times over -- a unit price against a quantity.

        The factor is a **whole count and nothing else**. ``bool`` is an ``int`` in
        Python and is refused too, because ``price * True`` is never what anybody
        meant. A ``float`` or a ``Decimal`` factor would be a *rate* rather than a
        count -- a discount, a margin floor, a tax -- and every one of those needs a
        rounding decision that somebody has to make out loud, at the place they make
        it. Making it here, silently and once, is how a rounding rule ends up applied
        to prices nobody chose it for.
        """
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError(
                f"money multiplies by a whole count of things, not by a "
                f"{type(count).__name__}; a rate is a rounding decision and does not "
                f"belong in this operator"
            )
        if count < 0:
            raise ValueError(f"{count} is negative, and nothing here spends backwards")
        return Money(amount=self.amount * count, currency=self.currency)

    def __le__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.amount <= other.amount

    def __lt__(self, other: Money) -> bool:
        self._same_currency(other)
        return self.amount < other.amount

    def __gt__(self, other: Money) -> bool:
        return not self <= other

    def __ge__(self, other: Money) -> bool:
        return not self < other

    def __str__(self) -> str:
        return f"{self.amount} {self.currency}"

    def _same_currency(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"money compares with money, not with {type(other).__name__}")
        if self.currency != other.currency:
            raise CurrencyMismatch(
                f"{self} and {other} are different currencies, and the Desk holds no "
                f"exchange rate; it refuses such a request rather than converting it"
            )

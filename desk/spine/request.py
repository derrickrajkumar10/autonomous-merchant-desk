"""What a buyer agent asks for, and how the Desk reads one request into its parts.

Check 1 proves that a signed request came from a registered agent and reached the Desk
unaltered. What it hands back is a JSON object, and this module is the one place that
says what an object has to contain to be a *purchase request*: the two mandates AP2
splits an authorisation across, the thing being bought, the price being offered, and
optionally some free text the buyer wants read.

That last field, ``enquiry``, is the odd one out: the deterministic spine never looks
at it. It is untrusted prose, and the only thing that reads it is check 5 -- the
model-backed Inspector in ``desk.inspector``, which runs *after* checks 1 to 4 have
passed and can only refuse. Carrying it here rather than on a later message keeps the
untrusted text on the one artefact check 1 has already proven came through unaltered.

**Reading is deliberately lenient, and that is not the same as permissive.** A field
that is missing, or is of a shape this module cannot read, becomes the emptiest value
of its kind -- an empty mandate, an empty item id, no amount at all -- and is then
refused by the check that would have read it. A request naming no mandate fails check
2 because nothing in it establishes that a human authorised anything; a request naming
no item fails check 3 because nothing authorises the nothing it named. That is one
refusal from the check that owns the question, rather than a second, parallel
vocabulary of protocol refusals sitting in front of the spine and saying almost the
same things in different words.

The one field with no such home is the price, because there is no such thing as an
emptiest amount of money: zero is a number a mandate would happily authorise.
``amount`` is therefore ``None`` when it cannot be read, and ``spine.py`` says what
the Desk does with that. A price is *two* fields -- an amount and the currency it is in
-- and either being missing or malformed leaves the same nothing, which is why the
refusal names both and the evidence shows what arrived in each.

Amounts are exact. A price written as a JSON number arrives here as a ``Decimal``,
because ``desk.identity.jws`` parses request bodies the way mandate claims are parsed
-- ``1000.10`` as a float is not 1000.10, and a ceiling drawn down by a number nobody
wrote is the kind of defect that is noticed after the money has moved.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from desk.spend import Money

#: The presented open Checkout Mandate -- *what may be bought*. A presentation rather
#: than a mandate: the key-binding hop check 4 reads is appended to it.
CHECKOUT = "checkout"

#: The presented open Payment Mandate -- *what may be spent*, and which Checkout
#: Mandate it was signed for.
PAYMENT = "payment"

#: The id of the item being bought, which check 3 looks for in the Checkout Mandate's
#: ``checkout.line_items`` requirements.
ITEM_ID = "item_id"

#: The price being offered, as a JSON number or a decimal string. Never a float once
#: it is here; see the module docstring.
AMOUNT = "amount"

#: The ISO 4217 code the price is in. Carried beside the amount rather than assumed,
#: because the Desk holds no exchange rate and check 3 refuses a mismatch outright.
CURRENCY = "currency"

#: Free text the buyer sends along with the request -- a product question, a note, a
#: preamble. The deterministic spine never reads it: it is untrusted prose, and the one
#: thing that looks at it is check 5 (``desk.inspector``), after checks 1 to 4 have
#: passed. Absent on most requests, and the emptiest value of its kind when it is.
ENQUIRY = "enquiry"

#: The most enquiry text the Desk keeps. A real product question and a paragraph of
#: preamble fit inside this comfortably; past it the request is carrying prose to run up
#: a model bill or a memory bill rather than to be read, so the tail is dropped here --
#: before anything holds the whole of it, and before check 5 sends it anywhere.
MAX_ENQUIRY = 8000


@dataclass(frozen=True)
class PurchaseRequest:
    """One purchase request, as far as the Desk can read it before any check has run.

    Nothing here has been verified. The two mandate strings are whatever the body
    carried, and both are about to be handed to check 2 precisely so that something
    other than this module decides whether to believe them.
    """

    checkout: str
    payment: str
    item_id: str
    amount: Money | None
    #: What the body said the price was, exactly as it arrived, so that a refusal for
    #: an unreadable amount can show the reader what it could not read.
    stated_price: Mapping[str, Any]
    #: The buyer's free text, carried through untouched for check 5 to inspect. Empty
    #: when the request named none. No check between here and check 5 reads it.
    enquiry: str = ""


def read_purchase_request(body: Mapping[str, Any]) -> PurchaseRequest:
    """The parts of a verified request body. Never raises; see the module docstring."""
    return PurchaseRequest(
        checkout=_text(body.get(CHECKOUT)),
        payment=_text(body.get(PAYMENT)),
        item_id=_text(body.get(ITEM_ID)),
        amount=_money(body.get(AMOUNT), body.get(CURRENCY)),
        stated_price={AMOUNT: _shown(body.get(AMOUNT)), CURRENCY: _shown(body.get(CURRENCY))},
        enquiry=_enquiry(body.get(ENQUIRY)),
    )


def _text(field: Any) -> str:
    """A field, but only if it is a string. Anything else named nothing."""
    return field if isinstance(field, str) else ""


def _enquiry(field: Any) -> str:
    """The buyer's free text, as a string and bounded in length.

    A string or nothing, like ``_text`` -- but capped, unlike ``_text``, because the
    other fields it serves are a sku or a whole mandate JWT and have their own natural
    size, while an enquiry is prose a stranger chose the length of. Past ``MAX_ENQUIRY``
    the tail is dropped rather than the request refused: an over-long note is still a
    note, and check 5 reads the part of it that a person would have.
    """
    return field[:MAX_ENQUIRY] if isinstance(field, str) else ""


def _money(amount: Any, currency: Any) -> Money | None:
    """The price, or ``None`` if the body did not state one the Desk can read.

    Both halves or neither. A currency this cannot read leaves no price, exactly as a
    missing amount does -- an amount without a currency is a bare number, and the Desk
    has no default to attach to one.

    ``bool`` is excluded before the ``int`` case because Python makes ``True`` an
    integer, and ``"amount": true`` is not an offer of one rupee.
    """
    if not isinstance(currency, str) or isinstance(amount, bool):
        return None
    if not isinstance(amount, str | int | Decimal):
        return None
    try:
        return Money.of(amount, currency)
    except (TypeError, ValueError):
        return None


def _shown(field: Any) -> str | None:
    """A field as the trail may carry it: text, and bounded in length.

    A refusal records what arrived, and what arrived is a stranger's to choose. The
    cap is here so that a megabyte of it cannot be written into an entry by sending
    one, and ``repr`` is here so that a nested object still says something legible.
    """
    if field is None:
        return None
    return (field if isinstance(field, str) else repr(field))[:120]

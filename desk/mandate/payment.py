"""The open Payment Mandate: what a principal signs about *money*.

The Checkout Mandate next door says what may be bought. This one says what may be
spent, and the split is AP2's rather than ours -- ``payment.budget`` and
``payment.execution_date`` are Payment Mandate constraints, and the open Checkout
Mandate's schema (``constraints.items.anyOf``) admits only ``checkout.line_items``
and ``checkout.allowed_merchants``. A ceiling carried in a Checkout Mandate would not
validate against the schema a stranger's library holds.

So a buyer agent presents **two** mandates, and the specification pairs them itself:
one ``payment.reference`` constraint is mandatory on this one (the schema's
``contains`` rule) and carries the *digest of the open Checkout Mandate* it belongs
with. That is what stops an agent pairing a generous budget with somebody else's
shopping list.

Three constraints are read here, and only the first is mandatory:

- ``payment.reference`` -- the checkout mandate this budget is for, by digest.
- ``payment.budget`` -- ``max`` and ``currency``: the ceiling drawn down across
  deals. The mandate itself never changes; the running total is the Desk's own state
  (ADR-0004), which is what AP2 specifies too: the verifier tracks it.
- ``payment.execution_date`` -- ``not_before`` and ``not_after``: the window the
  payment may execute in. Distinct from the mandate's ``exp``, which check 2 already
  reads: ``exp`` cannot say *authorised, but not until Monday*.

The other five constraint types AP2 defines here -- payees, payment instruments,
PISPs, ``payment.amount_range`` and ``payment.agent_recurrence`` -- are carried
through in ``constraints`` and not evaluated. They constrain how a charge is
*settled*, which is the Razorpay ticket's, and how often a mandate may be *reused*,
which needs the presentation history check 4 builds.

Field structure read from AP2 v0.2's canonical JSON Schema,
``code/sdk/schemas/ap2/open_payment_mandate.json``, and the evaluation rules from
``docs/ap2/payment_mandate.md`` lines 202-207 (budget), 231-235 (reference) and
254-257 (execution date), at commit ``e1ea56d``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from desk.mandate.open_mandate import OpenMandate, iso8601, mandate_content, read_open_mandate
from desk.mandate.sdjwt import MandateNotVerified

#: The ``vct`` an open Payment Mandate carries. ``mandate.payment.1`` is the closed
#: variant -- the authorisation of one specific charge -- and is a later ticket's.
OPEN_PAYMENT_VCT = "mandate.payment.open.1"

#: The one constraint AP2's schema makes mandatory here, via a ``contains`` rule.
PAYMENT_REFERENCE_CONSTRAINT = "payment.reference"

#: The spend ceiling, drawn down across presentations.
BUDGET_CONSTRAINT = "payment.budget"

#: The window the payment may execute in.
EXECUTION_DATE_CONSTRAINT = "payment.execution_date"

#: ISO 4217 alpha-3, which is what both money-carrying AP2 constraints name.
_CURRENCY = re.compile(r"^[A-Z]{3}\Z")


@dataclass(frozen=True)
class Budget:
    """A ``payment.budget`` constraint: the total this mandate may ever spend.

    ``maximum`` is a ``Decimal`` and never a ``float``. AP2 types it as a JSON
    ``number`` and its own example is ``1000.00``, so it is a decimal amount in the
    currency's ordinary units -- not the integer minor units its sibling
    ``payment.amount_range`` uses, an inconsistency in the specification itself that
    [the research note](../../docs/research/ap2-mandate-model.md) section 1c flags. The
    Desk works in the units the mandate was written in and converts nowhere; turning
    2,000 rupees into 200,000 paise is the payment rail's job, at the point a charge
    is actually created.
    """

    maximum: Decimal
    currency: str


@dataclass(frozen=True)
class ExecutionWindow:
    """A ``payment.execution_date`` constraint: when the payment may execute.

    Either end may be absent, which leaves that end unbounded. A constraint with
    neither is legal in the schema and constrains nothing, which is a thing a wallet
    may honestly write.
    """

    not_before: datetime | None
    not_after: datetime | None

    def contains(self, at: datetime) -> bool:
        """AP2's own rule: at or after ``not_before``, at or before ``not_after``."""
        if self.not_before is not None and at < self.not_before:
            return False
        return not (self.not_after is not None and at > self.not_after)


@dataclass(frozen=True)
class OpenPaymentMandate(OpenMandate):
    """A principal's forward-looking authorisation of *what may be spent*.

    Every constraint the Desk evaluates is read and shaped when the mandate is read,
    not when check 3 asks for it. A budget whose ``max`` is a string is a malformed
    mandate, and malformed mandates are refused where every other structural refusal
    already lives -- check 2 -- rather than surfacing later as a spend refusal, which
    would put a sentence in the trail that was not true.
    """

    #: The digest of the open Checkout Mandate this one belongs with. Mandatory.
    checkout_reference: str
    #: The ceiling, or ``None`` when the mandate sets none. Check 3 refuses the latter:
    #: a mandate with no ceiling bounds nothing, and default-deny is the whole point.
    budget: Budget | None
    #: The execution window, or ``None`` when the mandate sets none.
    execution_window: ExecutionWindow | None
    #: When the payment is to execute. AP2: "When absent indicates immediate
    #: execution", so ``None`` means *now* rather than *unknown*.
    execution_date: datetime | None


def read_open_payment_mandate(claims: Mapping[str, Any]) -> OpenPaymentMandate:
    """The mandate these verified claims describe, or a refusal saying why they do not."""
    read = read_open_mandate(claims, vct=OPEN_PAYMENT_VCT)
    content = mandate_content(claims)

    reference = read.constraint(PAYMENT_REFERENCE_CONSTRAINT)
    if reference is None:
        raise MandateNotVerified(
            f"the mandate carries no {PAYMENT_REFERENCE_CONSTRAINT} constraint, which "
            f"AP2 requires; it does not say which checkout it authorises payment for"
        )
    conditional_transaction_id = reference.get("conditional_transaction_id")
    if not isinstance(conditional_transaction_id, str) or not conditional_transaction_id:
        raise MandateNotVerified(
            f"the mandate's {PAYMENT_REFERENCE_CONSTRAINT} constraint carries no "
            f"conditional_transaction_id, so it names no checkout mandate"
        )

    return OpenPaymentMandate(
        constraints=read.constraints,
        key_binding=read.key_binding,
        issued_at=read.issued_at,
        expires_at=read.expires_at,
        checkout_reference=conditional_transaction_id,
        budget=_budget(read.constraint(BUDGET_CONSTRAINT)),
        execution_window=_execution_window(read.constraint(EXECUTION_DATE_CONSTRAINT)),
        execution_date=(
            None
            if content.get("execution_date") is None
            else iso8601(content.get("execution_date"), "execution_date")
        ),
    )


def _budget(constraint: Mapping[str, Any] | None) -> Budget | None:
    if constraint is None:
        return None
    return Budget(
        maximum=_amount(constraint.get("max")),
        currency=_currency(constraint.get("currency")),
    )


def _execution_window(constraint: Mapping[str, Any] | None) -> ExecutionWindow | None:
    if constraint is None:
        return None
    not_before = constraint.get("not_before")
    not_after = constraint.get("not_after")
    window = ExecutionWindow(
        not_before=None if not_before is None else iso8601(not_before, "not_before"),
        not_after=None if not_after is None else iso8601(not_after, "not_after"),
    )
    if (
        window.not_before is not None
        and window.not_after is not None
        and window.not_after < window.not_before
    ):
        raise MandateNotVerified(
            f"the mandate's {EXECUTION_DATE_CONSTRAINT} constraint ends before it "
            f"begins, so no payment could ever execute inside it"
        )
    return window


def _amount(claimed: Any) -> Decimal:
    """A money amount out of a mandate, as an exact decimal.

    A ``float`` is refused rather than converted. Mandate claims are parsed with
    ``parse_float=Decimal``, so every ordinary JSON number arrives here as a ``Decimal``
    or an ``int`` already -- which leaves ``NaN`` and ``Infinity`` as the only values
    that can still be floats, and neither is a ceiling.
    """
    if isinstance(claimed, bool) or not isinstance(claimed, int | Decimal):
        raise MandateNotVerified(
            f"the {BUDGET_CONSTRAINT} constraint's max must be a number, not "
            f"{type(claimed).__name__}"
        )
    amount = Decimal(claimed)
    if not amount.is_finite():
        raise MandateNotVerified(f"the {BUDGET_CONSTRAINT} constraint's max is not a finite amount")
    if amount <= 0:
        raise MandateNotVerified(
            f"the {BUDGET_CONSTRAINT} constraint's max is {amount}, which authorises no "
            f"spending at all; a mandate that permits nothing is a mandate not worth signing"
        )
    return amount


def _currency(claimed: Any) -> str:
    if not isinstance(claimed, str) or not _CURRENCY.match(claimed):
        raise MandateNotVerified(
            f"the {BUDGET_CONSTRAINT} constraint's currency must be an ISO 4217 "
            f"alpha-3 code; this one is {claimed!r}"
        )
    return claimed

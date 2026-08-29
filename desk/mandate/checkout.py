"""The open Checkout Mandate: what a principal signs, and what makes it well formed.

This is the artefact behind the sentence the whole project exists for -- *"restock my
coffee, keep it under 2,000 rupees"*. A human says it, their wallet turns it into
constraints, signs them, and names the one agent allowed to present the result. The
Desk reads it here.

**Open** is AP2's own word for the human-not-present case: the principal is not at the
keyboard when the purchase happens, so what they signed is a set of forward-looking
constraints rather than one agreed basket. The matching **closed** variant -- the
specific negotiated deal -- is a later ticket's work and is not read here.

Three fields carry the weight, and AP2 v0.2 makes each of them required:

- ``vct`` names which of the four mandate shapes this is. A Payment Mandate arriving
  where a Checkout Mandate belongs is refused rather than read hopefully.
- ``constraints`` is what the principal authorised. At least one
  ``checkout.line_items`` constraint is mandatory in the schema; the Desk enforces
  that, and leaves *evaluating* the constraints to check 3.
- ``cnf`` carries the presenting agent's own public key (RFC 7800). This is the thing
  that makes a stolen mandate worthless: whoever took it still cannot produce a
  signature under the key the mandate names. **AP2 requires this; we did not invent
  it** (CONTEXT.md section 4).

This mandate says *what may be bought*. What may be **spent** is the open Payment
Mandate next door: ``payment.budget`` and the rest are payment constraints, and the
checkout schema's ``constraints.items.anyOf`` admits only the two checkout ones. The
two mandates are paired by digest -- see ``payment.py``.

Field structure read from AP2 v0.2's canonical JSON Schema,
``code/sdk/schemas/ap2/open_checkout_mandate.json`` at commit ``e1ea56d``. See
[the research note](../../docs/research/ap2-mandate-model.md) section 1a.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from desk.mandate.open_mandate import OpenMandate, read_open_mandate
from desk.mandate.sdjwt import MandateNotVerified

#: The ``vct`` an open Checkout Mandate carries, and only it. ``mandate.checkout.1``
#: is the closed variant, and the two Payment Mandates are a different artefact again.
OPEN_CHECKOUT_VCT = "mandate.checkout.open.1"

#: The one constraint AP2's schema makes mandatory on this mandate: a ``contains``
#: rule, so a mandate authorising nothing in particular is not a mandate.
LINE_ITEMS_CONSTRAINT = "checkout.line_items"

#: The other constraint the schema admits here. Read so that a mandate carrying one is
#: not refused; evaluating it is the negotiation ticket's, since the Desk is the
#: merchant and knows whether it is in the list.
ALLOWED_MERCHANTS_CONSTRAINT = "checkout.allowed_merchants"


@dataclass(frozen=True)
class OpenCheckoutMandate(OpenMandate):
    """A principal's forward-looking authorisation of *what may be bought*.

    Carries no ceiling. AP2 puts spend constraints on the Payment Mandate, so the
    amount a deal may come to is not a question this artefact can answer.
    """

    def authorises_item(self, item_id: str) -> bool:
        """Whether some line-item requirement accepts this item by id.

        AP2's own rule, ``docs/ap2/checkout_mandate.md:83-89``: "An item matches an
        ``items`` entry if its ID is present in the revealed ``acceptable_items``."
        The Desk verifies a mandate only when it is fully disclosed, so *revealed* and
        *present* are the same set here.

        One item, not a basket. The specification's full evaluation is a maximal-flow
        match over a whole checkout -- quantities, and no requirement used twice --
        and that belongs with the closed mandate the negotiation produces. Check 3
        asks the narrower question the PRD asks: is this the *category* the principal
        authorised.
        """
        return any(
            item_id in _acceptable_item_ids(constraint)
            for constraint in self.constraints
            if constraint.get("type") == LINE_ITEMS_CONSTRAINT
        )

    def authorised_item_ids(self) -> tuple[str, ...]:
        """Every item id this mandate accepts, in the order the constraints list them.

        Evidence rather than logic: a ``category_not_authorised`` refusal that records
        what *was* authorised beside what was asked for is a refusal someone can act
        on, and one nobody has to re-derive from the mandate to read.
        """
        return tuple(
            item_id
            for constraint in self.constraints
            if constraint.get("type") == LINE_ITEMS_CONSTRAINT
            for item_id in _acceptable_item_ids(constraint)
        )


def read_open_checkout_mandate(claims: Mapping[str, Any]) -> OpenCheckoutMandate:
    """The mandate these verified claims describe, or a refusal saying why they do not.

    Every refusal names the field, because "malformed mandate" tells a counterparty
    nothing it can fix and tells the trail nothing worth aggregating.
    """
    read = read_open_mandate(claims, vct=OPEN_CHECKOUT_VCT)

    if not any(constraint.get("type") == LINE_ITEMS_CONSTRAINT for constraint in read.constraints):
        raise MandateNotVerified(
            f"the mandate carries no {LINE_ITEMS_CONSTRAINT} constraint, which AP2 "
            f"requires; it authorises nothing in particular"
        )

    mandate = OpenCheckoutMandate(
        constraints=read.constraints,
        key_binding=read.key_binding,
        issued_at=read.issued_at,
        expires_at=read.expires_at,
    )
    # Force both reads now rather than when check 3 asks for them. A malformed
    # requirement is a malformed mandate, and it belongs with every other structural
    # refusal in check 2 -- surfacing later would put "not authorised" in the trail
    # for a mandate that authorises nothing readable, which is a different sentence.
    mandate.authorised_item_ids()
    # The second read is for its refusal and not its value. ``constraint`` refuses a
    # mandate carrying two of one type, and check 3 asks this question of every
    # presentation -- so without this the refusal happened *there*, as an exception
    # nothing caught, leaving a decision the trail has no record of. Two merchant lists
    # is a malformed mandate like any other, and this is where those are refused.
    mandate.constraint(ALLOWED_MERCHANTS_CONSTRAINT)
    return mandate


def _acceptable_item_ids(constraint: Mapping[str, Any]) -> tuple[str, ...]:
    """The item ids one ``checkout.line_items`` constraint accepts.

    Shape refusals rather than quiet skips. A requirement whose ``acceptable_items``
    is not a list of objects with string ids is a mandate the Desk cannot evaluate,
    and treating it as "accepts nothing" would turn a malformed mandate into a
    ``category_not_authorised`` refusal -- a sentence that would not be true.
    """
    requirements = constraint.get("items")
    if not isinstance(requirements, Sequence) or isinstance(requirements, str | bytes):
        raise MandateNotVerified(
            f"a {LINE_ITEMS_CONSTRAINT} constraint's items must be a list of requirements"
        )

    ids: list[str] = []
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            raise MandateNotVerified(f"a {LINE_ITEMS_CONSTRAINT} requirement must be an object")
        acceptable = requirement.get("acceptable_items")
        if not isinstance(acceptable, Sequence) or isinstance(acceptable, str | bytes):
            raise MandateNotVerified(
                f"a {LINE_ITEMS_CONSTRAINT} requirement's acceptable_items must be a list"
            )
        for item in acceptable:
            if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
                raise MandateNotVerified(
                    f"every acceptable item in a {LINE_ITEMS_CONSTRAINT} constraint "
                    f"carries a string id"
                )
            ids.append(item["id"])
    return tuple(ids)

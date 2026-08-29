"""The worked example in ticket 04's explainer, section 7, as a test.

The explainer quotes this scenario's output verbatim. A script nobody runs is how a
quoted output goes quietly stale, so it is asserted here instead: if check 3's
behaviour ever changes, this fails rather than the explainer silently starting to lie.

The whole spine, end to end, the way a real request arrives -- a principal's wallet
signs, an agent registers, check 2 verifies both mandates, check 3 evaluates a series
of requests against one ceiling. Nothing is stubbed.

To see the output rather than assert it::

    .venv/Scripts/python.exe -m pytest tests/spend/test_explainer_walkthrough.py -s
"""

from __future__ import annotations

from dataclasses import dataclass

from desk.audit import ReasonCode
from desk.identity import AgentIdentity
from desk.mandate import MandateCheck
from desk.spend import BudgetAccumulator, Money, SpendAuthorityCheck, SpendRequest
from tests.mandate.conftest import budget, line_items
from tests.spend.conftest import Presented, present
from world.agents.keys import AgentKeypair
from world.wallet import PrincipalKeypair

COFFEE = "SKU-COFFEE-1KG"
LAPTOP = "SKU-LAPTOP-14"
CEILING = "2000.00"


@dataclass(frozen=True)
class Asked:
    """What one request came back with, in the two forms the explainer shows."""

    authorised: bool
    remaining: Money | None
    reason_code: ReasonCode | None
    line: str


def _ask(
    spend: SpendAuthorityCheck,
    accumulator: BudgetAccumulator,
    presented: Presented,
    identity: AgentIdentity,
    amount: str,
    item: str = COFFEE,
) -> Asked:
    """Evaluate one request and, if it is authorised, close the deal for it.

    Closing is the separate step on purpose: evaluating draws nothing down, so a
    walkthrough that only evaluated would show the same balance five times over.
    """
    request = SpendRequest(item_id=item, amount=Money.of(amount, "INR"))
    outcome = spend.evaluate(
        request,
        presented_by=identity,
        checkout=presented.checkout,
        payment=presented.payment,
    )
    if outcome.passed:
        accumulator.record_spend(presented.payment, amount=request.amount)
        line = f"  ask {amount:>8} {item:<17} -> authorised, would leave {outcome.remaining}"
    else:
        line = f"  ask {amount:>8} {item:<17} -> refused: {outcome.reason_code}"
    print(line)
    return Asked(
        authorised=outcome.passed,
        remaining=outcome.remaining,
        reason_code=outcome.reason_code,
        line=line,
    )


def test_the_walkthrough_in_the_explainer_still_does_what_it_says(
    spend_check: SpendAuthorityCheck,
    accumulator: BudgetAccumulator,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """Four deals against one ceiling, then a request for the wrong thing.

    The third line is the one the explainer asks the reader to look at: 500 is refused
    not because 500 is large but because 1,650 has already gone, and then 350 -- a
    smaller ask -- is authorised because it fits. That is a balance behaving like a
    balance rather than a limit applied to each request separately, which is what the
    salami-slicing attack exists to defeat.
    """
    presented = present(
        mandate_check,
        wallet,
        agent,
        identity,
        checkout_constraints=[line_items(sku=COFFEE)],
        payment_constraints=[budget(CEILING, "INR")],
    )

    print(f"\nA ceiling of {CEILING} INR, drawn down across deals:")
    first = _ask(spend_check, accumulator, presented, identity, "750.00")
    second = _ask(spend_check, accumulator, presented, identity, "900.00")
    third = _ask(spend_check, accumulator, presented, identity, "500.00")
    fourth = _ask(spend_check, accumulator, presented, identity, "350.00")

    assert first.authorised and first.remaining == Money.of("1250.00", "INR")
    assert second.authorised and second.remaining == Money.of("350.00", "INR")
    assert not third.authorised
    assert third.reason_code is ReasonCode.EXCEEDS_REMAINING_BALANCE
    assert fourth.authorised and fourth.remaining == Money.of("0.00", "INR")

    print("\nThe wrong thing entirely:")
    wrong = _ask(spend_check, accumulator, presented, identity, "10.00", LAPTOP)
    assert not wrong.authorised
    assert wrong.reason_code is ReasonCode.CATEGORY_NOT_AUTHORISED


def test_the_mandate_is_untouched_by_everything_drawn_against_it(
    spend_check: SpendAuthorityCheck,
    accumulator: BudgetAccumulator,
    mandate_check: MandateCheck,
    wallet: PrincipalKeypair,
    agent: AgentKeypair,
    identity: AgentIdentity,
) -> None:
    """ADR-0004's whole claim, asserted rather than described.

    After the ceiling has been spent to the last rupee the credential still verifies,
    still identifies as the same authorisation, and is byte-for-byte what the wallet
    signed. What moved is one row in one table.
    """
    presented = present(
        mandate_check,
        wallet,
        agent,
        identity,
        checkout_constraints=[line_items(sku=COFFEE)],
        payment_constraints=[budget(CEILING, "INR")],
    )
    for amount in ("750.00", "900.00", "350.00"):
        assert _ask(spend_check, accumulator, presented, identity, amount).authorised

    reverified = mandate_check.verify_payment(presented.payment_bytes, presented_by=identity)
    ledger = accumulator.spent_against(presented.payment)

    assert reverified.passed
    assert reverified.mandate_id == presented.payment.mandate_id
    assert presented.payment_bytes == presented.payment.presentation
    assert ledger.spent == Money.of("2000.00", "INR")
    assert ledger.remaining == Money.of("0.00", "INR")
